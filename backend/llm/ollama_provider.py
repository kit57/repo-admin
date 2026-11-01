import json
import os

import aiohttp

from .base import DEFAULT_MAX_TOKENS, LLMError, LLMProvider, ToolCall, Usage

# Local models can take a while to load into memory before the first token.
TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=600)


class OllamaProvider(LLMProvider):
    """Open-weight models (Gemma, Llama, Qwen...) served by a local Ollama instance."""

    name = "ollama"
    default_model = os.getenv("OLLAMA_MODEL") or "gemma3:4b"

    def __init__(self, model: str | None = None):
        super().__init__(model)
        self.base_url = (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
        # Ollama's own default context window is tiny and silently truncates the repo context.
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX") or 32_768)
        # Layers to offload to the GPU; "0" forces CPU. Unset lets Ollama decide.
        self.num_gpu = os.getenv("OLLAMA_NUM_GPU")

    @property
    def context_tokens(self) -> int:
        # Leave room for the reply, the system prompt and chat history.
        return max(self.num_ctx - self.max_tokens - 4_000, 2_000)

    async def stream(
        self,
        system: str | list[dict],
        messages: list[dict],
        usage: Usage,
        tools: list[dict] | None = None,
    ):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_text(system)},
                *self._messages(messages),
            ],
            "stream": True,
            "options": {"num_ctx": self.num_ctx, "num_predict": self.max_tokens},
        }
        if tools:
            payload["tools"] = tools
        if self.num_gpu:
            payload["options"]["num_gpu"] = int(self.num_gpu)
        url = f"{self.base_url}/api/chat"
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        raise LLMError(self._http_error(resp.status, await resp.text()))
                    # Ollama streams one JSON object per line.
                    async for line in resp.content:
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if "error" in data:
                            raise LLMError(f"Ollama error: {data['error']}")
                        token = data.get("message", {}).get("content")
                        if token:
                            yield token
                        if data.get("done"):
                            # The final line carries the counts; prompt_eval_count excludes
                            # prompt tokens Ollama reused from its cache.
                            usage.input_tokens = data.get("prompt_eval_count", 0)
                            usage.output_tokens = data.get("eval_count", 0)
                            usage.cache_read_tokens = data.get("prompt_eval_cached_count", 0)
                            for index, call in enumerate(data.get("message", {}).get("tool_calls") or []):
                                function = call.get("function") or {}
                                arguments = function.get("arguments") or {}
                                if not isinstance(arguments, dict):
                                    raise LLMError(
                                        f"Ollama returned invalid arguments for tool {function.get('name', '')}"
                                    )
                                yield ToolCall(
                                    id=f"ollama-{index}",
                                    name=function.get("name", ""),
                                    arguments=arguments,
                                )
                            break
        except aiohttp.ClientConnectorError as e:
            raise LLMError(
                f"Can't reach Ollama at {self.base_url} — is it running? (`ollama serve`)"
            ) from e
        except aiohttp.ClientError as e:
            raise LLMError(f"Ollama request failed: {e}") from e

    @staticmethod
    def _system_text(system: str | list[dict]) -> str:
        if isinstance(system, str):
            return system
        return "\n\n".join(block["text"] for block in system)

    @staticmethod
    def _messages(messages: list[dict]) -> list[dict]:
        converted = []
        for message in messages:
            if message.get("tool_calls"):
                calls = []
                for call in message["tool_calls"]:
                    function = call["function"]
                    calls.append({
                        "function": {
                            "name": function["name"],
                            "arguments": json.loads(function["arguments"]),
                        },
                    })
                converted.append({
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": calls,
                })
            elif message["role"] == "tool":
                converted.append({"role": "tool", "content": message["content"]})
            else:
                converted.append(message)
        return converted

    def _http_error(self, status: int, body: str) -> str:
        try:
            message = json.loads(body).get("error", body)
        except ValueError:
            message = body
        if status == 404:
            return f"Ollama model '{self.model}' not found — pull it with `ollama pull {self.model}`"
        return f"Ollama error ({status}): {message}"
