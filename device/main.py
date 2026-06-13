"""
AuralAI SDK — Entry Point
Run on MaixCAM via MaixVision or: python main.py

Threads:
  AILoop        — camera → NPU inference → audio queue
  WebServer     — HTTP dashboard + API
  Watchdog      — module health monitor (restarts crashed components)
  HealthMonitor — hardware telemetry + thermal throttle
  BtnListener   — GPIO mode-cycle button (if configured)
"""

import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import cfg
from core.orchestrator import Orchestrator
from core.watchdog import Watchdog
from core.onboarding import OnboardingAnnouncer
from core.cloud import CloudClient
from server.web_server import WebServer
from utils.logger import Logger
from utils.health import HealthMonitor
from utils.identity import device_name, current_ip
from utils.mdns import MdnsPublisher
from modes.data_collection_mode import DataCollector


def main():
    # ── Logger ────────────────────────────────────────────────────────────────
    logger = Logger(
        log_path=cfg.LOG_PATH,
        max_lines=cfg.LOG_MAX_LINES,
    )
    logger.info("=" * 50, module="Main")
    logger.info("AuralAI SDK — Starting up", module="Main")
    logger.info("=" * 50, module="Main")

    # ── Boot voice cues (immediate, before any processing) ─────────────────────
    # Announce power-on the instant we boot so a helper can observe the device is
    # alive without waiting for WiFi/AI/web to come up. Runs in a daemon thread so
    # it never blocks the rest of startup; cues are pre-recorded + PCM-cached.
    def _boot_cues():
        from core.audio_manager import play_wav_blocking
        vol = cfg.get("audio_volume", 80)
        play_wav_blocking("auralai_menyala.wav", audio_dir=cfg.AUDIO_DIR, volume=vol)
        play_wav_blocking("menghubungkan_ke_wifi.wav", audio_dir=cfg.AUDIO_DIR, volume=vol)

    threading.Thread(target=_boot_cues, daemon=True, name="BootCue").start()

    # ── Orchestrator ──────────────────────────────────────────────────────────
    orchestrator = Orchestrator(logger=logger)

    # ── Watchdog ──────────────────────────────────────────────────────────────
    watchdog = Watchdog(check_interval_s=1.0)
    orchestrator.watchdog = watchdog
    watchdog.start()
    logger.ok("Watchdog started", module="Main")

    # ── Health Monitor ────────────────────────────────────────────────────────
    health = HealthMonitor(
        throttle_temp_c=cfg.THERMAL_THROTTLE_TEMP_C,
        poll_interval_s=5.0,
    )
    health.start(
        on_throttle=orchestrator._on_thermal_throttle,
        on_recover=orchestrator._on_thermal_recover,
    )
    logger.ok("HealthMonitor started", module="Main")

    # ── Data Collector ────────────────────────────────────────────────────────
    data_collector = DataCollector(logger=logger)
    # Share with the orchestrator so the AI loop can own the camera handoff when
    # toggling Mode Ambil Data on/off (exactly one of AIEngine/DataCollector
    # holds the camera at a time).
    orchestrator.data_collector = data_collector

    # ── Web Server ────────────────────────────────────────────────────────────
    web_server = WebServer(
        host=cfg.WEB_HOST,
        port=cfg.WEB_PORT,
        orchestrator=orchestrator,
        logger=logger,
        data_collector=data_collector,
    )
    threading.Thread(
        target=web_server.start,
        daemon=True,
        name="WebServer",
    ).start()
    logger.info(f"Web server → http://{cfg.WEB_HOST}:{cfg.WEB_PORT}", module="Main")

    # ── mDNS Publisher (after web binds, so :8080 exists) ─────────────────────
    mdns = None
    if cfg.MDNS_ENABLED:
        mdns = MdnsPublisher(
            logger=logger,
            port=cfg.WEB_PORT,
            name_provider=device_name,
            ip_provider=current_ip,
        )
        orchestrator.mdns = mdns
        threading.Thread(target=mdns.start, daemon=True, name="Mdns").start()
        logger.info(
            f"mDNS → http://{device_name()}.local:{cfg.WEB_PORT}", module="Main"
        )

    # ── AI Loop ───────────────────────────────────────────────────────────────
    threading.Thread(
        target=orchestrator.run_ai_loop,
        daemon=True,
        name="AILoop",
    ).start()
    logger.ok("AI loop started", module="Main")

    # ── Spoken-URL onboarding (last; waits for WiFi + web + audio) ─────────────
    announcer = OnboardingAnnouncer(orchestrator=orchestrator, logger=logger)
    orchestrator.onboarding = announcer
    threading.Thread(
        target=announcer.wait_and_announce_on_boot,
        daemon=True,
        name="Onboard",
    ).start()

    # ── Cloud client (pairing + config relay; offline-safe) ────────────────────
    cloud = None
    if cfg.CLOUD_ENABLED:
        cloud = CloudClient(orchestrator=orchestrator, logger=logger, announcer=announcer)
        orchestrator.cloud = cloud
        threading.Thread(target=cloud.run, daemon=True, name="Cloud").start()
        logger.info(f"Cloud client → {cfg.CLOUD_BASE_URL}", module="Main")

    logger.info("All threads running. Press Ctrl+C to stop.", module="Main")

    # ── Main thread: keep alive, handle shutdown ───────────────────────────────
    # Treat SIGTERM (from `kill` / tools/run.py --stop) like Ctrl+C so the camera
    # is released cleanly instead of leaking the VI channel (→ segfault on next start).
    import signal

    def _graceful_shutdown(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested", module="Main")
        orchestrator.stop()
        watchdog.stop()
        health.stop()
        if mdns:
            mdns.stop()
        if cloud:
            cloud.stop()
        logger.info("AuralAI SDK stopped.", module="Main")


if __name__ == "__main__":
    main()
