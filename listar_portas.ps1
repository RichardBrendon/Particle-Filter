param(
    [string]$Python = 'py'
)

$cliente = Join-Path $PSScriptRoot 'Python/comunicacao_uart.py'
& $Python $cliente --listar-portas
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
