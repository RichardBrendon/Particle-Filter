/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "particle_filter.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART2_UART_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* Comunicação entre o PC e o filtro embarcado.
 * Cada comando é uma linha de texto terminada em '\n'; os campos usam vírgulas.
 * O PC controla os testes: envia RESET,semente e depois STEP para cada teste
 * independente. Este módulo converte as unidades, chama o filtro e responde;
 * a geração dos cenários e a gravação dos CSVs ficam no PC.
 * Mantenha as marcações USER CODE: elas delimitam áreas preservadas pelo CubeMX. */

/* Capacidade inclui o terminador '\0'. Valores do protocolo são inteiros:
 * distâncias em micrômetros (1 m = 1000000) e ângulos em milésimos de grau. */
#define UART_LINHA_TAMANHO 160
#define ESCALA_METROS 1000000.0f
#define ESCALA_ANGULO 1000.0f

/* Envio bloqueante pela USART2. O texto deve terminar em '\0'; esse terminador
 * não é transmitido. HAL_MAX_DELAY aguarda a conclusão sem timeout finito. */
static void uart_enviar(const char *texto)
{
  HAL_UART_Transmit(&huart2, (const uint8_t *)texto,
                    (uint16_t)strlen(texto), HAL_MAX_DELAY);
}

/* Recebe uma linha sem guardar '\r' ou '\n', aceitando finais LF e CRLF.
 * Retornos: 1 = linha completa; 0 = falha na UART; -1 = linha muito longa.
 * O chamador fornece um buffer com capacidade para dados e terminador. */
static int uart_receber_linha(char *linha, size_t capacidade)
{
  size_t indice = 0;
  uint8_t caractere;

  while (1)
  {
    if (HAL_UART_Receive(&huart2, &caractere, 1, HAL_MAX_DELAY) != HAL_OK)
    {
      return 0;
    }
    if (caractere == '\r')
    {
      continue;
    }
    if (caractere == '\n')
    {
      linha[indice] = '\0';
      return 1;
    }
    if (indice + 1 >= capacidade)
    {
      /* Descarta o restante até '\n' para que a próxima leitura comece em um
       * novo comando, em vez de interpretar o trecho excedente como comando. */
      linha[0] = '\0';
      do
      {
        if (HAL_UART_Receive(&huart2, &caractere, 1, HAL_MAX_DELAY) != HAL_OK)
        {
          return 0;
        }
      } while (caractere != '\n');
      return -1;
    }
    linha[indice++] = (char)caractere;
  }
}

/* Converte um campo decimal com sinal, exigindo consumo de todo o texto.
 * Não verifica explicitamente overflow de strtol nem a faixa de int32_t;
 * o cliente deve enviar valores representáveis no protocolo de 32 bits. */
static int ler_inteiro(const char *texto, int32_t *valor)
{
  char *fim;
  long convertido = strtol(texto, &fim, 10);

  if (texto == fim || *fim != '\0')
  {
    return 0;
  }
  *valor = (int32_t)convertido;
  return 1;
}

/* A semente aceita apenas dígitos, de 0 a UINT32_MAX, sem sinal.
 * A verificação antes de multiplicar evita overflow durante a conversão. */
static int ler_semente(const char *texto, uint32_t *valor)
{
  uint32_t convertido = 0;
  if (*texto == '\0')
  {
    return 0;
  }
  while (*texto != '\0')
  {
    unsigned int digito;
    if (*texto < '0' || *texto > '9')
    {
      return 0;
    }
    digito = (unsigned int)(*texto - '0');
    if (convertido > (UINT32_MAX - digito) / 10u)
    {
      return 0;
    }
    convertido = convertido * 10u + digito;
    texto++;
  }
  *valor = convertido;
  return 1;
}

/* Converte metros para a unidade inteira da resposta, arredondando ao inteiro
 * mais próximo; empates são afastados de zero. Evita formatar floats na UART. */
static int32_t metros_para_inteiro(float valor)
{
  float escalado = valor * ESCALA_METROS;
  return (int32_t)(escalado + (escalado >= 0.0f ? 0.5f : -0.5f));
}

/* Formato: STEP,etapa,deslocamento,angulo,esquerda,direita,inferior,superior.
 * Recebe sete inteiros nas escalas definidas acima. strtok modifica a linha.
 * Retorna 0 se não for STEP; retorna 1 se reconhecido, inclusive com erro.
 * O número da etapa identifica a resposta; não controla quantas vezes rodar. */
