"""Executa o cliente UART, a referencia Python e a comparacao dos testes."""

import argparse
import csv
import math
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from Python.medicoes import (
    CAMPOS_MEDICAO, ESCALA_ANGULO, ESCALA_METROS, LIMITES_SENSORES, criar_medicao,
)

RAIZ_PROJETO = Path(__file__).resolve().parent


def inteiro_positivo(texto):
    try:
        valor = int(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError("Informe um numero inteiro positivo.") from erro
    if valor <= 0:
        raise argparse.ArgumentTypeError("Informe um numero inteiro positivo.")
    return valor


def ler_quantidade():
    while True:
        try:
            return inteiro_positivo(input("Numero de testes: ").strip())
        except argparse.ArgumentTypeError as erro:
            print(erro)


def escolher_opcao(titulo, opcoes):
    print(titulo)
    for numero, descricao in enumerate(opcoes, start=1):
        print(f"{numero} - {descricao}")
    while True:
        escolha = input("Opcao: ").strip()
        if escolha in {str(i) for i in range(1, len(opcoes) + 1)}:
            return int(escolha)
        print("Escolha uma das opcoes listadas.")


def ler_valor(mensagem, limite=None):
    while True:
        try:
            valor = float(input(mensagem))
            if not math.isfinite(valor):
                raise ValueError
            if limite is not None and not 0 <= valor <= limite:
                raise ValueError
            return valor
        except ValueError:
            print(f"Informe um numero finito entre 0 e {limite}." if limite is not None
                  else "Informe um numero finito.")


def medicoes_manuais(quantidade):
    medicoes = []
    nomes = ("esquerda", "direita", "inferior", "superior")
    for teste in range(1, quantidade + 1):
        while True:
            print(f"\nEntradas do teste {teste} de {quantidade} | Etapa 1 de 1")
            deslocamento = ler_valor("Deslocamento (m): ")
            angulo = ler_valor("Angulo do movimento (graus): ")
            sensores = [ler_valor(f"Distancia ate a parede {nome} (m): ", limite)
                        for nome, limite in zip(nomes, LIMITES_SENSORES)]
            try:
                medicoes.append(criar_medicao(teste, deslocamento, angulo, sensores))
                break
            except ValueError as erro:
                print(f"Entrada invalida: {erro}. Informe novamente este teste.")
    return medicoes


def gerar_medicoes(quantidade):
    """Gera sensores ideais e movimentos de 0 a 2 m compativeis com o mapa."""
    aleatorio = secrets.SystemRandom()
    largura, altura = LIMITES_SENSORES[0], LIMITES_SENSORES[2]
    for teste in range(1, quantidade + 1):
        deslocamento_um = aleatorio.randint(0, 2 * ESCALA_METROS)
        angulo_mgraus = aleatorio.randrange(360 * ESCALA_ANGULO)
        deslocamento = deslocamento_um / ESCALA_METROS
        angulo = angulo_mgraus / ESCALA_ANGULO
        dx = deslocamento * math.cos(math.radians(angulo))
        dy = deslocamento * math.sin(math.radians(angulo))
        # Escolhe a posicao final de modo que a origem implicita tambem caiba
        # no mapa, sem relacionar o teste com qualquer linha anterior.
        x_um = aleatorio.randint(math.ceil(max(0, dx) * ESCALA_METROS),
                                 math.floor(min(largura, largura + dx) * ESCALA_METROS))
        y_um = aleatorio.randint(math.ceil(max(0, dy) * ESCALA_METROS),
                                 math.floor(min(altura, altura + dy) * ESCALA_METROS))
        x, y = x_um / ESCALA_METROS, y_um / ESCALA_METROS
        yield criar_medicao(teste, deslocamento, angulo,
                            (x, largura - x, y, altura - y))


def salvar_cenario(medicoes, quantidade, origem):
    diretorio = RAIZ_PROJETO / "Dados_Teste"
    diretorio.mkdir(exist_ok=True)
    if origem == "gerado":
        numero_cenario = 1
        while True:
            identificador = str(quantidade) if numero_cenario == 1 else f"{quantidade}-{numero_cenario}"
            caminho = diretorio / f"cenario_{identificador}_testes.csv"
            try:
                # Criacao exclusiva impede sobrescrita, inclusive em execucoes simultaneas.
                arquivo_cenario = caminho.open("x", newline="", encoding="utf-8")
                break
            except FileExistsError:
                numero_cenario += 1
    else:
        arquivo_cenario = tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=diretorio,
            prefix=f"cenario_{quantidade}_testes_{origem}_", suffix=".csv", delete=False,
        )
    with arquivo_cenario as arquivo:
        caminho = Path(arquivo.name)
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_MEDICAO)
        for medicao in medicoes:
            escritor.writerow(medicao.campos_entrada())
    return caminho


