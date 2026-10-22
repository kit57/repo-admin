import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Shared default for every provider; each one may override it with its own env var.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS") or 8000)


class LLMError(Exception):
    """A provider failed in a way the user should be told about (unreachable, bad key, unknown model...)."""


@dataclass
class Usage:
    """Token counts reported by the provider for one call; filled in by LLMProvider.stream.

    input_tokens excludes cached tokens, which are counted separately because
    they are billed at different rates. None means the provider didn't report it.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


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
    def stream(self, system: str, messages: list[dict], usage: Usage) -> AsyncIterator[str]:
        """Yield response tokens and record the provider's token counts in `usage`.

        Raise LLMError for user-facing failures. Leave a `usage` field as None when
        the provider doesn't report it; tracing then estimates it from the text.
        """
