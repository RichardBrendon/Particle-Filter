# Compara os resultados da implementação C com a referência Python.
# Cada linha representa um teste independente de uma etapa. A aprovação exige
# concordância das entradas e sementes, consistência dos valores medidos e
# estimados e diferença euclidiana dentro da tolerância configurada.

import argparse
import csv
import math
import sys
from itertools import zip_longest
from pathlib import Path

from medicoes import (
    CAMPOS_MEDICAO,
    CAMPOS_RESULTADO,
    ESCALA_METROS,
    LIMITES_SENSORES,
)


# Localiza os resultados na raiz do projeto, independentemente do diretório
# em que o comando foi executado. Este script apenas lê os CSVs existentes.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIRETORIO_RESULTADOS = RAIZ_PROJETO / "Resultados"
ARQUIVO_C = DIRETORIO_RESULTADOS / "resultado_c.csv"
ARQUIVO_PYTHON = DIRETORIO_RESULTADOS / "resultado_python.csv"

# Exclui o identificador: ele é verificado separadamente das entradas físicas.
CAMPOS_ENTRADA = CAMPOS_MEDICAO[1:]
# Limite em metros para a diferença entre posições estimadas. Zero exige
# igualdade dos valores lidos dos CSVs, não dos valores internos antes da saída.
TOLERANCIA_TESTE = 0.0
# Verificação separada das posições medidas, em micrômetros inteiros.
# Esse limite não é a tolerância das estimativas; acomoda arredondamentos na
# conversão das leituras dos sensores para as coordenadas medidas.
TOLERANCIA_MEDIDO_UM = 1
MAPA_LARGURA = 10.0
MAPA_ALTURA = 8.0


# Indica que os arquivos não podem ser comparados por ausência ou formato
# inválido, situação diferente de um teste válido que apresentou divergência.
class ErroComparacao(Exception):
    pass


# Converte metros à unidade inteira do protocolo UART para verificar as
# posições medidas. round usa empate para o inteiro par mais próximo.
def em_micrometros(valor):
    return round(valor * ESCALA_METROS)


# Lê um resultado e valida cabeçalho, campos numéricos, sequência dos testes,
# semente de 32 bits e limites individuais das distâncias dos sensores.
# Retorna uma lista de dicionários, mantendo a ordem das linhas do arquivo.
def ler_resultados(caminho):
    if not caminho.is_file():
        raise ErroComparacao(f"Arquivo nao encontrado: {caminho}")

    resultados = []
    # Aceita UTF-8 com ou sem BOM; exige os nomes e a ordem do formato atual.
    with caminho.open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_RESULTADO:
            raise ErroComparacao(
                f"Cabecalho invalido em {caminho.name}. "
                f"Esperado: {','.join(CAMPOS_RESULTADO)}. "
                "Gere novamente os resultados com os programas atualizados."
            )

        # A linha 1 contém o cabeçalho; a numeração identifica erros de leitura.
        for numero_linha, linha in enumerate(leitor, start=2):
            try:
                resultado = {
                    "teste": int(linha["teste"]),
                    "semente": int(linha["semente"]),
                }
                resultado.update(
                    (campo, float(linha[campo]))
                    for campo in CAMPOS_RESULTADO[1:]
                    if campo != "semente"
                )
            except (TypeError, ValueError) as erro:
                raise ErroComparacao(
                    f"Valor invalido em {caminho.name}, linha {numero_linha}."
                ) from erro

            # Rejeita NaN e infinitos antes das comparações: não representam
            # coordenadas ou entradas válidas para este teste de equivalência.
            if not all(math.isfinite(resultado[campo]) for campo in CAMPOS_RESULTADO[1:]):
                raise ErroComparacao(
                    f"Valor nao finito em {caminho.name}, linha {numero_linha}."
                )
            if resultado["teste"] != len(resultados) + 1:
                raise ErroComparacao(
                    f"Testes fora de sequencia em {caminho.name}, linha {numero_linha}."
                )
            if not 0 <= resultado["semente"] <= 0xFFFFFFFF:
                raise ErroComparacao(f"Semente invalida em {caminho.name}, linha {numero_linha}.")
            for campo, limite in zip(CAMPOS_ENTRADA[2:], LIMITES_SENSORES):
                if not 0.0 <= resultado[campo] <= limite:
                    raise ErroComparacao(
                        f"{campo} fora do mapa em {caminho.name}, linha {numero_linha}."
                    )
            resultados.append(resultado)

    if not resultados:
        raise ErroComparacao(f"{caminho.name} nao possui testes para comparar.")
    return resultados


