import os
import re
import asyncio
import aiohttp
import base64
import json
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from models import TreeNode, RepoMeta, RepoSummary

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=5)
MAX_ATTEMPTS = 3
BASE_RETRY_DELAY = 1
MAX_RETRY_DELAY = 30

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

    @staticmethod
    def _is_retryable(response: aiohttp.ClientResponse) -> bool:
        if response.status >= 500 or response.status == 429:
            return True
        return response.status == 403 and (
            response.headers.get("Retry-After") is not None
            or response.headers.get("X-RateLimit-Remaining") == "0"
        )

    @staticmethod
    def _retry_delay(response: aiohttp.ClientResponse, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0, float(retry_after))
            except ValueError:
                try:
                    return max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass

        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return max(0, float(reset) - time.time())
            except ValueError:
                pass

        return min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)

    @staticmethod
    async def _response_error(response: aiohttp.ClientResponse) -> str:
        try:
            body = json.loads(await response.text())
        except (aiohttp.ClientError, json.JSONDecodeError, UnicodeDecodeError):
            body = None

        detail = body.get("message") if isinstance(body, dict) else None
        return f"GitHub API request failed ({response.status}): {detail or response.reason or 'HTTP error'}"

    async def _request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        *,
        allow_statuses: tuple[int, ...] = (),
        allow_error_status: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        for attempt in range(MAX_ATTEMPTS):
            response = None
            try:
                response = await session.request(method, url, **kwargs)
                await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if response is not None:
                    response.release()
                if attempt + 1 == MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"GitHub API request failed after {MAX_ATTEMPTS} attempts: {e}"
                    ) from e
                await asyncio.sleep(min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY))
                continue

            if (
                response.status < 400
                or response.status in allow_statuses
                or allow_error_status
            ):
                return response

            if not self._is_retryable(response) or attempt + 1 == MAX_ATTEMPTS:
                raise RuntimeError(await self._response_error(response))

            delay = self._retry_delay(response, attempt)
            if delay > MAX_RETRY_DELAY:
                error = await self._response_error(response)
                raise RuntimeError(
                    f"{error}. GitHub requested a {delay:.0f}-second wait; retry manually later."
                )

            response.release()
            await asyncio.sleep(delay)

        raise AssertionError("unreachable")

    def parse_url(self, url: str) -> tuple[str, str]:
        """Extract owner and repo name from a GitHub URL."""
        match = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", url)
        if not match:
            raise ValueError(f"Cannot parse GitHub URL: {url}")
        return match.group(1), match.group(2)

    async def get_repo_meta(self, owner: str, repo: str) -> RepoMeta:
        async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
            resp = await self._request(session, "GET", f"{GITHUB_API}/repos/{owner}/{repo}")
            data = await resp.json()
            resp = await self._request(
                session, "GET", f"{GITHUB_API}/repos/{owner}/{repo}/languages",
            )
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

    async def get_open_issues(self, owner: str, repo: str) -> list[dict]:
        """Fetch open GitHub issues, excluding pull requests returned by the same API."""
        issues = []
        page = 1
        async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
            while True:
                params = {"state": "open", "per_page": 100, "page": page}
                resp = await self._request(
                    session,
                    "GET",
                    f"{GITHUB_API}/repos/{owner}/{repo}/issues",
                    params=params,
                )
                data = await resp.json()

                issues.extend(issue for issue in data if "pull_request" not in issue)
                if len(data) < 100:
                    break
                page += 1
        return issues

    async def list_user_repos(self) -> list[RepoSummary]:
        """List every repo the token's user owns or collaborates on (paginated)."""
        if "Authorization" not in self.headers:
            raise RuntimeError("GITHUB_TOKEN is not set — it is required to list your repositories")

        repos = []
        page = 1
        async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
            while True:
                params = {
                    "per_page": 100,
                    "page": page,
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "pushed",
                }
                resp = await self._request(
                    session, "GET", f"{GITHUB_API}/user/repos", params=params,
                )
                data = await resp.json()
                if not data:
                    break
                for r in data:
                    repos.append(RepoSummary(
                        id=r["id"],
                        full_name=r["full_name"],
                        owner=r["owner"]["login"],
                        name=r["name"],
                        description=r.get("description"),
                        html_url=r["html_url"],
                        private=r.get("private", False),
                        fork=r.get("fork", False),
                        archived=r.get("archived", False),
                        language=r.get("language"),
                        stars=r.get("stargazers_count", 0),
                        forks=r.get("forks_count", 0),
                        open_issues=r.get("open_issues_count", 0),
                        default_branch=r.get("default_branch"),
                        pushed_at=r.get("pushed_at"),
                        updated_at=r.get("updated_at"),
                    ))
                if len(data) < 100:
                    break
                page += 1
        return repos

    async def get_tree(self, owner: str, repo: str) -> list[TreeNode]:
        """Fetch the full recursive file tree."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
        async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
            resp = await self._request(session, "GET", url)
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
            resp = await self._request(session, "GET", url, allow_error_status=True)
            if resp.status != 200:
                return path, ""
            data = await resp.json()
            if data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                return path, content
        except Exception:
            pass
        return path, ""

    async def get_file(self, owner: str, repo: str, path: str) -> str:
        """Fetch one repository file by its exact tree path."""
        encoded_path = quote(path, safe="/")
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{encoded_path}"
        try:
            async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
                resp = await self._request(session, "GET", url, allow_statuses=(404,))
                if resp.status == 404:
                    raise ValueError(f"GitHub could not find repository file: {path}")
                data = await resp.json()
        except (aiohttp.ClientError, RuntimeError) as e:
            raise RuntimeError(f"GitHub API error retrieving {path}: {e}") from e

        if data.get("encoding") != "base64" or "content" not in data:
            raise RuntimeError(f"GitHub returned an unsupported file format for {path}")
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except (ValueError, TypeError) as e:
            raise RuntimeError(f"GitHub returned invalid content for {path}") from e

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

        async with aiohttp.ClientSession(headers=self.headers, timeout=REQUEST_TIMEOUT) as session:
            tasks = [fetch_with_limit(session, path) for path in readable]
            for path, content in await asyncio.gather(*tasks):
                if content:
                    results[path] = content

        return results