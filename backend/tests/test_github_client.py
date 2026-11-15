import json
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from github_client import GitHubClient, MAX_ATTEMPTS, REQUEST_TIMEOUT


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

    def test_requests_have_explicit_connect_and_total_timeouts(self):
        self.assertEqual(REQUEST_TIMEOUT.connect, 5)
        self.assertEqual(REQUEST_TIMEOUT.total, 30)


if __name__ == "__main__":
    unittest.main()
