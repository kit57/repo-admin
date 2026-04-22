import os
import anthropic
from repo_parser import FileChunk

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8096

SYSTEM_PROMPT = """You are an expert software engineer and code assistant embedded in a repository explorer.

You have been given the contents of a GitHub repository. Your job is to help the user understand, improve, and extend the codebase.

When generating code:
- Match the style, conventions, and patterns already present in the codebase
- Prefer modifying existing files over creating new ones unless a new file is clearly the right choice
- Always explain what you changed and why, briefly
- For large changes, show only the relevant diff/patch rather than the full file
- Use the exact import style already in the codebase

When answering questions:
- Be precise and reference specific files and line patterns when possible
- If you're unsure about something not in the provided context, say so clearly

The repository context provided may be a subset of the full codebase. If you need a file that isn't shown, mention it."""


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