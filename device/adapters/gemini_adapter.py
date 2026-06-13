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


class GeminiAdapter(AIAdapter):

    def _api_key(self) -> str:
        import os
        return (
            os.environ.get("GEMINI_API_KEY")
            or self._cfg.get("gemini_api_key", "")
        )

    def _call(self, jpeg_bytes: bytes, prompt: str, max_tokens: int) -> str:
        key   = self._api_key()
        if not key:
            raise AdapterError("gemini_api_key not configured")

        model   = self._cfg.get("gemini_model", "gemini-1.5-flash")
        url     = f"{_API_BASE}/{model}:generateContent?key={key}"
        timeout = int(self._cfg.get("ai_timeout_s", 15))

        parts: list = [{"text": prompt}]
        if jpeg_bytes:
            b64 = base64.b64encode(jpeg_bytes).decode()
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data":     b64,
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens},
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
