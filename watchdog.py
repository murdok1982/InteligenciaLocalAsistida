"""
watchdog.py — Lightweight background monitor that polls RSS feeds every 15 minutes
for crisis trigger keywords and emits Windows native toast notifications.
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import feedparser

from utils.database import init_db

logger = logging.getLogger("watchdog")

_CRISIS_TRIGGERS = [
    "ley marcial", "martial law", "cierre de frontera", "border closure",
    "movilización general", "general mobilization", "evacuación", "evacuation",
    "ciberataque masivo", "massive cyberattack", "estado de excepción",
    "state of emergency", "ataque nuclear", "nuclear attack", "ataque terrorista",
    "terrorist attack", "golpe de estado", "coup d'etat", "declaración de guerra",
    "declaration of war", "derribo", "shoot down", "explosión nuclear",
    "nuclear explosion", "ataque con misiles", "missile strike",
    "incursión militar", "military incursion", "operación encubierta",
    "covert operation", "sabotaje", "sabotage", "asedio", "siege",
]

_SOURCES_PATH = Path(__file__).parent / "sources" / "sources.json"
_POLL_INTERVAL = 900  # 15 minutes

_alerts: list[dict] = []
_alerts_lock = threading.Lock()


def _check_crisis_triggers(text: str) -> list[str]:
    text_lower = text.lower()
    hits = []
    for trigger in _CRISIS_TRIGGERS:
        if trigger in text_lower:
            hits.append(trigger)
    return hits


def poll_sources() -> list[dict]:
    if not _SOURCES_PATH.exists():
        return []
    with open(_SOURCES_PATH, encoding="utf-8") as f:
        sources = json.load(f).get("rss_feeds", [])

    alerts = []
    for source in sources[:50]:
        url = source.get("url")
        if not url:
            continue
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                combined = f"{title} {summary}"
                hits = _check_crisis_triggers(combined)
                if hits:
                    alerts.append({
                        "title": title,
                        "url": getattr(entry, "link", "") or "",
                        "source": source.get("name", "RSS"),
                        "triggers": hits,
                        "country": source.get("country"),
                        "region": source.get("region", "Global"),
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    })
            time.sleep(0.3)
        except Exception:
            continue
    return alerts


def send_windows_notification(title: str, body: str):
    try:
        from plyer import notification
        notification.notify(title=title, message=body, timeout=10)
    except ImportError:
        logger.warning("plyer no instalado, notificacion omitida: %s - %s", title, body)


def _watchdog_loop(stop_event: threading.Event):
    init_db()
    logger.info("Watchdog iniciado (intervalo=%ds)", _POLL_INTERVAL)
    while not stop_event.is_set():
        try:
            new_alerts = poll_sources()
            with _alerts_lock:
                for alert in new_alerts:
                    _alerts.append(alert)
                    msg = f"[{alert.get('region', '?')}] {alert.get('title', '')[:120]}"
                    logger.warning("ALERTA: %s (disparadores: %s)", msg, alert["triggers"])
                    send_windows_notification(
                        f"Alerta {alert.get('region', 'Geo')}",
                        f"{alert.get('title', '')[:80]}...\nDisparadores: {', '.join(alert['triggers'])}",
                    )
        except Exception as exc:
            logger.error("Watchdog error: %s", exc)
        stop_event.wait(_POLL_INTERVAL)


def start_watchdog() -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    thread = threading.Thread(target=_watchdog_loop, args=(stop_event,), daemon=True)
    thread.start()
    return stop_event, thread


def get_recent_alerts(minutes: int = 60) -> list[dict]:
    with _alerts_lock:
        return list(_alerts)
