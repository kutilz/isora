"""
Google Gemini Vision adapter — uses generateContent REST API (v1beta).
Supports gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash, etc.
"""

import base64
import json
import urllib.request
import urllib.error

from .base import AIAdapter, AdapterError

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Series that do no hidden thinking at all — their whole maxOutputTokens goes to
# the visible answer. Everything else is assumed to think, because a new model
# family thinking by default is the safer assumption than a truncated answer in
# a blind user's ear.
_NON_THINKING = ("gemini-1.0", "gemini-1.5", "gemini-2.0")


def _thinks(model: str) -> bool:
    m = (model or "").strip().lower()
    return not any(p in m for p in _NON_THINKING)


def _thinking_can_be_disabled(model: str) -> bool:
    """thinkingConfig is only valid on the 2.5 thinking series, and 2.5-pro
    rejects a 0 budget."""
    m = (model or "").strip().lower()
    return "2.5" in m and "pro" not in m


class GeminiAdapter(AIAdapter):

    def _api_key(self) -> str:
        import os
        return os.environ.get("GEMINI_API_KEY") or self._cfg.GEMINI_API_KEY

    def _call(self, jpeg_bytes: bytes, prompt: str, max_tokens: int) -> str:
        key   = self._api_key()
        if not key:
            raise AdapterError("gemini_api_key not configured")

        model   = self._cfg.get("gemini_model", "gemini-1.5-flash")
        url     = f"{_API_BASE}/{model}:generateContent?key={key}"
        timeout = self._cfg.AI_TIMEOUT_S

        parts: list = [{"text": prompt}]
        if jpeg_bytes:
            b64 = base64.b64encode(jpeg_bytes).decode()
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data":     b64,
                }
            })

        # 2.5+ "flash" models think by default even when unasked: a plain
        # describe call was measured spending 500-700+ hidden thoughtsTokenCount
        # before writing the 1-2 sentence answer (~10s of a ~16s round-trip, and
        # could truncate the answer if thinking ran past maxOutputTokens). This
        # task needs no reasoning, so thinking is disabled where that is
        # possible — BUT thinkingConfig is only valid on the 2.5 thinking
        # series. Sending it to 1.5/2.0 models (including the default
        # gemini-1.5-flash) returns HTTP 400, and 2.5-pro rejects a 0 budget.
        #
        # Where thinking CANNOT be silenced (2.5-pro, and any future family not
        # named "2.5"), the tight cap alone would be spent on hidden thoughts and
        # the call would come back finishReason=MAX_TOKENS with a truncated or
        # absent answer — a blind user hearing half a sentence. Those models keep
        # the generous budget instead; the prompt still holds the real answer to
        # 1-2 sentences, so the headroom costs nothing when it is not used.
        if _thinking_can_be_disabled(model):
            gen_cfg = {"maxOutputTokens": max_tokens,
                       "thinkingConfig": {"thinkingBudget": 0}}
        elif _thinks(model):
            gen_cfg = {"maxOutputTokens": max_tokens + 1024}
        else:
            gen_cfg = {"maxOutputTokens": max_tokens}
        # Deterministic decoding: a describe pressed twice on an unchanged
        # scene must not come back re-worded. Accepted by every Gemini family
        # (unlike OpenAI's reasoning models), so it is set unconditionally.
        gen_cfg["temperature"] = self._cfg.AI_TEMPERATURE
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": gen_cfg,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return (
                data["candidates"][0]["content"]["parts"][0]["text"].strip()
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            raise AdapterError(f"Gemini HTTP {e.code}: {body}") from e
        except (KeyError, IndexError) as e:
            raise AdapterError(f"Unexpected Gemini response shape: {e}") from e
        except Exception as e:
            raise AdapterError(str(e)) from e

    # Thinking is off (see _call), so the cap only needs to cover the actual
    # 1-2 sentence Indonesian answer the prompt asks for — matches the
    # OpenAI/Claude adapters' describe_scene budget.
    def describe_scene(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=220)

    def scan_qris(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=120)

    def test_connection(self) -> dict:
        try:
            result = self._call(b"", "Reply with exactly one word: OK", max_tokens=5)
            return {"ok": True, "message": result}
        except AdapterError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            return {"ok": False, "message": f"Unexpected: {e}"}
