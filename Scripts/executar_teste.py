# Executor do fluxo completo: cliente UART, referência Python e comparação.
# Uma única entrada é reutilizada em N testes independentes de uma etapa.
# Também fornece funções compartilhadas pelos executores individuais.

import argparse
import csv
import math
import re
import secrets
import subprocess
import sys
from pathlib import Path

# Resolve caminhos pela localização do script, não pelo diretório do terminal.
# Inclui a raiz na busca de módulos para importar Python.medicoes e Scripts.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from Python.medicoes import (
    CAMPOS_MEDICAO, ESCALA_ANGULO, ESCALA_METROS, LIMITES_SENSORES, criar_medicao,
)

# Conversor usado pelo argparse e pelo menu: aceita apenas inteiros positivos.
def inteiro_positivo(texto):
    try:
        valor = int(texto)
    except ValueError as erro:
        raise argparse.ArgumentTypeError("Informe um numero inteiro positivo.") from erro
    if valor <= 0:
        raise argparse.ArgumentTypeError("Informe um numero inteiro positivo.")
    return valor


# Repete a pergunta até receber uma quantidade válida, independente do cenário.
def ler_quantidade():
    while True:
        try:
            return inteiro_positivo(input("Numero de testes: ").strip())
        except argparse.ArgumentTypeError as erro:
            print(erro)


# Apresenta opções numeradas a partir de 1 e só retorna uma seleção existente.
def escolher_opcao(titulo, opcoes):
    print(titulo)
    for numero, descricao in enumerate(opcoes, start=1):
        print(f"{numero} - {descricao}")
    while True:
        escolha = input("Opcao: ").strip()
        if escolha in {str(i) for i in range(1, len(opcoes) + 1)}:
            return int(escolha)
        print("Escolha uma das opcoes listadas.")


# Lê um número finito. Quando há limite, exige o intervalo fechado [0, limite].
def ler_valor(mensagem, limite=None):
    while True:
        try:
            valor = float(input(mensagem))
            if not math.isfinite(valor):
                raise ValueError
            if limite is not None and not 0 <= valor <= limite:
                raise ValueError
            return valor
        except ValueError:
            print(f"Informe um numero finito entre 0 e {limite}." if limite is not None
                  else "Informe um numero finito.")


# Solicita a entrada uma única vez e valida as unidades pelo módulo medicoes.
# A quantidade serve à mensagem; esta função retorna somente uma medição.
def medicoes_manuais(quantidade):
    nomes = ("esquerda", "direita", "inferior", "superior")
    while True:
        print(f"\nInforme uma unica entrada para os {quantidade} testes | Etapa 1 de 1")
        deslocamento = ler_valor("Deslocamento (m): ")
        angulo = ler_valor("Angulo do movimento (graus): ")
        sensores = [ler_valor(f"Distancia ate a parede {nome} (m): ", limite)
                    for nome, limite in zip(nomes, LIMITES_SENSORES)]
        try:
            medicao = criar_medicao(1, deslocamento, angulo, sensores)
            return medicao
        except ValueError as erro:
            print(f"Entrada invalida: {erro}. Informe novamente a entrada.")


# Sorteia uma única entrada ideal compatível com o mapa, não N entradas.
# O parâmetro quantidade é mantido na interface, mas não participa do sorteio;
# a repetição dessa entrada é realizada posteriormente pelos programas filhos.
# O gerador do sistema operacional é independente das sementes das partículas.
def gerar_medicoes(quantidade):
    aleatorio = secrets.SystemRandom()
    largura, altura = LIMITES_SENSORES[0], LIMITES_SENSORES[2]
    deslocamento_um = aleatorio.randint(0, 2 * ESCALA_METROS)
    angulo_mgraus = aleatorio.randrange(360 * ESCALA_ANGULO)
    deslocamento = deslocamento_um / ESCALA_METROS
    angulo = angulo_mgraus / ESCALA_ANGULO
    dx = deslocamento * math.cos(math.radians(angulo))
    dy = deslocamento * math.sin(math.radians(angulo))
    # A origem implícita e a posição final devem caber no mapa. Os intervalos
    # abaixo garantem que tanto (x, y) quanto (x - dx, y - dy) estejam dentro
    # do retângulo, com posições sorteadas na resolução de micrômetros.
    x_um = aleatorio.randint(math.ceil(max(0, dx) * ESCALA_METROS),
                             math.floor(min(largura, largura + dx) * ESCALA_METROS))
    y_um = aleatorio.randint(math.ceil(max(0, dy) * ESCALA_METROS),
                             math.floor(min(altura, altura + dy) * ESCALA_METROS))
    x, y = x_um / ESCALA_METROS, y_um / ESCALA_METROS
    # Sensores ideais opostos somam exatamente a dimensão do respectivo eixo,
    # respeitada a conversão às unidades inteiras feita por criar_medicao.
    medicao = criar_medicao(1, deslocamento, angulo, (x, largura - x, y, altura - y))
    return medicao


