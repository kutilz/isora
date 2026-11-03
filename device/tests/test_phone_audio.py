"""Listening on the phone (/dengar) — core/phone_audio.py + its two consumers.

The feature exists so a presentation, or a user with Bluetooth earphones paired
to their phone, is not stuck with the device's small speaker. What these tests
pin down is the part that matters for a blind user: the FAIL-SAFE. A phone that
stops polling must hand the voice back to the device speaker within seconds,
and nothing about the feature may cost anything while nobody is listening.
"""

import json
import struct
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

import core.audio_manager as am_mod
import core.phone_audio as pa_mod
from core.phone_audio import PhoneAudio, wav_bytes


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _pcm(seconds):
    n = int(48000 * 2 * seconds)
    return bytes((i * 7 + 11) & 0xFF for i in range(n))


# ─── PhoneAudio ──────────────────────────────────────────────────────────────

def test_nobody_listening_costs_nothing():
    pa = PhoneAudio()
    assert pa.publish(_pcm(1.0), "orang di depan") is None
    assert pa.clip(1) is None
    assert not pa.listening()
    assert not pa.device_muted()


def test_a_listening_phone_receives_each_clip_as_wav():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    cid = pa.publish(_pcm(1.0), "orang di depan")
    got = pa.poll("hp1", 0, mute=True, hold_s=0)
    assert [e["type"] for e in got["events"]] == ["clip"]
    ev = got["events"][0]
    assert ev["id"] == cid and ev["text"] == "orang di depan"
    assert 990 <= ev["ms"] <= 1010
    wav = pa.clip(cid)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    rate = struct.unpack("<I", wav[24:28])[0]
    assert rate in (24000, 48000)
    assert abs((len(wav) - 44) - rate * 2) <= 8, "one second of mono s16 audio"


def test_wav_header_matches_payload():
    wav = wav_bytes(b"\x01\x00" * 100, 24000)
    assert struct.unpack("<I", wav[4:8])[0] == len(wav) - 8
    assert struct.unpack("<I", wav[40:44])[0] == 200


def test_a_phone_that_stops_polling_expires_and_unmutes_the_device():
    clock = _Clock()
    pa = PhoneAudio(clock=clock)
    pa.poll("hp1", -1, mute=True, hold_s=0)
    assert pa.device_muted()
    clock.t += pa_mod._ALIVE_S - 0.1
    assert pa.device_muted(), "still inside the alive window"
    clock.t += 0.2
    assert not pa.listening()
    assert not pa.device_muted(), "a vanished phone must give the voice back"
    assert pa.publish(_pcm(0.5)) is None


def test_mute_is_the_phones_choice():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=False, hold_s=0)
    assert pa.listening() and not pa.device_muted()


def test_leaving_unmutes_immediately():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    pa.leave("hp1")
    assert not pa.device_muted()


def test_old_clips_are_evicted():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    ids = [pa.publish(_pcm(0.2)) for _ in range(pa_mod._MAX_CLIPS + 2)]
    assert pa.clip(ids[0]) is None
    assert pa.clip(ids[-1]) is not None


def test_byte_budget_keeps_at_least_the_newest_clip():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    big = pa.publish(_pcm(40.0))          # bigger than the whole budget on its own
    assert pa.clip(big) is not None


def test_cancel_reaches_the_phone_only_when_someone_listens():
    pa = PhoneAudio()
    pa.cancel()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    seq = pa.poll("hp1", -1, mute=True, hold_s=0)["seq"]
    pa.cancel()
    got = pa.poll("hp1", seq, mute=True, hold_s=0)
    assert [e["type"] for e in got["events"]] == ["stop"]


def test_a_fresh_page_does_not_replay_history():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    pa.publish(_pcm(0.2), "lama")
    got = pa.poll("hp2", -1, mute=True, hold_s=0)
    assert got["events"] == []


def test_page_survives_an_app_restart():
    """The page remembers seq 57; the restarted app counts from 0 again."""
    pa = PhoneAudio()
    got = pa.poll("hp1", 57, mute=True, hold_s=0)       # first poll after restart
    assert got["seq"] == 0, "since > seq is read as 'now', not as 57 clips ahead"
    pa.publish(_pcm(0.2), "baru")
    got = pa.poll("hp1", got["seq"], mute=True, hold_s=0)
    assert [e["text"] for e in got["events"]] == ["baru"]


def test_a_held_poll_wakes_up_on_publish():
    pa = PhoneAudio()
    pa.poll("hp1", -1, mute=True, hold_s=0)
    out = {}

    def _wait():
        t0 = time.monotonic()
        out["r"] = pa.poll("hp1", 0, mute=True, hold_s=3.0)
        out["dt"] = time.monotonic() - t0

    th = threading.Thread(target=_wait)
    th.start()
    time.sleep(0.15)
    pa.publish(_pcm(0.2), "orang")
    th.join(5)
    assert out["r"]["events"], "the poll should return the new clip"
    assert out["dt"] < 2.0, "the poll must not sit out its full hold time"


