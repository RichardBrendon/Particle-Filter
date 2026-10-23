# Executa somente o filtro C, com as mesmas opções do executor completo.
# Reutiliza menus, geração de cenário e comunicação, sem rodar a referência
# Python ou comparar os resultados ao final.

import sys
from pathlib import Path

# Permite importar Scripts a partir da raiz, mesmo executando de outro diretório.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Scripts.executar_teste import main as executar


# Apenas delega ao executor compartilhado e preserva seu código de saída.
# O firmware deve estar ativo na placa ou no Renode antes da comunicação.
def main():
    return executar(apenas_c=True)


# Executa somente pela chamada direta do arquivo, não durante a importação.
if __name__ == "__main__":
    sys.exit(main())
