from urllib.parse import unquote, urlparse

from app.errors import InvalidProfileURLError

_LINKEDIN_HOST_SUFFIX = "linkedin.com"


def extract_vanity_name(profile_url: str) -> str:
    """Return the vanity slug from a LinkedIn profile URL.
    Raises InvalidProfileURLError for anything that is not a person profile."""
    if not profile_url or not str(profile_url).strip():
        raise InvalidProfileURLError()

    raw = profile_url.strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    hostname = (parsed.hostname or "").lower()
    if not hostname or not (hostname == _LINKEDIN_HOST_SUFFIX or hostname.endswith(f".{_LINKEDIN_HOST_SUFFIX}")):
        raise InvalidProfileURLError()

    segments = [segment for segment in parsed.path.split("/") if segment]
    if "in" not in segments:
        raise InvalidProfileURLError()
    in_index = segments.index("in")
    if in_index + 1 >= len(segments):
        raise InvalidProfileURLError()
    vanity = unquote(segments[in_index + 1]).strip()
    if not vanity:
        raise InvalidProfileURLError()
    return vanity
