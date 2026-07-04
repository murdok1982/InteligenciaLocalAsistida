import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "geoint.db")

_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class _Connection:
    def __init__(self):
        self.conn = None

    def __enter__(self):
        self.conn = _get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            try:
                if exc_type:
                    self.conn.rollback()
                self.conn.close()
            except sqlite3.Error:
                pass
        return False


def _execute_query(query: str, params: tuple | list = None, fetch: bool = False, fetch_one: bool = False, commit: bool = False):
    with _Connection() as conn:
        cursor = conn.execute(query, params or [])
        if commit:
            conn.commit()
        if fetch_one:
            row = cursor.fetchone()
            return dict(row) if row else None
        if fetch:
            return [dict(row) for row in cursor.fetchall()]
        return cursor.lastrowid


_SCHEMA_VERSION = 2


def _get_schema_version(conn) -> int:
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row else 0
    except sqlite3.Error:
        return 0


def _migrate(conn):
    version = _get_schema_version(conn)
    if version >= _SCHEMA_VERSION:
        return

    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    if version < 1 and "analysis_history" in existing:
        conn.executescript("DROP TABLE IF EXISTS analysis_history")
        conn.executescript("DROP TABLE IF EXISTS article_cache")
        conn.executescript("DROP TABLE IF EXISTS alerts")
        conn.executescript("DROP TABLE IF EXISTS reports")
        conn.executescript("DROP TABLE IF EXISTS schedules")

    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def init_db() -> None:
    try:
        with _Connection() as conn:
            _migrate(conn)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    system_prompt TEXT,
                    response TEXT,
                    provider TEXT,
                    model TEXT NOT NULL,
                    temperature REAL DEFAULT 0.3,
                    max_tokens INTEGER DEFAULT 2000,
                    status TEXT DEFAULT 'done',
                    region TEXT,
                    country TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS article_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT,
                    source TEXT,
                    published_date TEXT,
                    content TEXT,
                    country TEXT,
                    category TEXT,
                    reliability TEXT DEFAULT 'B',
                    cached_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    countries TEXT,
                    classification TEXT NOT NULL DEFAULT 'ABIERTO',
                    file_size INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    system_prompt TEXT,
                    temperature REAL DEFAULT 0.3,
                    max_tokens INTEGER DEFAULT 2000,
                    interval_seconds INTEGER NOT NULL DEFAULT 3600,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_country ON analysis_history(country);
                CREATE INDEX IF NOT EXISTS idx_analysis_region ON analysis_history(region);
                CREATE INDEX IF NOT EXISTS idx_analysis_created ON analysis_history(created_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_status ON analysis_history(status);
                CREATE INDEX IF NOT EXISTS idx_cache_country ON article_cache(country);
                CREATE INDEX IF NOT EXISTS idx_cache_category ON article_cache(category);
                CREATE INDEX IF NOT EXISTS idx_cache_cached_at ON article_cache(cached_at);
                CREATE INDEX IF NOT EXISTS idx_reports_generated ON reports(generated_at);
                CREATE INDEX IF NOT EXISTS idx_schedules_active ON schedules(active);

                CREATE TABLE IF NOT EXISTS article_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_url TEXT NOT NULL,
                    embedding BLOB,
                    text_chunk TEXT,
                    country TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (article_url) REFERENCES article_cache(url) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_emb_article_url ON article_embeddings(article_url);
                CREATE INDEX IF NOT EXISTS idx_emb_country ON article_embeddings(country);
            """)
            conn.commit()
        logger.info("Base de datos inicializada: %s (schema v%d)", DB_PATH, _SCHEMA_VERSION)
    except sqlite3.Error as e:
        logger.error("Error inicializando base de datos: %s", e)
        raise


def save_analysis(
    record_id: str,
    prompt: str,
    response: str,
    model: str,
    provider: str = "ollama",
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    status: str = "done",
    region: Optional[str] = None,
    country: Optional[str] = None,
) -> None:
    try:
        with _db_lock:
            with _Connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO analysis_history
                       (id, prompt, system_prompt, response, provider, model, temperature, max_tokens, status, region, country, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, prompt, system_prompt, response, provider, model,
                     temperature, max_tokens, status, region, country,
                     datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
                conn.commit()
        logger.info("Analisis guardado: id=%s pais=%s", record_id, country)
    except sqlite3.Error as e:
        logger.error("Error guardando analisis: %s", e)
        raise


def get_history(
    limit: int = 50,
    country: Optional[str] = None,
    region: Optional[str] = None,
) -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                query = "SELECT * FROM analysis_history WHERE 1=1"
                params: list = []

                if country:
                    query += " AND country = ?"
                    params.append(country)
                if region:
                    query += " AND region = ?"
                    params.append(region)

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error("Error obteniendo historial: %s", e)
        raise


def get_analysis(record_id: str) -> Optional[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                row = conn.execute(
                    "SELECT * FROM analysis_history WHERE id = ?", (record_id,)
                ).fetchone()
                return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error("Error obteniendo analisis: %s", e)
        raise


def delete_analysis(record_id: str) -> bool:
    try:
        with _db_lock:
            with _Connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM analysis_history WHERE id = ?", (record_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
            if deleted:
                logger.info("Analisis eliminado: id=%s", record_id)
            return deleted
    except sqlite3.Error as e:
        logger.error("Error eliminando analisis: %s", e)
        raise


def cache_articles(articles: list[dict], ttl_hours: int = 2) -> int:
    try:
        with _db_lock:
            with _Connection() as conn:
                cutoff = (datetime.now() - timedelta(hours=ttl_hours)).isoformat()
                conn.execute("DELETE FROM article_cache WHERE cached_at < ?", (cutoff,))

                count = 0
                for article in articles:
                    try:
                        conn.execute(
                            """INSERT OR REPLACE INTO article_cache
                               (url, title, source, published_date, content, country, category, reliability)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                article.get("url", ""),
                                article.get("title", ""),
                                article.get("source", ""),
                                article.get("date", article.get("published_date", "")),
                                article.get("content", article.get("summary", "")),
                                article.get("country", ""),
                                article.get("category", article.get("categories", [None])[0] if isinstance(article.get("categories"), list) else ""),
                                article.get("reliability", "B"),
                            ),
                        )
                        count += 1
                        try:
                            from utils.embeddings import get_embedding
                            text_to_embed = f"{article.get('title', '')} {article.get('content', article.get('summary', ''))}"
                            emb = get_embedding(text_to_embed)
                            if emb:
                                store_article_embedding(article.get("url", ""), emb, text_to_embed[:1000], article.get("country", ""))
                        except Exception:
                            pass
                    except sqlite3.Error as e:
                        logger.warning("Error cacheando articulo %s: %s", article.get("url"), e)

                conn.commit()
                logger.info("Articulos cacheados: %d", count)
                return count
    except sqlite3.Error as e:
        logger.error("Error en cache_articles: %s", e)
        raise


