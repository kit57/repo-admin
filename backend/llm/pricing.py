import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_write_tokens: int) -> float:
        return (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_read_tokens * self.cache_read
            + cache_write_tokens * self.cache_write
        ) / 1_000_000


# Keys are "<provider>/<model>"; "<provider>/*" matches any model of that provider.
# Anthropic first-party rates as of 2026-10-06 (cache writes at the 5-minute TTL rate, 1.25x input).
# Claude Haiku 5.5 bills prompts over 100K tokens at a higher rate, which isn't modeled here.
# OpenAI-compatible APIs have no built-in prices: their calls are logged with cost_usd = null
# until you add them via LLM_PRICING_FILE.
DEFAULT_PRICES: dict[str, Price] = {
    "anthropic/claude-fable-5-1": Price(10.00, 50.00, cache_read=0.25, cache_write=12.50),
    "anthropic/claude-opus-5-5": Price(4.00, 20.00, cache_read=0.20, cache_write=5.00),
    "anthropic/claude-opus-5": Price(5.00, 25.00, cache_read=0.50, cache_write=6.25),
    "anthropic/claude-sonnet-5-5": Price(2.00, 10.00, cache_read=0.20, cache_write=2.50),
    "anthropic/claude-sonnet-5": Price(2.00, 10.00, cache_read=0.20, cache_write=2.50),
    "anthropic/claude-haiku-5-5": Price(0.10, 0.50, cache_read=0.01, cache_write=0.125),
    # Local open-weight models have no per-token cost.
    "ollama/*": Price(0.0, 0.0),
}

_prices: dict[str, Price] | None = None


def _load() -> dict[str, Price]:
    prices = dict(DEFAULT_PRICES)
    path = os.getenv("LLM_PRICING_FILE")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                overrides = json.load(f)
            prices.update({key: Price(**value) for key, value in overrides.items()})
        except (OSError, ValueError, TypeError) as e:
            logger.error("Ignoring LLM_PRICING_FILE %s: %s", path, e)
    return prices


def lookup(provider: str, model: str) -> Price | None:
    global _prices
    if _prices is None:
        _prices = _load()
    return _prices.get(f"{provider}/{model}") or _prices.get(f"{provider}/*")
