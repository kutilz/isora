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
            if self.cloud_active:
                # The button prompt, not the code: see identity.pairing_button_phrase.
                # A code may well be in hand (cloud.py still mints one as a
                # fallback), but reciting six characters at someone who then has
                # to type them is exactly the friction this replaced.
                from utils.identity import pairing_button_phrase
                text = pairing_button_phrase(cfg.get("cloud_base_url", ""))
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
        """core/cloud.py calls this once it has a fresh code in hand.

        The code itself is no longer spoken — what `speak` triggers is the button
        prompt (see announce). The code is kept so the hub's typed-code path
        still resolves for a device whose ACTION button is broken.
        """
        self.cloud_active = True
        self.pairing_code = code
        if speak:
            self.announce(force=True)

    # Spoken answers to an ACTION press while unpaired. Keyed by the `reason`
    # core/cloud.py gets back from /api/pair/confirm, so the person holding the
    # device learns what happened without looking at anything.
    PAIR_REPLIES = {
        "no_session": "Belum ada ponsel yang menunggu. Buka halaman tambah perangkat dulu, lalu tekan lagi.",
        "ambiguous": "Ada lebih dari satu ponsel yang menunggu. Tutup salah satunya, lalu tekan lagi.",
        "already_paired": "Perangkat ini sudah terhubung.",
        "offline": "Belum ada internet. Sambungkan perangkat ke WiFi dulu.",
    }

    def announce_pair_result(self, reason: str):
        """core/cloud.py calls this when a button press did not pair the device."""
        am = getattr(self.orch, "audio_manager", None)
        if am is None:
            return
        text = self.PAIR_REPLIES.get(reason)
        if not text:
            text = "Gagal menghubungkan. Coba tekan lagi."
        am.queue(text, priority=NORMAL, label=f"pair_{reason}", cooldown=0)

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

    def _cloud_owns_boot_prompt(self) -> bool:
        """True when core/cloud.py will speak the first words after boot.

        It does so only for a device that is unpaired AND not yet set up: the
        pairing prompt ("Isora siap. Untuk menghubungkan…") or, with the cloud
        unreachable, the local URL phrase ("Isora siap digunakan. …") — both
        open with the greeting. In every other state it says nothing at boot,
        and deferring to it left a paired unit, or a set-up one with no cloud,
        silent after "menghubungkan ke wifi" on every single boot.
        """
        return (bool(cfg.get("cloud_enabled", True))
                and not bool(cfg.get("paired", False))
                and not bool(cfg.get("setup_completed", False)))

    def wait_and_announce_on_boot(self):
        """Daemon: say the device is ready (or, first time, how to set it up).

        The ready greeting waits only for the app itself (web server + audio),
        never for WiFi: navigation, banknotes and QRIS all work offline, and a
        unit at a venue with no network used to stay silent after "menghubungkan
        ke wifi" for good. Only the setup prompts, which are about the network,
        still wait for an IP.
        """
        deadline = time.monotonic() + 60.0
        while (self.orch._running and time.monotonic() < deadline
               and not self._web_ready()):
            time.sleep(0.5)

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

        cloud_prompt = self._cloud_owns_boot_prompt()
        local_prompt = (not bool(cfg.get("cloud_enabled", True))) and self._should_nag()
        if cloud_prompt or local_prompt:
            deadline = time.monotonic() + 180.0     # allow WiFi up to 3 min
            while (self.orch._running and time.monotonic() < deadline
                   and not self._has_ip()):
                time.sleep(1.0)
            if not self._has_ip():
                # No network for the setup prompt — still say it is usable.
                self.logger.warn("No WiFi for the setup prompt — ready greeting only",
                                 module="Onboard")
                self._greet(am)
                return
            if cloud_prompt:
                self.logger.info("Onboarding deferred to cloud client", module="Onboard")
                return

        if local_prompt:
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
        else:
            self._greet(am)

    def _greet(self, am):
        if am is None:
            self.logger.warn("No audio for the ready greeting", module="Onboard")
            return
        am.queue_cue("chime_ready.wav")
        am.queue("Isora siap digunakan.", priority=NORMAL,
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
