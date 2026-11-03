"""
OpenAI Vision adapter — uses the Responses API (POST /v1/responses), not
Chat Completions, because only Responses exposes the `reasoning.effort` knob.
Reasoning-capable models (gpt-5.6 series) think by default same as Gemini's
2.5+ "flash" models (see gemini_adapter.py) — an unbounded reasoning budget
adds seconds of latency a 1-2 sentence scene description doesn't need, so we
pin effort low and let it be tuned live via `openai_reasoning_effort`.
"""

import base64
import json
import time
import urllib.request
import urllib.error

from utils import diag

from .base import AIAdapter, AdapterError

_API_URL = "https://api.openai.com/v1/responses"

# Allowed reasoning.effort values (low -> high); "none" skips reasoning
# entirely on models that support it. Anything else falls back to "low".
#
# This set is the union across model families, NOT a per-model guarantee:
# gpt-5.6-terra answers effort="minimal" with HTTP 400 ("Unsupported value:
# 'minimal' is not supported with the 'gpt-5.6-terra' model"), measured on
# isora-bfe2. Passing this filter is therefore not proof the API will accept
# the value — see the retry in _call, which is what actually keeps a mismatch
# from turning every describe press into "gagal menganalisis".
_VALID_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}

# Only the reasoning series accepts a `reasoning` block on /v1/responses;
# sending one to gpt-4o / gpt-4-turbo is rejected with HTTP 400. This has to be
# decided per-model rather than assumed from the default: Config._load merges
# the saved file OVER _DEFAULTS, so a unit provisioned before the gpt-5.6
# default still carries openai_model="gpt-4o-mini" in /root/config.json and
# would 400 on every describe/QRIS press after an update.
_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")

# Reasoning tokens are billed against max_output_tokens, so a tight cap can be
# consumed entirely by thinking — the response then completes as
# status="incomplete" with only a reasoning item and no message, and
# _extract_text raises. Headroom must scale with effort: a flat +512 covers
# "low" but not the "high"/"xhigh" that _VALID_EFFORTS accepts and that
# POST /config (and the cloud config push) can set live.
_EFFORT_HEADROOM = {
    "none":    0,
    "minimal": 0,
    "low":     512,
    "medium":  1024,
    "high":    2048,
    "xhigh":   3072,
    "max":     4096,
}


class _EffortRejected(Exception):
    """The model refused this reasoning.effort value — retryable without it."""


def _is_effort_rejection(body: str) -> bool:
    low = (body or "").lower()
    return "unsupported value" in low and "not supported with" in low


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").strip().lower()
    return any(m.startswith(p) for p in _REASONING_PREFIXES)


class OpenAIAdapter(AIAdapter):

    def _api_key(self) -> str:
        import os
        return os.environ.get("OPENAI_API_KEY") or self._cfg.OPENAI_API_KEY

    def _call(self, jpeg_bytes: bytes, prompt: str, max_tokens: int) -> str:
        key = self._api_key()
        if not key:
            raise AdapterError("openai_api_key not configured")

        model   = self._cfg.get("openai_model", "gpt-5.6-terra")
        effort  = str(self._cfg.get("openai_reasoning_effort", "low")).lower()
        if effort not in _VALID_EFFORTS:
            effort = "low"
        timeout = self._cfg.AI_TIMEOUT_S

        content: list = [{"type": "input_text", "text": prompt}]
        if jpeg_bytes:
            b64 = base64.b64encode(jpeg_bytes).decode()
            content.append({
                "type":      "input_image",
                "image_url": f"data:image/jpeg;base64,{b64}",
            })

        # Leave room for the visible answer to land after the model finishes
        # thinking (see _EFFORT_HEADROOM). A non-reasoning model gets neither
        # the headroom it doesn't need nor the `reasoning` block it rejects.
        reasoning = _is_reasoning_model(model)
        out_cap   = max_tokens + (_EFFORT_HEADROOM.get(effort, 512) if reasoning else 0)
        payload = {
            "model":             model,
            "input":             [{"role": "user", "content": content}],
            "max_output_tokens": out_cap,
        }
        if reasoning:
            payload["reasoning"] = {"effort": effort}
        else:
            # Pressing describe twice on an unchanged scene should not re-word
            # the world (see utils/scene_prompt.py), so decoding is pinned to
            # cfg["ai_temperature"] (0.0 by default). Reasoning models reject
            # `temperature` on /v1/responses with HTTP 400 — "Unsupported
            # parameter" — so they are left to the prompt's output contract
            # plus the low reasoning effort instead.
            payload["temperature"] = self._cfg.AI_TEMPERATURE

        try:
            return self._post(payload, key, timeout)
        except _EffortRejected as e:
            # The effort value passed _VALID_EFFORTS but this particular model
            # does not take it (gpt-5.6-terra rejects "minimal"). Retrying
            # without the block lets the model use its own default effort: a
            # slower answer, but an answer. The alternative is every describe
            # press failing with "gagal menganalisis" until someone SSHes in.
            payload.pop("reasoning", None)
            payload["max_output_tokens"] = max_tokens + _EFFORT_HEADROOM["medium"]
            try:
                return self._post(payload, key, timeout)
            except _EffortRejected:
                raise AdapterError(str(e)) from e

    def _post(self, payload: dict, key: str, timeout: float) -> str:
        body_bytes = json.dumps(payload).encode()
        req = urllib.request.Request(
            _API_URL,
            data=body_bytes,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        call = {"model": payload.get("model"), "bytes": len(body_bytes),
                "effort": (payload.get("reasoning") or {}).get("effort")}
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                call["wait_s"] = time.monotonic() - started
                # The model's own clock, so a slow answer can be split into
                # "the model was thinking" and "the link was slow".
                call["server_ms"] = diag.header(resp, "openai-processing-ms")
                call["req"] = diag.header(resp, "x-request-id")
                data = json.loads(resp.read())
            text = _extract_text(data)
            usage = data.get("usage") or {}
            diag.ai_call("openai", started, True,
                         reason_tok=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                         out_tok=usage.get("output_tokens"), in_tok=usage.get("input_tokens"),
                         cached_tok=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
                         **call)
            return text
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            diag.ai_call("openai", started, False, err=f"HTTP {e.code}",
                         server_ms=diag.header(e, "openai-processing-ms"),
                         model=call["model"], bytes=call["bytes"], effort=call["effort"])
            if e.code == 400 and _is_effort_rejection(body):
                raise _EffortRejected(f"OpenAI HTTP 400: {body}") from e
            raise AdapterError(f"OpenAI HTTP {e.code}: {body}") from e
        except Exception as e:
            diag.ai_call("openai", started, False, err=e, **call)
            raise AdapterError(str(e)) from e

    def describe_scene(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=220)

    def scan_qris(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=120)

    def test_connection(self) -> dict:
        try:
            # Minimal text-only call, no image — cheaper and faster
            result = self._call(b"", "Reply with exactly one word: OK", max_tokens=16)
            return {"ok": True, "message": result}
        except AdapterError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            return {"ok": False, "message": f"Unexpected: {e}"}


def _extract_text(data: dict) -> str:
    """Pull the assistant's text out of a Responses API payload.

    `output` can list a reasoning summary item before the actual message item
    for reasoning-capable models, so find the message rather than assume
    output[0] is it.
    """
    for item in data.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return (part.get("text") or "").strip()
    raise AdapterError(f"No output_text in OpenAI response: {json.dumps(data)[:200]}")
