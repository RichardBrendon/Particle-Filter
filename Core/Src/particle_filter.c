/*
 * Aplicação: Filtro de Partículas para localização 2D de um robô
 * Arquivo: particle_filter.c
 *
 * APRESENTAÇÃO
 * Exemplo didático das etapas de um filtro de partículas: inicialização,
 * predição do movimento, cálculo e normalização dos pesos, estimativa da
 * posição e reamostragem sistemática. O modelo considera um mapa retangular
 * conhecido e quatro sensores simulados voltados às paredes.
 *
 * CONTEXTO E PLATAFORMA
 * Trabalho para a disciplina de SEMB (Sistemas Embarcados).
 * Plataforma alvo: NUCLEO-F030R8, com entrada e saida pela USART2.
 *
 * AUTORES/ESTUDANTES
 * Richard Brendon de Alcântara Pereira
 * Júlio Pereira Brasil
 *
 * DIREITOS DE USO
 * Não foram definidos titulares de copyright nem uma licença. Este aviso
 * não concede licença de uso ou redistribuição.
 *
 * ENTRADA E SAÍDA
 * A cada etapa entram deslocamento (float, metros), ângulo de movimento
 * (float, graus; convertido para radianos) e quatro distâncias (float,
 * metros), na ordem esquerda, direita, inferior e superior. A saída é a
 * posicao estimada (x,y), em metros, retornada para o modulo principal.
 *
 * Data: 30/09/2026.
 */

#include "particle_filter.h"

#include <math.h>
#include <stdint.h>


/* Número de hipóteses de posição e quantidade de sensores simulados. */
#define NUM_PARTICULAS 1000
#define COORDENADA_MAXIMA 4095u

/* Desvios dos ruídos de movimento (m), direção (rad) e sensores (m). */
#define DESVIO_MOVIMENTO 0.08f
#define DESVIO_ANGULO 0.03f
#define DESVIO_SENSOR 0.20f
#define PESO_MINIMO 1.0e-12f
#define PI 3.1415927f
#define SEMENTE_ALEATORIA 12345u

/* Cada partícula é uma hipótese de posição do robô. */
typedef struct {
    uint8_t dados[3];
} Particula;

_Static_assert(sizeof(Particula) == 3u,
               "Particula deve ocupar exatamente tres bytes");

/* Estado principal do filtro. */
typedef struct {
    Particula *particulas;
    Particula *novas_particulas;
    uint32_t estado_aleatorio;
} FiltroParticulas;

/* Estado persistente do filtro em SRAM estática (.bss); variável global de estado. */
static FiltroParticulas filtro;
static Particula populacao_a[NUM_PARTICULAS];
static Particula populacao_b[NUM_PARTICULAS];

/* 
 * Calcula distância ideal da posição (x,y) até a parede indicada.
 * Parâmetros: x e y em metros; sensor 0=esquerda, 1=direita, 2=inferior,
 * 3=superior. Retorno: distância em metros, ou 0 para índice inválido.
 * Globais afetadas: nenhuma.
 */
static float medir_distancia_ideal(float x, float y, int sensor) {
    switch (sensor) {
        case 0:
            return x;
        case 1:
            return MAPA_LARGURA - x;
        case 2:
            return y;
        case 3:
            return MAPA_ALTURA - y;
        default:
            return 0.0f;
    }
}

/* 
 * Limita valor ao intervalo fechado [minimo,maximo]. Parâmetros e retorno
 * usam a unidade de valor. Globais afetadas: nenhuma.
 */
static float limitar(float valor, float minimo, float maximo) {
    if (valor < minimo) {
        return minimo;
    }
    if (valor > maximo) {
        return maximo;
    }
    return valor;
}

static uint16_t codificar_coordenada(float valor, float limite) {
    float limitado = limitar(valor, 0.0f, limite);
    float escalado = limitado * (float)COORDENADA_MAXIMA / limite;
    return (uint16_t)(escalado + 0.5f);
}

static float decodificar_coordenada(uint16_t valor, float limite) {
    return (float)valor * limite / (float)COORDENADA_MAXIMA;
}

