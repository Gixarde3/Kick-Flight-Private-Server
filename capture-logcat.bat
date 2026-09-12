@echo off
rem Dumps the device log (Unity exceptions, crashes) to .local\logcat-<date>.txt for analysis.
setlocal
set PATH=%LOCALAPPDATA%\Android\Sdk\platform-tools;%PATH%
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do set STAMP=%%c%%a%%b-%%d%%e%%f
set OUT=%~dp0.local\logcat-%STAMP%.txt
adb logcat -d > "%OUT%"
findstr /c:"KFDIAG" "%OUT%" > "%OUT:.txt=-kfdiag.txt%"
echo Saved %OUT%
findstr /c:"E Unity" "%OUT%" | findstr /c:"Exception" | find /c /v "" 
echo ^ Unity exception lines (see the file for stacks). Use `adb logcat -c` to clear before a new test.
pause
