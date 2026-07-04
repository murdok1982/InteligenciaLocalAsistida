"""
Article content extractor: trafilatura primary, BeautifulSoup fallback.
Incluye protección SSRF robusta (bloqueo de IPs privadas, DNS rebinding, formatos alternativos).
"""
import ipaddress
import logging
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

logger = logging.getLogger(__name__)

_PRIVATE_RANGES = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("::/128"),
]

_ALLOWED_SCHEMES = {"http", "https"}

_DECIMAL_IP_PATTERN = re.compile(r"^\d{1,10}$")
_HEX_IP_PATTERN = re.compile(r"^0x[0-9a-fA-F]{1,8}$")
_OCTAL_IP_PATTERN = re.compile(r"^0[0-7]{1,11}$")
_DOTTED_PARTS_PATTERN = re.compile(
    r"^(?:0x[0-9a-fA-F]+|0[0-7]+|\d+)(?:\.(?:0x[0-9a-fA-F]+|0[0-7]+|\d+)){0,3}$"
)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DEFAULT_TIMEOUT = 20
_OCTET_MAX = 255
_IPV4_PARTS = 4
_IPV6_VERSION = 6
_MIN_TRAFILATURA_LEN = 150


def _parse_int_part(part: str) -> int:
    if part.startswith(("0x", "0X")):
        return int(part, 16)
    if part.startswith("0") and len(part) > 1:
        return int(part, 8)
    return int(part)


def _parse_dotted_notation(host: str) -> ipaddress.IPv4Address | None:
    if not _DOTTED_PARTS_PATTERN.match(host):
        return None
    parts = host.split(".")
    if len(parts) > _IPV4_PARTS:
        return None
    try:
        octets = [_parse_int_part(p) for p in parts]
    except (ValueError, OverflowError):
        return None
    if not all(0 <= o <= _OCTET_MAX for o in octets):
        return None
    while len(octets) < _IPV4_PARTS:
        octets.append(0)
    try:
        return ipaddress.IPv4Address(
            (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
        )
    except (ValueError, ipaddress.AddressValueError):
        return None


def _parse_single_value(host: str) -> ipaddress.IPv4Address | None:
    for pattern, base in (
        (_DECIMAL_IP_PATTERN, 10),
        (_HEX_IP_PATTERN, 16),
        (_OCTAL_IP_PATTERN, 8),
    ):
        if pattern.match(host):
            try:
                return ipaddress.IPv4Address(int(host, base))
            except (ValueError, ipaddress.AddressValueError):
                continue
    return None


def _parse_numeric_ip(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    result = _parse_single_value(host)
    if result is not None:
        return result

    return _parse_dotted_notation(host)


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_RANGES)


def _validate_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"Esquema no permitido: {parsed.scheme}")

    host = parsed.hostname
    if not host:
        raise ValueError("URL sin host")

    if parsed.username or parsed.password:
        raise ValueError("Credenciales en URL no permitidas")

    return host, parsed.geturl()


def _resolve_and_check(host: str) -> list[str]:
    ip = _parse_numeric_ip(host)
    if ip is not None:
        if _is_private_ip(ip):
            raise ValueError(f"IP privada/reservada bloqueada: {ip}")
        return [str(ip)]

    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"No se puede resolver: {host}") from e

    resolved_ips = []
    for _family, _, _, _, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(addr)
        except ValueError as err:
            raise ValueError(f"IP resuelta inválida: {addr}") from err
        if _is_private_ip(ip_obj):
            raise ValueError(f"DNS resolvió a IP privada: {host} → {addr}")
        resolved_ips.append(addr)

    if not resolved_ips:
        raise ValueError(f"Sin direcciones IP válidas para: {host}")

    return resolved_ips


def _build_addrinfo_patch(host: str, resolved_ips: list[str]):  # noqa: ANN202
    results = []
    for ip_str in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            family = socket.AF_INET6 if ip_obj.version == _IPV6_VERSION else socket.AF_INET
            results.append(
                (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip_str, None))
            )
        except ValueError:
            continue
    return {"host": host, "results": results}


def _safe_connect(url: str, resolved_ips: list[str], timeout: int) -> requests.Response:
    parsed = urlparse(url)
    host = parsed.hostname

    original_getaddrinfo = socket.getaddrinfo
    patch = _build_addrinfo_patch(host, resolved_ips)

    def _patched_getaddrinfo(hostname, port_arg, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if hostname == patch["host"] and patch["results"]:
            return [
                (fam, typ, proto, canon, (addr, port_arg))
                for fam, typ, proto, canon, (addr, _) in patch["results"]
            ]
        return original_getaddrinfo(hostname, port_arg, *args, **kwargs)

    socket.getaddrinfo = _patched_getaddrinfo
    try:
        headers = {"User-Agent": _UA}
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if location:
                redirect_host = urlparse(location).hostname
                if redirect_host:
                    _resolve_and_check(redirect_host)
                resp = requests.get(
                    location, headers=headers, timeout=timeout, allow_redirects=False,
                )

        return resp
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _is_ssrf(url: str) -> bool:
    try:
        host, _clean_url = _validate_url(url)
        _resolve_and_check(host)
    except ValueError as e:
        logger.warning("SSRF bloqueado: %s — %s", url, e)
        return True
    return False


def fetch_article_text(url: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    try:
        host, clean_url = _validate_url(url)
        resolved_ips = _resolve_and_check(host)
    except ValueError as e:
        logger.warning("SSRF bloqueado: %s — %s", url, e)
        return ""

    try:
        resp = _safe_connect(clean_url, resolved_ips, timeout)
        resp.raise_for_status()
        html = resp.text

        if _HAS_TRAFILATURA:
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if text and len(text) > _MIN_TRAFILATURA_LEN:
                return text.strip()

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        return re.sub(r"\s{2,}", " ", text).strip()
    except requests.exceptions.Timeout:
        logger.warning("Timeout extrayendo artículo: %s", url)
        return ""
    except requests.exceptions.RequestException as e:
        logger.warning("Error HTTP extrayendo artículo: %s — %s", url, e)
        return ""
    except Exception:
        logger.exception("Error inesperado extrayendo artículo: %s", url)
        return ""
