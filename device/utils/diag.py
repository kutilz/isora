"""
Field diagnostics: "[diag] <kind> key=value ..." lines in the normal log.

Each kind exists because a real complaint could not be answered from the logs:

  ai_call         "why did that take 21 s?" Only a total was logged, so the model,
                  the link and the device could not be told apart.
  net_probe       the link and CPU at the moment a call is slow, not minutes later.
  root_ro         the SD card failed twice on isora-iiot; the app kept running on a
                  read-only root and nothing said so.
  sample          once a minute: WiFi, ping, memory, SD counters.
  speech_dropped  a sentence went silent with only "[Audio fallback]" to show for it.
  tts_failed/late gTTS errors were swallowed; a timeout looked like a failure.
  listen_*        phone audio going quiet, or coming out of the speaker first.
  prev_run        how the last run ended: a clean stop, or cut off mid-line.
  frame           every photo sent to the AI, only with debug_save_frames: a session
                  that could have been reviewed left no photos behind.
  press_*         ACTION presses, and those lost to the one pending-command slot.

Everything here is best effort. A diagnostic must never take the device down, so
every reader returns a neutral value on failure. Nothing here logs an API key.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time

_logger = None

SAMPLE_EVERY_S = 60.0
ROOT_CHECK_EVERY_S = 15.0
_MAX_VALUE_CHARS = 120
_ANY_INTERNET_HOST = "1.1.1.1"
_LOG_NAME = re.compile(r"^isora_(\d{5})_\d{8}_\d{6}\.log$")


def _fmt(value) -> str:
    if isinstance(value, float):
        value = round(value, 2)
    text = str(value)[:_MAX_VALUE_CHARS]
    return json.dumps(text, ensure_ascii=False) if (" " in text or not text) else text


def event(kind: str, level: str = "info", **fields) -> None:
    log = _logger
    if log is None:
        return
    body = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items() if v is not None)
    try:
        getattr(log, level)(f"[diag] {kind} {body}".rstrip(), module="Diag")
    except Exception:
        pass


# ─── Readers ─────────────────────────────────────────────────────────────────

def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _run(cmd: list, timeout_s: float = 4.0) -> str:
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout_s, universal_newlines=True,
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def root_mode(mounts_path: str = "/proc/mounts") -> str:
    """"rw" or "ro" for the root filesystem, "?" when it cannot be told."""
    for line in _read(mounts_path).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "/":
            options = parts[3].split(",")
            if "ro" in options:
                return "ro"
            if "rw" in options:
                return "rw"
    return "?"


def ext4_errors(base: str = "/sys/fs/ext4/mmcblk0p2") -> dict:
    """The filesystem's own error record. It lives in the superblock, so unlike
    dmesg it survives the reboot that follows a card failure."""
    found = {}
    for name in ("errors_count", "first_error_time", "last_error_time"):
        value = _read(os.path.join(base, name))
        if value:
            found[name] = value
    return found


def sd_counters(path: str = "/sys/block/mmcblk0/stat") -> dict:
    """Completed reads and writes, requests in flight, and ms the card was busy."""
    parts = _read(path).split()
    if len(parts) < 10:
        return {}
    return {"sd_rd": parts[0], "sd_wr": parts[4], "sd_inflight": parts[8],
            "sd_busy_ms": parts[9]}


def sd_kernel_errors(max_lines: int = 12) -> list:
    pattern = re.compile(r"I/O error|error -\d+|EXT4-fs error|Remounting|CMD\d+ timeout")
    return [l for l in _run(["dmesg"]).splitlines() if pattern.search(l)][-max_lines:]


def parse_iw_link(text: str) -> dict:
    found = {}
    for pattern, key in ((r"SSID: (.+)", "ssid"), (r"signal: (-?\d+)", "dbm"),
                         (r"rx bitrate: ([\d.]+)", "rx_mbit"),
                         (r"tx bitrate: ([\d.]+)", "tx_mbit")):
        match = re.search(pattern, text)
        if match:
            found[key] = match.group(1).strip()
    return found


def gateway(route_path: str = "/proc/net/route") -> str:
    for line in _read(route_path).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            try:
                raw = int(parts[2], 16)
            except ValueError:
                continue
            return ".".join(str((raw >> s) & 0xff) for s in (0, 8, 16, 24))
    return ""


def parse_ping_ms(text: str):
    match = re.search(r"time=([\d.]+)", text)
    return float(match.group(1)) if match else None


def _ping(host: str):
    """Round trip in ms, or "lost". None when there is nothing to ping."""
    if not host:
        return None
    ms = parse_ping_ms(_run(["ping", "-c", "1", "-W", "2", host]))
    return "lost" if ms is None else ms


def _cpu_times() -> tuple:
    parts = _read("/proc/stat").split("\n")[0].split()[1:8]
    try:
        values = [int(p) for p in parts]
        return sum(values), values[3] + values[4]
    except (ValueError, IndexError):
        return 0, 0


def cpu_busy_pct(before: tuple, after: tuple):
    total = after[0] - before[0]
    return round(100.0 * (1 - (after[1] - before[1]) / total)) if total > 0 else None


def _mem_avail_mb():
    match = re.search(r"MemAvailable:\s+(\d+)", _read("/proc/meminfo"))
    return int(match.group(1)) // 1024 if match else None


def _load1():
    parts = _read("/proc/loadavg").split()
    return parts[0] if parts else None


def link_snapshot() -> dict:
    snapshot = parse_iw_link(_run(["iw", "dev", "wlan0", "link"]))
    snapshot["gw_ms"] = _ping(gateway())
    snapshot["net_ms"] = _ping(_ANY_INTERNET_HOST)
    return snapshot


# ─── Probe while something is slow ───────────────────────────────────────────

_probe_lock = threading.Lock()


def net_probe(reason: str) -> None:
    """Record the link and CPU right now, off the caller's thread. One at a time:
    a burst of slow calls needs one answer, not a pile of ping processes."""
    if not _probe_lock.acquire(blocking=False):
        return

    def _work():
        try:
            before = _cpu_times()
            snapshot = link_snapshot()
            event("net_probe", reason=reason, cpu_pct=cpu_busy_pct(before, _cpu_times()),
                  load=_load1(), mem_mb=_mem_avail_mb(), root=root_mode(), **snapshot)
        finally:
            _probe_lock.release()

    threading.Thread(target=_work, daemon=True, name="DiagProbe").start()


# ─── AI calls ────────────────────────────────────────────────────────────────

def header(resp, name: str):
    """A response header, or None. Test doubles may not carry headers at all."""
    headers = getattr(resp, "headers", None)
    return headers.get(name) if headers is not None else None


def ai_call(provider: str, started: float, ok: bool, server_ms=None, **fields) -> None:
    """One cloud call. net_s is everything the model's own clock did not cover:
    the upload, the link, the provider's front door, and the download."""
    total = time.monotonic() - started
    server_s = None
    if server_ms is not None:
        try:
            server_s = int(server_ms) / 1000.0
        except (TypeError, ValueError):
            pass
    event("ai_call", level="info" if ok else "warn", provider=provider, ok=ok,
          total_s=total, server_s=server_s,
          net_s=None if server_s is None else total - server_s, **fields)


