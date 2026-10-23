# Executa somente a referência Python, reutilizando as sementes do resultado C.
# Exige uma execução C anterior compatível, mas não abre conexão com a placa.

import argparse
import subprocess
import sys
from pathlib import Path

# Localiza os módulos compartilhados pela raiz do projeto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Scripts.executar_teste import RAIZ_PROJETO, executar_python, resolver_cenario, inteiro_positivo


# Monta os argumentos da referência e a inicia com o mesmo interpretador.
# Retorna 0 ao concluir e 1 em erro ou cancelamento; não compara os CSVs.
def main():
    analisador = argparse.ArgumentParser(description="Executa somente a referencia Python, reutilizando as sementes do resultado C.")
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument("--cenario", help="numero, nome ou caminho do CSV usado pelo C")
    entrada.add_argument("--manual", action="store_true", help="digitar as mesmas entradas do C")
    analisador.add_argument("--resultados-c", type=Path,
                            help="registro C com entradas e sementes (padrao: Resultados/resultado_c.csv)")
    analisador.add_argument("--testes", type=inteiro_positivo, help="numero de repeticoes a conferir com o C")
    try:
        argumentos = analisador.parse_args()
    except SystemExit as erro:
        return 0 if erro.code == 0 else 1
    try:
        # Com --cenario, lê a entrada indicada; com --manual, solicita a entrada
        # na referência. Sem ambos, reproduz diretamente as entradas do C.
        referencia = []
        if argumentos.cenario:
            cenario = resolver_cenario(argumentos.cenario)
            print(f"Cenario: {cenario.name}", flush=True)
            referencia += ["--entradas", str(cenario)]
        elif not argumentos.manual:
            referencia.append("--repetir-c")
        if argumentos.testes is not None:
            referencia += ["--testes", str(argumentos.testes)]
        # Um registro C alternativo fornece as entradas e sementes. Caminhos
        # relativos são interpretados a partir da raiz, não do terminal.
        if argumentos.resultados_c:
            registro = argumentos.resultados_c
            if not registro.is_absolute():
                registro = RAIZ_PROJETO / registro
            referencia += ["--resultados-c", str(registro)]
        # A referência confere quantidade e entradas contra o registro C antes
        # de gerar resultado_python.csv com as sementes correspondentes.
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


# Propaga ao terminal o código de conclusão do executor.
if __name__ == "__main__":
    sys.exit(main())
