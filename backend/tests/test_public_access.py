import asyncio
import httpx
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app import public_access
from app.agents import mock_workflow
from app.agents.foundry_workflow import FoundryResponseError
from app.api import routes
from app.public_access import supported_public_match

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_process_limits():
    public_access._reset_foundry_process_limits_for_tests()
    routes._analysis_requests.clear()
    yield
    public_access._reset_foundry_process_limits_for_tests()
    routes._analysis_requests.clear()


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


def test_foundry_attempt_counts_error_and_enforces_daily_limit(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")

    attempts = 0

    async def failed_analysis(_request):
        nonlocal attempts
        attempts += 1
        raise FoundryResponseError("simulated Foundry failure")

    monkeypatch.setattr(routes, "run_analysis", failed_analysis)
    body = {"mode": "foundry", "access_guid": "public-demo-guid", "match_id": "match-001", "audience": "fan", "question": "Why?"}
    responses = [client.post("/api/analysis", json=body) for _ in range(11)]
    assert [response.status_code for response in responses[:10]] == [502] * 10
    assert responses[10].status_code == 429
    assert "daily Foundry" in responses[10].json()["detail"]
    assert attempts == 10
    assert public_access._foundry_process_state.daily_attempts == 10
    assert public_access._foundry_process_state.lifetime_attempts == 10


def test_foundry_attempt_counts_failed_call_against_lifetime_limit(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")
    public_access._foundry_process_state.lifetime_attempts = 39
    public_access._foundry_process_state.daily_attempts = 0

    async def failed_analysis(_request):
        raise FoundryResponseError("simulated Foundry failure")

    monkeypatch.setattr(routes, "run_analysis", failed_analysis)
    body = {"mode": "foundry", "access_guid": "public-demo-guid", "match_id": "match-001", "audience": "fan", "question": "Why?"}
    assert client.post("/api/analysis", json=body).status_code == 502
    response = client.post("/api/analysis", json=body)
    assert response.status_code == 429
    assert "Foundry lifetime" in response.json()["detail"]
    assert public_access._foundry_process_state.lifetime_attempts == 40


def test_foundry_attempts_are_single_flight_under_concurrent_requests(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PUBLIC_ENABLED", "true")
    monkeypatch.setenv("FOUNDRY_PUBLIC_ACCESS_GUID", "public-demo-guid")
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_analysis(request):
        started.set()
        await release.wait()
        return mock_workflow.run_mock(request)

    monkeypatch.setattr(routes, "run_analysis", blocked_analysis)
    body = {"mode": "foundry", "access_guid": "public-demo-guid", "match_id": "match-001", "audience": "fan", "question": "Why?"}

    async def send_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            first = asyncio.create_task(async_client.post("/api/analysis", json=body))
            await started.wait()
            second = await async_client.post("/api/analysis", json=body)
            release.set()
            first_response = await first
            return first_response, second

    first, second = asyncio.run(send_requests())
    assert first.status_code == 200
    assert second.status_code == 429
    assert "already active" in second.json()["detail"]
    assert public_access._foundry_process_state.active_attempts == 0


def test_foundry_limits_do_not_change_mock_mode(monkeypatch):
    public_access._foundry_process_state.daily_attempts = 10
    public_access._foundry_process_state.lifetime_attempts = 40
    response = client.post("/api/analysis", json={"match_id": "match-001", "audience": "fan", "question": "Why?"})
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


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
