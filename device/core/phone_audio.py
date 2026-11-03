"""
Phone audio — play what the device says on a phone, and from there on the
Bluetooth earphones or speaker the phone is already paired with.

Why it is built this way
------------------------
Bluetooth on the MaixCAM needs an SMD rework, so the glasses never talk to the
earphones themselves. The phone does: it opens /dengar on the device (plain
HTTP on the same WiFi — usually the phone's own hotspot), and the page plays
every clip the AudioManager would have played on the device speaker. Android
then routes that audio to whatever Bluetooth output it already uses. It goes
over the LAN, not the cloud: the cloud app is HTTPS and a browser will not let
an HTTPS page fetch a plain-HTTP device, and a cloud round trip would add a
second or two to every obstacle warning.

Transport is a long-poll, not a stream. Each poll is also the phone's "still
here" signal, so there is one mechanism to keep alive instead of two, and it
works over the HTTP/1.0 the device's server speaks.

Fail-safe direction
-------------------
While a phone is listening the device speaker can be silenced (a presentation
does not want the same sentence twice, half a second apart). The moment the
phone stops polling — screen locked, browser killed, WiFi gone — the listener
expires and the very next clip plays on the device speaker again. Losing the
phone must never mean losing the voice. The cost is bounded: at most
_ALIVE_S of audio can go to a phone that has just vanished.
"""

import struct
import threading
import time
from collections import deque
from typing import Optional

from utils import diag

# A clip this soon after a phone was last seen went to the speaker by accident.
_GAP_WORTH_LOGGING_S = 120.0

# A listener is alive while its last poll STARTED less than this long ago. The
# page re-polls immediately after each answer and a poll is held for at most
# POLL_HOLD_S, so a healthy phone is never older than POLL_HOLD_S + one round
# trip. Short on purpose: this is how long a vanished phone can keep the
# device speaker muted.
_ALIVE_S = 5.0

# How long one poll is held open waiting for something to say.
POLL_HOLD_S = 2.5

# Clips kept for the phone to fetch. One description is ~800 KB at 48 kHz, so
# both a count and a byte budget; the oldest goes first. The phone fetches a
# clip right after it is announced, so a short history is plenty.
_MAX_CLIPS = 4
_MAX_CLIP_BYTES = 3 * 1024 * 1024

# Events kept so a poll that arrives a little late still sees what it missed.
_MAX_EVENTS = 32

# Sent to the phone at half the device rate: speech loses nothing audible at
# 24 kHz and it halves both the WiFi traffic and the memory the clips hold.
_SRC_RATE = 48000
_OUT_RATE = 24000


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    """Wrap s16le mono PCM in a minimal RIFF/WAVE header."""
    n = len(pcm)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n) + pcm)


def _downsample(pcm: bytes) -> tuple:
    """48 kHz → 24 kHz with audioop (C) when present; else send it as is."""
    try:
        import audioop
        out, _ = audioop.ratecv(pcm, 2, 1, _SRC_RATE, _OUT_RATE, None)
        return out, _OUT_RATE
    except Exception:
        return pcm, _SRC_RATE