def get_cached_articles(
    country: Optional[str] = None,
    category: Optional[str] = None,
    max_age_hours: int = 2,
) -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
                query = "SELECT * FROM article_cache WHERE cached_at >= ?"
                params: list = [cutoff]

                if country:
                    query += " AND country = ?"
                    params.append(country)
                if category:
                    query += " AND category = ?"
                    params.append(category)

                query += " ORDER BY cached_at DESC"
                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error("Error obteniendo articulos cacheados: %s", e)
        raise


def save_report(
    filepath: str,
    filename: str,
    countries: list[str],
    classification: str = "ABIERTO",
    file_size: int = 0,
) -> int:
    try:
        with _db_lock:
            with _Connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO reports (filepath, filename, countries, classification, file_size)
                       VALUES (?, ?, ?, ?, ?)""",
                    (filepath, filename, json.dumps(countries), classification, file_size),
                )
                conn.commit()
                report_id = cursor.lastrowid
                logger.info("Informe guardado: id=%s path=%s", report_id, filepath)
                return report_id
    except sqlite3.Error as e:
        logger.error("Error guardando informe: %s", e)
        raise


def get_reports(limit: int = 20) -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM reports ORDER BY generated_at DESC LIMIT ?", (limit,)
                ).fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    if d.get("countries"):
                        try:
                            d["countries"] = json.loads(d["countries"])
                        except json.JSONDecodeError:
                            d["countries"] = []
                    results.append(d)
                return results
    except sqlite3.Error as e:
        logger.error("Error obteniendo informes: %s", e)
        raise


def save_schedule(
    schedule_id: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    interval_seconds: int = 3600,
) -> None:
    try:
        with _db_lock:
            with _Connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO schedules
                       (id, prompt, system_prompt, temperature, max_tokens, interval_seconds, active, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                    (schedule_id, prompt, system_prompt, temperature, max_tokens,
                     interval_seconds, datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
                conn.commit()
    except sqlite3.Error as e:
        logger.error("Error guardando schedule: %s", e)
        raise


def get_schedules() -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM schedules WHERE active = 1 ORDER BY created_at DESC"
                ).fetchall()
                return [dict(r) for r in rows]
    except sqlite3.Error as e:
        logger.error("Error obteniendo schedules: %s", e)
        raise


def delete_schedule(schedule_id: str) -> bool:
    try:
        with _db_lock:
            with _Connection() as conn:
                conn.execute(
                    "UPDATE schedules SET active = 0 WHERE id = ?", (schedule_id,)
                )
                conn.commit()
                cursor = conn.execute(
                    "DELETE FROM schedules WHERE id = ?", (schedule_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
                return deleted
    except sqlite3.Error as e:
        logger.error("Error eliminando schedule: %s", e)
        raise


def get_related_context(
    country: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                query = "SELECT prompt, response, country, region, created_at FROM analysis_history WHERE 1=1"
                params: list = []

                if country:
                    query += " AND country = ?"
                    params.append(country)
                if region:
                    query += " AND region = ?"
                    params.append(region)

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error("Error obteniendo contexto relacionado: %s", e)
        raise


def store_article_embedding(article_url: str, embedding: list[float], text_chunk: str, country: str) -> None:
    try:
        embedding_json = json.dumps(embedding)
        with _db_lock:
            with _Connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO article_embeddings
                       (article_url, embedding, text_chunk, country)
                       VALUES (?, ?, ?, ?)""",
                    (article_url, embedding_json, text_chunk, country),
                )
                conn.commit()
    except sqlite3.Error as e:
        logger.warning("Error guardando embedding para %s: %s", article_url, e)


