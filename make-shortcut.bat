@echo off
chcp 65001 >nul
title Create desktop shortcut
cd /d "%~dp0"

set "PYCMD=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "%USERPROFILE%\.workbuddy\binaries\python\current\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\current\python.exe"

%PYCMD% "%~dp0tools\make_shortcut.py" %*
echo.
pause
