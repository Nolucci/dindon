"""The /health endpoint."""
from pathlib import Path

from fastapi.testclient import TestClient

from dindon.api.main import create_app
from dindon.config import Settings

DB_DIR = Path(__file__).resolve().parents[1] / "db"


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        db_dir=DB_DIR,
        host="127.0.0.1",
        port=8000,
        ollama_url="http://127.0.0.1:9",  # nothing listens there
        password="test",
    )


def test_health_reports_the_state_of_the_database(migrated_url):
    response = TestClient(create_app(_settings(migrated_url))).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["tables"] == 37 and body["database"]["views"] == 9
    assert body["database"]["axes"] == 21 and body["database"]["axes_active"] == 12
    assert body["ollama"] == {"reachable": False, "models": []}  # the AI is optional: not a failure


def test_health_says_503_without_details_when_the_database_is_down():
    app = create_app(_settings("postgresql://dindon:wrong@127.0.0.1:9/dindon"))
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert "wrong" not in response.text and "127.0.0.1" not in response.text
