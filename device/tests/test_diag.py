"""The logs have to answer what could not be answered on 3 Nov 2026."""

import io
import json
import threading
import urllib.error

import pytest

from adapters.base import AdapterError
from adapters.openai_adapter import OpenAIAdapter
from core.phone_audio import PhoneAudio
from core.orchestrator import Orchestrator
from utils import diag, tts


class Log:
    def __init__(self):
        self.lines = []

    def _add(self, level, msg, module=""):
        self.lines.append((level, msg))

    def info(self, msg, module=""): self._add("info", msg)
    def warn(self, msg, module=""): self._add("warn", msg)
    def error(self, msg, module=""): self._add("error", msg)

    def of(self, kind):
        return [(l, m) for l, m in self.lines if m.startswith(f"[diag] {kind}")]


@pytest.fixture
def log(monkeypatch):
    sink = Log()
    monkeypatch.setattr(diag, "_logger", sink)
    return sink


class Cfg:
    AI_TIMEOUT_S = 5

    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


# ── AI calls: the model's clock against the wall clock ───────────────────────

class Resp(io.BytesIO):
    headers = {"openai-processing-ms": "4200", "x-request-id": "req_1"}

    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_a_slow_answer_can_be_split_into_model_and_link(log, monkeypatch):
    body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 3000, "input_tokens_details": {"cached_tokens": 2900},
                      "output_tokens": 150, "output_tokens_details": {"reasoning_tokens": 130}}}
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout: Resp(json.dumps(body).encode()))
    assert OpenAIAdapter(Cfg())._post({"model": "m"}, "sk-secret", 5) == "ok"

    (_, line), = log.of("ai_call")
    assert "server_s=4.2" in line and "net_s=" in line
    assert "reason_tok=130" in line and "out_tok=150" in line and "req=req_1" in line
    assert "cached_tok=2900" in line
    assert "sk-secret" not in line


def test_a_timed_out_call_is_logged_with_how_long_it_waited(log, monkeypatch):
    def _timeout(req, timeout):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr("urllib.request.urlopen", _timeout)
    with pytest.raises(AdapterError):
        OpenAIAdapter(Cfg())._post({"model": "m"}, "k", 5)

    (level, line), = log.of("ai_call")
    assert level == "warn"
    assert "ok=False" in line and "total_s=" in line and "timed out" in line


def test_an_http_error_is_logged_once_with_its_code(log, monkeypatch):
    def _denied(req, timeout):
        raise urllib.error.HTTPError("u", 429, "busy", {}, io.BytesIO(b"slow down"))
    monkeypatch.setattr("urllib.request.urlopen", _denied)
    with pytest.raises(AdapterError):
        OpenAIAdapter(Cfg())._post({"model": "m"}, "k", 5)
    assert '"HTTP 429"' in log.of("ai_call")[0][1] and len(log.of("ai_call")) == 1


# ── The SD card going read-only ──────────────────────────────────────────────

MOUNTS = "/dev/mmcblk0p2 / ext4 {},relatime 0 0\n/dev/mmcblk0p1 /boot vfat rw 0 0\n"


@pytest.mark.parametrize("flag, mode", [("rw", "rw"), ("ro", "ro")])
def test_root_mode_reads_the_root_line_only(tmp_path, flag, mode):
    p = tmp_path / "mounts"
    p.write_text(MOUNTS.format(flag))
    assert diag.root_mode(str(p)) == mode


def test_root_mode_is_unknown_without_the_file(tmp_path):
    assert diag.root_mode(str(tmp_path / "missing")) == "?"


def test_going_read_only_is_an_error_said_once_with_the_kernel_lines(log, monkeypatch):
    modes = iter(["rw", "ro", "ro", "rw"])
    monkeypatch.setattr(diag, "sd_kernel_errors", lambda: ["EXT4-fs error (mmcblk0p2)"])
    sampler = diag.Sampler(read_root=lambda: next(modes))
    for _ in range(4):
        sampler.check_root()

    (level, _), = log.of("root_ro")
    assert level == "error"
    assert len(log.of("sd_kernel")) == 1
    assert log.of("root_mode")[0][1].endswith("was=ro now=rw")


def test_a_card_that_never_failed_says_nothing(log):
    sampler = diag.Sampler(read_root=lambda: "rw")
    sampler.check_root()
    sampler.check_root()
    assert log.lines == []


def test_leaving_the_wifi_network_is_flagged(log):
    links = iter([{"ssid": "Galaxy", "dbm": "-40"}, {}])
    sampler = diag.Sampler(read_root=lambda: "rw", read_link=lambda: next(links))
    sampler.sample()
    sampler.sample()
    assert "was=Galaxy now=none" in log.of("wifi_changed")[0][1]


# ── Parsers against real output from the unit ────────────────────────────────

