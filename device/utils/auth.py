"""
Auth — device token generation + verification.

A 32-byte random token is generated on first boot and stored in
/root/config.json as `device_token`. Dashboard reads it from
/auth/token (localhost-only) or it's printed once on first boot
console; subsequent runs persist it.

Token-protected POST endpoints require either:
  - header `X-Auth-Token: <token>`, or
  - query string `?token=<token>` (for trivial curl/test use).

Read-only GETs that don't change device state stay open so the
dashboard can render snapshots without juggling auth headers on
every fetch — but ALL POST routes that mutate config or trigger
hardware require auth.
"""

import os
import secrets

from config import cfg

_TOKEN_KEY = "device_token"


def ensure_token(logger=None) -> str:
    """
    Return the device token, generating one if not yet set.
    Persists to config.json on first generation.
    """
    existing = cfg.get(_TOKEN_KEY, "")
    if existing and len(existing) >= 16:
        return existing
    new_token = secrets.token_urlsafe(32)
    cfg.update({_TOKEN_KEY: new_token})
    if logger is not None:
        # Log without leaking value; first-boot prints to console for ops.
        logger.warn(
            "Generated new device API token — see /root/config.json",
            module="Auth",
        )
        print(f"[Auth] device token: {new_token}")
    return new_token


def get_token() -> str:
    return cfg.get(_TOKEN_KEY, "")


def env_override() -> str:
    """Env-var override (handy for dev / CI)."""
    return os.environ.get("AURAL_DEVICE_TOKEN", "")


def verify(presented: str) -> bool:
    """Constant-time compare against the stored token."""
    expected = env_override() or get_token()
    if not expected or not presented:
        return False
    return secrets.compare_digest(presented, expected)
