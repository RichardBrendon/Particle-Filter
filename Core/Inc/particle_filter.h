#ifndef PARTICLE_FILTER_H
#define PARTICLE_FILTER_H

#define NUM_SENSORES 4
#define MAPA_LARGURA 10.0f
#define MAPA_ALTURA 8.0f

typedef struct {
    float deslocamento; /* Metros. */
    float angulo; /* Graus. */
    float sensores[NUM_SENSORES]; /* Esq., dir., inferior e superior; metros. */
} Medicao;

typedef struct {
    float x; /* Metros. */
    float y; /* Metros. */
} Posicao;

/* Reinicia as particulas, os pesos e o gerador pseudoaleatorio. */
void filtro_inicializar(void);

/* Executa previsao, correcao, estimativa e reamostragem de uma etapa. */
Posicao filtro_processar(const Medicao *medicao);

#endif
