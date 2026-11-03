"""
Panduan arah ke kode QR — the pure part of guiding a blind user to a QR code.

Paying by QRIS means pointing a phone at a code the person cannot see: a sticker
on a counter, a stand next to the till, the merchant's screen. The glasses find
it and talk the person's head towards it — "kode di kanan bawah", "dekati kode",
"kode pas, pindai sekarang" — and the phone that is held at the same level then
does the scan. It all runs on the device, with no network: finding a code does
not get better for having a server, and the till is the last place to depend on
one.

Kept free of MaixPy so it runs (and is tested) on a PC; modes/pay_mode.py feeds
it sightings from AIEngine.locate_qr().

Every cue is a fixed phrase with a pre-generated WAV (tools/generate_audio.py),
so nothing here waits on gTTS.
"""

import re
from typing import Optional

# SYSTEM_EVENTS keys. The key equals the safe-name of its spoken text.
CUE_READY = "kode_pas_pindai_sekarang"
CUE_CLOSER = "dekati_kode"
CUE_LOST = "kode_hilang"
CUE_NOTHING = "belum_ada_kode_terlihat"

_POSITION_CUES = {
    ("kiri", "atas"): "kode_di_kiri_atas",
    ("tengah", "atas"): "kode_di_atas",
    ("kanan", "atas"): "kode_di_kanan_atas",
    ("kiri", "tengah"): "kode_di_kiri",
    ("kanan", "tengah"): "kode_di_kanan",
    ("kiri", "bawah"): "kode_di_kiri_bawah",
    ("tengah", "bawah"): "kode_di_bawah",
    ("kanan", "bawah"): "kode_di_kanan_bawah",
}

# Every cue this module can ask for: the generate-audio test pins each to a WAV.
ALL_CUES = tuple(_POSITION_CUES.values()) + (CUE_READY, CUE_CLOSER, CUE_LOST, CUE_NOTHING)

CUE_TEXT = {key: key.replace("_", " ") for key in ALL_CUES}
CUE_TEXT[CUE_READY] = "kode pas, pindai sekarang"


class Sighting:
    """Where a code is in the frame: centre as 0..1 of width/height, `size` as
    its side over the frame's shorter side, `payload` when it could be decoded
    (a code found from far away usually cannot be, yet)."""

    __slots__ = ("cx", "cy", "size", "payload")

    def __init__(self, cx: float, cy: float, size: float, payload: Optional[str] = None):
        self.cx, self.cy, self.size, self.payload = cx, cy, size, payload

    def __repr__(self):
        return "Sighting(%.2f,%.2f,size=%.2f,%s)" % (self.cx, self.cy, self.size,
                                                     "decoded" if self.payload else "found")


def _axis(value: float, previous: str, low: str, high: str, enter: float, leave: float) -> str:
    """Which third of an axis `value` is in. Leaving the middle takes a bigger
    step than entering it, so a code on the border does not flip the sentence."""
    off = value - 0.5
    tol = leave if previous == "tengah" else enter
    if abs(off) <= tol:
        return "tengah"
    return low if off < 0 else high


