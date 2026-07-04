import logging
import re

logger = logging.getLogger(__name__)

_POSITIVE_WORDS = {
    "acuerdo", "paz", "tregua", "diálogo", "cooperación", "alianza",
    "estabilidad", "progreso", "desarrollo", "crecimiento", "mejora",
    "éxito", "victoria", "avance", "reforma", "libertad", "democracia",
    "derechos", "justicia", "reconciliación", "alto el fuego",
}

_NEGATIVE_WORDS = {
    "guerra", "conflicto", "ataque", "misil", "bomba", "explosión",
    "muerte", "muerto", "herido", "destrucción", "crisis", "pánico",
    "amenaza", "peligro", "riesgo", "terror", "terrorista", "genocidio",
    "violencia", "sangre", "masacre", "invasión", "ocupación",
    "sanciones", "embargo", "bloqueo", "represión", "dictadura",
    "corrupción", "fraude", "colapso", "recesión", "hambruna",
}

_NEUTRAL_WORDS = {
    "informe", "reporte", "análisis", "evaluación", "declaración",
    "reunión", "conferencia", "comunicado", "nota", "documento",
}

_INTENSIFIERS = {"muy", "altamente", "extremadamente", "grave", "crítico",
                 "masivo", "máximo", "total", "completo", "absoluto"}


def analyze_sentiment(text: str) -> dict:
    text_lower = text.lower()
    words = set(re.findall(r'\w+', text_lower))

    positive = words & _POSITIVE_WORDS
    negative = words & _NEGATIVE_WORDS
    neutral = words & _NEUTRAL_WORDS
    intensifiers = words & _INTENSIFIERS

    pos_score = len(positive) + len(intensifiers & positive) * 0.5
    neg_score = len(negative) + len(intensifiers & negative) * 0.5
    total = pos_score + neg_score + len(neutral)

    if total == 0:
        return {"sentiment": "neutral", "score": 0.0, "positive": 0, "negative": 0, "intensity": 0.0}

    score = (pos_score - neg_score) / total
    intensity = (pos_score + neg_score) / total if total > 0 else 0

    if score > 0.2:
        sentiment = "positive"
    elif score < -0.2:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "score": round(score, 3),
        "positive_words": list(positive),
        "negative_words": list(negative),
        "intensity": round(min(intensity, 1.0), 3),
    }


def classify_tone(text: str) -> str:
    sentiment = analyze_sentiment(text)
    score = sentiment["score"]
    intensity = sentiment["intensity"]

    if intensity < 0.1:
        return "objetivo"
    if score > 0.5:
        return "entusiasta"
    if score > 0.2:
        return "favorable"
    if score < -0.5:
        return "alarmista"
    if score < -0.2:
        return "critico"
    return "informativo"
