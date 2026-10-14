"""Compara a implementacao C do filtro de particulas com a referencia Python."""

import argparse
import csv
import math
import sys
from pathlib import Path

from medicoes import (
    CAMPOS_MEDICAO,
    CAMPOS_RESULTADO,
    ESCALA_METROS,
    ESCALA_REAMOSTRAGEM,
    LIMITES_SENSORES,
)


RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIRETORIO_RESULTADOS = RAIZ_PROJETO / "Resultados"
ARQUIVO_C = DIRETORIO_RESULTADOS / "resultado_c.csv"
ARQUIVO_PYTHON = DIRETORIO_RESULTADOS / "resultado_python.csv"

CAMPOS_ENTRADA = CAMPOS_MEDICAO[1:]
TOLERANCIA_PRIMEIRA_ETAPA = 1.0e-5
# Criterio provisorio de 1 cm nas etapas seguintes.
TOLERANCIA_ETAPAS_SEGUINTES = 0.01
TOLERANCIA_MEDIDO_UM = 1
MAPA_LARGURA = 10.0
MAPA_ALTURA = 8.0


class ErroComparacao(Exception):
    """Indica que os arquivos nao podem ser comparados."""


def em_micrometros(valor):
    """Converte valores do CSV para a unidade inteira do protocolo UART."""
    return round(valor * ESCALA_METROS)


def ler_resultados(caminho):
    if not caminho.is_file():
        raise ErroComparacao(f"Arquivo nao encontrado: {caminho}")

    resultados = []
    with caminho.open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_RESULTADO:
            raise ErroComparacao(
                f"Cabecalho invalido em {caminho.name}. "
                f"Esperado: {','.join(CAMPOS_RESULTADO)}. "
                "Gere novamente os resultados com os programas atualizados."
            )

        for numero_linha, linha in enumerate(leitor, start=2):
            try:
                resultado = {
                    "etapa": int(linha["etapa"]),
                    "reamostragem_u53": int(linha["reamostragem_u53"]),
                }
                resultado.update(
                    (campo, float(linha[campo]))
                    for campo in CAMPOS_RESULTADO[1:]
                    if campo != "reamostragem_u53"
                )
            except (TypeError, ValueError) as erro:
                raise ErroComparacao(
                    f"Valor invalido em {caminho.name}, linha {numero_linha}."
                ) from erro

            if not all(math.isfinite(resultado[campo]) for campo in CAMPOS_RESULTADO[1:]):
                raise ErroComparacao(
                    f"Valor nao finito em {caminho.name}, linha {numero_linha}."
                )
            if resultado["etapa"] != len(resultados) + 1:
                raise ErroComparacao(
                    f"Etapas fora de sequencia em {caminho.name}, linha {numero_linha}."
                )
            if not 0 <= resultado["reamostragem_u53"] < ESCALA_REAMOSTRAGEM:
                raise ErroComparacao(
                    f"Sorteio da reamostragem invalido em {caminho.name}, "
                    f"linha {numero_linha}."
                )
            for campo, limite in zip(CAMPOS_ENTRADA[2:], LIMITES_SENSORES):
                if not 0.0 <= resultado[campo] <= limite:
                    raise ErroComparacao(
                        f"{campo} fora do mapa em {caminho.name}, linha {numero_linha}."
                    )
            resultados.append(resultado)

    if not resultados:
        raise ErroComparacao(f"{caminho.name} nao possui etapas para comparar.")
    return resultados


