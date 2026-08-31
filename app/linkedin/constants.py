import json

VOYAGER_BASE = "https://www.linkedin.com/voyager/api"
PROFILE_PATH = "/identity/dash/profiles"
ME_PATH = "/me"

DECORATION_CANDIDATES: tuple[str, ...] = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-128",
)

# Prefer a current Chrome TLS profile; bare "chrome" can lag behind LinkedIn's checks.
IMPERSONATE_TARGET = "chrome136"

CLIENT_VERSION = "1.13.36270"  # value that was accepted by Voyager during probing


def build_headers(csrf_token: str, referer: str | None) -> dict[str, str]:
    headers = {
        "csrf-token": csrf_token.strip('"'),
        "x-restli-protocol-version": "2.0.0",
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-li-lang": "en_US",
        "x-li-track": json.dumps(
            {
                "clientVersion": CLIENT_VERSION,
                "mpVersion": CLIENT_VERSION,
                "osName": "web",
                "timezoneOffset": 5.5,
                "deviceFormFactor": "DESKTOP",
                "mpName": "voyager-web",
            }
        ),
        "accept-language": "en-US,en;q=0.9",
    }
    if referer:
        headers["referer"] = referer
    return headers
