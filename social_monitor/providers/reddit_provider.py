import logging
import re
from datetime import datetime, timedelta

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = None
_reddit = None

_AD_PATTERNS = [
    r"(?i)(sponsored|promoted|advertisement|affiliate|paid)",
    r"(?i)(check out this|click here|limited time|offer expires)",
]


def _is_ad(text: str) -> bool:
    for pat in _AD_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _clean_text(text: str) -> str:
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"r/\w+", "", text)
    text = re.sub(r"u/\w+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:2000]


def _ensure_reddit():
    global _reddit
    if _reddit is not None:
        return _reddit
    try:
        import praw
        with open(_CONFIG_PATH or "social_monitor/config_social.yaml") as f:
            cfg = yaml.safe_load(f).get("reddit", {})
        _reddit = praw.Reddit(
            client_id=cfg.get("client_id", ""),
            client_secret=cfg.get("client_secret", ""),
            user_agent=cfg.get("user_agent", "GeoIntelOSINT/v1.0"),
        )
        logger.info("Reddit cliente conectado")
        return _reddit
    except Exception as e:
        logger.warning("Reddit client error: %s", e)
        return None


def fetch_reddit_posts(limit_per_subreddit: int = 25, max_age_hours: int = 168) -> list[dict]:
    reddit = _ensure_reddit()
    if not reddit:
        return []
    try:
        with open(_CONFIG_PATH or "social_monitor/config_social.yaml") as f:
            cfg = yaml.safe_load(f).get("reddit", {})
        subreddits = cfg.get("subreddits", [])
        sort = cfg.get("sort", "hot")
        results = []
        for sr_name in subreddits:
            try:
                subreddit = reddit.subreddit(sr_name)
                posts = getattr(subreddit, sort)(limit=limit_per_subreddit)
                for post in posts:
                    if _is_ad(post.title + " " + (post.selftext or "")):
                        continue
                    created = datetime.fromtimestamp(post.created_utc)
                    if datetime.now() - created > timedelta(hours=max_age_hours):
                        continue
                    text = (post.title + " " + (post.selftext or "")).strip()
                    if len(text) < 20:
                        continue
                    results.append({
                        "title": post.title[:200],
                        "content": _clean_text(post.selftext or ""),
                        "url": f"https://reddit.com{post.permalink}",
                        "source": f"r/{sr_name}",
                        "provider": "reddit",
                        "date": created.isoformat(),
                        "reliability": "B",
                        "score": post.score,
                        "comments": post.num_comments,
                    })
            except Exception as e:
                logger.warning("Reddit r/%s error: %s", sr_name, e)
                continue
        logger.info("Reddit: %d posts recolectados", len(results))
        return results
    except Exception as e:
        logger.warning("Reddit fetch error: %s", e)
        return []


def search_reddit(country_name: str, category: str, limit: int = 10) -> list[dict]:
    posts = fetch_reddit_posts()
    keywords = [country_name.lower()] + category.lower().split()
    scored = []
    for p in posts:
        text = (p.get("title", "") + " " + p.get("content", "")).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]]
