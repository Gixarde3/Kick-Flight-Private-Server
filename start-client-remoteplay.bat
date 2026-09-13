@echo off
rem Same as start-client.bat but renders the emulator in software (swiftshader) so the
rem window is capturable by Steam Remote Play / screen sharing. Slower than the GPU path.
rem If the emulator is already running with GPU rendering, close it first.
call "%~dp0start-client.bat" -gpu swiftshader_indirect