static int processar_step(char *linha)
{
  int32_t valores[7];
  char *token = strtok(linha, ",");
  char resposta[128];
  Medicao medicao;
  Posicao estimativa;
  float x_medido;
  float y_medido;

  if (token == NULL || strcmp(token, "STEP") != 0)
  {
    return 0;
  }

  /* Exige sete tokens numéricos e rejeita tokens adicionais. */
  for (int i = 0; i < 7; i++)
  {
    token = strtok(NULL, ",");
    if (token == NULL || !ler_inteiro(token, &valores[i]))
    {
      uart_enviar("ERROR,CAMPOS_INVALIDOS\n");
      return 1;
    }
  }
  if (strtok(NULL, ",") != NULL)
  {
    uart_enviar("ERROR,CAMPOS_INVALIDOS\n");
    return 1;
  }

  /* O filtro trabalha com floats em metros e graus, não com inteiros UART. */
  medicao.deslocamento = (float)valores[1] / ESCALA_METROS;
  medicao.angulo = (float)valores[2] / ESCALA_ANGULO;
  for (int i = 0; i < NUM_SENSORES; i++)
  {
    medicao.sensores[i] = (float)valores[i + 3] / ESCALA_METROS;
  }

  /* Verifica etapa positiva e limites individuais dos quatro sensores.
   * Não exige que sensores opostos somem exatamente a dimensão do mapa. */
  if (valores[0] < 1 ||
      valores[3] < 0 || valores[3] > (int32_t)(MAPA_LARGURA * ESCALA_METROS) ||
      valores[4] < 0 || valores[4] > (int32_t)(MAPA_LARGURA * ESCALA_METROS) ||
      valores[5] < 0 || valores[5] > (int32_t)(MAPA_ALTURA * ESCALA_METROS) ||
      valores[6] < 0 || valores[6] > (int32_t)(MAPA_ALTURA * ESCALA_METROS))
  {
    uart_enviar("ERROR,VALORES_FORA_DO_MAPA\n");
    return 1;
  }

  /* Executa predição, atualização dos pesos, estimativa e reamostragem. */
  estimativa = filtro_processar(&medicao);
  /* Posição medida: média das duas indicações de cada eixo. É informativa
   * na resposta; o filtro recebe diretamente as quatro distâncias acima. */
  x_medido = (medicao.sensores[0] +
              (MAPA_LARGURA - medicao.sensores[1])) / 2.0f;
  y_medido = (medicao.sensores[2] +
              (MAPA_ALTURA - medicao.sensores[3])) / 2.0f;

  /* RESULT,etapa,x_medido,y_medido,x_estimado,y_estimado.
   * Todas as coordenadas retornam como inteiros em micrômetros; o PC as
   * converte em metros para apresentação e armazenamento nos CSVs. */
  (void)snprintf(resposta, sizeof(resposta),
                 "RESULT,%ld,%ld,%ld,%ld,%ld\n",
                 (long)valores[0],
                 (long)metros_para_inteiro(x_medido),
                 (long)metros_para_inteiro(y_medido),
                 (long)metros_para_inteiro(estimativa.x),
                 (long)metros_para_inteiro(estimativa.y));
  uart_enviar(resposta);
  return 1;
}

/* Lê e atende um comando por chamada. As respostas de erro encerram apenas
 * esse atendimento; o laço principal continua disponível para novos comandos. */
static void processar_comando_uart(void)
{
  char linha[UART_LINHA_TAMANHO];
  int estado = uart_receber_linha(linha, sizeof(linha));

  if (estado < 0)
  {
    uart_enviar("ERROR,LINHA_MUITO_LONGA\n");
    return;
  }
  if (estado == 0)
  {
    uart_enviar("ERROR,UART\n");
    return;
  }
  if (strncmp(linha, "RESET,", 6) == 0)
  {
    /* Reinicia partículas e gerador com a semente escolhida pelo PC.
     * O PC registra essa semente para reprodução pela referência Python. */
    uint32_t semente;
    if (!ler_semente(linha + 6, &semente))
    {
      uart_enviar("ERROR,SEMENTE_INVALIDA\n");
      return;
    }
    filtro_inicializar(semente);
    uart_enviar("READY\n");
    return;
  }
  if (strcmp(linha, "RESET") == 0)
  {
    /* Forma sem argumento: reinicialização determinística com semente zero. */
    filtro_inicializar(0u);
    uart_enviar("READY\n");
    return;
  }
  if (strcmp(linha, "PING") == 0)
  {
    /* Testa a comunicação sem alterar o estado do filtro. */
    uart_enviar("PONG\n");
    return;
  }
  if (strcmp(linha, "INFO") == 0)
  {
    /* Informa largura e altura em micrômetros, número de partículas e sensores.
     * Permite ao cliente consultar a configuração compilada no firmware. */
    char resposta[64];
    (void)snprintf(resposta, sizeof(resposta),
                   "INFO,%ld,%ld,%u,%u\n",
                   (long)(MAPA_LARGURA * ESCALA_METROS),
                   (long)(MAPA_ALTURA * ESCALA_METROS),
                   (unsigned int)NUM_PARTICULAS,
                   (unsigned int)NUM_SENSORES);
    uart_enviar(resposta);
    return;
  }
  if (!processar_step(linha))
  {
    uart_enviar("ERROR,COMANDO_DESCONHECIDO\n");
  }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{
  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
  /* Estado inicial válido mesmo antes do primeiro RESET do PC.
   * READY sinaliza que a inicialização terminou e comandos podem ser enviados. */
  filtro_inicializar(0u);
  uart_enviar("READY\n");

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* Atendimento síncrono: espera uma linha, processa e envia a resposta.
     * Não há fila de testes no firmware; o cliente coordena cada solicitação. */
    processar_comando_uart();
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL12;
  RCC_OscInitStruct.PLL.PREDIV = RCC_PREDIV_DIV1;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USART2: 115200 baud, 8 bits, sem paridade, 1 bit de parada (8N1),
   * transmissão e recepção habilitadas, sem controle de fluxo por hardware.
   * O cliente no PC precisa usar os mesmos parâmetros. */
  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  huart2.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart2.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : B1_Pin */
  GPIO_InitStruct.Pin = B1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(B1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : LD2_Pin */
  GPIO_InitStruct.Pin = LD2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LD2_GPIO_Port, &GPIO_InitStruct);

}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* Falha de inicialização: interrompe a execução normal e permanece parado.
   * Diferentemente de ERROR no protocolo, este caminho não retorna ao laço UART. */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
