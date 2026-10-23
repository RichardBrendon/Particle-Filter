# Cliente de comunicação com o filtro C na placa ou no Renode.
# Envia uma mesma entrada em N testes independentes de uma etapa, recebe as
# posições e grava resultado_c.csv. O algoritmo do filtro é executado no
# firmware; este script cuida do transporte, do protocolo e dos arquivos.

import argparse
import csv
import math
import secrets
import socket
import sys
import time
from pathlib import Path

from medicoes import (
    CAMPOS_RESULTADO,
    LIMITES_SENSORES,
    criar_medicao,
    ler_arquivo_medicoes,
    repetir_medicao,
)

# A dependência pyserial é necessária apenas para comunicação serial e
# listagem de portas. O transporte TCP pode funcionar sem essa biblioteca.
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


# Parâmetros compartilhados com o firmware: UART a 115200 baud e distâncias
# transmitidas como inteiros em micrômetros. O timeout é dado em segundos.
BAUD_RATE = 115200
TIMEOUT_PADRAO = 3.0
ESCALA_METROS = 1_000_000
# Caminho absoluto baseado no script, não no diretório de execução do terminal.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
ARQUIVO_RESULTADO = RAIZ_PROJETO / "Resultados" / "resultado_c.csv"
NOMES_SENSORES = (
    "parede esquerda",
    "parede direita",
    "parede inferior",
    "parede superior",
)


# Distingue falhas de protocolo ou configuração das respostas válidas do filtro.
class ErroComunicacao(Exception):
    pass


# Adaptador para o socket do Renode com os métodos usados na conexão serial.
# Permite reutilizar o mesmo protocolo nos dois transportes. TCP é um fluxo
# de bytes: os blocos recebidos não correspondem necessariamente às linhas.
class ConexaoTCP:
    def __init__(self, host, porta, timeout):
        self.socket = socket.create_connection((host, porta), timeout=timeout)
        self.timeout = timeout
        self.socket.settimeout(timeout)
        self.buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        # O bloco with fecha o socket mesmo quando ocorre uma exceção.
        self.socket.close()

    def write(self, dados):
        self.socket.sendall(dados)

    def flush(self):
        # sendall já encaminha os dados ao socket; não há buffer de escrita
        # adicional mantido por este adaptador para descarregar aqui.
        pass

    def reset_input_buffer(self):
        # Descarta dados antigos do buffer local e os disponíveis no socket.
        # A leitura não bloqueante evita esperar por novos dados nessa limpeza;
        # ao terminar, restaura o timeout configurado para as leituras normais.
        self.buffer.clear()
        self.socket.setblocking(False)
        try:
            while self.socket.recv(1024):
                pass
        except BlockingIOError:
            pass
        finally:
            self.socket.settimeout(self.timeout)

    def readline(self):
        # Acumula blocos até encontrar LF e preserva os bytes da próxima linha.
        # Retorna bytes vazios se o servidor encerrar antes de completar a linha;
        # um timeout do socket gera exceção, tratada no fluxo principal.
        while b"\n" not in self.buffer:
            bloco = self.socket.recv(1024)
            if not bloco:
                return b""
            self.buffer.extend(bloco)
        fim = self.buffer.index(b"\n") + 1
        linha = bytes(self.buffer[:fim])
        del self.buffer[:fim]
        return linha


# Consulta as portas disponíveis no sistema, com dispositivo e descrição.
# Também é reutilizada pelo script dedicado à listagem de portas.
def listar_portas():
    if list_ports is None:
        raise ErroComunicacao(
            "pyserial nao esta instalado. Execute: pip install pyserial"
        )
    return list(list_ports.comports())


