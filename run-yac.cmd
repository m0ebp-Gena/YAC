@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -B "%~dp0yac.py" %*
) else (
    if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
        "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" -B "%~dp0yac.py" %*
    ) else (
        py -3 -B "%~dp0yac.py" %*
    )
)
if errorlevel 1 pause
