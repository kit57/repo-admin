import os

from .base import DEFAULT_MAX_TOKENS, LLMError, LLMProvider, Usage


def _api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = os.getenv("CLAUDE_MODEL") or "claude-sonnet-5-5"

    def __init__(self, model: str | None = None):
        super().__init__(model)
        self.max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
        self._client = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(_api_key())

    def _get_client(self):
        # Imported and built lazily so the SDK and key are only needed when Claude is selected.
        if self._client is None:
            if not _api_key():
                raise LLMError("ANTHROPIC_API_KEY is not set")
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=_api_key())
        return self._client

    async def stream(self, system: str, messages: list[dict], usage: Usage):
        import anthropic

        client = self._get_client()
        try:
            async with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = (await stream.get_final_message()).usage
                usage.input_tokens = final.input_tokens
                usage.output_tokens = final.output_tokens
                usage.cache_read_tokens = final.cache_read_input_tokens or 0
                usage.cache_write_tokens = final.cache_creation_input_tokens or 0
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}") from e
