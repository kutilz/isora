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
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import partial


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Voices /v1/audio/speech accepts. Kept here rather than fetched so a device
# with no internet can still validate a POST /config, and so an unknown name is
# refused with a list instead of failing once per describe.
_OPENAI_VOICES = {
    "alloy", "ash", "ballad", "coral", "echo", "fable",
    "nova", "onyx", "sage", "shimmer", "verse",
}

# What the "Coba suara" button speaks. A real-shaped sentence — positions and a
# clearance call, the two things a description actually has to land — so the
# listener is judging the voice on the words they will really hear.
_TTS_TEST_PHRASE = ("Di depan ada seorang pria berkacamata berdiri dekat meja "
                    "komputer. Di sebelah kanan Anda ada kursi kosong, jalur "
                    "di depan aman.")
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


# Preset clips queue at HIGH (audio_manager.HIGH): above scene speech, below a
# danger alert, which must still be able to cut in.
_PRESET_PRIORITY = 1


def _event_mode() -> bool:
    try:
        from config import cfg as _cfg
        return _cfg.EVENT_MODE
    except Exception:
        return False


# ─── Module-level singletons ───────────────────────────────────────────────────
_benchmark = BenchmarkRunner()
_stress    = StressRunner()
_suite     = BenchmarkSuiteRunner()


# ─── Request Handler ───────────────────────────────────────────────────────────

