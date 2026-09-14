@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 사용 예: build.bat cython v1
REM          build.bat list
REM          build.bat obfuscate v2
python build_cli.py %*
if %ERRORLEVEL% neq 0 exit /b 1
