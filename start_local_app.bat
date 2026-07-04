@echo off
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo Entorno virtual no encontrado. Ejecuta setup.bat primero.
    pause
    exit /b 1
)

python app.py
pause
