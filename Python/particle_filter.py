import math
import csv
import argparse
from pathlib import Path

import numpy as np
from filterpy.monte_carlo import systematic_resample

from medicoes import (
    CAMPOS_RESULTADO,
    ESCALA_METROS,
    ESCALA_REAMOSTRAGEM,
    SEMENTE_REAMOSTRAGEM,
    criar_medicao,
    ler_arquivo_medicoes,
)

NUM_PARTICULAS = 1000
NUM_SENSORES = 4
NUM_ETAPAS_PADRAO = 1
MAPA_LARGURA = np.float32(10.0)
MAPA_ALTURA = np.float32(8.0)
DESVIO_MOVIMENTO = np.float32(0.08)
DESVIO_ANGULO = np.float32(0.03)
DESVIO_SENSOR = np.float32(0.20)
SEMENTE_ALEATORIA = 12345
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


def ler_numero_etapas():
    texto = input(f"Numero de etapas: ").strip()
    if not texto:
        return NUM_ETAPAS_PADRAO
    try:
        etapas = int(texto)
    except ValueError as erro:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.") from erro
    if not 1 <= etapas <= 1_000_000:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.")
    return etapas


def ler_medicao(etapa, numero_etapas):
    deslocamento = float(input("Deslocamento (m): "))
    angulo_graus = float(input("Angulo do movimento (graus): "))
    sensores = []
    limites = (MAPA_LARGURA, MAPA_LARGURA, MAPA_ALTURA, MAPA_ALTURA)
    for indice, nome in enumerate(NOMES_SENSORES):
        valor = float(input(f"Distancia medida ate a {nome} (m): "))
        if not math.isfinite(valor) or not 0 <= valor <= limites[indice]:
            raise ValueError(f"Distancia invalida para {nome}.")
        sensores.append(valor)

    return criar_medicao(etapa, deslocamento, angulo_graus, sensores)


estado_aleatorio = SEMENTE_ALEATORIA


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


def inicializar_particulas():
    """Cria as mesmas particulas iniciais da implementacao C."""
    global estado_aleatorio
    estado_aleatorio = SEMENTE_ALEATORIA
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
            math.exp(float(np.float32(-erro_total / denominador)))
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


def formatar_medido_como_uart(valor):
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
                + np.float32(distancia * np.float32(math.cos(float(direcao))))
            ),
            MAPA_LARGURA,
        )
        particulas[indice, 1] = quantizar_coordenada(
            np.float32(
                particulas[indice, 1]
                + np.float32(distancia * np.float32(math.sin(float(direcao))))
            ),
            MAPA_ALTURA,
        )


def main():
    analisador = argparse.ArgumentParser(description="Referencia Python do filtro de particulas.")
    analisador.add_argument(
        "--entradas", type=Path,
        help="CSV com as mesmas medicoes enviadas ao firmware",
    )
    argumentos = analisador.parse_args()
    print("Filtro de Particulas em Python")
    print(f"Mapa: {MAPA_LARGURA:.1f} m x {MAPA_ALTURA:.1f} m")
    print(f"Particulas: {NUM_PARTICULAS} | Sensores: {NUM_SENSORES}")
    medicoes = ler_arquivo_medicoes(argumentos.entradas) if argumentos.entradas else None
    numero_etapas = len(medicoes) if medicoes else ler_numero_etapas()
    particulas = inicializar_particulas()
    np.random.seed(SEMENTE_REAMOSTRAGEM)
    sorteios_registro = np.random.RandomState(SEMENTE_REAMOSTRAGEM)
    DIRETORIO_RESULTADOS.mkdir(exist_ok=True)
    with ARQUIVO_RESULTADO_PYTHON.open(
        "w", newline="", encoding="utf-8"
    ) as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_RESULTADO)
        for etapa in range(numero_etapas):
            print(f"\nEtapa {etapa + 1} de {numero_etapas}")
            medicao = (
                medicoes[etapa] if medicoes
                else ler_medicao(etapa + 1, numero_etapas)
            )
            deslocamento = np.float32(medicao.deslocamento)
            angulo_graus = medicao.angulo
            sensores = np.asarray(medicao.sensores, dtype=np.float32)

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
            # A reamostragem do FilterPy atualiza as particulas para a proxima etapa.
            # Um gerador paralelo permite registrar o sorteio sem alterar o
            # estado global que a funcao pronta do FilterPy consome.
            amostra_u53 = int(sorteios_registro.random_sample()
                              * ESCALA_REAMOSTRAGEM)
            indices = systematic_resample(pesos)
            particulas = particulas[indices].copy()

            escritor.writerow((
                *medicao.campos_entrada(),
                amostra_u53,
                formatar_medido_como_uart(x_medido),
                formatar_medido_como_uart(y_medido),
                f"{float(x_estimado):.6f}",
                f"{float(y_estimado):.6f}",
            ))

            print(f"Posicao estimada: ({float(x_estimado):.6f}, {float(y_estimado):.6f}) m")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as erro:
        raise SystemExit(f"Erro: {erro}") from erro