class QrGuide:
    """Turns sightings into at most one spoken cue per quiet moment.

    update() takes every look; next_cue() is asked only when the speaker is
    quiet, so a cue is always about where the code is NOW and never a queue of
    stale directions. The cue repeats when the code has not moved: the person is
    turning their head and needs to know it is still there.
    """

    def __init__(self, enter_tol: float = 0.16, leave_tol: float = 0.22,
                 ready_size: float = 0.30, repeat_s: float = 2.5,
                 min_gap_s: float = 0.8, lost_s: float = 2.5):
        self.enter_tol = float(enter_tol)
        self.leave_tol = float(leave_tol)
        self.ready_size = float(ready_size)
        self.repeat_s = float(repeat_s)
        self.min_gap_s = float(min_gap_s)
        self.lost_s = float(lost_s)
        self.reset()

    def reset(self):
        self._last_seen = None
        self._h = "tengah"
        self._v = "tengah"
        self._size = 0.0
        self._decoded = False
        self._last_cue = None
        self._last_cue_at = float("-inf")
        self._ready_said = False
        self._lost_pending = False
        self._asked = False

    # ─── input ────────────────────────────────────────────────────────────────

    def update(self, sighting: Optional[Sighting], now: float):
        if sighting is None:
            if self._last_seen is not None and now - self._last_seen >= self.lost_s:
                self._last_seen = None
                self._ready_said = False
                self._decoded = False
                self._lost_pending = True
            return
        self._last_seen = now
        self._lost_pending = False
        self._h = _axis(sighting.cx, self._h, "kiri", "kanan", self.enter_tol, self.leave_tol)
        self._v = _axis(sighting.cy, self._v, "atas", "bawah", self.enter_tol, self.leave_tol)
        self._size = sighting.size
        self._decoded = bool(sighting.payload)
        if self._cue_now() != CUE_READY:
            # Drifted off after "pas": the person must hear "pas" again on return.
            self._ready_said = False

    def ask(self):
        """ACTION pressed: say where things stand at the next quiet moment."""
        self._asked = True

    # ─── output ───────────────────────────────────────────────────────────────

    @property
    def visible(self) -> bool:
        return self._last_seen is not None

    def _cue_now(self) -> str:
        if (self._h, self._v) != ("tengah", "tengah"):
            return _POSITION_CUES[(self._h, self._v)]
        if self._decoded or self._size >= self.ready_size:
            return CUE_READY
        return CUE_CLOSER

    def next_cue(self, now: float) -> Optional[str]:
        """The cue to speak now, or None. Marks it as said."""
        asked, self._asked = self._asked, False
        if not self.visible:
            if asked:
                return self._said(CUE_NOTHING, now)
            if self._lost_pending:
                self._lost_pending = False
                return self._said(CUE_LOST, now)
            return None
        cue = self._cue_now()
        if asked:
            return self._said(cue, now)
        since = now - self._last_cue_at
        if since < self.min_gap_s:
            return None
        if cue == CUE_READY:
            # Said once while the code stays in the sweet spot. Repeating "scan
            # now" at someone who is busy scanning is just noise.
            if self._ready_said:
                return None
            self._ready_said = True
            return self._said(cue, now)
        if cue != self._last_cue or since >= self.repeat_s:
            return self._said(cue, now)
        return None

    def _said(self, cue: str, now: float) -> str:
        self._last_cue = cue
        self._last_cue_at = now
        return cue


# ─── Finding a code that is too far away to decode ────────────────────────────

# The finder squares in three corners of every QR read 1:1:3:1:1 (dark, light,
# dark, light, dark) along any line through their centre, at any distance. That
# ratio survives down to about 1.5 pixels per module; decoding the code takes two
# or three. So it is what lets the glasses say "kode di kanan" from further away
# than the code can be read.
#
# This runs in Python on a 1 GHz core, every other camera frame, so the rows are
# done by bytes.translate and a compiled regex (both C) and the Python loop only
# ever sees the few places that matched.
_RATIO_TOL = 0.55       # each run may be off by this share of one module
_MIN_MODULE_PX = 1.5
_MAX_CODE_MODULES = 85  # finder to finder; a QRIS payload stays well below version 18
_MIN_CODE_MODULES = 14  # version 1 is 21 wide, finder centres 14 apart
_MAX_ROW_HITS = 240     # a real code gives a few dozen; fine texture gives thousands
_MAX_FINDERS = 8        # the largest few squares: the search below is cubic
_FIVE_RUNS = re.compile(rb"(?<!\x00)(?=(\x00+)(\x01+)(\x00+)(\x01+)(\x00+))")
_BINARY = {}


def _binary_table(threshold: int) -> bytes:
    """256-byte table mapping grey to 0 (dark) or 1 (light)."""
    table = _BINARY.get(threshold)
    if table is None:
        table = bytes(0 if i < threshold else 1 for i in range(256))
        _BINARY[threshold] = table
    return table


