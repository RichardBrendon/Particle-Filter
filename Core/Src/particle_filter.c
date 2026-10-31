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
 * Plataforma alvo: NUCLEO-F030R8, com entrada e saída pela USART2.
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
 * posição estimada (x,y), em metros, retornada para o módulo principal.
 *
 * Data: 30/09/2026.
 */

#include "particle_filter.h"

#include <math.h>
#include <stdint.h>


/* Configuração interna: representação compactada e parâmetros do modelo.
 * NUM_PARTICULAS, NUM_SENSORES e dimensões do mapa ficam no cabeçalho. */

/* Maior inteiro representável em 12 bits: coordenadas entre 0 e 4095. */
#define COORDENADA_MAXIMA 4095u

/* Desvios dos ruídos de movimento (m), direção (rad) e sensores (m). */
#define DESVIO_MOVIMENTO 0.08f
#define DESVIO_ANGULO 0.03f
#define DESVIO_SENSOR 0.20f
/* Limite da soma dos pesos para adotar a distribuição uniforme de segurança. */
#define PESO_MINIMO 1.0e-12f
#define PI 3.1415927f

/* Representa uma partícula durante os cálculos, com coordenadas em metros. */
/* Apenas variáveis temporárias usam este formato; não existe vetor de floats. */
typedef struct {
    float x;
    float y;
} Particula;

/* Representação persistente compactada: 12 bits para x e 12 bits para y. */
typedef struct {
    uint8_t dados[3];
} ParticulaCompactada;

/* Estado principal do filtro. */
/* Os ponteiros alternam entre as duas populações depois da reamostragem.
 * O estado do gerador pertence ao filtro e é reiniciado com a semente recebida. */
typedef struct {
    ParticulaCompactada *particulas;
    ParticulaCompactada *novas_particulas;
    uint32_t estado_aleatorio;
} FiltroParticulas;

/* Estado persistente do filtro em SRAM estática (.bss); variável global de estado. */
static FiltroParticulas filtro;
/* Duas populações de 1000 partículas ocupam 6000 bytes, sem alocação dinâmica.
 * A população de origem é preservada enquanto a de destino é preenchida. */
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

/* Conversão entre metros e a grade de 4096 valores por eixo.
 * Primeiro restringe ao mapa, depois arredonda ao inteiro mais próximo.
 * A compactação introduz quantização: o passo de cada eixo é limite / 4095. */
static uint16_t codificar_coordenada(float valor, float limite) {
    float limitado = limitar(valor, 0.0f, limite);
    float escalado = limitado * (float)COORDENADA_MAXIMA / limite;
    return (uint16_t)(escalado + 0.5f);
}

/* Recupera em metros o ponto da grade, não necessariamente o float original. */
static float decodificar_coordenada(uint16_t valor, float limite) {
    return (float)valor * limite / (float)COORDENADA_MAXIMA;
}

/* Distribuição dos 24 bits nos três bytes:
 * dados[0]: x[7:0]; dados[1]: y[3:0] nos bits altos e x[11:8] nos baixos;
 * dados[2]: y[11:4]. As operações explícitas evitam depender de bit-fields. */
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

/* Reconstrói os dois inteiros de 12 bits e entrega coordenadas para cálculo. */
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
    /* A aritmética sem sinal de 32 bits implementa o módulo 2^32 do gerador.
     * Mesma semente e mesma ordem de chamadas reproduzem a mesma sequência. */
    filtro->estado_aleatorio =
        1664525u * filtro->estado_aleatorio + 1013904223u;
    /* Constantes matemáticas utilizadas em um algoritmo chamado Gerador Congruencial Linear (LCG – Linear Congruential Generator).
     * Esse algoritmo gera uma sequência de números pseudoaleatórios por meio de uma fórmula matemática.
     * Essas duas constantes (1664525 e 1013904223) são conhecidas por serem utilizadas no LCG associado a Numerical Recipes.
     * Verificável em https://en.wikipedia.org/wiki/Linear_congruential_generator
     */
    return filtro->estado_aleatorio;
}

