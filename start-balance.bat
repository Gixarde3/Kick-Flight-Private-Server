@echo off
rem Starts the balance WebUI (tools\balance\server.py) and opens it in the browser.
rem   start-balance.bat          -> http://127.0.0.1:8765  (this PC only)
rem   start-balance.bat lan      -> also reachable from phones/other PCs on the LAN (URL printed below)
rem Saves write .local\masters-overrides (backup per save in tools\balance\backups), never config\; the game
rem server reads the masters at startup, so run start-server.bat again after saving.
rem Override KF_BALANCE_OVERRIDE_DIR / KF_BALANCE_BASE_DIR to edit a deployed server (see the README).
setlocal
cd /d "%~dp0"
set HOST=127.0.0.1
if /i "%~1"=="lan" set HOST=0.0.0.0
python tools\balance\server.py --host %HOST% --port 8765 --open
if errorlevel 1 pause