# ─── AudioManager integration ───────────────────────────────────────────────

class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)

    def strftime(self, *a):
        return time.strftime(*a)


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def rig(monkeypatch):
    """Fake maix Player (records plays), fake clock, fresh PhoneAudio."""
    plays = []

    class _Player:
        def volume(self, _v=-1):
            raise RuntimeError("Not implemented")

        def play(self, data):
            plays.append(bytes(data))

    audio_mod = types.ModuleType("maix.audio")
    audio_mod.Player = _Player
    maix_mod = types.ModuleType("maix")
    maix_mod.audio = audio_mod
    monkeypatch.setitem(sys.modules, "maix", maix_mod)
    monkeypatch.setitem(sys.modules, "maix.audio", audio_mod)
    monkeypatch.setattr(am_mod, "time", _FakeClock())
    pa = PhoneAudio()
    monkeypatch.setattr(pa_mod, "phone_audio", pa)

    stub = types.SimpleNamespace()
    stub._interrupt = threading.Event()
    stub._stop = threading.Event()
    stub.logger = _NullLogger()
    stub._current_text = "kursi di kanan"
    stub._hold_for_phone = lambda n: am_mod.AudioManager._hold_for_phone(stub, n)
    return types.SimpleNamespace(plays=plays, pa=pa, am=stub)


def _play(rig, pcm):
    return am_mod.AudioManager._play_pcm_bytes(rig.am, pcm)


def test_without_a_phone_the_speaker_plays_as_before(rig):
    assert _play(rig, _pcm(1.0)) is True
    assert rig.plays, "device speaker must play when no phone listens"


def test_muted_phone_session_keeps_the_speaker_silent_but_paced(rig):
    rig.pa.poll("hp1", -1, mute=True, hold_s=0)
    t0 = am_mod.time.monotonic()
    assert _play(rig, _pcm(2.0)) is True
    assert rig.plays == [], "the device speaker must stay quiet"
    held = am_mod.time.monotonic() - t0
    assert held >= 2.0, "the queue must still wait the clip out (%.2fs)" % held
    got = rig.pa.poll("hp1", 0, mute=True, hold_s=0)
    assert got["events"][0]["text"] == "kursi di kanan"


def test_both_mode_plays_on_device_and_phone(rig):
    rig.pa.poll("hp1", -1, mute=False, hold_s=0)
    _play(rig, _pcm(1.0))
    assert rig.plays
    assert rig.pa.poll("hp1", 0, mute=False, hold_s=0)["events"]


def test_barge_in_while_held_stops_the_phone_too(rig):
    rig.pa.poll("hp1", -1, mute=True, hold_s=0)
    rig.am._interrupt.set()
    _play(rig, _pcm(3.0))
    types_ = [e["type"] for e in rig.pa.poll("hp1", 0, mute=True, hold_s=0)["events"]]
    assert types_ == ["clip", "stop"]


# ─── HTTP endpoints ──────────────────────────────────────────────────────────

@pytest.fixture
def server(monkeypatch):
    from server.web_server import IsoraHandler
    pa = PhoneAudio()
    monkeypatch.setattr(pa_mod, "phone_audio", pa)
    handler = partial(IsoraHandler, types.SimpleNamespace(), _NullLogger(), None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield types.SimpleNamespace(base="http://127.0.0.1:%d" % srv.server_port, pa=pa)
    srv.shutdown()
    srv.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def test_listen_page_is_served(server):
    status, ctype, body = _get(server.base + "/dengar")
    assert status == 200 and "text/html" in ctype
    assert b"/listen/poll" in body


def test_poll_endpoint_registers_the_phone_and_delivers_clips(server):
    status, _, body = _get(server.base + "/listen/poll?client=hp-1&since=-1&mute=1")
    first = json.loads(body)
    assert status == 200 and server.pa.device_muted()
    cid = server.pa.publish(_pcm(0.5), "motor di kiri")
    _, _, body = _get(server.base + "/listen/poll?client=hp-1&since=%d&mute=1" % first["seq"])
    ev = json.loads(body)["events"][0]
    assert ev["id"] == cid
    status, ctype, wav = _get(server.base + "/listen/clip/%d.wav" % cid)
    assert status == 200 and ctype == "audio/wav" and wav[:4] == b"RIFF"


def test_poll_without_client_is_refused(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server.base + "/listen/poll?since=-1")
    assert e.value.code == 400


def test_expired_clip_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server.base + "/listen/clip/999.wav")
    assert e.value.code == 404


def test_leave_endpoint_unmutes(server):
    _get(server.base + "/listen/poll?client=hp-1&since=-1&mute=1")
    req = urllib.request.Request(server.base + "/listen/leave",
                                 data=json.dumps({"client": "hp-1"}).encode(),
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert json.loads(r.read())["ok"] is True
    assert not server.pa.device_muted()
