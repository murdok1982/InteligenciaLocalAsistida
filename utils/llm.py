"""
LLM adapter: Ollama (primary, local) → OpenAI (fallback, optional).
Set LLM_PROVIDER=ollama or LLM_PROVIDER=openai in .env.
"""
import os
import json
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:4b")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_SYSTEM_PROMPT = (
    "Eres un analista de inteligencia estratégica de nivel estatal. "
    "Redacta en español con rigor, precisión verificable y lenguaje técnico-militar. "
    "Evita especulaciones sin base factual. Cita fuentes cuando sea posible."
)


def _ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _ask_ollama(prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"].strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _ask_openai(prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurada y Ollama no disponible.")
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
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
            print("⚠️  Ollama no responde — usando OpenAI como fallback.")
            return _ask_openai(prompt, system, temperature, max_tokens)
        return _ask_ollama(prompt, system, temperature, max_tokens)

    return _ask_openai(prompt, system, temperature, max_tokens)
