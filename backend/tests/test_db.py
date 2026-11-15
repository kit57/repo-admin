from datetime import datetime, timezone
from unittest.mock import patch

import db
from models import RepoSummary


def _repo(repo_id, full_name, pushed_at, description=None):
    owner, name = full_name.split("/")
    return RepoSummary(
        id=repo_id,
        full_name=full_name,
        owner=owner,
        name=name,
        description=description,
        html_url=f"https://github.com/{full_name}",
        pushed_at=pushed_at,
    )


def test_replace_repos_upserts_orders_and_removes_missing_repos(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "repos.sqlite"))
    db.init_db()

    with patch("db.datetime") as datetime_mock:
        datetime_mock.now.side_effect = [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ]
        db.replace_repos([
            _repo(1, "owner/older", "2026-01-01T00:00:00Z"),
            _repo(2, "owner/newer", "2026-02-01T00:00:00Z"),
        ])
        db.replace_repos([
            _repo(1, "owner/older", "2026-03-01T00:00:00Z", "Updated"),
        ])

    repos = db.list_repos()
    assert [repo.full_name for repo in repos] == ["owner/older"]
    assert repos[0].description == "Updated"
