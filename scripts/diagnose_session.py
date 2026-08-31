"""Check whether a LinkedIn session survives one Voyager /me call from this machine.

Uses one upstream request. Do not loop it.

Examples:
  uv run python scripts/diagnose_session.py --li-at 'AQ…'
  uv run python scripts/diagnose_session.py --cookies 'li_at=AQ…; JSESSIONID="ajax:…"; bcookie=…'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import urllib.request


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose LinkedIn session from this host.")
    parser.add_argument("--li-at", default=None, help="Bare li_at value.")
    parser.add_argument(
        "--cookies",
        default=None,
        help="Full Cookie header paste (preferred locally).",
    )
    parser.add_argument(
        "--proxy-url",
        default=None,
        help="Optional PROXY_URL override (else env PROXY_URL).",
    )
    return parser.parse_args()


def _public_ip() -> str:
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as response:
            return response.read().decode().strip() or "unknown"
    except OSError as exc:
        return f"unavailable ({exc})"


async def _run(args: argparse.Namespace) -> int:
    from app.linkedin.client import CurlTransport, VoyagerClient
    from app.linkedin.session import parse_session_material

    raw = args.cookies or args.li_at or os.environ.get("LINKEDIN_LI_AT")
    if not raw:
        print("Provide --cookies, --li-at, or set LINKEDIN_LI_AT", file=sys.stderr)
        return 2
    try:
        material = parse_session_material(raw)
    except ValueError as exc:
        print(f"invalid session paste: {exc}", file=sys.stderr)
        return 2

    proxy = args.proxy_url or os.environ.get("PROXY_URL")
    print(f"public_ip={_public_ip()}")
    print(f"proxy_configured={bool(proxy)}")
    print(f"li_at_prefix={material.li_at[:6]}… (len={len(material.li_at)})")
    print(f"csrf={material.csrf_token}")
    print(f"cookie_names={[part.split('=', 1)[0] for part in material.cookie_header.split('; ')]}")

    transport = CurlTransport(proxy_url=proxy, ca_bundle=os.environ.get("CA_BUNDLE"))
    client = VoyagerClient(raw, transport=transport)
    try:
        ok = await client.ping_session()
    finally:
        await transport.aclose()

    if ok:
        print("result=OK  /me accepted this session from this host")
        print("Next: look up one real /in/… profile on http://127.0.0.1:8000/")
        return 0

    print("result=FAIL  LinkedIn rejected or revoked the session on /me")
    print("Try: fresh cookies from Chrome on the same network; prefer Windows Python over WSL;")
    print("      paste full Cookie string; avoid the Render URL for live lookups.")
    return 1


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
