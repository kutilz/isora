"""Mode PIMNAS: the event profile and the typed speech-preset buttons.

The promise to the operator is narrow and must hold exactly: a preset made
while there was internet plays later with none; the profile never lets the
device restart or load itself mid-demo; and a describe the network fails says
what the camera really sees instead of going quiet.
"""

import json
import threading
import types
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from config import cfg
from utils.speech_presets import SpeechPresets, PresetError, MAX_PRESETS, PCM_BYTES_S
import utils.speech_presets as sp_mod


def _render_ok(text):
    return b"\x01\x00" * 48000, "online"       # exactly 1 s of audio


def _render_fail(text):
    return None, ""


@pytest.fixture
def mem_cfg(monkeypatch):
    """cfg that changes in memory only — never the real config.json."""
    monkeypatch.setattr(cfg, "_data", dict(cfg._data))
    monkeypatch.setattr(cfg, "update", lambda m: cfg._data.update(m))
    return cfg


# ─── speech presets ──────────────────────────────────────────────────────────

def test_preset_is_rendered_once_and_plays_from_disk(tmp_path):
    store = SpeechPresets(str(tmp_path))
    calls = []

    def render(text):
        calls.append(text)
        return _render_ok(text)

    e = store.add("  di depan ada   juri  ", render)
    assert e["text"] == "di depan ada juri"            # whitespace tidied
    assert e["seconds"] == 1.0 and e["source"] == "online"
    assert store.pcm(e["id"]) == b"\x01\x00" * 48000
    assert [p["id"] for p in store.list()] == [e["id"]]
    store.pcm(e["id"])
    assert calls == ["di depan ada juri"], "playing must never re-render"


def test_presets_survive_a_restart(tmp_path):
    a = SpeechPresets(str(tmp_path)).add("satu", _render_ok)
    again = SpeechPresets(str(tmp_path))
    assert again.get(a["id"])["text"] == "satu"


def test_failed_render_leaves_no_button(tmp_path):
    store = SpeechPresets(str(tmp_path))
    with pytest.raises(PresetError, match="internet"):
        store.add("halo", _render_fail)
    assert store.list() == []


@pytest.mark.parametrize("text", ["", "   ", None, "x" * 301])
def test_bad_text_is_refused_before_rendering(tmp_path, text):
    store = SpeechPresets(str(tmp_path))
    with pytest.raises(PresetError):
        store.add(text, lambda t: pytest.fail("rendered a refused text"))


def test_list_is_capped(tmp_path):
    store = SpeechPresets(str(tmp_path))
    for i in range(MAX_PRESETS):
        store.add("kalimat %d" % i, _render_ok)
    with pytest.raises(PresetError, match="Hapus"):
        store.add("satu lagi", _render_ok)


def test_delete_and_reorder(tmp_path):
    store = SpeechPresets(str(tmp_path))
    a, b, c = (store.add(t, _render_ok) for t in ("a", "b", "c"))
    assert store.move(c["id"], -1)
    assert [p["text"] for p in store.list()] == ["a", "c", "b"]
    assert not store.move(a["id"], -1), "already at the top"
    assert store.delete(b["id"])
    assert not (tmp_path / (b["id"] + ".pcm")).exists()
    assert [p["text"] for p in store.list()] == ["a", "c"]
    assert not store.delete(b["id"])


@pytest.mark.parametrize("pid", ["../index", "a/b", "", None, "x" * 40])
def test_ids_cannot_reach_outside_the_folder(tmp_path, pid):
    store = SpeechPresets(str(tmp_path))
    assert store.pcm(pid) is None
    assert store.delete(pid) is False


def test_corrupt_index_reads_as_empty(tmp_path):
    (tmp_path / "index.json").write_text("{not json")
    store = SpeechPresets(str(tmp_path))
    assert store.list() == []
    store.add("pulih", _render_ok)
    assert [p["text"] for p in store.list()] == ["pulih"]


def test_presets_live_outside_the_pruned_tts_cache():
    assert cfg.get("speech_presets_dir") != cfg.get("tts_cache_dir")


# ─── the event profile ───────────────────────────────────────────────────────

def test_event_mode_shortens_the_ai_timeout(mem_cfg):
    mem_cfg.update({"ai_timeout_s": 15, "event_ai_timeout_s": 10, "event_mode": False})
    assert mem_cfg.AI_TIMEOUT_S == 15
    mem_cfg.update({"event_mode": True})
    assert mem_cfg.AI_TIMEOUT_S == 10
    mem_cfg.update({"event_ai_timeout_s": "garbage"})
    assert mem_cfg.AI_TIMEOUT_S == 10
    mem_cfg.update({"ai_timeout_s": 6, "event_ai_timeout_s": 10})
    assert mem_cfg.AI_TIMEOUT_S == 6, "never longer than the everyday timeout"


def test_event_mode_must_be_a_real_true(mem_cfg):
    mem_cfg.update({"event_mode": "false"})
    assert mem_cfg.EVENT_MODE is False


def test_context_keeps_the_nav_model_only_in_event_mode(mem_cfg):
    from core.orchestrator import Orchestrator
    mem_cfg.update({"event_mode": False})
    assert Orchestrator.model_for_mode("context") is None
    mem_cfg.update({"event_mode": True})
    assert Orchestrator.model_for_mode("context") == Orchestrator.model_for_mode("explorer")
    assert Orchestrator.model_for_mode("idle") is None


# ─── offline fallback after a failed describe ────────────────────────────────

