import math
import csv
import argparse
from pathlib import Path

import numpy as np
from filterpy.monte_carlo import systematic_resample

from medicoes import (
    CAMPOS_RESULTADO,
    ESCALA_ANGULO,
    ESCALA_METROS,
    criar_medicao,
    ler_arquivo_medicoes,
    ler_testes_registrados,
)

NUM_PARTICULAS = 1000
NUM_SENSORES = 4
MAPA_LARGURA = np.float32(10.0)
MAPA_ALTURA = np.float32(8.0)
DESVIO_MOVIMENTO = np.float32(0.08)
DESVIO_ANGULO = np.float32(0.03)
DESVIO_SENSOR = np.float32(0.20)
PI = np.float32(3.1415927)
COORDENADA_MAXIMA = np.float32(4095.0)
DIRETORIO_RESULTADOS = Path(__file__).resolve().parent.parent / "Resultados"
ARQUIVO_RESULTADO_PYTHON = DIRETORIO_RESULTADOS / "resultado_python.csv"
NOMES_SENSORES = (
    "parede esquerda",
    "parede direita",
    "parede inferior",
    "parede superior",
)


def ler_numero_testes():
    texto = input("Numero de testes: ").strip()
    try:
        testes = int(texto)
    except ValueError as erro:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.") from erro
    if not 1 <= testes <= 1_000_000:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.")
    return testes


def ler_medicao(teste):
    deslocamento = float(input("Deslocamento (m): "))
    angulo_graus = float(input("Angulo do movimento (graus): "))
    sensores = []
    limites = (MAPA_LARGURA, MAPA_LARGURA, MAPA_ALTURA, MAPA_ALTURA)
    for indice, nome in enumerate(NOMES_SENSORES):
        valor = float(input(f"Distancia medida ate a {nome} (m): "))
        if not math.isfinite(valor) or not 0 <= valor <= limites[indice]:
            raise ValueError(f"Distancia invalida para {nome}.")
        sensores.append(valor)

    return criar_medicao(teste, deslocamento, angulo_graus, sensores)


estado_aleatorio = 0


def proximo_aleatorio():
    """Reproduz o gerador congruente linear de 32 bits usado pelo C."""
    global estado_aleatorio
    estado_aleatorio = (
        1664525 * estado_aleatorio + 1013904223
    ) & 0xFFFFFFFF
    return estado_aleatorio


def aleatorio_entre_zero_e_um():
    valor_aleatorio = proximo_aleatorio()
    valor = np.float32(
        np.float32(valor_aleatorio) / np.float32(4294967295.0)
    )
    return valor


def quantizar_coordenada(valor, limite):
    """Reproduz a codificacao de 12 bits usada pelo firmware."""
    limitado = np.float32(np.clip(valor, np.float32(0.0), limite))
    escalado = np.float32(
        np.float32(limitado * COORDENADA_MAXIMA) / limite
    )
    codigo = int(np.float32(escalado + np.float32(0.5)))
    return np.float32(
        np.float32(codigo) * limite / COORDENADA_MAXIMA
    )


def inicializar_particulas(semente):
    """Cria as mesmas particulas iniciais da implementacao C."""
    global estado_aleatorio
    estado_aleatorio = semente
    particulas = np.empty((NUM_PARTICULAS, 2), dtype=np.float32)

    for indice in range(NUM_PARTICULAS):
        aleatorio = aleatorio_entre_zero_e_um()
        particulas[indice, 0] = quantizar_coordenada(
            np.float32(aleatorio * MAPA_LARGURA), MAPA_LARGURA
        )

        aleatorio = aleatorio_entre_zero_e_um()
        particulas[indice, 1] = quantizar_coordenada(
            np.float32(aleatorio * MAPA_ALTURA), MAPA_ALTURA
        )

    return particulas


def medir_distancia_ideal(x, y, sensor):
    if sensor == 0:
        return np.float32(x)
    if sensor == 1:
        return np.float32(MAPA_LARGURA - x)
    if sensor == 2:
        return np.float32(y)
    return np.float32(MAPA_ALTURA - y)


def calcular_pesos(particulas, sensores):
    pesos = np.empty(NUM_PARTICULAS, dtype=np.float32)
    soma = np.float32(0.0)
    denominador = np.float32(
        np.float32(2.0) * DESVIO_SENSOR * DESVIO_SENSOR
    )

    # Preserva a ordem e a precisao float usadas pelo programa C.
    for indice in range(NUM_PARTICULAS):
        erro_total = np.float32(0.0)
        for sensor in range(NUM_SENSORES):
            distancia = medir_distancia_ideal(
                particulas[indice, 0], particulas[indice, 1], sensor
            )
            erro = np.float32(distancia - sensores[sensor])
            erro_total = np.float32(erro_total + np.float32(erro * erro))
        pesos[indice] = np.float32(
            np.exp(np.float32(-erro_total / denominador))
        )
        soma = np.float32(soma + pesos[indice])

    if soma <= np.float32(1.0e-12):
        pesos.fill(np.float32(1.0 / NUM_PARTICULAS))
    else:
        for indice in range(NUM_PARTICULAS):
            pesos[indice] = np.float32(pesos[indice] / soma)
    return pesos


def estimar_posicao(particulas, pesos):
    x_estimado = np.float32(0.0)
    y_estimado = np.float32(0.0)
    for indice in range(NUM_PARTICULAS):
        x_estimado = np.float32(
            x_estimado + np.float32(particulas[indice, 0] * pesos[indice])
        )
        y_estimado = np.float32(
            y_estimado + np.float32(particulas[indice, 1] * pesos[indice])
        )
    return x_estimado, y_estimado


