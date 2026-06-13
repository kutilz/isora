"""
Anthropic Claude Vision adapter — uses Messages API with image content blocks.
Supports claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7, etc.
"""

import base64
import json
import urllib.request
import urllib.error

from .base import AIAdapter, AdapterError

_API_URL     = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class ClaudeAdapter(AIAdapter):

    def _api_key(self) -> str:
        import os
        return (
            os.environ.get("ANTHROPIC_API_KEY")
            or self._cfg.get("claude_api_key", "")
        )

    def _call(self, jpeg_bytes: bytes, prompt: str, max_tokens: int) -> str:
        key = self._api_key()
        if not key:
            raise AdapterError("claude_api_key not configured")

        model   = self._cfg.get("claude_model", "claude-haiku-4-5-20251001")
        timeout = int(self._cfg.get("ai_timeout_s", 15))

        content: list = []
        if jpeg_bytes:
            b64 = base64.b64encode(jpeg_bytes).decode()
            content.append({
                "type":   "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/jpeg",
                    "data":       b64,
                },
            })
        content.append({"type": "text", "text": prompt})

        payload = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": content}],
        }

        req = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         key,
                "anthropic-version": _API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            raise AdapterError(f"Claude HTTP {e.code}: {body}") from e
        except (KeyError, IndexError) as e:
            raise AdapterError(f"Unexpected Claude response shape: {e}") from e
        except Exception as e:
            raise AdapterError(str(e)) from e

    def describe_scene(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=150)

    def scan_qris(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=80)

    def test_connection(self) -> dict:
        try:
            result = self._call(b"", "Reply with exactly one word: OK", max_tokens=5)
            return {"ok": True, "message": result}
        except AdapterError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            return {"ok": False, "message": f"Unexpected: {e}"}
