@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                                                              ║
echo ║   ██████╗ ███████╗ ██████╗ ██████╗ ███╗   ██╗███████╗██╗    ║
echo ║  ██╔════╝ ██╔════╝██╔═══██╗██╔══██╗████╗  ██║██╔════╝██║    ║
echo ║  ██║  ███╗█████╗  ██║   ██║██████╔╝██╔██╗ ██║█████╗  ██║    ║
echo ║  ██║   ██║██╔══╝  ██║   ██║██╔══██╗██║╚██╗██║██╔══╝  ██║    ║
echo ║  ╚██████╔╝███████╗╚██████╔╝██║  ██║██║ ╚████║███████╗███████╗║
echo ║   ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝║
echo ║                                                              ║
echo ║          INSTALADOR AUTOMATICO v3.0                         ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo [1/7] Verificando Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python no encontrado.
    echo Descarga Python 3.11+ desde: https://python.org/downloads
    echo IMPORTANTE: Marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Python %PYVER% detectado.

echo.
echo [2/7] Detectando hardware...
echo.

set TOTAL_RAM=0
set HAS_GPU=0
set GPU_VRAM=0

for /f "tokens=2 delims==" %%a in ('wmic computersystem get totalphysicalmemory /value 2^>nul ^| findstr "="') do (
    set /a TOTAL_RAM=%%a / 1073741824
)

nvidia-smi >nul 2>&1
if %errorlevel% equ 0 (
    set HAS_GPU=1
    for /f "tokens=2 delims=:" %%a in ('nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2^>nul') do (
        set /a GPU_VRAM=%%a / 1024
    )
)

echo   ┌─────────────────────────────────────────┐
echo   │  RAM detectada:     %TOTAL_RAM% GB                  │
if %HAS_GPU% equ 1 (
    echo   │  GPU NVIDIA:        Si                     │
    echo   │  VRAM GPU:          %GPU_VRAM% GB                  │
) else (
    echo   │  GPU NVIDIA:        No (solo CPU)          │
    echo   │  VRAM GPU:          N/A                    │
)
echo   └─────────────────────────────────────────┘
echo.

echo [3/7] Seleccionando proveedor de IA...
echo.
echo   ┌─────────────────────────────────────────────────────────┐
echo   │  Elige el proveedor de modelos de lenguaje:             │
echo   │                                                         │
echo   │  [1] Ollama   — Local, gratis, privado (recomendado^)    │
echo   │  [2] OpenAI   — Cloud, requiere API key                 │
echo   │  [3] Auto     — Ollama con fallback a OpenAI            │
echo   │                                                         │
echo   └─────────────────────────────────────────────────────────┘
echo.

set PROVIDER_CHOICE=1
set /p PROVIDER_CHOICE="  Elige proveedor [1-3, Enter=Ollama]: "

if "%PROVIDER_CHOICE%"=="1" set LLM_PROVIDER=ollama
if "%PROVIDER_CHOICE%"=="2" set LLM_PROVIDER=openai
if "%PROVIDER_CHOICE%"=="3" set LLM_PROVIDER=auto

if not defined LLM_PROVIDER set LLM_PROVIDER=ollama

echo.
echo   Proveedor seleccionado: %LLM_PROVIDER%
echo.

set OPENAI_KEY_VALUE=

if "%LLM_PROVIDER%"=="openai" (
    echo   OpenAI requiere una API key.
    echo   Obtén una en: https://platform.openai.com/api-keys
    echo.
    set /p OPENAI_KEY_VALUE="  Introduce tu OPENAI_API_KEY: "
    if not defined OPENAI_KEY_VALUE (
        echo.
        echo   ERROR: No se proporcionó API key.
        pause
        exit /b 1
    )
    echo.
    echo   API key configurada.
    echo.
)

if "%LLM_PROVIDER%"=="auto" (
    echo   Modo Auto: usará Ollama localmente y OpenAI como respaldo.
    echo.
    set /p OPENAI_KEY_VALUE="  Introduce tu OPENAI_API_KEY (opcional, Enter para omitir): "
    echo.
)

