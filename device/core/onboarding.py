"""
Spoken-URL onboarding for the screen-less assistive device.

The MaixCAM's screen is removed — the user is blind and the only outputs are the
speaker (TTS) and the single button. After WiFi is up and the web server is
listening, the device speaks how to reach its dashboard. The button repeats the
announcement (short press) or acknowledges it (long press, which silences further
nagging). All announcements are gated so they only run during first-time setup;
a returning, already-provisioned device just speaks a short "ready" cue on boot.

Reuses the existing TTS pipeline (utils/tts → AudioManager) — no new audio path.
"""

import socket
import threading
import time

from config import cfg
from core.audio_manager import NORMAL


class OnboardingAnnouncer:
    def __init__(self, orchestrator, logger):
        self.orch = orchestrator
        self.logger = logger
        # Cloud pairing: when active, the spoken prompt is the pairing code (via
        # the web hub) instead of the local LAN URL. Set by core/cloud.py.
        self.cloud_active = False
        self.pairing_code = None

    # ─── gating ───────────────────────────────────────────────────────────────

    def _should_nag(self) -> bool:
        # In Mode Ambil Data the device skips all setup — never nag about the URL.
        if bool(cfg.get("data_collection_mode", False)):
            return False
        return (
            bool(cfg.get("url_announce_enabled", True))
            and not bool(cfg.get("setup_completed", False))
            and not bool(cfg.get("url_ack", False))
        )

    # ─── announce / acknowledge ───────────────────────────────────────────────

    def announce(self, force: bool = False):
        """Speak the onboarding phrase. force=True bypasses the gate (button repeat).

        Speaks the cloud pairing code when cloud pairing is active and a code is
        available; otherwise falls back to the local LAN URL phrase.
        """
        if not force and not self._should_nag():
            return
        am = getattr(self.orch, "audio_manager", None)
        if am is None:
            return
        try:
            if self.cloud_active and self.pairing_code:
                from utils.identity import pairing_phrase
                text = pairing_phrase(self.pairing_code, cfg.get("cloud_base_url", ""))
                label = "onboard_pair"
            else:
                from utils.identity import onboarding_phrase
                text = onboarding_phrase(port=int(cfg.get("web_port", 8080)))
                label = "onboard_url"
        except Exception as e:
            self.logger.warn(f"onboarding phrase failed: {e}", module="Onboard")
            return
        am.queue(text, priority=NORMAL, label=label, cooldown=3.0)

    def set_pairing_code(self, code: str, speak: bool = True):
        """core/cloud.py calls this once it has a fresh code to announce."""
        self.cloud_active = True
        self.pairing_code = code
        if speak:
            self.announce(force=True)

    def announce_paired(self):
        """core/cloud.py calls this when the device gets claimed by an account."""
        self.cloud_active = False
        self.pairing_code = None
        am = getattr(self.orch, "audio_manager", None)
        if am is not None:
            am.queue("Perangkat sudah terhubung.", priority=NORMAL,
                     label="onboard_paired", cooldown=0)

    def acknowledge(self):
        """User long-pressed 'understood' — stop re-announcing the URL."""
        try:
            cfg.update({"url_ack": True})
        except Exception:
            pass
        am = getattr(self.orch, "audio_manager", None)
        if am is not None:
            am.queue("Baik, sudah paham.", priority=NORMAL,
                     label="onboard_ack", cooldown=0)
        self.logger.info("Onboarding URL acknowledged by user", module="Onboard")

    # ─── boot wait loop ───────────────────────────────────────────────────────

    def wait_and_announce_on_boot(self):
        """Daemon: wait for WiFi+web (+audio), then announce; re-nag a few minutes."""
        deadline = time.monotonic() + 180.0     # allow WiFi up to 3 min to connect
        ready = False
        while self.orch._running and time.monotonic() < deadline:
            if self._web_ready() and self._has_ip():
                ready = True
                break
            time.sleep(1.0)
        if not ready:
            self.logger.warn(
                "Boot announce skipped — WiFi/web not ready in time", module="Onboard")
            return

        # The AudioManager is built by the AI thread; wait briefly for it.
        am = getattr(self.orch, "audio_manager", None)
        waited = 0.0
        while am is None and waited < 15.0 and self.orch._running:
            time.sleep(0.5)
            waited += 0.5
            am = getattr(self.orch, "audio_manager", None)

        # Mode Ambil Data: no setup, no "ready" cue — the orchestrator already
        # announces "Mode ambil data aktif" and capture auto-starts.
        if bool(cfg.get("data_collection_mode", False)):
            self.logger.info("Onboarding skipped — Mode Ambil Data", module="Onboard")
            return

        # When cloud pairing is enabled, core/cloud.py owns first-boot
        # announcements (pairing code, or local-URL fallback if cloud is
        # unreachable). Skip the local nag here to avoid double-speaking.
        if bool(cfg.get("cloud_enabled", True)):
            self.logger.info("Onboarding deferred to cloud client", module="Onboard")
            return

        if self._should_nag():
            try:
                self._prewarm()      # synth once now that internet is up
            except Exception:
                pass
            self.announce()
            nag_until = time.monotonic() + 300.0   # re-nag for ~5 min
            while self.orch._running and time.monotonic() < nag_until:
                time.sleep(60.0)
                if self._should_nag():
                    self.announce()
                else:
                    break
        elif am is not None:
            am.queue_cue("chime_ready.wav")
            am.queue("AuralAI siap digunakan.", priority=NORMAL,
                     label="boot_ready", cooldown=0)

    # ─── readiness helpers ────────────────────────────────────────────────────

    def _web_ready(self) -> bool:
        try:
            with socket.create_connection(
                ("127.0.0.1", int(cfg.get("web_port", 8080))), 0.5):
                return True
        except OSError:
            return False

    def _has_ip(self) -> bool:
        try:
            from utils.identity import current_ip
            return bool(current_ip())
        except Exception:
            return False

    def _prewarm(self):
        """Pre-synthesize the phrase so the first announcement isn't delayed."""
        from utils.identity import onboarding_phrase
        from utils.tts import get_or_synthesize
        text = onboarding_phrase(port=int(cfg.get("web_port", 8080)))
        get_or_synthesize(
            text, cache_dir=cfg.get("tts_cache_dir", "/root/audio/tts_cache"))