# Verifica cada par de resultados e apresenta PASSOU ou FALHOU por teste.
# Mantém motivos internamente, sem imprimi-los; retorna True apenas quando
# não há falhas. Um teste conta uma única vez no total, mesmo com vários erros.
def comparar(resultados_c, resultados_python, tolerancia):
    falhas = []
    distancias = []
    total_passou = 0
    total_falhou = 0

    print(f"\nTeste | {'Diferença C x Python':^20} | Resultado")
    print("------|----------------------|----------")

    # zip_longest também examina linhas sem par quando os tamanhos diferem.
    # Nesse caso há falha, mas não é possível calcular a diferença de posição.
    for c, python in zip_longest(resultados_c, resultados_python):
        if c is None or python is None:
            teste = (python if c is None else c)["teste"]
            origem = "C" if c is None else "Python"
            motivo = f"Teste {teste}: resultado ausente em {origem}."
            print(f"{teste:5d} | {'---':^20} | FALHOU")
            falhas.append(motivo)
            total_falhou += 1
            continue
        etapa_c = c["teste"]
        etapa_python = python["teste"]
        problemas_etapa = []

        if etapa_c != etapa_python:
            problemas_etapa.append(
                f"indices diferentes (C={etapa_c}, Python={etapa_python})"
            )

        # Antes de comparar saídas, exige a mesma entrada e a mesma semente.
        # Uma estimativa próxima não compensa testes executados em condições
        # diferentes das registradas pela referência.
        for campo in CAMPOS_ENTRADA:
            if c[campo] != python[campo]:
                problemas_etapa.append(
                    f"entrada {campo} diferente (C={c[campo]:.6f}, "
                    f"Python={python[campo]:.6f})"
                )
        if c["semente"] != python["semente"]:
            problemas_etapa.append("sementes diferentes entre C e Python")

        # Confere a posição medida de cada arquivo contra os próprios sensores:
        # média das indicações das paredes opostas em cada eixo.
        for nome, resultado in (("C", c), ("Python", python)):
            esperado_x = (resultado["sensor_esquerda"] +
                          MAPA_LARGURA - resultado["sensor_direita"]) / 2.0
            esperado_y = (resultado["sensor_inferior"] +
                          MAPA_ALTURA - resultado["sensor_superior"]) / 2.0
            for campo, esperado in (("x_medido", esperado_x),
                                     ("y_medido", esperado_y)):
                if abs(em_micrometros(resultado[campo]) -
                       em_micrometros(esperado)) > TOLERANCIA_MEDIDO_UM:
                    problemas_etapa.append(
                        f"{campo} de {nome} nao corresponde aos sensores"
                    )

        # Também exige concordância entre as posições medidas dos dois arquivos,
        # usando o limite específico em micrômetros, não a tolerância estimada.
        for eixo in ("x", "y"):
            campo = f"{eixo}_medido"
            if abs(em_micrometros(c[campo]) -
                   em_micrometros(python[campo])) > TOLERANCIA_MEDIDO_UM:
                problemas_etapa.append(
                    f"{campo} diferente (C={c[campo]:.6f}, "
                    f"Python={python[campo]:.6f})"
                )

        # As posições estimadas devem permanecer dentro do mapa retangular.
        for nome, resultado in (("C", c), ("Python", python)):
            x = resultado["x_estimado"]
            y = resultado["y_estimado"]
            if not (0.0 <= x <= MAPA_LARGURA and 0.0 <= y <= MAPA_ALTURA):
                problemas_etapa.append(
                    f"estimativa {nome} fora do mapa ({x:.6f}, {y:.6f})"
                )

        # Diferença euclidiana em metros: sqrt((x_C-x_Python)^2 +
        # (y_C-y_Python)^2). A comparação usa o valor calculado, antes da
        # formatação com seis casas decimais exibida na tabela.
        distancia = math.hypot(
            c["x_estimado"] - python["x_estimado"],
            c["y_estimado"] - python["y_estimado"],
        )
        distancias.append(distancia)
        if distancia > tolerancia:
            problemas_etapa.append(
                f"diferenca {distancia:.6f} m excede {tolerancia:.6f} m"
            )

        # Aprova somente quando todas as verificações do par foram atendidas,
        # não apenas quando a diferença euclidiana respeita o limite.
        estado = "PASSOU" if not problemas_etapa else "FALHOU"
        if problemas_etapa:
            total_falhou += 1
        else:
            total_passou += 1
        diferenca_formatada = f"{distancia:.6f} m"
        print(f"{etapa_c:5d} | {diferenca_formatada:^20} | {estado}")
        falhas.extend(f"Teste {etapa_c}: {item}." for item in problemas_etapa)

    # A diferença máxima considera apenas os pares disponíveis nos dois CSVs.
    # O resumo apresenta contagens, sem transformar a comparação em um único
    # veredito global e sem calcular RMSE.
    if distancias:
        print(f"\nDiferenca maxima: {max(distancias):.6f} m")
    print(f"Tolerancia por teste de uma etapa: {tolerancia:.6f} m")
    print(f"Total de testes que PASSOU: {total_passou}")
    print(f"Total de testes que FALHOU: {total_falhou}")

    # O retorno informa concordância para chamadas diretas desta função.
    return not falhas


