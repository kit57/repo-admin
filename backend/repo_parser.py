import os
import re
from dataclasses import dataclass

# Rough token estimate: 1 token ≈ 4 chars
CHARS_PER_TOKEN = 4
MAX_CHUNK_CHARS = 12_000
STOP_WORDS = {
    "a", "about", "add", "after", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "get", "had", "has",
    "have", "how", "i", "in", "into", "is", "it", "its", "just", "me", "more",
    "most", "my", "of", "on", "or", "our", "please", "should", "so", "some",
    "such", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "under", "up", "use", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your",
}


@dataclass
class FileChunk:
    path: str
    content: str
    token_estimate: int
    start_line: int = 1
    end_line: int = 1

    @property
    def formatted(self) -> str:
        line_range = f" (lines {self.start_line}-{self.end_line})"
        return f"### File: {self.path}{line_range}\n```\n{self.content}\n```\n"


class RepoParser:
    def chunk_files(self, files: dict[str, str]) -> list[FileChunk]:
        """Split files into bounded, line-addressable chunks without dropping their tails."""
        chunks = []
        for path, content in files.items():
            if not content:
                chunks.append(FileChunk(path=path, content="", token_estimate=0))
                continue
            start = 0
            start_line = 1
            while start < len(content):
                end = min(start + MAX_CHUNK_CHARS, len(content))
                if end < len(content):
                    newline = content.rfind("\n", start, end)
                    if newline > start:
                        end = newline + 1
                chunk_content = content[start:end]
                line_count = chunk_content.count("\n")
                end_line = start_line + line_count - int(chunk_content.endswith("\n"))
                chunks.append(
                    FileChunk(
                        path=path,
                        content=chunk_content,
                        token_estimate=(len(chunk_content) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN,
                        start_line=start_line,
                        end_line=max(start_line, end_line),
                    )
                )
                start = end
                start_line += line_count
        return chunks

    @staticmethod
    def _keywords(text: str) -> set[str]:
        split_camel_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        return {
            word for word in re.findall(r"[a-z0-9]+", split_camel_case.lower())
            if len(word) > 1 and word not in STOP_WORDS
        }

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
        prompt_words = self._keywords(prompt)
        pinned_paths = set(context_files)

        scored: list[tuple[float, FileChunk]] = []
        for chunk in chunks:
            score = 0.0
            path_lower = chunk.path.lower()
            filename = os.path.basename(path_lower)

            if chunk.path in pinned_paths:
                score += 1000

            stem = os.path.splitext(filename)[0]
            if stem and stem in prompt_lower:
                score += 50

            path_words = self._keywords(path_lower)
            score += len(prompt_words & path_words) * 5

            content_words = self._keywords(chunk.content)
            score += len(prompt_words & content_words) * 2

            score -= chunk.token_estimate * 0.0001

            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected = [chunk for _, chunk in scored if chunk.path in pinned_paths]
        selected_ids = {id(chunk) for chunk in selected}
        used_tokens = sum(chunk.token_estimate for chunk in selected)

        for score, chunk in scored:
            if id(chunk) in selected_ids or score <= 0:
                continue
            if used_tokens + chunk.token_estimate > max_tokens:
                continue
            selected.append(chunk)
            used_tokens += chunk.token_estimate

        return selected

    def search_code(
        self, files: dict[str, str], query: str, max_results: int = 8,
    ) -> str:
        """Find matching lines across complete loaded files, with surrounding context."""
        keywords = self._keywords(query)
        if not keywords:
            return "Search needs at least one non-stop-word keyword."

        matches: list[tuple[int, str, int, list[str]]] = []
        for path, content in files.items():
            lines = content.splitlines()
            for index, line in enumerate(lines):
                line_words = self._keywords(line)
                score = len(keywords & line_words)
                if score:
                    first = max(0, index - 2)
                    last = min(len(lines), index + 3)
                    matches.append((score, path, index + 1, lines[first:last]))

        matches.sort(key=lambda item: (-item[0], item[1], item[2]))
        if not matches:
            return f"No matches found in the {len(files)} loaded files."

        results = []
        for _, path, line_number, excerpt in matches[:max_results]:
            start_line = max(1, line_number - 2)
            formatted_lines = [
                f"{start_line + offset}: {line[:500]}"
                for offset, line in enumerate(excerpt)
            ]
            results.append(f"### {path}\n" + "\n".join(formatted_lines))
        return "\n\n".join(results)