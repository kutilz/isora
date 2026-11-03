"""The heartbeat has to say whether this device is actually ready to use.

Pairing completes on the device the instant the ACTION button is pressed; the
settings that follow come from a phone that may close the page halfway. Nothing
on the relay remembers a half-finished setup, so unless the device reports it,
the web app cannot tell "linked and ready" from "linked and still waiting" —
and the person is the one left holding a device with no visible next step.

Two flags carry that: `setup_completed` (mirrored from config) and `ai_ready`
(does the provider actually in use have a key). Both are booleans; the key
itself never leaves the device.
"""

import pytest

from config import cfg
from core import cloud


class _Logger:
    def info(self, *a, **k): pass
    def warn(self, *a, **k): pass
    def ok(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Orch:
    def __init__(self, **status):
        self._status = status

    def get_status(self):
        return dict(self._status)


def _client(orch):
    c = cloud.CloudClient(orch, _Logger())
    sent = {}

    def fake_req(method, path, body=None, auth=False, timeout=None):
        sent["path"] = path
        sent["body"] = body
        return 200, {"paired": True}

    c._req = fake_req
    return c, sent


def test_heartbeat_reports_unfinished_setup(monkeypatch):
    monkeypatch.setattr(cloud, "_ai_key_present", lambda: False)
    c, sent = _client(_Orch(mode="idle", setup_completed=False))

    c._heartbeat()

    status = sent["body"]["status"]
    assert sent["path"] == "/api/heartbeat"
    assert status["setup_completed"] is False
    assert status["ai_ready"] is False


def test_heartbeat_reports_finished_setup(monkeypatch):
    monkeypatch.setattr(cloud, "_ai_key_present", lambda: True)
    c, sent = _client(_Orch(mode="idle", setup_completed=True))

    c._heartbeat()

    status = sent["body"]["status"]
    assert status["setup_completed"] is True
    assert status["ai_ready"] is True


def test_flags_are_json_booleans_not_none(monkeypatch):
    """A device that reports nothing must not read as `false` on the web.

    `undefined` (absent) means "old firmware, don't nag"; `null` would serialize
    into the same JSON slot as a real answer, so the value is always a bool.
    """
    monkeypatch.setattr(cloud, "_ai_key_present", lambda: False)
    c, sent = _client(_Orch(mode="idle"))  # no setup_completed at all

    c._heartbeat()

    assert sent["body"]["status"]["setup_completed"] is False


@pytest.mark.parametrize(
    "provider, keys, expected",
    [
        ("openai", {"OPENAI_API_KEY": "sk-x"}, True),
        ("openai", {}, False),
        ("gemini", {"GEMINI_API_KEY": "AIza-x"}, True),
        ("gemini", {"OPENAI_API_KEY": "sk-x"}, False),   # wrong provider's key
        ("claude", {"CLAUDE_API_KEY": "sk-ant-x"}, True),
        ("claude", {}, False),
    ],
)
def test_ai_ready_follows_the_selected_provider(monkeypatch, provider, keys, expected):
    klass = type(cfg)
    monkeypatch.setattr(klass, "AI_PROVIDER", property(lambda self: provider))
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "CLAUDE_API_KEY"):
        monkeypatch.setattr(klass, name, property(lambda self, n=name: keys.get(n, "")))

    assert cloud._ai_key_present() is expected
