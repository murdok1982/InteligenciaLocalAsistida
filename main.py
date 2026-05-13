"""
InteligenciaGeopolitica — weekly geopolitical intelligence report generator.
Runs fully locally with Ollama (gemma4:4b); falls back to OpenAI if configured.
"""
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from jinja2 import Template
from tqdm import tqdm

# --- Force .env load BEFORE any local module import ---
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    os.environ.update(dotenv_values(_env_path))
load_dotenv(dotenv_path=_env_path, override=True)

from utils.io import ensure_dir, load_config, save_text, ts_stamp
from utils.llm import LLM_PROVIDER, OLLAMA_MODEL, ask_model
from utils.regions import region_for
from providers.gdelt_provider import search_gdelt
from providers.newsapi_provider import search_newsapi
from providers.rss_provider import search_rss
from providers.youtube_provider import search_youtube

CATEGORIES = [
    ("economía", "economy"),
    ("seguridad", "security"),
    ("defensa", "defense"),
    ("inteligencia", "intelligence"),
]


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
    pool = []
    per_cat = max(2, math.ceil(per_country_limit / len(CATEGORIES)))

    for cat_es, cat_en in CATEGORIES:
        if use_gdelt:
            pool += search_gdelt(country_name, cat_es, days_back=days_back, limit=per_cat)
        if use_newsapi:
            pool += search_newsapi(country_name, cat_es, days_back=days_back, limit=per_cat, language="en")
        if use_rss:
            pool += search_rss(country_name, cat_es, days_back=days_back, limit=per_cat)
        if use_youtube:
            pool += search_youtube(country_name, cat_es, limit=max(2, per_cat // 2))

    seen: set = set()
    deduped = []
    for a in pool:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(a)
    return deduped[:per_country_limit]


def build_country_section(name: str, region: str, analysis: str, forecast: str) -> str:
    return (
        f"\n## País: {name}\n"
        f"**Región:** {region}\n\n"
        f"### Análisis\n{analysis}\n\n"
        f"### Previsión (6m / 1a / 3a)\n{forecast}\n"
    )


def format_bullets(articles: list) -> str:
    lines = []
    for a in articles:
        reliability = a.get("reliability", "")
        tag = f" [{reliability}]" if reliability else ""
        source = a.get("source", "")
        lines.append(f"- {a['title']} ({source}){tag} — {a['url']}")
    return "\n".join(lines) if lines else "(Sin fuentes disponibles para este período)"


def main() -> None:
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

    # Validate at least one provider is active
    if not any([use_gdelt, use_newsapi, use_rss, use_youtube]):
        print("⚠️  No hay proveedores de noticias activos en config.yaml")
        sys.exit(1)

    # LLM readiness check
    if LLM_PROVIDER == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key or not openai_key.startswith("sk-"):
            print("⚠️  LLM_PROVIDER=openai pero OPENAI_API_KEY no está configurada.")
            print("   Edita .env o cambia LLM_PROVIDER=ollama en .env")
            sys.exit(1)

    print(f"🔧 Proveedor LLM: {LLM_PROVIDER.upper()} | Modelo: {OLLAMA_MODEL if LLM_PROVIDER == 'ollama' else os.getenv('OPENAI_MODEL','gpt-4o-mini')}")
    print(f"📰 Fuentes activas: {', '.join(p for p in providers)}")
    print(f"🌍 Países a analizar: {len(cfg['countries'])}")
    print(f"📅 Período: últimos {days_back} días\n")

    analysis_tpl = read_prompt("prompts/analysis_es.txt")
    forecast_tpl = read_prompt("prompts/forecast_es.txt")
    synthesis_tpl = read_prompt("prompts/synthesis_es.txt")
    report_tpl = read_prompt("prompts/report_bilingual.txt")

    country_sections_es, country_sections_en = [], []
    region_blobs_es: dict = {}

    print("🔎 Recolectando y analizando países...")
    for c in tqdm(cfg["countries"]):
        name, code = c["name"], c["code"]
        region = region_for(code)

        articles = collect_articles(
            name, days_back, per_country_limit,
            use_gdelt, use_newsapi, use_rss, use_youtube,
        )
        bullets = format_bullets(articles)

        analysis_prompt = render(
            analysis_tpl,
            country=name,
            region=region,
            days_back=days_back,
            reliability="Mixta (ver fuentes)",
        ) + f"\n\nContexto — titulares recientes:\n{bullets}"

        analysis_text = ask_model(analysis_prompt, temperature=0.3)

        forecast_prompt = render(forecast_tpl, country=name)
        forecast_text = ask_model(
            forecast_prompt + f"\n\nContexto de análisis previo:\n{analysis_text}",
            temperature=0.4,
        )

        section_es = build_country_section(name, region, analysis_text, forecast_text)
        section_en = ask_model(
            "Translate the following Spanish intelligence analysis into clear, professional English Markdown. "
            "Preserve all section headers, bullets and structure:\n\n" + section_es,
            temperature=0.2,
        )

        country_sections_es.append(section_es)
        country_sections_en.append(section_en)
        region_blobs_es.setdefault(region, []).append(section_es)

    # Regional synthesis
    regional_parts_es = []
    for region, blobs in region_blobs_es.items():
        joined = "\n\n".join(blobs[:8])
        syn_es = ask_model(
            synthesis_tpl + f"\n\nAnálisis de países en {region}:\n{joined}",
            temperature=0.3,
        )
        regional_parts_es.append(f"### {region}\n{syn_es}")

    regional_synthesis_es = "\n\n".join(regional_parts_es)
    regional_synthesis_en = ask_model(
        "Translate and tighten to professional English Markdown:\n\n" + regional_synthesis_es,
        temperature=0.2,
    )

    global_overview_es = ask_model(
        "Elabora un panorama estratégico global en español a partir de estas síntesis regionales:\n\n"
        + regional_synthesis_es,
        temperature=0.4,
    )
    global_overview_en = ask_model(
        "Write a concise global strategic overview in English based on these regional syntheses:\n\n"
        + regional_synthesis_en,
        temperature=0.4,
    )

    exec_summary_es = ask_model(
        "Resume en 10-14 líneas el panorama global en español. "
        "Incluye viñetas de riesgos y oportunidades estratégicas:\n\n" + global_overview_es,
        temperature=0.3,
    )
    exec_summary_en = ask_model(
        "Summarize in 10-14 lines the global outlook in English. "
        "Include bullets for strategic risks and opportunities:\n\n" + global_overview_en,
        temperature=0.3,
    )

    llm_model_label = (
        OLLAMA_MODEL if LLM_PROVIDER == "ollama"
        else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )

    report_md = Template(report_tpl).render(
        classification=classification,
        days_back=days_back,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
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
    print(f"\n✅ Reporte generado: {out_path}")


if __name__ == "__main__":
    main()
