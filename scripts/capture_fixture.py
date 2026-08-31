"""Capture a raw Voyager profile payload for fixture work.

LinkedIn revokes sessions under automated access — often after a single Voyager
call from a datacenter IP. Do not run this script in a loop. A lifted li_at is a
login, not a durable credential.

Writes fixtures/raw_<vanity>.json and refuses to overwrite unless --force is passed.
Never prints the session cookie.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

from app.linkedin.client import CurlTransport, VoyagerClient
from app.linkedin.constants import DECORATION_CANDIDATES
from app.linkedin.normalize import EntityGraph
from app.linkedin.urls import extract_vanity_name

COLLECTION_KEYS = (
    "*profilePositionGroups",
    "*profileEducations",
    "*profileSkills",
    "*profileCertifications",
    "*profileLanguages",
    "*profileProjects",
    "*profileTreasuryMediaProfile",
    "*profileVolunteerExperiences",
    "*profileHonors",
    "*profilePublications",
    "*profilePatents",
    "*profileCourses",
    "*profileOrganizations",
    "*profileTestScores",
    "*profileRingStatusCollection",
    "*profileVideoPreview",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a raw Voyager profile payload.")
    parser.add_argument("--url", default=None, help="LinkedIn profile URL. Defaults to the authenticated user's /me.")
    parser.add_argument("--li-at", default=None, help="Session cookie. Defaults to LINKEDIN_LI_AT.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing raw capture.")
    return parser.parse_args()


async def _resolve_own_vanity(client: VoyagerClient) -> str:
    from app.linkedin.constants import ME_PATH, VOYAGER_BASE

    url = f"{VOYAGER_BASE}{ME_PATH}"
    headers = client._request_headers(referer=None)
    response = await client._transport.get(url, headers)
    payload = response.json()
    for entity in payload.get("included") or []:
        identifier = entity.get("publicIdentifier")
        if isinstance(identifier, str) and identifier:
            return identifier
    raise SystemExit("Could not resolve the authenticated user's publicIdentifier from /me")


async def _run(args: argparse.Namespace) -> None:
    li_at = args.li_at or os.environ.get("LINKEDIN_LI_AT")
    if not li_at:
        raise SystemExit("Provide --li-at or set LINKEDIN_LI_AT")
    transport = CurlTransport(proxy_url=os.environ.get("PROXY_URL"), ca_bundle=os.environ.get("CA_BUNDLE"))
    client = VoyagerClient(li_at, transport=transport)
    if args.url:
        vanity = extract_vanity_name(args.url)
    else:
        vanity = await _resolve_own_vanity(client)
    payload, decoration = await client.fetch_profile(vanity)
    fixtures_dir = Path("fixtures")
    fixtures_dir.mkdir(exist_ok=True)
    output_path = fixtures_dir / f"raw_{vanity}.json"
    if output_path.exists() and not args.force:
        raise SystemExit(f"{output_path} already exists; pass --force to overwrite")
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    graph = EntityGraph(payload)
    profile = graph.root_profile()
    type_counts = Counter(str(entity.get("$type")) for entity in payload.get("included") or [])
    print(f"wrote {output_path}")
    print(f"decoration {decoration} (primary candidate {DECORATION_CANDIDATES[0]})")
    print("$type inventory:")
    for type_name, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:4d}  {type_name}")
    print("collection audit:")
    for star_key in COLLECTION_KEYS:
        returned, total = graph.collection_paging(profile, star_key)
        print(f"  {star_key}: returned={returned} total={total}")


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
