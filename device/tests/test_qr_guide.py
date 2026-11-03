"""Panduan QR: what the person hears while their head is turned towards a code,
and whether a code too far away to decode is still found.

The locator runs on real QR images (OpenCV's encoder, scaled and placed in a
noisy frame) because its whole value is holding up where the decoder gives out.
"""

import importlib.util
import os
import random
import sys

import pytest

from utils.qr_guide import (ALL_CUES, CUE_CLOSER, CUE_LOST, CUE_NOTHING, CUE_READY,
                            CUE_TEXT, QrGuide, Sighting, locate_finders)

QRIS_LIKE = "00020101021126570011ID.DANA.WWW011893600915302259148102090225914810303UMI" \
            "51440014ID.CO.QRIS.WWW0215ID10200176114730303UMI5204581253033605802ID" \
            "5913WARUNG BU SRI6007BANDUNG6105402116304ABCD"


def _heard(guide, frames):
    """Feed (t, sighting) pairs with the speaker always quiet; list of (t, cue)."""
    out = []
    for t, s in frames:
        guide.update(s, t)
        cue = guide.next_cue(t)
        if cue:
            out.append((t, cue))
    return out


# ─── directions ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cx,cy,cue", [
    (0.1, 0.1, "kode_di_kiri_atas"), (0.5, 0.1, "kode_di_atas"), (0.9, 0.1, "kode_di_kanan_atas"),
    (0.1, 0.5, "kode_di_kiri"), (0.9, 0.5, "kode_di_kanan"),
    (0.1, 0.9, "kode_di_kiri_bawah"), (0.5, 0.9, "kode_di_bawah"), (0.9, 0.9, "kode_di_kanan_bawah"),
])
def test_position_is_named_by_the_part_of_the_frame_it_is_in(cx, cy, cue):
    g = QrGuide()
    g.update(Sighting(cx, cy, 0.1), 0.0)
    assert g.next_cue(0.0) == cue


def test_a_centred_small_code_asks_to_come_closer():
    g = QrGuide()
    g.update(Sighting(0.5, 0.5, 0.1), 0.0)
    assert g.next_cue(0.0) == CUE_CLOSER


def test_a_centred_big_code_is_ready():
    g = QrGuide()
    g.update(Sighting(0.5, 0.5, 0.4), 0.0)
    assert g.next_cue(0.0) == CUE_READY


def test_a_decoded_centred_code_is_ready_whatever_its_size():
    g = QrGuide()
    g.update(Sighting(0.5, 0.5, 0.2, "000201"), 0.0)
    assert g.next_cue(0.0) == CUE_READY


def test_the_full_walk_from_far_to_ready():
    g = QrGuide()
    heard = _heard(g, [
        (0.0, Sighting(0.9, 0.9, 0.08)),
        (1.0, Sighting(0.7, 0.75, 0.10)),
        (2.0, Sighting(0.5, 0.5, 0.15)),
        (3.0, Sighting(0.5, 0.5, 0.35)),
    ])
    assert [c for _, c in heard] == ["kode_di_kanan_bawah", CUE_CLOSER, CUE_READY]


# ─── when it is said ─────────────────────────────────────────────────────────

def test_a_code_that_stays_put_is_repeated_not_chattered():
    g = QrGuide(repeat_s=2.5, min_gap_s=0.8)
    heard = _heard(g, [(i * 0.1, Sighting(0.9, 0.5, 0.1)) for i in range(60)])
    times = [t for t, _ in heard]
    assert len(times) == 3
    assert all(b - a >= 2.5 - 1e-9 for a, b in zip(times, times[1:]))


def test_ready_is_said_once_while_the_code_is_held_there():
    g = QrGuide()
    heard = _heard(g, [(i * 0.1, Sighting(0.5, 0.5, 0.5)) for i in range(100)])
    assert [c for _, c in heard] == [CUE_READY]


def test_drifting_off_and_returning_says_ready_again():
    g = QrGuide(min_gap_s=0.1)
    heard = _heard(g, [
        (0.0, Sighting(0.5, 0.5, 0.5)),
        (1.0, Sighting(0.95, 0.5, 0.5)),
        (2.0, Sighting(0.5, 0.5, 0.5)),
    ])
    assert [c for _, c in heard] == [CUE_READY, "kode_di_kanan", CUE_READY]


def test_a_code_on_the_border_does_not_flip_the_sentence():
    g = QrGuide(enter_tol=0.16, leave_tol=0.22, min_gap_s=0.0, repeat_s=99)
    g.update(Sighting(0.5, 0.5, 0.1), 0.0)
    assert g.next_cue(0.0) == CUE_CLOSER
    # Wobbling around the enter line stays inside the wider leave line.
    for i, cx in enumerate([0.68, 0.66, 0.70, 0.67]):
        g.update(Sighting(cx, 0.5, 0.1), 1.0 + i)
        assert g.next_cue(1.0 + i) is None


def test_a_lost_code_is_said_once_after_a_real_absence():
    g = QrGuide(lost_s=2.5)
    frames = [(0.0, Sighting(0.9, 0.5, 0.1))] + [(0.5 * i, None) for i in range(1, 12)]
    heard = _heard(g, frames)
    assert [c for _, c in heard] == ["kode_di_kanan", CUE_LOST]
    assert heard[1][0] >= 2.5


def test_a_dropped_frame_is_not_a_lost_code():
    g = QrGuide(lost_s=2.5)
    heard = _heard(g, [(0.0, Sighting(0.9, 0.5, 0.1)), (0.5, None), (1.0, Sighting(0.9, 0.5, 0.1))])
    assert CUE_LOST not in [c for _, c in heard]