def _engine(loaded=True, role="nav", dets=None):
    spoken = []
    am = types.SimpleNamespace(
        announce_detections=lambda d, force=False: spoken.append((list(d), force)))
    eng = types.SimpleNamespace(
        _lock=threading.Lock(), _model_loaded=loaded, _model_role=role,
        capture_and_infer=lambda: (b"", list(dets or []), {}),
        orch=types.SimpleNamespace(audio_manager=am),
        logger=types.SimpleNamespace(info=lambda *a, **k: None,
                                     warn=lambda *a, **k: None))
    return eng, spoken


def test_fallback_reads_real_detections_in_event_mode(mem_cfg):
    from core.ai_engine import AIEngine
    mem_cfg.update({"event_mode": True})
    det = [{"label": "person", "position": "tengah"}]
    eng, spoken = _engine(dets=det)
    assert AIEngine._offline_fallback(eng) == 1
    assert spoken == [(det, True)]


def test_fallback_is_off_outside_event_mode(mem_cfg):
    from core.ai_engine import AIEngine
    mem_cfg.update({"event_mode": False})
    eng, spoken = _engine(dets=[{"label": "person", "position": "tengah"}])
    assert AIEngine._offline_fallback(eng) == 0 and spoken == []


@pytest.mark.parametrize("loaded,role,dets", [
    (False, "nav", [{"label": "person"}]),        # no model on the NPU
    (True, "money", [{"label": "person"}]),       # banknote model is not nav
    (True, "nav", []),                            # nothing in view: say nothing
])
def test_fallback_says_nothing_it_did_not_see(mem_cfg, loaded, role, dets):
    from core.ai_engine import AIEngine
    mem_cfg.update({"event_mode": True})
    eng, spoken = _engine(loaded, role, dets)
    assert AIEngine._offline_fallback(eng) == 0 and spoken == []


# ─── operator endpoints ──────────────────────────────────────────────────────

class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Audio:
    def __init__(self):
        self.queued, self.cleared = [], 0

    def render_text_pcm(self, text):
        return b"\x00" * PCM_BYTES_S, "online"     # exactly 1 s

    def queue_pcm_bytes(self, pcm, text, priority=3, label=""):
        self.queued.append((text, len(pcm), priority))

    def clear(self):
        self.cleared += 1

    def queue_cue(self, *a, **k):
        pass

    def queue_system(self, *a, **k):
        pass


@pytest.fixture
def server(monkeypatch, tmp_path, mem_cfg):
    from server.web_server import IsoraHandler
    from core.orchestrator import Orchestrator
    monkeypatch.setattr(sp_mod, "_instance", SpeechPresets(str(tmp_path)))
    am = _Audio()
    orch = types.SimpleNamespace(
        MODES=Orchestrator.MODES, audio_manager=am, commands=[], presses=[],
        set_pending_command=lambda c, d=None: orch.commands.append((c, d)),
        note_press=lambda *a: orch.presses.append(a),
        note_user_interaction=lambda w=None: None)
    handler = partial(IsoraHandler, orch, _NullLogger(), None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(base="http://127.0.0.1:%d" % srv.server_port,
                                am=am, orch=orch)
    srv.shutdown()
    srv.server_close()


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.status, r.read()


def test_type_a_sentence_then_play_it(server):
    code, d = _post(server.base, "/pimnas/presets", {"text": "Di depan ada juri"})
    assert code == 200 and d["preset"]["seconds"] == 1.0
    code, body = _get(server.base, "/pimnas/presets")
    [p] = json.loads(body)["presets"]
    code, d = _post(server.base, "/pimnas/presets/play", {"id": p["id"]})
    assert code == 200 and d["ok"]
    assert server.am.cleared == 1
    assert server.am.queued == [("Di depan ada juri", PCM_BYTES_S, 1)]


def test_empty_sentence_is_a_400_not_a_crash(server):
    code, d = _post(server.base, "/pimnas/presets", {"text": "  "})
    assert code == 400 and "kosong" in d["error"].lower()


def test_unknown_preset_is_404(server):
    code, _ = _post(server.base, "/pimnas/presets/play", {"id": "abc123"})
    assert code == 404


def test_mode_buttons_queue_a_mode_change(server):
    code, _ = _post(server.base, "/pimnas/mode", {"mode": "context"})
    assert code == 200
    assert server.orch.commands == [("set_mode", {"mode": "context"})]
    code, _ = _post(server.base, "/pimnas/mode", {"mode": "shutdown"})
    assert code == 400


def test_event_switch_locks_dev_tools(server, mem_cfg):
    code, d = _post(server.base, "/pimnas/event", {"on": True})
    assert code == 200 and mem_cfg.EVENT_MODE
    code, d = _post(server.base, "/collect/start", {})
    assert code == 423 and "PIMNAS" in d["error"]
    _post(server.base, "/pimnas/event", {"on": False})
    assert not mem_cfg.EVENT_MODE


def test_volume_is_clamped(server, mem_cfg):
    mem_cfg.update({"audio_volume": 95})
    code, d = _post(server.base, "/pimnas/volume", {"delta": 10})
    assert d["audio_volume"] == 100
    mem_cfg.update({"audio_volume": 25})
    code, d = _post(server.base, "/pimnas/volume", {"delta": -10})
    assert d["audio_volume"] == 20, "the page never mutes the device outright"


def test_operator_page_is_served(server):
    code, body = _get(server.base, "/pimnas")
    assert code == 200 and b"Mode PIMNAS" in body
