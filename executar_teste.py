"""Executa o cliente UART, a referencia Python e a comparacao dos testes."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parent


def resolver_cenario(cenario):
    if re.fullmatch(r"\d+(-\d+)?", cenario):
        sufixo = "teste" if cenario == "1" else "testes"
        caminho = RAIZ_PROJETO / "Dados_Teste" / f"cenario_{cenario}_{sufixo}.csv"
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
    analisador.add_argument("--cenario", required=True, help="numero, variante ou caminho do CSV")
    analisador.add_argument("--modo", type=str.lower, choices=("renode", "placa"), default="renode")
    analisador.add_argument("--porta", help="porta da placa, por exemplo COM3")
    analisador.add_argument("--endereco-renode", default="localhost:12345", help="HOST:PORTA do Renode")
    argumentos = analisador.parse_args()
    if argumentos.modo == "renode" and argumentos.porta:
        analisador.error("Use --porta somente com --modo placa.")

    try:
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
    except (OSError, ValueError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
