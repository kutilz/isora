"""
Base class for all AI Vision adapters.

Each adapter implements two methods:
  describe_scene(jpeg_bytes, prompt) -> str
  scan_qris(jpeg_bytes, prompt)      -> str

Raise AdapterError for recoverable API failures so callers can
present a user-friendly message without crashing.
"""


class AdapterError(Exception):
    """Raised when an API call fails in a recoverable way."""


class AIAdapter:
    """Abstract base — subclass and implement describe_scene / scan_qris."""

    def __init__(self, cfg):
        self._cfg = cfg

    def describe_scene(self, jpeg_bytes: bytes, prompt: str) -> str:
        raise NotImplementedError

    def scan_qris(self, jpeg_bytes: bytes, prompt: str) -> str:
        raise NotImplementedError

    def test_connection(self) -> dict:
        """
        Quick connectivity check. Returns {"ok": bool, "message": str}.
        Subclasses may override for a lighter-weight probe.
        """
        try:
            result = self.describe_scene(
                b"",
                "Reply with exactly: OK",
            )
            return {"ok": True, "message": result[:80]}
        except AdapterError as e:
            return {"ok": False, "message": str(e)}
        except Exception as e:
            return {"ok": False, "message": f"Unexpected error: {e}"}
