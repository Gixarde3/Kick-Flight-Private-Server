@echo off
rem Starts the Kick-Flight private server on http://0.0.0.0:18080 (gRPC 18081).
rem Re-run after editing config\masters_*.json (masters are read at startup).
setlocal
cd /d "%~dp0src\KickFlight.BootstrapApi"

rem stop a previous copy that still holds the port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r ":18080 .*LISTENING"') do (
    echo Stopping old server PID %%p
    taskkill /PID %%p /F >nul 2>&1
)

echo Building server (incremental)...
dotnet build -c Release -nologo -v q || goto :fail

set HttpPort=18080
set GrpcPort=18081
set Harness__PersistCaptures=true
set Harness__DirectClientHosts__0=192.168.68.55
echo.
echo Server starting on port 18080 - leave this window open, Ctrl+C stops it.
echo.
dotnet bin\Release\net8.0\KickFlight.BootstrapApi.dll
goto :eof

:fail
echo Build failed.
pause
