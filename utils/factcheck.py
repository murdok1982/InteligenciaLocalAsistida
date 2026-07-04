"""
Módulo de fact-checking básico: extracción de afirmaciones, verificación cruzada
contra fuentes, evaluación de fiabilidad e inserción de referencias.
"""
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_MIN_NAME_LEN = 5
_MIN_SENTENCE_LEN = 10
_CONTRADICTION_THRESHOLD = 0.4


@dataclass
class Claim:
    text: str
    claim_type: str
    value: str
    start: int = 0
    end: int = 0


@dataclass
class VerificationResult:
    claim: Claim
    matched_source: str = ""
    matched_snippet: str = ""
    confidence: float = 0.0
    verified: bool = False


@dataclass
class ReliabilityReport:
    score: float = 0.0
    total_claims: int = 0
    verified_claims: int = 0
    unverified_claims: int = 0
    contradicted_claims: int = 0
    details: list = field(default_factory=list)


_DATE_PATTERNS = [
    re.compile(
        r"\b(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|"
        r"julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]

_NUMBER_PATTERNS = [
    re.compile(
        r"\b(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*"
        r"(?:millones|millards|billones|trillones|mil|cientos|"
        r"personas|muertos|heridos|desplazados|refugiados|"
        r"kilómetros|km|metros|m|dólares|euros|USD|EUR|%|por ciento)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d+(?:\.\d+)?\s*%)\b"),
    re.compile(r"\b(\$\s*\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\b"),
]

_NAME_PATTERNS = [
    re.compile(
        r"\b((?:el\s+)?(?:presidente|primer ministro|canciller|ministro|general|"
        r"secretario|director|jefe|comandante|embajador|senador|diputado)\s+"
        r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3})\b"
    ),
    re.compile(
        r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"
        r"(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)\b"
    ),
]

_ORG_PATTERNS = [
    re.compile(
        r"\b((?:ONU|OTAN|UE|OEA|FMI|BM|OMS|UNICEF|UNESCO|CIA|FBI|MI6|"
        r"Mossad|FSB|MSZ|BND|DGSE|RAW|ISI|MSS)[A-Z]*)\b"
    ),
    re.compile(
        r"\b((?:Ministerio|Gobierno|Ejército|Armada|Fuerza Aérea|"
        r"Pentágono|Kremlin|Casa Blanca|Parlamento|Congreso|Senado)"
        r"(?:\s+de\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)\b"
    ),
]


def _fuzzy_match(text_a: str, text_b: str) -> float:
    return SequenceMatcher(None, text_a.lower(), text_b.lower()).ratio()


def _extract_context(text: str, start: int, end: int, window: int = 120) -> str:
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].strip()


def _make_claim(text: str, match: re.Match, claim_type: str, seen: set[str]) -> Claim | None:
    value = match.group(1).strip()
    if value in seen:
        return None
    if claim_type == "person" and len(value) <= _MIN_NAME_LEN:
        return None
    seen.add(value)
    context = _extract_context(text, match.start(), match.end())
    return Claim(
        text=context,
        claim_type=claim_type,
        value=value,
        start=match.start(),
        end=match.end(),
    )


def _extract_pattern_claims(
    text: str, patterns: list[re.Pattern], claim_type: str, seen: set[str],
) -> list[Claim]:
    claims = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            claim = _make_claim(text, match, claim_type, seen)
            if claim is not None:
                claims.append(claim)
    return claims


def extract_claims(text: str) -> list[Claim]:
    seen: set[str] = set()
    claims: list[Claim] = []

    claims.extend(_extract_pattern_claims(text, _DATE_PATTERNS, "date", seen))
    claims.extend(_extract_pattern_claims(text, _NUMBER_PATTERNS, "number", seen))
    claims.extend(_extract_pattern_claims(text, _NAME_PATTERNS, "person", seen))
    claims.extend(_extract_pattern_claims(text, _ORG_PATTERNS, "organization", seen))

    logger.info("Extraídas %d afirmaciones del texto", len(claims))
    return claims


