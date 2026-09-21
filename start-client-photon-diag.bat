@echo off
rem Installs the Photon-flavour KF_DIAG build (.local\KickFlight-2.11.0-photon-DIAG.apk): merged patch set with the
rem LuxonServer matchmaking flow (KF_PHOTON=1) pointed at 51.79.241.70, plus the KFDIAG probes. Same flow as start-client.bat.
rem Build: KF_PHOTON=1 KF_PHOTON_HOST=51.79.241.70 KF_DIAG=1 OUT=$PWD/.local/KickFlight-2.11.0-photon-DIAG.apk bash .local/build.sh
setlocal
set APK_OVERRIDE=%~dp0.local\KickFlight-2.11.0-photon-DIAG.apk
call "%~dp0start-client.bat" %*
