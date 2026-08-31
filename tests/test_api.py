from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.errors import ProfileNotFoundError, RateLimitedError, SessionRevokedError
from app.linkedin.client import VoyagerResponse
from app.linkedin.mapper import UNVERIFIED_SECTIONS
from app.main import app, fresh_cache, get_transport, reset_runtime_state, upstream_timestamps

TEST_COOKIE = "test-session-cookie-value-xyz"
PROFILE_URL = "https://www.linkedin.com/in/alex-rivera-demo"
RICH_URL = "https://www.linkedin.com/in/taylor-quinn-demo"


class RecordingTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []
        self.raise_exc: Exception | None = None
        self.delay = 0.0

    async def get(self, url: str, headers: dict) -> VoyagerResponse:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append((url, dict(headers)))
        if self.raise_exc is not None:
            raise self.raise_exc
        return VoyagerResponse(200, {}, json.dumps(self.payload), url)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    get_settings.cache_clear()
    reset_runtime_state()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    reset_runtime_state()
    get_settings.cache_clear()


@pytest.fixture
def transport(sample_payload: dict) -> RecordingTransport:
    return RecordingTransport(sample_payload)


@pytest.fixture
def client(transport: RecordingTransport) -> TestClient:
    app.dependency_overrides[get_transport] = lambda: transport
    with TestClient(app) as test_client:
        yield test_client


def _meta_flags(body: dict) -> tuple[str, bool, bool, object]:
    meta = body["meta"]
    return meta["source"], meta["cached"], meta["stale"], meta["stale_reason"]


def test_post_profile_success(client: TestClient, transport: RecordingTransport) -> None:
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["profile"]["full_name"] == "Alex Rivera"
    source, cached, stale, stale_reason = _meta_flags(body)
    assert (source, cached, stale, stale_reason) == ("live", False, False, None)
    assert TEST_COOKIE not in response.text