static void compactar_particula(Particula *particula, float x, float y) {
    uint16_t x_compactado = codificar_coordenada(x, MAPA_LARGURA);
    uint16_t y_compactado = codificar_coordenada(y, MAPA_ALTURA);

    particula->dados[0] = (uint8_t)x_compactado;
    particula->dados[1] = (uint8_t)(((x_compactado >> 8) & 0x0Fu) |
                                    ((y_compactado & 0x0Fu) << 4));
    particula->dados[2] = (uint8_t)(y_compactado >> 4);
}

static void descompactar_particula(const Particula *particula,
                                   float *x, float *y) {
    uint16_t x_compactado = (uint16_t)particula->dados[0] |
        ((uint16_t)(particula->dados[1] & 0x0Fu) << 8);
    uint16_t y_compactado = ((uint16_t)particula->dados[1] >> 4) |
        ((uint16_t)particula->dados[2] << 4);

    *x = decodificar_coordenada(x_compactado, MAPA_LARGURA);
    *y = decodificar_coordenada(y_compactado, MAPA_ALTURA);
}

/* 
 * Avança o gerador linear congruente armazenado no estado recebido.
 * Parâmetro: ponteiro para o filtro a atualizar. Retorno: próxima palavra
 * pseudoaleatória. Globais afetadas: nenhuma; altera o objeto apontado.
 */
static unsigned int proximo_aleatorio(FiltroParticulas *filtro) {
    filtro->estado_aleatorio =
        1664525u * filtro->estado_aleatorio + 1013904223u;
    return filtro->estado_aleatorio;
}

/* 
 * Gera valor aproximadamente uniforme em [0,1]. Parâmetro: filtro, cujo
 * gerador é avançado. Retorno: amostra float em [0,1]. Globais afetadas:
 * nenhuma; altera somente o objeto apontado.
 */
static float aleatorio_entre_zero_e_um(FiltroParticulas *filtro) {
    return (float)proximo_aleatorio(filtro) / 4294967295.0f;
}

/* 
 * Aproxima uma amostra normal somando 12 amostras uniformes centradas.
 * Parâmetros: filtro (gerador atualizado) e desvio padrão desejado. Retorno:
 * amostra de ruído centrada aproximadamente em zero. Globais afetadas: nenhuma.
 */
static float ruido_normal(FiltroParticulas *filtro, float desvio) {
    float soma = 0.0f;

    for (int i = 0; i < 12; i++) {
        soma += aleatorio_entre_zero_e_um(filtro);
    }

    return (soma - 6.0f) * desvio;
}

/* 
 * Inicializa semente, distribui partículas uniformemente no mapa e atribui
 * pesos iguais. Parâmetro: estado do filtro a preencher. Retorno: nenhum.
 * Globais afetadas: nenhuma diretamente; altera o argumento. main passa a
 * variável global filtro.
 */
static void inicializar_estado(FiltroParticulas *filtro) {
    filtro->particulas = populacao_a;
    filtro->novas_particulas = populacao_b;
    filtro->estado_aleatorio = SEMENTE_ALEATORIA;

    /* Sem uma posicao inicial conhecida, usa prior uniforme no mapa. */
    for (int i = 0; i < NUM_PARTICULAS; i++) {
        float x = aleatorio_entre_zero_e_um(filtro) * MAPA_LARGURA;
        float y = aleatorio_entre_zero_e_um(filtro) * MAPA_ALTURA;
        compactar_particula(&filtro->particulas[i], x, y);
    }
}

/* 
 * Prediz o movimento de cada partícula com ruído de distância e direção e
 * limita suas coordenadas ao mapa. Parâmetros: filtro a atualizar; medicao
 * com deslocamento (m) e direção (rad). Retorno: nenhum. Globais afetadas:
 * nenhuma diretamente; altera o argumento. main passa a global filtro.
 */
static void prever_particulas(FiltroParticulas *filtro,
                              const Medicao *medicao) {
    float angulo = medicao->angulo * PI / 180.0f;

    for (int i = 0; i < NUM_PARTICULAS; i++) {
        float x;
        float y;
        float direcao = angulo +
                        ruido_normal(filtro, DESVIO_ANGULO);
        float distancia = medicao->deslocamento +
                          ruido_normal(filtro, DESVIO_MOVIMENTO);

        descompactar_particula(&filtro->particulas[i], &x, &y);
        x += distancia * cosf(direcao);
        y += distancia * sinf(direcao);
        compactar_particula(&filtro->particulas[i], x, y);
    }
}

