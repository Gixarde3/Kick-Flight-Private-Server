@echo off
rem Installs the merged-patch KF_DIAG trace build (.local\KickFlight-2.11.0-merged-DIAG.apk) - merged patch set plus the
rem KFDIAG logcat probes. Same flow as start-client.bat / start-client-diag.bat.
rem Build: KF_DIAG=1 OUT=$PWD/.local/KickFlight-2.11.0-merged-DIAG.apk bash .local/build.sh
setlocal
set APK_OVERRIDE=%~dp0.local\KickFlight-2.11.0-merged-DIAG.apk
call "%~dp0start-client.bat" %*
