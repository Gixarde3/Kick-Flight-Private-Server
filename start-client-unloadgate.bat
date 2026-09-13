@echo off
rem Kept for history: since 2026-09-13 the normal build (start-client.bat) no longer carries the LoadManager.Enqueue
rem _isUnloading bypass either, so this launcher is identical to start-client-remoteplay.bat.
call "%~dp0start-client-remoteplay.bat" %*
