# Lista as portas seriais pelo cliente UART do projeto.
# Reutiliza --listar-portas para manter a detecção em um único lugar;
# não inicia testes nem envia comandos ao filtro.

import subprocess
import sys
from pathlib import Path


# Localiza o cliente pela raiz e o executa com o mesmo interpretador usado aqui.
# Propaga seu código de saída; falha ao iniciar retorna 2 e cancelamento retorna
# 130. A listagem depende do pyserial instalado nesse interpretador.
def main():
    cliente = Path(__file__).resolve().parent.parent / "Python" / "comunicacao_uart.py"
    try:
        return subprocess.run([sys.executable, str(cliente), "--listar-portas"]).returncode
    except OSError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


# Executa apenas na chamada direta e informa o código de saída ao terminal.
if __name__ == "__main__":
    sys.exit(main())
