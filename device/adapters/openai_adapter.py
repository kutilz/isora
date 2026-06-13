"""
OpenAI Vision adapter — uses Chat Completions with image_url (base64 inline).
"""

import base64
import json
import urllib.request
import urllib.error

from .base import AIAdapter, AdapterError

_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIAdapter(AIAdapter):

    def _api_key(self) -> str:
        import os
        return (
            os.environ.get("OPENAI_API_KEY")
            or self._cfg.get("openai_api_key", "")
        )

    def _call(self, jpeg_bytes: bytes, prompt: str, max_tokens: int) -> str:
        key = self._api_key()
        if not key:
            raise AdapterError("openai_api_key not configured")

        b64 = base64.b64encode(jpeg_bytes).decode() if jpeg_bytes else ""
        content: list = [{"type": "text", "text": prompt}]
        if b64:
            content.append({
                "type":      "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        payload = {
            "model":      self._cfg.get("openai_model", "gpt-4o-mini"),
            "messages":   [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        try:
            timeout = int(self._cfg.get("ai_timeout_s", 15))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            raise AdapterError(f"OpenAI HTTP {e.code}: {body}") from e
        except Exception as e:
            raise AdapterError(str(e)) from e

    def describe_scene(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=150)

    def scan_qris(self, jpeg_bytes: bytes, prompt: str) -> str:
        return self._call(jpeg_bytes, prompt, max_tokens=80)

    def test_connection(self) -> dict:
        try:
            # Minimal text-only call, no image — cheaper and faster
            result = self._call(b"", "Reply with exactly one word: OK", max_tokens=5)
            return {"ok": True, "message": result}
        except AdapterError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            return {"ok": False, "message": f"Unexpected: {e}"}
