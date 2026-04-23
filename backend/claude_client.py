import os
import anthropic
from backend.prompts.claude_prompts import CLAUDE_GENERAL_PROMPT
from repo_parser import FileChunk
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("CLAUDE_MODEL")
MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS"))

SYSTEM_PROMPT = CLAUDE_GENERAL_PROMPT


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def _build_context_block(self, chunks: list[FileChunk]) -> str:
        if not chunks:
            return "No file context available."
        parts = [f"## Repository Context ({len(chunks)} files)\n"]
        for chunk in chunks:
            parts.append(chunk.formatted)
        return "\n".join(parts)

    async def stream(
        self,
        repo_owner: str,
        repo_name: str,
        relevant_chunks: list[FileChunk],
        history: list[dict],
        user_message: str,
    ):
        """Yield tokens from a streaming Claude response."""
        context = self._build_context_block(relevant_chunks)

        system = f"{SYSTEM_PROMPT}\n\n---\n\nRepository: {repo_owner}/{repo_name}\n\n{context}"

        messages = [
            *history,
            {"role": "user", "content": user_message},
        ]

        async with self.client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text