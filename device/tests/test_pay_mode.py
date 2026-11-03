"""Scan bayar: banknotes and QRIS on alternating frames, each said once.

The device half (camera, NPU) is faked; what is pinned here is what the user
hears and when — a note named once when it arrives and not again while it is
held, a QRIS code read out with its merchant, nothing spoken over other audio,
and every note the model can name having an offline WAV.
"""

import importlib.util
import os
import sys

import pytest

from core.orchestrator import Orchestrator
from modes.pay_mode import PayScanner, run_pay_tick
from utils.money import (PresenceTracker, cue_key, is_qris_payload,
                         nominal_from_label, spoken_nominal, terbilang)
from utils.qr_guide import CUE_READY, Sighting

# The labels exactly as MaixPy hands them back from uang_yolo26n.mud — note the
# space it keeps after every comma.
MUD_LABELS = ["UANG_100K", " UANG_1K", " UANG_2K", " Uang_5k", " UANG_10K",
              " Uang_20k", " Uang_50k"]
DENOMINATIONS = [1000, 2000, 5000, 10000, 20000, 50000, 100000]



def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


QRIS = (_tlv("00", "01") + _tlv("01", "12")
        + _tlv("26", _tlv("00", "ID.CO.QRIS.WWW") + _tlv("01", "936009153022591481"))
        + _tlv("52", "5812") + _tlv("53", "360") + _tlv("54", "25000")
        + _tlv("58", "ID") + _tlv("59", "WARUNG BU SRI") + _tlv("60", "BANDUNG")
        + _tlv("63", "4B2A"))


# ─── labels and words ────────────────────────────────────────────────────────

def test_every_mud_label_parses_to_its_denomination():
    assert sorted(nominal_from_label(l) for l in MUD_LABELS) == DENOMINATIONS


@pytest.mark.parametrize("label,value", [
    ("50000", 50000), ("Rp 2.000", 2000), ("uang_100k", 100000), ("kursi", None), ("", None),
])
def test_other_label_spellings(label, value):
    assert nominal_from_label(label) == value


@pytest.mark.parametrize("n,words", [
    (1000, "seribu"), (2000, "dua ribu"), (5000, "lima ribu"),
    (10000, "sepuluh ribu"), (20000, "dua puluh ribu"),
    (50000, "lima puluh ribu"), (100000, "seratus ribu"),
    (11, "sebelas"), (15, "lima belas"), (21, "dua puluh satu"),
    (115, "seratus lima belas"), (1500, "seribu lima ratus"),
    (12500, "dua belas ribu lima ratus"), (1_000_000, "satu juta"),
])
def test_terbilang(n, words):
    assert terbilang(n) == words


