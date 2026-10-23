"""Lista as portas seriais pelo cliente UART do projeto."""

import subprocess
import sys
from pathlib import Path


def main():
    cliente = Path(__file__).resolve().parent.parent / "Python" / "comunicacao_uart.py"
    try:
        return subprocess.run([sys.executable, str(cliente), "--listar-portas"]).returncode
    except OSError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
