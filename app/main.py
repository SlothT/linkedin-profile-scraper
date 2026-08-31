from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cachetools import TTLCache
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.errors import (
    LinkedInAPIError,
    MissingCredentialsError,
    RateLimitedError,
    SessionRejectedError,
    SessionRevokedError,
    UpstreamShapeError,
    UpstreamUnavailableError,
)
from app.linkedin.client import CurlTransport, Transport, VoyagerClient
from app.linkedin.constants import DECORATION_CANDIDATES
from app.linkedin.mapper import UNVERIFIED_SECTIONS, build_profile_data
from app.linkedin.urls import extract_vanity_name
from app.logging_setup import configure_logging
from app.schemas import ProfileData, ProfileRequest, ProfileResponse, ResponseMeta, TruncationInfo

STALE_TTL = 86_400
_TRANSIENT_UPSTREAM = (
    SessionRevokedError,
    SessionRejectedError,
    RateLimitedError,
    UpstreamUnavailableError,
    UpstreamShapeError,
)

CacheTuple = tuple[ProfileData, dict[str, TruncationInfo], str, str]

fresh_cache: TTLCache = TTLCache(maxsize=256, ttl=get_settings().cache_ttl)
stale_cache: TTLCache = TTLCache(maxsize=256, ttl=STALE_TTL)
flight_locks: dict[str, asyncio.Lock] = {}
upstream_timestamps: deque[float] = deque()

limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger("linkedin-profile-api")
STATIC_DIR = Path(__file__).resolve().parent / "static"

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Invalid profile URL"},
    401: {"description": "Missing credentials or revoked session"},
    403: {"description": "Session rejected"},
    404: {"description": "Profile not found"},
    429: {"description": "Rate limited"},
    502: {"description": "Upstream payload could not be parsed"},
    503: {"description": "LinkedIn unreachable"},
}


def _client_rate_limit() -> str:
    return f"{get_settings().rate_limit_per_minute}/minute"


def get_transport() -> Transport:
    settings = get_settings()
    return CurlTransport(proxy_url=settings.proxy_url, ca_bundle=settings.ca_bundle)


def reset_runtime_state() -> None:
    """Test helper: drop in-process caches, locks, and the upstream ceiling window."""
    fresh_cache.clear()
    stale_cache.clear()
    flight_locks.clear()
    upstream_timestamps.clear()
    limiter._storage.reset()


def _lock_for(vanity_name: str) -> asyncio.Lock:
    lock = flight_locks.get(vanity_name)
    if lock is None:
        lock = asyncio.Lock()
        flight_locks[vanity_name] = lock
    if len(flight_locks) > 1024:
        for key, existing in list(flight_locks.items()):
            if key != vanity_name and not existing.locked():
                del flight_locks[key]
    return lock


def _check_upstream_ceiling() -> None:
    settings = get_settings()
    now = time.monotonic()
    while upstream_timestamps and now - upstream_timestamps[0] > 60.0:
        upstream_timestamps.popleft()
    if len(upstream_timestamps) >= settings.upstream_limit:
        raise RateLimitedError(
            f"local upstream ceiling reached ({settings.upstream_limit} requests/60s); "
            "this request did not reach LinkedIn"
        )
    upstream_timestamps.append(now)


def _require_api_key(request: Request) -> None:
    settings = get_settings()
    if not settings.api_key:
        return
    provided = request.headers.get("x-api-key")
    if provided != settings.api_key:
        raise MissingCredentialsError("Invalid or missing API key")


def _resolve_session(request: Request, body_li_at: str | None) -> str:
    header_cookie = request.headers.get("x-li-at")
    if header_cookie:
        return header_cookie
    if body_li_at:
        return body_li_at
    settings = get_settings()
    if settings.linkedin_li_at:
        return settings.linkedin_li_at
    raise MissingCredentialsError()


def _assemble_response(
    data: ProfileData,
    truncated: dict[str, TruncationInfo],
    decoration_id: str,
    fetched_at: str,
    duration_ms: int,
    source: str,
    stale_reason: str | None = None,
) -> ProfileResponse:
    cached = source in {"cache", "stale"}
    stale = source == "stale"
    return ProfileResponse(
        data=data,
        meta=ResponseMeta(
            fetched_at=fetched_at,
            duration_ms=duration_ms,
            decoration_id=decoration_id,
            source=source,
            cached=cached,
            stale=stale,
            stale_reason=stale_reason if stale else None,
            truncated=truncated,
            unverified_sections=list(UNVERIFIED_SECTIONS),
        ),
    )