def _finder_points(gray, width, height, row_step=2):
    """Candidate finder centres (x, y, module) in row order. `gray` is bytes."""
    hits = []
    for y in range(0, height, row_step):
        row = gray[y * width:(y + 1) * width]
        lo, hi = min(row), max(row)
        if hi - lo < 50:
            continue                    # a flat row: wall, ceiling
        for m in _FIVE_RUNS.finditer(row.translate(_binary_table((lo + hi) // 2))):
            a, b, c, d, e = (m.end(i) - m.start(i) for i in (1, 2, 3, 4, 5))
            module = (a + b + c + d + e) / 7.0
            if module < _MIN_MODULE_PX:
                continue
            tol = module * _RATIO_TOL + 0.5
            if (abs(a - module) < tol and abs(b - module) < tol and abs(d - module) < tol
                    and abs(e - module) < tol and abs(c - 3 * module) < tol * 2):
                hits.append(((m.start(3) + m.end(3)) / 2.0, y, module))
                if len(hits) > _MAX_ROW_HITS:
                    return []           # texture, not a code: stop spending time on it
    return hits


def _column_is_finder(gray, width, height, x, y, module) -> bool:
    """The same 1:1:3:1:1 read straight down through (x, y). A finder square has
    it both ways; a row of text that happens to fit the ratio does not."""
    x = int(x)
    if not 0 <= x < width:
        return False
    y0 = int(y)
    reach = int(module * 5) + 2
    top = max(0, y0 - reach)
    bottom = min(height, y0 + reach + 1)
    col = [gray[r * width + x] for r in range(top, bottom)]
    if len(col) < 5:
        return False
    lo, hi = min(col), max(col)
    if hi - lo < 50:
        return False
    threshold = (lo + hi) // 2
    runs = []
    start = 0
    dark = col[0] < threshold
    for i in range(1, len(col)):
        d = col[i] < threshold
        if d != dark:
            runs.append((dark, start, i))
            start = i
            dark = d
    runs.append((dark, start, len(col)))
    mid = y0 - top
    for i, (is_dark, a, b) in enumerate(runs):
        if not (is_dark and a <= mid < b):
            continue
        if i < 2 or i + 2 >= len(runs):
            return False
        centre = b - a
        tol = module * _RATIO_TOL + 1
        if abs(centre - 3 * module) > tol * 2:
            return False
        sides = [runs[i - 2], runs[i - 1], runs[i + 1], runs[i + 2]]
        # The outer dark runs may be cut off by `reach`; they only need to exist.
        return (abs((runs[i - 1][2] - runs[i - 1][1]) - module) <= tol
                and abs((runs[i + 1][2] - runs[i + 1][1]) - module) <= tol
                and sides[0][0] and sides[3][0])
    return False


def locate_finders(gray, width, height, row_step=2) -> Optional[Sighting]:
    """A QR from its finder squares alone, or None.

    Each square must read 1:1:3:1:1 both across and down (text, grilles and
    barcodes throw up rows that fit one way, only a square fits both), and it takes
    all three squares of a code. Being wrong here means telling someone a code
    exists where it does not, so this leans to silence.
    """
    hits = _finder_points(bytes(gray), width, height, row_step)
    if len(hits) < 2:
        return None
    # Group row hits into squares: same x (within a module or so), adjacent rows.
    squares = []
    for x, y, m in hits:
        for s in squares:
            if abs(s[0] / s[3] - x) <= max(2.0, m) and y - s[4] <= row_step + m:
                s[0] += x
                s[1] += y
                s[2] += m
                s[3] += 1
                s[4] = y
                break
        else:
            squares.append([x, y, m, 1, y])
    found = []
    for s in squares:
        cx, cy, m, n = s[0] / s[3], s[1] / s[3], s[2] / s[3], s[3]
        # The centre square is 3 modules tall; a finder is seen on about that many rows.
        if n * row_step >= max(2.0, 1.5 * m) and _column_is_finder(gray, width, height, cx, cy, m):
            found.append((cx, cy, m))
    return _sighting_from_finders(found, width, height)


def _sighting_from_finders(found, width, height) -> Optional[Sighting]:
    """Three squares that form the corner of a square: one (the corner) about
    equally far from the other two, at about a right angle, all of one module
    size. Chance texture passes the ratio test now and then; it does not pass
    this. Tolerances are wide because the code is rarely seen head on."""
    if len(found) < 3:
        return None
    found = sorted(found, key=lambda f: -f[2])[:_MAX_FINDERS]
    best = None
    for i, c in enumerate(found):
        others = found[:i] + found[i + 1:]
        for j, a in enumerate(others):
            for b in others[j + 1:]:
                ax, ay = a[0] - c[0], a[1] - c[1]
                bx, by = b[0] - c[0], b[1] - c[1]
                la = (ax * ax + ay * ay) ** 0.5
                lb = (bx * bx + by * by) ** 0.5
                m = (a[2] + b[2] + c[2]) / 3.0
                if min(la, lb) < _MIN_CODE_MODULES * m or max(la, lb) > _MAX_CODE_MODULES * m:
                    continue
                if not 0.65 < la / lb < 1.55:
                    continue
                if abs(ax * bx + ay * by) / (la * lb) > 0.5:
                    continue            # not within 30 degrees of a right angle
                if not all(0.7 < f[2] / m < 1.4 for f in (a, b, c)):
                    continue
                side = max(la, lb)
                if best is None or side > best[0]:
                    best = (side, (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, m)
    if best is None:
        return None
    side, cx, cy, m = best
    return Sighting(cx / width, cy / height, (side + 7 * m) / float(min(width, height)))