def _find_exact_match(
    claim: Claim, full_text: str, source: str, best: VerificationResult,
) -> VerificationResult:
    claim_value_lower = claim.value.lower()
    full_text_lower = full_text.lower()

    if claim_value_lower not in full_text_lower:
        return best

    idx = full_text_lower.index(claim_value_lower)
    snippet_start = max(0, idx - 80)
    snippet_end = min(len(full_text), idx + len(claim.value) + 80)
    snippet = full_text[snippet_start:snippet_end].strip()

    context_score = _fuzzy_match(claim.text, snippet)
    combined = 0.6 + (context_score * 0.4)

    if combined > best.confidence:
        return VerificationResult(
            claim=claim,
            matched_source=source,
            matched_snippet=snippet,
            confidence=combined,
            verified=True,
        )
    return best


def _find_fuzzy_match(
    claim: Claim, full_text: str, source: str, threshold: float, best: VerificationResult,
) -> VerificationResult:
    sentences = re.split(r"[.!?\n]+", full_text)
    for raw_sentence in sentences:
        sentence = raw_sentence.strip()
        if len(sentence) < _MIN_SENTENCE_LEN:
            continue
        score = _fuzzy_match(claim.text, sentence)
        if score > threshold and score > best.confidence:
            best = VerificationResult(
                claim=claim,
                matched_source=source,
                matched_snippet=sentence[:200],
                confidence=score,
                verified=True,
            )
    return best


def verify_against_sources(
    claims: list[Claim],
    articles: list[dict],
    threshold: float = 0.55,
) -> list[VerificationResult]:
    results: list[VerificationResult] = []

    for claim in claims:
        best = VerificationResult(claim=claim)

        for article in articles:
            title = article.get("title", "")
            content = article.get("content", article.get("text", ""))
            source = article.get("source", article.get("url", "desconocida"))
            full_text = f"{title} {content}"

            if not full_text.strip():
                continue

            best = _find_exact_match(claim, full_text, source, best)
            best = _find_fuzzy_match(claim, full_text, source, threshold, best)

        results.append(best)

    verified_count = sum(1 for r in results if r.verified)
    logger.info(
        "Verificación: %d/%d afirmaciones confirmadas",
        verified_count, len(results),
    )
    return results


def _classify_results(verifications: list[VerificationResult], threshold: float) -> tuple[int, int, int]:
    verified = 0
    contradicted = 0
    unverified = 0

    for result in verifications:
        if result.verified and result.confidence >= threshold:
            verified += 1
        elif result.verified and result.confidence < _CONTRADICTION_THRESHOLD:
            contradicted += 1
        else:
            unverified += 1

    return verified, contradicted, unverified


def grade_reliability(
    analysis_text: str,
    source_articles: list[dict],
    threshold: float = 0.55,
) -> ReliabilityReport:
    claims = extract_claims(analysis_text)
    verifications = verify_against_sources(claims, source_articles, threshold)

    verified, contradicted, unverified = _classify_results(verifications, threshold)

    total = len(verifications)
    if total == 0:
        score = 0.5
    else:
        score = (verified / total) * 0.7 + min(verified / max(total, 1), 1.0) * 0.3
        score = round(min(score, 1.0), 2)

    report = ReliabilityReport(
        score=score,
        total_claims=total,
        verified_claims=verified,
        unverified_claims=unverified,
        contradicted_claims=contradicted,
        details=[
            {
                "claim": r.claim.value,
                "type": r.claim.claim_type,
                "verified": r.verified,
                "confidence": round(r.confidence, 2),
                "source": r.matched_source,
            }
            for r in verifications
        ],
    )

    logger.info(
        "Fiabilidad: %.0f%% (%d verificadas, %d sin verificar, %d contradichas de %d total)",
        score * 100, verified, unverified, contradicted, total,
    )
    return report


