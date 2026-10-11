"""Compara a implementacao C do filtro de particulas com a referencia Python."""

import argparse
import csv
import math
import sys
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIRETORIO_RESULTADOS = RAIZ_PROJETO / "Resultados"
ARQUIVO_C = DIRETORIO_RESULTADOS / "resultado_c.csv"
ARQUIVO_PYTHON = DIRETORIO_RESULTADOS / "resultado_python.csv"

CAMPOS = (
    "etapa",
    "x_medido",
    "y_medido",
    "x_estimado",
    "y_estimado",
)
TOLERANCIA_PRIMEIRA_ETAPA = 0.0001
TOLERANCIA_ETAPAS_SEGUINTES = 0.05
TOLERANCIA_ENTRADA = 1.0e-6
MAPA_LARGURA = 10.0
MAPA_ALTURA = 8.0


class ErroComparacao(Exception):
    """Indica que os arquivos nao podem ser comparados."""


def ler_resultados(caminho):
    if not caminho.is_file():
        raise ErroComparacao(f"Arquivo nao encontrado: {caminho}")

    resultados = []
    with caminho.open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS:
            raise ErroComparacao(
                f"Cabecalho invalido em {caminho.name}. "
                f"Esperado: {','.join(CAMPOS)}"
            )

        for numero_linha, linha in enumerate(leitor, start=2):
            try:
                resultado = {
                    "etapa": int(linha["etapa"]),
                    "x_medido": float(linha["x_medido"]),
                    "y_medido": float(linha["y_medido"]),
                    "x_estimado": float(linha["x_estimado"]),
                    "y_estimado": float(linha["y_estimado"]),
                }
            except (TypeError, ValueError) as erro:
                raise ErroComparacao(
                    f"Valor invalido em {caminho.name}, linha {numero_linha}."
                ) from erro

            if not all(
                math.isfinite(resultado[campo]) for campo in CAMPOS[1:]
            ):
                raise ErroComparacao(
                    f"Valor nao finito em {caminho.name}, linha {numero_linha}."
                )
            resultados.append(resultado)

    if not resultados:
        raise ErroComparacao(f"{caminho.name} nao possui etapas para comparar.")
    return resultados


def comparar(
    resultados_c,
    resultados_python,
    tolerancia_primeira,
    tolerancia_seguintes,
):
    """Compara todas as etapas usando limites adequados a cada fase."""
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

        for eixo in ("x", "y"):
            campo = f"{eixo}_medido"
            if not math.isclose(
                c[campo], python[campo], abs_tol=TOLERANCIA_ENTRADA
            ):
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
        tolerancia = (
            tolerancia_primeira
            if etapa_c == 1
            else tolerancia_seguintes
        )
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
            "distancia maxima nas etapas posteriores, em metros "
            f"(padrao: {TOLERANCIA_ETAPAS_SEGUINTES})"
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
