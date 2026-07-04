import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import yaml
import requests

logger = logging.getLogger(__name__)

_CONFIG_PATH = "social_monitor/config_social.yaml"

_AD_PATTERNS = [
    r"(?i)(sponsored|patrocinado|publicidad|ad|anuncio|promocionado)",
    r"(?i)(compra ahora|buy now|limited offer|sorteo|giveaway)",
]

_FACEBOOK_URL_PATTERNS = [
    r"facebook\.com/groups/(\d+)",
    r"facebook\.com/(\w+)/posts",
    r"fb\.com/groups/(\d+)",
]


def _is_ad(text: str) -> bool:
    for pat in _AD_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _clean_text(text: str) -> str:
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:2000]


def _extract_group_id(url: str) -> Optional[str]:
    for pat in _FACEBOOK_URL_PATTERNS:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def search_facebook_groups(keywords: list[str], limit: int = 20) -> list[dict]:
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f).get("facebook", {})
        access_token = cfg.get("access_token", "")
        group_ids = cfg.get("groups", [])
        search_terms = cfg.get("search_keywords", [])

        if not access_token:
            logger.warning("Facebook: falta access_token en config_social.yaml")
            return _facebook_fallback_scrape(cfg, keywords, limit)

        results = []
        cutoff = datetime.now() - timedelta(hours=cfg.get("max_age_hours", 168))

        for group_ref in group_ids:
            group_id = _extract_group_id(group_ref) or group_ref
            for term in (keywords + search_terms)[:5]:
                try:
                    url = f"https://graph.facebook.com/v19.0/{group_id}/feed"
                    params = {
                        "access_token": access_token,
                        "q": term,
                        "limit": min(limit, 25),
                        "fields": "message,created_time,permalink_url,from",
                    }
                    resp = requests.get(url, params=params, timeout=15)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for post in data.get("data", []):
                        msg = post.get("message", "")
                        if not msg or len(msg.strip()) < 20:
                            continue
                        created_str = post.get("created_time", "")
                        if created_str:
                            created = datetime.strptime(created_str.replace("+0000", ""), "%Y-%m-%dT%H:%M:%S")
                            if created < cutoff:
                                continue
                        if _is_ad(msg):
                            continue
                        results.append({
                            "title": msg[:80],
                            "content": _clean_text(msg),
                            "url": post.get("permalink_url", ""),
                            "source": f"FB/{group_ref}",
                            "provider": "facebook",
                            "date": created_str,
                            "reliability": "B",
                            "author": post.get("from", {}).get("name", ""),
                        })
                except Exception as e:
                    logger.warning("Facebook group %s error: %s", group_ref, e)
                    continue

        logger.info("Facebook Graph API: %d posts recolectados", len(results))
        return results

    except Exception as e:
        logger.warning("Facebook fetch error: %s", e)
        return []


def _facebook_fallback_scrape(cfg: dict, keywords: list[str], limit: int) -> list[dict]:
    results = []
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        login_email = cfg.get("login_email", "")
        login_pass = cfg.get("login_password", "")
        if not login_email or not login_pass:
            logger.warning("Facebook fallback: falta login_email/password")
            return []

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=opts)
        driver.get("https://mbasic.facebook.com/login")
        driver.find_element(By.NAME, "email").send_keys(login_email)
        driver.find_element(By.NAME, "pass").send_keys(login_pass)
        driver.find_element(By.NAME, "login").click()
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "root")))

        results = []
        for group_ref in cfg.get("groups", []):
            group_id = _extract_group_id(group_ref) or group_ref
            try:
                driver.get(f"https://mbasic.facebook.com/groups/{group_id}")
                posts = driver.find_elements(By.CSS_SELECTOR, "article, div[role='article']")
                for post in posts[:limit]:
                    text = post.text.strip()
                    if len(text) < 20:
                        continue
                    if _is_ad(text):
                        continue
                    results.append({
                        "title": text[:80],
                        "content": _clean_text(text),
                        "url": driver.current_url,
                        "source": f"FB/{group_ref}",
                        "provider": "facebook",
                        "date": datetime.now().isoformat(),
                        "reliability": "B",
                    })
            except Exception as e:
                logger.warning("Facebook scrape group %s error: %s", group_ref, e)
                continue
        driver.quit()
        logger.info("Facebook fallback scrape: %d posts", len(results))
        return results
    except Exception as e:
        logger.warning("Facebook fallback error: %s", e)
        return []


def search_facebook(country_name: str, category: str, limit: int = 10) -> list[dict]:
    posts = search_facebook_groups([country_name, category], limit=limit*2)
    keywords = [country_name.lower()] + category.lower().split()
    scored = []
    for p in posts:
        text = (p.get("title", "") + " " + p.get("content", "")).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]]
