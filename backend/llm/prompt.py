from prompts.claude_prompts import CLAUDE_GENERAL_PROMPT
from repo_parser import FileChunk

SYSTEM_PROMPT = CLAUDE_GENERAL_PROMPT
RETRIEVAL_INSTRUCTIONS = """You can inspect this repository with read_file and search_code tools.
Use them whenever the file tree or current context does not contain enough evidence.
Prefer reading the relevant file or line range before answering, and cite repository paths."""


def build_context_block(chunks: list[FileChunk]) -> str:
    if not chunks:
        return "No file context available."
    parts = [f"## Repository Context ({len(chunks)} files)\n"]
    for chunk in chunks:
        parts.append(chunk.formatted)
    return "\n".join(parts)


def build_system_prompt(
    repo_owner: str,
    repo_name: str,
    tree: list,
    chunks: list[FileChunk],
) -> list[dict]:
    paths = "\n".join(
        f"- {node.path}" for node in tree if node.type == "blob"
    )
    stable = (
        f"{SYSTEM_PROMPT}\n\n{RETRIEVAL_INSTRUCTIONS}\n\n"
        f"Repository: {repo_owner}/{repo_name}\n\n"
        f"## Repository file tree\n{paths or '(No files indexed)'}"
    )
    return [
        {
            "type": "text",
            "text": stable,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": build_context_block(chunks)},
    ]
