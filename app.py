import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)

from utils.llm import LLM_PROVIDER, OLLAMA_MODEL, ask_model, ask_model_stream, set_model, set_provider, get_ollama_tags
from utils.database import (
    init_db, save_analysis, get_history, get_analysis, delete_analysis,
    save_report, get_reports as db_get_reports, save_schedule, get_schedules,
    delete_schedule, cache_articles, get_stats,
)

WEB_ROOT = ROOT / "web"
API_TOKEN = os.getenv("API_TOKEN", secrets.token_urlsafe(32))
MAX_BODY_SIZE = 1024 * 50

_rate_lock = threading.Lock()
_rate_requests: dict = {}
_RATE_LIMIT = 30
_RATE_WINDOW = 60

_schedules: dict = {}
_schedules_lock = threading.Lock()

_pipeline_state = {
    "running": False,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "thread": None,
}
_pipeline_lock = threading.Lock()

_server_port = 8765

_pipeline_events: list = []
_pipeline_events_lock = threading.Lock()


def _check_rate(client_ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        timestamps = _rate_requests.get(client_ip, [])
        timestamps = [t for t in timestamps if now - t < _RATE_WINDOW]
        if len(timestamps) >= _RATE_LIMIT:
            _rate_requests[client_ip] = timestamps
            return False
        timestamps.append(now)
        _rate_requests[client_ip] = timestamps
        return True


def _emit_pipeline_event(event: dict) -> None:
    with _pipeline_events_lock:
        _pipeline_events.append(event)


def _run_pipeline_background():
    try:
        with _pipeline_lock:
            _pipeline_state["status"] = "running"
            _pipeline_state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _pipeline_state["error"] = None

        _emit_pipeline_event({"type": "start", "message": "Pipeline iniciado"})

        from main import main as pipeline_main
        pipeline_main(progress_callback=_emit_pipeline_event)

        _emit_pipeline_event({"type": "complete", "message": "Pipeline completado"})

        with _pipeline_lock:
            _pipeline_state["status"] = "completed"
            _pipeline_state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception as exc:
        _emit_pipeline_event({"type": "error", "message": str(exc)})
        with _pipeline_lock:
            _pipeline_state["status"] = "failed"
            _pipeline_state["error"] = str(exc)
            _pipeline_state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    finally:
        with _pipeline_lock:
            _pipeline_state["running"] = False


class AppHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str):
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, generator):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        try:
            for token in generator:
                event = f"data: {json.dumps({'token': token})}\n\n"
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()
            done_event = f"data: {json.dumps({'done': True})}\n\n"
            self.wfile.write(done_event.encode("utf-8"))
            self.wfile.flush()
        except Exception as exc:
            err_event = f"data: {json.dumps({'error': str(exc)})}\n\n"
            self.wfile.write(err_event.encode("utf-8"))
            self.wfile.flush()

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if secrets.compare_digest(token, API_TOKEN):
                return True
        origin = self.headers.get("Origin", "")
        if origin in ("null", f"http://127.0.0.1:{_server_port}", f"http://localhost:{_server_port}"):
            return True
        referer = self.headers.get("Referer", "")
        if referer.startswith(f"http://127.0.0.1:{_server_port}") or referer.startswith(f"http://localhost:{_server_port}"):
            return True
        return False

    def _read_json_body(self):
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return None, ("invalid_content_type", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY_SIZE:
                return None, ("body_too_large", 413)
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body or "{}")
            return data, None
        except Exception as exc:
            return None, (f"invalid_json: {exc}", 400)

    def _match_path(self, path: str, pattern: str):
        return re.match(f"^{pattern}$", path)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json({"ok": True, "provider": LLM_PROVIDER, "model": OLLAMA_MODEL})
            return

        if path == "/api/ollama/status":
            from utils.llm import _ollama_available
            self._send_json({"ok": True, "ollama_available": _ollama_available(), "model": OLLAMA_MODEL})
            return

        if path == "/api/token":
            self._send_json({"token": API_TOKEN})
            return

        if path == "/api/history":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            records = get_history(limit=100)
            self._send_json({"ok": True, "records": records})
            return

        m = self._match_path(path, r"/api/history/([a-f0-9-]+)")
        if m:
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            record = get_analysis(m.group(1))
            if record:
                self._send_json({"ok": True, "record": record})
            else:
                self._send_json({"error": "not_found"}, 404)
            return

        if path == "/api/schedule":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            with _schedules_lock:
                items = []
                for sid, s in _schedules.items():
                    items.append({
                        "id": sid,
                        "prompt": s["prompt"],
                        "interval_seconds": s["interval_seconds"],
                        "created_at": s["created_at"],
                        "active": s["active"],
                    })
            self._send_json({"ok": True, "schedules": items})
            return

        if path == "/api/reports":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            records = db_get_reports(limit=50)
            report_list = []
            for r in records:
                report_list.append({
                    "filename": r.get("filename", ""),
                    "size": r.get("file_size", 0),
                    "created_at": r.get("generated_at", ""),
                    "classification": r.get("classification", "ABIERTO"),
                    "countries": r.get("countries", []),
                })
            self._send_json({"ok": True, "reports": report_list})
            return

        if path == "/api/pipeline/status":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            with _pipeline_lock:
                self._send_json({
                    "ok": True,
                    "running": _pipeline_state["running"],
                    "status": _pipeline_state["status"],
                    "started_at": _pipeline_state["started_at"],
                    "finished_at": _pipeline_state["finished_at"],
                    "error": _pipeline_state["error"],
                })
            return

        if path == "/api/pipeline/stream":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            self._handle_pipeline_stream()
            return

        if path == "/api/models":
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            from utils.llm import LLM_PROVIDER as current_provider
            models = get_ollama_tags()
            self._send_json({"ok": True, "models": models, "provider": current_provider})
            return

        m = self._match_path(path, r"/api/reports/([^/]+)")
        if m:
            if not self._check_auth():
                self._send_json({"error": "unauthorized"}, 401)
                return
            filename = m.group(1)
            if ".." in filename or "/" in filename or "\\" in filename:
                self._send_json({"error": "invalid_filename"}, 400)
                return
            reports_dir = ROOT / "outputs"
            if not reports_dir.exists():
                reports_dir = ROOT / "reports"
            file_path = reports_dir / filename
            if not file_path.exists() or not file_path.is_file():
                self._send_json({"error": "not_found"}, 404)
                return
            self._send_file(file_path, "application/octet-stream")
            return

        if path in {"/", "/index.html"}:
            self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return

        if path == "/styles.css":
            self._send_file(WEB_ROOT / "styles.css", "text/css; charset=utf-8")
            return

        if path == "/app.js":
            self._send_file(WEB_ROOT / "app.js", "application/javascript; charset=utf-8")
            return

        self._send_json({"error": "not_found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        client_ip = self.client_address[0]
        if not _check_rate(client_ip):
            self._send_json({"error": "rate_limit_exceeded"}, 429)
            return

        if not self._check_auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        if path == "/api/config":
            self._handle_config_update()
            return

        self._send_json({"error": "not_found"}, 404)

    def _handle_config_update(self):
        data, err = self._read_json_body()
        if err:
            self._send_json({"error": err[0]}, err[1])
            return

        new_model = data.get("model")
        new_provider = data.get("provider")

        if not new_model and not new_provider:
            self._send_json({"error": "se_requiere_model_o_provider"}, 400)
            return

        import utils.llm as llm_module

        if new_provider:
            if new_provider not in ("ollama", "openai", "auto"):
                self._send_json({"error": "provider_invalid"}, 400)
                return
            llm_module.set_provider(new_provider)

        if new_model:
            llm_module.set_model(new_model)

        self._send_json({
            "ok": True,
            "model": llm_module.OLLAMA_MODEL,
            "provider": llm_module.LLM_PROVIDER,
        })

    def _handle_pipeline_stream(self):
        with _pipeline_events_lock:
            _pipeline_events.clear()

        def event_generator():
            last_index = 0
            while True:
                with _pipeline_lock:
                    running = _pipeline_state["running"]
                    status = _pipeline_state["status"]

                with _pipeline_events_lock:
                    while last_index < len(_pipeline_events):
                        evt = _pipeline_events[last_index]
                        last_index += 1
                        yield evt

                if not running and status in ("completed", "failed", "idle"):
                    with _pipeline_events_lock:
                        while last_index < len(_pipeline_events):
                            evt = _pipeline_events[last_index]
                            last_index += 1
                            yield evt
                    break

                time.sleep(0.5)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        try:
            for event in event_generator():
                sse = f"data: {json.dumps(event)}\n\n"
                self.wfile.write(sse.encode("utf-8"))
                self.wfile.flush()
            done = f"data: {json.dumps({'done': True})}\n\n"
            self.wfile.write(done.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        client_ip = self.client_address[0]
        if not _check_rate(client_ip):
            self._send_json({"error": "rate_limit_exceeded"}, 429)
            return

        if not self._check_auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        if path == "/api/analyze":
            self._handle_analyze()
            return

        if path == "/api/analyze/stream":
            self._handle_analyze_stream()
            return

        if path == "/api/schedule":
            self._handle_schedule_create()
            return

        if path == "/api/pipeline":
            self._handle_pipeline()
            return

        self._send_json({"error": "not_found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        client_ip = self.client_address[0]
        if not _check_rate(client_ip):
            self._send_json({"error": "rate_limit_exceeded"}, 429)
            return

        if not self._check_auth():
            self._send_json({"error": "unauthorized"}, 401)
            return

        m = self._match_path(path, r"/api/history/([a-f0-9-]+)")
        if m:
            deleted = delete_analysis(m.group(1))
            if deleted:
                self._send_json({"ok": True, "deleted": True})
            else:
                self._send_json({"error": "not_found"}, 404)
            return

        m = self._match_path(path, r"/api/schedule/([a-f0-9-]+)")
        if m:
            sid = m.group(1)
            with _schedules_lock:
                schedule = _schedules.get(sid)
                if not schedule:
                    self._send_json({"error": "not_found"}, 404)
                    return
                timer = schedule.get("timer")
                if timer:
                    timer.cancel()
                schedule["active"] = False
                del _schedules[sid]
            self._send_json({"ok": True, "cancelled": True})
            return

        self._send_json({"error": "not_found"}, 404)

    def _handle_analyze(self):
        data, err = self._read_json_body()
        if err:
            self._send_json({"error": err[0]}, err[1])
            return

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send_json({"error": "prompt_required"}, 400)
            return

        system = (data.get("system") or "Eres un analista de inteligencia estratégica. Responde en español con rigor y claridad.").strip()
        temperature = float(data.get("temperature", 0.3))
        max_tokens = int(data.get("max_tokens", 2000))

        record_id = str(uuid.uuid4())
        try:
            response = ask_model(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system=system,
            )
            save_analysis(record_id, prompt, response, OLLAMA_MODEL, LLM_PROVIDER, system, temperature, max_tokens, "done")
            self._send_json({
                "ok": True,
                "id": record_id,
                "response": response,
                "provider": LLM_PROVIDER,
                "model": OLLAMA_MODEL,
                "status": "done",
            })
        except Exception as exc:
            save_analysis(record_id, prompt, "", OLLAMA_MODEL, LLM_PROVIDER, system, temperature, max_tokens, "error")
            self._send_json({"ok": False, "error": f"Fallo al consultar el modelo: {exc}"}, 502)

    def _handle_analyze_stream(self):
        data, err = self._read_json_body()
        if err:
            self._send_json({"error": err[0]}, err[1])
            return

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send_json({"error": "prompt_required"}, 400)
            return

        system = (data.get("system") or "Eres un analista de inteligencia estratégica. Responde en español con rigor y claridad.").strip()
        temperature = float(data.get("temperature", 0.3))
        max_tokens = int(data.get("max_tokens", 2000))

        record_id = str(uuid.uuid4())

        def token_generator():
            full_response = []
            try:
                for token in ask_model_stream(prompt, temperature=temperature, max_tokens=max_tokens, system=system):
                    full_response.append(token)
                    yield token
            except Exception:
                raise
            finally:
                save_analysis(record_id, prompt, "".join(full_response), OLLAMA_MODEL, LLM_PROVIDER, system, temperature, max_tokens, "done")

        self._send_sse(token_generator())

    def _handle_schedule_create(self):
        data, err = self._read_json_body()
        if err:
            self._send_json({"error": err[0]}, err[1])
            return

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send_json({"error": "prompt_required"}, 400)
            return

        interval = int(data.get("interval_seconds", 3600))
        if interval < 60:
            self._send_json({"error": "interval_minimum_60"}, 400)
            return

        system = (data.get("system") or "Eres un analista de inteligencia estratégica. Responde en español con rigor y claridad.").strip()
        temperature = float(data.get("temperature", 0.3))
        max_tokens = int(data.get("max_tokens", 2000))

        schedule_id = str(uuid.uuid4())

        def _execute_scheduled():
            try:
                response = ask_model(prompt, temperature=temperature, max_tokens=max_tokens, system=system)
                save_analysis(str(uuid.uuid4()), prompt, response, OLLAMA_MODEL, LLM_PROVIDER, system, temperature, max_tokens, "done")
            except Exception:
                pass
            with _schedules_lock:
                s = _schedules.get(schedule_id)
                if s and s["active"]:
                    timer = threading.Timer(interval, _execute_scheduled)
                    timer.daemon = True
                    s["timer"] = timer
                    timer.start()

        timer = threading.Timer(interval, _execute_scheduled)
        timer.daemon = True

        with _schedules_lock:
            _schedules[schedule_id] = {
                "prompt": prompt,
                "system": system,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "interval_seconds": interval,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "active": True,
                "timer": timer,
            }

        timer.start()

        self._send_json({
            "ok": True,
            "id": schedule_id,
            "interval_seconds": interval,
            "status": "scheduled",
        })

    def _handle_pipeline(self):
        with _pipeline_lock:
            if _pipeline_state["running"]:
                self._send_json({"error": "pipeline_already_running"}, 409)
                return
            _pipeline_state["running"] = True
            _pipeline_state["status"] = "starting"
            _pipeline_state["started_at"] = None
            _pipeline_state["finished_at"] = None
            _pipeline_state["error"] = None

        t = threading.Thread(target=_run_pipeline_background, daemon=True)
        with _pipeline_lock:
            _pipeline_state["thread"] = t
        t.start()

        self._send_json({"ok": True, "status": "started"})

    def log_message(self, format, *args):
        return


def _load_schedules_from_db():
    try:
        records = get_schedules()
        for s in records:
            sid = s.get("id")
            if not sid:
                continue
            interval = s.get("interval_seconds", 3600)
            prompt = s.get("prompt", "")
            system = s.get("system_prompt", "")
            temperature = s.get("temperature", 0.3)
            max_tokens = s.get("max_tokens", 2000)

            def _execute_scheduled(sid=sid, prompt=prompt, system=system, temperature=temperature, max_tokens=max_tokens, interval=interval):
                try:
                    response = ask_model(prompt, temperature=temperature, max_tokens=max_tokens, system=system)
                    save_analysis(str(uuid.uuid4()), prompt, response, OLLAMA_MODEL, LLM_PROVIDER, system, temperature, max_tokens, "done")
                except Exception:
                    pass
                with _schedules_lock:
                    s_info = _schedules.get(sid)
                    if s_info and s_info["active"]:
                        timer = threading.Timer(interval, _execute_scheduled)
                        timer.daemon = True
                        s_info["timer"] = timer
                        timer.start()

            timer = threading.Timer(interval, _execute_scheduled)
            timer.daemon = True

            with _schedules_lock:
                _schedules[sid] = {
                    "prompt": prompt,
                    "system": system,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "interval_seconds": interval,
                    "created_at": s.get("created_at", ""),
                    "active": True,
                    "timer": timer,
                }
            timer.start()
            logger.info("Schedule cargado desde DB: id=%s intervalo=%ds", sid, interval)
    except Exception as exc:
        logger.error("Error cargando schedules desde DB: %s", exc)


def run_server(host: str = "127.0.0.1", port: int = 8765):
    global _server_port
    _server_port = port
    init_db()
    _load_schedules_from_db()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"\n🚀 Interfaz local lista en http://{host}:{port}")
    print(f"🧠 Modelo configurado: {OLLAMA_MODEL}")
    print(f"🔑 Token API: {API_TOKEN}")
    print("Presiona Ctrl+C para detenerla.\n")
    server.serve_forever()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8765"))

    def open_browser():
        time.sleep(1.2)
        webbrowser.open(f"http://{host}:{port}")

    threading.Thread(target=open_browser, daemon=True).start()
    run_server(host, port)