# ─── Every photo sent to the AI (off unless debug_save_frames) ───────────────

FRAMES_DIR = "/root/captures/debug"
FRAMES_RAM_DIR = "/tmp/isora_frames"
FRAMES_INDEX = "index.jsonl"
_FRAMES_RAM_MAX = 40        # RAM is 128 MB; only here is anything ever evicted
_FRAMES_MIN_FREE_MB = 100   # a full card breaks the speech cache and the logs
_frames_lock = threading.Lock()


def _free_mb(path: str) -> float:
    return shutil.disk_usage(path).free / (1024 * 1024)


def _write_durably(path: str, data: bytes, mode: str) -> None:
    # The device is switched off by pulling power.
    with open(path, mode) as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _store(filename: str, data: bytes, mode: str, directory: str, ram_directory: str) -> None:
    """The SD card first. A read-only or full card must not cost the photos of
    the session that exposed it, so those go to RAM until the next reboot."""
    with _frames_lock:
        try:
            os.makedirs(directory, exist_ok=True)
            if _free_mb(directory) < _FRAMES_MIN_FREE_MB:
                raise OSError("card nearly full")
            _write_durably(os.path.join(directory, filename), data, mode)
            return
        except OSError as e:
            card_error = e
        try:
            os.makedirs(ram_directory, exist_ok=True)
            _write_durably(os.path.join(ram_directory, filename), data, mode)
            photos = sorted(n for n in os.listdir(ram_directory) if n.endswith(".jpg"))
            for old in photos[:max(0, len(photos) - _FRAMES_RAM_MAX)]:
                os.remove(os.path.join(ram_directory, old))
            event("frame_in_ram", level="warn", file=filename, err=card_error)
        except OSError as e:
            event("frame_not_saved", level="error", file=filename, err=e)


def _background(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="DiagFrame").start()


def save_frame(jpeg: bytes, cfg, kind: str = "konteks", directory: str = FRAMES_DIR,
               ram_directory: str = FRAMES_RAM_DIR, _spawn=None) -> str:
    """Keep a photo for evaluation, before the AI sees it, so a failed call keeps
    its photo too. Nothing on the card is ever deleted. It can show people, so it
    stays off by default. Returns the name to hand to frame_result()."""
    if not jpeg or not cfg.get("debug_save_frames", False):
        return ""
    now = time.time()
    name = "%s_%03d_%s.jpg" % (time.strftime("%Y%m%d_%H%M%S", time.localtime(now)),
                               int(now * 1000) % 1000, kind)
    (_spawn or _background)(lambda: _store(name, jpeg, "wb", directory, ram_directory))
    event("frame", name=name, bytes=len(jpeg))
    return name


