from fastapi.testclient import TestClient

from smart_grid.api import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metadata_contains_seed_and_solver():
    response = client.get("/metadata")
    assert response.status_code == 200
    body = response.json()
    assert body["seed"] == 31052026
    assert "highs" in body["solver"]


def test_project_run_returns_phases():
    response = client.get("/project/run")
    assert response.status_code == 200
    body = response.json()
    for key in ["phase1", "phase2", "phase3", "phase4", "phase5"]:
        assert key in body


def test_dcopf_with_rating_override():
    response = client.post("/dcopf", json={"rating_overrides": {"L2": 30}})
    assert response.status_code == 200
    body = response.json()
    assert abs(body["line_flows_mw"][1]) <= 30.000001


def test_scopf_default_contingency():
    response = client.post("/scopf", json={})
    assert response.status_code == 200
    body = response.json()
    assert "dispatch_mw" in body
    assert "total_cost_usd_per_h" in body