echo [4/7] Seleccionando modelo de IA...
echo.
echo   Tu hardware puede ejecutar estos modelos:
echo.

if %TOTAL_RAM% geq 32 (
    if %HAS_GPU% equ 1 (
        if %GPU_VRAM% geq 24 (
            echo   [1] ★ qwen2.5:32b      - Calidad EXCEPCIONAL (recomendado^)
            echo       RAM: 32GB+ ^| VRAM: 24GB+ ^| Velocidad: Media
            echo       Mejor para: Analisis profesional de alta precision
            echo.
        )
    )
    echo   [2] ★ gemma3:12b       - Calidad SUPERIOR (recomendado^)
    echo       RAM: 16GB+ ^| Velocidad: Media
    echo       Mejor para: Analisis detallados, informes semanales
    echo.
    echo   [3] ★ qwen2.5:14b      - Calidad SUPERIOR (alternativa^)
    echo       RAM: 16GB+ ^| Velocidad: Media-Lenta
    echo       Mejor para: Analisis en espanol de alta calidad
    echo.
) else if %TOTAL_RAM% geq 16 (
    echo   [2] ★ gemma3:12b       - Calidad SUPERIOR (recomendado^)
    echo       RAM: 16GB+ ^| Velocidad: Media
    echo       Mejor para: Analisis detallados, informes semanales
    echo.
    echo   [3] ★ qwen2.5:14b      - Calidad SUPERIOR (alternativa^)
    echo       RAM: 16GB+ ^| Velocidad: Media-Lenta
    echo       Mejor para: Analisis en espanol de alta calidad
    echo.
)

echo   [4] ★ gemma3:4b        - Calidad BUENA (rapido^)
echo       RAM: 8GB+ ^| Velocidad: Rapida
echo       Mejor para: Consultas rapidas, hardware limitado
echo.
echo   [5] ★ llama3.2:3b      - Calidad BASICA (muy rapido^)
echo       RAM: 8GB+ ^| Velocidad: Muy Rapida
echo       Mejor para: Pruebas, hardware muy limitado
echo.
echo   [6] Personalizado      - Escribir nombre del modelo
echo.

echo   ┌─────────────────────────────────────────────────────────┐
echo   │  RECOMENDACION POR TAREA:                                │
echo   │                                                         │
echo   │  Informes semanales completos (23 paises^):              │
echo   │    → gemma3:12b o qwen2.5:14b (mejor calidad^)          │
echo   │                                                         │
echo   │  Analisis rapidos y consultas puntuales:                 │
echo   │    → gemma3:4b (rapido y equilibrado^)                   │
echo   │                                                         │
echo   │  Uso academico / aprendizaje:                            │
echo   │    → gemma3:4b o llama3.2:3b (suficiente^)              │
echo   │                                                         │
echo   │  Inteligencia profesional / gubernamental:               │
echo   │    → qwen2.5:32b o gemma3:12b (maxima precision^)       │
echo   │                                                         │
echo   └─────────────────────────────────────────────────────────┘
echo.

set MODEL_CHOICE=4
set /p MODEL_CHOICE="  Elige modelo [1-6, Enter=gemma3:4b]: "

if "%MODEL_CHOICE%"=="1" set SELECTED_MODEL=qwen2.5:32b
if "%MODEL_CHOICE%"=="2" set SELECTED_MODEL=gemma3:12b
if "%MODEL_CHOICE%"=="3" set SELECTED_MODEL=qwen2.5:14b
if "%MODEL_CHOICE%"=="4" set SELECTED_MODEL=gemma3:4b
if "%MODEL_CHOICE%"=="5" set SELECTED_MODEL=llama3.2:3b
if "%MODEL_CHOICE%"=="6" (
    set /p SELECTED_MODEL="  Escribe el nombre del modelo (ej: gemma3:12b): "
)

if not defined SELECTED_MODEL set SELECTED_MODEL=gemma3:4b

