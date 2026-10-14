$portas = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)

if ($portas.Count -eq 0) {
    Write-Output 'Nenhuma porta serial encontrada.'
    exit 0
}

try {
    $dispositivos = @(Get-CimInstance -ClassName Win32_PnPEntity -ErrorAction Stop)
} catch {
    $dispositivos = @()
}

foreach ($porta in $portas) {
    $descricao = $null
    $marcador = "\($([regex]::Escape($porta))\)"
    foreach ($dispositivo in $dispositivos) {
        if ($dispositivo.Name -match $marcador) {
            $descricao = $dispositivo.Name -replace "\s*$marcador$", ''
            break
        }
    }

    if ($descricao) {
        Write-Output "${porta}: $descricao"
    } else {
        Write-Output $porta
    }
}
