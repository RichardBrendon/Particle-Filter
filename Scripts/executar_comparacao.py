# Executa somente a comparação dos CSVs existentes em Resultados/.
# Não executa os filtros, não gera entradas e não modifica os resultados.

import subprocess
import sys
from pathlib import Path

# Permite reutilizar o lançador compartilhado na pasta Scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Scripts.executar_teste import executar_python


# Encaminha os argumentos recebidos, como --tolerancia, diretamente ao comparador.
# Retorna 1 em falha de execução ou cancelamento. Testes reprovados não são
# falhas de execução quando o comparador consegue concluir o relatório.
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


# Devolve o código de conclusão ao terminal.
if __name__ == "__main__":
    sys.exit(main())