def test_iw_output_is_parsed():
    text = ("Connected to c2:2a:68:a3:83:f4 (on wlan0)\n\tSSID: Galaxy A14 2F6A\n"
            "\tsignal: -65 dBm\n\trx bitrate: 39.0 MBit/s MCS 4\n\ttx bitrate: 19.5 MBit/s MCS 2\n")
    assert diag.parse_iw_link(text) == {"ssid": "Galaxy A14 2F6A", "dbm": "-65",
                                        "rx_mbit": "39.0", "tx_mbit": "19.5"}


def test_ping_time_is_parsed_and_a_lost_ping_is_none():
    assert diag.parse_ping_ms("64 bytes from 1.1.1.1: seq=0 ttl=57 time=36.3 ms") == 36.3
    assert diag.parse_ping_ms("1 packets transmitted, 0 received") is None


def test_gateway_comes_from_the_default_route(tmp_path):
    p = tmp_path / "route"
    p.write_text("Iface\tDestination\tGateway\nwlan0\t00521D0A\t00000000\n"
                 "wlan0\t00000000\tAB521D0A\n")
    assert diag.gateway(str(p)) == "10.29.82.171"


# ── How the previous run ended ───────────────────────────────────────────────

def _write_log(path, msg):
    path.write_text(json.dumps({"ts": "T", "up": 12.5, "msg": "first"}) + "\n"
                    + json.dumps({"ts": "T", "up": 99.5, "msg": msg}) + "\n", encoding="utf-8")


def test_a_run_cut_off_mid_way_is_not_clean(tmp_path):
    _write_log(tmp_path / "isora_00001_20261103_120000.log", "Scene: benda")
    (tmp_path / "isora_00002_20261103_130000.log").write_text("")
    run = diag.previous_run(str(tmp_path))
    assert run["clean"] is False and run["last_up"] == 99.5 and run["last"] == "Scene: benda"


@pytest.mark.parametrize("last", ["Shutdown requested", "I-Sora SDK stopped."])
def test_a_deliberate_stop_is_clean(tmp_path, last):
    _write_log(tmp_path / "isora_00001_20261103_120000.log", last)
    (tmp_path / "isora_00002_20261103_130000.log").write_text("")
    assert diag.previous_run(str(tmp_path))["clean"] is True


def test_a_torn_last_line_does_not_break_the_boot(tmp_path):
    (tmp_path / "isora_00001_20261103_120000.log").write_text('{"ts": "T", "ms')
    (tmp_path / "isora_00002_20261103_130000.log").write_text("")
    assert diag.previous_run(str(tmp_path))["clean"] is False


def test_the_first_run_has_no_previous_run(tmp_path):
    (tmp_path / "isora_00001_20261103_120000.log").write_text("")
    assert diag.previous_run(str(tmp_path)) == {}


# ── gTTS: swallowed errors and timeouts ──────────────────────────────────────

def _fake_gtts(monkeypatch, save):
    import gtts
    class Fake:
        def __init__(self, text, lang, slow): pass
        def save(self, path): save(path)
    monkeypatch.setattr(gtts, "gTTS", Fake)


def test_a_failed_render_says_why(log, monkeypatch, tmp_path):
    pytest.importorskip("gtts")
    def _ro(path):
        raise OSError(30, "Read-only file system")
    _fake_gtts(monkeypatch, _ro)
    assert tts._synthesize("halo", str(tmp_path / "a.wav"), "id", 2.0) is None
    assert "Read-only" in log.of("tts_failed")[0][1]


def test_a_timeout_is_logged_and_a_late_finish_too(log, monkeypatch, tmp_path):
    pytest.importorskip("gtts")
    release, finished = threading.Event(), threading.Event()
    def _slow(path):
        release.wait(5)
        open(path, "wb").close()
    _fake_gtts(monkeypatch, _slow)
    monkeypatch.setattr(diag, "net_probe", lambda reason: finished.set())

    assert tts._synthesize("halo", str(tmp_path / "a.wav"), "id", 0.05) is None
    assert "err=timeout" in log.of("tts_failed")[0][1] and finished.is_set()

    release.set()
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(0.2)
    assert log.of("tts_late")


# ── Phone audio ──────────────────────────────────────────────────────────────

def test_a_phone_that_went_quiet_shows_as_a_gap(log):
    now = [0.0]
    pa = PhoneAudio(clock=lambda: now[0])
    pa.poll("phone-1", -1, True, hold_s=0)
    assert log.of("listen_join")

    now[0] = 8.0
    assert pa.publish(b"\0\0" * 100, "kursi hitam") is None
    assert log.of("listen_expired")
    assert "away_s=8.0" in log.of("listen_gap")[0][1]


def test_a_device_nobody_listens_to_stays_quiet_in_the_log(log):
    pa = PhoneAudio(clock=lambda: 0.0)
    assert pa.publish(b"\0\0" * 100, "kursi") is None
    assert log.lines == []


