"""Executa somente a comparacao dos CSVs existentes em Resultados."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Scripts.executar_teste import executar_python


def main():
    try:
        executar_python("Comparando os resultados", "comparar_resultados.py", sys.argv[1:])
    except subprocess.CalledProcessError:
        return 1
    except OSError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
