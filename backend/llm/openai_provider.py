import json
import os

import aiohttp

from .base import DEFAULT_MAX_TOKENS, LLMError, LLMProvider, Usage

TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=300)
OPENAI_URL = "https://api.openai.com/v1"


class OpenAIProvider(LLMProvider):
    """OpenAI, or any OpenAI-compatible API (OpenRouter, Groq, vLLM, LM Studio...) via OPENAI_BASE_URL."""

    name = "openai"
    default_model = os.getenv("OPENAI_MODEL") or ""

    def __init__(self, model: str | None = None):
        super().__init__(model)
        self.base_url = (os.getenv("OPENAI_BASE_URL") or OPENAI_URL).rstrip("/")
        self.api_key = os.getenv("OPENAI_API_KEY") or ""
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS") or DEFAULT_MAX_TOKENS)

    @classmethod
    def is_configured(cls) -> bool:
        # A custom base URL may point at a local server that needs no key.
        has_auth = bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"))
        return has_auth and bool(cls.default_model)

    async def stream(self, system: str, messages: list[dict], usage: Usage):
        if not self.model:
            raise LLMError("OPENAI_MODEL is not set")
        if not self.api_key and self.base_url == OPENAI_URL:
            raise LLMError("OPENAI_API_KEY is not set")

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            # Ask for a final chunk with token counts; servers that ignore it get estimated usage.
            "stream_options": {"include_usage": True},
        }
        # OpenAI's current models reject the legacy field; compatible servers often only know it.
        token_field = "max_completion_tokens" if self.base_url == OPENAI_URL else "max_tokens"
        payload[token_field] = self.max_tokens

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url}/chat/completions"
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        raise LLMError(f"OpenAI API error ({resp.status}): {await resp.text()}")
                    # Server-sent events: "data: {...}" lines, terminated by "data: [DONE]".
                    async for raw in resp.content:
                        line = raw.decode().strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or []
                        token = choices[0].get("delta", {}).get("content") if choices else None
                        if token:
                            yield token
                        if chunk.get("usage"):
                            self._record_usage(chunk["usage"], usage)
        except aiohttp.ClientError as e:
            raise LLMError(f"Can't reach OpenAI-compatible API at {self.base_url}: {e}") from e

    @staticmethod
    def _record_usage(reported: dict, usage: Usage) -> None:
        # prompt_tokens includes cached tokens; split them out to match the other providers.
        cached = (reported.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        usage.input_tokens = reported.get("prompt_tokens", 0) - cached
        usage.output_tokens = reported.get("completion_tokens", 0)
        usage.cache_read_tokens = cached