def test_an_expired_clip_request_is_logged(log):
    pa = PhoneAudio(clock=lambda: 0.0)
    assert pa.clip(7) is None
    assert "id=7" in log.of("listen_clip_miss")[0][1]


# ── Photos: privacy default and the cap ──────────────────────────────────────

def test_no_photo_is_kept_unless_asked(log, tmp_path):
    assert diag.save_frame(b"jpg", Cfg(), str(tmp_path / "d")) == ""
    assert not (tmp_path / "d").exists() and log.lines == []


def _now(fn):
    fn()


ON = Cfg(debug_save_frames=True)


def test_no_photo_on_the_card_is_ever_deleted(log, tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    for i in range(500):
        (d / f"{1000 + i}.jpg").write_bytes(b"old")
    name = diag.save_frame(b"x", ON, "konteks", str(d), str(tmp_path / "r"), _spawn=_now)
    assert len(list(d.glob("*.jpg"))) == 501 and (d / name).exists()


def test_a_photo_is_paired_with_the_answer(log, tmp_path):
    d, r = str(tmp_path / "d"), str(tmp_path / "r")
    name = diag.save_frame(b"x", ON, "konteks", d, r, _spawn=_now)
    diag.frame_result(name, "Kursi hitam di depan.", directory=d, ram_directory=r, _spawn=_now)
    diag.frame_result(name, TimeoutError("timed out"), ok=False, directory=d, ram_directory=r,
                      _spawn=_now)
    assert name.endswith("_konteks.jpg") and (tmp_path / "d" / name).read_bytes() == b"x"
    first, second = (json.loads(l) for l in
                     (tmp_path / "d" / "index.jsonl").read_text(encoding="utf-8").splitlines())
    assert first == {"photo": name, "ok": True, "text": "Kursi hitam di depan."}
    assert second["ok"] is False and "timed out" in second["text"]


def test_nothing_is_paired_when_saving_is_off(tmp_path):
    diag.frame_result("", "teks", directory=str(tmp_path / "d"), ram_directory=str(tmp_path / "r"))
    assert not (tmp_path / "d").exists()


def test_a_read_only_card_keeps_the_photo_in_ram(log, tmp_path):
    card = tmp_path / "file-not-dir"
    card.write_text("")
    r = tmp_path / "r"
    name = diag.save_frame(b"x", ON, "konteks", str(card / "d"), str(r), _spawn=_now)
    assert (r / name).read_bytes() == b"x"
    assert log.of("frame_in_ram")[0][0] == "warn"


def test_a_full_card_keeps_the_photo_in_ram(log, tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "_free_mb", lambda path: 5.0)
    r = tmp_path / "r"
    name = diag.save_frame(b"x", ON, "konteks", str(tmp_path / "d"), str(r), _spawn=_now)
    assert (r / name).exists() and not (tmp_path / "d" / name).exists()
    assert "nearly full" in log.of("frame_in_ram")[0][1]


def test_ram_holds_a_bounded_number_of_photos(log, tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "_free_mb", lambda path: 5.0)
    monkeypatch.setattr(diag, "_FRAMES_RAM_MAX", 2)
    r = tmp_path / "r"
    r.mkdir()
    for i in range(3):
        (r / f"100{i}.jpg").write_bytes(b"old")
    diag.save_frame(b"x", ON, "konteks", str(tmp_path / "d"), str(r), _spawn=_now)
    assert len(list(r.glob("*.jpg"))) == 2


def test_losing_both_places_is_an_error_not_a_crash(log, tmp_path):
    bad = tmp_path / "file-not-dir"
    bad.write_text("")
    diag.save_frame(b"x", ON, "konteks", str(bad / "a"), str(bad / "b"), _spawn=_now)
    assert log.of("frame_not_saved")[0][0] == "error"


# ── Presses: the one pending-command slot ────────────────────────────────────

class _Slot:
    _lock = threading.Lock()
    _pending_command = None
    set_pending_command = Orchestrator.set_pending_command
    pop_pending_command = Orchestrator.pop_pending_command


def test_a_press_overwriting_a_waiting_one_is_logged(log):
    slot = _Slot()
    slot.set_pending_command("describe")
    assert not log.of("press_merged")
    slot.set_pending_command("describe")
    assert "replaced=describe" in log.of("press_merged")[0][1]
    assert slot.pop_pending_command()["cmd"] == "describe"
    assert "waited_s=" in log.of("press_run")[0][1]
    assert slot.pop_pending_command() is None and len(log.of("press_run")) == 1


# ── It must never get in the way ─────────────────────────────────────────────

def test_events_before_the_logger_exists_are_ignored(monkeypatch):
    monkeypatch.setattr(diag, "_logger", None)
    diag.event("anything", a=1)


def test_a_broken_logger_does_not_propagate(monkeypatch):
    class Broken:
        def info(self, *a, **k):
            raise OSError("disk gone")
    monkeypatch.setattr(diag, "_logger", Broken())
    diag.event("anything", a=1)
