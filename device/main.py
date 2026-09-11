"""
I-Sora SDK — Entry Point
Run on MaixCAM via MaixVision or: python main.py

Threads:
  AILoop        — camera → NPU inference → audio queue
  WebServer     — HTTP dashboard + API
  Watchdog      — module health monitor (restarts crashed components)
  HealthMonitor — hardware telemetry → adaptive power governor
  BtnListener   — GPIO mode-cycle button (if configured)

Boot-time optimization (2025-06-23)
────────────────────────────────────
The original code imported ALL modules at the top of the file before main()
could even start. On the MaixCAM RISC-V this import chain takes ~6.7 seconds
(config: 2s, cloud: 2.5s, web_server: 0.8s, …). The boot chime could not
play until after those imports completed.

Fix: only import stdlib at the top. Play the boot chime FIRST using a minimal
PCM player (just os + maix.audio), then do the heavy imports while the sound
is already playing. Net effect: boot chime plays ~4-6 seconds earlier.

To revert: move the "# ── Deferred imports" block back to the top of the file
(before main()), remove the _boot_cue_fast function, and uncomment the original
_boot_cues block. See RC_BLOCK_LEGACY in tools/run.py for the rc.local revert.
"""

import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Freeze forensics ─────────────────────────────────────────────────────────
# The camera/NPU teardown is a C call that holds the GIL. When it blocks in the
# cvitek VI driver the ENTIRE interpreter stops — no log line, no heartbeat, no
# traceback, and the audio already handed to the DMA loops one phrase forever.
# faulthandler's handler runs at the C level and walks the interpreter state
# directly, so `kill -USR1 <pid>` still prints every thread's Python stack while
# the GIL is held. It is the only way to see where a freeze actually happened.
# Costs nothing until the signal arrives.
try:
    import faulthandler
    import signal as _signal
    _fh_log = open("/tmp/isora_faulthandler.log", "a", buffering=1)
    faulthandler.enable(file=_fh_log, all_threads=True)
    if hasattr(_signal, "SIGUSR1"):
        faulthandler.register(_signal.SIGUSR1, file=_fh_log,
                              all_threads=True, chain=False)
except Exception:
    pass

# ── NOTE: Heavy imports are deferred into main() — see docstring above. ──────


def _boot_cue_fast():
    """Play 'Isora menyala' the instant we boot, with minimal imports.

    Three cases, in order:

    1. PCM exists AND /tmp/.boot_chime_played is set → aplay (from rc.local)
       already played the chime this boot. Skip, to avoid double-play.
       rc.local only sets the flag when the PCM file is present (see RC_BLOCK in
       tools/run.py), so a set flag reliably means "aplay had something to play".
       tools/run.py clears the flag on a manual relaunch, so an app restart
       (no reboot) still replays the cue.

    2. PCM exists, flag NOT set → play it directly via maix.audio.Player.
       Fast path: <0.5s vs ~2.3s for the full audio_manager route, and no
       config.py import (volume is read straight from /root/config.json).

    3. PCM missing (fresh flash, deleted cache, or re-recorded WAV) → FALLBACK:
       regenerate it from isora_menyala.wav via play_wav_blocking(), which
       runs ffmpeg, caches the .pcm next to the WAV, and plays it. Slower and
       pulls in audio_manager, but only in this degraded case — and it is the
       ONLY path that recreates the PCM, so without it the cue would be silent
       forever once the cache is gone. The flag is ignored here because aplay
       cannot have played anything without the PCM.

    Any error → returns silently.
    """
    try:
        pcm_path = "/root/audio/isora_menyala.pcm"

        # Read volume from config.json directly (avoid importing config.py)
        vol = 80  # safe default
        try:
            import json
            with open("/root/config.json") as f:
                vol = json.load(f).get("audio_volume", 80)
        except Exception:
            pass

        # Case 3: PCM missing OR not built from the WAV sitting next to it →
        # regenerate (the only self-heal path). The mtime half matters after an
        # audio deploy: a fresh isora_menyala.wav sitting next to last
        # release's .pcm would otherwise greet with the OLD recording forever,
        # because this fast path never looks at the WAV at all.
        #
        # Same equality test as audio_manager._pcm_is_fresh, inlined because
        # this path must not import audio_manager (that is the whole point of
        # the fast path). A "pcm older than wav" test would call every cache
        # entry stale here: the clock reads 1970 until NTP lands, so a .pcm
        # rebuilt on a previous boot is stamped behind a WAV deployed in 2026.
        wav_path = "/root/audio/isora_menyala.wav"
        try:
            delta = os.path.getmtime(pcm_path) - os.path.getmtime(wav_path)
            pcm_stale = abs(delta) > 2.0
        except OSError:
            pcm_stale = False        # no WAV to compare against → leave it be
        if pcm_stale or not os.path.exists(pcm_path):
            try:
                from core.audio_manager import (
                    play_wav_blocking, _ensure_pcm_standalone,
                )
                if pcm_stale and os.path.exists("/tmp/.boot_chime_played"):
                    # S00a's aplay already greeted this boot — off the stale
                    # PCM, but playing a SECOND, different greeting on top of
                    # it is worse than one outdated one. Rebuild the cache
                    # quietly so the next boot is right, and stay silent now.
                    _ensure_pcm_standalone(wav_path)
                else:
                    play_wav_blocking("isora_menyala.wav", volume=vol)
            except Exception:
                pass
            return

        # Case 1: aplay already handled it this boot → skip to avoid double-play.
        if os.path.exists("/tmp/.boot_chime_played"):
            return

        # Case 2: fast direct play.
        from maix import audio as maix_audio
        with open(pcm_path, "rb") as f:
            pcm_data = f.read()
        player = maix_audio.Player()
        try:
            player.volume(vol)
        except Exception:
            pass
        player.play(bytes(pcm_data))
        # Wait for playback to finish: PCM bytes / (48000 Hz * 2 bytes/sample) + pad
        duration_s = len(pcm_data) / (48000 * 2) + 0.15
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            time.sleep(0.02)
    except Exception:
        pass  # Fast path failed silently


