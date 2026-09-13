@echo off
rem Starts the Kick-Flight private server on http://0.0.0.0:18080 (gRPC 18081).
rem Re-run after editing config\masters_*.json (masters are read at startup).
setlocal enabledelayedexpansion
cd /d "%~dp0src\KickFlight.BootstrapApi"

rem stop a previous copy that still holds the port.
rem /c: is essential: without it findstr splits the pattern at the space into two
rem patterns (":18080" OR ".*LISTENING") and the loop kills the owner of EVERY
rem listening socket (Unity editor, emulator, adb...). Match only the local-address
rem column ending in :18080 in LISTENING state, and only kill dotnet processes.
for /f "tokens=1,2,5" %%a in ('netstat -ano ^| findstr /r /c:"^ *TCP  *[^ ]*:18080  *[^ ]*  *LISTENING"') do (
    for /f "tokens=1 delims=," %%n in ('tasklist /fi "PID eq %%c" /fo csv /nh') do (
        set "IMG=%%~n"
        if /i "%%~n"=="dotnet.exe" set "IMG=server"
        if /i "%%~n"=="KickFlight.BootstrapApi.exe" set "IMG=server"
        if "!IMG!"=="server" (
            echo Stopping old server PID %%c
            taskkill /PID %%c /F >nul 2>&1
        ) else (
            echo Port 18080 is held by %%~n PID %%c - not a dotnet server, leaving it alone.
        )
    )
)

echo Building server (incremental)...
dotnet build -c Release -nologo -v q || goto :fail

set HttpPort=18080
set GrpcPort=18081
set Harness__PersistCaptures=true
set Harness__DirectClientHosts__0=192.168.68.55
if not exist "%~dp0.local\session-logs" mkdir "%~dp0.local\session-logs"
echo.
echo Server starting on port 18080 - leave this window open, Ctrl+C stops it.
echo Console output is also written to .local\session-logs\server-^<timestamp^>.log
echo.
rem tee the console into .local\session-logs so a frozen client can be matched against what the server saw.
rem (Tee-Object in Windows PowerShell writes UTF-16; a StreamWriter keeps the log plain UTF-8 for grep.)
powershell -NoProfile -Command "$log = '%~dp0.local\session-logs\server-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log'; Write-Host \"log: $log\"; $w = New-Object System.IO.StreamWriter($log, $false, (New-Object System.Text.UTF8Encoding($false))); $w.AutoFlush = $true; try { & dotnet 'bin\Release\net8.0\KickFlight.BootstrapApi.dll' 2>&1 | ForEach-Object { $s = [string]$_; [Console]::Out.WriteLine($s); $w.WriteLine($s) } } finally { $w.Close() }"
goto :eof

:fail
echo Build failed.
pause
