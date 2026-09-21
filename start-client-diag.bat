@echo off
rem Installs the KF_DIAG trace build (.local\KickFlight-2.11.0-DIAG.apk) instead of the normal APK and boots
rem the emulator with the software renderer (Remote Play capturable). Same flow as start-client.bat.
rem Same gameplay/data as production (summons load since 2026-09-20); it only adds KFDIAG logcat probes
rem (read them with python scriptsettack_diag_read.py or adb logcat -d -s KFDIAG; see AGENTS.md "Builds DIAG").
rem If a GPU-rendered emulator is already running, close it first.
setlocal
set APK_OVERRIDE=%~dp0.local\KickFlight-2.11.0-DIAG.apk
call "%~dp0start-client.bat" %*