def _mark_boot_ready():
    """Record time-to-ready against the monotonic boot clock.

    The wall clock cannot measure boot: it starts at the epoch and NTP jumps it
    forward at an unpredictable point *during* boot, so two log timestamps can
    sit in different time bases and their difference is meaningless.
    /proc/uptime never jumps. Written where the user-visible milestone is --
    every thread up, the device about to announce itself -- and read back by
    tools/boot_timeline.py. Best-effort: a failure here must never affect boot.
    """
    try:
        with open("/proc/uptime") as f:
            uptime = f.read().split()[0]
        with open("/tmp/isora_boot_ready", "w") as f:
            f.write(uptime)
    except (OSError, IndexError):
        pass


def main():
    # ── Boot voice cue (IMMEDIATE — before heavy imports) ──────────────────────
    # Fire the "Isora menyala" sound the instant we enter main(), using a
    # minimal PCM player that doesn't need config.py or audio_manager.
    # This runs in a daemon thread so main() can proceed to imports in parallel.
    boot_cue_thread = threading.Thread(
        target=_boot_cue_fast, daemon=True, name="BootCueFast"
    )
    boot_cue_thread.start()

    # ── Deferred imports ──────────────────────────────────────────────────────
    # These are loaded HERE instead of at the top of the file so the boot cue
    # above can start playing while these ~6.7s of imports happen in parallel.
    # To revert: move these back above main() as top-level imports.
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

    # ── Logger ────────────────────────────────────────────────────────────────
    logger = Logger(
        log_path=cfg.LOG_PATH,
        max_lines=cfg.LOG_MAX_LINES,
    )
    logger.info("=" * 50, module="Main")
    logger.info("I-Sora SDK — Starting up", module="Main")
    logger.info("=" * 50, module="Main")

    # ── Second boot cue: "menghubungkan ke wifi" ──────────────────────────────
    # Played via the full audio_manager path (which is now imported).
    # The fast boot cue thread above handles "isora_menyala" — this one plays
    # the follow-up "connecting to wifi" message. Wait for the first cue to
    # finish so they don't overlap.
    def _boot_cue_wifi():
        boot_cue_thread.join(timeout=5.0)  # wait for "menyala" to finish
        from core.audio_manager import play_wav_blocking
        vol = cfg.get("audio_volume", 80)
        play_wav_blocking(
            "menghubungkan_ke_wifi.wav", audio_dir=cfg.AUDIO_DIR, volume=vol
        )

    threading.Thread(target=_boot_cue_wifi, daemon=True, name="BootCue").start()

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
    # Every sample feeds the power governor (not just threshold crossings): a
    # tiered plan with hysteresis has to see the trend to hold and release it.
    health.start(on_sample=orchestrator.on_health_sample)
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

    # ── SoC hardware watchdog ────────────────────────────────────────────────
    # Armed only when the unit opts in (cfg["hw_watchdog_enabled"]). This is
    # the ONLY mechanism that can recover the device from a camera/NPU teardown
    # that blocks inside a C call: that hang holds the GIL, so no Python
    # supervisor — including core/watchdog.py — ever runs again. Started after
    # the AI loop so there is a real heartbeat to judge, and fed from the
    # loop's own tick rather than from anything engine-specific, because idle
    # mode has no engine. See utils/hw_watchdog.py for why it defaults to off.
    from utils import hw_watchdog as _hw_watchdog
    _stale_s = cfg.get("hw_watchdog_stale_s", 45.0)
    hw_wd = _hw_watchdog.start_if_enabled(
        cfg, logger=logger,
        is_alive_fn=lambda: orchestrator.loop_healthy(_stale_s),
    )

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
    _mark_boot_ready()

    # Pre-warm the speech backend AFTER boot-ready is stamped, so its cost never
    # lands in the boot-latency number — and, more to the point, never lands on
    # the user's first describe. See AudioManager.warm_speech_stack.
    try:
        orchestrator.audio_manager.warm_speech_stack(delay_s=2.0)
    except Exception as e:
        logger.debug(f"Speech pre-warm not started: {e}", module="Main")

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
        # Disarm FIRST and with the magic close: a deliberate stop must not
        # leave the board to reset itself one timeout after we exit.
        if hw_wd is not None:
            hw_wd.stop(disarm=True)
        orchestrator.stop()
        watchdog.stop()
        health.stop()
        if mdns:
            mdns.stop()
        if cloud:
            cloud.stop()
        logger.info("I-Sora SDK stopped.", module="Main")


if __name__ == "__main__":
    main()
