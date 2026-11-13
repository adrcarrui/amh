@echo off
setlocal
title Iniciar AMH

set "AMH_DIR=%~dp0"
cd /d "%AMH_DIR%"

echo ========================================
echo              INICIAR AMH
echo ========================================
echo.

if not exist "scripts\start_dev.ps1" (
    echo ERROR: No se encuentra scripts\start_dev.ps1
    goto :error
)

if not exist "scripts\start_nfc_agent_dev.ps1" (
    echo ERROR: No se encuentra scripts\start_nfc_agent_dev.ps1
    goto :error
)

if not exist "frontend\package.json" (
    echo ERROR: No se encuentra frontend\package.json
    goto :error
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo ERROR: No se encuentra npm. Comprueba Node.js.
    goto :error
)

echo Iniciando PostgreSQL, Keycloak y backend...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%AMH_DIR%scripts\start_dev.ps1"
if errorlevel 1 goto :error

echo.
echo Comprobando frontend...

powershell.exe -NoProfile -Command ^
    "try { $r = Invoke-WebRequest 'http://127.0.0.1:5174' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"

if not errorlevel 1 goto :frontend_ready

echo Iniciando frontend...

start "AMH - Frontend" /D "%AMH_DIR%frontend" "%ComSpec%" /k "npm.cmd run dev -- --host 127.0.0.1 --port 5174 --strictPort"

echo Esperando al frontend...

powershell.exe -NoProfile -Command ^
    "for ($i = 0; $i -lt 45; $i++) { try { $r = Invoke-WebRequest 'http://127.0.0.1:5174' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; Write-Host 'El frontend no responde. Revisa su ventana.'; exit 1"

if errorlevel 1 goto :error

:frontend_ready
echo.
echo Comprobando puerto del agente NFC...

rem Comprueba si ya hay un proceso escuchando en 8766.
powershell.exe -NoProfile -Command ^
    "$listener = Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue; if ($listener) { exit 0 }; exit 1"

if not errorlevel 1 goto :nfc_existing

echo Iniciando agente NFC...

start "AMH - Agente NFC" /D "%AMH_DIR%" powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -File "%AMH_DIR%scripts\start_nfc_agent_dev.ps1"

echo.
echo Si es la primera ejecucion, introduce el token
echo en la ventana del agente NFC.
echo Esperando al agente...

powershell.exe -NoProfile -Command ^
    "for ($i = 0; $i -lt 60; $i++) { $listener = Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction SilentlyContinue; if ($listener) { exit 0 }; Start-Sleep -Seconds 1 }; exit 1"

if errorlevel 1 (
    echo.
    echo El agente NFC aun no escucha en el puerto 8766.
    echo Revisa su ventana para introducir el token o ver el error.
    echo El portal se abrira igualmente.
)
goto :ready

:nfc_existing
echo El puerto 8766 ya esta ocupado.
echo No se inicia otra instancia del agente NFC.

:ready
echo.
echo Portal disponible: http://127.0.0.1:5174
start "" "http://127.0.0.1:5174"
echo.
echo Manten abiertas las ventanas de los servicios.
echo Puedes cerrar esta ventana.
pause
exit /b 0

:error
echo.
echo No se ha podido completar el inicio.
echo Revisa el mensaje de error anterior.
echo.
pause
exit /b 1