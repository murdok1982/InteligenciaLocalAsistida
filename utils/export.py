"""Export structured JSON report with actors, risk scores, coordinates."""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def export_structured_report(
    country_sections: list[dict],
    report_path: str,
    classification: str = "ABIERTO",
    llm_provider: str = "ollama",
    llm_model: str = "",
) -> str:
    countries_data = []
    for section in country_sections:
        name = section.get("name", "")
        region = section.get("region", "")
        analysis_text = section.get("section_es", "")

        risk_score = _extract_risk_score(analysis_text)
        actors = _extract_actors(analysis_text)
        coordinates = _extract_coordinates(analysis_text)

        countries_data.append({
            "country": name,
            "region": region,
            "risk_score": risk_score,
            "risk_category": _risk_category(risk_score),
            "actors_identified": actors,
            "coordinates": coordinates,
            "analysis_summary": analysis_text[:500],
        })

    report = {
        "metadata": {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "classification": classification,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "total_countries": len(countries_data),
            "format_version": "1.0",
        },
        "countries": countries_data,
        "global_risk_assessment": {
            "average_risk": sum(c["risk_score"] for c in countries_data) / max(len(countries_data), 1),
            "highest_risk_country": max(countries_data, key=lambda c: c["risk_score"])["country"] if countries_data else "",
        },
    }

    json_path = report_path.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("Reporte estructurado exportado: %s", json_path)
    return json_path


def _extract_risk_score(text: str) -> int:
    import re
    patterns = [
        r"(?:riesgo|risk)[\s:]*(\d+)(?:/10|[\s]*puntos)?",
        r"(?:nivel|level)[\s:]*(\d+)",
        r"puntuaci[óo]n[\s:]*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                score = int(m.group(1))
                return max(1, min(10, score))
            except ValueError:
                pass
    return 5


def _extract_actors(text: str) -> list[str]:
    import re
    actors = set()
    org_patterns = [
        r"\b(?:OTAN|NATO|UE|EU|ONU|UN|FMI|IMF|BM|OMS|Rusia|Rusia|China|EE\.UU\.|USA|Iran|Irán|Israel|Ucrania|Taiwán|Corea del Norte|North Korea)\b",
    ]
    for pat in org_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            actors.add(m.group(0))
    return sorted(actors)


def _extract_coordinates(text: str) -> list[dict]:
    import re
    coords = []
    pat = re.compile(r"(\-?\d+\.?\d*)\s*[,°]\s*(\-?\d+\.?\d*)")
    for m in pat.finditer(text):
        try:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                coords.append({"lat": lat, "lng": lng})
        except ValueError:
            pass
    return coords


def _risk_category(score: int) -> str:
    if score >= 8:
        return "CRITICO"
    if score >= 6:
        return "ALTO"
    if score >= 4:
        return "MODERADO"
    return "BAJO"
