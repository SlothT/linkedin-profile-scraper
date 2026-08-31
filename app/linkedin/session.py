"""Session cookie helpers for Voyager calls."""

from __future__ import annotations

import hashlib


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
    """Stable synthetic CSRF for a given cookie.

    A new random JSESSIONID on every request with the same ``li_at`` looks like
    many devices sharing one login. Deriving digits from the cookie keeps the
    double-submit pair consistent for that session without needing a real id.
    """
    digest = hashlib.sha256(li_at.encode("utf-8")).hexdigest()
    digits = "".join(str(int(ch, 16) % 10) for ch in digest[:19])
    return f"ajax:{digits}"
