import os
import re
from dataclasses import dataclass

# Rough token estimate: 1 token ≈ 4 chars
CHARS_PER_TOKEN = 4
MAX_FILE_CHARS = 40_000  # ~10k tokens per file cap


@dataclass
class FileChunk:
    path: str
    content: str
    token_estimate: int

    @property
    def formatted(self) -> str:
        return f"### File: {self.path}\n```\n{self.content}\n```\n"


class RepoParser:
    def chunk_files(self, files: dict[str, str]) -> list[FileChunk]:
        """Convert raw file dict into FileChunk list, truncating large files."""
        chunks = []
        for path, content in files.items():
            truncated = content[:MAX_FILE_CHARS]
            if len(content) > MAX_FILE_CHARS:
                truncated += f"\n... [truncated — {len(content) - MAX_FILE_CHARS} chars omitted]"
            token_est = len(truncated) // CHARS_PER_TOKEN
            chunks.append(FileChunk(path=path, content=truncated, token_estimate=token_est))
        return chunks

    def select_relevant_chunks(
        self,
        chunks: list[FileChunk],
        prompt: str,
        context_files: list[str],
        max_tokens: int = 60_000,
    ) -> list[FileChunk]:
        """
        Select the most relevant file chunks to include in the prompt.

        Priority order:
        1. Files explicitly pinned by the user (context_files)
        2. Files whose names appear in the prompt
        3. Files scored by keyword overlap with the prompt
        """
        prompt_lower = prompt.lower()
        prompt_words = set(re.findall(r'\w+', prompt_lower))

        # Score each chunk
        scored: list[tuple[float, FileChunk]] = []
        for chunk in chunks:
            score = 0.0
            path_lower = chunk.path.lower()
            filename = os.path.basename(path_lower)

            # Explicit user pin gets highest score
            if any(cf in chunk.path for cf in context_files):
                score += 1000

            # Filename mentioned in prompt
            if filename.replace(".py", "").replace(".ts", "") in prompt_lower:
                score += 50

            # Path keywords overlap
            path_words = set(re.findall(r'\w+', path_lower))
            score += len(prompt_words & path_words) * 5

            # Content keyword overlap (cheap — just scan first 2000 chars)
            content_words = set(re.findall(r'\w+', chunk.content[:2000].lower()))
            score += len(prompt_words & content_words) * 2

            # Prefer shorter files (less noise)
            score -= chunk.token_estimate * 0.001

            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Greedily fill up to max_tokens
        selected = []
        used_tokens = 0
        for _, chunk in scored:
            if used_tokens + chunk.token_estimate > max_tokens:
                break
            selected.append(chunk)
            used_tokens += chunk.token_estimate

        return selected