import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from social_monitor.utils.social_cleaner import dedup_social_posts, normalize_social_text
from social_monitor.utils.sentiment import analyze_sentiment

logger = logging.getLogger(__name__)


def collect_all_social(
    country_name: str = "",
    category: str = "",
    limit: int = 5,
    providers: list[str] = None,
) -> list[dict]:
    if providers is None:
        providers = ["telegram", "reddit", "twitter", "facebook"]

    results = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {}
        if "telegram" in providers:
            from social_monitor.providers.telegram_provider import search_telegram
            futures[executor.submit(search_telegram, country_name, category, limit)] = "telegram"
        if "reddit" in providers:
            from social_monitor.providers.reddit_provider import search_reddit
            futures[executor.submit(search_reddit, country_name, category, limit)] = "reddit"
        if "twitter" in providers:
            from social_monitor.providers.twitter_provider import search_twitter
            futures[executor.submit(search_twitter, country_name, category, limit)] = "twitter"
        if "facebook" in providers:
            from social_monitor.providers.facebook_provider import search_facebook
            futures[executor.submit(search_facebook, country_name, category, limit)] = "facebook"

        for future in as_completed(futures):
            provider = futures[future]
            try:
                posts = future.result()
                for p in posts:
                    p["title"] = normalize_social_text(p.get("title", ""), 200)
                    p["content"] = normalize_social_text(p.get("content", ""), 2000)
                    p["sentiment"] = analyze_sentiment(p.get("title", "") + " " + p.get("content", ""))
                results.extend(posts)
                logger.info("Social %s: %d posts para %s/%s", provider, len(posts), country_name, category)
            except Exception as e:
                logger.warning("Social %s error: %s", provider, e)

    results = dedup_social_posts(results)
    results.sort(key=lambda x: abs(x.get("sentiment", {}).get("score", 0)), reverse=True)
    logger.info("Social total: %d posts deduped para %s/%s", len(results), country_name, category)
    return results
