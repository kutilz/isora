"""
Mode scan bayar — the pure part: banknote labels, spoken amounts, QRIS sniffing,
and the tracker that decides when something is new enough to be said.

Kept free of MaixPy so it runs (and is tested) on a PC. The device-facing half
is modes/pay_mode.py.
"""

import re
from typing import Iterable, Optional


# ─── Banknote labels ──────────────────────────────────────────────────────────

def nominal_from_label(label) -> Optional[int]:
    """Rupiah value of a money-model class label, or None.

    The .mud carries the training names as they were ("UANG_100K", "Uang_5k",
    " UANG_1K" — MaixPy keeps the space after each comma). A retrained model may
    well use plain numbers ("50000") instead, so both are accepted rather than
    tying the code to one dataset's spelling.
    """
    s = str(label or "").strip()
    m = re.search(r"(\d+)\s*k\b", s, re.I)
    if m:
        return int(m.group(1)) * 1000
    m = re.search(r"\d[\d.]*", s)
    if m:
        digits = m.group(0).replace(".", "")
        return int(digits) if digits else None
    return None


# ─── Amounts in words ─────────────────────────────────────────────────────────

_SATUAN = ("", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh",
           "delapan", "sembilan", "sepuluh", "sebelas")


def terbilang(n: int) -> str:
    """Indonesian words for a whole number, 0 < n < 1e12 ("lima puluh ribu").

    Written out instead of left to TTS so each banknote has ONE fixed phrase —
    the name of a pre-generated WAV the device can play with no network.
    """
    n = int(n)
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_SATUAN[n - 10]} belas"
    if n < 100:
        return _join(f"{_SATUAN[n // 10]} puluh", n % 10)
    if n < 200:
        return _join("seratus", n - 100)
    if n < 1000:
        return _join(f"{_SATUAN[n // 100]} ratus", n % 100)
    if n < 2000:
        return _join("seribu", n - 1000)
    if n < 1_000_000:
        return _join(f"{terbilang(n // 1000)} ribu", n % 1000)
    if n < 1_000_000_000:
        return _join(f"{terbilang(n // 1_000_000)} juta", n % 1_000_000)
    return _join(f"{terbilang(n // 1_000_000_000)} miliar", n % 1_000_000_000)


def _join(head: str, rest: int) -> str:
    return f"{head} {terbilang(rest)}" if rest else head


def spoken_nominal(value: int) -> str:
    """What the device says for a banknote: "lima puluh ribu rupiah"."""
    return f"{terbilang(value)} rupiah"


def cue_key(value: int) -> str:
    """SYSTEM_EVENTS key (and WAV name) of spoken_nominal(value)."""
    return spoken_nominal(value).replace(" ", "_")


# ─── QRIS ─────────────────────────────────────────────────────────────────────

def is_qris_payload(payload) -> bool:
    """Whether a decoded QR is an EMVCo merchant code (QRIS), not any QR.

    Every QRIS payload opens with the EMVCo payload-format indicator "000201"
    (tag 00, length 02, value 01). Non-payment QRs — URLs, the pairing code —
    never do.
    """
    return isinstance(payload, str) and payload.startswith("000201")


# ─── When is something new enough to say? ─────────────────────────────────────

class PresenceTracker:
    """Turns per-frame sightings into "this just arrived" events.

    A key (a banknote value, a QR payload) becomes PRESENT after `min_streak`
    sightings in a row, and stops being present once it has gone unseen for
    `gone_s`. Each arrival is offered once through take(); holding the same
    note in view says nothing more, while putting it down and showing it again
    is a new arrival. `min_gap_s` keeps a key that flickers at the edge of
    detection from being repeated faster than that.

    update() and take() are split on purpose: the caller only takes when it can
    actually be heard. An arrival that lands while other audio is playing stays
    pending instead of being marked as said.
    """

    def __init__(self, min_streak: int = 2, gone_s: float = 1.5,
                 min_gap_s: float = 4.0):
        self.min_streak = max(1, int(min_streak))
        self.gone_s = float(gone_s)
        self.min_gap_s = float(min_gap_s)
        self.reset()

    def reset(self):
        self._streak: dict = {}
        self._last_seen: dict = {}
        self._present: set = set()
        self._pending: list = []
        self._said_at: dict = {}

    def update(self, seen: Iterable, now: float):
        seen = set(seen)
        for key in seen:
            self._streak[key] = self._streak.get(key, 0) + 1
            self._last_seen[key] = now
            if key not in self._present and self._streak[key] >= self.min_streak:
                self._present.add(key)
                if key not in self._pending:
                    self._pending.append(key)
        # A miss breaks a streak that has not made it to "present" yet; once
        # present, only gone_s of absence clears it, so one dropped frame of a
        # note being held still does not count as putting it down.
        for key in list(self._streak):
            if key in seen:
                continue
            if key not in self._present:
                del self._streak[key]
            elif now - self._last_seen.get(key, now) >= self.gone_s:
                self._present.discard(key)
                self._streak.pop(key, None)
                if key in self._pending:
                    self._pending.remove(key)

    def take(self, now: float) -> list:
        """Arrivals not yet said (respecting min_gap_s); marks them said."""
        out = []
        for key in list(self._pending):
            if now - self._said_at.get(key, float("-inf")) < self.min_gap_s:
                continue
            self._pending.remove(key)
            self._said_at[key] = now
            out.append(key)
        return out

    @property
    def present(self) -> set:
        return set(self._present)