# Permite substituir a tolerância padrão pela linha de comando, em metros.
# A validação de finitude e sinal é feita em main antes de ler os arquivos.
def criar_argumentos():
    analisador = argparse.ArgumentParser(
        description="Compara os testes independentes de uma etapa dos resultados C e Python."
    )
    analisador.add_argument(
        "-t",
        "--tolerancia",
        type=float,
        default=TOLERANCIA_TESTE,
        help=(
            "distancia maxima por teste, em metros "
            f"(padrao: {TOLERANCIA_TESTE})"
        ),
    )
    return analisador.parse_args()


# Coordena a leitura e o relatório. Código 0 significa comparação concluída,
# inclusive com testes reprovados; código 1 indica erro ou interrupção.
# O retorno booleano de comparar não é usado como código de saída do programa.
def main():
    try:
        argumentos = criar_argumentos()
    except SystemExit as erro:
        return 0 if erro.code == 0 else 1
    if not math.isfinite(argumentos.tolerancia) or argumentos.tolerancia < 0.0:
        print("ERRO: as tolerancias devem ser numeros finitos nao negativos.")
        return 1

    try:
        resultados_c = ler_resultados(ARQUIVO_C)
        resultados_python = ler_resultados(ARQUIVO_PYTHON)
        comparar(
            resultados_c,
            resultados_python,
            argumentos.tolerancia,
        )
    except (OSError, ErroComparacao) as erro:
        print(f"ERRO: {erro}")
        return 1
    except KeyboardInterrupt:
        print("\nComparacao cancelada.")
        return 1

    # Testes reprovados são resultados válidos de uma comparação concluída.
    return 0


# Propaga ao terminal o código de conclusão da execução, não a aprovação dos testes.
if __name__ == "__main__":
    sys.exit(main())
