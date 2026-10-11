$ErrorActionPreference = "Stop"

$diretorioRenode = $PSScriptRoot
$raizProjeto = Split-Path -Parent $diretorioRenode
$elfOrigem = Join-Path $raizProjeto "Debug\Particle Filter.elf"
$elfRenode = Join-Path $diretorioRenode "firmware.elf"
$executavelRenode = "C:\Program Files\Renode\renode.exe"

if (-not (Test-Path -LiteralPath $elfOrigem)) {
    throw "Firmware nao encontrado: $elfOrigem. Compile o projeto primeiro."
}
if (-not (Test-Path -LiteralPath $executavelRenode)) {
    throw "Renode nao encontrado em: $executavelRenode"
}

Copy-Item -LiteralPath $elfOrigem -Destination $elfRenode -Force

try {
    subst R: $raizProjeto
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel criar a unidade temporaria R:."
    }
    & $executavelRenode "R:\Renode\executar.resc"
}
finally {
    subst R: /D 2>$null
}