async def _lookup_profile(
    request: Request,
    profile_url: str,
    body_li_at: str | None,
    transport: Transport,
) -> ProfileResponse:
    started = time.perf_counter()
    _require_api_key(request)
    vanity_name = extract_vanity_name(profile_url)
    li_at = _resolve_session(request, body_li_at)

    cached_hit = fresh_cache.get(vanity_name)
    if cached_hit is not None:
        data, truncated, decoration_id, fetched_at = cached_hit
        return _assemble_response(
            data,
            truncated,
            decoration_id,
            fetched_at,
            int((time.perf_counter() - started) * 1000),
            "cache",
        )

    lock = _lock_for(vanity_name)
    async with lock:
        cached_hit = fresh_cache.get(vanity_name)
        if cached_hit is not None:
            data, truncated, decoration_id, fetched_at = cached_hit
            return _assemble_response(
                data,
                truncated,
                decoration_id,
                fetched_at,
                int((time.perf_counter() - started) * 1000),
                "cache",
            )
        _check_upstream_ceiling()
        client = VoyagerClient(li_at, transport=transport)
        try:
            payload, decoration_id = await client.fetch_profile(vanity_name)
        except _TRANSIENT_UPSTREAM as exc:
            stale_hit = stale_cache.get(vanity_name)
            if stale_hit is not None:
                data, truncated, decoration_id, fetched_at = stale_hit
                return _assemble_response(
                    data,
                    truncated,
                    decoration_id,
                    fetched_at,
                    int((time.perf_counter() - started) * 1000),
                    "stale",
                    stale_reason=type(exc).__name__,
                )
            raise
        data, truncated = build_profile_data(payload)
        fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        cache_tuple: CacheTuple = (data, truncated, decoration_id, fetched_at)
        fresh_cache[vanity_name] = cache_tuple
        stale_cache[vanity_name] = cache_tuple
        return _assemble_response(
            data,
            truncated,
            decoration_id,
            fetched_at,
            int((time.perf_counter() - started) * 1000),
            "live",
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    secrets = [settings.linkedin_li_at] if settings.linkedin_li_at else []
    configure_logging(secrets)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="LinkedIn Profile API",
        description=(
            "Accepts a LinkedIn profile URL and returns the profile as structured JSON. "
            "Data is fetched from LinkedIn's private Voyager API over HTTP — no browser."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    application.add_exception_handler(LinkedInAPIError, _linkedin_error_handler)
    application.add_exception_handler(Exception, _unhandled_error_handler)
    return application


async def _rate_limit_handler(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    settings = get_settings()
    message = (
        f"per-client rate limit reached ({settings.rate_limit_per_minute} requests/minute); "
        "this request did not reach LinkedIn"
    )
    return JSONResponse(
        status_code=429,
        content={"success": False, "error": {"type": "RateLimitedError", "message": message}},
    )


async def _linkedin_error_handler(_request: Request, exc: LinkedInAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"type": type(exc).__name__, "message": exc.message}},
    )


async def _unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, (StarletteHTTPException, LinkedInAPIError, RateLimitExceeded, RequestValidationError)):
        raise exc
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": {"type": "InternalError", "message": "internal server error"}},
    )


app = create_app()


@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"status": "ok", "server_session_configured": bool(settings.linkedin_li_at)}


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/v1/profile/example", response_model=ProfileResponse)
async def example_profile() -> ProfileResponse | JSONResponse:
    started = time.perf_counter()
    settings = get_settings()
    fixture_path = Path(settings.example_fixture_path)
    if not fixture_path.is_file():
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": {"type": "ProfileNotFoundError", "message": "example fixture not found"}},
        )
    payload = json.loads(fixture_path.read_text())
    data, truncated = build_profile_data(payload)
    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return _assemble_response(
        data,
        truncated,
        DECORATION_CANDIDATES[0],
        fetched_at,
        int((time.perf_counter() - started) * 1000),
        "fixture",
    )


@app.post("/v1/profile", response_model=ProfileResponse, responses=ERROR_RESPONSES)
@limiter.limit(_client_rate_limit)
async def post_profile(
    request: Request,
    body: ProfileRequest,
    transport: Transport = Depends(get_transport),  # noqa: B008
) -> ProfileResponse:
    return await _lookup_profile(request, body.url, body.li_at, transport)


@app.get("/v1/profile", response_model=ProfileResponse, responses=ERROR_RESPONSES)
@limiter.limit(_client_rate_limit)
async def get_profile(
    request: Request,
    url: str,
    transport: Transport = Depends(get_transport),  # noqa: B008
) -> ProfileResponse:
    return await _lookup_profile(request, url, None, transport)
