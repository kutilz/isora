"""
Speech presets — sentences typed on the operator page, rendered to speech once
and kept as buttons that play with no network at all.

Rendering needs the cloud voice (gTTS / OpenAI) or a full per-word cache hit,
so a preset is made BEFORE the presentation, while there is internet. What is
stored is the finished 48 kHz s16le PCM the codec plays, so pressing the button
later is a file read — the same offline guarantee as the pre-recorded system
cues.

Kept out of tts_cache_dir on purpose: that cache is pruned to its newest 120
utterances, and a scene description spoken during rehearsal must never be able
to evict a button someone is counting on during the real thing.

Layout (all under `root`):
    index.json      [{"id", "text", "seconds", "source", "created"}, ...]
    <id>.pcm        the rendered audio

Every write goes through a temp file + os.replace, so a power cut mid-write
leaves the previous index or no file, never a half-written one.
"""

import json
import os
import threading
import time
import uuid
from typing import Callable, List, Optional, Tuple

MAX_PRESETS = 40
MAX_TEXT = 300
PCM_BYTES_S = 48000 * 2          # 48 kHz, 16-bit mono


class PresetError(Exception):
    """A request the operator can fix (bad text, full list, no voice)."""


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class SpeechPresets:
    def __init__(self, root: str = "/root/audio/pimnas_presets"):
        self.root = root
        self._lock = threading.Lock()

    # ─── index ────────────────────────────────────────────────────────────────

    @property
    def _index_path(self) -> str:
        return os.path.join(self.root, "index.json")

    def _pcm_path(self, pid: str) -> str:
        return os.path.join(self.root, pid + ".pcm")

    @staticmethod
    def _valid_id(pid) -> bool:
        return isinstance(pid, str) and 0 < len(pid) <= 32 and pid.isalnum()

    def _read(self) -> list:
        try:
            with open(self._index_path, encoding="utf-8") as f:
                items = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(items, list):
            return []
        return [it for it in items
                if isinstance(it, dict) and self._valid_id(it.get("id"))]

    def _write(self, items: list) -> None:
        os.makedirs(self.root, exist_ok=True)
        _atomic_write(self._index_path,
                      json.dumps(items, ensure_ascii=False).encode("utf-8"))

    def list(self) -> List[dict]:
        """Presets in button order. One whose audio vanished is left out."""
        with self._lock:
            return [dict(it) for it in self._read()
                    if os.path.isfile(self._pcm_path(it["id"]))]

    # ─── changes ──────────────────────────────────────────────────────────────

    @staticmethod
    def clean_text(text) -> str:
        text = " ".join(str(text or "").split())
        if not text:
            raise PresetError("Teks kosong.")
        if len(text) > MAX_TEXT:
            raise PresetError("Teks terlalu panjang (maks %d huruf)." % MAX_TEXT)
        return text

    def add(self, text, render: Callable[[str], Tuple[Optional[bytes], str]]) -> dict:
        """Render `text` and append it as a new button.

        `render(text)` returns (pcm_bytes or None, source). It runs OUTSIDE the
        lock — a synth can take seconds and must not stall play() for buttons
        that already exist.
        """
        text = self.clean_text(text)
        with self._lock:
            if len(self._read()) >= MAX_PRESETS:
                raise PresetError("Sudah %d tombol. Hapus satu dulu." % MAX_PRESETS)
        pcm, source = render(text)
        if not pcm:
            raise PresetError(
                "Gagal membuat suara. Pembuatan tombol butuh internet; "
                "setelah jadi, tombol bisa diputar tanpa internet.")
        pid = uuid.uuid4().hex[:12]
        entry = {
            "id":      pid,
            "text":    text,
            "seconds": round(len(pcm) / PCM_BYTES_S, 1),
            "source":  source,
            "created": int(time.time()),
        }
        with self._lock:
            items = self._read()
            if len(items) >= MAX_PRESETS:
                raise PresetError("Sudah %d tombol. Hapus satu dulu." % MAX_PRESETS)
            os.makedirs(self.root, exist_ok=True)
            _atomic_write(self._pcm_path(pid), pcm)
            items.append(entry)
            self._write(items)
        return dict(entry)

    def pcm(self, pid) -> Optional[bytes]:
        if not self._valid_id(pid):
            return None
        try:
            with open(self._pcm_path(pid), "rb") as f:
                return f.read()
        except OSError:
            return None

    def get(self, pid) -> Optional[dict]:
        for it in self.list():
            if it["id"] == pid:
                return it
        return None

    def delete(self, pid) -> bool:
        if not self._valid_id(pid):
            return False
        with self._lock:
            items = self._read()
            kept = [it for it in items if it["id"] != pid]
            if len(kept) == len(items):
                return False
            self._write(kept)
            try:
                os.remove(self._pcm_path(pid))
            except OSError:
                pass
            return True

    def move(self, pid, delta: int) -> bool:
        """Shift a button up (delta < 0) or down (delta > 0) by one place."""
        if not self._valid_id(pid) or delta == 0:
            return False
        with self._lock:
            items = self._read()
            idx = next((i for i, it in enumerate(items) if it["id"] == pid), None)
            if idx is None:
                return False
            to = idx + (1 if delta > 0 else -1)
            if not 0 <= to < len(items):
                return False
            items[idx], items[to] = items[to], items[idx]
            self._write(items)
            return True


_instance = None
_instance_lock = threading.Lock()


def presets() -> SpeechPresets:
    """The device-wide store, rooted at cfg presets dir."""
    global _instance
    with _instance_lock:
        if _instance is None:
            try:
                from config import cfg
                root = cfg.get("speech_presets_dir", "/root/audio/pimnas_presets")
            except Exception:
                root = "/root/audio/pimnas_presets"
            _instance = SpeechPresets(root)
        return _instance
