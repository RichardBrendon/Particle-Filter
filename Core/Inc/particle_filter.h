#ifndef PARTICLE_FILTER_H
#define PARTICLE_FILTER_H

#define NUM_SENSORES 4
#define NUM_PARTICULAS 1000
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

/* Executa uma etapa; amostra_reamostragem e o sorteio enviado pelo PC em [0, 1). */
Posicao filtro_processar(const Medicao *medicao, double amostra_reamostragem);

#endif
