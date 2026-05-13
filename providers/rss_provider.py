"""
RSS/Atom aggregator using feedparser. No API key required.
Reads source list from sources/sources.json.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import List, Dict

import feedparser
from bs4 import BeautifulSoup

_SOURCES_PATH = Path(__file__).parent.parent / "sources" / "sources.json"
_RATE_LIMIT_S = 0.5  # seconds between feed fetches


def _strip_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return re.sub(r"\s{2,}", " ", soup.get_text(" ", strip=True))


def _dedup_key(article: dict) -> str:
    return hashlib.sha256((article.get("url") or article.get("title") or "").encode()).hexdigest()


def fetch_rss_sources(
    category_filter: str = None,
    region_filter: str = None,
    limit_per_feed: int = 10,
) -> List[Dict]:
    """
    Fetch articles from all RSS sources optionally filtered by category/region.
    Returns a deduplicated list of article dicts.
    """
    if not _SOURCES_PATH.exists():
        return []

    with open(_SOURCES_PATH, "r", encoding="utf-8") as f:
        sources_data = json.load(f)

    rss_sources = sources_data.get("rss_feeds", [])

    if category_filter:
        rss_sources = [
            s for s in rss_sources
            if category_filter.lower() in [c.lower() for c in s.get("categories", [])]
        ]
    if region_filter:
        rss_sources = [
            s for s in rss_sources
            if region_filter.lower() in s.get("region", "").lower()
        ]

    seen = set()
    articles = []

    for source in rss_sources:
        url = source.get("url")
        if not url:
            continue
        try:
            feed = feedparser.parse(url)
            entries = feed.entries[:limit_per_feed]
            for entry in entries:
                title = getattr(entry, "title", "") or ""
                link = getattr(entry, "link", "") or ""
                summary = _strip_html(
                    getattr(entry, "summary", "")
                    or getattr(entry, "description", "")
                    or ""
                )
                date = ""
                if hasattr(entry, "published"):
                    date = entry.published
                elif hasattr(entry, "updated"):
                    date = entry.updated

                article = {
                    "title": title,
                    "url": link,
                    "source": source.get("name", feed.feed.get("title", "RSS")),
                    "date": date,
                    "summary": summary[:500],
                    "provider": "rss",
                    "reliability": source.get("reliability", "B"),
                    "categories": source.get("categories", []),
                    "region": source.get("region", "Global"),
                    "language": source.get("language", "en"),
                }
                key = _dedup_key(article)
                if key not in seen and title:
                    seen.add(key)
                    articles.append(article)

            time.sleep(_RATE_LIMIT_S)
        except Exception:
            continue

    return articles


def search_rss(
    country_name: str,
    category: str,
    days_back: int = 7,
    limit: int = 20,
) -> List[Dict]:
    """Search RSS articles relevant to a country and category."""
    all_articles = fetch_rss_sources(limit_per_feed=20)
    keywords = [country_name.lower()] + category.lower().split()

    scored = []
    for article in all_articles:
        text = (article["title"] + " " + article["summary"]).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:limit]]
