import json
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from github_client import FileFetchResult, GitHubClient, MAX_ATTEMPTS, REQUEST_TIMEOUT


class FakeResponse:
    def __init__(self, status, headers=None, message=None):
        self.status = status
        self.headers = headers or {}
        self.reason = "HTTP error"
        self.body = json.dumps({"message": message}) if message else "{}"

    async def read(self):
        return self.body.encode()

    async def text(self):
        return self.body

    def release(self):
        pass


class GitHubRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = GitHubClient()
        self.session = AsyncMock()

    async def test_retries_server_errors_with_bounded_backoff(self):
        success = FakeResponse(200)
        self.session.request.side_effect = [FakeResponse(503), success]

        with patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            response = await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.assertIs(response, success)
        self.assertEqual(self.session.request.await_count, 2)
        sleep.assert_awaited_once_with(1)

    async def test_rate_limit_retry_respects_retry_after(self):
        success = FakeResponse(200)
        self.session.request.side_effect = [
            FakeResponse(429, {"Retry-After": "4"}),
            success,
        ]

        with patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            response = await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.assertIs(response, success)
        sleep.assert_awaited_once_with(4)

    async def test_primary_rate_limit_waits_until_reset(self):
        success = FakeResponse(200)
        self.session.request.side_effect = [
            FakeResponse(
                403,
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1005"},
            ),
            success,
        ]

        with (
            patch("github_client.time.time", return_value=1000),
            patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            response = await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.assertIs(response, success)
        sleep.assert_awaited_once_with(5)

    async def test_rate_limit_reset_beyond_delay_cap_fails_without_early_retry(self):
        self.session.request.return_value = FakeResponse(
            403,
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1100"},
            "API rate limit exceeded",
        )

        with (
            patch("github_client.time.time", return_value=1000),
            patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "retry manually later"):
                await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.session.request.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_permanent_http_error_is_not_retried_and_includes_github_message(self):
        self.session.request.return_value = FakeResponse(404, message="Not Found")

        with patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(RuntimeError, r"404.*Not Found"):
                await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.session.request.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_network_errors_retry_only_up_to_attempt_limit(self):
        self.session.request.side_effect = aiohttp.ClientConnectionError("connection failed")

        with patch("github_client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(RuntimeError, f"after {MAX_ATTEMPTS} attempts"):
                await self.client._request(self.session, "GET", "https://api.github.com/test")

        self.assertEqual(self.session.request.await_count, MAX_ATTEMPTS)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [1, 2])

    async def test_fetch_file_reports_failed_response_without_treating_empty_content_as_failure(self):
        class EmptyResponse:
            status = 200

            async def read(self):
                return b"{}"

            async def json(self):
                return {"encoding": "base64", "content": "", "type": "file"}

            def release(self):
                pass

        async def fake_request(*args, **kwargs):
            return EmptyResponse()

        session = AsyncMock()
        session.request.side_effect = fake_request

        result = await self.client._fetch_file(session, "owner", "repo", "empty.txt")

        self.assertEqual(result.status, "fetched")
        self.assertEqual(result.content, "")
        self.assertIsNone(result.reason)

    async def test_fetch_file_reports_http_failure_with_details(self):
        class FailedResponse:
            status = 500
            reason = "Internal Server Error"

            async def read(self):
                return b"{}"

            async def text(self):
                return "{}"

            def release(self):
                pass

        async def fake_request(*args, **kwargs):
            return FailedResponse()

        session = AsyncMock()
        session.request.side_effect = fake_request

        result = await self.client._fetch_file(session, "owner", "repo", "broken.js")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.category, "http")
        self.assertIn("500", result.reason)

    async def test_get_files_can_retry_only_failed_paths(self):
        tree = [
            type("Node", (), {"path": "ok.py", "type": "blob"})(),
            type("Node", (), {"path": "bad.py", "type": "blob"})(),
            type("Node", (), {"path": "empty.md", "type": "blob"})(),
        ]

        async def fake_fetch_file(session, owner, repo, path):
            if path == "ok.py":
                return FileFetchResult(path=path, content="print('ok')", status="fetched")
            if path == "bad.py":
                return FileFetchResult(path=path, content=None, status="failed", reason="GitHub returned HTTP 500", category="http")
            if path == "empty.md":
                return FileFetchResult(path=path, content="", status="fetched")
            return FileFetchResult(path=path, content="", status="fetched")

        with patch.object(self.client, "_fetch_file", new=fake_fetch_file):
            result = await self.client.get_files("owner", "repo", tree, retry_failed=["bad.py"])

        self.assertEqual(list(result.keys()), [])
        self.assertEqual(result.indexing.failed, 1)
        self.assertEqual(result.indexing.failed_files[0].path, "bad.py")
        self.assertEqual(result.indexing.complete, False)

    def test_requests_have_explicit_connect_and_total_timeouts(self):
        self.assertEqual(REQUEST_TIMEOUT.connect, 5)
        self.assertEqual(REQUEST_TIMEOUT.total, 30)


if __name__ == "__main__":
    unittest.main()
