import os
import requests
from datetime import datetime, timedelta
from urllib.parse import quote_plus

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")


def search_newsapi(
    country_name: str,
    category: str,
    days_back: int = 30,
    limit: int = 10,
    language: str = "en",
):
    if not NEWSAPI_KEY:
        return []
    start_date = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
    q = quote_plus(f"{country_name} {category}")
    url = (
        f"https://newsapi.org/v2/everything?q={q}"
        f"&from={start_date}&language={language}&pageSize={limit}&sortBy=publishedAt"
    )
    headers = {"X-Api-Key": NEWSAPI_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for a in data.get("articles", [])[:limit]:
            articles.append({
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "source": (a.get("source") or {}).get("name", "NewsAPI"),
                "date": a.get("publishedAt") or "",
                "summary": a.get("description") or "",
                "provider": "newsapi",
            })
        return articles
    except Exception:
        return []
