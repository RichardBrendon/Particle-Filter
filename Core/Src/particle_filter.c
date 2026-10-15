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
#define COORDENADA_MAXIMA 4095u

/* Desvios dos ruídos de movimento (m), direção (rad) e sensores (m). */
#define DESVIO_MOVIMENTO 0.08f
#define DESVIO_ANGULO 0.03f
#define DESVIO_SENSOR 0.20f
#define PESO_MINIMO 1.0e-12f
#define PI 3.1415927f

/* Representa uma particula durante os calculos, com coordenadas em metros. */
typedef struct {
    float x;
    float y;
} Particula;

/* Representacao persistente compactada: 12 bits para x e 12 bits para y. */
typedef struct {
    uint8_t dados[3];
} ParticulaCompactada;

_Static_assert(sizeof(ParticulaCompactada) == 3u,
               "ParticulaCompactada deve ocupar exatamente tres bytes");

/* Estado principal do filtro. */
typedef struct {
    ParticulaCompactada *particulas;
    ParticulaCompactada *novas_particulas;
    uint32_t estado_aleatorio;
} FiltroParticulas;

/* Estado persistente do filtro em SRAM estática (.bss); variável global de estado. */
static FiltroParticulas filtro;
static ParticulaCompactada populacao_a[NUM_PARTICULAS];
static ParticulaCompactada populacao_b[NUM_PARTICULAS];

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

static void compactar_particula(ParticulaCompactada *destino,
                                const Particula *particula) {
    uint16_t x_compactado = codificar_coordenada(
        particula->x, MAPA_LARGURA);
    uint16_t y_compactado = codificar_coordenada(
        particula->y, MAPA_ALTURA);

    destino->dados[0] = (uint8_t)x_compactado;
    destino->dados[1] = (uint8_t)(((x_compactado >> 8) & 0x0Fu) |
                                  ((y_compactado & 0x0Fu) << 4));
    destino->dados[2] = (uint8_t)(y_compactado >> 4);
}

static void descompactar_particula(const ParticulaCompactada *origem,
                                   Particula *particula) {
    uint16_t x_compactado = (uint16_t)origem->dados[0] |
        ((uint16_t)(origem->dados[1] & 0x0Fu) << 8);
    uint16_t y_compactado = ((uint16_t)origem->dados[1] >> 4) |
        ((uint16_t)origem->dados[2] << 4);

    particula->x = decodificar_coordenada(x_compactado, MAPA_LARGURA);
    particula->y = decodificar_coordenada(y_compactado, MAPA_ALTURA);
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
static void inicializar_estado(FiltroParticulas *filtro, uint32_t semente) {
    filtro->particulas = populacao_a;
    filtro->novas_particulas = populacao_b;
    filtro->estado_aleatorio = semente;

    /* Sem uma posicao inicial conhecida, usa prior uniforme no mapa. */
    for (int i = 0; i < NUM_PARTICULAS; i++) {
        Particula particula;
        particula.x = aleatorio_entre_zero_e_um(filtro) * MAPA_LARGURA;
        particula.y = aleatorio_entre_zero_e_um(filtro) * MAPA_ALTURA;
        compactar_particula(&filtro->particulas[i], &particula);
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
        Particula particula;
        float direcao = angulo +
                        ruido_normal(filtro, DESVIO_ANGULO);
        float distancia = medicao->deslocamento +
                          ruido_normal(filtro, DESVIO_MOVIMENTO);

        descompactar_particula(&filtro->particulas[i], &particula);
        particula.x += distancia * cosf(direcao);
        particula.y += distancia * sinf(direcao);
        compactar_particula(&filtro->particulas[i], &particula);
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
    float erro_total = 0.0f;

    for (int sensor = 0; sensor < NUM_SENSORES; sensor++) {
        float distancia_prevista = medir_distancia_ideal(
            particula->x, particula->y, sensor);
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
        Particula particula;
        float peso;
        descompactar_particula(&filtro->particulas[i], &particula);
        peso = calcular_peso(&particula, medicao);
        soma_pesos += peso;
        soma_x += particula.x * peso;
        soma_y += particula.y * peso;
    }

    if (soma_pesos <= PESO_MINIMO) {
        soma_x = 0.0f;
        soma_y = 0.0f;
        for (int i = 0; i < NUM_PARTICULAS; i++) {
            Particula particula;
            descompactar_particula(&filtro->particulas[i], &particula);
            soma_x += particula.x;
            soma_y += particula.y;
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
 * vezes e os pesos retornam à distribuição uniforme. O ponto inicial e
 * sorteado pelo proprio filtro usando seu gerador pseudoaleatorio. Cada peso
 * e recalculado e normalizado pela soma total quando necessario, sem vetor
 * adicional de pesos. A segunda populacao compactada fica em memoria estatica.
 */
static void reamostrar(FiltroParticulas *filtro, const Medicao *medicao,
                       float soma_pesos) {
    /* Divisao por 2^32 garante um sorteio em [0, 1), sem incluir 1. */
    double amostra_reamostragem = (double)proximo_aleatorio(filtro) / 4294967296.0;
    if (soma_pesos <= PESO_MINIMO) {
        for (int i = 0; i < NUM_PARTICULAS; i++) {
            filtro->novas_particulas[i] = filtro->particulas[i];
        }
    } else {
        Particula particula;
        float acumulado;
        int indice = 0;

        descompactar_particula(&filtro->particulas[0], &particula);
        acumulado = calcular_peso(&particula, medicao) / soma_pesos;

        for (int i = 0; i < NUM_PARTICULAS; i++) {
            double alvo = (amostra_reamostragem + (double)i) /
                          (double)NUM_PARTICULAS;

            while (alvo >= acumulado && indice < NUM_PARTICULAS - 1) {
                indice++;
                descompactar_particula(
                    &filtro->particulas[indice], &particula);
                acumulado += calcular_peso(&particula, medicao) / soma_pesos;
            }
            filtro->novas_particulas[i] = filtro->particulas[indice];
        }
    }

    {
        ParticulaCompactada *temporaria = filtro->particulas;
        filtro->particulas = filtro->novas_particulas;
        filtro->novas_particulas = temporaria;
    }
}

void filtro_inicializar(uint32_t semente) {
    inicializar_estado(&filtro, semente);
}

Posicao filtro_processar(const Medicao *medicao) {
    Posicao estimativa;
    float soma_pesos;

    prever_particulas(&filtro, medicao);
    soma_pesos = calcular_soma_e_estimativa(&filtro, medicao, &estimativa);
    reamostrar(&filtro, medicao, soma_pesos);

    return estimativa;
}
