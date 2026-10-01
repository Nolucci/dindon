"""The /health endpoint."""
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from synthetic import settings_for


def test_health_reports_the_state_of_the_database(migrated_url, tmp_path):
    with TestClient(create_app(settings_for(migrated_url, tmp_path), background=False)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # 37 tables of the starter kit, 9 views, 21 axes of which the 12 of the model are active
    assert body["database"]["tables"] == 37 and body["database"]["views"] == 9
    assert body["database"]["axes"] == 21 and body["database"]["axes_active"] == 12
    assert body["ollama"] == {"reachable": False, "models": []}  # the AI is optional: not a failure


def test_health_says_503_without_details_when_the_database_is_down(tmp_path):
    app = create_app(settings_for("postgresql://dindon:wrong@127.0.0.1:9/dindon", tmp_path), background=False)
    response = TestClient(app).get("/health")  # no lifespan: the pool is not opened, only /health is used
    assert response.status_code == 503
    assert "wrong" not in response.text and "127.0.0.1" not in response.text
