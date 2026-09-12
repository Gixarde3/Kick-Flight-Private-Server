@echo off
rem Saves a screenshot of the emulator to .local\shot-<time>.png (useful when the emulator window is not visible).
setlocal
set PATH=%LOCALAPPDATA%\Android\Sdk\platform-tools;%PATH%
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do set STAMP=%%c%%a%%b-%%d%%e%%f
adb exec-out screencap -p > "%~dp0.local\shot-%STAMP%.png"
echo Saved %~dp0.local\shot-%STAMP%.png