# Prioriza a porta explícita. Sem ela, escolhe uma única candidata ST-LINK ou,
# na ausência dessa escolha inequívoca, a única porta disponível no sistema.
# Se houver ambiguidade ou nenhuma porta, solicita seleção via --porta.
def escolher_porta(porta_informada):
    if serial is None:
        raise ErroComunicacao(
            "pyserial nao esta instalado. Execute: pip install pyserial"
        )
    if porta_informada:
        return porta_informada

    portas = listar_portas()
    candidatas_stlink = [
        porta for porta in portas
        if "stlink" in porta.description.lower()
        or "st-link" in porta.description.lower()
    ]
    if len(candidatas_stlink) == 1:
        return candidatas_stlink[0].device
    if len(portas) == 1:
        return portas[0].device

    disponiveis = ", ".join(
        f"{porta.device} ({porta.description})" for porta in portas
    ) or "nenhuma"
    raise ErroComunicacao(
        "Nao foi possivel escolher a porta automaticamente. "
        f"Portas encontradas: {disponiveis}. Use --porta COMx."
    )


# Repete a solicitação até receber um número finito dentro dos limites
# opcionais. Os limites são inclusivos e usam a unidade do valor solicitado.
def ler_float(mensagem, minimo=None, maximo=None):
    while True:
        try:
            valor = float(input(mensagem))
        except ValueError:
            print("Informe um numero valido.")
            continue
        if not math.isfinite(valor):
            print("O valor deve ser finito.")
            continue
        if minimo is not None and valor < minimo:
            print(f"O valor minimo e {minimo}.")
            continue
        if maximo is not None and valor > maximo:
            print(f"O valor maximo e {maximo}.")
            continue
        return valor


# A quantidade de testes é escolhida separadamente da entrada e do nome do CSV.
def ler_numero_testes():
    while True:
        try:
            testes = int(input("Numero de testes: "))
        except ValueError:
            print("Informe um numero inteiro positivo.")
            continue
        if testes > 0:
            return testes
        print("Informe um numero inteiro positivo.")


# Decodifica uma resposta do protocolo, que usa apenas caracteres ASCII.
# Na serial, uma leitura vazia normalmente indica timeout; no adaptador TCP,
# também pode indicar que o servidor encerrou a conexão.
def receber_linha(conexao):
    resposta = conexao.readline()
    if not resposta:
        raise ErroComunicacao("Tempo esgotado aguardando resposta da placa.")
    try:
        return resposta.decode("ascii").strip()
    except UnicodeDecodeError as erro:
        raise ErroComunicacao("A placa enviou uma resposta nao ASCII.") from erro


# Troca síncrona: envia um comando terminado em LF e espera uma resposta.
# ERROR indica rejeição pelo firmware e interrompe a execução no cliente.
def enviar_comando(conexao, comando):
    conexao.write((comando + "\n").encode("ascii"))
    conexao.flush()
    resposta = receber_linha(conexao)
    if resposta.startswith("ERROR,"):
        raise ErroComunicacao(f"Erro informado pela placa: {resposta}")
    return resposta


# Limpa respostas antigas e confirma o protocolo com RESET sem semente.
# Esse RESET usa a semente padrão do firmware; cada teste envia outro RESET
# com sua própria semente antes de executar a etapa.
def sincronizar(conexao):
    conexao.reset_input_buffer()
    resposta = enviar_comando(conexao, "RESET")
    if resposta != "READY":
        raise ErroComunicacao(f"Esperado READY, recebido: {resposta}")


# Consulta INFO,largura,altura,particulas,sensores e valida formato e valores.
# As dimensões vêm em micrômetros e são convertidas em metros para exibição.
def obter_info(conexao):
    resposta = enviar_comando(conexao, "INFO")
    campos = resposta.split(",")
    if len(campos) != 5 or campos[0] != "INFO":
        raise ErroComunicacao(f"Resposta INFO invalida: {resposta}")
    try:
        largura_um, altura_um, particulas, sensores = map(int, campos[1:])
    except ValueError as erro:
        raise ErroComunicacao(f"Resposta INFO invalida: {resposta}") from erro
    if min(largura_um, altura_um, particulas, sensores) <= 0:
        raise ErroComunicacao(f"Resposta INFO invalida: {resposta}")
    return largura_um / ESCALA_METROS, altura_um / ESCALA_METROS, particulas, sensores


