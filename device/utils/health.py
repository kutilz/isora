"""
System health reader + HealthMonitor daemon.
Reads hardware metrics from /proc and /sys (no external deps).

Battery support is optional: probed once at import time via I2C.
If no battery HAT is detected, battery_info() returns {} and all
battery-related audio warnings are silently disabled.
"""

import os
import time
import threading
from typing import Callable, Optional

# ─── I2C battery HAT probe ───────────────────────────────────────────────────
# Attempt to detect a common battery gauge IC (INA219 @ 0x40, MAX17043 @ 0x36,
# or generic HAT @ 0x41/0x36) on /dev/i2c-1 or /dev/i2c-2.
# One write + read is enough; we don't need a valid response.

def _probe_i2c_battery() -> bool:
    """
    Probe I2C bus for a battery gauge IC (INA219 @ 0x40, MAX17043 @ 0x36).
    Read-only: opens device and reads 1 byte to confirm presence.
    Call manually via POST /i2c-probe; not called at import time.
    """
    import fcntl
    I2C_SLAVE = 0x0703
    candidates = [("/dev/i2c-1", 0x36), ("/dev/i2c-1", 0x40),
                  ("/dev/i2c-2", 0x36), ("/dev/i2c-2", 0x40)]
    for dev, addr in candidates:
        if not os.path.exists(dev):
            continue
        try:
            with open(dev, "rb", buffering=0) as f:
                fcntl.ioctl(f, I2C_SLAVE, addr)
                f.read(1)
            return True
        except Exception:
            continue
    return False


def battery_hat_present() -> bool:
    """True if I2C battery HAT was enabled via /i2c-probe endpoint."""
    try:
        from config import cfg as _cfg
        return _cfg.I2C_BATTERY_ENABLED
    except Exception:
        return False


def battery_info() -> dict:
    """
    Return battery metrics if a HAT is present, else empty dict.
    Real implementation requires a HAT-specific driver; this stub
    returns a placeholder so callers can check `if battery_info()`.
    """
    if not _BATTERY_HAT_PRESENT:
        return {}
    # TODO: implement HAT-specific register reads (INA219, MAX17043, etc.)
    return {"present": True}


# ─── Raw sysfs readers ────────────────────────────────────────────────────────

def _read(path: str, default: str = "") -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _thermals() -> dict:
    temps = {}
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return temps
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        raw = _read(os.path.join(base, entry, "temp"))
        if raw:
            zone_type = _read(os.path.join(base, entry, "type")) or entry
            try:
                temps[zone_type] = round(int(raw) / 1000, 1)
            except ValueError:
                pass
    return temps


def _meminfo() -> dict:
    result = {}
    for line in _read("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                result[parts[0].rstrip(":")] = int(parts[1])
            except ValueError:
                pass
    return result


def _loadavg() -> list:
    raw = _read("/proc/loadavg")
    try:
        parts = raw.split()
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        return [0.0, 0.0, 0.0]


def _uptime() -> float:
    raw = _read("/proc/uptime")
    try:
        return float(raw.split()[0])
    except Exception:
        return 0.0


def _cpu_freq_mhz() -> int:
    for p in (
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
        "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq",
    ):
        raw = _read(p)
        if raw:
            try:
                return int(raw) // 1000
            except ValueError:
                pass
    return 0


def _disk_free_mb(path: str = "/") -> int:
    try:
        s = os.statvfs(path)
        return (s.f_bavail * s.f_frsize) // (1024 * 1024)
    except Exception:
        return 0


def _disk_total_mb(path: str = "/") -> int:
    try:
        s = os.statvfs(path)
        return (s.f_blocks * s.f_frsize) // (1024 * 1024)
    except Exception:
        return 0


def get_health() -> dict:
    """Return all hardware metrics as a single dict."""
    thermals   = _thermals()
    mem        = _meminfo()
    total_kb   = mem.get("MemTotal", 0)
    avail_kb   = mem.get("MemAvailable", mem.get("MemFree", 0))
    total_mb   = total_kb // 1024
    avail_mb   = avail_kb // 1024
    used_pct   = round((1 - avail_mb / total_mb) * 100) if total_mb else 0
    disk_free  = _disk_free_mb()
    disk_total = _disk_total_mb()
    disk_pct   = round((1 - disk_free / disk_total) * 100) if disk_total else 0
    cpu_temp   = max(thermals.values()) if thermals else 0.0
    uptime_s   = int(_uptime())
    h, rem     = divmod(uptime_s, 3600)
    m          = rem // 60

    return {
        "cpu_temp_c":    cpu_temp,
        "thermals":      thermals,
        "ram_total_mb":  total_mb,
        "ram_free_mb":   avail_mb,
        "ram_used_pct":  used_pct,
        "disk_free_mb":  disk_free,
        "disk_total_mb": disk_total,
        "disk_used_pct": disk_pct,
        "load_avg":      _loadavg(),
        "uptime_s":      uptime_s,
        "uptime_str":    f"{h}j {m:02d}m",
        "cpu_freq_mhz":  _cpu_freq_mhz(),
    }


# ─── HealthMonitor ────────────────────────────────────────────────────────────

class HealthMonitor:
    """
    Background daemon polling hardware every poll_interval_s seconds.

    Fires on_throttle(temp_c) when CPU temp exceeds throttle_temp_c,
    and on_recover(temp_c) when it drops back below.
    Both callbacks run in the monitor thread — keep them short.
    """

    def __init__(self, throttle_temp_c: float = 80.0,
                 poll_interval_s: float = 5.0):
        self._throttle_temp   = throttle_temp_c
        self._poll_interval   = poll_interval_s
        self._throttling      = False
        self._snapshot: dict  = {}
        self._lock            = threading.Lock()
        self._stop            = threading.Event()
        self._on_throttle: Optional[Callable] = None
        self._on_recover:  Optional[Callable] = None
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="HealthMonitor"
        )

    def start(self,
              on_throttle: Optional[Callable] = None,
              on_recover:  Optional[Callable] = None):
        self._on_throttle = on_throttle
        self._on_recover  = on_recover
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    @property
    def is_throttling(self) -> bool:
        with self._lock:
            return self._throttling

    def update_throttle_temp(self, temp_c: float):
        with self._lock:
            self._throttle_temp = temp_c

    def _loop(self):
        while not self._stop.wait(self._poll_interval):
            snap     = get_health()
            cpu_temp = snap.get("cpu_temp_c", 0.0)

            with self._lock:
                was_throttling  = self._throttling
                now_throttling  = bool(cpu_temp > 0 and cpu_temp > self._throttle_temp)
                self._throttling = now_throttling
                self._snapshot   = snap

            if now_throttling and not was_throttling and self._on_throttle:
                try:
                    self._on_throttle(cpu_temp)
                except Exception:
                    pass
            elif not now_throttling and was_throttling and self._on_recover:
                try:
                    self._on_recover(cpu_temp)
                except Exception:
                    pass