def formatar_como_uart(valor):
    """Reproduz a conversao float32 -> micrometros feita pelo firmware."""
    escalado = np.float32(np.float32(valor) * np.float32(ESCALA_METROS))
    arredondamento = np.float32(0.5 if escalado >= 0 else -0.5)
    micrometros = int(np.float32(escalado + arredondamento))
    return f"{micrometros / ESCALA_METROS:.6f}"


def ruido_normal(desvio):
    soma = np.float32(0.0)
    for _ in range(12):
        soma = np.float32(soma + aleatorio_entre_zero_e_um())
    return np.float32(np.float32(soma - np.float32(6.0)) * desvio)


def prever_particulas(particulas, deslocamento, angulo_graus):
    angulo = np.float32(
        np.float32(angulo_graus) * PI / np.float32(180.0)
    )
    for indice in range(NUM_PARTICULAS):
        direcao = np.float32(angulo + ruido_normal(DESVIO_ANGULO))
        distancia = np.float32(deslocamento + ruido_normal(DESVIO_MOVIMENTO))
        particulas[indice, 0] = quantizar_coordenada(
            np.float32(
                particulas[indice, 0]
                + np.float32(distancia * np.cos(direcao))
            ),
            MAPA_LARGURA,
        )
        particulas[indice, 1] = quantizar_coordenada(
            np.float32(
                particulas[indice, 1]
                + np.float32(distancia * np.sin(direcao))
            ),
            MAPA_ALTURA,
        )


def main():
    analisador = argparse.ArgumentParser(description="Referencia Python do filtro de particulas.")
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument(
        "--entradas", type=Path,
        help="CSV com as mesmas medicoes enviadas ao firmware",
    )
    entrada.add_argument(
        "--repetir-c", action="store_true",
        help="reutilizar entradas e sementes do resultado C, sem digitacao",
    )
    analisador.add_argument(
        "--resultados-c", type=Path,
        default=DIRETORIO_RESULTADOS / "resultado_c.csv",
        help="resultado C com as sementes dos testes a reproduzir",
    )
    argumentos = analisador.parse_args()
    print("Filtro de Particulas em Python")
    print(f"Mapa: {MAPA_LARGURA:.1f} m x {MAPA_ALTURA:.1f} m")
    print(f"Particulas: {NUM_PARTICULAS} | Sensores: {NUM_SENSORES}")
    testes_registrados = ler_testes_registrados(argumentos.resultados_c)
    if argumentos.repetir_c:
        medicoes = [medicao for medicao, _ in testes_registrados]
    else:
        medicoes = ler_arquivo_medicoes(argumentos.entradas) if argumentos.entradas else None
    numero_testes = len(medicoes) if medicoes else ler_numero_testes()
    if len(testes_registrados) != numero_testes:
        raise ValueError("Quantidade de testes diferente do resultado C. Execute C primeiro.")
    if medicoes and medicoes != [medicao for medicao, _ in testes_registrados]:
        raise ValueError("As entradas nao correspondem ao resultado C. Execute C novamente.")
    DIRETORIO_RESULTADOS.mkdir(exist_ok=True)
    with ARQUIVO_RESULTADO_PYTHON.open(
        "w", newline="", encoding="utf-8"
    ) as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_RESULTADO)
        for teste in range(1, numero_testes + 1):
            print(f"\nTeste {teste} de {numero_testes} | Etapa 1 de 1")
            medicao = (
                medicoes[teste - 1] if medicoes
                else ler_medicao(teste)
            )
            medicao_c, semente = testes_registrados[teste - 1]
            if medicao != medicao_c:
                raise ValueError(f"Entradas do teste {teste} diferentes do resultado C.")
            particulas = inicializar_particulas(semente)
            np.random.seed(semente)
            # Reproduz o firmware: converte o inteiro da UART para float32
            # antes de dividir pela escala, tambem em float32.
            deslocamento = np.float32(medicao.deslocamento_um) / np.float32(ESCALA_METROS)
            angulo_graus = np.float32(medicao.angulo_mgraus) / np.float32(ESCALA_ANGULO)
            sensores = np.asarray(medicao.sensores_um, dtype=np.float32) / np.float32(ESCALA_METROS)

            prever_particulas(particulas, deslocamento, angulo_graus)

            pesos = calcular_pesos(particulas, sensores)
            x_estimado, y_estimado = estimar_posicao(particulas, pesos)
            x_medido = np.float32(
                (sensores[0] + np.float32(MAPA_LARGURA - sensores[1]))
                / np.float32(2.0)
            )
            y_medido = np.float32(
                (sensores[2] + np.float32(MAPA_ALTURA - sensores[3]))
                / np.float32(2.0)
            )
            # Cada teste tem apenas uma etapa; a reamostragem continua sendo
            # executada, mas a populacao e reinicializada no teste seguinte.
            indices = systematic_resample(pesos)
            particulas = particulas[indices].copy()

            escritor.writerow((
                *medicao.campos_entrada(),
                semente,
                formatar_como_uart(x_medido),
                formatar_como_uart(y_medido),
                formatar_como_uart(x_estimado),
                formatar_como_uart(y_estimado),
            ))

            print("Posicao estimada: "
                  f"({formatar_como_uart(x_estimado)}, "
                  f"{formatar_como_uart(y_estimado)}) m")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as erro:
        raise SystemExit(f"Erro: {erro}") from erro
