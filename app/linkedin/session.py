"""Session cookie helpers for Voyager calls."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Optional browser cookies that often travel with li_at on a real LinkedIn tab.
_COMPANION_COOKIE_NAMES: tuple[str, ...] = (
    "li_a",
    "liap",
    "bcookie",
    "bscookie",
    "lidc",
    "UserMatchHistory",
    "AnalyticsSyncHistory",
    "lang",
)


@dataclass(frozen=True)
class SessionMaterial:
    li_at: str
    csrf_token: str
    cookie_header: str


def normalize_li_at(raw: str) -> str:
    """Strip paste noise: whitespace, quotes, and an optional ``li_at=`` prefix."""
    value = (raw or "").strip()
    if not value:
        return ""
    value = value.splitlines()[0].strip()
    if value.lower().startswith("li_at="):
        value = value.split("=", 1)[1].strip()
    return value.strip('"').strip("'")


def csrf_token_for_li_at(li_at: str) -> str:
    """Stable synthetic CSRF for a given cookie when the browser did not supply one."""
    digest = hashlib.sha256(li_at.encode("utf-8")).hexdigest()
    digits = "".join(str(int(ch, 16) % 10) for ch in digest[:19])
    return f"ajax:{digits}"


def _parse_cookie_pairs(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in raw.replace("\n", ";").split(";"):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        name, value = piece.split("=", 1)
        key = name.strip()
        if not key:
            continue
        pairs[key] = value.strip().strip('"').strip("'")
    return pairs


def parse_session_material(raw: str) -> SessionMaterial:
    """Build Voyager cookie + CSRF material from a bare ``li_at`` or a full Cookie header."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty session cookie")

    looks_like_header = "li_at=" in text.lower() or ";" in text or (
        "=" in text and not text.upper().startswith("AQ")
    )
    if looks_like_header:
        pairs = _parse_cookie_pairs(text)
        li_at = normalize_li_at(pairs.get("li_at", ""))
    else:
        pairs = {}
        li_at = normalize_li_at(text)

    if not li_at:
        raise ValueError("li_at missing from session paste")

    browser_jsession = pairs.get("JSESSIONID") or pairs.get("jsessionid") or ""
    browser_jsession = browser_jsession.strip().strip('"')
    if browser_jsession.startswith("ajax:"):
        csrf_token = browser_jsession
    else:
        csrf_token = csrf_token_for_li_at(li_at)

    cookie_parts = [f"li_at={li_at}", f'JSESSIONID="{csrf_token}"']
    for name in _COMPANION_COOKIE_NAMES:
        value = pairs.get(name)
        if value:
            cookie_parts.append(f"{name}={value}")

    return SessionMaterial(
        li_at=li_at,
        csrf_token=csrf_token,
        cookie_header="; ".join(cookie_parts),
    )
