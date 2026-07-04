import logging
import subprocess
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
EMBEDDING_MODEL = "nomic-embed-text"


def ensure_embedding_model() -> bool:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if EMBEDDING_MODEL not in result.stdout:
            logger.info("Modelo %s no encontrado, descargando...", EMBEDDING_MODEL)
            subprocess.run(
                ["ollama", "pull", EMBEDDING_MODEL],
                capture_output=True, text=True, timeout=120, check=False,
            )
        return True
    except Exception as e:
        logger.warning("Error ensuring embedding model: %s", e)
        return False


def get_embedding(text: str) -> list[float]:
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBEDDING_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embeddings", [None])[0] or []
    except Exception as e:
        logger.warning("Error obteniendo embedding: %s", e)
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_similar(
    query: str,
    country: Optional[str] = None,
    top_k: int = 10,
) -> list[dict]:
    try:
        from utils.database import get_embeddings_by_country

        query_emb = get_embedding(query)
        if not query_emb:
            return []

        rows = get_embeddings_by_country(country=country)
        if not rows:
            return []

        try:
            import numpy as np

            query_arr = np.array(query_emb, dtype=np.float64)
            embeddings_arr = np.array(
                [r["embedding"] for r in rows if r["embedding"]],
                dtype=np.float64,
            )
            if embeddings_arr.size == 0:
                return []
            norms = np.linalg.norm(embeddings_arr, axis=1)
            query_norm = np.linalg.norm(query_arr)
            if query_norm == 0:
                return []
            scores = embeddings_arr @ query_arr / (norms * query_norm)
            top_indices = np.argsort(scores)[-top_k:][::-1]
            results = []
            for idx in top_indices:
                if scores[idx] <= 0:
                    continue
                r = rows[idx]
                results.append({
                    "url": r.get("article_url", ""),
                    "title": "",
                    "source": "",
                    "summary": r.get("text_chunk", "")[:500],
                    "country": r.get("country", ""),
                    "similarity_score": float(scores[idx]),
                })
            return results
        except ImportError:
            scored = []
            for r in rows:
                emb = r.get("embedding")
                if not emb:
                    continue
                score = _cosine_similarity(query_emb, emb)
                if score > 0:
                    scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "url": r.get("article_url", ""),
                    "title": "",
                    "source": "",
                    "summary": r.get("text_chunk", "")[:500],
                    "country": r.get("country", ""),
                    "similarity_score": float(score),
                }
                for score, r in scored[:top_k]
            ]
    except Exception as e:
        logger.warning("Error en search_similar: %s", e)
        return []