# Salva cabeçalho e uma única linha em Dados_Teste/ na raiz do projeto.
# Escolhe o primeiro nome livre cenario_N.csv; N identifica o cenário, não
# a quantidade de testes. Entradas manuais e automáticas usam a mesma sequência.
def salvar_cenario(medicao):
    diretorio = RAIZ_PROJETO / "Dados_Teste"
    diretorio.mkdir(exist_ok=True)
    numero_cenario = 1
    while True:
        caminho = diretorio / f"cenario_{numero_cenario}.csv"
        try:
            # Criação exclusiva impede sobrescrita, inclusive em execuções simultâneas.
            arquivo_cenario = caminho.open("x", newline="", encoding="utf-8")
            break
        except FileExistsError:
            numero_cenario += 1
    with arquivo_cenario as arquivo:
        caminho = Path(arquivo.name)
        escritor = csv.writer(arquivo)
        escritor.writerow(CAMPOS_MEDICAO)
        escritor.writerow(medicao.campos_entrada())
    return caminho


# Aceita identificador numérico, nome com ou sem .csv ou caminho de arquivo.
# Nomes simples priorizam Dados_Teste/ e depois a raiz; caminhos relativos com
# diretório são resolvidos pela raiz do projeto. Retorna um caminho absoluto.
def resolver_cenario(cenario):
    if re.fullmatch(r"\d+", cenario):
        caminho = RAIZ_PROJETO / "Dados_Teste" / f"cenario_{cenario}.csv"
    else:
        caminho = Path(cenario)
        if not caminho.suffix:
            caminho = caminho.with_suffix(".csv")
        if not caminho.is_absolute() and caminho.parent == Path("."):
            nome = caminho
            caminho = RAIZ_PROJETO / "Dados_Teste" / nome
            if not caminho.is_file() and (RAIZ_PROJETO / nome).is_file():
                caminho = RAIZ_PROJETO / nome
        elif not caminho.is_absolute():
            caminho = RAIZ_PROJETO / caminho
    if not caminho.is_file():
        raise ValueError(f"Cenario nao encontrado: {caminho}")
    return caminho.resolve()


# Inicia um programa de Python/ com o mesmo interpretador do executor.
# check=True interrompe a sequência se o processo filho terminar com erro.
# Não inicia o Renode e não compila nem grava o firmware na placa.
def executar_python(descricao, arquivo, argumentos=()):
    print(f"\n== {descricao} ==", flush=True)
    subprocess.run(
        [sys.executable, str(RAIZ_PROJETO / "Python" / arquivo), *argumentos],
        check=True,
    )


