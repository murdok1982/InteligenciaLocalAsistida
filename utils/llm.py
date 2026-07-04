"""
LLM adapter: Ollama (primary, local) via HTTP API → OpenAI (fallback, optional).
Set LLM_PROVIDER=ollama or LLM_PROVIDER=openai in .env.
"""
import json
import logging
import os
import re

import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(dotenv_path=ENV_PATH, override=True)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "1800"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def set_model(model: str) -> None:
    global OLLAMA_MODEL
    OLLAMA_MODEL = model


def set_provider(provider: str) -> None:
    global LLM_PROVIDER
    LLM_PROVIDER = provider.lower()


def get_ollama_tags() -> list:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        r.raise_for_status()
        data = r.json()
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            if size_bytes:
                size_gb = round(size_bytes / (1024 ** 3), 1)
                size_str = f"{size_gb}GB"
            else:
                size_str = "desconocido"
            models.append({"name": name, "size": size_str})
        return models
    except Exception:
        return []

_SYSTEM_PROMPT = (
    "Eres un analista de inteligencia estratégica de nivel estatal. "
    "Redacta en español con rigor, precisión verificable y lenguaje técnico-militar. "
    "Evita especulaciones sin base factual. Cita fuentes cuando sea posible."
)

_MODEL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._/:-]+$")

_ALLOWED_OLLAMA_MODELS = {
    "gemma3:4b",
    "gemma3:12b",
    "gemma4:4b",
    "huihui_ai/deepseek-r1-abliterated:8b",
    "deepseek-r1:8b",
    "deepseek-r1:14b",
    "deepseek-r1:32b",
    "llama3.1:8b",
    "llama3.1:70b",
    "llama3.2:3b",
    "mistral:7b",
    "mixtral:8x7b",
    "gemma2:9b",
    "gemma2:27b",
    "qwen2.5:7b",
    "qwen2.5:14b",
    "qwen2.5:32b",
    "phi3:14b",
    "command-r:35b",
    "atalaya-geoint",
}

_extra = os.getenv("ALLOWED_MODELS_EXTRA", "")
if _extra:
    _ALLOWED_OLLAMA_MODELS.update(m.strip() for m in _extra.split(",") if m.strip())


def _validate_model_name(model: str) -> str:
    if not _MODEL_NAME_PATTERN.match(model):
        raise ValueError(f"Nombre de modelo inválido: {model}")
    if model not in _ALLOWED_OLLAMA_MODELS:
        raise ValueError(f"Modelo no permitido: {model}. Permitidos: {sorted(_ALLOWED_OLLAMA_MODELS)}")
    return model


def _ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _ask_ollama(prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    _validate_model_name(OLLAMA_MODEL)

    full_prompt = f"{system}\n\nUsuario: {prompt}\n\nAsistente:"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("response", "").strip()
        return output.replace("Thinking...", "").replace("...done thinking.", "").strip()
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"Timeout consultando Ollama ({OLLAMA_TIMEOUT_SECONDS}s)") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error consultando Ollama: {e}") from e


def _ask_ollama_stream(prompt: str, system: str, temperature: float, max_tokens: int):
    _validate_model_name(OLLAMA_MODEL)

    full_prompt = f"{system}\n\nUsuario: {prompt}\n\nAsistente:"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
            stream=True,
        )
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token:
                yield token
            if chunk.get("done", False):
                break
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"Timeout consultando Ollama ({OLLAMA_TIMEOUT_SECONDS}s)") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error consultando Ollama: {e}") from e


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _ask_openai(prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada y Ollama no disponible.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def ask_model(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    system: str = _SYSTEM_PROMPT,
) -> str:
    provider = LLM_PROVIDER

    if provider == "auto":
        provider = "ollama" if _ollama_available() else "openai"

    if provider == "ollama":
        if not _ollama_available():
            logger.warning("Ollama no responde — usando OpenAI como fallback.")
            return _ask_openai(prompt, system, temperature, max_tokens)
        return _ask_ollama(prompt, system, temperature, max_tokens)

    return _ask_openai(prompt, system, temperature, max_tokens)


def ask_model_stream(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    system: str = _SYSTEM_PROMPT,
):
    provider = LLM_PROVIDER

    if provider == "auto":
        provider = "ollama" if _ollama_available() else "openai"

    if provider == "ollama":
        if not _ollama_available():
            raise RuntimeError("Streaming no soportado con OpenAI. Usa Ollama.")
        yield from _ask_ollama_stream(prompt, system, temperature, max_tokens)
        return

    raise RuntimeError("Streaming solo soportado con Ollama.")
