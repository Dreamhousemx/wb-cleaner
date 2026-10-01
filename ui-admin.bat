@echo off
chcp 65001 >nul
title WBCleaner - Visual UI (Administrator)
cd /d "%~dp0"

set "PYCMD=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "%USERPROFILE%\.workbuddy\binaries\python\current\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\current\python.exe"

net session >nul 2>&1
if errorlevel 1 goto elevate
goto run

:elevate
echo [WBCleaner] Administrator rights required for DISM and system cleanup.
echo [WBCleaner] A UAC prompt will appear - please click Yes.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo [WBCleaner] Starting visual interface with administrator rights...
echo.
%PYCMD% "%~dp0wbcleaner_ui.py" %*
pause
