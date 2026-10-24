import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.public_access import supported_public_match

client = TestClient(app)


def test_demo_is_default_and_does_not_need_guid(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "false")
    response = client.post("/api/analysis", json={"match_id": "match-001", "audience": "fan", "question": "Why is the home team favored?"})
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


def test_foundry_access_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "false")
    response = client.post("/api/foundry/access", json={"access_guid": "public-demo-guid"})
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_foundry_access_requires_exact_guid(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")
    assert client.post("/api/foundry/access", json={"access_guid": "wrong"}).status_code == 403
    assert client.post("/api/foundry/access", json={"access_guid": "public-demo-guid"}).status_code == 200


def test_direct_foundry_request_uses_gate_then_fails_without_foundry_configuration(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    response = client.post("/api/analysis", headers={"x-matchlens-session": "browser-1"}, json={"mode": "foundry", "access_guid": "public-demo-guid", "match_id": "match-001", "audience": "fan", "question": "Why is the home team favored?"})
    assert response.status_code == 503
    assert "FOUNDRY_PROJECT_ENDPOINT" in response.json()["detail"]


def test_live_mode_cannot_expand_unverified_fixture(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")
    response = client.post("/api/analysis", json={"mode": "foundry", "access_guid": "public-demo-guid", "match_id": "match-002", "audience": "fan", "question": "Why?"})
    assert response.status_code == 400
    assert "verified match" in response.json()["detail"]


def test_question_length_is_bounded():
    response = client.post("/api/analysis", json={"match_id": "match-001", "audience": "fan", "question": "x" * 301})
    assert response.status_code == 422


def test_supported_fixture_is_explicit(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PUBLIC_MATCH_IDS", raising=False)
    assert supported_public_match("match-001")
    assert not supported_public_match("match-002")
