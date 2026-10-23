# Referência Python do filtro de partículas para localização em um mapa 2D.
# Cada teste reinicializa o filtro e executa uma única etapa. As entradas e
# sementes devem corresponder às registradas pela implementação C.
# Os cálculos usam float32 e a mesma grade de coordenadas do firmware para
# reduzir diferenças numéricas; isso não garante resultados idênticos entre
# as implementações das funções matemáticas do NumPy e da biblioteca C.

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
    repetir_medicao,
)

# Configuração do modelo: deve acompanhar a configuração compilada no firmware.
# Distâncias são expressas em metros; desvios angulares são dados em radianos.
NUM_PARTICULAS = 1000
NUM_SENSORES = 4
MAPA_LARGURA = np.float32(10.0)
MAPA_ALTURA = np.float32(8.0)
DESVIO_MOVIMENTO = np.float32(0.08)
DESVIO_ANGULO = np.float32(0.03)
DESVIO_SENSOR = np.float32(0.20)
PI = np.float32(3.1415927)
# Maior código de 12 bits. Cada eixo possui 4096 coordenadas representáveis.
COORDENADA_MAXIMA = np.float32(4095.0)
# Resolve a pasta na raiz do projeto, independentemente do diretório de execução.
DIRETORIO_RESULTADOS = Path(__file__).resolve().parent.parent / "Resultados"
ARQUIVO_RESULTADO_PYTHON = DIRETORIO_RESULTADOS / "resultado_python.csv"
NOMES_SENSORES = (
    "parede esquerda",
    "parede direita",
    "parede inferior",
    "parede superior",
)


# Lê a quantidade de testes independentes no modo interativo.
# Entradas inválidas geram ValueError, tratado no ponto de entrada do programa.
def ler_numero_testes():
    texto = input("Numero de testes: ").strip()
    try:
        testes = int(texto)
    except ValueError as erro:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.") from erro
    if not 1 <= testes <= 1_000_000:
        raise ValueError("Informe um numero inteiro entre 1 e 1000000.")
    return testes


# Solicita uma única entrada: deslocamento, ângulo em graus e quatro sensores.
# criar_medicao valida os valores e os converte às escalas inteiras da UART,
# compartilhadas com o cliente C e com os arquivos de resultados.
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


# Estado do gerador usado na inicialização e nos ruídos de movimento.
# É separado do gerador NumPy utilizado pela reamostragem do FilterPy.
estado_aleatorio = 0


# Avança o gerador congruente linear de 32 bits usado pelo C.
# A máscara reproduz o módulo 2^32 da aritmética sem sinal do firmware.
# A reprodução exige a mesma semente e a mesma ordem de chamadas.
def proximo_aleatorio():
    global estado_aleatorio
    estado_aleatorio = (
        1664525 * estado_aleatorio + 1013904223
    ) & 0xFFFFFFFF
    return estado_aleatorio


# Converte a palavra pseudoaleatória em uma amostra aproximadamente uniforme
# em [0, 1]. Conversão e divisão em float32 acompanham a sequência do C.
def aleatorio_entre_zero_e_um():
    valor_aleatorio = proximo_aleatorio()
    valor = np.float32(
        np.float32(valor_aleatorio) / np.float32(4294967295.0)
    )
    return valor


# Reproduz a codificação e a decodificação de 12 bits usadas pelo firmware:
# limita ao mapa, arredonda ao código mais próximo e retorna o ponto em metros.
# O Python guarda esse ponto em float32, sem empacotar os três bytes do C.
# O passo da grade de cada eixo é limite / 4095.
def quantizar_coordenada(valor, limite):
    limitado = np.float32(np.clip(valor, np.float32(0.0), limite))
    escalado = np.float32(
        np.float32(limitado * COORDENADA_MAXIMA) / limite
    )
    codigo = int(np.float32(escalado + np.float32(0.5)))
    return np.float32(
        np.float32(codigo) * limite / COORDENADA_MAXIMA
    )


# Reinicia o gerador e distribui as partículas uniformemente pelo mapa.
# Cada linha da matriz representa uma partícula: coluna 0 = x, coluna 1 = y.
# Os sorteios seguem a ordem x, y, com quantização igual à da implementação C.
def inicializar_particulas(semente):
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