/* 
 * Gera valor aproximadamente uniforme em [0,1]. Parâmetro: filtro, cujo
 * gerador é avançado. Retorno: amostra float em [0,1]. Globais afetadas:
 * nenhuma; altera somente o objeto apontado.
 */
static float aleatorio_entre_zero_e_um(FiltroParticulas *filtro) {
    return (float)proximo_aleatorio(filtro) / 4294967295.0f;
    /* 
     * Para isso, é utilizada a operação R = X/(2^32 - 1), onde R é o valor em [0,1] e
     * X o proximo_aleatorio.
     * A constante 4294967295 vem de 2^32 - 1, pois 4294967296 - 1 = 4294967295.
     */
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

    /* Doze uniformes ideais têm soma com média 6 e variância 1.
     * A aproximação é limitada, não uma distribuição normal exata. */
    return (soma - 6.0f) * desvio;
}

/* 
 * Inicializa semente e distribui partículas uniformemente no mapa; os pesos
 * iniciais iguais são implícitos, sem vetor armazenado. Parâmetros: estado
 * do filtro a preencher e semente. Retorno: nenhum. Altera o estado recebido
 * e a populacao_a estática, referenciada por esse estado.
 */
static void inicializar_estado(FiltroParticulas *filtro, uint32_t semente) {
    filtro->particulas = populacao_a;
    filtro->novas_particulas = populacao_b;
    filtro->estado_aleatorio = semente;

    /* Sem uma posição inicial conhecida, usa prior uniforme no mapa. */
    for (int i = 0; i < NUM_PARTICULAS; i++) {
        Particula particula;
        particula.x = aleatorio_entre_zero_e_um(filtro) * MAPA_LARGURA;
        particula.y = aleatorio_entre_zero_e_um(filtro) * MAPA_ALTURA;
        compactar_particula(&filtro->particulas[i], &particula);
    }
}

/* 
 * Prediz o movimento de cada partícula com ruído de distância e direção e
 * limita suas coordenadas ao mapa. Parâmetros: filtro a atualizar; medição
 * com deslocamento (m) e direção (graus). Retorno: nenhum. Globais afetadas:
 * nenhuma diretamente; altera o argumento. main passa a global filtro.
 */
