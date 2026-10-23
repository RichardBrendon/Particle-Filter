"""Formato compartilhado das entradas e dos resultados da validacao."""

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path


ESCALA_METROS = 1_000_000
ESCALA_ANGULO = 1_000
LIMITE_INTEIRO = 2_147_483_647
LIMITES_SENSORES = (10.0, 10.0, 8.0, 8.0)
CAMPOS_MEDICAO = (
    "teste",
    "deslocamento",
    "angulo",
    "sensor_esquerda",
    "sensor_direita",
    "sensor_inferior",
    "sensor_superior",
)
CAMPOS_RESULTADO = CAMPOS_MEDICAO + (
    "semente",
    "x_medido",
    "y_medido",
    "x_estimado",
    "y_estimado",
)


@dataclass(frozen=True)
class Medicao:
    teste: int
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
            self.teste,
            f"{self.deslocamento:.6f}",
            f"{self.angulo:.3f}",
            *(f"{valor:.6f}" for valor in self.sensores),
        )


def criar_medicao(teste, deslocamento, angulo, sensores):
    if not isinstance(teste, int) or teste < 1:
        raise ValueError("O teste deve ser um inteiro positivo.")
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
    return Medicao(teste, escalados[0], escalados[1], escalados[2:])


def repetir_medicao(medicao, quantidade):
    """Repete as mesmas entradas, alterando apenas o identificador do teste."""
    if quantidade <= 0:
        raise ValueError("A quantidade de testes deve ser positiva.")
    return [replace(medicao, teste=teste) for teste in range(1, quantidade + 1)]


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
                teste = int(linha["teste"])
                valores = [float(linha[campo]) for campo in CAMPOS_MEDICAO[1:]]
                if teste != len(medicoes) + 1:
                    raise ValueError("testes devem ser consecutivos a partir de 1")
                medicoes.append(criar_medicao(teste, valores[0], valores[1], valores[2:]))
            except (TypeError, ValueError) as erro:
                raise ValueError(f"Medicao invalida na linha {numero_linha}: {erro}") from erro
    if not medicoes:
        raise ValueError("O arquivo de medicoes nao possui testes.")
    if len(medicoes) != 1:
        raise ValueError("O cenario deve conter apenas uma linha de dados, alem do cabecalho.")
    return medicoes


def ler_testes_registrados(caminho):
    """Recupera entradas e sementes da execucao C para repetir os testes."""
    testes = []
    with Path(caminho).open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_RESULTADO:
            raise ValueError("Gere novamente resultado_c.csv com o cliente atualizado.")
        for linha in leitor:
            semente = int(linha["semente"])
            if not 0 <= semente <= 0xFFFFFFFF:
                raise ValueError("Semente fora da faixa de 32 bits.")
            medicao = criar_medicao(
                int(linha["teste"]), float(linha["deslocamento"]),
                float(linha["angulo"]),
                [float(linha[campo]) for campo in CAMPOS_MEDICAO[3:]],
            )
            if medicao.teste != len(testes) + 1:
                raise ValueError("Testes registrados fora de sequencia.")
            testes.append((medicao, semente))
    if not testes:
        raise ValueError("O resultado C nao possui testes registrados.")
    return testes
