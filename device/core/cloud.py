"""
Cloud client — pairs the device to the I-Sora web hub and pulls config.

Runs as a daemon thread. Flow (all over outbound HTTPS, so it works behind any
home router without port-forwarding):

  1. Wait for internet, then ensure a cloud identity (id + secret + E2E keypair).
  2. register() with the relay (uploads the E2E public key).
  3. If unpaired: request a short pairing code and have the onboarding announcer
     speak it. Refresh before it expires; re-speak periodically.
  4. Long-poll for config commands; decrypt E2E secrets; apply to config; ACK.
  5. Heartbeat status periodically (mode, wifi, battery — never the camera feed).

Offline-safe: if the cloud is unreachable, it falls back to the local spoken-URL
setup (utils/identity.onboarding_phrase via the announcer) and keeps retrying.

Stdlib HTTP only (urllib) so it runs on MaixPy without extra packages. E2E
secret decryption needs `cryptography` (see utils/crypto_box); without it,
non-secret config still applies and API keys fall back to local setup.
"""

import json
import secrets as pysecrets
import threading
import time
import urllib.error
import urllib.request

from config import cfg
from core.audio_manager import NORMAL
from utils import crypto_box

FW_VERSION = "device-1.0"

# Plain (non-secret) config keys the cloud is allowed to set. Anything else in a
# pushed command is ignored — the web cannot rewrite arbitrary device internals.
ALLOWED_CONFIG_KEYS = {
    "ai_provider", "ai_timeout_s",
    "openai_model", "openai_reasoning_effort", "gemini_model", "claude_model",
    "audio_mode", "audio_volume",
    # Mount orientation. Safe to push unvalidated: Config.CAMERA_ROTATION
    # normalizes at the read site, so a junk value degrades to "normal".
    "camera_rotation",
    "device_name", "prompt_scene", "prompt_scene_sedang", "prompt_qris",
    # Which prompt the describe button uses, and how deterministic the
    # decoding is. Both are safe to push unvalidated: Config.AI_TEMPERATURE
    # clamps at the read site, and select_scene_prompt falls back to the
    # detailed prompt for any verbosity string it does not recognize.
    "scene_verbosity", "ai_temperature",
    # Online-navigation photo interval. Safe unvalidated: Config.SCAN_INTERVAL_S
    # clamps it to 3-60 s at the read site.
    "scan_interval_s",
    "qris_mode", "tts_enabled", "url_announce_enabled",
    "setup_completed",
}

# Secret config keys delivered E2E-encrypted; stored encrypted-at-rest on apply.
SECRET_KEYS = {"openai_api_key", "gemini_api_key", "claude_api_key"}

def _ai_key_present() -> bool:
    """Does the provider the device is actually set to use have a key?

    Reported (as a bool, never the key) so the web app can say "deskripsi
    suasana belum aktif" instead of letting someone discover it by pressing the
    button outdoors and hearing nothing useful.
    """
    provider = (cfg.AI_PROVIDER or "openai").lower()
    try:
        if provider == "gemini":
            return bool(cfg.GEMINI_API_KEY)
        if provider == "claude":
            return bool(cfg.CLAUDE_API_KEY)
        return bool(cfg.OPENAI_API_KEY)
    except Exception:
        return False


CODE_REFRESH_S = 8 * 60      # request a new code before the 10-min TTL expires
ANNOUNCE_EVERY_S = 60        # re-speak the code roughly this often while unpaired
HEARTBEAT_EVERY_S = 20