# Coordena menu ou argumentos diretos. apenas_c reutiliza a preparação e a
# comunicação, mas omite a referência e a comparação no executor dedicado ao C.
# Retorna 0 ao concluir e 1 em falhas ou cancelamento.
def main(apenas_c=False):
    descricao = "Executa apenas o filtro C pela UART ou pelo Renode." if apenas_c else "Executa o cliente UART, a referencia Python e a comparacao dos testes."
    analisador = argparse.ArgumentParser(description=descricao)
    entrada = analisador.add_mutually_exclusive_group()
    entrada.add_argument("--cenario", help="identificador do cenario, nome em Dados_Teste (com ou sem .csv) ou caminho")
    entrada.add_argument("--manual", action="store_true", help="digitar as entradas uma unica vez")
    entrada.add_argument("--gerar-testes", type=inteiro_positivo, metavar="N",
                         help="gerar e salvar N testes independentes automaticamente")
    analisador.add_argument("--testes", type=inteiro_positivo, metavar="N",
                            help="quantidade de repeticoes da unica entrada do cenario")
    analisador.add_argument("--modo", type=str.lower, choices=("renode", "placa"))
    analisador.add_argument("--porta", help="porta da placa, por exemplo COM3")
    analisador.add_argument("--endereco-renode", default="localhost:12345", help="HOST:PORTA do Renode")
    try:
        argumentos = analisador.parse_args()
    except SystemExit as erro:
        return 0 if erro.code == 0 else 1
    try:
        # Sem modo de entrada explícito, abre o menu. As três fontes de entrada
        # são alternativas: manual, CSV existente ou geração automática.
        menu = not (argumentos.cenario or argumentos.manual or argumentos.gerar_testes)
        if menu:
            escolha = escolher_opcao("Entrada dos testes:", (
                "Manual", "Executar CSV existente", "Gerar dados automaticamente"))
            if escolha == 1:
                argumentos.manual = True
            elif escolha == 2:
                argumentos.cenario = input("Cenario (numero, nome com ou sem .csv, ou caminho): ").strip()
                if argumentos.testes is None:
                    argumentos.testes = ler_quantidade()
            else:
                argumentos.gerar_testes = argumentos.testes or ler_quantidade()
        # Pelo menu, pergunta o destino; por comando direto, assume Renode.
        # A detecção de porta serial omitida é responsabilidade do cliente UART.
        if argumentos.modo is None:
            if menu:
                destino = escolher_opcao("Onde executar o filtro C:", ("Renode", "Placa"))
                argumentos.modo = "renode" if destino == 1 else "placa"
            else:
                argumentos.modo = "renode"
        if argumentos.modo == "renode" and argumentos.porta:
            raise ValueError("Use --porta somente com --modo placa.")
        if menu and argumentos.modo == "placa" and not argumentos.porta:
            argumentos.porta = input("Porta (ex.: COM3; Enter para detectar): ").strip()
        # Modos manual e automático criam um cenário; o modo CSV apenas lê um
        # existente. A quantidade escolhida não é inferida do nome do arquivo.
        if argumentos.manual:
            quantidade = argumentos.testes or ler_quantidade()
            cenario = salvar_cenario(medicoes_manuais(quantidade))
        elif argumentos.gerar_testes:
            quantidade = argumentos.gerar_testes
            if argumentos.testes is not None and argumentos.testes != quantidade:
                raise ValueError("--testes deve coincidir com --gerar-testes.")
            cenario = salvar_cenario(gerar_medicoes(quantidade))
        else:
            cenario = resolver_cenario(argumentos.cenario)
            quantidade = argumentos.testes or ler_quantidade()
        print(f"Cenario: {cenario.name}\nModo: {argumentos.modo}", flush=True)
        # Encaminha exatamente o mesmo arquivo e quantidade ao C e ao Python.
        # O cliente UART registra as sementes que a referência reproduzirá.
        entradas = ["--entradas", str(cenario), "--testes", str(quantidade)]
        cliente = entradas.copy()
        if argumentos.modo == "renode":
            cliente += ["--tcp", argumentos.endereco_renode]
        elif argumentos.porta:
            cliente += ["--porta", argumentos.porta]
        # Ordem obrigatória: executar C, reproduzir no Python e comparar CSVs.
        # Uma reprovação relatada pelo comparador não é falha de execução;
        # seu código de saída é zero quando conclui normalmente o relatório.
        executar_python("Executando o filtro C pela UART", "comunicacao_uart.py", cliente)
        if not apenas_c:
            executar_python("Executando a referencia Python", "particle_filter.py", entradas)
            executar_python("Comparando os resultados", "comparar_resultados.py")
    except subprocess.CalledProcessError:
        return 1
    except (OSError, ValueError, EOFError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperacao cancelada.", file=sys.stderr)
        return 1
    return 0


# Devolve o código de execução ao terminal quando chamado como programa.
if __name__ == "__main__":
    sys.exit(main())
