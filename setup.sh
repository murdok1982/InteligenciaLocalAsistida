#!/usr/bin/env bash
set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-gemma3:4b}"
MODELFILE="./ollama_geoint.modelfile"

echo "============================================"
echo "  InteligenciaGeopolitica — Setup"
echo "============================================"

# --- 1. Python dependencies ---
echo ""
echo "[1/5] Instalando dependencias Python..."
pip install --quiet -r requirements.txt
echo "Dependencias Python instaladas."

# --- 2. Ollama ---
echo ""
echo "[2/5] Verificando Ollama..."
if ! command -v ollama &>/dev/null; then
    echo "  Ollama no encontrado. Instalando..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Ollama instalado."
else
    echo "Ollama ya esta instalado: $(ollama --version)"
fi

# --- 3. Model selector ---
echo ""
echo "[3/5] Seleccionando modelo de IA..."
echo ""
echo "  Modelos disponibles:"
echo ""
echo "  [1] gemma3:4b    — Recomendado, rapido (8GB+ RAM)"
echo "  [2] gemma3:12b   — Calidad superior (16GB+ RAM)"
echo "  [3] qwen2.5:14b  — Alternativa calidad superior (16GB+ RAM)"
echo "  [4] llama3.2:3b  — Muy rapido, hardware limitado (8GB+ RAM)"
echo "  [5] Personalizado — Escribir nombre del modelo"
echo ""

read -rp "  Elige modelo [1-5, Enter=gemma3:4b]: " MODEL_CHOICE
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "$MODEL_CHOICE" in
    1) OLLAMA_MODEL="gemma3:4b" ;;
    2) OLLAMA_MODEL="gemma3:12b" ;;
    3) OLLAMA_MODEL="qwen2.5:14b" ;;
    4) OLLAMA_MODEL="llama3.2:3b" ;;
    5)
        read -rp "  Escribe el nombre del modelo (ej: gemma3:12b): " OLLAMA_MODEL
        ;;
    *) OLLAMA_MODEL="gemma3:4b" ;;
esac

echo ""
echo "  Modelo seleccionado: ${OLLAMA_MODEL}"
echo ""

# --- 4. Pull model ---
echo ""
echo "[4/5] Descargando modelo ${OLLAMA_MODEL} (esto puede tardar varios minutos)..."
ollama pull "${OLLAMA_MODEL}"
echo "Modelo ${OLLAMA_MODEL} descargado."

# --- 5. Create custom profile ---
echo ""
echo "[5/5] Creando perfil atalaya-geoint..."
if [ -f "${MODELFILE}" ]; then
    ollama create atalaya-geoint -f "${MODELFILE}"
    echo "Perfil atalaya-geoint creado."
else
    echo "  ${MODELFILE} no encontrado — omitiendo creacion de perfil personalizado."
fi

# --- .env check ---
echo ""
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        sed -i "s/OLLAMA_MODEL=.*/OLLAMA_MODEL=${OLLAMA_MODEL}/" .env
    else
        cat > .env <<EOF
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=${OLLAMA_MODEL}
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
HOST=127.0.0.1
PORT=8765
EOF
    fi
    echo "Archivo .env creado con modelo ${OLLAMA_MODEL}"
else
    sed -i "s/OLLAMA_MODEL=.*/OLLAMA_MODEL=${OLLAMA_MODEL}/" .env
    echo "Archivo .env actualizado con modelo ${OLLAMA_MODEL}"
fi

echo ""
echo "============================================"
echo "  Instalacion completada."
echo "  Modelo: ${OLLAMA_MODEL}"
echo ""
echo "  Para generar el informe semanal:"
echo "    python main.py"
echo ""
echo "  Para iniciar la interfaz web:"
echo "    python app.py"
echo ""
echo "  Para uso con Docker:"
echo "    docker compose --profile ollama-init up -d"
echo "    docker compose --profile run up"
echo "============================================"
