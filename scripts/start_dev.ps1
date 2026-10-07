$ErrorActionPreference = "Stop"

$amhDir = Split-Path -Parent $PSScriptRoot
$keycloakDir = Join-Path $env:USERPROFILE "Downloads\keycloak-26.7.4"
$python = Join-Path $amhDir ".venv\Scripts\python.exe"

$keycloakUrl = "http://127.0.0.1:8081/realms/amh-dev/.well-known/openid-configuration"
$amhUrl = "http://127.0.0.1:8001/health"

function Test-HttpReady([string] $url) {
    try {
        $result = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $result.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-HttpReady([string] $url, [string] $name) {
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if (Test-HttpReady $url) {
            Write-Host "${name}: disponible" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "$name no respondió en $url. Revisa su ventana de errores."
}

if (-not (Test-Path $python)) {
    throw "No se encontró Python de AMH: $python"
}
if (-not (Test-Path (Join-Path $keycloakDir "bin\kc.bat"))) {
    throw "No se encontró Keycloak en $keycloakDir"
}

# PostgreSQL debe estar funcionando antes de arrancar Keycloak.
$postgresServices = @(
    Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
)
$runningPostgres = @(
    $postgresServices | Where-Object { $_.Status -eq "Running" }
)

if ($runningPostgres.Count -eq 0) {
    if ($postgresServices.Count -ne 1) {
        throw "No se ha identificado un único servicio PostgreSQL. Revísalo con Get-Service 'postgresql*'."
    }

    Write-Host "Iniciando PostgreSQL: $($postgresServices[0].Name)"
    Start-Service -Name $postgresServices[0].Name
}

if (-not (Test-HttpReady $keycloakUrl)) {
    Write-Host "Iniciando Keycloak..."

    $env:KC_DB = "postgres"
    $env:KC_DB_URL_HOST = "127.0.0.1"
    $env:KC_DB_URL_PORT = "5432"
    $env:KC_DB_URL_DATABASE = "keycloak_dev"
    $env:KC_DB_USERNAME = "keycloak_dev"

    $securePassword = Read-Host "Password PostgreSQL de keycloak_dev" -AsSecureString

    try {
        $env:KC_DB_PASSWORD = (
            [System.Net.NetworkCredential]::new("", $securePassword)
        ).Password

        Start-Process `
            -FilePath "powershell.exe" `
            -WorkingDirectory $keycloakDir `
            -ArgumentList @(
                "-NoProfile",
                "-NoExit",
                "-Command",
                "& '.\bin\kc.bat' start-dev --http-host=127.0.0.1 --http-port=8081"
            )
    }
    finally {
        Remove-Item Env:KC_DB_PASSWORD -ErrorAction SilentlyContinue
        Remove-Variable securePassword -ErrorAction SilentlyContinue
    }

    Wait-HttpReady $keycloakUrl "Keycloak"
}
else {
    Write-Host "Keycloak: ya estaba disponible"
}

# Esta ejecución de desarrollo toma los datos de amh\.env.
# Evita heredar variables de una sesión usada para probar amh_test.
foreach ($name in @(
    "AMH_DB_HOST",
    "AMH_DB_PORT",
    "AMH_DB_NAME",
    "AMH_DB_USER",
    "AMH_DB_PASSWORD"
)) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}

$databaseName = & $python -c "from app.config import settings; print(settings.amh_db_name)"
if ($LASTEXITCODE -ne 0 -or $databaseName.Trim() -ne "amh_dev") {
    throw "AMH debe apuntar a amh_dev; configuración detectada: $databaseName"
}

if (-not (Test-HttpReady $amhUrl)) {
    Write-Host "Iniciando AMH con base de datos amh_dev..."

    Start-Process `
        -FilePath "powershell.exe" `
        -WorkingDirectory $amhDir `
        -ArgumentList @(
            "-NoProfile",
            "-NoExit",
            "-Command",
            "& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --no-access-log"
        )

    Wait-HttpReady $amhUrl "AMH"
}
else {
    Write-Host "AMH: ya estaba disponible"
}

Write-Host "AMH listo: http://127.0.0.1:8001/auth/login"