$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$secretDirectory = Join-Path $env:LOCALAPPDATA "AMH"
$secretFile = Join-Path $secretDirectory "nfc-agent-token.dpapi"

if (-not (Test-Path $pythonPath)) {
    throw "No se encuentra Python: $pythonPath"
}

if (-not (Test-Path $secretFile)) {
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null

    $secureToken = Read-Host `
        "Introduce AMH_NFC_AGENT_TOKEN (solo esta primera vez)" `
        -AsSecureString

    if ($secureToken.Length -eq 0) {
        throw "El token no puede estar vacío"
    }

    $secureToken |
        ConvertFrom-SecureString |
        Set-Content -Path $secretFile -NoNewline

    Write-Host "Token cifrado para este usuario de Windows."
}

$secureToken = Get-Content -Path $secretFile -Raw |
    ConvertTo-SecureString

$env:AMH_NFC_AGENT_TOKEN = [System.Net.NetworkCredential]::new(
    "",
    $secureToken
).Password

$env:AMH_NFC_API_URL = "http://127.0.0.1:8001"
$env:AMH_NFC_FRONTEND_ORIGIN = "http://127.0.0.1:5174"

try {
    Push-Location $projectRoot

    & $pythonPath -m uvicorn `
        agents.windows_nfc.login_agent:app `
        --host 127.0.0.1 `
        --port 8766
}
finally {
    Remove-Item Env:\AMH_NFC_AGENT_TOKEN -ErrorAction SilentlyContinue
    Pop-Location
}