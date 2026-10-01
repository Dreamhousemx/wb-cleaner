@echo off
chcp 65001 >nul
title WBCleaner - Scan Only (read-only, no admin needed)
cd /d "%~dp0"

set "PYCMD=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "%USERPROFILE%\.workbuddy\binaries\python\current\python.exe" set PYCMD="%USERPROFILE%\.workbuddy\binaries\python\current\python.exe"

if not exist "reports" mkdir reports
%PYCMD% "%~dp0wbcleaner.py" scan --html "%~dp0reports\scan.html" --json "%~dp0reports\scan.json"
echo.
echo Report: %~dp0reports\scan.html
start "" "%~dp0reports\scan.html"
pause
