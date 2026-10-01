@echo off
chcp 65001 >nul
title WBCleaner - Visual UI
cd /d "%~dp0"

set "PYCMD=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "%USERPROFILE%\.workbuddy\binaries\python\current\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\current\python.exe"

echo [WBCleaner] Starting visual interface...
echo [WBCleaner] A desktop-style window will open automatically.
echo [WBCleaner] Keep this console window open while using the UI.
echo.
%PYCMD% "%~dp0wbcleaner_ui.py" %*
pause