# Valida RESULT,etapa,x_medido,y_medido,x_estimado,y_estimado e converte as
# coordenadas inteiras em metros. Conferir a etapa evita aceitar uma resposta
# identificada como outra etapa; o identificador do teste fica no cliente.
def processar_resposta(resposta, etapa_esperada):
    campos = resposta.split(",")
    if len(campos) != 6 or campos[0] != "RESULT":
        raise ErroComunicacao(f"Resposta invalida: {resposta}")
    try:
        etapa = int(campos[1])
        valores = [int(campo) / ESCALA_METROS for campo in campos[2:]]
    except ValueError as erro:
        raise ErroComunicacao(f"Resposta invalida: {resposta}") from erro
    if etapa != etapa_esperada:
        raise ErroComunicacao(
            f"Etapa inesperada: esperado {etapa_esperada}, recebido {etapa}."
        )
    return (etapa, *valores)


# Seleciona TCP quando --tcp foi informado; caso contrário, abre a serial.
# O retorno contém a conexão e uma descrição para o terminal. Os dois objetos
# suportam with, garantindo fechamento ao sair do bloco de execução.
def abrir_conexao(porta_serial, endereco_tcp, timeout):
    if endereco_tcp:
        host, separador, porta_texto = endereco_tcp.rpartition(":")
        if not separador or not host:
            raise ErroComunicacao("Use --tcp no formato HOST:PORTA.")
        try:
            porta_tcp = int(porta_texto)
        except ValueError as erro:
            raise ErroComunicacao("A porta TCP deve ser um numero inteiro.") from erro
        if not 1 <= porta_tcp <= 65535:
            raise ErroComunicacao("A porta TCP deve estar entre 1 e 65535.")
        return ConexaoTCP(host, porta_tcp, timeout), f"TCP {host}:{porta_tcp}"

    porta = escolher_porta(porta_serial)
    return serial.Serial(porta, BAUD_RATE, timeout=timeout), porta


