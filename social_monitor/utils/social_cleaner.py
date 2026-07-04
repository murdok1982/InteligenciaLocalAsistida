import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_CLUTTER_PATTERNS = [
    r"(?i)(suscr[íi]bete|subscribe|sub[ í]|sígueme|follow me)",
    r"(?i)(dale like|like|comparte|share this video|click)",
    r"(?i)(apoya el canal|support|patreon|paypal|donation)",
    r"(?i)(gracias por ver|thanks for watching|thanks for)",
    r"(?i)(no olvides|don't forget|remember to)",
    r"(?i)(link en descripci[óo]n|link in description|link in bio)",
    r"(?i)(activa la|turn on|enable|bell icon|notifications)",
    r"(?i)(s[íi]guenos en|follow us on|check out our)",
    r"(?i)(membership|miembro|join this channel)",
    r"(?i)(rt[ _]?not[s]?|retweet|favorite|like this)",
]

_SPAM_PATTERNS = [
    r"(?i)(gana dinero|make money|trabaja desde casa|work from home)",
    r"(?i)(inversión segura|guaranteed|free money|sin riesgo)",
    r"(?i)(\b\w+\b.*\b\1\b.*\b\1\b)",  # repeated words (spam)
    r"(.)\1{5,}",  # repeated chars (spam)
]

_AD_KEYWORDS = [
    "sponsored", "patrocinado", "publicidad", "ad", "anuncio",
    "promocion", "affiliate", "paid partnership", "sorteo",
    "giveaway", "descuento", "discount", "coupon", "código",
]


def is_ad_or_spam(text: str) -> bool:
    text_lower = text.lower()
    for pat in _SPAM_PATTERNS:
        if re.search(pat, text_lower):
            return True
    for kw in _AD_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def remove_clutter(text: str) -> str:
    for pat in _CLUTTER_PATTERNS:
        text = re.sub(pat, "", text)
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def normalize_social_text(text: str, max_length: int = 2000) -> str:
    text = remove_clutter(text)
    text = re.sub(r"(.)\1{4,}", r"\1\1\1", text)
    text = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text)
    text = text.strip()
    return text[:max_length]


def dedup_social_posts(posts: list[dict], window_minutes: int = 30) -> list[dict]:
    seen_urls = set()
    seen_titles = set()
    deduped = []
    for p in posts:
        url = p.get("url", "")
        title = p.get("title", "")[:100]
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        seen_urls.add(url)
        if title:
            seen_titles.add(title)
        deduped.append(p)
    return deduped
