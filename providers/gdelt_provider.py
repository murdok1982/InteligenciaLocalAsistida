import requests

def search_gdelt(country_name: str, category: str, days_back: int = 30, limit: int = 10):
    params = {
        "query": f"{country_name} {category}",
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(limit),
        "sort": "DateDesc",
    }
    try:
        resp = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for a in data.get("articles", [])[:limit]:
            articles.append({
                "title": a.get("title") or "",
                "url": a.get("url") or "",
                "source": a.get("source") or "GDELT",
                "date": a.get("seendate") or "",
                "summary": a.get("title") or "",
                "provider": "gdelt",
            })
        return articles
    except Exception:
        return []