def get_embeddings_by_country(country: Optional[str] = None) -> list[dict]:
    try:
        with _db_lock:
            with _Connection() as conn:
                query = "SELECT article_url, embedding, text_chunk, country FROM article_embeddings"
                params: list = []
                if country:
                    query += " WHERE country = ?"
                    params.append(country)
                rows = conn.execute(query, params).fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    try:
                        d["embedding"] = json.loads(d["embedding"])
                    except (json.JSONDecodeError, TypeError):
                        d["embedding"] = []
                    results.append(d)
                return results
    except sqlite3.Error as e:
        logger.warning("Error obteniendo embeddings: %s", e)
        return []


def build_context_prompt(
    country: Optional[str] = None,
    region: Optional[str] = None,
    query: str = "latest geopolitical developments and strategic changes",
) -> str:
    try:
        from utils.embeddings import search_similar
        articles = search_similar(query, country=country, top_k=10)
    except Exception:
        context_items = get_related_context(country=country, region=region, limit=5)
        if not context_items:
            return ""
        return _format_rag_fallback(context_items)

    if not articles:
        return ""

    lines = ["CONTEXTO RELEVANTE (RAG):"]
    lines.append("=" * 50)
    for i, a in enumerate(articles, 1):
        similarity = a.get("similarity_score", 0)
        lines.append(f"\n--- Fuente #{i} (similitud: {similarity:.2f}) [ID:{i}] ---")
        lines.append(f"Titulo: {a.get('title', 'N/A')}")
        lines.append(f"URL: {a.get('url', 'N/A')}")
        lines.append(f"Contenido: {a.get('summary', '')[:500]}")
    lines.append("\n" + "=" * 50)
    lines.append("INSTRUCCION DE CITAS: Cualquier afirmacion categorica que hagas debe incluir al final el numero de fuente entre corchetes, ej. [Fuente #1]. Asi el analista puede verificar el origen.")
    lines.append("Usa este contexto obtenido por similitud semantica como base para tu analisis.")
    lines.append("Cuando menciones un dato especifico, INDICA siempre de que fuente proviene usando [Fuente #N].")
    return "\n".join(lines)


def _format_rag_fallback(context_items: list) -> str:
    lines = ["CONTEXTO DE ANALISIS PREVIOS (RAG fallback):"]
    lines.append("=" * 50)
    for i, item in enumerate(context_items, 1):
        lines.append(f"\n--- Analisis #{i} ({item.get('created_at', 'N/A')}) ---")
        lines.append(f"Pais: {item.get('country', 'N/A')}")
        lines.append(f"Respuesta: {item.get('response', '')[:500]}")
    lines.append("\n" + "=" * 50)
    return "\n".join(lines)


def get_stats() -> dict:
    try:
        with _db_lock:
            with _Connection() as conn:
                total_analyses = conn.execute(
                    "SELECT COUNT(*) FROM analysis_history"
                ).fetchone()[0]
                total_articles = conn.execute(
                    "SELECT COUNT(*) FROM article_cache"
                ).fetchone()[0]
                total_reports = conn.execute(
                    "SELECT COUNT(*) FROM reports"
                ).fetchone()[0]
                db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                return {
                    "total_analyses": total_analyses,
                    "total_articles_cached": total_articles,
                    "total_reports": total_reports,
                    "db_path": DB_PATH,
                    "db_size_bytes": db_size,
                }
    except sqlite3.Error as e:
        logger.error("Error obteniendo estadisticas: %s", e)
        return {}
