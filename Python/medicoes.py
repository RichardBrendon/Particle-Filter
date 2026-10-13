"""Formato compartilhado das entradas e dos resultados da validacao."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path


ESCALA_METROS = 1_000_000
ESCALA_ANGULO = 1_000
SEMENTE_REAMOSTRAGEM = 12345
ESCALA_REAMOSTRAGEM = 1 << 53
LIMITE_INTEIRO = 2_147_483_647
LIMITES_SENSORES = (10.0, 10.0, 8.0, 8.0)
CAMPOS_MEDICAO = (
    "etapa",
    "deslocamento",
    "angulo",
    "sensor_esquerda",
    "sensor_direita",
    "sensor_inferior",
    "sensor_superior",
)
CAMPOS_RESULTADO = CAMPOS_MEDICAO + (
    "reamostragem_u53",
    "x_medido",
    "y_medido",
    "x_estimado",
    "y_estimado",
)


@dataclass(frozen=True)
class Medicao:
    etapa: int
    deslocamento_um: int
    angulo_mgraus: int
    sensores_um: tuple[int, int, int, int]

    @property
    def deslocamento(self):
        return self.deslocamento_um / ESCALA_METROS

    @property
    def angulo(self):
        return self.angulo_mgraus / ESCALA_ANGULO

    @property
    def sensores(self):
        return tuple(valor / ESCALA_METROS for valor in self.sensores_um)

    def campos_entrada(self):
        return (
            self.etapa,
            f"{self.deslocamento:.6f}",
            f"{self.angulo:.3f}",
            *(f"{valor:.6f}" for valor in self.sensores),
        )


def criar_medicao(etapa, deslocamento, angulo, sensores):
    if not isinstance(etapa, int) or etapa < 1:
        raise ValueError("A etapa deve ser um inteiro positivo.")
    if len(sensores) != 4:
        raise ValueError("A medicao deve conter quatro sensores.")

    valores = (deslocamento, angulo, *sensores)
    if not all(math.isfinite(valor) for valor in valores):
        raise ValueError("Os valores da medicao devem ser finitos.")
    for nome, valor, limite in zip(CAMPOS_MEDICAO[3:], sensores, LIMITES_SENSORES):
        if not 0.0 <= valor <= limite:
            raise ValueError(f"{nome} deve estar entre 0 e {limite} m.")

    escalas = (ESCALA_METROS, ESCALA_ANGULO, *(ESCALA_METROS for _ in sensores))
    valores_escalados = tuple(valor * escala for valor, escala in zip(valores, escalas))
    if not all(math.isfinite(valor) for valor in valores_escalados):
        raise ValueError("Valor fora da faixa de inteiros de 32 bits da UART.")
    escalados = tuple(round(valor) for valor in valores_escalados)
    if any(not -LIMITE_INTEIRO - 1 <= valor <= LIMITE_INTEIRO for valor in escalados):
        raise ValueError("Valor fora da faixa de inteiros de 32 bits da UART.")
    return Medicao(etapa, escalados[0], escalados[1], escalados[2:])


def ler_arquivo_medicoes(caminho):
    medicoes = []
    with Path(caminho).open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_MEDICAO:
            raise ValueError(
                "Cabecalho invalido nas medicoes. Esperado: "
                + ",".join(CAMPOS_MEDICAO)
            )
        for numero_linha, linha in enumerate(leitor, start=2):
            try:
                etapa = int(linha["etapa"])
                valores = [float(linha[campo]) for campo in CAMPOS_MEDICAO[1:]]
                if etapa != len(medicoes) + 1:
                    raise ValueError("etapas devem ser consecutivas a partir de 1")
                medicoes.append(criar_medicao(etapa, valores[0], valores[1], valores[2:]))
            except (TypeError, ValueError) as erro:
                raise ValueError(f"Medicao invalida na linha {numero_linha}: {erro}") from erro
    if not medicoes:
        raise ValueError("O arquivo de medicoes nao possui etapas.")
    return medicoes
