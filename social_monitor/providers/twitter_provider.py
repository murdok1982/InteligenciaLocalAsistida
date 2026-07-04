import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = "social_monitor/config_social.yaml"
_api = None

_AD_PATTERNS = [
    r"(?i)(sponsored|promoted|ad|affiliate|paid partnership)",
    r"(?i)(click here|limited offer|buy now|subscribe now)",
]


def _is_ad(text: str) -> bool:
    for pat in _AD_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _clean_tweet(text: str) -> str:
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:2000]


def _ensure_api():
    global _api
    if _api is not None:
        return _api
    try:
        import tweepy
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f).get("twitter", {})
        bearer = cfg.get("bearer_token", "")
        if bearer:
            client = tweepy.Client(bearer_token=bearer)
            _api = client
            logger.info("Twitter API v2 conectada (bearer)")
            return _api
        api_key = cfg.get("api_key", "")
        api_secret = cfg.get("api_secret", "")
        access_token = cfg.get("access_token", "")
        access_secret = cfg.get("access_secret", "")
        if api_key and api_secret:
            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
            api = tweepy.API(auth)
            _api = api
            logger.info("Twitter API v1.1 conectada (oauth)")
            return _api
        logger.warning("Twitter: sin credenciales configuradas")
        return None
    except Exception as e:
        logger.warning("Twitter client error: %s", e)
        return None


def fetch_twitter_posts(limit_per_account: int = 20, max_age_hours: int = 168) -> list[dict]:
    api = _ensure_api()
    if not api:
        return []
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f).get("twitter", {})
        accounts = cfg.get("accounts", [])
        results = []
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        for username in accounts:
            try:
                if hasattr(api, "get_user"):
                    user = api.get_user(username=username)
                    tweets = api.get_users_tweets(id=user.data.id, max_results=limit_per_account)
                    if tweets.data:
                        for tweet in tweets.data:
                            created = tweet.created_at.replace(tzinfo=None) if tweet.created_at else None
                            if created and created < cutoff:
                                continue
                            if not tweet.text or len(tweet.text.strip()) < 10:
                                continue
                            if _is_ad(tweet.text):
                                continue
                            results.append({
                                "title": tweet.text[:80],
                                "content": _clean_tweet(tweet.text),
                                "url": f"https://twitter.com/{username}/status/{tweet.id}",
                                "source": f"@{username}",
                                "provider": "twitter",
                                "date": created.isoformat() if created else "",
                                "reliability": "B",
                            })
                else:
                    tweets = api.user_timeline(screen_name=username, count=limit_per_account)
                    for tweet in tweets:
                        created = tweet.created_at.replace(tzinfo=None)
                        if created < cutoff:
                            continue
                        if not tweet.text or len(tweet.text.strip()) < 10:
                            continue
                        if _is_ad(tweet.text):
                            continue
                        results.append({
                            "title": tweet.text[:80],
                            "content": _clean_tweet(tweet.text),
                            "url": f"https://twitter.com/{username}/status/{tweet.id}",
                            "source": f"@{username}",
                            "provider": "twitter",
                            "date": created.isoformat(),
                            "reliability": "B",
                            "retweets": tweet.retweet_count,
                            "likes": tweet.favorite_count,
                        })
            except Exception as e:
                logger.warning("Twitter @%s error: %s", username, e)
                continue
        logger.info("Twitter: %d tweets recolectados", len(results))
        return results
    except Exception as e:
        logger.warning("Twitter fetch error: %s", e)
        return []


def search_twitter(country_name: str, category: str, limit: int = 10) -> list[dict]:
    tweets = fetch_twitter_posts()
    keywords = [country_name.lower()] + category.lower().split()
    scored = []
    for t in tweets:
        text = (t.get("title", "") + " " + t.get("content", "")).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]]
