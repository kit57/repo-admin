import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    database_path = tmp_path / "api-tests.sqlite"
    monkeypatch.setenv("DB_PATH", str(database_path))

    import main

    main.db.DB_PATH = str(database_path)
    main.db.init_db()
    main.sessions.clear()

    with TestClient(main.app) as client:
        yield client

    main.sessions.clear()
