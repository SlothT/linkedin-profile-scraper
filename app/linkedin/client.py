from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from app.errors import (
    ProfileNotFoundError,
    RateLimitedError,
    SessionRejectedError,
    SessionRevokedError,
    UpstreamShapeError,
    UpstreamUnavailableError,
)
from app.linkedin.constants import (
    DECORATION_CANDIDATES,
    IMPERSONATE_TARGET,
    PROFILE_PATH,
    VOYAGER_BASE,
    build_headers,
)
from app.linkedin.session import csrf_token_for_li_at, normalize_li_at


@dataclass
class VoyagerResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str
    request_url: str = ""

    def json(self) -> dict:
        return json.loads(self.text)

    def header(self, name: str) -> str:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return ""


class Transport(Protocol):
    async def get(self, url: str, headers: Mapping[str, str]) -> VoyagerResponse: ...


class CurlTransport:
    """Real transport. Reuses one Chrome-impersonating AsyncSession for connection reuse."""

    def __init__(self, proxy_url: str | None = None, ca_bundle: str | None = None) -> None:
        self._proxy_url = proxy_url
        self._ca_bundle = ca_bundle
        self._session: AsyncSession | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> AsyncSession:
        if self._session is not None:
            return self._session
        async with self._lock:
            if self._session is None:
                verify: bool | str = self._ca_bundle or True
                self._session = AsyncSession(
                    impersonate=IMPERSONATE_TARGET,
                    verify=verify,
                    proxy=self._proxy_url,
                )
            return self._session

    async def aclose(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None

    async def get(self, url: str, headers: Mapping[str, str]) -> VoyagerResponse:
        try:
            session = await self._ensure_session()
            response = await session.get(url, headers=dict(headers), allow_redirects=False)
        except RequestException as exc:
            await self.aclose()
            raise UpstreamUnavailableError() from exc
        except OSError as exc:
            await self.aclose()
            raise UpstreamUnavailableError() from exc
        header_map = {key: value for key, value in response.headers.items()}
        return VoyagerResponse(
            status_code=response.status_code,
            headers=header_map,
            text=response.text or "",
            request_url=url,
        )


class VoyagerClient:
    def __init__(self, li_at: str, transport: Transport | None = None) -> None:
        self._li_at = normalize_li_at(li_at)
        self._csrf_token = csrf_token_for_li_at(self._li_at)
        self._transport = transport or CurlTransport()

    def _request_headers(self, referer: str | None) -> dict[str, str]:
        headers = build_headers(self._csrf_token, referer)
        headers["cookie"] = f'li_at={self._li_at}; JSESSIONID="{self._csrf_token}"'
        return headers

    def _classify(self, response: VoyagerResponse, request_url: str) -> dict | None:
        status = response.status_code
        if status in (301, 302, 303, 307, 308):
            set_cookie = response.header("set-cookie")
            location = response.header("location")
            if "delete me" in set_cookie.lower() or (location and location == request_url):
                raise SessionRevokedError()
            raise SessionRejectedError()
        if status in (401, 403):
            raise SessionRejectedError()
        if status in (429, 999):
            raise RateLimitedError()
        if status == 404:
            raise ProfileNotFoundError()
        if status == 200:
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise UpstreamShapeError() from exc
            if not isinstance(payload, dict) or "data" not in payload or "included" not in payload:
                raise UpstreamShapeError()
            return payload
        raise UpstreamShapeError()

    async def fetch_profile(self, vanity_name: str) -> tuple[dict, str]:
        last_error: UpstreamShapeError | None = None
        for index, decoration in enumerate(DECORATION_CANDIDATES):
            if index > 0:
                await asyncio.sleep(random.uniform(0.8, 1.6))
            url = (
                f"{VOYAGER_BASE}{PROFILE_PATH}"
                f"?q=memberIdentity&memberIdentity={quote(vanity_name, safe='')}"
                f"&decorationId={quote(decoration, safe='')}"
            )
            referer = f"https://www.linkedin.com/in/{vanity_name}/"
            response = await self._transport.get(url, self._request_headers(referer))
            try:
                payload = self._classify(response, url)
            except UpstreamShapeError as exc:
                last_error = exc
                continue
            if payload is None:
                last_error = UpstreamShapeError()
                continue
            return payload, decoration
        if last_error is not None:
            raise last_error
        raise UpstreamShapeError()
