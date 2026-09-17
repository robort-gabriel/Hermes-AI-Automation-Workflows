@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo Job Hunter setup (Windows)
echo.

set PYEXE=
where python >nul 2>nul
if not errorlevel 1 (
    set PYEXE=python
) else (
    where python3 >nul 2>nul
    if not errorlevel 1 (
        set PYEXE=python3
    )
)

if "%PYEXE%"=="" (
    echo Python 3 was not found on PATH.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo winget is not available on this machine either.
        echo Install Python 3 manually from https://python.org
        echo ^(check "Add python.exe to PATH" during setup^), then re-run install.bat.
        pause
        exit /b 1
    )
    echo Installing Python 3 via winget...
    winget install --id Python.Python.3.12 -e --source winget
    echo.
    echo Python was just installed. Close this window and double-click
    echo install.bat again so your PATH picks up the new install.
    pause
    exit /b 0
)

echo Using %PYEXE% for setup...
%PYEXE% scripts\setup-hermes-profile.py
set SETUP_RC=%ERRORLEVEL%

echo.
if not "%SETUP_RC%"=="0" (
    echo Setup reported an error above.
)
pause
exit /b %SETUP_RC%