def test_nothing_is_said_when_nothing_was_ever_seen():
    g = QrGuide()
    assert _heard(g, [(i * 0.5, None) for i in range(40)]) == []


# ─── the ACTION button ───────────────────────────────────────────────────────

def test_asking_with_nothing_in_view_says_so():
    g = QrGuide()
    g.ask()
    assert g.next_cue(0.0) == CUE_NOTHING
    assert g.next_cue(1.0) is None


def test_asking_repeats_the_current_position_at_once():
    g = QrGuide(min_gap_s=5.0, repeat_s=50.0)
    g.update(Sighting(0.1, 0.1, 0.1), 0.0)
    assert g.next_cue(0.0) == "kode_di_kiri_atas"
    g.ask()
    assert g.next_cue(0.1) == "kode_di_kiri_atas"


# ─── offline speech ──────────────────────────────────────────────────────────

def test_every_cue_has_an_offline_wav_entry_with_a_matching_name():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    spec = importlib.util.spec_from_file_location(
        "isora_generate_audio_guide", os.path.join(root, "tools", "generate_audio.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    events = module.SYSTEM_EVENTS
    for key in ALL_CUES:
        assert events.get(key) == CUE_TEXT[key], key
        safe = "".join(c for c in events[key].lower().replace(" ", "_").replace(",", "")
                       if c.isalnum() or c == "_")
        assert safe == key


# ─── finding a code from its finder squares ──────────────────────────────────

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _frame(side_px, cx=0.5, cy=0.5, w=640, h=480, seed=3, payload=QRIS_LIKE, noise=8):
    """A grey frame with a QR of `side_px` pixels centred at (cx, cy)."""
    rng = np.random.RandomState(seed)
    frame = np.clip(rng.normal(150, noise, (h, w)), 0, 255).astype(np.uint8)
    code = cv2.QRCodeEncoder.create().encode(payload)
    code = cv2.resize(code, (side_px, side_px), interpolation=cv2.INTER_AREA)
    x0 = int(cx * w - side_px / 2)
    y0 = int(cy * h - side_px / 2)
    pad = max(4, side_px // 12)
    cv2.rectangle(frame, (x0 - pad, y0 - pad), (x0 + side_px + pad, y0 + side_px + pad), 245, -1)
    frame[y0:y0 + side_px, x0:x0 + side_px] = code
    frame = cv2.GaussianBlur(frame, (3, 3), 0)
    return frame


@pytest.mark.parametrize("side", [90, 120, 160, 240, 320])
def test_a_code_is_found_at_many_distances(side):
    f = _frame(side)
    s = locate_finders(f.tobytes(), f.shape[1], f.shape[0])
    assert s is not None, side
    assert abs(s.cx - 0.5) < 0.12 and abs(s.cy - 0.5) < 0.12
    assert 0.5 < s.size / (side / 480.0) < 1.4


@pytest.mark.parametrize("cx,cy", [(0.2, 0.25), (0.8, 0.25), (0.2, 0.75), (0.8, 0.75)])
def test_a_found_code_reports_the_right_corner(cx, cy):
    f = _frame(130, cx, cy)
    s = locate_finders(f.tobytes(), f.shape[1], f.shape[0])
    assert s is not None
    assert (s.cx < 0.5) == (cx < 0.5) and (s.cy < 0.5) == (cy < 0.5)


def test_a_code_too_small_to_decode_is_still_found():
    """The reason this locator exists at all."""
    f = _frame(100)
    assert cv2.QRCodeDetector().detectAndDecode(f)[0] == ""
    assert locate_finders(f.tobytes(), f.shape[1], f.shape[0]) is not None


def test_the_search_is_cheap_enough_for_the_device():
    """A full 640x480 frame on this PC; the 1 GHz RISC-V core runs ~30x slower,
    and the mode spends only every other frame here."""
    import time
    f = _frame(160)
    t0 = time.perf_counter()
    for _ in range(5):
        locate_finders(f.tobytes(), f.shape[1], f.shape[0])
    assert (time.perf_counter() - t0) / 5 < 0.05


def test_scenes_without_a_code_stay_silent():
    h, w = 480, 640
    rng = random.Random(5)
    flat = np.full((h, w), 140, np.uint8)
    # Printed text, the likeliest false alarm: dense dark/light runs on every row.
    text = np.full((h, w), 235, np.uint8)
    for y in range(20, h - 20, 26):
        line = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz RP 0123456789") for _ in range(46))
        cv2.putText(text, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 20, 1, cv2.LINE_AA)
    # A grille: evenly spaced bars, which is 1:1:1:1:1 and must not pass as 1:1:3:1:1.
    grille = np.full((h, w), 230, np.uint8)
    grille[:, ::12] = 20
    grille[:, 1::12] = 20
    for name, f in [("flat", flat), ("text", text), ("grille", grille)]:
        assert locate_finders(f.tobytes(), w, h) is None, name
    # Fabric or a dim sensor: fine-grained texture, not single-pixel static.
    for seed in range(25):
        raw = np.random.RandomState(seed).randint(0, 255, (h, w)).astype(np.uint8)
        noisy = cv2.normalize(cv2.GaussianBlur(raw, (5, 5), 0), None, 0, 255, cv2.NORM_MINMAX)
        assert locate_finders(noisy.tobytes(), w, h) is None, seed
