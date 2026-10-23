# Formato compartilhado das entradas e dos resultados da validação.
# Centraliza as unidades, os cabeçalhos CSV e as verificações usadas pelos
# scripts de execução, pelo cliente UART e pela referência Python.

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path


# A representação interna acompanha o protocolo UART: distâncias em
# micrômetros e ângulos em milésimos de grau, armazenados como inteiros.
ESCALA_METROS = 1_000_000
ESCALA_ANGULO = 1_000
# Maior inteiro com sinal de 32 bits aceito para os campos de medição.
LIMITE_INTEIRO = 2_147_483_647
# Limites por sensor: esquerda, direita, inferior e superior, em metros.
LIMITES_SENSORES = (10.0, 10.0, 8.0, 8.0)
# A ordem dos campos faz parte do formato: a leitura exige cabeçalho idêntico.
CAMPOS_MEDICAO = (
    "teste",
    "deslocamento",
    "angulo",
    "sensor_esquerda",
    "sensor_direita",
    "sensor_inferior",
    "sensor_superior",
)
# Cada resultado preserva a entrada e acrescenta a semente e as coordenadas.
# A semente permite reproduzir a inicialização e o movimento de cada teste.
CAMPOS_RESULTADO = CAMPOS_MEDICAO + (
    "semente",
    "x_medido",
    "y_medido",
    "x_estimado",
    "y_estimado",
)


# Registro imutável de uma entrada: frozen=True impede a reatribuição normal
# dos campos. As propriedades abaixo expõem valores em metros e graus sem
# modificar os inteiros armazenados. A semente não pertence a esta estrutura.
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

    # Produz os campos na ordem do CSV: seis casas para metros e três para
    # graus, compatíveis com a resolução inteira adotada pelo protocolo.
    def campos_entrada(self):
        return (
            self.teste,
            f"{self.deslocamento:.6f}",
            f"{self.angulo:.3f}",
            *(f"{valor:.6f}" for valor in self.sensores),
        )


# Constrói uma medição a partir de metros e graus, validando identificador,
# quantidade de sensores, valores finitos, limites do mapa e faixa da UART.
# Não exige que as distâncias de sensores opostos somem a dimensão do mapa.
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

    # Converte às unidades inteiras antes de armazenar. round usa o critério
    # do Python: em empate exato, escolhe o inteiro par mais próximo.
    escalas = (ESCALA_METROS, ESCALA_ANGULO, *(ESCALA_METROS for _ in sensores))
    valores_escalados = tuple(valor * escala for valor, escala in zip(valores, escalas))
    # Mesmo entradas finitas podem exceder a representação ao aplicar a escala.
    if not all(math.isfinite(valor) for valor in valores_escalados):
        raise ValueError("Valor fora da faixa de inteiros de 32 bits da UART.")
    escalados = tuple(round(valor) for valor in valores_escalados)
    # O intervalo com sinal vai de -2147483648 até 2147483647, inclusive.
    if any(not -LIMITE_INTEIRO - 1 <= valor <= LIMITE_INTEIRO for valor in escalados):
        raise ValueError("Valor fora da faixa de inteiros de 32 bits da UART.")
    return Medicao(teste, escalados[0], escalados[1], escalados[2:])


# Repete a mesma entrada, alterando apenas o identificador para 1, 2, ..., N.
# replace cria novos registros sem modificar a medição original. As sementes
# de cada teste são tratadas separadamente pelos scripts de execução.
def repetir_medicao(medicao, quantidade):
    if quantidade <= 0:
        raise ValueError("A quantidade de testes deve ser positiva.")
    return [replace(medicao, teste=teste) for teste in range(1, quantidade + 1)]


# Lê um cenário com cabeçalho e exatamente uma linha de entrada (teste 1).
# Retorna uma lista com uma medição; a repetição em N testes ocorre fora daqui.
# utf-8-sig aceita UTF-8 com ou sem BOM; newline="" delega as quebras ao csv.
def ler_arquivo_medicoes(caminho):
    medicoes = []
    with Path(caminho).open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_MEDICAO:
            raise ValueError(
                "Cabecalho invalido nas medicoes. Esperado: "
                + ",".join(CAMPOS_MEDICAO)
            )
        # A primeira linha é o cabeçalho; a numeração ajuda a localizar erros.
        for numero_linha, linha in enumerate(leitor, start=2):
            try:
                teste = int(linha["teste"])
                valores = [float(linha[campo]) for campo in CAMPOS_MEDICAO[1:]]
                if teste != len(medicoes) + 1:
                    raise ValueError("testes devem ser consecutivos a partir de 1")
                medicoes.append(criar_medicao(teste, valores[0], valores[1], valores[2:]))
            except (TypeError, ValueError) as erro:
                raise ValueError(f"Medicao invalida na linha {numero_linha}: {erro}") from erro
    # Cenários antigos com várias entradas devem ser adequados ao formato
    # atual: uma única entrada, com a quantidade de testes escolhida à parte.
    if not medicoes:
        raise ValueError("O arquivo de medicoes nao possui testes.")
    if len(medicoes) != 1:
        raise ValueError("O cenario deve conter apenas uma linha de dados, alem do cabecalho.")
    return medicoes


# Recupera pares (medição, semente) do resultado C, um por teste executado.
# Diferentemente do cenário, este CSV possui N linhas. A leitura recupera
# entradas e sementes; não compara as coordenadas medidas ou estimadas.
def ler_testes_registrados(caminho):
    testes = []
    with Path(caminho).open("r", newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != CAMPOS_RESULTADO:
            raise ValueError("Gere novamente resultado_c.csv com o cliente atualizado.")
        for linha in leitor:
            semente = int(linha["semente"])
            # O gerador C usa uma semente sem sinal de 32 bits, incluindo zero.
            if not 0 <= semente <= 0xFFFFFFFF:
                raise ValueError("Semente fora da faixa de 32 bits.")
            medicao = criar_medicao(
                int(linha["teste"]), float(linha["deslocamento"]),
                float(linha["angulo"]),
                [float(linha[campo]) for campo in CAMPOS_MEDICAO[3:]],
            )
            # Mantém correspondência entre posição na lista e número do teste.
            if medicao.teste != len(testes) + 1:
                raise ValueError("Testes registrados fora de sequencia.")
            testes.append((medicao, semente))
    if not testes:
        raise ValueError("O resultado C nao possui testes registrados.")
    return testes
