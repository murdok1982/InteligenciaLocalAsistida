#!/usr/bin/env bash
# setup.sh — One-click installer for InteligenciaGeopolitica local server
set -euo pipefail

OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:4b}"
MODELFILE="./ollama_geoint.modelfile"

echo "============================================"
echo "  InteligenciaGeopolitica — Setup"
echo "============================================"

# --- 1. Python dependencies ---
echo ""
echo "[1/4] Instalando dependencias Python..."
pip install --quiet -r requirements.txt
echo "✅ Dependencias Python instaladas."

# --- 2. Ollama ---
echo ""
echo "[2/4] Verificando Ollama..."
if ! command -v ollama &>/dev/null; then
    echo "  Ollama no encontrado. Instalando..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama instalado."
else
    echo "✅ Ollama ya está instalado: $(ollama --version)"
fi

# --- 3. Pull model ---
echo ""
echo "[3/4] Descargando modelo ${OLLAMA_MODEL} (esto puede tardar varios minutos)..."
ollama pull "${OLLAMA_MODEL}"
echo "✅ Modelo ${OLLAMA_MODEL} descargado."

# --- 4. Create custom profile ---
echo ""
echo "[4/4] Creando perfil atalaya-geoint..."
if [ -f "${MODELFILE}" ]; then
    ollama create atalaya-geoint -f "${MODELFILE}"
    echo "✅ Perfil atalaya-geoint creado."
else
    echo "⚠️  ${MODELFILE} no encontrado — omitiendo creación de perfil personalizado."
fi

# --- .env check ---
echo ""
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "📋 Archivo .env creado desde .env.example"
    echo "   Edita .env si necesitas configurar NewsAPI u OpenAI como fallback."
fi

echo ""
echo "============================================"
echo "  Instalación completada."
echo "  Para generar el informe semanal:"
echo "    python main.py"
echo ""
echo "  Para uso con Docker:"
echo "    docker compose --profile ollama-init up -d"
echo "    docker compose --profile run up"
echo "============================================"
