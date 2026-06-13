"""
AI API Adapters — unified interface to OpenAI, Gemini, and Claude Vision APIs.
"""

from .base import AIAdapter, AdapterError
from .openai_adapter import OpenAIAdapter
from .gemini_adapter import GeminiAdapter
from .claude_adapter import ClaudeAdapter


def get_adapter(provider: str, cfg) -> AIAdapter:
    """
    Factory: return the correct adapter for the configured provider.
    provider: "openai" | "gemini" | "claude"
    Raises ValueError if unknown.
    """
    p = provider.lower()
    if p == "openai":
        return OpenAIAdapter(cfg)
    if p == "gemini":
        return GeminiAdapter(cfg)
    if p == "claude":
        return ClaudeAdapter(cfg)
    raise ValueError(f"Unknown AI provider: {provider!r}. Choose openai, gemini, or claude.")


__all__ = [
    "AIAdapter", "AdapterError",
    "OpenAIAdapter", "GeminiAdapter", "ClaudeAdapter",
    "get_adapter",
]
