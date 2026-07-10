"""
InteligenciaGeopolitica — weekly geopolitical intelligence report generator.
Runs fully locally with Ollama (gemma4:4b); falls back to OpenAI if configured.
"""
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from threading import Lock

from dotenv import dotenv_values, load_dotenv
from jinja2 import Template
from tqdm import tqdm

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    os.environ.update(dotenv_values(_env_path))
load_dotenv(dotenv_path=_env_path, override=True)

from providers.gdelt_provider import search_gdelt
from providers.newsapi_provider import search_newsapi
from providers.rss_provider import search_rss
from providers.youtube_provider import search_youtube
from utils.database import cache_articles, get_cached_articles, init_db, save_report
from utils.factcheck import grade_reliability
from utils.io import ensure_dir, load_config, save_text, ts_stamp
from utils.llm import LLM_PROVIDER, OLLAMA_MODEL, ask_model
from utils.regions import region_for

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


_ROOT = Path(__file__).resolve().parent


def read_prompt(path: str | PathLike) -> str:
    abs_path = path if Path(path).is_absolute() else _ROOT / path
    with open(abs_path, "r", encoding="utf-8") as f:
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
    import yaml
    cfg_air = None
    try:
        cfg_path = _ROOT / "config.yaml"
        with open(cfg_path) as f:
            cfg_air = yaml.safe_load(f)
        air_gapped = cfg_air.get("air_gapped", {}).get("enabled", False)
    except Exception:
        air_gapped = False

    if air_gapped:
        logger.info("MODO AIR-GAPPED activado — solo fuentes locales")
        local_articles = []
        import_dir = (cfg_air.get("air_gapped", {}).get("data_import_dir", "imports")
                      if cfg_air else "imports")
        import_path = _ROOT / import_dir
        if import_path.exists():
            for fpath in import_path.glob("*.*"):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                    local_articles.append({
                        "title": fpath.stem,
                        "url": fpath.name,
                        "source": "local_import",
                        "date": datetime.fromtimestamp(fpath.stat().st_mtime).isoformat(),
                        "summary": text[:500],
                        "content": text,
                        "provider": "local",
                        "reliability": "B",
                    })
                except Exception:
                    continue
        logger.info("Air-gapped: %d articulos locales cargados", len(local_articles))
        cache_articles(local_articles, ttl_hours=48)
        return local_articles[:per_country_limit]

    pool = []
    cat_es = ""
    use_social = True
    social_providers = ["telegram", "reddit"]
    try:
        from social_monitor.collector import collect_all_social
        social_limit = max(2, math.ceil(per_country_limit / 3))
        social_pool = collect_all_social(
            country_name=country_name,
            category=cat_es,
            limit=social_limit,
            providers=social_providers,
        )
        pool += social_pool
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Social collector error: %s", exc)

    cached = get_cached_articles(country=country_name, max_age_hours=2)
    if len(cached) >= per_country_limit:
        logger.info("Cache SQLite hit para %s (%d artículos)", country_name, len(cached))
        return [dict(a) for a in cached][:per_country_limit]

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

    try:
        from utils.factcheck import rank_articles
        articles = rank_articles(articles, country_name=name, top_n=15)
        logger.info("%s: rankeados a %d artículos por relevancia", name, len(articles))
    except Exception as exc:
        logger.debug("Ranker no disponible: %s", exc)

    try:
        from utils.database import get_cached_articles
        all_articles_for_country = get_cached_articles(country=name, max_age_hours=48)
        from collections import Counter
        cat_counter = Counter()
        for a in all_articles_for_country:
            cat = a.get("category", "") or ""
            if cat:
                cat_counter[cat] += 1
        total_with_cat = sum(cat_counter.values()) or 1

        top_cats = cat_counter.most_common(3)
        if top_cats:
            focus_instruction = []
            reduce_instruction = []
            used = set()
            for cat, count in top_cats:
                pct = count / total_with_cat * 100
                if pct > 25:
                    focus_instruction.append(f"ENFOCATE en {cat} ({pct:.0f}% de las noticias)")
                    used.add(cat)
                elif pct > 10:
                    focus_instruction.append(f"Prioriza {cat} ({pct:.0f}% de las noticias)")
                    used.add(cat)

            all_cats = ["economía", "seguridad", "defensa", "inteligencia"]
            for cat in all_cats:
                if cat not in used:
                    reduce_instruction.append(f"reduce {cat} al mínimo crítico")

            dynamic_instruction = ". ".join(focus_instruction)
            if reduce_instruction:
                dynamic_instruction += ". " + ", ".join(reduce_instruction)

            analysis_tpl = analysis_tpl.replace(
                "{{dynamic_focus}}",
                f"\nInstrucción de enfoque dinámico: {dynamic_instruction}\n"
            )
            logger.info("%s: prompt dinamizado: %s", name, dynamic_instruction)
    except Exception as exc:
        logger.debug("Dynamic prompt no disponible: %s", exc)
        analysis_tpl = analysis_tpl.replace("{{dynamic_focus}}", "")

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

    contradiction_matrix = ""
    try:
        contradiction_prompt = read_prompt(_ROOT / "prompts" / "contradiction_es.txt")
        contradiction_prompt = Template(contradiction_prompt).render(country=name)

        _STATE_MEDIA_KEYWORDS = ["tass", "rt.com", "xinhua", "presstv", "cgtn", "sputnik", "fars", "irna", "kremlin", "gov.cn"]
        western_articles = [a for a in articles if not any(kw in (a.get("source", "") + a.get("url", "")).lower() for kw in _STATE_MEDIA_KEYWORDS)]
        state_articles = [a for a in articles if any(kw in (a.get("source", "") + a.get("url", "")).lower() for kw in _STATE_MEDIA_KEYWORDS)]

        context_parts = []
        if western_articles:
            context_parts.append("OCCIDENTE:\n" + format_bullets(western_articles[:5]))
        if state_articles:
            context_parts.append("BLOQUE ADVERSARIO:\n" + format_bullets(state_articles[:5]))

        if context_parts:
            contradiction_matrix = ask_model(
                contradiction_prompt + "\n\n" + "\n\n".join(context_parts),
                temperature=0.3,
            )
    except Exception as exc:
        logger.warning("Matriz de contradicciones no disponible para %s: %s", name, exc)

    reliability_score = None
    try:
        report = grade_reliability(analysis_text, articles)
        reliability_score = report.score
        logger.info("Fiabilidad de análisis para %s: %.0f%%", name, reliability_score * 100)
    except Exception as exc:
        logger.warning("Error evaluando fiabilidad para %s: %s", name, exc)

    contradiction_section = ""
    if contradiction_matrix:
        contradiction_section = f"\n\n### Matriz de Contradicciones\n{contradiction_matrix}\n"
    section_es = build_country_section(name, region, analysis_text + contradiction_section, forecast_text, reliability_score)

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
        "source_articles": articles,
    }


