"""
InteligenciaGeopolitica — weekly geopolitical intelligence report generator.
Runs fully locally with Ollama (gemma4:4b); falls back to OpenAI if configured.
"""
import json
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from dotenv import dotenv_values, load_dotenv
from jinja2 import Template
from tqdm import tqdm

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    os.environ.update(dotenv_values(_env_path))
load_dotenv(dotenv_path=_env_path, override=True)

from utils.io import ensure_dir, load_config, save_text, ts_stamp
from utils.llm import LLM_PROVIDER, OLLAMA_MODEL, ask_model
from utils.regions import region_for
from utils.factcheck import grade_reliability
from utils.database import init_db, cache_articles, get_cached_articles, save_report
from providers.gdelt_provider import search_gdelt
from providers.newsapi_provider import search_newsapi
from providers.rss_provider import search_rss
from providers.youtube_provider import search_youtube

logger = logging.getLogger("inteligencia_geopolitica")

CATEGORIES = [
    ("economía", "economy"),
    ("seguridad", "security"),
    ("defensa", "defense"),
    ("inteligencia", "intelligence"),
]


def _setup_logging() -> None:
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def read_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def render(tpl_str: str, **kwargs) -> str:
    return Template(tpl_str).render(**kwargs)


def collect_articles(
    country_name: str,
    days_back: int,
    per_country_limit: int,
    use_gdelt: bool,
    use_newsapi: bool,
    use_rss: bool,
    use_youtube: bool,
) -> list:
    cached = get_cached_articles(country=country_name, max_age_hours=2)
    if len(cached) >= per_country_limit:
        logger.info("Cache SQLite hit para %s (%d artículos)", country_name, len(cached))
        return [dict(a) for a in cached][:per_country_limit]

    pool = []
    per_cat = max(2, math.ceil(per_country_limit / len(CATEGORIES)))

    for cat_es, cat_en in CATEGORIES:
        if use_gdelt:
            try:
                pool += search_gdelt(country_name, cat_es, days_back=days_back, limit=per_cat)
            except Exception as exc:
                logger.error("Error en GDELT para %s/%s: %s", country_name, cat_es, exc)
        if use_newsapi:
            try:
                pool += search_newsapi(country_name, cat_es, days_back=days_back, limit=per_cat, language="en")
            except Exception as exc:
                logger.error("Error en NewsAPI para %s/%s: %s", country_name, cat_es, exc)
        if use_rss:
            try:
                pool += search_rss(country_name, cat_es, days_back=days_back, limit=per_cat)
            except Exception as exc:
                logger.error("Error en RSS para %s/%s: %s", country_name, cat_es, exc)
        if use_youtube:
            try:
                pool += search_youtube(country_name, cat_es, limit=max(2, per_cat // 2))
            except Exception as exc:
                logger.error("Error en YouTube para %s/%s: %s", country_name, cat_es, exc)

    seen: set = set()
    deduped = []
    for a in pool:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(a)
    result = deduped[:per_country_limit]

    cache_articles(result, ttl_hours=2)
    return result


def build_country_section(name: str, region: str, analysis: str, forecast: str, reliability_score: float = None) -> str:
    section = (
        f"\n## País: {name}\n"
        f"**Región:** {region}\n\n"
        f"### Análisis\n{analysis}\n\n"
        f"### Previsión (6m / 1a / 3a)\n{forecast}\n"
    )
    if reliability_score is not None:
        porcentaje = int(reliability_score * 100)
        section += f"\n**Fiabilidad del análisis:** {porcentaje}%\n"
    return section


def format_bullets(articles: list) -> str:
    lines = []
    for a in articles:
        reliability = a.get("reliability", "")
        tag = f" [{reliability}]" if reliability else ""
        source = a.get("source", "")
        lines.append(f"- {a['title']} ({source}){tag} — {a['url']}")
    return "\n".join(lines) if lines else "(Sin fuentes disponibles para este período)"


def _analyze_country(
    country_cfg: dict,
    days_back: int,
    per_country_limit: int,
    use_gdelt: bool,
    use_newsapi: bool,
    use_rss: bool,
    use_youtube: bool,
    analysis_tpl: str,
    forecast_tpl: str,
    progress_lock: Lock,
    progress_bar: tqdm,
    progress_callback=None,
) -> dict:
    name, code = country_cfg["name"], country_cfg["code"]
    region = region_for(code)
    logger.info("Analizando país: %s (%s)", name, region)

    if progress_callback:
        progress_callback({"type": "country_start", "country": name, "region": region, "message": f"Analizando {name}"})

    try:
        articles = collect_articles(
            name, days_back, per_country_limit,
            use_gdelt, use_newsapi, use_rss, use_youtube,
        )
    except Exception as exc:
        logger.error("Fallo recolectando artículos para %s: %s", name, exc)
        articles = []

    bullets = format_bullets(articles)
    logger.info("%s: %d artículos recolectados", name, len(articles))

    try:
        analysis_prompt = render(
            analysis_tpl,
            country=name,
            region=region,
            days_back=days_back,
            reliability="Mixta (ver fuentes)",
        ) + f"\n\nContexto — titulares recientes:\n{bullets}"
        analysis_text = ask_model(analysis_prompt, temperature=0.3)
    except Exception as exc:
        logger.error("Error en análisis LLM para %s: %s", name, exc)
        analysis_text = f"(Error generando análisis para {name}: {exc})"

    try:
        forecast_prompt = render(forecast_tpl, country=name)
        forecast_text = ask_model(
            forecast_prompt + f"\n\nContexto de análisis previo:\n{analysis_text}",
            temperature=0.4,
        )
    except Exception as exc:
        logger.error("Error en forecast LLM para %s: %s", name, exc)
        forecast_text = f"(Error generando previsión para {name}: {exc})"

    reliability_score = None
    try:
        report = grade_reliability(analysis_text, articles)
        reliability_score = report.score
        logger.info("Fiabilidad de análisis para %s: %.0f%%", name, reliability_score * 100)
    except Exception as exc:
        logger.warning("Error evaluando fiabilidad para %s: %s", name, exc)

    section_es = build_country_section(name, region, analysis_text, forecast_text, reliability_score)

    try:
        section_en = ask_model(
            "Translate the following Spanish intelligence analysis into clear, professional English Markdown. "
            "Preserve all section headers, bullets and structure:\n\n" + section_es,
            temperature=0.2,
        )
    except Exception as exc:
        logger.error("Error en traducción LLM para %s: %s", name, exc)
        section_en = f"(Translation error for {name}: {exc})"

    logger.info("País completado: %s", name)

    if progress_callback:
        progress_callback({"type": "country_done", "country": name, "region": region, "reliability": reliability_score, "message": f"{name} completado"})

    with progress_lock:
        progress_bar.update(1)

    return {
        "name": name,
        "region": region,
        "section_es": section_es,
        "section_en": section_en,
    }


def main(progress_callback=None) -> None:
    _setup_logging()
    init_db()

    cfg = load_config("config.yaml")
    days_back = cfg["run"]["days_back"]
    per_country_limit = cfg["run"]["per_country_limit"]
    providers = cfg["run"]["providers"]
    output_dir = cfg["report"]["output_dir"]
    classification = cfg["report"].get("classification", "ABIERTO")

    ensure_dir(output_dir)

    use_gdelt = "gdelt" in providers
    use_newsapi = "newsapi" in providers
    use_rss = "rss" in providers
    use_youtube = "youtube" in providers

    if not any([use_gdelt, use_newsapi, use_rss, use_youtube]):
        logger.critical("No hay proveedores de noticias activos en config.yaml")
        sys.exit(1)

    if LLM_PROVIDER == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key or not openai_key.startswith("sk-"):
            logger.critical("LLM_PROVIDER=openai pero OPENAI_API_KEY no está configurada. Edita .env o cambia LLM_PROVIDER=ollama")
            sys.exit(1)

    llm_model_label = (
        OLLAMA_MODEL if LLM_PROVIDER == "ollama"
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )

    logger.info("Proveedor LLM: %s | Modelo: %s", LLM_PROVIDER.upper(), llm_model_label)
    logger.info("Fuentes activas: %s", ", ".join(providers))
    logger.info("Países a analizar: %d", len(cfg["countries"]))
    logger.info("Período: últimos %d días", days_back)

    analysis_tpl = read_prompt("prompts/analysis_es.txt")
    forecast_tpl = read_prompt("prompts/forecast_es.txt")
    synthesis_tpl = read_prompt("prompts/synthesis_es.txt")
    report_tpl = read_prompt("prompts/report_bilingual.txt")

    country_sections_es: list[str] = []
    country_sections_en: list[str] = []
    region_blobs_es: dict[str, list[str]] = {}

    max_workers = min(4, len(cfg["countries"]))
    logger.info("Iniciando análisis paralelo de países (max_workers=%d)", max_workers)

    progress_lock = Lock()
    progress_bar = tqdm(total=len(cfg["countries"]), desc="Países")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_country = {
            executor.submit(
                _analyze_country,
                c, days_back, per_country_limit,
                use_gdelt, use_newsapi, use_rss, use_youtube,
                analysis_tpl, forecast_tpl,
                progress_lock, progress_bar,
                progress_callback,
            ): c
            for c in cfg["countries"]
        }
        for future in as_completed(future_to_country):
            country_cfg = future_to_country[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                logger.error("Fallo inesperado analizando %s: %s", country_cfg["name"], exc)

    progress_bar.close()

    country_order = {c["name"]: i for i, c in enumerate(cfg["countries"])}
    results.sort(key=lambda r: country_order.get(r["name"], 999))

    for r in results:
        country_sections_es.append(r["section_es"])
        country_sections_en.append(r["section_en"])
        region_blobs_es.setdefault(r["region"], []).append(r["section_es"])

    logger.info("Análisis de países completado. Iniciando síntesis regional...")

    regional_parts_es = []
    for region, blobs in region_blobs_es.items():
        joined = "\n\n".join(blobs[:8])
        try:
            syn_es = ask_model(
                synthesis_tpl + f"\n\nAnálisis de países en {region}:\n{joined}",
                temperature=0.3,
            )
            regional_parts_es.append(f"### {region}\n{syn_es}")
        except Exception as exc:
            logger.error("Error en síntesis regional para %s: %s", region, exc)
            regional_parts_es.append(f"### {region}\n(Error generando síntesis: {exc})")

    regional_synthesis_es = "\n\n".join(regional_parts_es)

    try:
        regional_synthesis_en = ask_model(
            "Translate and tighten to professional English Markdown:\n\n" + regional_synthesis_es,
            temperature=0.2,
        )
    except Exception as exc:
        logger.error("Error traduciendo síntesis regional: %s", exc)
        regional_synthesis_en = f"(Translation error: {exc})"

    try:
        global_overview_es = ask_model(
            "Elabora un panorama estratégico global en español a partir de estas síntesis regionales:\n\n"
            + regional_synthesis_es,
            temperature=0.4,
        )
    except Exception as exc:
        logger.error("Error en panorama global ES: %s", exc)
        global_overview_es = f"(Error generando panorama global: {exc})"

    try:
        global_overview_en = ask_model(
            "Write a concise global strategic overview in English based on these regional syntheses:\n\n"
            + regional_synthesis_en,
            temperature=0.4,
        )
    except Exception as exc:
        logger.error("Error en panorama global EN: %s", exc)
        global_overview_en = f"(Error generating global overview: {exc})"

    try:
        exec_summary_es = ask_model(
            "Resume en 10-14 líneas el panorama global en español. "
            "Incluye viñetas de riesgos y oportunidades estratégicas:\n\n" + global_overview_es,
            temperature=0.3,
        )
    except Exception as exc:
        logger.error("Error en resumen ejecutivo ES: %s", exc)
        exec_summary_es = f"(Error generando resumen ejecutivo: {exc})"

    try:
        exec_summary_en = ask_model(
            "Summarize in 10-14 lines the global outlook in English. "
            "Include bullets for strategic risks and opportunities:\n\n" + global_overview_en,
            temperature=0.3,
        )
    except Exception as exc:
        logger.error("Error en resumen ejecutivo EN: %s", exc)
        exec_summary_en = f"(Error generating executive summary: {exc})"

    report_md = Template(report_tpl).render(
        classification=classification,
        days_back=days_back,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        llm_provider=LLM_PROVIDER,
        llm_model=llm_model_label,
        executive_summary_es=exec_summary_es,
        regional_synthesis_es=regional_synthesis_es,
        country_sections_es="\n\n".join(country_sections_es),
        global_overview_es=global_overview_es,
        executive_summary_en=exec_summary_en,
        regional_synthesis_en=regional_synthesis_en,
        country_sections_en="\n\n".join(country_sections_en),
        global_overview_en=global_overview_en,
    )

    fname = f"{cfg['report']['filename_prefix']}_{ts_stamp()}.md"
    out_path = os.path.join(output_dir, fname)
    save_text(out_path, report_md)
    logger.info("Reporte generado: %s", out_path)

    country_names = [c["name"] for c in cfg["countries"]]
    file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    save_report(
        filepath=out_path,
        filename=fname,
        countries=country_names,
        classification=classification,
        file_size=file_size,
    )


if __name__ == "__main__":
    main()
