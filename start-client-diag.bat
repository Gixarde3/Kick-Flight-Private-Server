@echo off
rem Installs the KF_DIAG trace build (.local\KickFlight-2.11.0-DIAG.apk) instead of the normal APK and boots
rem the emulator with the software renderer (Remote Play capturable). Same flow as start-client.bat.
rem This build has no disc pets but logs state transitions (capture-logcat.bat writes the ...-kfdiag.txt).
rem If a GPU-rendered emulator is already running, close it first.
setlocal
set APK_OVERRIDE=%~dp0.local\KickFlight-2.11.0-DIAG.apk
call "%~dp0start-client.bat" -gpu swiftshader_indirect %*
