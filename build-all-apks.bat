@echo off
rem Rebuilds every APK flavour with the current scripts\patch-il2cpp-endpoints.py (production caves, RANGED_ATTACK_INTERVALS,
rem DIAG probes) via Git Bash + .local\build.sh, one after another, and prints the sha256 of each:
rem   .local\KickFlight-2.11.0-current-patches.apk    LAN build   (server literal 192.168.68.55)        -> http://<pc>:18080/apk
rem   .local\KickFlight-2.11.0-remote-kickflightsg.apk ddns build (kickflightsg.ddns.net)               -> /apk/remote
rem   .local\KickFlight-2.11.0-DIAG.apk                LAN + KFDIAG probes (start-client-diag.bat)     -> /apk/diag
rem   .local\KickFlight-2.11.0-DIAG-remote.apk         ddns + KFDIAG probes                            -> /apk/diag-remote
rem Usage:  build-all-apks.bat            (all four)
rem         build-all-apks.bat lan remote (only the named flavours: lan | remote | diag | diag-remote)
rem apktool needs ~4 GB: stop the emulator first (apktool + emulator + server do not fit in 16 GB).
rem Logs: .local\build-all-<flavour>.log. The server keeps serving the old files until each build finishes.
setlocal enabledelayedexpansion
set ROOT=%~dp0
set BASH=C:\Program Files\Git\bin\bash.exe
if not exist "%BASH%" set BASH=C:\Program Files\Git\usr\bin\bash.exe
if not exist "%BASH%" (
    echo Git Bash not found - install Git for Windows or fix BASH= in this file.
    exit /b 1
)
if not exist "%ROOT%.local\build.sh" (
    echo .local\build.sh is missing.
    exit /b 1
)

set FLAVOURS=%*
if "%FLAVOURS%"=="" set FLAVOURS=lan remote diag diag-remote

tasklist | findstr /i "qemu-system" >nul && echo WARNING: the emulator is running - apktool may run out of memory.

set FAILED=
for %%f in (%FLAVOURS%) do (
    call :build %%f || set FAILED=!FAILED! %%f
)
echo.
if defined FAILED (
    echo FAILED:%FAILED%   ^(see .local\build-all-^<flavour^>.log^)
    exit /b 1
)
rem config/resources/catalog.json pins the sha256 of the hosted remote APK (entry apk-remote-kickflightsg); a stale hash makes
rem /health/ready answer 503, so refresh it and restart the server (start-server.bat) after this.
python "%ROOT%scripts/update-apk-catalog-sha.py"
echo All builds done. The server serves the new files from .local immediately; restart it once so /health/ready picks up the new catalog hash.
exit /b 0

:build
set F=%1
set LOG=%ROOT%.local\build-all-%F%.log
if "%F%"=="lan"         set CMD=OUT='%ROOT:\=/%.local/KickFlight-2.11.0-current-patches.apk' bash .local/build.sh
if "%F%"=="remote"      set CMD=bash .local/build-remote.sh
if "%F%"=="diag"        set CMD=KF_DIAG=1 OUT='%ROOT:\=/%.local/KickFlight-2.11.0-DIAG.apk' bash .local/build.sh
if "%F%"=="diag-remote" set CMD=KF_DIAG=1 URL=http://kickflightsg.ddns.net:18080 OUT='%ROOT:\=/%.local/KickFlight-2.11.0-DIAG-remote.apk' bash .local/build.sh
if not defined CMD (
    echo Unknown flavour "%F%" ^(use lan, remote, diag, diag-remote^)
    exit /b 1
)
echo ===== %F%: %CMD%
"%BASH%" -lc "cd '%ROOT:\=/%' && %CMD%" > "%LOG%" 2>&1
set RC=%ERRORLEVEL%
set CMD=
if not "%RC%"=="0" (
    echo   FAILED ^(exit %RC%^) - tail of %LOG%:
    powershell -NoProfile -Command "Get-Content -Tail 8 '%LOG%'"
    exit /b 1
)
for /f "delims=" %%l in ('findstr /c:"BUILD DONE" "%LOG%"') do echo   %%l
for /f "tokens=1" %%h in ('findstr /r /c:"^[0-9a-f]* \*" "%LOG%"') do echo   sha256 %%h
exit /b 0
