"""Executa o cliente UART, a referencia Python e a comparacao dos testes."""

import argparse
import csv
import math
import re
import secrets
import subprocess
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from Python.medicoes import (
    CAMPOS_MEDICAO, ESCALA_ANGULO, ESCALA_METROS, LIMITES_SENSORES, criar_medicao,
)

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
    nomes = ("esquerda", "direita", "inferior", "superior")
    while True:
        print(f"\nInforme uma unica entrada para os {quantidade} testes | Etapa 1 de 1")
        deslocamento = ler_valor("Deslocamento (m): ")
        angulo = ler_valor("Angulo do movimento (graus): ")
        sensores = [ler_valor(f"Distancia ate a parede {nome} (m): ", limite)
                    for nome, limite in zip(nomes, LIMITES_SENSORES)]
        try:
            medicao = criar_medicao(1, deslocamento, angulo, sensores)
            return medicao
        except ValueError as erro:
            print(f"Entrada invalida: {erro}. Informe novamente a entrada.")


def gerar_medicoes(quantidade):
    """Gera uma entrada compativel com o mapa e a repete em todos os testes."""
    aleatorio = secrets.SystemRandom()
    largura, altura = LIMITES_SENSORES[0], LIMITES_SENSORES[2]
    deslocamento_um = aleatorio.randint(0, 2 * ESCALA_METROS)
    angulo_mgraus = aleatorio.randrange(360 * ESCALA_ANGULO)
    deslocamento = deslocamento_um / ESCALA_METROS
    angulo = angulo_mgraus / ESCALA_ANGULO
    dx = deslocamento * math.cos(math.radians(angulo))
    dy = deslocamento * math.sin(math.radians(angulo))
    # A origem implicita e a posicao final devem caber no mapa.
    x_um = aleatorio.randint(math.ceil(max(0, dx) * ESCALA_METROS),
                             math.floor(min(largura, largura + dx) * ESCALA_METROS))
    y_um = aleatorio.randint(math.ceil(max(0, dy) * ESCALA_METROS),
                             math.floor(min(altura, altura + dy) * ESCALA_METROS))
    x, y = x_um / ESCALA_METROS, y_um / ESCALA_METROS
    medicao = criar_medicao(1, deslocamento, angulo, (x, largura - x, y, altura - y))
    return medicao


def salvar_cenario(medicao):
    diretorio = RAIZ_PROJETO / "Dados_Teste"
    diretorio.mkdir(exist_ok=True)
    numero_cenario = 1
    while True:
        caminho = diretorio / f"cenario_{numero_cenario}.csv"
        try:
            # Criacao exclusiva impede sobrescrita, inclusive em execucoes simultaneas.
            arquivo_cenario = caminho.open("x", newline="", encoding="utf-8")
            break
        except FileExistsError:
            numero_cenario += 1
    with arquivo_cenario as arquivo:
        caminho = Path(arquivo.name)
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_MEDICAO)
        escritor.writerow(medicao.campos_entrada())
    return caminho


def resolver_cenario(cenario):
    if re.fullmatch(r"\d+", cenario):
        caminho = RAIZ_PROJETO / "Dados_Teste" / f"cenario_{cenario}.csv"
    else:
        caminho = Path(cenario)
        if not caminho.suffix:
            caminho = caminho.with_suffix(".csv")
        if not caminho.is_absolute() and caminho.parent == Path("."):
            nome = caminho
            caminho = RAIZ_PROJETO / "Dados_Teste" / nome
            if not caminho.is_file() and (RAIZ_PROJETO / nome).is_file():
                caminho = RAIZ_PROJETO / nome
        elif not caminho.is_absolute():
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


def main(apenas_c=False):
    descricao = "Executa apenas o filtro C pela UART ou pelo Renode." if apenas_c else __doc__
    analisador = argparse.ArgumentParser(description=descricao)
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument("--cenario", help="identificador do cenario, nome em Dados_Teste (com ou sem .csv) ou caminho")
    entrada.add_argument("--manual", action="store_true", help="digitar as entradas uma unica vez")
    entrada.add_argument("--gerar-testes", type=inteiro_positivo, metavar="N",
                         help="gerar e salvar N testes independentes automaticamente")
    analisador.add_argument("--testes", type=inteiro_positivo, metavar="N",
                            help="quantidade de repeticoes da unica entrada do cenario")
    analisador.add_argument("--modo", type=str.lower, choices=("renode", "placa"))
    analisador.add_argument("--porta", help="porta da placa, por exemplo COM3")
    analisador.add_argument("--endereco-renode", default="localhost:12345", help="HOST:PORTA do Renode")
    try:
        argumentos = analisador.parse_args()
    except SystemExit as erro:
        return 0 if erro.code == 0 else 1
    try:
        menu = not (argumentos.cenario or argumentos.manual or argumentos.gerar_testes)
        if menu:
            escolha = escolher_opcao("Entrada dos testes:", (
                "Manual", "Executar CSV existente", "Gerar testes automaticamente"))
            if escolha == 1:
                argumentos.manual = True
            elif escolha == 2:
                argumentos.cenario = input("Cenario (numero, nome com ou sem .csv, ou caminho): ").strip()
                if argumentos.testes is None:
                    argumentos.testes = ler_quantidade()
            else:
                argumentos.gerar_testes = argumentos.testes or ler_quantidade()
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
            quantidade = argumentos.testes or ler_quantidade()
            cenario = salvar_cenario(medicoes_manuais(quantidade))
        elif argumentos.gerar_testes:
            quantidade = argumentos.gerar_testes
            if argumentos.testes is not None and argumentos.testes != quantidade:
                raise ValueError("--testes deve coincidir com --gerar-testes.")
            cenario = salvar_cenario(gerar_medicoes(quantidade))
        else:
            cenario = resolver_cenario(argumentos.cenario)
            quantidade = argumentos.testes or ler_quantidade()
        print(f"Cenario: {cenario.name}\nModo: {argumentos.modo}", flush=True)
        entradas = ["--entradas", str(cenario), "--testes", str(quantidade)]
        cliente = entradas.copy()
        if argumentos.modo == "renode":
            cliente += ["--tcp", argumentos.endereco_renode]
        elif argumentos.porta:
            cliente += ["--porta", argumentos.porta]
        executar_python("Executando o filtro C pela UART", "comunicacao_uart.py", cliente)
        if not apenas_c:
            executar_python("Executando a referencia Python", "particle_filter.py", entradas)
            executar_python("Comparando os resultados", "comparar_resultados.py")
    except subprocess.CalledProcessError:
        return 1
    except (OSError, ValueError, EOFError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