class CloudClient:
    def __init__(self, orchestrator, logger, announcer=None):
        self.orch = orchestrator
        self.logger = logger
        self.announcer = announcer
        self._running = True
        self.cloud_ok = False           # last register/heartbeat reachable?
        self._code = None
        self._code_at = 0.0
        self._last_announce = 0.0
        self._last_hb = 0.0
        self._paired = bool(cfg.PAIRED)
        self._last_qr_token = None
        self._last_qr_at = 0.0
        self._confirm_busy = False      # an ACTION-press confirm is in flight
        self._confirm_at = 0.0

    def stop(self):
        self._running = False

    # ─── HTTP ──────────────────────────────────────────────────────────────────

    def _headers(self, auth: bool = False) -> dict:
        h = {"Content-Type": "application/json"}
        if auth:
            h["X-Device-Id"] = cfg.get("cloud_device_id", "")
            h["X-Device-Secret"] = cfg.get("cloud_device_secret", "")
        return h

    def _req(self, method, path, body=None, auth=False, timeout=15):
        url = f"{cfg.CLOUD_BASE_URL}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(auth), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                payload = json.loads(raw) if raw else None
                return r.status, payload
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, None
        except Exception:
            return 0, None      # network error / timeout

    # ─── identity ──────────────────────────────────────────────────────────────

    def _ensure_identity(self):
        patch = {}
        if not cfg.get("cloud_device_id"):
            patch["cloud_device_id"] = pysecrets.token_hex(8)
        if not cfg.get("cloud_device_secret"):
            patch["cloud_device_secret"] = pysecrets.token_hex(32)
        if patch:
            cfg.update(patch)
        try:
            # Logged because the regeneration is invisible otherwise, and the
            # symptom it cures ("every API key I send is ignored") is one of the
            # hardest things to diagnose from the outside.
            status = crypto_box.keypair_status(cfg)
            if status == "unusable":
                self.logger.warn(
                    "E2E keypair unusable (private key can no longer be decrypted) "
                    "— regenerating; re-send the API key from the app",
                    module="Cloud",
                )
            crypto_box.ensure_keypair(cfg)
        except Exception as e:
            self.logger.warn(f"E2E keypair unavailable: {e}", module="Cloud")

    # ─── relay calls ───────────────────────────────────────────────────────────

    def _register(self):
        st, resp = self._req("POST", "/api/devices/register", body={
            "device_id": cfg.get("cloud_device_id"),
            "secret": cfg.get("cloud_device_secret"),
            "pubkey": crypto_box.public_key_b64(cfg),
            "fw_version": FW_VERSION,
            "name": cfg.get("device_name") or "",
        })
        self.cloud_ok = st == 200
        if st == 200:
            return bool(resp and resp.get("paired"))
        return None

    def _request_code(self):
        st, resp = self._req("POST", "/api/pair/code", body={}, auth=True)
        if st == 200 and resp and resp.get("code"):
            self._code = resp["code"]
            self._code_at = time.monotonic()
            self.logger.info(f"Pairing code issued: {self._code}", module="Cloud")
            return self._code
        self.logger.warn(f"pair/code failed: {st}", module="Cloud")
        return None

    def _heartbeat(self):
        status = {}
        try:
            from utils.identity import current_ip
            _lan_ip = current_ip()
        except Exception:
            _lan_ip = ""
        try:
            status = self.orch.get_status() if hasattr(self.orch, "get_status") else {}
            status = {
                "mode": status.get("mode"),
                "wifi": status.get("wifi_ssid") or status.get("wifi"),
                "battery": status.get("battery"),
                "online": True,
                # Mode Ambil Data — lets the web hub show/diagnose the device
                # remotely while a helper is out collecting data.
                "data_collection_mode": status.get("data_collection_mode"),
                "capturing": status.get("capturing"),
                "capture_count": status.get("capture_count"),
                # First-run state. Pairing finishes the moment the ACTION
                # button is pressed, but the settings that follow are pushed
                # from a phone that may well close the page halfway. Without
                # these two the hub cannot tell "linked and ready" from
                # "linked and still waiting to be set up", and the person is
                # the one left guessing.
                "setup_completed": bool(status.get("setup_completed")),
                "ai_ready": _ai_key_present(),
                # Online navigation (explorer + ACTION): whether it is on, and
                # the interval the app's slider should start from.
                "scan_active": bool(status.get("scan_active")),
                "scan_interval_s": status.get("scan_interval_s"),
                # LAN entry points so the hub can deep-link /buttons and
                # /collect (only reachable from the same WiFi as the device).
                # Both are reported because neither works everywhere: Chrome on
                # Android does not resolve mDNS `.local` names, while the IP
                # moves whenever DHCP hands out a new lease.
                "local_url": (
                    f"http://{status.get('mdns_host')}:{cfg.get('web_port', 8080)}"
                    if status.get("mdns_host") else None
                ),
                "local_ip_url": (
                    f"http://{_lan_ip}:{cfg.get('web_port', 8080)}" if _lan_ip else None
                ),
            }
        except Exception:
            status = {"online": True}
        st, resp = self._req("POST", "/api/heartbeat", body={"status": status}, auth=True)
        self.cloud_ok = st == 200
        if st == 200 and resp:
            return bool(resp.get("paired"))
        return None

    def _poll_once(self):
        timeout = cfg.CLOUD_POLL_TIMEOUT_S
        st, resp = self._req(
            "GET", f"/api/poll?device_id={cfg.get('cloud_device_id')}",
            auth=True, timeout=timeout + 10,
        )
        if st == 200 and resp and resp.get("command"):
            return resp["command"]
        return None

    def _ack(self, command_id):
        self._req("POST", "/api/ack", body={"command_id": command_id}, auth=True)

    # ─── apply pushed config ───────────────────────────────────────────────────

    def _apply_command(self, cmd):
        payload = cmd.get("payload", {}) or {}
        config = payload.get("config", {}) or {}
        secrets = payload.get("secrets", {}) or {}
        patch = {}

        for k, v in config.items():
            if k in ALLOWED_CONFIG_KEYS:
                patch[k] = v

        if secrets and not cfg.get("api_keys_locked", False):
            try:
                from utils.secure_keys import encrypt as enc_at_rest
            except Exception:
                enc_at_rest = None
            for name, sealed in secrets.items():
                if name not in SECRET_KEYS:
                    continue
                value = crypto_box.unseal(cfg, sealed)
                if not value:
                    self.logger.warn(f"secret {name}: decrypt failed/skipped", module="Cloud")
                    continue
                if enc_at_rest:
                    patch[f"{name}_enc"] = enc_at_rest(value)
                    patch[name] = ""        # don't keep plaintext alongside
                else:
                    patch[name] = value
                self.logger.info(f"secret {name}: applied", module="Cloud")

        if patch:
            cfg.update(patch)
            if "camera_rotation" in patch:
                # Same live re-apply POST /config does — a rotation pushed from
                # the hub should not wait for the next reboot to take effect.
                try:
                    engine = getattr(self.orch, "ai_engine", None)
                    if engine is not None:
                        engine.request_orientation_reload()
                except Exception:
                    pass
            self.logger.ok(f"Applied cloud config: {sorted(patch.keys())}", module="Cloud")
        self._ack(cmd.get("id"))

    # ─── announce helpers ──────────────────────────────────────────────────────

    def _announce_code(self):
        # Mode Ambil Data: keep pairing/heartbeat working silently (so the device
        # still shows up on the hub for diagnosis) but don't speak setup prompts.
        if cfg.get("data_collection_mode", False):
            self._last_announce = time.monotonic()
            return
        if self.announcer is not None and self._code:
            try:
                self.announcer.set_pairing_code(self._code, speak=True)
            except Exception as e:
                self.logger.warn(f"announce code failed: {e}", module="Cloud")
        self._last_announce = time.monotonic()

    def _fallback_local_announce(self):
        """Cloud unreachable — fall back to the local spoken-URL onboarding."""
        if cfg.get("data_collection_mode", False):
            return
        if self.announcer is not None and not cfg.SETUP_COMPLETED:
            try:
                self.announcer.cloud_active = False
                self.announcer.announce(force=True)
            except Exception:
                pass

    def _on_paired(self):
        self._paired = True
        cfg.update({"paired": True})
        self.logger.ok("Device paired to an account", module="Cloud")
        if self.announcer is not None:
            try:
                self.announcer.announce_paired()
            except Exception:
                pass

    def _on_unpaired(self):
        """The relay says nobody owns this device any more — believe it.

        Someone tapped "Lepaskan perangkat" in the app. Without this the device
        keeps `paired` forever: wants_button_pair() stays False, an ACTION press
        never offers to pair again, and the only way back is editing
        config.json over SSH — which is not something the person wearing the
        glasses can do. The device keeps working exactly as before; it just
        becomes pairable again, and says so.
        """
        self._paired = False
        cfg.update({"paired": False})
        self._code = None
        self._code_at = 0.0
        self._last_announce = 0.0
        self.logger.warn("Device released by its owner — pairable again", module="Cloud")
        if self.announcer is not None and not cfg.get("data_collection_mode", False):
            try:
                # force=True because the onboarding gate is closed once setup is
                # done — yet this is the one moment a set-up device genuinely
                # needs to repeat "press the button to connect".
                self.announcer.announce(force=True)
            except Exception:
                pass

    # ─── button pairing ────────────────────────────────────────────────────────

    def wants_button_pair(self) -> bool:
        """True while an ACTION press should be read as 'pair me'."""
        return bool(cfg.CLOUD_ENABLED) and not self._paired

    def confirm_pairing(self):
        """
        The person holding the device pressed ACTION — tell the relay to link it
        to whoever is waiting (see web/app/api/pair/confirm).

        Called from the button thread, so the HTTP round-trip runs on a throwaway
        thread: a GPIO handler that blocks for the request timeout would swallow
        every press made while it waits.
        """
        if not self.wants_button_pair():
            return
        now = time.monotonic()
        # One press in flight at a time, and ignore a bounce/impatient re-press
        # while the previous answer is still coming back.
        if self._confirm_busy or now - self._confirm_at < 2.0:
            return
        self._confirm_busy = True
        self._confirm_at = now
        threading.Thread(target=self._confirm_worker, daemon=True, name="PairBtn").start()

    def _confirm_worker(self):
        try:
            st, resp = self._req("POST", "/api/pair/confirm", body={}, auth=True)
            if st == 200 and resp and resp.get("ok"):
                self.logger.ok("Paired via button press", module="Cloud")
                self._on_paired()
                return
            # 0 means the request never left the device — that is "no internet"
            # to the person holding it, not "nobody is waiting".
            reason = "offline" if st == 0 else ((resp or {}).get("reason") or "failed")
            self.logger.warn(f"Button pair rejected: {st} ({reason})", module="Cloud")
            if self.announcer is not None:
                try:
                    self.announcer.announce_pair_result(reason)
                except Exception:
                    pass
        finally:
            self._confirm_busy = False

    # ─── camera QR pairing ─────────────────────────────────────────────────────

    def wants_qr_scan(self) -> bool:
        """True while the device should watch the camera for a pairing QR."""
        return cfg.CLOUD_ENABLED and self.cloud_ok and not self._paired

    def on_qr_payload(self, payload: str):
        """Called by the AI loop with a decoded QR. Acts only on I-Sora tokens."""
        if not payload or not payload.startswith("auralai-pair:"):
            return
        token = payload[len("auralai-pair:"):].strip()
        if not token:
            return
        # de-dupe: don't hammer the same scanned token
        now = time.monotonic()
        if token == self._last_qr_token and now - self._last_qr_at < 10.0:
            return
        self._last_qr_token = token
        self._last_qr_at = now
        self._submit_scan(token)

    def _submit_scan(self, token: str):
        st, resp = self._req("POST", "/api/pair/scan", body={"token": token}, auth=True)
        if st == 200 and resp and resp.get("paired"):
            self.logger.ok("Paired via camera QR", module="Cloud")
            self._on_paired()
        else:
            self.logger.warn(f"QR pair rejected: {st}", module="Cloud")

    # ─── main loop ─────────────────────────────────────────────────────────────

    def run(self):
        if not cfg.CLOUD_ENABLED:
            self.logger.info("Cloud disabled — skipping cloud client", module="Cloud")
            return

        # Wait for internet (utils.identity.current_ip), up to ~3 min.
        from utils.identity import current_ip
        deadline = time.monotonic() + 180.0
        while self._running and not current_ip() and time.monotonic() < deadline:
            time.sleep(2.0)
        if not current_ip():
            self.logger.warn("No internet — cloud client falling back to local setup", module="Cloud")
            self._fallback_local_announce()
            # keep trying in the background
        self._ensure_identity()

        announced_fallback = False

        while self._running:
            # 1. Make sure we're registered / reachable.
            reg = self._register()
            if reg is None:
                # Cloud unreachable: fall back to local announcement once, retry later.
                if not announced_fallback and not self._paired:
                    self._fallback_local_announce()
                    announced_fallback = True
                time.sleep(15.0)
                continue
            announced_fallback = False
            if reg and not self._paired:
                self._on_paired()
            elif reg is False and self._paired:
                self._on_unpaired()

            # 2. Unpaired → keep a fresh code spoken (camera-QR pairing runs in
            #    parallel via the AI loop: wants_qr_scan() / on_qr_payload()).
            if not self._paired:
                need_new = (self._code is None) or (
                    time.monotonic() - self._code_at > CODE_REFRESH_S
                )
                if need_new and self._request_code():
                    self._announce_code()
                elif self._code and time.monotonic() - self._last_announce > ANNOUNCE_EVERY_S:
                    self._announce_code()

            # 3. Heartbeat (also reports paired transitions).
            if time.monotonic() - self._last_hb > HEARTBEAT_EVERY_S:
                hb = self._heartbeat()
                self._last_hb = time.monotonic()
                if hb and not self._paired:
                    self._on_paired()
                elif hb is False and self._paired:
                    self._on_unpaired()

            # 4. Long-poll for a command (blocks up to the poll window).
            cmd = self._poll_once()
            if cmd:
                try:
                    self._apply_command(cmd)
                except Exception as e:
                    self.logger.warn(f"apply command failed: {e}", module="Cloud")
            elif self._paired:
                # Paired & idle: gentle pacing so we don't hammer when poll is short.
                time.sleep(2.0)