def _system_events():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "tools", "generate_audio.py")
    spec = importlib.util.spec_from_file_location("isora_generate_audio_pay", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SYSTEM_EVENTS


def test_every_denomination_has_an_offline_wav_entry():
    """A note named through gTTS would need the network at the till."""
    events = _system_events()
    for value in DENOMINATIONS:
        assert events.get(cue_key(value)) == spoken_nominal(value), value
    assert "bukan_kode_pembayaran" in events


def test_qris_is_told_apart_from_other_qr_codes():
    assert is_qris_payload(QRIS)
    assert not is_qris_payload("https://isora-smartglasses.vercel.app/app")
    assert not is_qris_payload(None)


# ─── the arrival tracker ─────────────────────────────────────────────────────

def test_a_held_note_is_said_once():
    t = PresenceTracker(min_streak=3, gone_s=1.5, min_gap_s=4.0)
    said = []
    for i in range(30):                         # 3 s of the same note in view
        t.update({50000}, i * 0.1)
        said += t.take(i * 0.1)
    assert said == [50000]


def test_a_flicker_never_becomes_a_note():
    t = PresenceTracker(min_streak=3, gone_s=1.5, min_gap_s=4.0)
    for i, seen in enumerate([{20000}, set(), {20000}, set(), {20000}]):
        t.update(seen, i * 0.1)
    assert t.take(0.5) == []


def test_one_missed_frame_is_not_putting_the_note_down():
    t = PresenceTracker(min_streak=2, gone_s=1.5, min_gap_s=4.0)
    t.update({5000}, 0.0); t.update({5000}, 0.1)
    assert t.take(0.1) == [5000]
    t.update(set(), 0.2)                        # decoder missed one frame
    t.update({5000}, 0.3)
    assert t.take(0.3) == []


def test_putting_the_note_down_and_showing_it_again_is_said_again():
    t = PresenceTracker(min_streak=2, gone_s=1.0, min_gap_s=4.0)
    t.update({10000}, 0.0); t.update({10000}, 0.1)
    assert t.take(0.1) == [10000]
    t.update(set(), 2.0)                        # gone for 1.9 s
    t.update({10000}, 5.0); t.update({10000}, 5.1)
    assert t.take(5.1) == [10000]


def test_an_arrival_during_other_audio_waits_instead_of_being_lost():
    t = PresenceTracker(min_streak=1, gone_s=4.0, min_gap_s=10.0)
    t.update({"qr"}, 0.0)                       # speaker busy: nobody takes
    t.update({"qr"}, 0.5)
    assert t.take(1.0) == ["qr"]


# ─── the tick ────────────────────────────────────────────────────────────────

class _FakeAudio:
    def __init__(self):
        self.quiet = True
        self.heard = []

    def is_quiet(self):
        return self.quiet

    def queue_system(self, key):
        self.heard.append(("system", key))

    def queue_cue(self, name):
        self.heard.append(("cue", name))

    def queue_info(self, text):
        self.heard.append(("info", text))


class _FakeEngine:
    def __init__(self):
        self.money = []
        self.qr = None
        self.sighting = None
        self.looks = []
        self.photos = []

    def capture_and_infer(self):
        return None, [], {"fps": 15}

    def detect_money(self):
        self.looks.append("money")
        return [{"label": "Uang_50k", "nominal": v, "confidence": 0.8} for v in self.money]

    def locate_qr(self):
        self.looks.append("qr")
        if self.sighting is not None:
            return self.sighting
        return Sighting(0.5, 0.5, 0.6, self.qr) if self.qr else None

    def save_guide_photo(self, cue):
        self.photos.append(cue)


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _FakeOrch:
    def __init__(self):
        self.ai_engine = _FakeEngine()
        self.audio_manager = _FakeAudio()
        self.logger = _NullLogger()
        self.cloud = None
        self.pay = PayScanner()
        self.detections = []
        self.latency = {}


def _ticks(orch, n):
    for _ in range(n):
        run_pay_tick(orch)


def test_frames_alternate_between_banknote_and_qr():
    orch = _FakeOrch()
    _ticks(orch, 6)
    assert orch.ai_engine.looks == ["money", "qr"] * 3


def test_a_banknote_is_named_from_its_offline_cue():
    orch = _FakeOrch()
    orch.ai_engine.money = [50000]
    _ticks(orch, 10)
    assert orch.audio_manager.heard == [("system", "lima_puluh_ribu_rupiah")]


def test_two_notes_at_once_are_named_largest_first():
    orch = _FakeOrch()
    orch.ai_engine.money = [5000, 20000]
    _ticks(orch, 10)
    assert orch.audio_manager.heard == [("system", "dua_puluh_ribu_rupiah"),
                                        ("system", "lima_ribu_rupiah")]


def test_a_qris_code_is_read_out_with_its_merchant():
    orch = _FakeOrch()
    orch.ai_engine.qr = QRIS
    _ticks(orch, 4)
    heard = orch.audio_manager.heard
    assert heard[0] == ("cue", "chime_success.wav")
    assert heard[1][0] == "info" and "WARUNG BU SRI" in heard[1][1]
    assert "25.000 rupiah" in heard[1][1]
    # Then the guide: centred and readable is "scan now". Said once while held up.
    assert heard[2:] == [("cue", "chime_success.wav"), ("system", CUE_READY)]


def test_another_qr_is_called_not_a_payment_code():
    orch = _FakeOrch()
    orch.ai_engine.qr = "https://example.com/menu"
    _ticks(orch, 2)
    assert orch.audio_manager.heard == [("system", "bukan_kode_pembayaran")]


def test_a_code_too_far_to_read_is_still_pointed_at():
    orch = _FakeOrch()
    orch.ai_engine.sighting = Sighting(0.9, 0.9, 0.1, None)
    _ticks(orch, 2)
    assert orch.audio_manager.heard == [("system", "kode_di_kanan_bawah")]
    assert orch.ai_engine.photos == ["kode_di_kanan_bawah"]


def test_no_banknote_is_named_while_a_code_is_in_view():
    orch = _FakeOrch()
    orch.ai_engine.money = [50000]
    orch.ai_engine.sighting = Sighting(0.5, 0.5, 0.1, None)
    _ticks(orch, 10)
    assert ("system", "lima_puluh_ribu_rupiah") not in orch.audio_manager.heard


def test_directions_wait_for_a_quiet_speaker():
    orch = _FakeOrch()
    orch.ai_engine.sighting = Sighting(0.1, 0.5, 0.1, None)
    orch.audio_manager.quiet = False
    _ticks(orch, 6)
    assert orch.audio_manager.heard == []
    orch.audio_manager.quiet = True
    _ticks(orch, 1)
    assert orch.audio_manager.heard == [("system", "kode_di_kiri")]


def test_nothing_is_said_over_other_audio():
    orch = _FakeOrch()
    orch.audio_manager.quiet = False
    orch.ai_engine.money = [100000]
    _ticks(orch, 10)
    assert orch.audio_manager.heard == []
    orch.audio_manager.quiet = True
    _ticks(orch, 1)
    assert orch.audio_manager.heard == [("system", "seratus_ribu_rupiah")]


# ─── the model follows the mode ──────────────────────────────────────────────

class _RecordingEngine:
    def __init__(self):
        self.calls = []

    def reload_model(self, *args):
        self.calls.append(("reload",) + args)

    def release_model(self):
        self.calls.append(("release",))

    def ensure_qr_detector(self):
        self.calls.append(("qr-load",))

    def release_qr_detector(self):
        self.calls.append(("qr-release",))


@pytest.fixture
def orch(monkeypatch, tmp_path):
    import config as config_mod
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", tmp_path / "config.json")
    o = Orchestrator(_NullLogger())
    o.audio_manager = None
    return o


def test_scan_bayar_swaps_in_the_banknote_model(orch):
    from config import cfg
    engine = _RecordingEngine()
    orch.ai_engine = engine
    orch._sync_engine_to_mode("qris")
    orch._sync_engine_to_mode("explorer")
    orch._sync_engine_to_mode("context")
    assert engine.calls == [
        ("reload", cfg.get("money_model_path"), "money"),
        ("qr-load",),
        ("reload", cfg.get("model_path"), "nav"),
        ("qr-release",),
        ("release",),
        ("qr-release",),
    ]


def test_action_in_scan_bayar_asks_the_guide_and_never_calls_the_cloud(orch):
    from config import cfg
    cfg.update({"setup_completed": True})
    orch._mode = "qris"
    orch._on_action_button(long_press=False, in_volume=False)
    assert orch.pop_pending_command() is None
    assert orch.pay.guide.next_cue(0.0) == "belum_ada_kode_terlihat"


def test_switching_mode_forgets_what_scan_bayar_already_said(orch):
    orch.pay.money.update({50000}, 0.0)
    orch.pay.money.update({50000}, 0.1)
    orch.pay.money.update({50000}, 0.2)
    orch.switch_mode("qris")
    assert orch.pay.money.present == set()
