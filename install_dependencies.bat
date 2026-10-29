@echo off
setlocal

call python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto install
)
call py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto install
)

echo Python was not found. Install Python 3.10 or newer and add it to PATH.
goto failed

:install
call %PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed

echo.
echo Twitch bot dependencies installed successfully.
pause
exit /b 0

:failed
echo Installation failed. Check the message above.
pause
exit /b 1