class PhoneAudio:

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._cond = threading.Condition()
        self._listeners: dict = {}       # client id → {"seen": t, "mute": bool}
        self._clips: dict = {}           # clip id → wav bytes (insertion-ordered)
        self._events: deque = deque(maxlen=_MAX_EVENTS)
        self._seq = 0
        self._clip_id = 0
        self._last_seen: Optional[float] = None

    # ─── listeners ────────────────────────────────────────────────────────────

    def _alive_locked(self) -> list:
        now = self._clock()
        for cid in [c for c, l in self._listeners.items() if now - l["seen"] > _ALIVE_S]:
            diag.event("listen_expired", client=cid[:8], away_s=now - self._listeners[cid]["seen"])
            del self._listeners[cid]
        return list(self._listeners.values())

    def listening(self) -> bool:
        """True while at least one phone is polling."""
        with self._cond:
            return bool(self._alive_locked())

    def device_muted(self) -> bool:
        """True while a live phone asked for the device speaker to stay quiet."""
        with self._cond:
            return any(l["mute"] for l in self._alive_locked())

    def leave(self, client: str):
        """The page said goodbye — give the voice back to the device at once."""
        with self._cond:
            if self._listeners.pop(client, None) is not None:
                diag.event("listen_leave", client=client[:8])
            self._cond.notify_all()

    # ─── producer side (AudioManager) ─────────────────────────────────────────

    def publish(self, pcm: bytes, text: str = "") -> Optional[int]:
        """Offer one clip (s16le mono 48 kHz) to listening phones.

        Returns the clip id, or None when nobody is listening — then nothing is
        converted or stored, so the feature costs nothing while unused.
        """
        if not pcm:
            return None
        with self._cond:
            if not self._alive_locked():
                # A phone that was here moments ago: this clip goes to the device
                # speaker only, which is the "speaker first, then the phone" gap.
                if self._last_seen is not None:
                    away_s = self._clock() - self._last_seen
                    if away_s < _GAP_WORTH_LOGGING_S:
                        diag.event("listen_gap", away_s=away_s, text=text[:40])
                return None
        data, rate = _downsample(pcm)
        wav = wav_bytes(data, rate)
        dur_ms = int(len(data) * 1000 / (rate * 2))
        with self._cond:
            self._clip_id += 1
            cid = self._clip_id
            self._clips[cid] = wav
            while (len(self._clips) > _MAX_CLIPS
                   or sum(len(v) for v in self._clips.values()) > _MAX_CLIP_BYTES):
                if len(self._clips) == 1:
                    break
                del self._clips[next(iter(self._clips))]
            self._push_locked({"type": "clip", "id": cid, "ms": dur_ms,
                               "text": text or ""})
        return cid

    def cancel(self):
        """The device cut the current clip short (barge-in): so must the phone."""
        with self._cond:
            if not self._listeners:
                return
            self._push_locked({"type": "stop"})

    def _push_locked(self, event: dict):
        self._seq += 1
        event["seq"] = self._seq
        self._events.append(event)
        self._cond.notify_all()

    # ─── consumer side (web server) ───────────────────────────────────────────

    def poll(self, client: str, since: int, mute: bool,
             hold_s: float = POLL_HOLD_S) -> dict:
        """Register `client` as alive and wait up to `hold_s` for news.

        Returns {"seq": latest, "events": [...newer than since...]}. `since`
        of -1 means "a fresh page": it starts at the present instead of
        replaying clips it was never there for.
        """
        deadline = self._clock() + hold_s
        with self._cond:
            if client not in self._listeners:
                diag.event("listen_join", client=client[:8], mute=bool(mute), since=since,
                           away_s=None if self._last_seen is None
                           else self._clock() - self._last_seen)
            self._listeners[client] = {"seen": self._clock(), "mute": bool(mute)}
            self._last_seen = self._clock()
            # since > seq: the app restarted under an open page, and its
            # counter began again from zero. Start from the present rather
            # than wait for the new counter to catch up with the old one.
            if since < 0 or since > self._seq:
                since = self._seq
            while True:
                fresh = [e for e in self._events if e["seq"] > since]
                remaining = deadline - self._clock()
                if fresh or remaining <= 0:
                    break
                self._cond.wait(remaining)
            return {"seq": self._seq, "events": [dict(e) for e in fresh]}

    def clip(self, clip_id: int) -> Optional[bytes]:
        with self._cond:
            data = self._clips.get(clip_id)
            if data is None:
                diag.event("listen_clip_miss", level="warn", id=clip_id, newest=self._clip_id)
            return data


# One per process: the AudioManager publishes into it, the web server reads.
phone_audio = PhoneAudio()
