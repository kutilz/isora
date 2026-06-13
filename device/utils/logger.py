"""
Logger — Structured JSON logging to file + console.
Web UI stream via get_recent().

Adds:
  - exception(msg, module, exc=None) — error log with full traceback
  - log rotation at init: prunes files >7 days OR total dir >100MB
"""

import os
import json
import time
import threading
import traceback
from collections import deque


class Logger:
    LEVELS = {"debug": 0, "info": 1, "ok": 2, "warn": 3, "error": 4}
    _TAGS  = {"debug": "DBG", "info": "INF", "ok": "OK ", "warn": "WRN", "error": "ERR"}

    # Log retention policy (CG-5)
    MAX_AGE_DAYS  = 7
    MAX_TOTAL_MB  = 100

    def __init__(self, log_path: str = "/root/logs",
                 max_lines: int = 500, min_level: str = "info"):
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=max_lines)
        self._log_file = None
        self._min_level = self.LEVELS.get(min_level, 1)
        self._log_path = log_path
        self._rotate_old_logs(log_path)
        self._init_file(log_path)

    # ─── Log rotation (CG-5) ──────────────────────────────────────────────────

    def _rotate_old_logs(self, log_path: str):
        """Delete logs older than MAX_AGE_DAYS, then trim oldest until total <= MAX_TOTAL_MB."""
        try:
            if not os.path.isdir(log_path):
                return
            now      = time.time()
            cutoff   = now - self.MAX_AGE_DAYS * 86400
            max_bytes = self.MAX_TOTAL_MB * 1024 * 1024

            files = []
            for name in os.listdir(log_path):
                if not name.startswith("aural_") or not name.endswith(".log"):
                    continue
                full = os.path.join(log_path, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                files.append((full, st.st_mtime, st.st_size))

            # Pass 1: age-based cleanup
            kept = []
            for full, mtime, size in files:
                if mtime < cutoff:
                    try:
                        os.remove(full)
                    except OSError:
                        kept.append((full, mtime, size))
                else:
                    kept.append((full, mtime, size))

            # Pass 2: size-based cleanup (oldest first)
            kept.sort(key=lambda x: x[1])  # ascending mtime
            total = sum(size for _, _, size in kept)
            while total > max_bytes and kept:
                full, _, size = kept.pop(0)
                try:
                    os.remove(full)
                    total -= size
                except OSError:
                    break
        except Exception:
            pass

    def _init_file(self, log_path: str):
        try:
            os.makedirs(log_path, exist_ok=True)
            name = f"aural_{time.strftime('%Y%m%d_%H%M%S')}.log"
            self._log_file = open(os.path.join(log_path, name), "a", encoding="utf-8")
        except Exception:
            self._log_file = None

    def _log(self, level: str, msg: str, module: str = "", **extra):
        if self.LEVELS.get(level, 0) < self._min_level:
            return

        entry = {
            "ts":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            "level":  level,
            "module": module,
            "msg":    msg,
            **extra,
        }
        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            self._buffer.append(entry)
            if self._log_file:
                try:
                    self._log_file.write(line + "\n")
                    self._log_file.flush()
                except Exception:
                    pass

        tag = self._TAGS.get(level, "---")
        mod = f"[{module}] " if module else ""
        print(f"[{entry['ts']}] {tag} {mod}{msg}")

    def debug(self, msg: str, module: str = "", **kw): self._log("debug", msg, module, **kw)
    def info(self, msg: str, module: str = "", **kw):  self._log("info",  msg, module, **kw)
    def ok(self, msg: str, module: str = "", **kw):    self._log("ok",    msg, module, **kw)
    def warn(self, msg: str, module: str = "", **kw):  self._log("warn",  msg, module, **kw)
    def error(self, msg: str, module: str = "", **kw): self._log("error", msg, module, **kw)

    def exception(self, msg: str, module: str = "", exc=None, **kw):
        """
        Error log with full traceback attached. Call from within `except:`
        so traceback.format_exc() captures the live exception.

        Logs `msg` at error level and embeds the traceback as a multi-line
        field so it's both visible in console and persisted in the JSON line.
        """
        tb = traceback.format_exc()
        # When called outside an except block tb is just "NoneType: None\n"
        # — fall back to the exception's repr when provided.
        if tb.strip() in ("NoneType: None", ""):
            tb = repr(exc) if exc is not None else ""
        full = f"{msg}\n{tb}".rstrip()
        self._log("error", full, module, traceback=tb, **kw)

    def get_recent(self, n: int = 50) -> list:
        with self._lock:
            return list(self._buffer)[-n:]

    def __del__(self):
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass


# ─── Utility ──────────────────────────────────────────────────────────────────

def position_from_bbox(x, y, w, h, frame_w, frame_h) -> str:
    """Map bounding box center to 3×3 grid position string."""
    cx = x + w / 2
    cy = y + h / 2
    col = min(int(cx / frame_w * 3), 2)
    row = min(int(cy / frame_h * 3), 2)
    col_n = ["kiri",  "tengah", "kanan"][col]
    row_n = ["atas",  "tengah", "bawah"][row]
    if row_n == "tengah":
        return col_n
    if col_n == "tengah":
        return row_n
    return f"{col_n}-{row_n}"