def comparar(resultados_c, resultados_python, tolerancia_primeira,
             tolerancia_seguintes):
    """Verifica cada etapa com seu limite e relata o RMSE."""
    falhas = []
    distancias = []

    if len(resultados_c) != len(resultados_python):
        falhas.append(
            "Quantidade de etapas diferente: "
            f"C={len(resultados_c)}, Python={len(resultados_python)}."
        )

    print("\nEtapa | Distancia C x Python | Tolerancia | Resultado")
    print("------|----------------------|------------|----------")

    for c, python in zip(resultados_c, resultados_python):
        etapa_c = c["etapa"]
        etapa_python = python["etapa"]
        problemas_etapa = []

        if etapa_c != etapa_python:
            problemas_etapa.append(
                f"indices diferentes (C={etapa_c}, Python={etapa_python})"
            )

        for campo in CAMPOS_ENTRADA:
            if c[campo] != python[campo]:
                problemas_etapa.append(
                    f"entrada {campo} diferente (C={c[campo]:.6f}, "
                    f"Python={python[campo]:.6f})"
                )
        if c["reamostragem_u53"] != python["reamostragem_u53"]:
            problemas_etapa.append(
                "sorteio da reamostragem diferente "
                f"(C={c['reamostragem_u53']}, "
                f"Python={python['reamostragem_u53']})"
            )

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

        for eixo in ("x", "y"):
            campo = f"{eixo}_medido"
            if abs(em_micrometros(c[campo]) -
                   em_micrometros(python[campo])) > TOLERANCIA_MEDIDO_UM:
                problemas_etapa.append(
                    f"{campo} diferente (C={c[campo]:.6f}, "
                    f"Python={python[campo]:.6f})"
                )

        for nome, resultado in (("C", c), ("Python", python)):
            x = resultado["x_estimado"]
            y = resultado["y_estimado"]
            if not (0.0 <= x <= MAPA_LARGURA and 0.0 <= y <= MAPA_ALTURA):
                problemas_etapa.append(
                    f"estimativa {nome} fora do mapa ({x:.6f}, {y:.6f})"
                )

        distancia = math.hypot(
            c["x_estimado"] - python["x_estimado"],
            c["y_estimado"] - python["y_estimado"],
        )
        distancias.append(distancia)
        tolerancia = (tolerancia_primeira if etapa_c == 1
                      else tolerancia_seguintes)
        if distancia > tolerancia:
            problemas_etapa.append(
                f"diferenca {distancia:.6f} m excede {tolerancia:.6f} m"
            )

        estado = "PASSOU" if not problemas_etapa else "FALHOU"
        print(
            f"{etapa_c:5d} | {distancia:20.6f} m | "
            f"{tolerancia:8.6f} m | {estado}"
        )
        falhas.extend(f"Etapa {etapa_c}: {item}." for item in problemas_etapa)

    if distancias:
        rmse = math.sqrt(sum(d * d for d in distancias) / len(distancias))
        print(f"\nDiferenca maxima: {max(distancias):.6f} m")
        print(f"RMSE entre as estimativas: {rmse:.6f} m")
    print(f"Tolerancia da primeira etapa: {tolerancia_primeira:.6f} m")
    print(f"Tolerancia das demais etapas: {tolerancia_seguintes:.6f} m")
    print("Criterio: cada etapa deve respeitar seu limite; RMSE e informativo.")

    if falhas:
        print("\nFALHOU")
        for falha in falhas:
            print(f"- {falha}")
        return False

    print("\nPASSOU: a implementacao C esta de acordo com a referencia Python.")
    return True


def criar_argumentos():
    analisador = argparse.ArgumentParser(
        description="Compara todas as etapas dos resultados C e Python."
    )
    analisador.add_argument(
        "-t",
        "--tolerancia",
        type=float,
        default=TOLERANCIA_ETAPAS_SEGUINTES,
        help=(
            "distancia maxima nas etapas seguintes, em metros "
            f"(padrao provisorio: {TOLERANCIA_ETAPAS_SEGUINTES})"
        ),
    )
    analisador.add_argument(
        "--tolerancia-primeira",
        type=float,
        default=TOLERANCIA_PRIMEIRA_ETAPA,
        help=(
            "distancia maxima na primeira etapa, em metros "
            f"(padrao: {TOLERANCIA_PRIMEIRA_ETAPA})"
        ),
    )
    return analisador.parse_args()


def main():
    argumentos = criar_argumentos()
    tolerancias = (argumentos.tolerancia_primeira, argumentos.tolerancia)
    if any(not math.isfinite(valor) or valor < 0.0 for valor in tolerancias):
        print("ERRO: as tolerancias devem ser numeros finitos nao negativos.")
        return 2

    try:
        resultados_c = ler_resultados(ARQUIVO_C)
        resultados_python = ler_resultados(ARQUIVO_PYTHON)
        passou = comparar(
            resultados_c,
            resultados_python,
            argumentos.tolerancia_primeira,
            argumentos.tolerancia,
        )
    except (OSError, ErroComparacao) as erro:
        print(f"ERRO: {erro}")
        return 2

    return 0 if passou else 1


if __name__ == "__main__":
    sys.exit(main())
