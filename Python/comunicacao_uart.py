"""Envia medicoes ao STM32 pela UART e grava o resultado produzido pela placa."""

import argparse
import csv
import math
import socket
import sys
import time
from pathlib import Path

import numpy as np

from medicoes import (
    CAMPOS_RESULTADO,
    ESCALA_REAMOSTRAGEM,
    LIMITES_SENSORES,
    SEMENTE_REAMOSTRAGEM,
    criar_medicao,
    ler_arquivo_medicoes,
)

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


BAUD_RATE = 115200
TIMEOUT_PADRAO = 3.0
ESCALA_METROS = 1_000_000
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
ARQUIVO_RESULTADO = RAIZ_PROJETO / "Resultados" / "resultado_c.csv"
NOMES_SENSORES = (
    "parede esquerda",
    "parede direita",
    "parede inferior",
    "parede superior",
)


class ErroComunicacao(Exception):
    pass


class ConexaoTCP:
    def __init__(self, host, porta, timeout):
        self.socket = socket.create_connection((host, porta), timeout=timeout)
        self.timeout = timeout
        self.socket.settimeout(timeout)
        self.buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traceback):
        self.socket.close()

    def write(self, dados):
        self.socket.sendall(dados)

    def flush(self):
        pass

    def reset_input_buffer(self):
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
        while b"\n" not in self.buffer:
            bloco = self.socket.recv(1024)
            if not bloco:
                return b""
            self.buffer.extend(bloco)
        fim = self.buffer.index(b"\n") + 1
        linha = bytes(self.buffer[:fim])
        del self.buffer[:fim]
        return linha


def listar_portas():
    if list_ports is None:
        raise ErroComunicacao(
            "pyserial nao esta instalado. Execute: pip install pyserial"
        )
    return list(list_ports.comports())


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


def ler_numero_etapas():
    while True:
        try:
            etapas = int(input("Numero de etapas: "))
        except ValueError:
            print("Informe um numero inteiro positivo.")
            continue
        if etapas > 0:
            return etapas
        print("Informe um numero inteiro positivo.")


def receber_linha(conexao):
    resposta = conexao.readline()
    if not resposta:
        raise ErroComunicacao("Tempo esgotado aguardando resposta da placa.")
    try:
        return resposta.decode("ascii").strip()
    except UnicodeDecodeError as erro:
        raise ErroComunicacao("A placa enviou uma resposta nao ASCII.") from erro


def enviar_comando(conexao, comando):
    conexao.write((comando + "\n").encode("ascii"))
    conexao.flush()
    resposta = receber_linha(conexao)
    if resposta.startswith("ERROR,"):
        raise ErroComunicacao(f"Erro informado pela placa: {resposta}")
    return resposta


def sincronizar(conexao):
    conexao.reset_input_buffer()
    resposta = enviar_comando(conexao, "RESET")
    if resposta != "READY":
        raise ErroComunicacao(f"Esperado READY, recebido: {resposta}")


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


def executar(porta_serial, endereco_tcp, timeout, arquivo_entradas=None):
    medicoes = ler_arquivo_medicoes(arquivo_entradas) if arquivo_entradas else None
    numero_etapas = len(medicoes) if medicoes else ler_numero_etapas()
    ARQUIVO_RESULTADO.parent.mkdir(exist_ok=True)
    conexao, descricao = abrir_conexao(porta_serial, endereco_tcp, timeout)

    with conexao:
        time.sleep(0.2)
        sincronizar(conexao)
        largura, altura, particulas, sensores_configurados = obter_info(conexao)
        np.random.seed(SEMENTE_REAMOSTRAGEM)
        print("Filtro de Particulas em C")
        print(f"Mapa: {largura:.1f} m x {altura:.1f} m")
        print(f"Particulas: {particulas} | Sensores: {sensores_configurados}")
        print(f"Conectado a {descricao}.")

        with ARQUIVO_RESULTADO.open("w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(CAMPOS_RESULTADO)

            for etapa in range(1, numero_etapas + 1):
                print(f"\nEtapa {etapa} de {numero_etapas}")
                if medicoes:
                    medicao = medicoes[etapa - 1]
                else:
                    deslocamento = ler_float("Deslocamento (m): ")
                    angulo = ler_float("Angulo do movimento (graus): ")
                    sensores = [
                        ler_float(
                            f"Distancia medida ate a {nome} (m): ", 0.0, limite
                        )
                        for nome, limite in zip(NOMES_SENSORES, LIMITES_SENSORES)
                    ]
                    medicao = criar_medicao(etapa, deslocamento, angulo, sensores)

                # O FilterPy consumira o mesmo sorteio na etapa correspondente.
                amostra_u53 = int(np.random.random() * ESCALA_REAMOSTRAGEM)
                campos = [
                    "STEP",
                    str(etapa),
                    str(medicao.deslocamento_um),
                    str(medicao.angulo_mgraus),
                    *(str(valor) for valor in medicao.sensores_um),
                    str(amostra_u53),
                ]
                resposta = enviar_comando(conexao, ",".join(campos))
                resultado = processar_resposta(resposta, etapa)
                escritor.writerow(
                    (*medicao.campos_entrada(), amostra_u53,
                     *(f"{valor:.6f}" for valor in resultado[1:]))
                )
                arquivo.flush()
                print(
                    "Posicao estimada: "
                    f"({resultado[3]:.6f}, {resultado[4]:.6f}) m"
                )

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
    return analisador.parse_args()


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
        executar(argumentos.porta, argumentos.tcp, argumentos.timeout, argumentos.entradas)
    except (OSError, ValueError, ErroComunicacao) as erro:
        print(f"Erro: {erro}")
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