def test_get_profile_success(client: TestClient) -> None:
    response = client.get("/v1/profile", params={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 200


def test_rich_payload_serialises_new_sections(client: TestClient, transport: RecordingTransport, rich_payload: dict) -> None:
    transport.payload = rich_payload
    response = client.get("/v1/profile", params={"url": RICH_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]["projects"]) == 2
    assert len(body["data"]["featured_media"]) == 2
    assert body["meta"]["unverified_sections"] == list(UNVERIFIED_SECTIONS)
    assert len(body["meta"]["unverified_sections"]) == 7


def test_invalid_url(client: TestClient) -> None:
    response = client.post("/v1/profile", json={"url": "not-a-url"}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "InvalidProfileURLError"


def test_missing_credentials(client: TestClient) -> None:
    response = client.post("/v1/profile", json={"url": PROFILE_URL})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "MissingCredentialsError"


def test_company_url(client: TestClient) -> None:
    response = client.post(
        "/v1/profile",
        json={"url": "https://www.linkedin.com/company/northwind"},
        headers={"X-LI-AT": TEST_COOKIE},
    )
    assert response.status_code == 400


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["server_session_configured"], bool)
    assert isinstance(body["proxy_configured"], bool)
    assert "api_key_required" not in body


def test_ui_index_is_html_and_docs_still_exist(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "text/html" in home.headers["content-type"]
    assert "Profile lookup" in home.text
    assert "Look up" in home.text
    assert "Load example" not in home.text
    assert "example-btn" not in home.text
    assert "health-badges" not in home.text
    assert 'href="/health"' not in home.text
    assert 'id="api_key"' not in home.text
    assert "API key" not in home.text
    assert 'href="/docs"' in home.text
    docs = client.get("/docs")
    assert docs.status_code == 200


def test_ui_post_shape_matches_backend(client: TestClient, transport: RecordingTransport) -> None:
    """Same request the page sends: JSON {url} plus optional X-LI-AT, no X-API-Key."""
    response = client.post(
        "/v1/profile",
        json={"url": PROFILE_URL},
        headers={"X-LI-AT": TEST_COOKIE, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["profile"]["full_name"] == "Alex Rivera"
    assert body["meta"]["source"] == "live"
    assert transport.calls


def test_ui_missing_cookie_error_shape(client: TestClient) -> None:
    missing = client.post("/v1/profile", json={"url": PROFILE_URL})
    assert missing.status_code == 401
    err = missing.json()
    assert err["success"] is False
    assert err["error"]["type"] == "MissingCredentialsError"


def test_api_key_gates_lookup_but_not_example(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "secret-key")
    get_settings.cache_clear()
    missing = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert missing.status_code == 401
    wrong = client.post(
        "/v1/profile",
        json={"url": PROFILE_URL},
        headers={"X-LI-AT": TEST_COOKIE, "X-API-Key": "nope"},
    )
    assert wrong.status_code == 401
    ok = client.post(
        "/v1/profile",
        json={"url": PROFILE_URL},
        headers={"X-LI-AT": TEST_COOKIE, "X-API-Key": "secret-key"},
    )
    assert ok.status_code == 200
    example = client.get("/v1/profile/example")
    assert example.status_code == 200


def test_session_revoked_empty_stale_cache_returns_401(client: TestClient, transport: RecordingTransport) -> None:
    transport.raise_exc = SessionRevokedError()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "SessionRevokedError"


def test_rate_limited_empty_stale_cache_returns_429(client: TestClient, transport: RecordingTransport) -> None:
    transport.raise_exc = RateLimitedError()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 429


def test_second_request_is_cache_hit(client: TestClient, transport: RecordingTransport) -> None:
    first = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    second = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(transport.calls) == 1
    assert first.json()["meta"]["cached"] is False
    assert first.json()["meta"]["source"] == "live"
    assert second.json()["meta"]["cached"] is True
    assert second.json()["meta"]["source"] == "cache"
    assert first.json()["meta"]["fetched_at"] == second.json()["meta"]["fetched_at"]
    source, cached, stale, stale_reason = _meta_flags(second.json())
    assert (source, cached, stale, stale_reason) == ("cache", True, False, None)


def test_example_route_uses_fixture_and_no_network(client: TestClient, transport: RecordingTransport) -> None:
    response = client.get("/v1/profile/example")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "fixture"
    assert body["data"]["profile"]["full_name"] == "Alex Rivera"
    assert len(transport.calls) == 0
    source, cached, stale, stale_reason = _meta_flags(body)
    assert (source, cached, stale, stale_reason) == ("fixture", False, False, None)


def test_example_missing_file(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXAMPLE_FIXTURE_PATH", "fixtures/does-not-exist.json")
    get_settings.cache_clear()
    response = client.get("/v1/profile/example")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert "Traceback" not in response.text


def test_cache_does_not_bypass_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    primed = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert primed.status_code == 200
    monkeypatch.setenv("API_KEY", "secret-key")
    get_settings.cache_clear()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 401


def test_cache_does_not_bypass_credentials(client: TestClient) -> None:
    primed = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert primed.status_code == 200
    response = client.post("/v1/profile", json={"url": PROFILE_URL})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "MissingCredentialsError"


def test_serve_stale_on_session_revoked(client: TestClient, transport: RecordingTransport) -> None:
    primed = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert primed.status_code == 200
    fresh_cache.clear()
    transport.raise_exc = SessionRevokedError()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "stale"
    assert body["meta"]["stale"] is True
    assert body["meta"]["cached"] is True
    assert body["meta"]["stale_reason"] == "SessionRevokedError"
    assert body["meta"]["fetched_at"] == primed.json()["meta"]["fetched_at"]
    assert body["data"] == primed.json()["data"]
    source, cached, stale, stale_reason = _meta_flags(body)
    assert (source, cached, stale, stale_reason) == ("stale", True, True, "SessionRevokedError")


def test_stale_does_not_mask_profile_not_found(client: TestClient, transport: RecordingTransport) -> None:
    primed = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert primed.status_code == 200
    fresh_cache.clear()
    transport.raise_exc = ProfileNotFoundError()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 404


def test_stale_does_not_bypass_auth(
    client: TestClient, transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    primed = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert primed.status_code == 200
    fresh_cache.clear()
    transport.raise_exc = SessionRevokedError()
    monkeypatch.setenv("API_KEY", "secret-key")
    get_settings.cache_clear()
    response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_single_flight_same_vanity(sample_payload: dict) -> None:
    transport = RecordingTransport(sample_payload)
    transport.delay = 0.2
    app.dependency_overrides[get_transport] = lambda: transport
    reset_runtime_state()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
        first, second = await asyncio.gather(
            async_client.get("/v1/profile", params={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE}),
            async_client.get("/v1/profile", params={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE}),
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_single_flight_is_per_vanity(sample_payload: dict) -> None:
    transport = RecordingTransport(sample_payload)
    transport.delay = 0.2
    app.dependency_overrides[get_transport] = lambda: transport
    reset_runtime_state()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
        first, second = await asyncio.gather(
            async_client.get("/v1/profile", params={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE}),
            async_client.get("/v1/profile", params={"url": RICH_URL}, headers={"X-LI-AT": TEST_COOKIE}),
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(transport.calls) == 2


def test_upstream_ceiling_default(client: TestClient, transport: RecordingTransport) -> None:
    for index in range(8):
        response = client.get(
            "/v1/profile",
            params={"url": f"https://www.linkedin.com/in/person-{index}"},
            headers={"X-LI-AT": TEST_COOKIE},
        )
        assert response.status_code == 200, response.text
    ninth = client.get(
        "/v1/profile",
        params={"url": "https://www.linkedin.com/in/person-8"},
        headers={"X-LI-AT": TEST_COOKIE},
    )
    assert ninth.status_code == 429
    assert len(transport.calls) == 8
    assert "did not reach LinkedIn" in ninth.json()["error"]["message"]
    assert "local upstream ceiling" in ninth.json()["error"]["message"]


def test_upstream_ceiling_configurable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTREAM_LIMIT", "2")
    get_settings.cache_clear()
    reset_runtime_state()
    for index in range(2):
        response = client.get(
            "/v1/profile",
            params={"url": f"https://www.linkedin.com/in/limit-{index}"},
            headers={"X-LI-AT": TEST_COOKIE},
        )
        assert response.status_code == 200
    third = client.get(
        "/v1/profile",
        params={"url": "https://www.linkedin.com/in/limit-2"},
        headers={"X-LI-AT": TEST_COOKIE},
    )
    assert third.status_code == 429


def test_per_client_rate_limit(client: TestClient, transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_runtime_state()
    for index in range(2):
        response = client.get(
            "/v1/profile",
            params={"url": f"https://www.linkedin.com/in/rate-{index}"},
            headers={"X-LI-AT": TEST_COOKIE},
        )
        assert response.status_code == 200
    third = client.get(
        "/v1/profile",
        params={"url": "https://www.linkedin.com/in/rate-2"},
        headers={"X-LI-AT": TEST_COOKIE},
    )
    assert third.status_code == 429
    message = third.json()["error"]["message"]
    assert "per-client" in message
    assert "did not reach LinkedIn" in message
    assert "local upstream ceiling" not in message
    assert len(transport.calls) == 2
    assert len(upstream_timestamps) == 2


def test_example_exempt_from_limits(client: TestClient, transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("UPSTREAM_LIMIT", "1")
    get_settings.cache_clear()
    for _ in range(5):
        response = client.get("/v1/profile/example")
        assert response.status_code == 200
    assert len(transport.calls) == 0
    assert len(upstream_timestamps) == 0


def test_cookie_never_appears_in_body_or_logs(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.post("/v1/profile", json={"url": PROFILE_URL}, headers={"X-LI-AT": TEST_COOKIE})
    assert response.status_code == 200
    assert TEST_COOKIE not in response.text
    for record in caplog.records:
        assert TEST_COOKIE not in record.getMessage()
