import json
import os

from .base import DEFAULT_MAX_TOKENS, LLMError, LLMProvider, ToolCall, Usage


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

    async def stream(
        self,
        system: str | list[dict],
        messages: list[dict],
        usage: Usage,
        tools: list[dict] | None = None,
    ):
        import anthropic

        client = self._get_client()
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": self._messages(messages),
        }
        if tools:
            request["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"]["description"],
                    "input_schema": item["function"]["parameters"],
                }
                for item in tools
            ]
        try:
            async with client.messages.stream(**request) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                usage.input_tokens = final.usage.input_tokens
                usage.output_tokens = final.usage.output_tokens
                usage.cache_read_tokens = final.usage.cache_read_input_tokens or 0
                usage.cache_write_tokens = final.usage.cache_creation_input_tokens or 0
                for block in final.content:
                    if block.type == "tool_use":
                        yield ToolCall(id=block.id, name=block.name, arguments=block.input)
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e}") from e

    @staticmethod
    def _messages(messages: list[dict]) -> list[dict]:
        converted = []
        pending_tool_results = []

        def flush_tool_results():
            if pending_tool_results:
                converted.append({"role": "user", "content": pending_tool_results.copy()})
                pending_tool_results.clear()

        for message in messages:
            if message["role"] == "tool":
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": message["content"],
                })
                continue

            flush_tool_results()
            if message.get("tool_calls"):
                blocks = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for call in message["tool_calls"]:
                    function = call["function"]
                    blocks.append({
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function["name"],
                        "input": json.loads(function["arguments"]),
                    })
                converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": message["role"], "content": message["content"]})

        flush_tool_results()
        return converted
