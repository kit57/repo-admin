from prompts.claude_prompts import CLAUDE_GENERAL_PROMPT
from repo_parser import FileChunk

SYSTEM_PROMPT = CLAUDE_GENERAL_PROMPT


def build_context_block(chunks: list[FileChunk]) -> str:
    if not chunks:
        return "No file context available."
    parts = [f"## Repository Context ({len(chunks)} files)\n"]
    for chunk in chunks:
        parts.append(chunk.formatted)
    return "\n".join(parts)


def build_system_prompt(repo_owner: str, repo_name: str, chunks: list[FileChunk]) -> str:
    context = build_context_block(chunks)
    return f"{SYSTEM_PROMPT}\n\n---\n\nRepository: {repo_owner}/{repo_name}\n\n{context}"