def frame_result(name: str, text, ok: bool = True, directory: str = FRAMES_DIR,
                 ram_directory: str = FRAMES_RAM_DIR, _spawn=None) -> None:
    """Pair a saved photo with what the AI answered, before any filtering."""
    if not name:
        return
    line = json.dumps({"photo": name, "ok": ok, "text": str(text)},
                      ensure_ascii=False).encode("utf-8") + b"\n"
    (_spawn or _background)(lambda: _store(FRAMES_INDEX, line, "ab", directory, ram_directory))


# ─── How the last run ended ──────────────────────────────────────────────────

def previous_run(log_dir: str) -> dict:
    """Read the last line of the log before this run's own.

    A last line of "Shutdown requested" or "SDK stopped" is a deliberate stop. Anything else means
    the run was cut off: power, the watchdog, a crash, or a dying card.
    """
    try:
        names = sorted(n for n in os.listdir(log_dir) if _LOG_NAME.match(n))
    except OSError:
        return {}
    if len(names) < 2:
        return {}
    path = os.path.join(log_dir, names[-2])
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            lines = f.read().decode("utf-8", "replace").strip().splitlines()
        last = json.loads(lines[-1])
    except (OSError, ValueError, IndexError):
        return {"file": names[-2], "clean": False, "last": "unreadable"}
    msg = str(last.get("msg", ""))
    return {"file": names[-2], "clean": "Shutdown requested" in msg or "SDK stopped" in msg,
            "last_ts": last.get("ts"), "last_up": last.get("up"),
            "last": str(last.get("msg", ""))[:80]}


def _boot_summary(cfg) -> None:
    # Two units behaved differently on 3 Nov and the reason was their settings.
    version = _read(os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION"))
    event("boot", version=version, ai=cfg.get("ai_provider"), model=cfg.get("openai_model"),
          effort=cfg.get("openai_reasoning_effort"), ai_timeout_s=cfg.get("ai_timeout_s"),
          slow_warn_s=cfg.get("ai_slow_warn_s"), verbosity=cfg.get("scene_verbosity"),
          tts=cfg.get("tts_provider"), pack=cfg.get("prompt_pack_version"),
          audio=cfg.get("audio_mode"), frames=cfg.get("debug_save_frames"),
          root=root_mode(), **ext4_errors())


# ─── Background sampler ──────────────────────────────────────────────────────

class Sampler:
    """Watches the root mount every 15 s (a procfs read) and writes one fuller
    sample a minute. A sample spawns iw and ping, so it stays that rare."""

    def __init__(self, sample_every_s: float = SAMPLE_EVERY_S,
                 read_root=root_mode, read_link=link_snapshot):
        self._sample_every_s = sample_every_s
        self._read_root = read_root
        self._read_link = read_link
        self._root = None
        self._ssid = None
        self._cpu = _cpu_times()
        self._next_sample = time.monotonic() + ROOT_CHECK_EVERY_S

    def check_root(self) -> None:
        mode = self._read_root()
        if mode != self._root:
            if mode == "ro":
                event("root_ro", level="error", was=self._root, **ext4_errors())
                for line in sd_kernel_errors():
                    event("sd_kernel", level="error", line=line)
            elif self._root is not None:
                event("root_mode", was=self._root, now=mode)
            self._root = mode

    def sample(self) -> None:
        link = self._read_link()
        ssid = link.get("ssid")
        if ssid != self._ssid:
            if self._ssid is not None:
                event("wifi_changed", level="warn", was=self._ssid, now=ssid or "none")
            self._ssid = ssid
        cpu = _cpu_times()
        event("sample", cpu_pct=cpu_busy_pct(self._cpu, cpu), load=_load1(),
              mem_mb=_mem_avail_mb(), root=self._root, **sd_counters(), **link)
        self._cpu = cpu

    def tick(self) -> None:
        self.check_root()
        if self._sample_every_s > 0 and time.monotonic() >= self._next_sample:
            self._next_sample = time.monotonic() + self._sample_every_s
            self.sample()


def start(logger, cfg, log_dir: str) -> None:
    """Hook the log up now; do everything slower on a daemon thread, off the boot."""
    global _logger
    _logger = logger
    try:
        sample_every_s = float(cfg.get("diag_sample_s", SAMPLE_EVERY_S))
    except (TypeError, ValueError):
        sample_every_s = SAMPLE_EVERY_S
    sampler = Sampler(sample_every_s=sample_every_s)

    def _loop():
        try:
            run = previous_run(log_dir)
            if run:
                event("prev_run", level="info" if run.get("clean") else "warn", **run)
            _boot_summary(cfg)
        except Exception:
            pass
        while True:
            try:
                sampler.tick()
            except Exception:
                pass
            time.sleep(ROOT_CHECK_EVERY_S)

    threading.Thread(target=_loop, daemon=True, name="Diag").start()
