"""
YouTube OSINT via public RSS feeds — no API key required.
Uses https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
"""
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import feedparser

_SOURCES_PATH = Path(__file__).parent.parent / "sources" / "sources.json"
_RATE_LIMIT_S = 0.5


@dataclass
class VideoItem:
    title: str
    url: str
    channel: str
    published: str
    summary: str
    provider: str = "youtube"
    reliability: str = "B"


def fetch_youtube_channels(limit_per_channel: int = 10) -> List[VideoItem]:
    if not _SOURCES_PATH.exists():
        return []

    with open(_SOURCES_PATH, "r", encoding="utf-8") as f:
        sources_data = json.load(f)

    channels = sources_data.get("youtube_channels", [])
    items = []

    for ch in channels:
        channel_id = ch.get("channel_id")
        if not channel_id:
            continue
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:limit_per_channel]:
                title = getattr(entry, "title", "") or ""
                link = getattr(entry, "link", "") or ""
                published = getattr(entry, "published", "") or ""
                summary = ""
                if hasattr(entry, "summary"):
                    summary = re.sub(r"<[^>]+>", "", entry.summary).strip()[:400]
                items.append(VideoItem(
                    title=title,
                    url=link,
                    channel=ch.get("name", "YouTube"),
                    published=published,
                    summary=summary,
                    reliability=ch.get("reliability", "B"),
                ))
            time.sleep(_RATE_LIMIT_S)
        except Exception:
            continue

    return items


def search_youtube(country_name: str, category: str, limit: int = 10) -> List[dict]:
    """Return YouTube videos relevant to country + category as article dicts."""
    videos = fetch_youtube_channels(limit_per_channel=15)
    keywords = [country_name.lower()] + category.lower().split()

    scored = []
    for v in videos:
        text = (v.title + " " + v.summary).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, v))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "title": v.title,
            "url": v.url,
            "source": v.channel,
            "date": v.published,
            "summary": v.summary,
            "provider": "youtube",
            "reliability": v.reliability,
        }
        for _, v in scored[:limit]
    ]
