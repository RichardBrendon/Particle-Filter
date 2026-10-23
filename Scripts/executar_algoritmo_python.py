"""Executa somente a referencia Python, reutilizando as sementes do resultado C."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Scripts.executar_teste import RAIZ_PROJETO, executar_python, resolver_cenario


def main():
    analisador = argparse.ArgumentParser(description=__doc__)
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument("--cenario", help="numero, nome ou caminho do CSV usado pelo C")
    entrada.add_argument("--manual", action="store_true", help="digitar as mesmas entradas do C")
    analisador.add_argument("--resultados-c", type=Path,
                            help="registro C com entradas e sementes (padrao: Resultados/resultado_c.csv)")
    try:
        argumentos = analisador.parse_args()
    except SystemExit as erro:
        return 0 if erro.code == 0 else 1
    try:
        referencia = []
        if argumentos.cenario:
            cenario = resolver_cenario(argumentos.cenario)
            print(f"Cenario: {cenario.name}", flush=True)
            referencia += ["--entradas", str(cenario)]
        elif not argumentos.manual:
            referencia.append("--repetir-c")
        if argumentos.resultados_c:
            registro = argumentos.resultados_c
            if not registro.is_absolute():
                registro = RAIZ_PROJETO / registro
            referencia += ["--resultados-c", str(registro)]
        executar_python("Executando a referencia Python", "particle_filter.py", referencia)
    except subprocess.CalledProcessError:
        return 1
    except (OSError, ValueError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
