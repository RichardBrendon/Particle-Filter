# Filtro de Partículas para STM32F030R8

Implementação de um filtro de partículas para estimar a posição de um objeto em um ambiente retangular. O projeto executa o filtro em uma placa **NUCLEO-F030R8** e utiliza uma implementação em Python como referência para validação.

O firmware recebe deslocamento, ângulo e quatro distâncias por UART, processa uma etapa do filtro e devolve a posição estimada. A comunicação também pode ser testada sem a placa por meio do Renode.

## Características

- 1.000 partículas;
- mapa de `10 m x 8 m`;
- quatro sensores de distância: paredes esquerda, direita, inferior e superior;
- comunicação UART a `115200 baud`, 8N1;
- referência em Python com NumPy e FilterPy;
- inicialização e movimento pseudoaleatórios reproduzíveis entre C e Python;
- coordenadas compactadas em 12 bits para atender ao limite de RAM do STM32F030R8;
- comparação automática de todas as etapas executadas;
- suporte a teste da UART por TCP usando o Renode.

## Estrutura do projeto

```text
Particle Filter/
├── Core/                       # Firmware e filtro de partículas em C
├── Drivers/                    # HAL e CMSIS fornecidos pela ST
├── Python/
│   ├── particle_filter.py       # Implementação de referência
│   ├── comunicacao_uart.py      # Cliente para placa ou Renode
│   ├── comparar_resultados.py   # Valida C contra Python
│   └── requirements.txt
├── Renode/                    # Plataforma e scripts de emulação
├── Resultados/                # CSVs gerados (não versionados)
├── Particle Filter.ioc         # Configuração do STM32CubeMX
└── STM32F030R8TX_FLASH.ld     # Script de linker
```

A pasta `Resultados` não precisa existir após o clone. Os programas Python a criam automaticamente quando salvam os CSVs.

## Requisitos

### Firmware

- STM32CubeIDE;
- placa NUCLEO-F030R8 e cabo USB, para o teste físico;
- driver do ST-LINK Virtual COM Port, quando necessário.

### Python

- Python 3;
- dependências presentes em `Python/requirements.txt`.

Instale-as a partir da raiz do projeto:

```powershell
python -m pip install -r .\Python\requirements.txt
```

### Emulação opcional

- Renode instalado em `C:\Program Files\Renode`.

## Compilar o firmware

1. Abra o STM32CubeIDE.
2. Selecione **File > Import > General > Existing Projects into Workspace**.
3. Escolha a pasta raiz deste repositório.
4. Execute **Project > Clean**.
5. Execute **Build Project**.

O firmware gerado fica em `Debug/Particle Filter.elf`.

## Executar na placa

1. Compile o projeto e grave o firmware na NUCLEO-F030R8 pelo STM32CubeIDE.
2. Identifique a porta COM do ST-LINK no Gerenciador de Dispositivos do Windows.
3. Feche outros monitores seriais que estejam usando a mesma porta.
4. Na raiz do projeto, execute:

```powershell
python .\Python\comunicacao_uart.py --porta COM3
```

Substitua `COM3` pela porta correspondente à placa. O programa solicita o número de etapas e, em cada etapa:

- deslocamento, em metros;
- ângulo do movimento, em graus;
- distância até as paredes esquerda, direita, inferior e superior, em metros.

Ao final, as respostas da placa são gravadas em `Resultados/resultado_c.csv`.

Se houver somente uma porta serial disponível, ou uma única porta identificada como ST-LINK, também é possível executar sem `--porta`:

```powershell
python .\Python\comunicacao_uart.py
```

## Executar com o Renode

Primeiro compile o firmware no STM32CubeIDE. Em um terminal PowerShell aberto na raiz do projeto, inicie a emulação:

```powershell
.\Renode\iniciar.ps1
```

Mantenha o Renode aberto. Em outro terminal, execute o cliente por TCP:

```powershell
python .\Python\comunicacao_uart.py --tcp localhost:12345
```

O cliente usa o mesmo fluxo de entrada e gera o mesmo arquivo `Resultados/resultado_c.csv` usado no teste com a placa.

## Executar a referência Python

Na raiz do projeto, execute:

```powershell
python .\Python\particle_filter.py
```

Informe o mesmo número de etapas e exatamente as mesmas medições utilizadas no teste do firmware. O resultado será salvo em `Resultados/resultado_python.csv`.

## Comparar os resultados

Depois de gerar os dois CSVs, execute:

```powershell
python .\Python\comparar_resultados.py
```

O comparador verifica:

- a quantidade e a numeração das etapas;
- se as posições medidas são iguais;
- se as estimativas permanecem dentro do mapa;
- a distância entre as estimativas C e Python em cada etapa;
- a diferença máxima e o RMSE do processo completo.

As tolerâncias padrão são:

- primeira etapa: `0,0001 m`;
- etapas seguintes: `0,05 m`.

A tolerância maior depois da primeira etapa considera que as duas implementações utilizam algoritmos de reamostragem equivalentes, mas não necessariamente selecionam as mesmas partículas. O Python preserva a função `systematic_resample` do FilterPy.

Para alterar as tolerâncias no momento do teste:

```powershell
python .\Python\comparar_resultados.py --tolerancia-primeira 0.0001 --tolerancia 0.05
```

O programa termina com código `0` quando a validação passa, `1` quando alguma comparação falha e `2` quando os arquivos ou argumentos são inválidos.

## Fluxo recomendado de validação

1. Execute o firmware na placa ou no Renode com uma sequência de medições.
2. Execute `particle_filter.py` fornecendo a mesma sequência.
3. Execute `comparar_resultados.py`.
4. Verifique a indicação `PASSOU` ou `FALHOU` para cada etapa e para o processo completo.

## Protocolo de comunicação

O cliente envia comandos ASCII terminados por quebra de linha. Para evitar formatação de ponto flutuante no microcontrolador, distâncias são transmitidas em micrômetros e ângulos em miligraus.

```text
RESET
STEP,etapa,deslocamento_um,angulo_mgraus,esquerda_um,direita_um,inferior_um,superior_um
```

Respostas esperadas:

```text
READY
RESULT,etapa,x_medido_um,y_medido_um,x_estimado_um,y_estimado_um
```

Normalmente não é necessário enviar esses comandos manualmente, pois `comunicacao_uart.py` implementa todo o protocolo.
