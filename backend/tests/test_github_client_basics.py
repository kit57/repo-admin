import pytest

from github_client import GitHubClient


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("https://github.com/owner/repo/tree/main/src", ("owner", "repo")),
    ],
)
def test_parse_url(url, expected):
    assert GitHubClient().parse_url(url) == expected


@pytest.mark.parametrize("url", ["not a url", "https://gitlab.com/owner/repo"])
def test_parse_url_rejects_non_github_urls(url):
    with pytest.raises(ValueError):
        GitHubClient().parse_url(url)


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "frontend/src/App.jsx",
        "README.md",
    ],
)
def test_is_readable_accepts_source_and_documentation(path):
    assert GitHubClient()._is_readable(path)


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/package/index.js",
        "backend/.venv/lib/site.py",
        "assets/logo.png",
        "frontend/package-lock.json",
    ],
)
def test_is_readable_rejects_skipped_folders_and_extensions(path):
    assert not GitHubClient()._is_readable(path)