# Prepara uma única entrada, repete-a N vezes e coordena os testes no firmware.
# O resultado registra a semente de cada teste para reprodução pelo Python.
# Exceções interrompem a execução e são apresentadas pelo chamador.
def executar(porta_serial, endereco_tcp, timeout, arquivo_entradas=None, numero_testes=None):
    medicoes = ler_arquivo_medicoes(arquivo_entradas) if arquivo_entradas else None
    if numero_testes is None:
        numero_testes = ler_numero_testes()
    if numero_testes <= 0:
        raise ValueError("O numero de testes deve ser positivo.")
    # Um cenário fornece apenas uma linha; no modo manual os valores também
    # são solicitados uma única vez. Apenas o identificador muda nas repetições.
    if medicoes:
        medicoes = repetir_medicao(medicoes[0], numero_testes)
    else:
        print(f"Informe uma unica entrada para os {numero_testes} testes.")
        deslocamento = ler_float("Deslocamento (m): ")
        angulo = ler_float("Angulo do movimento (graus): ")
        sensores = [
            ler_float(f"Distancia medida ate a {nome} (m): ", 0.0, limite)
            for nome, limite in zip(NOMES_SENSORES, LIMITES_SENSORES)
        ]
        medicoes = repetir_medicao(criar_medicao(1, deslocamento, angulo, sensores), numero_testes)
    ARQUIVO_RESULTADO.parent.mkdir(exist_ok=True)
    conexao, descricao = abrir_conexao(porta_serial, endereco_tcp, timeout)

    with conexao:
        # Dá um breve intervalo antes de limpar os dados e sincronizar.
        # READY confirma o atendimento do RESET, não depende apenas da espera.
        time.sleep(0.2)
        sincronizar(conexao)
        largura, altura, particulas, sensores_configurados = obter_info(conexao)
        print("Filtro de Particulas em C")
        print(f"Mapa: {largura:.1f} m x {altura:.1f} m")
        print(f"Particulas: {particulas} | Sensores: {sensores_configurados}")
        print(f"Conectado a {descricao}.")

        # Sobrescreve o resultado anterior após sincronização e consulta INFO.
        # Se houver interrupção, o CSV poderá conter apenas os testes concluídos.
        with ARQUIVO_RESULTADO.open("w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(CAMPOS_RESULTADO)

            for teste in range(1, numero_testes + 1):
                print(f"\nTeste {teste} de {numero_testes} | Etapa 1 de 1")
                medicao = medicoes[teste - 1]

                # Sorteia no PC uma semente sem sinal de 32 bits. O RESET a
                # envia ao C; o CSV permite que a referência use o mesmo valor.
                # O sorteio não garante sementes distintas em todos os testes.
                semente = secrets.randbits(32)
                if enviar_comando(conexao, f"RESET,{semente}") != "READY":
                    raise ErroComunicacao("O firmware nao confirmou o reinicio do teste.")
                # STEP sempre usa etapa 1: cada teste começa com filtro novo.
                # As unidades inteiras já foram preparadas pelo módulo medicoes.
                campos = [
                    "STEP",
                    "1",
                    str(medicao.deslocamento_um),
                    str(medicao.angulo_mgraus),
                    *(str(valor) for valor in medicao.sensores_um),
                ]
                resposta = enviar_comando(conexao, ",".join(campos))
                resultado = processar_resposta(resposta, 1)
                # Preserva a entrada e a semente junto às coordenadas recebidas.
                # Seis casas decimais em metros correspondem a micrômetros.
                escritor.writerow(
                    (*medicao.campos_entrada(), semente,
                     *(f"{valor:.6f}" for valor in resultado[1:]))
                )
                # Descarrega o buffer Python a cada teste; não equivale a uma
                # garantia de gravação física no disco em caso de queda de energia.
                arquivo.flush()
                print(
                    "Posicao estimada: "
                    f"({resultado[3]:.6f}, {resultado[4]:.6f}) m"
                )

# Define a interface de linha de comando. Serial e TCP são alternativas;
# --listar-portas permite consultar dispositivos sem executar o filtro.
def criar_argumentos():
    analisador = argparse.ArgumentParser(
        description="Envia medicoes para a NUCLEO-F030R8 pela USART2."
    )
    transporte = analisador.add_mutually_exclusive_group()
    transporte.add_argument("--porta", help="porta serial, por exemplo COM4")
    transporte.add_argument(
        "--tcp",
        help="socket TCP exposto pelo Renode, por exemplo localhost:12345",
    )
    analisador.add_argument(
        "--timeout",
        type=float,
        default=TIMEOUT_PADRAO,
        help=f"timeout da UART em segundos (padrao: {TIMEOUT_PADRAO})",
    )
    analisador.add_argument(
        "--entradas",
        type=Path,
        help="CSV com as mesmas medicoes usadas pela referencia Python",
    )
    analisador.add_argument(
        "--listar-portas",
        action="store_true",
        help="lista as portas seriais e encerra",
    )
    analisador.add_argument("--testes", type=int, help="numero de repeticoes da unica entrada")
    return analisador.parse_args()


# Seleciona listagem ou execução e traduz falhas em códigos de saída:
# 0 = conclusão normal; 1 = falha de execução; 2 = timeout inválido;
# 130 = cancelamento por teclado. Erros de argumentos também são tratados
# pelo argparse antes de iniciar a comunicação.
def main():
    argumentos = criar_argumentos()
    if argumentos.listar_portas:
        portas = listar_portas()
        if not portas:
            print("Nenhuma porta serial encontrada.")
        for porta in portas:
            print(f"{porta.device}: {porta.description}")
        return 0
    if not math.isfinite(argumentos.timeout) or argumentos.timeout <= 0.0:
        print("Erro: o timeout deve ser um numero positivo.")
        return 2

    try:
        executar(argumentos.porta, argumentos.tcp, argumentos.timeout,
                 argumentos.entradas, argumentos.testes)
    except (OSError, ValueError, ErroComunicacao) as erro:
        print(f"Erro: {erro}")
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.")
        return 130
    return 0


# Executa apenas quando chamado como programa e devolve o código ao terminal.
if __name__ == "__main__":
    sys.exit(main())
