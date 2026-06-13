"""
Web Server — HTTP server yang serve dashboard dan API endpoints.
Berjalan di Thread 2 (selalu aktif).
"""

import ipaddress
import json
import os
import signal
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import partial


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_DEVICE_DIR = os.path.dirname(os.path.dirname(__file__))


def _is_lan_peer(peer: str) -> bool:
    """
    True for loopback + RFC1918 + link-local addresses. Used to gate the
    /auth/token handoff so any pendamping device on the same WiFi can
    fetch the token without SSH'ing in, while still rejecting random
    public IPs.
    """
    if not peer:
        return False
    if peer in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


# ─── Benchmark Runner ──────────────────────────────────────────────────────────

class BenchmarkRunner:
    STATUS_FILE = '/tmp/benchmark_progress.json'

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()

    def start(self, section=None):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return False, 'Already running'
            try:
                # Clear old progress
                try:
                    with open(self.STATUS_FILE, 'w') as f:
                        json.dump({'running': True, 'section': -1, 'lines': [], 'results': {}}, f)
                except Exception:
                    pass

                script = os.path.join(_DEVICE_DIR, 'benchmark.py')
                args   = [sys.executable, script]
                if section is not None:
                    args += ['--section', str(section)]
                self._proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=_DEVICE_DIR,
                )
                return True, f'Started PID {self._proc.pid}'
            except Exception as e:
                return False, str(e)

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                return True, 'Stopped'
            return False, 'Not running'

    def status(self):
        with self._lock:
            proc_running = self._proc is not None and self._proc.poll() is None
        try:
            with open(self.STATUS_FILE) as f:
                data = json.load(f)
            # proc is authoritative for running state
            data['running'] = proc_running or data.get('running', False)
            return data
        except Exception:
            return {'running': proc_running, 'section': -1, 'lines': [], 'results': {}}


# ─── Stress Runner ─────────────────────────────────────────────────────────────

