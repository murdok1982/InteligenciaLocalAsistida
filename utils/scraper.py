"""
Article content extractor: trafilatura primary, BeautifulSoup fallback.
Includes SSRF protection (blocks private IP ranges).
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    import trafilatura
    _HAS_TRAFILATURA = True
except ImportError:
    _HAS_TRAFILATURA = False

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _is_ssrf(url: str) -> bool:
    try:
        host = urlparse(url).hostname
        if not host:
            return True
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return any(ip in net for net in _PRIVATE_RANGES)
    except Exception:
        return True


def fetch_article_text(url: str, timeout: int = 20) -> str:
    if _is_ssrf(url):
        return ""
    headers = {"User-Agent": _UA}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        html = resp.text

        if _HAS_TRAFILATURA:
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if text and len(text) > 150:
                return text.strip()

        # BeautifulSoup fallback
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        return re.sub(r"\s{2,}", " ", text).strip()
    except Exception:
        return ""