# Distância prevista até a parede: 0 = esquerda, 1 = direita, 2 = inferior,
# 3 = superior. O chamador usa apenas os quatro índices válidos.
def medir_distancia_ideal(x, y, sensor):
    if sensor == 0:
        return np.float32(x)
    if sensor == 1:
        return np.float32(MAPA_LARGURA - x)
    if sensor == 2:
        return np.float32(y)
    return np.float32(MAPA_ALTURA - y)


# Calcula a verossimilhança de cada hipótese usando erros gaussianos
# independentes com o mesmo desvio para os quatro sensores.
# Diferentemente do C, armazena um vetor de pesos: não há a restrição de SRAM.
# Retorna pesos normalizados para a estimativa e a reamostragem.
def calcular_pesos(particulas, sensores):
    pesos = np.empty(NUM_PARTICULAS, dtype=np.float32)
    soma = np.float32(0.0)
    denominador = np.float32(
        np.float32(2.0) * DESVIO_SENSOR * DESVIO_SENSOR
    )

    # Acumula os erros e os pesos na ordem do C, com arredondamentos float32.
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

    # Sem evidência numericamente suficiente, usa pesos uniformes para evitar
    # dividir por uma soma nula ou muito pequena. Caso contrário, normaliza.
    if soma <= np.float32(1.0e-12):
        pesos.fill(np.float32(1.0 / NUM_PARTICULAS))
    else:
        for indice in range(NUM_PARTICULAS):
            pesos[indice] = np.float32(pesos[indice] / soma)
    return pesos


# Calcula a média ponderada de x e y antes da reamostragem.
# A acumulação explícita preserva a ordem das operações do firmware, evitando
# uma redução vetorizada que possa somar os termos em outra ordem.
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


# Reproduz a conversão float32 para micrômetros inteiros feita pelo firmware.
# Arredonda ao inteiro mais próximo, afastando de zero nos empates, e devolve
# uma string em metros com seis casas decimais para o terminal e para o CSV.
def formatar_como_uart(valor):
    escalado = np.float32(np.float32(valor) * np.float32(ESCALA_METROS))
    arredondamento = np.float32(0.5 if escalado >= 0 else -0.5)
    micrometros = int(np.float32(escalado + arredondamento))
    return f"{micrometros / ESCALA_METROS:.6f}"


# Aproxima um ruído normal pela soma de 12 uniformes: subtrai a média 6 e
# aplica o desvio desejado. É a mesma aproximação limitada utilizada no C,
# não uma chamada ao gerador normal do NumPy.
def ruido_normal(desvio):
    soma = np.float32(0.0)
    for _ in range(12):
        soma = np.float32(soma + aleatorio_entre_zero_e_um())
    return np.float32(np.float32(soma - np.float32(6.0)) * desvio)


# Prediz o movimento e atualiza a matriz de partículas no próprio objeto.
# Converte graus em radianos; sorteia primeiro o ruído angular e depois o de
# deslocamento. Ao atualizar cada eixo, restringe ao mapa e quantiza novamente.
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


