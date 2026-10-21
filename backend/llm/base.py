import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

# Shared default for every provider; each one may override it with its own env var.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS") or 8000)


class LLMError(Exception):
    """A provider failed in a way the user should be told about (unreachable, bad key, unknown model...)."""


class LLMProvider(ABC):
    """Provider-agnostic chat client.

    Every provider takes the same input — a system prompt plus a list of
    {"role": "user" | "assistant", "content": str} messages — and yields
    plain text tokens, so callers never need to know which backend is in use.
    """

    name: str = ""
    default_model: str = ""

    def __init__(self, model: str | None = None):
        self.model = model or self.default_model

    @property
    def label(self) -> str:
        return f"{self.name}/{self.model}"

    @classmethod
    def is_configured(cls) -> bool:
        """True when the env has everything this provider needs (API keys etc.)."""
        return True

    @property
    def context_tokens(self) -> int:
        """Token budget for repository context sent with each prompt."""
        return 60_000

    @abstractmethod
    def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        """Yield response tokens. Raise LLMError for user-facing failures."""
