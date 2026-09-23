@echo off
rem Installs the merged-patch build (.local\KickFlight-2.11.0-merged.apk: offline combat + Photon 2-player patch sets,
rem scripts/patch-il2cpp-endpoints.py since 46f9392) instead of the validated current-patches APK. Same flow as
rem start-client.bat. Build it with: OUT=$PWD/.local/KickFlight-2.11.0-merged.apk bash .local/build.sh
setlocal
set APK_OVERRIDE=%~dp0.local\KickFlight-2.11.0-merged.apk
call "%~dp0start-client.bat" %*
