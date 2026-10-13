# Funcionamento e validação do filtro de partículas

Este documento separa o funcionamento de **uma etapa do filtro** do procedimento usado para **comparar a implementação C com a referência Python**. Os diagramas Mermaid podem ser visualizados no GitHub.

## 1. Funcionamento do filtro

O mapa mede 10 × 8 m e cada execução começa com 1.000 partículas. A inicialização e o ruído do movimento usam geradores reproduzíveis entre C e Python. No firmware, as coordenadas persistentes são compactadas em 12 bits por eixo para reduzir o uso de SRAM; durante os cálculos, cada partícula é representada por coordenadas `float`.

```mermaid
flowchart TD
    A[Início] --> B[Inicializar 1.000 partículas no mapa]
    B --> C[Receber deslocamento, ângulo e quatro sensores]
    C --> D[Prever movimento das partículas com ruído]
    D --> E[Calcular pesos pelas distâncias previstas às paredes]
    E --> F[Calcular posição estimada com os pesos]
    F --> G[Reamostragem sistemática com o sorteio da etapa]
    G --> H{Há outra etapa?}
    H -- Sim --> C
    H -- Não --> I[Fim]
```

A **estimativa é calculada antes da reamostragem**. A população reamostrada será usada na etapa seguinte. No C, a reamostragem ocorre dentro de `particle_filter.c`; na referência Python, ela usa `systematic_resample` do FilterPy. Mesmo com o mesmo sorteio, diferenças de arredondamento nos pesos e nas somas acumuladas podem selecionar partículas diferentes.

## 2. Teste e validação C–Python

O objetivo deste teste é verificar a **concordância das posições estimadas** pelo C e pelo Python, não medir o erro em relação à posição real. Use exatamente o mesmo arquivo de `Dados_Teste/` nos dois programas. Para o C, `comunicacao_uart.py` envia cada medição e o sorteio da reamostragem à placa ou ao Renode e grava `Resultados/resultado_c.csv`. O Python processa as mesmas medições, reproduz a sequência de sorteios e grava `Resultados/resultado_python.csv`.

```mermaid
flowchart TD
    A[Escolher um CSV em Dados_Teste] --> B[Executar C via cliente UART]
    A --> C[Executar a referência Python]
    B --> D[resultado_c.csv]
    C --> E[resultado_python.csv]
    D --> F[Comparar os dois resultados]
    E --> F
    F --> G{Etapas, entradas, sorteios e valores são válidos?}
    G -- Não --> H[FALHOU: indicar etapa e motivo]
    G -- Sim --> I{Distância C–Python é até 1 cm em toda etapa?}
    I -- Não --> H
    I -- Sim --> J[PASSOU]
    H --> K[Mostrar diferença máxima e RMSE]
    J --> K
```

Em cada etapa, o comparador calcula a distância euclidiana entre as estimativas:

`d = sqrt((x_C - x_Python)^2 + (y_C - y_Python)^2)`

O critério numérico padrão, ainda **provisório**, é `d ≤ 0,01 m` em **todas** as etapas. O comparador também confere quantidade e ordem das etapas, entradas e sorteios iguais, posições dentro do mapa e posições medidas compatíveis com os sensores, admitindo 1 micrômetro de diferença por arredondamento da UART. Qualquer falha torna o resultado geral `FALHOU`.

A **diferença máxima** e o **RMSE** resumem o comportamento do cenário, mas o RMSE não decide a aprovação: uma etapa muito divergente poderia ser escondida pela média das demais. Se todas as distâncias individuais são no máximo 1 cm, o RMSE também é no máximo 1 cm. O desvio padrão das diferenças não substitui esse critério, pois pode ser pequeno mesmo quando todas as diferenças são grandes. O limite de 1 cm foi adotado como critério prático de comparação entre implementações; não afirma precisão absoluta de localização nem garante aprovação em qualquer cenário.

## Como reproduzir

1. Escolha um cenário, por exemplo `Dados_Teste/cenario_60_etapas.csv`.
2. Execute `comunicacao_uart.py` com `--entradas` apontando para ele, usando a placa ou o Renode.
3. Execute `particle_filter.py` com o mesmo `--entradas`.
4. Execute `python .\Python\comparar_resultados.py` na raiz do projeto.

Os arquivos em `Resultados/` são sobrescritos a cada execução. Portanto, gere **ambos** novamente antes de comparar outro cenário. Para comandos completos da placa e do Renode, consulte o [README](../README.md).
