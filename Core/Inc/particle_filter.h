#ifndef PARTICLE_FILTER_H
#define PARTICLE_FILTER_H

#include <stdint.h>

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

/* Reinicia particulas e gerador pseudoaleatorio com a semente recebida do PC. */
void filtro_inicializar(uint32_t semente);

/* Executa uma etapa, incluindo o sorteio e a reamostragem no proprio filtro. */
Posicao filtro_processar(const Medicao *medicao);

#endif