static void prever_particulas(FiltroParticulas *filtro,
                              const Medicao *medicao) {
    float angulo = medicao->angulo * PI / 180.0f;

    for (int i = 0; i < NUM_PARTICULAS; i++) {
        Particula particula;
        /* A ordem dos sorteios importa para reproduzir o movimento no Python:
         * primeiro o ruído angular, depois o ruído de deslocamento. */
        float direcao = angulo +
                        ruido_normal(filtro, DESVIO_ANGULO);
        float distancia = medicao->deslocamento +
                          ruido_normal(filtro, DESVIO_MOVIMENTO);

        descompactar_particula(&filtro->particulas[i], &particula);
        particula.x += distancia * cosf(direcao);
        particula.y += distancia * sinf(direcao);
        /* Ao salvar, também restringe ao mapa e quantiza as coordenadas. */
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
    /* Modelo de erros gaussianos independentes, com mesmo desvio nos sensores.
     * O fator multiplicativo comum da densidade cancela na normalização. */
    return expf(-erro_total / (2.0f * DESVIO_SENSOR * DESVIO_SENSOR));
}

/* Atualização pelos sensores e estimativa da posição, antes da reamostragem.
 * Duas passagens trocam processamento por economia de SRAM: não há vetor de
 * pesos. Retorna a soma não normalizada para reutilização na reamostragem;
 * a posição devolvida por ponteiro usa os pesos normalizados. */
static float calcular_soma_e_estimativa(const FiltroParticulas *filtro,
                                        const Medicao *medicao,
                                        Posicao *estimativa) {
    float soma_pesos = 0.0f;
    float soma_x = 0.0f;
    float soma_y = 0.0f;

    /* Primeira passagem: calcula o denominador comum da normalização. */
    for (int i = 0; i < NUM_PARTICULAS; i++) {
        Particula particula;
        descompactar_particula(&filtro->particulas[i], &particula);
        soma_pesos += calcular_peso(&particula, medicao);
    }

    /* Normaliza cada peso antes de multiplicar e somar.
     * Recalcula os pesos nesta segunda passagem para não guardar um vetor. */
    for (int i = 0; i < NUM_PARTICULAS; i++) {
        Particula particula;
        float peso_normalizado;
        descompactar_particula(&filtro->particulas[i], &particula);
        if (soma_pesos <= PESO_MINIMO) {
            /* Sem evidência numericamente suficiente, nenhuma hipótese e
             * favorecida: evita dividir por uma soma nula ou muito pequena. */
            peso_normalizado = 1.0f / (float)NUM_PARTICULAS;
        } else {
            peso_normalizado = calcular_peso(&particula, medicao) / soma_pesos;
        }
        /* Média ponderada das coordenadas, na mesma ordem das partículas. */
        soma_x += particula.x * peso_normalizado;
        soma_y += particula.y * peso_normalizado;
    }
    estimativa->x = soma_x;
    estimativa->y = soma_y;
    return soma_pesos;
}

/* 
 * Reamostra sistematicamente: partículas de maior peso são selecionadas mais
 * vezes e os pesos retornam à distribuição uniforme. O ponto inicial e
 * sorteado pelo próprio filtro usando seu gerador pseudoaleatório. Cada peso
 * é recalculado e normalizado pela soma total quando necessário, sem vetor
 * adicional de pesos. A segunda população compactada fica em memória estática.
 */
static void reamostrar(FiltroParticulas *filtro, const Medicao *medicao,
                       float soma_pesos) {
    /* Divisão por 2^32 garante um sorteio em [0, 1), sem incluir 1. */
    double amostra_reamostragem = (double)proximo_aleatorio(filtro) / 4294967296.0;
    if (soma_pesos <= PESO_MINIMO) {
        /* Com pesos uniformes e N pontos sistemáticos, cada partícula aparece
         * uma vez. Copiar a população implementa esse caso diretamente. */
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

            /* Pontos igualmente espaçados em 1/N, com deslocamento comum u/N.
             * acumulado é a CDF dos pesos normalizados. Como os alvos crescem,
             * índice só avança: a busca completa é linear, não quadrática.
             * O limite do índice protege o acesso contra arredondamentos da CDF. */
            while (alvo >= acumulado && indice < NUM_PARTICULAS - 1) {
                indice++;
                descompactar_particula(
                    &filtro->particulas[indice], &particula);
                acumulado += calcular_peso(&particula, medicao) / soma_pesos;
            }
            /* Copia a representação compactada sem nova quantização.
             * A mesma origem pode ser selecionada para vários destinos. */
            filtro->novas_particulas[i] = filtro->particulas[indice];
        }
    }

    /* Troca apenas os ponteiros: a população pronta passa a ser a atual.
     * A antiga origem será reaproveitada como destino na próxima etapa.
     * Os pesos após reamostrar são iguais e permanecem implícitos. */
    {
        ParticulaCompactada *temporaria = filtro->particulas;
        filtro->particulas = filtro->novas_particulas;
        filtro->novas_particulas = temporaria;
    }
}

/* Interface pública: reinicia o único filtro mantido por este módulo.
 * Deve ser chamada antes de processar a primeira medição de cada teste. */
void filtro_inicializar(uint32_t semente) {
    inicializar_estado(&filtro, semente);
}

/* Executa uma etapa completa. A medição deve apontar para uma entrada válida;
 * validação de entrada e comunicação ficam a cargo do chamador. */
Posicao filtro_processar(const Medicao *medicao) {
    Posicao estimativa;
    float soma_pesos;

    /* 1. Predição: aplica deslocamento e ruído a todas as hipóteses. */
    prever_particulas(&filtro, medicao);
    /* 2. Atualização: compara sensores e calcula a média ponderada. */
    soma_pesos = calcular_soma_e_estimativa(&filtro, medicao, &estimativa);
    /* 3. Reamostragem: prepara a população para uma eventual próxima etapa. */
    reamostrar(&filtro, medicao, soma_pesos);

    /* A estimativa é anterior à reamostragem; o sorteio desta etapa não altera
     * a posição retornada. Em testes independentes, o próximo teste reinicia. */
    return estimativa;
}