class IsoraHandler(BaseHTTPRequestHandler):
    """HTTP request handler untuk semua endpoint I-Sora."""

    # Socket timeout for every read and write. Without it a client that
    # promises a body it never sends (or a phone that drops off the hotspot
    # mid-response) pins its handler thread forever, and on a 128 MB board
    # enough of those starve the app. A long-poll is unaffected: it waits on
    # a condition, not on the socket.
    timeout = 20

    # Every POST body here is a small JSON document (the largest is a prompt).
    # Anything bigger is refused before a byte of it is read into RAM.
    _MAX_BODY = 256 * 1024

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
        elif path == "/companion" or path == "/companion/":
            # Caregiver/companion dashboard — relocated here from `/` now that the
            # button console is the blind user's primary home page.
            self._serve_app_page("companion.html", fallback_legacy=True)
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
        elif path == "/audio/trace":
            self._serve_audio_trace()
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
        # ── Button simulation page (web fallback for dead hardware buttons) ────
        elif path == "/buttons" or path == "/buttons/":
            self._serve_file("buttons.html", "text/html")
        # ── Listen on the phone (→ its Bluetooth earphones/speaker) ────────────
        elif path == "/pimnas" or path == "/pimnas/":
            self._serve_file("pimnas.html", "text/html; charset=utf-8")
        elif path == "/pimnas/presets":
            from utils.speech_presets import presets
            self._send_json({"presets": presets().list()})
        elif path == "/pimnas/check":
            self._serve_pimnas_check()
        elif path == "/dengar" or path == "/dengar/":
            self._serve_file("listen.html", "text/html; charset=utf-8")
        elif path == "/listen/poll":
            self._serve_listen_poll()
        elif path.startswith("/listen/clip/"):
            self._serve_listen_clip(path[len("/listen/clip/"):])
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

    def _body_size_ok(self) -> bool:
        """Refuse a body too big for RAM, or a length that is not a length.

        Checked once here, so the per-handler `rfile.read(length)` calls can
        trust it: a negative length would read until the client hangs up.
        """
        raw = self.headers.get("Content-Length")
        if raw is None:
            return True
        try:
            length = int(raw)
        except ValueError:
            length = -1
        if 0 <= length <= self._MAX_BODY:
            return True
        self.close_connection = True
        self._send_json({"error": "request body too large or invalid"},
                        413 if length > self._MAX_BODY else 400)
        return False

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._body_size_ok():
            return
        if not self._require_auth(path):
            return
        if path in self._EVENT_LOCKED_POSTS and _event_mode():
            self._send_json({"error": "Mode PIMNAS aktif — fitur ini dikunci. "
                                      "Matikan dulu dari /pimnas."}, 423)
            return

        if path.startswith("/pimnas/"):
            self._handle_pimnas(path)
        elif path == "/command":
            self._handle_command()
        elif path == "/tts-test":
            self._handle_tts_test()
        elif path == "/button":
            self._handle_button()
        elif path == "/listen/leave":
            self._handle_listen_leave()
        elif path == "/config":
            self._handle_config()
        elif path == "/brand":
            self._handle_brand()
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
        "/tts-test",
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
    # to be driven by a non-technical helper from their phone with no login.
    # SECURITY NOTE: /auth/token is LAN-accessible (any RFC1918/link-local peer,
    # not just loopback — see _is_lan_peer), so token auth is only as strong as
    # the WiFi the device is on. On a shared network any peer can obtain the
    # token; the intended deployment is a private/isolated AP. Do not treat these
    # open endpoints as loopback-protected. (/collect/mode toggles Mode Ambil
    # Data; start/stop/delete control capture.)

    # Bootstrap mode — when setup_completed=False, these endpoints are needed by
    # the first-time setup wizard, which runs from the pendamping's phone on the
    # same LAN. Auth is skipped for these paths until setup completes; the
    # protected-key stripping in _handle_config still applies, so an
    # unauthenticated bootstrap client cannot set device_token/auth_required or
    # overwrite encrypted keys. Once setup_completed=True is persisted, the full
    # auth gate engages.
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
        else:
            # No grant at all. "null" would let in a sandboxed iframe on any
            # page (its Origin IS "null"); the device's own pages are
            # same-origin and need no CORS header.
            return
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
        `/` handler — the device's home page.
          - to /setup if setup_completed=False (first-time pendamping)
          - otherwise the button console (buttons.html): the blind user's
            PRIMARY daily interface. User interviews found they rely on it as a
            familiar "second control" (their phone) alongside the physical
            buttons, so it is the home page. The caregiver/companion dashboard
            moved to /companion; the technical dashboard is at /admin.
        """
        from config import cfg as _cfg
        if not _cfg.SETUP_COMPLETED:
            self._send_redirect("/setup")
            return
        self._serve_file("buttons.html", "text/html")

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
        # Tell the AI loop someone is looking, so it starts paying for the JPEG
        # encode again. It stops on its own once the polling stops.
        try:
            self.orch.note_preview_request()
        except Exception:
            pass
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

    def _serve_audio_trace(self):
        """GET /audio/trace?since=<seq> — every clip asked for and its fate.

        Answers "why did it not say X": queued → played / cut (then replayed)
        / dropped with a reason (flushed by a press, cooldown, stale nav,
        play-failed...). Read-only; the same text /status already shows.
        """
        from urllib.parse import urlparse, parse_qs
        am = getattr(self.orch, "audio_manager", None)
        if am is None or not hasattr(am, "trace_since"):
            self._send_json({"error": "audio not running"}, 503)
            return
        try:
            since = int(parse_qs(urlparse(self.path).query).get("since", ["0"])[0])
        except ValueError:
            since = 0
        self._send_json(am.trace_since(since))

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
        # Guard against path traversal: reject ".." segments AND absolute paths
        # (os.path.join drops the base when the second arg starts with "/", so a
        # request like /audio//root/config.json would otherwise escape AUDIO_DIR),
        # then confirm the resolved real path is still contained in AUDIO_DIR.
        base = os.path.realpath(_cfg.AUDIO_DIR)
        filepath = os.path.realpath(os.path.join(base, filename))
        if (".." in filename.split("/")
                or os.path.isabs(filename)
                or (filepath != base and not filepath.startswith(base + os.sep))):
            self._send_404()
            return
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

    def _handle_tts_test(self):
        """Speak a fixed sample so a voice can be auditioned from the phone.

        Without this, changing the voice means pressing Deskripsikan and waiting
        out a whole AI round-trip to hear one sentence — and the pendamping
        choosing the voice is often not the person holding the device. Body may
        carry {"voice": "..."} to preview a voice WITHOUT saving it, so a
        candidate can be rejected without ever having been the live setting.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            data = {}

        voice = str(data.get("voice", "")).strip()
        if voice and voice not in _OPENAI_VOICES:
            self._send_json({"error": "invalid voice",
                             "allowed": sorted(_OPENAI_VOICES)}, 400)
            return

        am = getattr(self.orch, "audio_manager", None)
        if am is None:
            self._send_json({"error": "audio unavailable"}, 503)
            return

        from config import cfg as _cfg
        prev = _cfg.get("tts_openai_voice", "alloy")
        try:
            if voice and voice != prev:
                # In-memory only — never written to config.json, so a preview
                # can't outlive the request or survive a reboot.
                _cfg._data["tts_openai_voice"] = voice
            am.clear()          # the sample is the point; drop what's queued
            am.speak_scene(_TTS_TEST_PHRASE)
            # Give the background renderer time to read the voice before we put
            # the previous one back; speak_scene returns as soon as it starts.
            time.sleep(0.4)
        finally:
            if voice and voice != prev:
                _cfg._data["tts_openai_voice"] = prev

        self._send_json({"ok": True, "voice": voice or prev,
                         "text": _TTS_TEST_PHRASE})

    def _handle_button(self):
        """
        Inject a simulated MODE/ACTION button press — the web fallback for a
        device whose physical buttons are dead. Body:
        {"button": "mode"|"action"|"chord", "long": bool}.

        "chord" is both buttons held together (open/close volume mode). It has
        no long/short form: a page cannot hold two buttons, so the gesture is
        sent as one event.

        Stays OPEN on the LAN (not in _AUTH_REQUIRED_POSTS) for the same reason
        as the /collect endpoints: a non-technical pendamping drives this from
        their phone with no login, and /auth/token is localhost-only so a remote
        browser can't fetch a token anyway. The press is queued + handled on the
        orchestrator's SimBtn worker, so this returns immediately and can never
        block the HTTP thread (even during a slow NPU model reload).
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length)) if length else {}
            which      = str(data.get("button", "")).strip().lower()
            long_press = bool(data.get("long", False))
            if which not in ("mode", "action", "chord"):
                self._send_json(
                    {"error": "button must be 'mode', 'action' or 'chord'"}, 400)
                return
            queued = self.orch.simulate_button(which, long_press)
            self.logger.info(
                f"Web button: {which} ({'long' if long_press else 'short'}) "
                f"{'queued' if queued else 'DROPPED'}",
                module="WebServer",
            )
            self._send_json({
                "ok":     queued,
                "button": which,
                "long":   long_press,
                "queued": queued,
            })
        except Exception as e:
            self._send_error(e)

    # ── Mode PIMNAS operator page (/pimnas) ───────────────────────────────────
    # A second person (in the audience, on a phone that is also the device's
    # hotspot) watches and steers a live demo. Everything here is LAN-only
    # plain HTTP on purpose: the cloud app needs the venue's internet, and an
    # HTTPS page cannot reach the device at all.
    #
    # OPEN on the LAN like /button and /dengar — the hotspot is the operator's
    # own phone, and /auth/token is localhost-only so a phone could never hold
    # a token anyway.

    # Dev/maintenance work that has no place on a stage and that would load the
    # single-core board (or take the camera away) mid-demo.
    _EVENT_LOCKED_POSTS = {
        "/collect/mode", "/collect/start",
        "/benchmark/run", "/stress/start", "/suite/start",
    }

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _handle_pimnas(self, path: str):
        from config import cfg as _cfg
        from utils.speech_presets import presets, PresetError
        data = self._read_json_body()
        am = getattr(self.orch, "audio_manager", None)
        store = presets()
        try:
            if path == "/pimnas/event":
                on = bool(data.get("on"))
                _cfg.update({"event_mode": on})
                self.logger.info(f"Mode PIMNAS {'ON' if on else 'OFF'}",
                                 module="WebServer")
                self._send_json({"ok": True, "event_mode": on})

            elif path == "/pimnas/presets":
                if am is None:
                    self._send_json({"error": "Audio belum siap."}, 503)
                    return
                entry = store.add(data.get("text"), am.render_text_pcm)
                self.logger.info(f"Preset added ({entry['source']}): "
                                 f"{entry['text']}", module="WebServer")
                self._send_json({"ok": True, "preset": entry})

            elif path == "/pimnas/presets/play":
                pid = str(data.get("id", ""))
                pcm = store.pcm(pid)
                item = store.get(pid) if pcm else None
                if not pcm or item is None:
                    self._send_json({"error": "Tombol tidak ditemukan."}, 404)
                    return
                if am is None:
                    self._send_json({"error": "Audio belum siap."}, 503)
                    return
                # Like a button press: what was queued is dropped so this plays
                # now, and detection alerts stay quiet until it has finished.
                am.clear()
                am.queue_pcm_bytes(pcm, item["text"], priority=_PRESET_PRIORITY,
                                   label="preset")
                self.orch.note_user_interaction(
                    float(item.get("seconds", 3)) + 1.5)
                self.logger.info(f"Preset played: {item['text']}",
                                 module="WebServer")
                self._send_json({"ok": True})

            elif path == "/pimnas/presets/delete":
                self._send_json({"ok": store.delete(str(data.get("id", "")))})

            elif path == "/pimnas/presets/move":
                try:
                    delta = int(data.get("delta", 0))
                except (TypeError, ValueError):
                    delta = 0
                self._send_json({"ok": store.move(str(data.get("id", "")), delta)})

            elif path == "/pimnas/mode":
                mode = str(data.get("mode", ""))
                if mode not in self.orch.MODES:
                    self._send_json({"error": "mode tidak dikenal"}, 400)
                    return
                self.orch.note_press("ponsel", "mode:" + mode)
                self.orch.set_pending_command("set_mode", {"mode": mode})
                self._send_json({"ok": True, "mode": mode})

            elif path == "/pimnas/describe":
                self.orch.note_press("ponsel", "describe")
                self.orch.set_pending_command("describe", {})
                self._send_json({"ok": True})

            elif path == "/pimnas/hush":
                if am is not None:
                    am.clear()
                self._send_json({"ok": True})

            elif path == "/pimnas/volume":
                try:
                    delta = int(data.get("delta", 0))
                except (TypeError, ValueError):
                    delta = 0
                vol = max(20, min(100, _cfg.AUDIO_VOLUME + delta))
                _cfg.update({"audio_volume": vol})
                if am is not None:
                    am.queue_cue("chime_press.wav", label="vol_test")
                self._send_json({"ok": True, "audio_volume": vol})

            elif path == "/pimnas/test-sound":
                if am is None:
                    self._send_json({"error": "Audio belum siap."}, 503)
                    return
                am.clear()
                am.queue_system("isora_siap_digunakan")
                self._send_json({"ok": True})

            else:
                self._send_404()
        except PresetError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_error(e, context="pimnas")

    def _serve_pimnas_check(self):
        """Pre-flight list for the operator, one row per thing that can sink a
        demo. Each row: {key, label, ok (True/False/None = info), detail}."""
        import socket
        from config import cfg as _cfg
        from utils.speech_presets import presets
        rows = []

        def row(key, label, ok, detail=""):
            rows.append({"key": key, "label": label, "ok": ok, "detail": detail})

        try:
            st = self.orch.get_status()
        except Exception:
            st = {}

        row("event", "Mode PIMNAS aktif (update & alat dev dikunci)",
            _cfg.EVENT_MODE, "" if _cfg.EVENT_MODE else "nyalakan saklar di atas")

        provider = _cfg.AI_PROVIDER
        host = {"openai": "api.openai.com",
                "gemini": "generativelanguage.googleapis.com",
                "claude": "api.anthropic.com"}.get(provider, "api.openai.com")
        key = {"openai": _cfg.OPENAI_API_KEY, "gemini": _cfg.GEMINI_API_KEY,
               "claude": _cfg.CLAUDE_API_KEY}.get(provider, "")
        row("ai_key", "Kunci AI (%s) terpasang" % provider, bool(key),
            "" if key else "deskripsi daring tidak akan jalan")
        t0 = time.monotonic()
        try:
            socket.create_connection((host, 443), timeout=3).close()
            ms = int((time.monotonic() - t0) * 1000)
            row("internet", "Internet ke server AI", ms < 1500,
                "%d ms%s" % (ms, "" if ms < 1500 else " — lambat"))
        except OSError as e:
            row("internet", "Internet ke server AI", False,
                "tidak tersambung (%s) — fitur luring tetap jalan"
                % e.__class__.__name__)

        year = time.localtime().tm_year
        row("clock", "Jam alat benar", year >= 2026,
            time.strftime("%d %b %Y %H:%M") if year >= 2026
            else "tahun %d — HTTPS akan gagal" % year)

        bat = st.get("battery")
        if isinstance(bat, (int, float)):
            row("battery", "Baterai", bat >= 40, "%d%%" % bat)
        else:
            row("battery", "Baterai", None, "tidak terbaca")

        temp = st.get("temperature")
        if isinstance(temp, (int, float)):
            row("temp", "Suhu prosesor", temp < 75, "%.0f °C" % temp)

        vol = _cfg.AUDIO_VOLUME
        row("volume", "Volume cukup keras untuk ruangan", vol >= 70, "%d%%" % vol)

        mode = st.get("mode", "")
        if mode == "idle":
            row("camera", "Kamera", None, "mati di mode diam (wajar)")
        else:
            eng = getattr(self.orch, "ai_engine", None)
            cam = eng is not None and getattr(eng, "_cam", None) is not None
            row("camera", "Kamera", cam,
                "" if cam else "tidak terbuka — coba ganti mode")

        am = getattr(self.orch, "audio_manager", None)
        try:
            have = am is not None and am._find_wav("koneksi lambat") is not None
        except Exception:
            have = False
        row("audio", "Suara luring terpasang", have,
            "" if have else "jalankan tools/deploy.py --audio-only")

        n = len(presets().list())
        row("presets", "Tombol suara siap", True if n else None,
            "%d tombol" % n if n else "belum ada")

        self._send_json({"rows": rows, "time": time.time()})

    # ── Listen on the phone (/dengar) ──────────────────────────────────────────
    # The phone plays every clip the device speaks, so a presentation (or a
    # user with Bluetooth earphones paired to their phone) is not stuck with
    # the device's small speaker. See core/phone_audio.py for the design and
    # its fail-safe: a phone that stops polling expires within seconds and the
    # device speaker takes over again.
    #
    # Stays OPEN on the LAN like /button: the page is opened by whoever holds
    # the phone, with no login. What it exposes is what the speaker already
    # says out loud, and the one thing it can change (silencing the device
    # speaker) only lasts while that phone keeps polling.

    @staticmethod
    def _query(path: str) -> dict:
        from urllib.parse import parse_qs
        q = path.split("?", 1)
        return {k: v[-1] for k, v in parse_qs(q[1]).items()} if len(q) == 2 else {}

    @staticmethod
    def _listen_client(raw: str) -> str:
        raw = (raw or "")[:40]
        return raw if raw and all(c.isalnum() or c == "-" for c in raw) else ""

    def _serve_listen_poll(self):
        from core.phone_audio import phone_audio
        q = self._query(self.path)
        client = self._listen_client(q.get("client", ""))
        if not client:
            self._send_json({"error": "client id required"}, 400)
            return
        try:
            since = int(q.get("since", "-1"))
        except ValueError:
            since = -1
        mute = q.get("mute", "1") != "0"
        result = phone_audio.poll(client, since, mute)
        result["device_muted"] = phone_audio.device_muted()
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_listen_clip(self, name: str):
        from core.phone_audio import phone_audio
        stem = name[:-4] if name.endswith(".wav") else name
        data = phone_audio.clip(int(stem)) if stem.isdigit() else None
        if data is None:
            self._send_json({"error": "clip expired"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "no-store")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _handle_listen_leave(self):
        from core.phone_audio import phone_audio
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, json.JSONDecodeError):
            data = {}
        client = self._listen_client(str(data.get("client", "")))
        if client:
            phone_audio.leave(client)
        self._send_json({"ok": bool(client)})

    # ── Brand toggle (I-Sora ⇄ AuralAI white-label) ─────────────────────────────
    # Hidden feature: a long-press on the /buttons logo flips the device's spoken
    # identity + web UI name between the two brands (same software). The switch
    # copies the selected greeting set from /root/audio/brand/<brand>/ over the
    # canonical isora_menyala.* / isora_siap_digunakan.* names that the boot
    # cue (main.py) and AudioManager resolve, then persists cfg["brand"].
    #
    # Stays OPEN on the LAN (not in _AUTH_REQUIRED_POSTS), like /button: it is a
    # cosmetic demo toggle driven from the same page with no login, and must keep
    # working even if the /auth/token fetch flakes at the venue. It writes only
    # the brand key + two greeting files — no auth/identity/secret material.
    _BRANDS = ("auralai", "isora")
    # greeting kind -> canonical active filename stem in AUDIO_DIR
    _BRAND_FILES = {
        "menyala":        "isora_menyala",
        "siap_digunakan": "isora_siap_digunakan",
    }

    def _apply_brand(self, brand):
        """Copy the <brand> greeting set over the canonical names + persist
        cfg["brand"]. Returns (ok: bool, error: str|None). Never raises."""
        import shutil
        from config import cfg as _cfg
        if brand not in self._BRANDS:
            return False, "unknown brand: %s" % brand
        base = os.path.realpath(_cfg.AUDIO_DIR)
        src_dir = os.path.join(base, "brand", brand)
        copied = 0
        for kind, canon in self._BRAND_FILES.items():
            got = set()
            for ext in ("wav", "pcm"):
                src = os.path.join(src_dir, "%s.%s" % (kind, ext))
                if not os.path.exists(src):
                    continue
                dst = os.path.join(base, "%s.%s" % (canon, ext))
                try:
                    tmp = dst + ".tmp"
                    shutil.copyfile(src, tmp)
                    os.replace(tmp, dst)   # atomic swap of the active greeting
                    copied += 1
                    got.add(ext)
                except OSError as e:
                    return False, "copy %s.%s: %s" % (kind, ext, e)
            # A brand that ships only .wav would otherwise leave the PREVIOUS
            # brand's .pcm in place — and nothing would ever regenerate it:
            # _ensure_pcm short-circuits on `if os.path.exists(pcm)`, and the
            # fast boot cue in main.py reads the .pcm directly. The UI would say
            # one brand while the device audibly greets with the other. Drop the
            # stale derived file so it is rebuilt from the new .wav on next play.
            if "wav" in got and "pcm" not in got:
                try:
                    os.remove(os.path.join(base, "%s.pcm" % canon))
                except OSError:
                    pass
        if copied == 0:
            return False, "no audio for brand '%s' (looked in %s)" % (brand, src_dir)
        _cfg.update({"brand": brand})
        return True, None

    def _handle_brand(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            data = {}
        from config import cfg as _cfg
        cur = _cfg.get("brand", "isora")
        req = str(data.get("brand", "")).strip().lower()
        # Explicit valid brand → set it; otherwise toggle to the other one.
        target = req if req in self._BRANDS else ("auralai" if cur == "isora" else "isora")
        ok, err = self._apply_brand(target)
        if not ok:
            self.logger.error("Brand switch failed: %s" % err)
            self._send_json({"ok": False, "error": err, "brand": cur}, 500)
            return
        # Audible confirmation: play the freshly-activated "<brand> siap
        # digunakan" greeting so the (blind) user hears which brand is now active.
        try:
            am = getattr(self.orch, "audio_manager", None)
            if am:
                am.queue_cue("isora_siap_digunakan.wav")
        except Exception:
            pass
        self.logger.info("Brand switched: %s -> %s" % (cur, target),
                         module="WebServer")
        self._send_json({"ok": True, "brand": target})

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
            # Which mode the device stands in at power-on. Rejected rather
            # than coerced: a typo silently becoming "idle" would look like the
            # setting simply doesn't work, and the pendamping setting it is the
            # one person who cannot see the device's screen to check.
            if "boot_mode" in data:
                from core.orchestrator import Orchestrator
                allowed = list(Orchestrator.MODES) + ["last"]
                if data["boot_mode"] not in allowed:
                    self._send_json({
                        "error": "invalid boot_mode",
                        "allowed": allowed,
                        "hint": "mode saat perangkat dinyalakan, atau 'last'",
                    }, 400)
                    return
            if "scene_verbosity" in data and data["scene_verbosity"] not in ("sedang", "detail"):
                self._send_json({
                    "error": "invalid scene_verbosity",
                    "allowed": ["sedang", "detail"],
                }, 400)
                return
            # Which cloud voice renders free-form speech. Rejected rather than
            # coerced for the same reason as boot_mode: a typo falling back to
            # the slow backend looks exactly like "the setting does nothing".
            if "tts_provider" in data and data["tts_provider"] not in ("auto", "gtts", "openai"):
                self._send_json({
                    "error": "invalid tts_provider",
                    "allowed": ["auto", "gtts", "openai"],
                    "hint": "auto = openai kalau ada API key, kalau tidak gtts",
                }, 400)
                return
            # Voice name is sent straight to the TTS API; a typo would come back
            # as an HTTP 400 per describe and read to the user as "the device
            # stopped talking", so reject it here where we can say why.
            if "tts_openai_voice" in data and data["tts_openai_voice"] not in _OPENAI_VOICES:
                self._send_json({
                    "error": "invalid tts_openai_voice",
                    "allowed": sorted(_OPENAI_VOICES),
                }, 400)
                return
            # Vision sampling temperature. Clamped rather than rejected: the
            # same key also arrives via the cloud config push, which does no
            # validation, and every provider answers an out-of-range value with
            # an HTTP 400 — a describe press that just says "gagal menganalisis".
            if "ai_temperature" in data:
                try:
                    temp = float(data["ai_temperature"])
                except (TypeError, ValueError):
                    self._send_json({
                        "error": "invalid ai_temperature",
                        "hint":  "kirim angka 0.0 - 2.0 (0 = jawaban paling konsisten)",
                    }, 400)
                    return
                data["ai_temperature"] = max(0.0, min(2.0, temp))
            # Online-navigation photo interval (seconds). Clamped, like the gap
            # slider: the same key also arrives from the cloud push, and
            # Config.SCAN_INTERVAL_S clamps again at the read site.
            if "scan_interval_s" in data:
                try:
                    iv = int(round(float(data["scan_interval_s"])))
                except (TypeError, ValueError, OverflowError):
                    self._send_json({
                        "error": "invalid scan_interval_s",
                        "hint": "kirim jumlah detik, 3 - 60",
                    }, 400)
                    return
                data["scan_interval_s"] = max(3, min(60, iv))
            # Per-word audio cache toggle ("caching per-kata" vs "satu blok audio").
            if "word_cache_enabled" in data:
                data["word_cache_enabled"] = bool(data["word_cache_enabled"])
            # Inter-word gap slider (ms). <0 overlaps words (smoother), >0 inserts
            # silence. Clamp to a sane band so the slider can't wedge playback.
            if "word_cache_gap_ms" in data:
                try:
                    gap = int(data["word_cache_gap_ms"])
                except (TypeError, ValueError):
                    self._send_json({
                        "error": "invalid word_cache_gap_ms",
                        "hint": "kirim bilangan bulat milidetik",
                    }, 400)
                    return
                data["word_cache_gap_ms"] = max(-60, min(60, gap))
            # Word-count cap for concat mode (0 = disabled). Clamp to a sane
            # band so a bad value can't silently wedge every describe onto
            # the slow synth path (too low) or defeat the point of the cap
            # (absurdly high).
            if "word_cache_max_words" in data:
                try:
                    mw = int(data["word_cache_max_words"])
                except (TypeError, ValueError):
                    self._send_json({
                        "error": "invalid word_cache_max_words",
                        "hint": "kirim bilangan bulat jumlah kata (0 = nonaktif)",
                    }, 400)
                    return
                data["word_cache_max_words"] = max(0, min(40, mw))
            # Camera orientation. Snapped to a quarter turn rather than
            # rejected: the value reaches image.rotate() on the AI loop's hot
            # path, and the same key also arrives via the cloud config push,
            # which does no validation at all.
            if "camera_rotation" in data:
                from utils.orientation import VALID_ROTATIONS
                try:
                    deg = int(data["camera_rotation"])
                except (TypeError, ValueError):
                    deg = None
                # Wrap (so -90 and 450 are accepted as 270 and 90) but do NOT
                # snap: silently turning a typo'd 45 into 0 would leave the
                # camera sideways while the UI reports it fixed.
                rot = None if deg is None else deg % 360
                if rot not in VALID_ROTATIONS:
                    self._send_json({
                        "error": "invalid camera_rotation",
                        "allowed": list(VALID_ROTATIONS),
                        "hint": "derajat searah jarum jam: 0, 90, 180, atau 270",
                    }, 400)
                    return
                data["camera_rotation"] = rot
            if "setup_completed" in data:
                # One-way latch. COMPLETING setup here is the whole point of
                # _BOOTSTRAP_OPEN_POSTS — the pendamping finishes the wizard from
                # a phone with no token. CLEARING it is the opposite: it puts
                # /config, /ai-settings, /ai-settings/test, /ai-settings/secure
                # and /presets/apply back on the unauthenticated open list, so a
                # single leaked LAN token (and /auth/token answers any RFC1918
                # peer) would buy a standing bypass that outlives rotating that
                # token. Nothing in the UI ever sends false — the wizard stays
                # reachable at /setup regardless — so refuse the direction
                # outright. Re-opening setup is a factory-reset-grade action and
                # belongs out-of-band, by editing /root/config.json over SSH.
                if not bool(data["setup_completed"]):
                    self._send_json({
                        "error": "forbidden",
                        "hint":  "setup_completed tidak bisa dibatalkan lewat "
                                 "/config; ubah /root/config.json lewat SSH",
                    }, 403)
                    return
                data["setup_completed"] = True
            # Speaker volume reaches player.volume() on every playback, in a
            # blind user's ear. Clamped here as well as in Config.AUDIO_VOLUME so
            # a bad value is rejected at the edge rather than silently corrected
            # on every read.
            if "audio_volume" in data:
                try:
                    vol = int(data["audio_volume"])
                except (TypeError, ValueError):
                    self._send_json({
                        "error": "invalid audio_volume",
                        "hint":  "kirim bilangan bulat 0-100",
                    }, 400)
                    return
                data["audio_volume"] = max(0, min(100, vol))
            # device_name becomes the mDNS `.local` label — keep it DNS-safe.
            # Empty ("") is allowed: it reverts to the auto "isora-<id>" default.
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
            # Security: POST /config is a general tuning endpoint AND is open
            # pre-setup for the wizard (see _BOOTSTRAP_OPEN_POSTS). It must never
            # write auth/identity/secret material — those belong to dedicated,
            # authenticated flows (/ai-settings, /ai-settings/secure) or are set
            # out-of-band. Strip protected keys so neither an unauthenticated
            # bootstrap client nor a plain token holder can seize the device
            # (device_token / auth_required), disable the key lock, or overwrite
            # encrypted keys here.
            _PROTECTED = {
                "device_token", "auth_required", "api_keys_locked",
                "cloud_device_secret", "admin_role_token", "device_privkey_enc",
                # Which relay the device trusts for pairing and config pushes.
                # Pointing it elsewhere hands that relay the device.
                "cloud_base_url", "cloud_device_id", "device_pubkey",
                # Who may read this device's camera from a browser.
                "cors_allowed_origins",
            }
            blocked = [k for k in list(data)
                       if k in _PROTECTED
                       or k.endswith("_api_key_enc") or k.endswith("_api_key")]
            for k in blocked:
                data.pop(k, None)
            if blocked:
                self.logger.warn(
                    f"POST /config ignored protected keys: {blocked}",
                    module="WebServer")
            cfg.update(data)
            # Apply a new orientation to the live camera immediately — the
            # helper re-clips the device and watches the preview come out the
            # right way up. The engine picks it up on its own thread; every
            # camera call has to stay off this HTTP thread.
            if "camera_rotation" in data:
                try:
                    engine = getattr(self.orch, "ai_engine", None)
                    if engine is not None:
                        engine.request_orientation_reload()
                except Exception:
                    pass
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
        # Don't leak secrets via /config — this endpoint is UNAUTHENTICATED and
        # served with permissive CORS, so redact EVERY secret-bearing field, not
        # just the three plaintext API keys: the cloud device secret, the admin
        # role token, and any encrypted-key / private-key blobs must be masked too.
        def _is_secret(k):
            return (k.endswith("_token") or k.endswith("_secret")
                    or k.endswith("_enc") or "api_key" in k or "privkey" in k)
        for k in list(data.keys()):
            if _is_secret(k) and data.get(k):
                v = str(data[k])
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

    def _read_body_json(self):
        """Read and JSON-parse the request body; {} on empty/invalid."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def _handle_i2c_probe(self):
        if not self._auth_ok():
            self._send_json(
                {"error": "unauthorized", "hint": "X-Auth-Token required"}, 401)
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
        from config import cfg, _DEFAULTS
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
            "ai_timeout_s":  data.get("ai_timeout_s", _DEFAULTS["ai_timeout_s"]),
            "openai_model":  data.get("openai_model", _DEFAULTS["openai_model"]),
            "openai_key_set":  _has("openai"),
            "openai_key_hint": _masked("openai_api_key"),
            "openai_key_status": _enc_status("openai"),
            "gemini_model":  data.get("gemini_model", _DEFAULTS["gemini_model"]),
            "gemini_key_set":  _has("gemini"),
            "gemini_key_hint": _masked("gemini_api_key"),
            "gemini_key_status": _enc_status("gemini"),
            "claude_model":  data.get("claude_model", _DEFAULTS["claude_model"]),
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
                "<title>Halaman tidak ditemukan — I-Sora</title>"
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
        handler = partial(IsoraHandler, self.orch, self.logger, self.data_collector)
        # ThreadingHTTPServer: a slow handler (e.g. /snapshot during AI engine
        # reload) no longer blocks unrelated polls. Daemon threads die with
        # the server on shutdown.
        server = ThreadingHTTPServer((self.host, self.port), handler)
        server.daemon_threads = True
        self.logger.ok(f"Web server listening on {self.host}:{self.port}")
        server.serve_forever()