echo.
echo   Modelo seleccionado: %SELECTED_MODEL%
echo.

echo [5/7] Creando entorno virtual...
if not exist "venv" (
    python -m venv venv
    echo   Entorno virtual creado.
) else (
    echo   Entorno virtual ya existe.
)
call venv\Scripts\activate.bat

echo.
echo [6/7] Instalando dependencias...
pip install -r requirements.txt --quiet 2>nul
if %errorlevel% neq 0 (
    echo   ERROR: Fallo al instalar dependencias.
    echo   Intenta: pip install -r requirements.txt
    pause
    exit /b 1
)
echo   Dependencias instaladas correctamente.

echo.
echo [7/7] Configurando Ollama y modelo...

if "%LLM_PROVIDER%"=="ollama" (
    where ollama >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo   Ollama no encontrado.
        echo   Descarga Ollama desde: https://ollama.com/download
        echo.
        set /p SKIP="   Continuar sin Ollama? (s/n): "
        if /i "!SKIP!" neq "s" (
            pause
            exit /b 1
        )
    ) else (
        echo   Ollama detectado.
        echo   Descargando modelo %SELECTED_MODEL%...
        echo   (Esto puede tardar 5-30 minutos segun tu conexion^)
        echo.
        ollama pull %SELECTED_MODEL%
        if %errorlevel% neq 0 (
            echo   ERROR: No se pudo descargar el modelo.
            echo   Verifica tu conexion a internet.
            pause
            exit /b 1
        )
        echo.
        echo   Creando perfil ATALAYA...
        ollama create atalaya-geoint -f ollama_geoint.modelfile 2>nul
    )
) else if "%LLM_PROVIDER%"=="auto" (
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        echo   Ollama detectado. Descargando modelo %SELECTED_MODEL%...
        ollama pull %SELECTED_MODEL%
        ollama create atalaya-geoint -f ollama_geoint.modelfile 2>nul
    ) else (
        echo   Ollama no encontrado. Se usara OpenAI como proveedor principal.
    )
) else (
    echo   Proveedor OpenAI seleccionado. No se requiere Ollama.
)

if not exist ".env" (
    (
        echo LLM_PROVIDER=%LLM_PROVIDER%
        echo OLLAMA_BASE_URL=http://localhost:11434
        echo OLLAMA_MODEL=%SELECTED_MODEL%
        echo OPENAI_API_KEY=%OPENAI_KEY_VALUE%
        echo OPENAI_MODEL=gpt-4o-mini
        echo HOST=127.0.0.1
        echo PORT=8765
    ) > .env
    echo   Archivo .env creado con proveedor %LLM_PROVIDER% y modelo %SELECTED_MODEL%
) else (
    echo   Archivo .env ya existe. Actualizando configuracion...
    powershell -Command "(Get-Content .env) -replace 'OLLAMA_MODEL=.*','OLLAMA_MODEL=%SELECTED_MODEL%' | Set-Content .env"
    powershell -Command "(Get-Content .env) -replace 'LLM_PROVIDER=.*','LLM_PROVIDER=%LLM_PROVIDER%' | Set-Content .env"
    if defined OPENAI_KEY_VALUE (
        powershell -Command "(Get-Content .env) -replace 'OPENAI_API_KEY=.*','OPENAI_API_KEY=%OPENAI_KEY_VALUE%' | Set-Content .env"
    )
)

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                                                              ║
echo ║   INSTALACION COMPLETADA                                     ║
echo ║                                                              ║
echo ║   Proveedor: %LLM_PROVIDER%                                    ║
echo ║   Modelo:    %SELECTED_MODEL%                                 ║
echo ║                                                              ║
echo ║   Para iniciar la aplicacion:                                ║
echo ║     start_local_app.bat                                      ║
echo ║                                                              ║
echo ║   Para generar informe completo:                             ║
echo ║     venv\Scripts\activate                                    ║
echo ║     python main.py                                           ║
echo ║                                                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
pause