def main(progress_callback=None, countries: list[str] = None, days_back: int = None, classification: str = None) -> None:
    _setup_logging()
    init_db()

    cfg = load_config(str(_ROOT / "config.yaml"))
    if days_back is not None:
        cfg["run"]["days_back"] = days_back
    if classification is not None:
        cfg["report"]["classification"] = classification
    if countries is not None:
        cfg["countries"] = [c for c in cfg["countries"] if c["name"] in countries]
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

    prompt_dir = _ROOT / "prompts"
    analysis_tpl = read_prompt(prompt_dir / "analysis_es.txt")
    forecast_tpl = read_prompt(prompt_dir / "forecast_es.txt")
    synthesis_tpl = read_prompt(prompt_dir / "synthesis_es.txt")
    report_tpl = read_prompt(prompt_dir / "report_bilingual.txt")

    country_sections_es: list[str] = []
    country_sections_en: list[str] = []
    region_blobs_es: dict[str, list[str]] = {}
    articles_used_for_citation: list[dict] = []

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
        articles_used_for_citation.extend(r.get("source_articles", []))

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

    try:
        citation_lines = ["\n\n---\n## INDICE DE FUENTES\n"]
        for i, a in enumerate(articles_used_for_citation or [], 1):
            citation_lines.append(f"{i}. [{a.get('title', 'Sin titulo')}]({a.get('url', '#')}) — {a.get('source', '')}")
        if citation_lines:
            report_md += "\n".join(citation_lines)
    except Exception:
        pass

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

    try:
        from utils.export import export_structured_report
        json_path = export_structured_report(
            results,
            out_path,
            classification=classification,
            llm_provider=LLM_PROVIDER,
            llm_model=llm_model_label,
        )
        logger.info("Reporte estructurado: %s", json_path)
    except Exception as exc:
        logger.warning("Error exportando JSON estructurado: %s", exc)


if __name__ == "__main__":
    main()