def add_source_references(
    analysis_text: str,
    articles: list[dict],
    threshold: float = 0.55,
) -> str:
    claims = extract_claims(analysis_text)
    if not claims:
        logger.info("Sin afirmaciones detectadas — texto sin modificar")
        return analysis_text

    verifications = verify_against_sources(claims, articles, threshold)

    verified_map: dict[int, VerificationResult] = {}
    for result in verifications:
        if result.verified and result.confidence >= threshold:
            verified_map[result.claim.start] = result

    if not verified_map:
        logger.info("Ninguna afirmación verificada — texto sin modificar")
        return analysis_text

    sorted_positions = sorted(verified_map.keys(), reverse=True)
    result_text = analysis_text

    for pos in sorted_positions:
        vr = verified_map[pos]
        end = vr.claim.end
        ref = f" [ref: {vr.matched_source}]"
        result_text = result_text[:end] + ref + result_text[end:]

    references_used = {
        vr.matched_source
        for vr in verified_map.values()
    }
    logger.info("Añadidas %d referencias a %d fuentes", len(verified_map), len(references_used))

    return result_text


CRISIS_TRIGGER_WORDS = {
    "es": [
        "misil", "misiles", "sanciones", "sanción", "elecciones", "despliegue",
        "escasez", "protestas", "conflicto", "guerra", "ataque", "invasión",
        "movilización", "ejército", "armada", "nuclear", "explosión",
        "derrumbe", "crisis", "emergencia", "desastre", "pandemia",
        "negociaciones", "tratado", "acuerdo", "alianza", "embargo",
        "aranceles", "inflación", "recesión", "default", "quiebra",
        "golpe", "levantamiento", "revuelta", "huelga", "manifestación",
        "ciberataque", "espionaje", "contrainteligencia", "radicalización",
        "violencia", "genocidio", "crímenes", "tribunal", "investigación",
        "dimisión", "destitución", "impeachment", "fraude", "corrupción",
        "refugiados", "desplazados", "hambruna", "sequía", "inundación",
    ],
    "en": [
        "missile", "sanctions", "election", "deployment", "shortage",
        "protests", "conflict", "war", "attack", "invasion", "mobilization",
        "military", "navy", "nuclear", "explosion", "collapse", "crisis",
        "emergency", "disaster", "pandemic", "negotiations", "treaty",
        "agreement", "alliance", "embargo", "tariffs", "inflation",
        "recession", "default", "bankruptcy", "coup", "uprising", "revolt",
        "strike", "cyberattack", "espionage", "counterintelligence",
        "violence", "genocide", "crimes", "tribunal", "investigation",
        "resignation", "impeachment", "fraud", "corruption", "refugees",
        "displaced", "famine", "drought", "flood",
    ],
}


def score_article_relevance(article_text: str, country_name: str = "") -> float:
    text_lower = article_text.lower()
    score = 0.0

    for lang_words in CRISIS_TRIGGER_WORDS.values():
        for word in lang_words:
            if word in text_lower:
                score += 1.0

    country_words = country_name.lower().split()
    for cw in country_words:
        if len(cw) > 3 and cw in text_lower:
            score += 2.0

    text_len = len(text_lower)
    if text_len > 0:
        density = score / max(text_len, 1) * 1000
        return min(density * 10, 100.0)
    return 0.0


def rank_articles(articles: list[dict], country_name: str = "", top_n: int = 15) -> list[dict]:
    scored = []
    for a in articles:
        text = f"{a.get('title', '')} {a.get('summary', '')} {a.get('content', '')}"
        relevance = score_article_relevance(text, country_name)
        reliability_bonus = 0
        rel = a.get("reliability", "B")
        if rel == "A":
            reliability_bonus = 20
        elif rel == "B":
            reliability_bonus = 10
        scored.append((relevance + reliability_bonus, a))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:top_n]]
