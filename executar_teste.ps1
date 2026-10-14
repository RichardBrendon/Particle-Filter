param(
    [Parameter(Mandatory = $true)]
    [string]$Cenario,

    [ValidateSet('Renode', 'Placa')]
    [string]$Modo = 'Renode',

    [string]$Porta,
    [string]$EnderecoRenode = 'localhost:12345',
    [string]$Python = 'py'
)

$ErrorActionPreference = 'Stop'
$raizProjeto = $PSScriptRoot

if ($Cenario -match '^\d+$') {
    $sufixo = if ($Cenario -eq '1') { 'etapa' } else { 'etapas' }
    $arquivoCenario = Join-Path $raizProjeto "Dados_Teste/cenario_${Cenario}_${sufixo}.csv"
} elseif ([System.IO.Path]::IsPathRooted($Cenario)) {
    $arquivoCenario = $Cenario
} else {
    $arquivoCenario = Join-Path $raizProjeto $Cenario
}

if (-not (Test-Path -LiteralPath $arquivoCenario -PathType Leaf)) {
    throw "Cenario nao encontrado: $arquivoCenario"
}
$arquivoCenario = (Resolve-Path -LiteralPath $arquivoCenario).Path

$cliente = Join-Path $raizProjeto 'Python/comunicacao_uart.py'
$referencia = Join-Path $raizProjeto 'Python/particle_filter.py'
$comparador = Join-Path $raizProjeto 'Python/comparar_resultados.py'

function Executar-Python {
    param(
        [string]$Descricao,
        [string[]]$Argumentos
    )

    Write-Host "`n== $Descricao =="
    & $Python @Argumentos
    if ($LASTEXITCODE -ne 0) {
        throw "$Descricao falhou (codigo $LASTEXITCODE). Teste interrompido."
    }
}

Write-Host "Cenario: $arquivoCenario"
Write-Host "Modo: $Modo"

$argumentosCliente = @($cliente)
if ($Modo -eq 'Renode') {
    if ($Porta) {
        throw 'Use -Porta somente com -Modo Placa.'
    }
    $argumentosCliente += @('--tcp', $EnderecoRenode)
} elseif ($Porta) {
    $argumentosCliente += @('--porta', $Porta)
}
$argumentosCliente += @('--entradas', $arquivoCenario)

Executar-Python 'Executando o filtro C pela UART' $argumentosCliente
Executar-Python 'Executando a referencia Python' @($referencia, '--entradas', $arquivoCenario)
Executar-Python 'Comparando os resultados' @($comparador)
