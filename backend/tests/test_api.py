from models import RepoSummary


def test_get_repos_returns_empty_list(api_client):
    response = api_client.get("/repos")

    assert response.status_code == 200
    assert response.json()["repos"] == []


def test_sync_repos_uses_github_client_and_persists_result(api_client, monkeypatch):
    import main

    async def list_repos():
        return [
            RepoSummary(
                id=1,
                full_name="owner/repo",
                owner="owner",
                name="repo",
                html_url="https://github.com/owner/repo",
            ),
        ]

    monkeypatch.setattr(main.github, "list_user_repos", list_repos)
    response = api_client.post("/repos/sync")

    assert response.status_code == 200
    assert [repo["full_name"] for repo in response.json()["repos"]] == ["owner/repo"]


def test_sync_repos_returns_400_when_token_is_missing(api_client, monkeypatch):
    import main

    monkeypatch.delitem(main.github.headers, "Authorization", raising=False)
    response = api_client.post("/repos/sync")

    assert response.status_code == 400
    assert "GITHUB_TOKEN is not set" in response.json()["detail"]


def test_load_repo_reports_partial_indexing_when_files_fail(api_client, monkeypatch):
    import github_client
    import main
    from models import FileFetchFailure, RepoMeta, TreeNode

    async def fake_get_tree(owner, repo):
        return [
            TreeNode(path="ok.py", type="blob"),
            TreeNode(path="bad.py", type="blob"),
        ]

    async def fake_get_files(owner, repo, tree, max_files=300, retry_failed=None):
        class FakeResult(dict):
            def __init__(self):
                super().__init__({"ok.py": "print('ok')"})
                self.summary = github_client.IndexingSummary(
                    complete=False,
                    fetched=1,
                    skipped=0,
                    failed=1,
                    failed_files=[FileFetchFailure(path="bad.py", reason="GitHub returned HTTP 500", category="http")],
                )

        return FakeResult()

    async def fake_get_repo_meta(owner, repo):
        return RepoMeta(full_name="owner/repo")

    monkeypatch.setattr(main.github, "get_tree", fake_get_tree)
    monkeypatch.setattr(main.github, "get_files", fake_get_files)
    monkeypatch.setattr(main.github, "get_repo_meta", fake_get_repo_meta)

    response = api_client.post("/repo/load", json={"url": "https://github.com/owner/repo"})

    assert response.status_code == 200
    data = response.json()
    assert data["complete"] is False
    assert data["partial"] is True
    assert data["indexing"]["failed"] == 1
    assert data["failed_files"][0]["path"] == "bad.py"


def test_chat_returns_404_for_unknown_session(api_client):
    response = api_client.post(
        "/chat",
        json={"session_id": "missing", "prompt": "hello"},
    )

    assert response.status_code == 404
