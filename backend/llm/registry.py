import os
import uuid

from .anthropic_provider import AnthropicProvider
from .base import LLMError, LLMProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from .tracing import traced_stream

# To add a provider: subclass LLMProvider and register it here.
PROVIDERS: dict[str, type[LLMProvider]] = {
    OllamaProvider.name: OllamaProvider,
    AnthropicProvider.name: AnthropicProvider,
    OpenAIProvider.name: OpenAIProvider,
}

ALIASES = {
    "claude": "anthropic",
    "gemma": "ollama",  # Gemma runs locally through Ollama (the default model)
}

# Open-weight by default: no API key, no per-token cost.
DEFAULT_PROVIDER = "ollama"

_instances: dict[tuple[str, str], LLMProvider] = {}


def normalize(name: str) -> str:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider '{name}'. Available: {', '.join(PROVIDERS)}")
    return key


def default_provider_name() -> str:
    return normalize(os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER)


def fallback_provider_names() -> list[str]:
    raw = os.getenv("LLM_FALLBACK_PROVIDERS") or ""
    return [normalize(n) for n in raw.split(",") if n.strip()]


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    key = normalize(name) if name else default_provider_name()
    cls = PROVIDERS[key]
    model = model or cls.default_model
    if (key, model) not in _instances:
        _instances[(key, model)] = cls(model)
    return _instances[(key, model)]


def provider_chain(name: str | None = None, model: str | None = None) -> list[LLMProvider]:
    """The requested provider followed by any configured fallbacks (each on its default model)."""
    primary = get_provider(name, model)
    chain = [primary]
    for fallback in fallback_provider_names():
        if fallback != primary.name:
            chain.append(get_provider(fallback))
    return chain


async def open_stream(
    chain: list[LLMProvider],
    system: str,
    messages: list[dict],
    *,
    feature: str,
    session_id: str | None = None,
):
    """Start streaming from the first provider in the chain that produces a token.

    Falling back is only possible before anything has been sent to the client,
    so each provider is primed with its first token here. Every attempt is
    traced under one request id. Returns
    (provider, first_token, rest_of_stream, request_id).
    """
    request_id = str(uuid.uuid4())
    errors = []
    for attempt, provider in enumerate(chain):
        stream = traced_stream(
            provider, system, messages,
            request_id=request_id, attempt=attempt, feature=feature, session_id=session_id,
        )
        try:
            first = await anext(stream)
        except StopAsyncIteration:
            return provider, "", stream, request_id
        except LLMError as e:
            await stream.aclose()
            errors.append(f"{provider.label}: {e}")
            continue
        return provider, first, stream, request_id
    raise LLMError(" | ".join(errors))


def describe_providers() -> list[dict]:
    return [
        {"name": name, "default_model": cls.default_model, "configured": cls.is_configured()}
        for name, cls in PROVIDERS.items()
    ]
