import os
import re
import asyncio
import aiohttp
from models import TreeNode, RepoMeta

GITHUB_API = "https://api.github.com"

# Extensions worth reading — skip binaries, assets, lock files
READABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
    ".md", ".mdx", ".txt", ".rst", ".toml", ".yaml", ".yml",
    ".json", ".env.example", ".sh", ".bash", ".zsh",
    ".html", ".css", ".scss", ".sql",
}

SKIP_PATHS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache",
    "dist", "build", ".next", "vendor", "venv", ".venv",
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
}


class GitHubClient:
    def __init__(self):
        token = os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def parse_url(self, url: str) -> tuple[str, str]:
        """Extract owner and repo name from a GitHub URL."""
        match = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", url)
        if not match:
            raise ValueError(f"Cannot parse GitHub URL: {url}")
        return match.group(1), match.group(2)

    async def get_repo_meta(self, owner: str, repo: str) -> RepoMeta:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(f"{GITHUB_API}/repos/{owner}/{repo}") as resp:
                resp.raise_for_status()
                data = await resp.json()

            async with session.get(f"{GITHUB_API}/repos/{owner}/{repo}/languages") as resp:
                resp.raise_for_status()
                languages = await resp.json()

        return RepoMeta(
            full_name=data["full_name"],
            description=data.get("description"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            open_issues=data.get("open_issues_count", 0),
            default_branch=data.get("default_branch", "main"),
            language=data.get("language"),
            languages=languages,
            last_push=data.get("pushed_at"),
        )

    async def get_tree(self, owner: str, repo: str) -> list[TreeNode]:
        """Fetch the full recursive file tree."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()

        nodes = []
        for item in data.get("tree", []):
            path = item["path"]
            if any(skip in path.split("/") for skip in SKIP_PATHS):
                continue
            nodes.append(TreeNode(
                path=path,
                type=item["type"],
                size=item.get("size"),
            ))
        return nodes

    def _is_readable(self, path: str) -> bool:
        if any(skip in path.split("/") for skip in SKIP_PATHS):
            return False
        _, ext = os.path.splitext(path)
        return ext.lower() in READABLE_EXTENSIONS

    async def _fetch_file(self, session: aiohttp.ClientSession, owner: str, repo: str, path: str) -> tuple[str, str]:
        """Fetch a single file's content. Returns (path, content)."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return path, ""
                data = await resp.json()
                if data.get("encoding") == "base64":
                    import base64
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return path, content
        except Exception:
            pass
        return path, ""

    async def get_files(
        self,
        owner: str,
        repo: str,
        tree: list[TreeNode],
        max_files: int = 300,
    ) -> dict[str, str]:
        """Fetch file contents concurrently. Returns {path: content}."""
        readable = [
            node.path for node in tree
            if node.type == "blob" and self._is_readable(node.path)
        ][:max_files]

        results = {}
        # Batch requests to avoid hammering the API
        semaphore = asyncio.Semaphore(10)

        async def fetch_with_limit(session, path):
            async with semaphore:
                return await self._fetch_file(session, owner, repo, path)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [fetch_with_limit(session, path) for path in readable]
            for path, content in await asyncio.gather(*tasks):
                if content:
                    results[path] = content

        return results