# Coordena a leitura das entradas, a reprodução das sementes e a execução.
# O resultado C deve existir: fornece a semente de cada teste e permite
# conferir se as entradas e a quantidade correspondem à execução comparada.
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
    analisador.add_argument("--testes", type=int, help="numero de repeticoes da unica entrada")
    argumentos = analisador.parse_args()
    print("Filtro de Particulas em Python")
    print(f"Mapa: {MAPA_LARGURA:.1f} m x {MAPA_ALTURA:.1f} m")
    print(f"Particulas: {NUM_PARTICULAS} | Sensores: {NUM_SENSORES}")
    # --repetir-c reutiliza as entradas registradas; --entradas lê um CSV com
    # uma única entrada. Sem essas opções, a entrada é solicitada no terminal.
    testes_registrados = ler_testes_registrados(argumentos.resultados_c)
    if argumentos.repetir_c:
        medicoes = [medicao for medicao, _ in testes_registrados]
    else:
        medicoes = ler_arquivo_medicoes(argumentos.entradas) if argumentos.entradas else None
    # A quantidade explícita tem prioridade. Ao reutilizar dados de arquivo,
    # o padrão é a quantidade registrada no resultado C, não o nome do cenário.
    if argumentos.testes is not None:
        numero_testes = argumentos.testes
    elif argumentos.repetir_c or argumentos.entradas:
        numero_testes = len(testes_registrados)
    else:
        numero_testes = ler_numero_testes()
    if numero_testes <= 0:
        raise ValueError("O numero de testes deve ser positivo.")
    # Todos os testes devem usar a mesma entrada, variando apenas identificador
    # e semente. A comparação abaixo ocorre antes de sobrescrever o resultado.
    if argumentos.repetir_c:
        if any(m.campos_entrada()[1:] != medicoes[0].campos_entrada()[1:] for m in medicoes):
            raise ValueError("O resultado C deve usar a mesma entrada em todos os testes. Execute C novamente.")
    elif medicoes:
        medicoes = repetir_medicao(medicoes[0], numero_testes)
    else:
        print(f"Informe uma unica entrada para os {numero_testes} testes.")
        medicoes = repetir_medicao(ler_medicao(1), numero_testes)
    if len(testes_registrados) != numero_testes:
        raise ValueError("Quantidade de testes diferente do resultado C. Execute C primeiro.")
    if medicoes and medicoes != [medicao for medicao, _ in testes_registrados]:
        raise ValueError("As entradas nao correspondem ao resultado C. Execute C novamente.")
    # Cria a pasta quando necessário e sobrescreve o CSV da execução anterior.
    # Cada linha contém entrada, semente, posição medida e posição estimada.
    DIRETORIO_RESULTADOS.mkdir(exist_ok=True)
    with ARQUIVO_RESULTADO_PYTHON.open(
        "w", newline="", encoding="utf-8"
    ) as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_RESULTADO)
        for teste in range(1, numero_testes + 1):
            print(f"\nTeste {teste} de {numero_testes} | Etapa 1 de 1")
            medicao = medicoes[teste - 1]
            medicao_c, semente = testes_registrados[teste - 1]
            if medicao != medicao_c:
                raise ValueError(f"Entradas do teste {teste} diferentes do resultado C.")
            # O gerador próprio reproduz inicialização e movimento do C.
            # A semente NumPy controla separadamente a reamostragem do FilterPy;
            # não implica que seu sorteio seja igual ao sorteio interno do C.
            particulas = inicializar_particulas(semente)
            np.random.seed(semente)
            # Reproduz o firmware: converte o inteiro da UART para float32
            # antes de dividir pela escala, também em float32.
            deslocamento = np.float32(medicao.deslocamento_um) / np.float32(ESCALA_METROS)
            angulo_graus = np.float32(medicao.angulo_mgraus) / np.float32(ESCALA_ANGULO)
            sensores = np.asarray(medicao.sensores_um, dtype=np.float32) / np.float32(ESCALA_METROS)

            # 1. Predição: aplica o movimento com ruído às hipóteses iniciais.
            prever_particulas(particulas, deslocamento, angulo_graus)

            # 2. Atualização: calcula pesos normalizados e estima a posição.
            pesos = calcular_pesos(particulas, sensores)
            x_estimado, y_estimado = estimar_posicao(particulas, pesos)
            # A posição medida é a média das indicações dos sensores opostos.
            # É informativa; os pesos usam as quatro distâncias diretamente.
            x_medido = np.float32(
                (sensores[0] + np.float32(MAPA_LARGURA - sensores[1]))
                / np.float32(2.0)
            )
            y_medido = np.float32(
                (sensores[2] + np.float32(MAPA_ALTURA - sensores[3]))
                / np.float32(2.0)
            )
            # 3. Reamostragem sistemática pela função pronta do FilterPy.
            # A estimativa acima não é alterada pela seleção dos índices.
            # Como cada teste tem uma etapa, a população selecionada é
            # descartada ao reinicializar o filtro no próximo teste.
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

# Executa apenas quando chamado como programa; falhas de arquivo ou validação
# encerram a execução com mensagem de erro, sem produzir uma aprovação falsa.
if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as erro:
        raise SystemExit(f"Erro: {erro}") from erro
