"""Tests for GET /v1/healthz and GET /v1/branches."""
from app.constants.branches import NBA_BRANCHES


def test_health_check(client):
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_branches_returns_list(client):
    response = client.get("/v1/branches")
    assert response.status_code == 200
    data = response.json()
    assert "branches" in data
    assert isinstance(data["branches"], list)


def test_branches_content(client):
    response = client.get("/v1/branches")
    data = response.json()
    branches = data["branches"]
    # Check a representative set of branches are present
    for expected in ["Lagos", "Abuja", "Port Harcourt", "Kano", "Enugu"]:
        assert expected in branches, f"Expected branch '{expected}' not found"


def test_branches_matches_constant(client):
    response = client.get("/v1/branches")
    assert response.json()["branches"] == NBA_BRANCHES


def test_branches_no_duplicates(client):
    response = client.get("/v1/branches")
    branches = response.json()["branches"]
    assert len(branches) == len(set(branches)), "Branch list contains duplicates"
