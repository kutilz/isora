"""Request-shape guards for the AI vision adapters.

These payloads are only ever exercised against the live APIs on the device, so
the shape itself is what gets tested here: a wrong field is a 400 that takes
vision down completely for a blind user, with no fallback path.
"""

import json

import pytest

from adapters.gemini_adapter import GeminiAdapter
from adapters.openai_adapter import OpenAIAdapter


class FakeCfg:
    """Stands in for the Config singleton (adapters get the real one)."""

    def __init__(self, **over):
        self._d = dict(over)

    def get(self, key, default=None):
        return self._d.get(key, default)

    # Typed properties the adapters read directly.
    OPENAI_API_KEY = "sk-test"
    GEMINI_API_KEY = "AIza-test"

    @property
    def AI_TIMEOUT_S(self):
        return 15

    @property
    def AI_TEMPERATURE(self):
        return float(self._d.get("ai_temperature", 0.0))


def _capture(monkeypatch, module):
    """Intercept the urlopen call and return the decoded request payload."""
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return seen["response"]

    def fake_urlopen(req, timeout=None):
        seen["payload"] = json.loads(req.data.decode())
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    return seen


# ── OpenAI: `reasoning` is rejected by the non-reasoning models ───────────────

@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"])
def test_no_reasoning_block_for_non_reasoning_models(monkeypatch, model):
    # A device provisioned before the gpt-5.6 default still has gpt-4o-mini in
    # /root/config.json, and _load merges the saved file OVER _DEFAULTS. Sending
    # `reasoning` to it is an HTTP 400 on every single press.
    from adapters import openai_adapter

    seen = _capture(monkeypatch, openai_adapter)
    seen["response"] = json.dumps({
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "ok"}]}]
    }).encode()

    OpenAIAdapter(FakeCfg(openai_model=model)).describe_scene(b"", "p")

    assert "reasoning" not in seen["payload"]
    # No thinking means no thinking budget to pay for either.
    assert seen["payload"]["max_output_tokens"] == 220


@pytest.mark.parametrize("model", ["gpt-5.6-terra", "gpt-5-mini", "o3", "o4-mini"])
def test_reasoning_block_present_for_reasoning_models(monkeypatch, model):
    from adapters import openai_adapter

    seen = _capture(monkeypatch, openai_adapter)
    seen["response"] = json.dumps({
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "ok"}]}]
    }).encode()

    OpenAIAdapter(FakeCfg(openai_model=model)).describe_scene(b"", "p")

    assert seen["payload"]["reasoning"] == {"effort": "low"}


def test_reasoning_headroom_scales_with_effort(monkeypatch):
    # Reasoning tokens are billed against max_output_tokens. A flat +512 is fine
    # for "low" but leaves a high-effort pass no room for the visible answer —
    # the response comes back with only a reasoning item and _extract_text raises.
    from adapters import openai_adapter

    caps = {}
    for effort in ("low", "high", "xhigh"):
        seen = _capture(monkeypatch, openai_adapter)
        seen["response"] = json.dumps({
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": "ok"}]}]
        }).encode()
        OpenAIAdapter(
            FakeCfg(openai_model="gpt-5.6-terra", openai_reasoning_effort=effort)
        ).describe_scene(b"", "p")
        caps[effort] = seen["payload"]["max_output_tokens"]

    assert caps["low"] < caps["high"] < caps["xhigh"]


# ── Gemini: the cap has to survive models whose thinking can't be silenced ────

def test_thinking_disabled_keeps_the_tight_cap(monkeypatch):
    from adapters import gemini_adapter

    seen = _capture(monkeypatch, gemini_adapter)
    seen["response"] = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
    }).encode()

    GeminiAdapter(FakeCfg(gemini_model="gemini-2.5-flash")).describe_scene(b"", "p")

    cfg = seen["payload"]["generationConfig"]
    assert cfg["thinkingConfig"] == {"thinkingBudget": 0}
    assert cfg["maxOutputTokens"] == 220


@pytest.mark.parametrize("model", ["gemini-2.5-pro", "gemini-3-flash"])
def test_unsilenceable_thinking_keeps_headroom(monkeypatch, model):
    # 2.5-pro rejects a 0 budget and a future family won't match the "2.5" test,
    # so both still think. Spending the whole 220-token cap on hidden thoughts
    # returns finishReason=MAX_TOKENS — half a sentence in a blind user's ear.
    from adapters import gemini_adapter

    seen = _capture(monkeypatch, gemini_adapter)
    seen["response"] = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
    }).encode()

    GeminiAdapter(FakeCfg(gemini_model=model)).describe_scene(b"", "p")

    cfg = seen["payload"]["generationConfig"]
    assert "thinkingConfig" not in cfg
    assert cfg["maxOutputTokens"] > 220


