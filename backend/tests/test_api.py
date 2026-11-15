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


def test_chat_returns_404_for_unknown_session(api_client):
    response = api_client.post(
        "/chat",
        json={"session_id": "missing", "prompt": "hello"},
    )

    assert response.status_code == 404
