import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import yaml
from telethon import TelegramClient

logger = logging.getLogger(__name__)

_CONFIG_PATH = None
_client: Optional[TelegramClient] = None

_AD_PATTERNS = [
    r"(?i)(publicidad|ad|sponsored|patrocinado|anuncio|promocion|affiliate)",
    r"(?i)(gana dinero|make money|click here|compra ahora|buy now)",
    r"(?i)(sorteo|giveaway|premio|prize|descuento|discount)",
]

_CRISIS_TRIGGERS = [
    "misil", "ataque", "guerra", "conflicto", "sanciones", "movilizacion",
    "invasión", "ciberataque", "golpe", "protestas", "crisis", "emergencia",
    "nuclear", "despliegue", "evacuacion", "bloqueo",
]


def _is_ad(text: str) -> bool:
    for pat in _AD_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _clean_message(text: str) -> str:
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:2000]


async def _ensure_client() -> Optional[TelegramClient]:
    global _client
    if _client and _client.is_connected():
        return _client
    try:
        with open(_CONFIG_PATH or "social_monitor/config_social.yaml") as f:
            cfg = yaml.safe_load(f).get("telegram", {})
        api_id = cfg.get("api_id", "")
        api_hash = cfg.get("api_hash", "")
        phone = cfg.get("phone", "")
        session = cfg.get("session_name", "geo_intel_telegram")
        if not api_id or not api_hash:
            logger.warning("Telegram: falta api_id/api_hash en config_social.yaml")
            return None
        _client = TelegramClient(session, int(api_id), api_hash)
        await _client.start(phone=phone)
        logger.info("Telegram cliente conectado")
        return _client
    except Exception as e:
        logger.warning("Telegram client error: %s", e)
        return None


async def fetch_telegram_posts(limit_per_channel: int = 50, max_age_hours: int = 168) -> list[dict]:
    client = await _ensure_client()
    if not client:
        return []
    try:
        with open(_CONFIG_PATH or "social_monitor/config_social.yaml") as f:
            cfg = yaml.safe_load(f).get("telegram", {})
        channels = cfg.get("channels", [])
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        results = []
        for ch in channels:
            try:
                entity = await client.get_entity(ch)
                async for msg in client.iter_messages(entity, limit=limit_per_channel):
                    if msg.date and msg.date.replace(tzinfo=None) < cutoff:
                        continue
                    if not msg.text or len(msg.text.strip()) < 20:
                        continue
                    if _is_ad(msg.text):
                        continue
                    results.append({
                        "title": msg.text[:80],
                        "content": _clean_message(msg.text),
                        "url": f"https://t.me/{entity.username}/{msg.id}" if entity.username else "",
                        "source": entity.title or ch,
                        "provider": "telegram",
                        "date": msg.date.isoformat() if msg.date else "",
                        "reliability": "B",
                        "views": getattr(msg, "views", 0),
                        "forwards": getattr(msg, "forwards", 0),
                    })
            except Exception as e:
                logger.warning("Telegram channel %s error: %s", ch, e)
                continue
        logger.info("Telegram: %d mensajes recolectados", len(results))
        return results
    except Exception as e:
        logger.warning("Telegram fetch error: %s", e)
        return []


def search_telegram(country_name: str, category: str, limit: int = 10) -> list[dict]:
    loop = asyncio.new_event_loop()
    try:
        posts = loop.run_until_complete(fetch_telegram_posts())
    finally:
        loop.close()
    keywords = [country_name.lower()] + category.lower().split()
    scored = []
    for p in posts:
        text = (p.get("title", "") + " " + p.get("content", "")).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            crisis_bonus = sum(3 for t in _CRISIS_TRIGGERS if t in text)
            scored.append((score + crisis_bonus, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]]
