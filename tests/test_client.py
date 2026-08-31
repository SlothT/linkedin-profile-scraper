import json

import pytest

from app.errors import (
    ProfileNotFoundError,
    RateLimitedError,
    SessionRejectedError,
    SessionRevokedError,
    UpstreamShapeError,
)
from app.linkedin.client import VoyagerClient, VoyagerResponse
from app.linkedin.constants import DECORATION_CANDIDATES


class FakeTransport:
    def __init__(self, responses: list[VoyagerResponse] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._responses = list(responses or [])

    def queue(self, response: VoyagerResponse) -> None:
        self._responses.append(response)

    async def get(self, url: str, headers: dict) -> VoyagerResponse:
        self.calls.append((url, dict(headers)))
        if not self._responses:
            raise AssertionError("FakeTransport has no queued responses")
        queued = self._responses.pop(0)
        return VoyagerResponse(
            status_code=queued.status_code,
            headers=queued.headers,
            text=queued.text,
            request_url=url,
        )


def _json_response(payload: dict, status_code: int = 200) -> VoyagerResponse:
    return VoyagerResponse(status_code=status_code, headers={}, text=json.dumps(payload))


@pytest.mark.asyncio
async def test_fetch_profile_success_uses_first_decoration(sample_payload: dict) -> None:
    transport = FakeTransport([_json_response(sample_payload)])
    client = VoyagerClient("test-li-at", transport=transport)
    payload, decoration = await client.fetch_profile("alex-rivera-demo")
    assert payload == sample_payload
    assert decoration == DECORATION_CANDIDATES[0]
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_302_delete_me_revokes_session() -> None:
    transport = FakeTransport(
        [VoyagerResponse(302, {"set-cookie": 'li_at="delete me"; Max-Age=0'}, "", "")]
    )
    client = VoyagerClient("test-li-at", transport=transport)
    with pytest.raises(SessionRevokedError):
        await client.fetch_profile("alex-rivera-demo")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_302_location_equals_request_url_revokes() -> None:
    transport = FakeTransport([])

    async def get(url: str, headers: dict) -> VoyagerResponse:
        transport.calls.append((url, dict(headers)))
        return VoyagerResponse(302, {"Location": url}, "", url)

    transport.get = get  # type: ignore[method-assign]
    client = VoyagerClient("test-li-at", transport=transport)
    with pytest.raises(SessionRevokedError):
        await client.fetch_profile("alex-rivera-demo")


@pytest.mark.asyncio
async def test_status_mapping() -> None:
    for status, error in ((403, SessionRejectedError), (429, RateLimitedError), (999, RateLimitedError)):
        transport = FakeTransport([VoyagerResponse(status, {}, "")])
        client = VoyagerClient("test-li-at", transport=transport)
        with pytest.raises(error):
            await client.fetch_profile("alex-rivera-demo")


@pytest.mark.asyncio
async def test_shape_error_retries_second_decoration(sample_payload: dict) -> None:
    transport = FakeTransport(
        [
            VoyagerResponse(200, {}, "not json"),
            _json_response(sample_payload),
        ]
    )
    client = VoyagerClient("test-li-at", transport=transport)
    payload, decoration = await client.fetch_profile("alex-rivera-demo")
    assert payload == sample_payload
    assert decoration == DECORATION_CANDIDATES[1]
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_404_is_not_retried() -> None:
    transport = FakeTransport([VoyagerResponse(404, {}, "")])
    client = VoyagerClient("test-li-at", transport=transport)
    with pytest.raises(ProfileNotFoundError):
        await client.fetch_profile("missing-person")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_shape_error_on_both_decorations() -> None:
    transport = FakeTransport(
        [VoyagerResponse(200, {}, "not json"), VoyagerResponse(200, {}, "not json")]
    )
    client = VoyagerClient("test-li-at", transport=transport)
    with pytest.raises(UpstreamShapeError):
        await client.fetch_profile("alex-rivera-demo")
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_missing_included_is_shape_error() -> None:
    transport = FakeTransport(
        [_json_response({"data": {}}), _json_response({"data": {}})]
    )
    client = VoyagerClient("test-li-at", transport=transport)
    with pytest.raises(UpstreamShapeError):
        await client.fetch_profile("alex-rivera-demo")
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_headers_csrf_cookie_and_no_user_agent(sample_payload: dict) -> None:
    cookie_value = "test-li-at-once"
    transport = FakeTransport([_json_response(sample_payload), _json_response(sample_payload)])
    client = VoyagerClient(cookie_value, transport=transport)
    await client.fetch_profile("alex-rivera-demo")
    other = VoyagerClient(cookie_value, transport=transport)
    await other.fetch_profile("alex-rivera-demo")
    assert len(transport.calls) == 2
    first_csrf = transport.calls[0][1]["csrf-token"]
    second_csrf = transport.calls[1][1]["csrf-token"]
    assert first_csrf == second_csrf
    for _url, headers in transport.calls:
        cookie = headers["cookie"]
        assert cookie.count(f"li_at={cookie_value}") == 1
        assert "user-agent" not in {key.lower() for key in headers}
        jsession = None
        for part in cookie.split(";"):
            if "JSESSIONID=" in part:
                jsession = part.split("=", 1)[1].strip().strip('"')
        assert headers["csrf-token"] == jsession
        assert '"' not in headers["csrf-token"]
