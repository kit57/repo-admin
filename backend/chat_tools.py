import json

MAX_READ_FILE_CHARS = 12_000
MAX_READ_FILE_LINES = 200


CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a repository file, optionally requesting a line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Exact path from the repository file tree"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search loaded repository files for matching code and return line-numbered excerpts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
]


def decode_tool_arguments(value: str | dict) -> dict:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def read_file(
    files: dict[str, str],
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    content = files.get(path)
    if content is None:
        return f"File not found in the loaded repository: {path}"

    lines = content.splitlines()
    if not lines:
        return f"{path} is empty."

    start = max(start_line, 1)
    requested_end = end_line if end_line is not None else start + 199
    end = min(max(requested_end, start), start + MAX_READ_FILE_LINES - 1, len(lines))
    if start > len(lines):
        return f"Line {start} is past the end of {path} ({len(lines)} lines)."

    excerpt_lines = []
    chars = 0
    last_line = start - 1
    truncated = False
    for number in range(start, end + 1):
        line = f"{number}: {lines[number - 1]}"
        separator = int(bool(excerpt_lines))
        remaining = MAX_READ_FILE_CHARS - chars - separator
        if remaining <= 0:
            truncated = True
            break
        if len(line) > remaining:
            line = line[:remaining]
            if line:
                excerpt_lines.append(line)
                chars += separator + len(line)
                last_line = number
            truncated = True
            break
        excerpt_lines.append(line)
        chars += separator + len(line)
        last_line = number

    excerpt = "\n".join(excerpt_lines)
    if truncated:
        excerpt += "\n... (output capped; request a smaller line range)"
    elif last_line < len(lines):
        excerpt += f"\n... ({len(lines) - last_line} more lines; request a later range)"
    return f"### {path} (lines {start}-{max(last_line, start)})\n{excerpt}"