def resolver_cenario(cenario):
    if re.fullmatch(r"\d+(-\d+)?", cenario):
        caminho = RAIZ_PROJETO / "Dados_Teste" / f"cenario_{cenario}_testes.csv"
        if cenario == "1" and not caminho.is_file():
            caminho = RAIZ_PROJETO / "Dados_Teste" / "cenario_1_teste.csv"
    else:
        caminho = Path(cenario)
        if not caminho.is_absolute():
            caminho = RAIZ_PROJETO / caminho
    if not caminho.is_file():
        raise ValueError(f"Cenario nao encontrado: {caminho}")
    return caminho.resolve()


def executar_python(descricao, arquivo, argumentos=()):
    print(f"\n== {descricao} ==", flush=True)
    subprocess.run(
        [sys.executable, str(RAIZ_PROJETO / "Python" / arquivo), *argumentos],
        check=True,
    )


def main():
    analisador = argparse.ArgumentParser(description=__doc__)
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument("--cenario", help="numero, variante ou caminho do CSV")
    entrada.add_argument("--manual", action="store_true", help="digitar as entradas uma unica vez")
    entrada.add_argument("--gerar-testes", type=inteiro_positivo, metavar="N",
                         help="gerar e salvar N testes independentes automaticamente")
    analisador.add_argument("--modo", type=str.lower, choices=("renode", "placa"))
    analisador.add_argument("--porta", help="porta da placa, por exemplo COM3")
    analisador.add_argument("--endereco-renode", default="localhost:12345", help="HOST:PORTA do Renode")
    argumentos = analisador.parse_args()
    try:
        menu = not (argumentos.cenario or argumentos.manual or argumentos.gerar_testes)
        if menu:
            escolha = escolher_opcao("Entrada dos testes:", (
                "Manual", "Executar CSV existente", "Gerar testes automaticamente"))
            if escolha == 1:
                argumentos.manual = True
            elif escolha == 2:
                argumentos.cenario = input("Cenario (numero, variante ou caminho): ").strip()
            else:
                argumentos.gerar_testes = ler_quantidade()
        if argumentos.modo is None:
            if menu:
                destino = escolher_opcao("Onde executar o filtro C:", ("Renode", "Placa"))
                argumentos.modo = "renode" if destino == 1 else "placa"
            else:
                argumentos.modo = "renode"
        if argumentos.modo == "renode" and argumentos.porta:
            raise ValueError("Use --porta somente com --modo placa.")
        if menu and argumentos.modo == "placa" and not argumentos.porta:
            argumentos.porta = input("Porta (ex.: COM3; Enter para detectar): ").strip()
        if argumentos.manual:
            quantidade = ler_quantidade()
            cenario = salvar_cenario(medicoes_manuais(quantidade), quantidade, "manual")
        elif argumentos.gerar_testes:
            quantidade = argumentos.gerar_testes
            cenario = salvar_cenario(gerar_medicoes(quantidade), quantidade, "gerado")
        else:
            cenario = resolver_cenario(argumentos.cenario)
        print(f"Cenario: {cenario}\nModo: {argumentos.modo}", flush=True)
        cliente = ["--entradas", str(cenario)]
        if argumentos.modo == "renode":
            cliente += ["--tcp", argumentos.endereco_renode]
        elif argumentos.porta:
            cliente += ["--porta", argumentos.porta]
        executar_python("Executando o filtro C pela UART", "comunicacao_uart.py", cliente)
        executar_python("Executando a referencia Python", "particle_filter.py", ["--entradas", str(cenario)])
        executar_python("Comparando os resultados", "comparar_resultados.py")
    except subprocess.CalledProcessError as erro:
        print(f"Teste interrompido: programa encerrou com codigo {erro.returncode}.", file=sys.stderr)
        return erro.returncode
    except (OSError, ValueError, EOFError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