class StressRunner:
    STATUS_FILE = '/tmp/overnight_status.json'
    STOP_FILE   = '/tmp/overnight_stop'
    PID_FILE    = '/tmp/overnight_pid'

    def start(self, hours=3):
        # Check if already running via pid file
        if os.path.exists(self.PID_FILE):
            try:
                with open(self.PID_FILE) as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)  # raises if dead
                return False, f'Already running (PID {pid})'
            except (ProcessLookupError, ValueError, OSError):
                pass  # stale pid file

        try: os.remove(self.STOP_FILE)
        except FileNotFoundError: pass

        script = os.path.join(_DEVICE_DIR, 'overnight_stress.py')
        proc   = subprocess.Popen(
            [sys.executable, script, '--hours', str(hours)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=_DEVICE_DIR,
            start_new_session=True,
        )
        try:
            with open(self.PID_FILE, 'w') as f:
                f.write(str(proc.pid))
        except Exception:
            pass
        return True, f'Started PID {proc.pid}'

    def stop(self):
        try: open(self.STOP_FILE, 'w').close()
        except Exception: pass
        try:
            if os.path.exists(self.PID_FILE):
                with open(self.PID_FILE) as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        return True, 'Stop signal sent'

    def status(self):
        try:
            with open(self.STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            return {
                'running': False, 'elapsed_s': 0, 'fps': 0.0,
                'temp_c': 0.0, 'ram_free_mb': 0,
                'throttle_events': 0, 'frames_total': 0,
            }


# ─── Benchmark Suite Runner ────────────────────────────────────────────────────

class BenchmarkSuiteRunner:
    """
    Runs the standardized 4-test benchmark suite as a subprocess.
    Results are readable from /tmp/bench_suite_progress.json while running,
    and from /root/logs/safety_index_report.json when done.
    """
    PROGRESS_FILE = "/tmp/bench_suite_progress.json"
    REPORT_FILE   = "/root/logs/safety_index_report.json"

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()

    def start(self, tests="T1,T2,T3,T4", t1_frames=100, t4_duration=600):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return False, "Already running"
            try:
                script = os.path.join(_DEVICE_DIR, "benchmark", "run_all.py")
                args   = [
                    sys.executable, script,
                    "--tests",       tests,
                    "--t1-frames",   str(t1_frames),
                    "--t4-duration", str(t4_duration),
                ]
                self._proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=_DEVICE_DIR,
                )
                return True, f"Suite started (PID {self._proc.pid})"
            except Exception as e:
                return False, str(e)

    def report_only(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return False, "Suite running — wait for it to finish"
            try:
                script = os.path.join(_DEVICE_DIR, "benchmark", "run_all.py")
                subprocess.Popen(
                    [sys.executable, script, "--report-only"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=_DEVICE_DIR,
                )
                return True, "Report compilation started"
            except Exception as e:
                return False, str(e)

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                return True, "Stopped"
        return False, "Not running"

    def progress(self):
        running = self._proc is not None and self._proc.poll() is None
        try:
            with open(self.PROGRESS_FILE) as f:
                data = json.load(f)
            data["proc_running"] = running
            return data
        except Exception:
            return {"running": running, "step": "idle", "pct": 0, "results": {}}

    def report(self):
        try:
            with open(self.REPORT_FILE) as f:
                return json.load(f)
        except Exception:
            return None


# ─── Module-level singletons ───────────────────────────────────────────────────
_benchmark = BenchmarkRunner()
_stress    = StressRunner()
_suite     = BenchmarkSuiteRunner()


# ─── Request Handler ───────────────────────────────────────────────────────────

class AuralAIHandler(BaseHTTPRequestHandler):
    """HTTP request handler untuk semua endpoint AuralAI."""

    def __init__(self, orchestrator, logger, data_collector, *args, **kwargs):
        self.orch = orchestrator
        self.logger = logger
        self.dc = data_collector
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass  # suppress default HTTPServer logging

    def do_GET(self):
        path = self.path.split("?")[0]

        # ── Companion redesign page routing (handoff §1) ──────────────────────
        # Behaviour:
        #   `/`         → static/app/companion.html if it exists. If first-time
        #                 (setup_completed=false), 302 to /setup. Falls back to
        #                 the legacy operator dashboard while the Preact build
        #                 hasn't shipped yet.
        #   `/admin`    → static/app/admin.html (or 302 to legacy if missing).
        #   `/guide`    → static/app/guide.html (public — no auth required).
        #   `/setup`    → static/app/setup.html.
        #   `/admin/legacy` → original device/server/static/index.html, kept
        #                     reachable for debug as long as the project lives.
        if path == "/" or path == "/index.html":
            self._serve_companion_root()
        elif path == "/admin" or path == "/admin/":
            self._serve_app_page("admin.html", fallback_legacy=True)
        elif path == "/guide" or path == "/guide/":
            self._serve_app_page("guide.html")
        elif path == "/setup" or path == "/setup/":
            self._serve_app_page("setup.html")
        elif path == "/admin/legacy" or path == "/admin/legacy/":
            self._serve_file("index.html", "text/html")
        elif path.startswith("/app/"):
            self._serve_app_asset(path[len("/app/"):])
        elif path == "/style.css":
            self._serve_file("style.css", "text/css")
        elif path == "/tokens.css":
            self._serve_file("tokens.css", "text/css")
        elif path == "/dashboard.js":
            self._serve_file("dashboard.js", "application/javascript")
        elif path == "/snapshot":
            self._serve_snapshot()
        elif path == "/status":
            self._serve_status()
        elif path == "/logs":
            self._serve_logs()
        elif path == "/history":
            self._serve_history()
        elif path == "/health":
            self._serve_health()
        # Companion redesign — manifest endpoints (must precede /audio/, /assets/)
        elif path == "/audio/chimes/manifest.json":
            self._serve_chimes_manifest()
        elif path == "/assets/manifest.json":
            self._serve_assets_manifest()
        elif path.startswith("/assets/"):
            self._serve_asset(path[len("/assets/"):])
        elif path.startswith("/audio/"):
            self._serve_audio(path[7:])
        # ── Benchmark endpoints ────────────────────────────────────────────────
        elif path == "/benchmark/status":
            self._send_json(_benchmark.status())
        # ── Stress endpoints ───────────────────────────────────────────────────
        elif path == "/stress/status":
            self._send_json(_stress.status())
        # ── Benchmark Suite endpoints ──────────────────────────────────────────
        elif path == "/suite/progress":
            self._send_json(_suite.progress())
        elif path == "/suite/report":
            r = _suite.report()
            if r:
                self._send_json(r)
            else:
                self._send_json({"error": "Report not available — run suite first"}, 404)
        # ── Data Collection endpoints ──────────────────────────────────────────
        elif path == "/collect" or path == "/collect/":
            self._serve_file("collect.html", "text/html")
        elif path == "/collect/status":
            self._serve_collect_status()
        elif path == "/collect/gallery":
            self._serve_collect_gallery()
        elif path.startswith("/collect/photo/"):
            self._serve_collect_photo(path[len("/collect/photo/"):])
        elif path == "/collect/download":
            self._serve_collect_download()
        elif path == "/ai-settings":
            self._serve_ai_settings()
        elif path == "/config":
            self._serve_config()
        elif path == "/auth/required":
            from config import cfg as _cfg
            self._send_json({
                "auth_required":   _cfg.AUTH_REQUIRED,
                "autosave":        _cfg.AUTOSAVE_ENABLED,
            })
        elif path == "/auth/token":
            self._serve_auth_token()
        elif path == "/presets":
            self._serve_presets()
        elif path == "/i2c-probe":
            self._serve_i2c_probe_status()
        else:
            self._send_404()

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._require_auth(path):
            return

        if path == "/command":
            self._handle_command()
        elif path == "/config":
            self._handle_config()
        # ── Benchmark ─────────────────────────────────────────────────────────
        elif path == "/benchmark/run":
            self._handle_benchmark_run()
        elif path == "/benchmark/stop":
            ok, msg = _benchmark.stop()
            self._send_json({"ok": ok, "message": msg})
        # ── Stress ────────────────────────────────────────────────────────────
        elif path == "/stress/start":
            self._handle_stress_start()
        elif path == "/stress/stop":
            ok, msg = _stress.stop()
            self._send_json({"ok": ok, "message": msg})
        # ── Benchmark Suite ───────────────────────────────────────────────
        elif path == "/suite/start":
            self._handle_suite_start()
        elif path == "/suite/stop":
            ok, msg = _suite.stop()
            self._send_json({"ok": ok, "message": msg})
        elif path == "/suite/report-only":
            ok, msg = _suite.report_only()
            self._send_json({"ok": ok, "message": msg})
        # ── Data Collection ───────────────────────────────────────────────────
        elif path == "/collect/mode":
            self._handle_collect_mode()
        elif path == "/collect/start":
            self._handle_collect_start()
        elif path == "/collect/stop":
            self._handle_collect_stop()
        elif path == "/collect/delete":
            self._handle_collect_delete()
        elif path == "/ai-settings":
            self._handle_ai_settings_save()
        elif path == "/ai-settings/test":
            self._handle_ai_settings_test()
        elif path == "/ai-settings/secure":
            self._handle_ai_settings_secure()
        elif path == "/presets/apply":
            self._handle_preset_apply()
        elif path == "/i2c-probe":
            self._handle_i2c_probe()
        else:
            self._send_404()

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    # ─── CORS / auth (CG-4) ────────────────────────────────────────────────────

    # POST paths that require token auth. Other POSTs and all GETs stay open.
    _AUTH_REQUIRED_POSTS = {
        "/command",
        "/config",
        "/ai-settings",
        "/ai-settings/test",
        "/ai-settings/secure",
        "/benchmark/run", "/benchmark/stop",
        "/stress/start",  "/stress/stop",
        "/suite/start",   "/suite/stop", "/suite/report-only",
        "/presets/apply",
    }

    # Data-collection endpoints stay OPEN on the LAN: the /collect page is meant
    # to be driven by a non-technical helper from their phone with no login, and
    # /auth/token is localhost-only (a remote browser can never obtain a token).
    # The photos themselves are already readable without auth via GET /snapshot
    # and GET /collect/photo, so gating start/stop/mode/delete added no real
    # protection — only made the page unusable remotely. (/collect/mode toggles
    # Mode Ambil Data; start/stop/delete control capture.)

    # Bootstrap mode — when setup_completed=False, these endpoints are needed
    # by the first-time setup wizard but the pendamping has no way to get a
    # token (the wizard runs from a remote browser, /auth/token is
    # localhost-only). Auth is skipped for these paths until setup completes.
    # Once setup_completed=True is persisted, the full auth gate engages.
    _BOOTSTRAP_OPEN_POSTS = {
        "/config",
        "/ai-settings",
        "/ai-settings/test",
        "/ai-settings/secure",
        "/presets/apply",
    }

    def _set_cors_headers(self):
        from config import cfg as _cfg
        origins = _cfg.CORS_ALLOWED_ORIGINS
        req_origin = self.headers.get("Origin", "")
        if "*" in origins:
            allow = "*"
        elif req_origin and req_origin in origins:
            allow = req_origin
        elif origins:
            allow = origins[0]
        else:
            allow = "null"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Auth-Token")

    def _auth_ok(self) -> bool:
        from config import cfg as _cfg
        if not _cfg.AUTH_REQUIRED:
            return True
        from utils.auth import verify
        token = self.headers.get("X-Auth-Token", "")
        if not token:
            q = self.path.split("?", 1)
            if len(q) == 2:
                for kv in q[1].split("&"):
                    if kv.startswith("token="):
                        token = kv[6:]
                        break
        return verify(token)

    def _require_auth(self, path: str) -> bool:
        if path not in self._AUTH_REQUIRED_POSTS:
            return True
        if self._auth_ok():
            return True
        # Bootstrap exemption: setup wizard endpoints stay open until the
        # device has been provisioned. This lets the pendamping finish the
        # first-time wizard from a remote browser without juggling tokens.
        from config import cfg as _cfg
        if not _cfg.SETUP_COMPLETED and path in self._BOOTSTRAP_OPEN_POSTS:
            return True
        self._send_json(
            {"error": "unauthorized", "hint": "X-Auth-Token required"}, 401,
        )
        return False

    # ─── Core endpoints ────────────────────────────────────────────────────────

    def _serve_file(self, filename, content_type):
        filepath = os.path.join(STATIC_DIR, filename)
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(data))
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._send_404()

    # ─── Companion redesign — page + asset serving (handoff §1) ───────────────

    def _serve_companion_root(self):
        """
        `/` handler. Routes:
          - to /setup if setup_completed=False (first-time pendamping)
          - to static/app/companion.html if built and present
          - falls back to the legacy operator dashboard otherwise so the device
            is never left without a UI.
        """
        from config import cfg as _cfg
        if not _cfg.SETUP_COMPLETED:
            self._send_redirect("/setup")
            return
        if self._app_file_exists("companion.html"):
            self._serve_app_page("companion.html")
            return
        # Build artefacts not yet present → legacy dashboard.
        self._serve_file("index.html", "text/html")

    def _serve_app_page(self, filename: str, fallback_legacy: bool = False):
        """Serve a built HTML entry from static/app/. Optional legacy fallback."""
        app_dir = os.path.join(STATIC_DIR, "app")
        filepath = os.path.join(app_dir, filename)
        if not os.path.isfile(filepath):
            if fallback_legacy:
                self._serve_file("index.html", "text/html")
            else:
                self._send_404()
            return
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(data))
            # HTML entries are immutable per build hash; allow short caching.
            self.send_header("Cache-Control", "no-cache")
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._send_404()

    def _serve_app_asset(self, rel_path: str):
        """Serve a hashed asset (JS/CSS/img) from static/app/."""
        import mimetypes
        # Guard against traversal — these paths come straight from URLs.
        if not rel_path or ".." in rel_path.split("/") or rel_path.startswith("/"):
            self._send_404()
            return
        app_dir = os.path.join(STATIC_DIR, "app")
        filepath = os.path.normpath(os.path.join(app_dir, rel_path))
        if not filepath.startswith(os.path.abspath(app_dir)):
            self._send_404()
            return
        try:
            with open(filepath, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self._send_404()
            return
        ctype, _ = mimetypes.guess_type(filepath)
        if not ctype:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(data))
        # Vite emits hashed filenames → safe to long-cache.
        if "/assets/" in rel_path.replace("\\", "/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _app_file_exists(filename: str) -> bool:
        return os.path.isfile(os.path.join(STATIC_DIR, "app", filename))

    def _send_redirect(self, location: str, status: int = 302):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self._set_cors_headers()
        self.end_headers()

    def _serve_snapshot(self):
        snap = self.orch.snapshot
        if snap is None:
            self._send_404()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", len(snap))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(snap)

    def _serve_status(self):
        self._send_json(self.orch.get_status())

    def _serve_logs(self):
        logs = self.orch.logger.get_recent(50)
        self._send_json({"logs": logs})

    def _serve_health(self):
        try:
            from utils.health import get_health
            self._send_json(get_health())
        except Exception as e:
            self._send_error(e)

    def _serve_audio(self, filename):
        from config import cfg as _cfg
        # Allow files in /audio/ root and subfolders (e.g. /audio/chimes/boot.wav).
        # Filename is everything after "/audio/" — already URL-decoded by BaseHTTPRequestHandler.
        # Guard against path traversal.
        if ".." in filename.split("/"):
            self._send_404()
            return
        filepath = os.path.join(_cfg.AUDIO_DIR, filename)
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", len(data))
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._send_404()

    # ─── Companion redesign — manifest + asset endpoints (handoff §8.5) ───────

    def _serve_chimes_manifest(self):
        """List *.wav files in <audio_dir>/chimes. Empty list if folder absent."""
        from pathlib import Path
        from config import cfg as _cfg
        chimes_dir = Path(_cfg.AUDIO_DIR) / "chimes"
        try:
            if chimes_dir.exists():
                files = sorted(p.name for p in chimes_dir.glob("*.wav"))
            else:
                files = []
        except Exception:
            files = []
        self._send_json({"chimes": files})

    def _serve_assets_manifest(self):
        """List files in assets_dir. Empty list if folder absent."""
        from pathlib import Path
        from config import cfg as _cfg
        assets_dir = Path(_cfg.ASSETS_DIR)
        try:
            if assets_dir.exists():
                files = sorted(
                    p.name for p in assets_dir.iterdir()
                    if p.is_file() and not p.name.startswith(".")
                )
            else:
                files = []
        except Exception:
            files = []
        self._send_json({"assets": files})

    def _serve_asset(self, filename):
        """Serve a file from assets_dir. MIME via mimetypes. Guards traversal."""
        import mimetypes
        from pathlib import Path
        from config import cfg as _cfg
        if not filename or ".." in filename.split("/") or filename.startswith("/"):
            self._send_404()
            return
        # Disallow nested paths — assets is flat.
        if "/" in filename:
            self._send_404()
            return
        filepath = Path(_cfg.ASSETS_DIR) / filename
        try:
            data = filepath.read_bytes()
        except FileNotFoundError:
            self._send_404()
            return
        except Exception as e:
            self._send_error(e)
            return
        ctype, _ = mimetypes.guess_type(filename)
        if not ctype:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "public, max-age=300")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _serve_history(self):
        """
        Companion activity feed source (handoff §8.4).
        Parses recent log entries into items {t, mode, text, priority}.
        Query: ?date=today (only "today" supported now; future: YYYY-MM-DD).
        """
        from urllib.parse import parse_qs, urlparse
        try:
            qs = parse_qs(urlparse(self.path).query)
        except Exception:
            qs = {}
        date_filter = (qs.get("date") or ["today"])[0]

        # Source 1: in-memory recent log buffer (always available)
        try:
            raw = self.orch.logger.get_recent(500)
        except Exception:
            raw = []

        items = []
        # Look at recent audio_text events recorded by orchestrator/audio_manager.
        # Logger entries are dicts with at least {ts, level, module, msg}
        # — see utils/logger.py _log().
        for entry in raw:
            try:
                t_iso = entry.get("ts") or ""
                module = entry.get("module", "")
                text = entry.get("msg") or ""
                level = (entry.get("level") or "").lower()
            except Exception:
                continue
            if not text:
                continue
            # Filter for user-relevant events. Modules that emit audio/captions:
            if module not in ("AudioManager", "Orchestrator", "AI", "QRIS"):
                continue
            # Derive a "mode" tag from module/text.
            low = text.lower()
            if "qris" in low:
                mode = "qris"
            elif module == "AI" or "scene" in low or "deskrip" in low:
                mode = "scene"
            else:
                mode = "explorer"
            # Priority from log level.
            if level in ("error", "danger", "warn"):
                priority = "high"
            elif level in ("info", "ok"):
                priority = "normal"
            else:
                priority = "low"
            # Short clock from ISO timestamp HH:MM
            t_clock = t_iso[11:16] if len(t_iso) >= 16 else t_iso[:5]
            items.append({
                "t":        t_clock,
                "t_iso":    t_iso,
                "mode":     mode,
                "text":     text,
                "priority": priority,
                "module":   module,
            })
        # Cap to last 200 (newest last per logger convention).
        items = items[-200:]
        self._send_json({"items": items, "date": date_filter})

    def _handle_command(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            cmd = data.get("cmd")
            if not cmd:
                self._send_json({"error": "missing cmd"}, 400)
                return

            valid_cmds = {"focus", "capture", "qris", "describe", "set_mode"}
            if cmd not in valid_cmds:
                self._send_json({"error": f"unknown cmd: {cmd}"}, 400)
                return

            self.orch.set_pending_command(cmd, data)
            self.logger.info(f"Command received: {cmd}")
            self._send_json({"ok": True, "cmd": cmd})

        except Exception as e:
            self.logger.error(f"Command error: {e}")
            self._send_json({"error": str(e)}, 500)

    def _handle_config(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            data   = json.loads(body)
            from config import cfg
            # Validate enum-style fields introduced by the companion redesign.
            if "audio_mode" in data and data["audio_mode"] not in ("chime", "speech", "both"):
                self._send_json({
                    "error": "invalid audio_mode",
                    "allowed": ["chime", "speech", "both"],
                }, 400)
                return
            if "setup_completed" in data:
                data["setup_completed"] = bool(data["setup_completed"])
            # device_name becomes the mDNS `.local` label — keep it DNS-safe.
            # Empty ("") is allowed: it reverts to the auto "aural-<id>" default.
            # Reject only a non-empty name that sanitizes to nothing (e.g. "@@@").
            if "device_name" in data:
                from utils.identity import sanitize_name
                raw = (data["device_name"] or "").strip()
                clean = sanitize_name(raw)
                if raw and not clean:
                    self._send_json({
                        "error": "invalid device_name",
                        "hint": "gunakan huruf, angka, atau tanda strip",
                    }, 400)
                    return
                data["device_name"] = clean
            cfg.update(data)
            # Re-publish mDNS under the new name if it changed.
            if "device_name" in data:
                try:
                    mdns = getattr(self.orch, "mdns", None)
                    if mdns is not None:
                        from utils.identity import device_name as _dn
                        mdns.update_name(_dn())
                except Exception:
                    pass
            self.logger.info(f"Config updated: {list(data.keys())}")
            self._send_json({"ok": True, "applied": list(data.keys())})
        except Exception as e:
            self._send_error(e)

    # ─── Benchmark Suite endpoints ─────────────────────────────────────────────

    def _handle_suite_start(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length)) if length else {}
            tests      = data.get("tests",       "T1,T2,T3,T4")
            t1_frames  = int(data.get("t1_frames",  100))
            t4_duration = float(data.get("t4_duration", 600))
            ok, msg = _suite.start(tests=tests, t1_frames=t1_frames,
                                   t4_duration=t4_duration)
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    # ─── Benchmark endpoints ───────────────────────────────────────────────────

    def _handle_benchmark_run(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length)) if length else {}
            section = data.get("section")  # None = all sections
            ok, msg = _benchmark.start(section)
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    # ─── Stress endpoints ──────────────────────────────────────────────────────

    def _handle_stress_start(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length)) if length else {}
            hours  = float(data.get("hours", 3))
            ok, msg = _stress.start(hours)
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    # ─── Data Collection endpoints ─────────────────────────────────────────────

    def _serve_collect_status(self):
        if self.dc is None:
            self._send_json({"error": "data collector not available"}, 503)
            return
        from config import cfg as _cfg
        stats = dict(self.dc.stats)
        # So the UI can render the Mode Ambil Data toggle state on load/poll.
        stats["data_collection_mode"] = _cfg.get("data_collection_mode", False)
        self._send_json(stats)

    def _handle_collect_mode(self):
        """Toggle Mode Ambil Data. Persists the flag and wakes the AI loop, which
        owns the camera handoff (release aural ↔ auto-start capture). We do NOT
        touch the camera here — that must stay on the AI thread to avoid races."""
        try:
            from config import cfg as _cfg
            length  = int(self.headers.get("Content-Length", 0))
            data    = json.loads(self.rfile.read(length)) if length else {}
            enabled = bool(data.get("enabled"))
            _cfg.update({"data_collection_mode": enabled})   # persist (survives reboot)
            try:
                self.orch._mode_event.set()                  # trigger live transition
            except Exception:
                pass
            self._send_json({"ok": True, "data_collection_mode": enabled})
        except Exception as e:
            self._send_error(e)

    def _serve_collect_gallery(self):
        if self.dc is None:
            self._send_json({"photos": []})
            return
        self._send_json({"photos": self.dc.gallery})

    def _serve_collect_photo(self, filename):
        if self.dc is None:
            self._send_404()
            return
        data = self.dc.serve_photo(filename)
        if data is None:
            self._send_404()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "no-cache")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _handle_collect_start(self):
        if self.dc is None:
            self._send_json({"error": "data collector not available"}, 503)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = {}
            if length:
                data = json.loads(self.rfile.read(length))
            ok, msg = self.dc.start(
                interval_s=data.get("interval_s"),
                quality=data.get("quality"),
            )
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    def _handle_collect_stop(self):
        if self.dc is None:
            self._send_json({"error": "data collector not available"}, 503)
            return
        try:
            ok, msg = self.dc.stop()
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    def _handle_collect_delete(self):
        if self.dc is None:
            self._send_json({"error": "data collector not available"}, 503)
            return
        try:
            length   = int(self.headers.get("Content-Length", 0))
            data     = json.loads(self.rfile.read(length)) if length else {}
            filename = data.get("filename", "")
            ok, msg  = self.dc.delete_photo(filename)
            self._send_json({"ok": ok, "message": msg})
        except Exception as e:
            self._send_error(e)

    def _serve_collect_download(self):
        if self.dc is None:
            self._send_json({"error": "data collector not available"}, 503)
            return
        zip_path, err = self.dc.create_session_zip()
        if err or not zip_path:
            self._send_json({"error": err or "zip gagal"}, 500)
            return
        try:
            with open(zip_path, "rb") as f:
                data = f.read()
            import os as _os
            basename = _os.path.basename(zip_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", len(data))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{basename}"')
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_error(e)

    def _serve_config(self):
        from config import cfg
        data = cfg.as_dict()
        # Don't leak secrets via /config — mask keys + token
        for k in ("openai_api_key", "gemini_api_key", "claude_api_key", "device_token"):
            if data.get(k):
                v = data[k]
                data[k] = "***" + v[-4:] if len(v) > 4 else "****"
        self._send_json(data)

    def _serve_auth_token(self):
        """
        Return the device token so dashboard JS can pre-fill its auth
        header. Allowed from:
          - loopback (127.0.0.1, ::1)
          - private LAN (RFC1918 + link-local) when on the same WiFi as the
            device, which is the pilot/handoff topology — pendamping plugs
            their laptop into the same WiFi the kacamata is on.

        For production deployments where the device is reachable over a
        wider network, tighten this via `cors_allowed_origins` and consider
        moving the token out-of-band (printed sticker, QR on setup card).
        """
        peer = self.client_address[0] if self.client_address else ""
        if not _is_lan_peer(peer):
            self._send_json({"error": "off-LAN access denied"}, 403)
            return
        from utils.auth import get_token, ensure_token
        token = get_token() or ensure_token(self.logger)
        self._send_json({"token": token})

    def _serve_presets(self):
        try:
            from utils.presets import list_presets
            self._send_json(list_presets())
        except Exception as e:
            self._send_error(e, context="presets list")

    # ─── I2C probe endpoints (W-2) ────────────────────────────────────────────

    def _serve_i2c_probe_status(self):
        from config import cfg as _cfg
        self._send_json({
            "i2c_battery_enabled": _cfg.I2C_BATTERY_ENABLED,
            "note": "POST /i2c-probe {\"action\":\"probe\"} to run probe, {\"action\":\"disable\"} to disable",
        })

    def _handle_i2c_probe(self):
        if not self._auth_ok():
            return
        body = self._read_body_json() or {}
        action = body.get("action", "probe")
        from config import cfg as _cfg
        if action == "disable":
            _cfg.update({"i2c_battery_enabled": False})
            self._send_json({"ok": True, "i2c_battery_enabled": False})
        else:
            try:
                from utils.health import _probe_i2c_battery
                found = _probe_i2c_battery()
            except Exception:
                found = False
            _cfg.update({"i2c_battery_enabled": found})
            self._send_json({"ok": True, "found": found, "i2c_battery_enabled": found})

    # ─── AI Settings endpoints ─────────────────────────────────────────────────

    def _serve_ai_settings(self):
        from config import cfg
        data = cfg.as_dict()
        # Mask secrets — send only whether a key is set, not the value
        def _masked(key: str) -> str:
            v = data.get(key, "")
            if not v:
                return ""
            return "***" + v[-4:] if len(v) > 4 else "****"

        def _has(provider: str) -> bool:
            return bool(
                data.get(f"{provider}_api_key")
                or data.get(f"{provider}_api_key_enc")
            )

        def _enc_status(provider: str) -> str:
            if data.get(f"{provider}_api_key_enc"):
                return "encrypted"
            if data.get(f"{provider}_api_key"):
                return "plaintext"
            return "unset"

        self._send_json({
            "ai_provider":   data.get("ai_provider", "openai"),
            "ai_timeout_s":  data.get("ai_timeout_s", 15),
            "openai_model":  data.get("openai_model", "gpt-4o-mini"),
            "openai_key_set":  _has("openai"),
            "openai_key_hint": _masked("openai_api_key"),
            "openai_key_status": _enc_status("openai"),
            "gemini_model":  data.get("gemini_model", "gemini-1.5-flash"),
            "gemini_key_set":  _has("gemini"),
            "gemini_key_hint": _masked("gemini_api_key"),
            "gemini_key_status": _enc_status("gemini"),
            "claude_model":  data.get("claude_model", "claude-haiku-4-5-20251001"),
            "claude_key_set":  _has("claude"),
            "claude_key_hint": _masked("claude_api_key"),
            "claude_key_status": _enc_status("claude"),
            "prompt_scene":  data.get("prompt_scene", ""),
            "prompt_qris":   data.get("prompt_qris", ""),
            "keys_locked":   bool(data.get("api_keys_locked")),
            "qris_mode":     data.get("qris_mode", "hybrid"),
            "autosave":      bool(data.get("autosave_enabled", True)),
        })

    def _handle_ai_settings_save(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            from config import cfg

            allowed = {
                "ai_provider", "ai_timeout_s",
                "openai_api_key", "openai_model",
                "gemini_api_key", "gemini_model",
                "claude_api_key", "claude_model",
                "prompt_scene",   "prompt_qris",
            }
            payload = {k: v for k, v in body.items() if k in allowed}
            for key in ("openai_api_key", "gemini_api_key", "claude_api_key"):
                if payload.get(key) in ("", "****", None):
                    payload.pop(key, None)

            # Refuse plaintext key overwrite when locked.
            if cfg.API_KEYS_LOCKED:
                blocked = [k for k in list(payload.keys()) if k.endswith("_api_key")]
                for k in blocked:
                    payload.pop(k, None)
                if blocked:
                    self.logger.warn(
                        f"API key edit refused (locked): {blocked}",
                        module="WebServer",
                    )

            cfg.update(payload)
            self.logger.info(
                f"AI settings saved: {[k for k in payload if 'key' not in k]}"
            )
            self._send_json({
                "ok":          True,
                "applied":     list(payload.keys()),
                "keys_locked": cfg.API_KEYS_LOCKED,
            })
        except Exception as e:
            self._send_error(e)

    def _handle_ai_settings_secure(self):
        """
        Store an API key in encrypted form. Body:
            {"provider": "openai|gemini|claude", "api_key": "<plain>"}
        Optionally {"lock": true|false} to toggle api_keys_locked.

        When locked, this endpoint also rejects writes — operator must
        run tools/unlock_keys.py on the device console to clear the lock.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            from config import cfg
            from utils.secure_keys import encrypt

            if cfg.API_KEYS_LOCKED:
                self._send_json({
                    "ok":    False,
                    "error": "api_keys_locked",
                    "hint":  "Run tools/unlock_keys.py on device console to clear lock.",
                }, 403)
                return

            applied = {}
            provider = body.get("provider")
            api_key  = body.get("api_key", "")
            if provider in ("openai", "gemini", "claude") and api_key:
                applied[f"{provider}_api_key_enc"] = encrypt(api_key)
                applied[f"{provider}_api_key"]     = ""  # clear any plaintext
            if "lock" in body:
                applied["api_keys_locked"] = bool(body["lock"])

            if not applied:
                self._send_json({"ok": False, "error": "no-op"}, 400)
                return

            cfg.update(applied)
            self.logger.warn(
                f"Secure-key update: provider={provider} lock={applied.get('api_keys_locked')}",
                module="WebServer",
            )
            self._send_json({
                "ok":          True,
                "keys_locked": cfg.API_KEYS_LOCKED,
                "applied":     [k for k in applied if "api_key" not in k or "locked" in k],
            })
        except Exception as e:
            self._send_error(e)

    def _handle_preset_apply(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
            mode   = body.get("mode", "")
            name   = body.get("name", "")
            from utils.presets import apply_preset
            applied = apply_preset(mode, name)
            if not applied:
                self._send_json({"ok": False, "error": "unknown preset"}, 404)
                return
            self.logger.info(
                f"Preset applied: {mode}/{name} -> {list(applied.keys())}",
                module="WebServer",
            )
            self._send_json({"ok": True, "mode": mode, "name": name, "applied": applied})
        except Exception as e:
            self._send_error(e, context="preset apply")

    def _handle_ai_settings_test(self):
        try:
            from config import cfg
            from adapters import get_adapter
            adapter = get_adapter(cfg.AI_PROVIDER, cfg)
            result  = adapter.test_connection()
            self._send_json(result)
        except ValueError as e:
            self._send_json({"ok": False, "message": str(e)}, 400)
        except Exception as e:
            self.logger.exception(str(e), module="WebServer", exc=e)
            self._send_json({"ok": False, "message": str(e)}, 500)

    # ─── Helpers ───────────────────────────────────────────────────────────────

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self):
        accept = self.headers.get("Accept", "")
        if "text/html" in accept:
            html = (
                "<!doctype html><html lang=\"id\"><head>"
                "<meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>Halaman tidak ditemukan — AuralAI</title>"
                "<style>body{font-family:system-ui,sans-serif;max-width:480px;"
                "margin:80px auto;padding:0 20px;text-align:center;color:#1a1a2e}"
                "h1{font-size:1.5rem;margin-bottom:.5rem}p{color:#555}"
                "a{color:#4f46e5;text-decoration:none;font-weight:600}</style>"
                "</head><body>"
                "<h1>Halaman tidak ditemukan</h1>"
                "<p>Alamat yang kamu cari tidak ada.</p>"
                "<p><a href=\"/\">Kembali ke Beranda</a></p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(html)
        else:
            self._send_json({"error": "not found"}, 404)

    def _send_error(self, exc: Exception, status: int = 500, context: str = ""):
        """Log full traceback + return error JSON. Use in handler except blocks."""
        msg = f"{context}: {exc}" if context else str(exc)
        try:
            self.logger.exception(msg, module="WebServer", exc=exc)
        except Exception:
            pass
        self._send_json({"error": str(exc)}, status)


# ─── WebServer ─────────────────────────────────────────────────────────────────

class WebServer:
    def __init__(self, host, port, orchestrator, logger, data_collector=None):
        self.host = host
        self.port = port
        self.orch = orchestrator
        self.logger = logger
        self.data_collector = data_collector

    def start(self):
        # Ensure device token exists before serving any request (CG-4)
        try:
            from utils.auth import ensure_token
            ensure_token(self.logger)
        except Exception as e:
            self.logger.exception(
                f"Auth token init failed: {e}", module="WebServer", exc=e,
            )
        handler = partial(AuralAIHandler, self.orch, self.logger, self.data_collector)
        # ThreadingHTTPServer: a slow handler (e.g. /snapshot during AI engine
        # reload) no longer blocks unrelated polls. Daemon threads die with
        # the server on shutdown.
        server = ThreadingHTTPServer((self.host, self.port), handler)
        server.daemon_threads = True
        self.logger.ok(f"Web server listening on {self.host}:{self.port}")
        server.serve_forever()