def test_non_thinking_model_gets_no_thinking_config(monkeypatch):
    # thinkingConfig on 1.5/2.0 is an HTTP 400.
    from adapters import gemini_adapter

    seen = _capture(monkeypatch, gemini_adapter)
    seen["response"] = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
    }).encode()

    GeminiAdapter(FakeCfg(gemini_model="gemini-1.5-flash")).describe_scene(b"", "p")

    cfg = seen["payload"]["generationConfig"]
    assert "thinkingConfig" not in cfg
    assert cfg["maxOutputTokens"] == 220


# ── Deterministic decoding: same scene, same sentence ────────────────────────

def test_non_reasoning_openai_model_gets_the_temperature(monkeypatch):
    # A describe pressed twice on an unchanged scene must not come back
    # re-worded — that reads as a changed world to someone who cannot check.
    from adapters import openai_adapter

    seen = _capture(monkeypatch, openai_adapter)
    seen["response"] = json.dumps({
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "ok"}]}]
    }).encode()

    OpenAIAdapter(FakeCfg(openai_model="gpt-4o-mini")).describe_scene(b"", "p")

    assert seen["payload"]["temperature"] == 0.0


@pytest.mark.parametrize("model", ["gpt-5.6-terra", "o3"])
def test_reasoning_openai_model_gets_no_temperature(monkeypatch, model):
    # /v1/responses answers `temperature` on a reasoning model with HTTP 400
    # ("Unsupported parameter"), which would take describe down completely.
    from adapters import openai_adapter

    seen = _capture(monkeypatch, openai_adapter)
    seen["response"] = json.dumps({
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "ok"}]}]
    }).encode()

    OpenAIAdapter(FakeCfg(openai_model=model)).describe_scene(b"", "p")

    assert "temperature" not in seen["payload"]


def test_gemini_always_gets_the_temperature(monkeypatch):
    from adapters import gemini_adapter

    seen = _capture(monkeypatch, gemini_adapter)
    seen["response"] = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
    }).encode()

    GeminiAdapter(
        FakeCfg(gemini_model="gemini-2.5-flash", ai_temperature=0.3)
    ).describe_scene(b"", "p")

    assert seen["payload"]["generationConfig"]["temperature"] == 0.3


# ── An effort this model doesn't take must not kill describe ────────────────

def test_rejected_effort_retries_without_the_reasoning_block(monkeypatch):
    """gpt-5.6-terra answers effort="minimal" with HTTP 400 (measured on
    isora-bfe2) even though _VALID_EFFORTS accepts it — the set is a union
    across model families, not a per-model guarantee. Without the retry, one
    bad value in /root/config.json makes every describe press say "gagal
    menganalisis" until somebody SSHes into the device."""
    import urllib.error
    from adapters import openai_adapter

    calls = []
    ok = json.dumps({
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": "ok"}]}]
    }).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return ok

    class _Body:
        def read(self):
            return (b'{"error":{"message":"Unsupported value: \'minimal\' is '
                    b'not supported with the \'gpt-5.6-terra\' model."}}')

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode())
        calls.append(payload)
        if "reasoning" in payload:
            err = urllib.error.HTTPError(_API_URL, 400, "Bad Request", {}, None)
            err.read = _Body().read
            raise err
        return _Resp()

    _API_URL = openai_adapter._API_URL
    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", fake_urlopen)

    out = OpenAIAdapter(
        FakeCfg(openai_model="gpt-5.6-terra", openai_reasoning_effort="minimal")
    ).describe_scene(b"", "p")

    assert out == "ok"
    assert len(calls) == 2
    assert "reasoning" in calls[0] and "reasoning" not in calls[1]
    # The retry still needs room for the answer behind the model's own default
    # thinking, or it comes back as a reasoning item with no message.
    assert calls[1]["max_output_tokens"] > 220


def test_other_400s_are_not_retried(monkeypatch):
    # A bad API key or a malformed image must surface immediately, not burn a
    # second round-trip out of a blind user's latency budget.
    import urllib.error
    from adapters import openai_adapter
    from adapters.base import AdapterError

    calls = []

    class _Body:
        def read(self):
            return b'{"error":{"message":"Invalid image data"}}'

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
        err.read = _Body().read
        raise err

    monkeypatch.setattr(openai_adapter.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(AdapterError):
        OpenAIAdapter(FakeCfg(openai_model="gpt-5.6-terra")).describe_scene(b"", "p")
    assert len(calls) == 1