/* 
 * Calcula a verossimilhança de uma hipótese usando as diferenças quadráticas
 * entre distâncias previstas e medidas. Parâmetros: partícula candidata e
 * medição dos sensores. Retorno: peso não normalizado (maior indica melhor
 * concordância). Globais afetadas: nenhuma.
 */
static float calcular_peso(const Particula *particula,
                           const Medicao *medicao) {
    float x;
    float y;
    float erro_total = 0.0f;

    descompactar_particula(particula, &x, &y);

    for (int sensor = 0; sensor < NUM_SENSORES; sensor++) {
        float distancia_prevista = medir_distancia_ideal(
            x, y, sensor);
        float erro = distancia_prevista - medicao->sensores[sensor];

        erro_total += erro * erro;
    }

    /* Quanto menor o erro, maior o peso. */
    return expf(-erro_total / (2.0f * DESVIO_SENSOR * DESVIO_SENSOR));
}

static float calcular_soma_e_estimativa(const FiltroParticulas *filtro,
                                        const Medicao *medicao,
                                        Posicao *estimativa) {
    float soma_pesos = 0.0f;
    float soma_x = 0.0f;
    float soma_y = 0.0f;

    for (int i = 0; i < NUM_PARTICULAS; i++) {
        float x;
        float y;
        float peso = calcular_peso(&filtro->particulas[i], medicao);
        descompactar_particula(&filtro->particulas[i], &x, &y);
        soma_pesos += peso;
        soma_x += x * peso;
        soma_y += y * peso;
    }

    if (soma_pesos <= PESO_MINIMO) {
        soma_x = 0.0f;
        soma_y = 0.0f;
        for (int i = 0; i < NUM_PARTICULAS; i++) {
            float x;
            float y;
            descompactar_particula(&filtro->particulas[i], &x, &y);
            soma_x += x;
            soma_y += y;
        }
        estimativa->x = soma_x / (float)NUM_PARTICULAS;
        estimativa->y = soma_y / (float)NUM_PARTICULAS;
    } else {
        estimativa->x = soma_x / soma_pesos;
        estimativa->y = soma_y / soma_pesos;
    }
    return soma_pesos;
}

/* 
 * Reamostra sistematicamente: partículas de maior peso são selecionadas mais
 * vezes e os pesos retornam à distribuição uniforme. Parâmetro: filtro cuja
 * população, pesos e gerador são alterados. Retorno: ponto inicial aleatório
 * da grade sistemática. Globais afetadas: nenhuma diretamente; main passa a
 * global filtro. A segunda populacao compactada fica em memoria estatica.
 */
static void reamostrar(FiltroParticulas *filtro, const Medicao *medicao,
                       float soma_pesos) {
    float aleatorio = aleatorio_entre_zero_e_um(filtro);

    if (soma_pesos <= PESO_MINIMO) {
        for (int i = 0; i < NUM_PARTICULAS; i++) {
            filtro->novas_particulas[i] = filtro->particulas[i];
        }
    } else {
        float passo = soma_pesos / (float)NUM_PARTICULAS;
        float ponto = aleatorio * passo;
        float acumulado = calcular_peso(&filtro->particulas[0], medicao);
        int indice = 0;

        for (int i = 0; i < NUM_PARTICULAS; i++) {
            float alvo = ponto + (float)i * passo;

            while (alvo > acumulado && indice < NUM_PARTICULAS - 1) {
                indice++;
                acumulado += calcular_peso(
                    &filtro->particulas[indice], medicao);
            }
            filtro->novas_particulas[i] = filtro->particulas[indice];
        }
    }

    {
        Particula *temporaria = filtro->particulas;
        filtro->particulas = filtro->novas_particulas;
        filtro->novas_particulas = temporaria;
    }
}

void filtro_inicializar(void) {
    inicializar_estado(&filtro);
}

Posicao filtro_processar(const Medicao *medicao) {
    Posicao estimativa;
    float soma_pesos;

    prever_particulas(&filtro, medicao);
    soma_pesos = calcular_soma_e_estimativa(&filtro, medicao, &estimativa);
    reamostrar(&filtro, medicao, soma_pesos);

    return estimativa;
}
