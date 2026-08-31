# LinkedIn Profile API

HTTPS API that accepts a LinkedIn person-profile URL and returns the profile as structured JSON. Data is fetched from LinkedIn's private Voyager API over HTTP — **no browser, Playwright, or Selenium**.

**Deployed URL:** `https://linkedin-profile-api-pdos.onrender.com` (Render free tier).

This uses an undocumented private API and contravenes LinkedIn's Terms of Service. Built for a hiring challenge; not for production use.

## Quickstart

### Try it in 10 seconds

`GET /v1/profile/example` needs **no credentials**. It returns anonymised fixture data through the **same mapper** as the live path (`meta.source: "fixture"`).

Render's free tier sleeps after ~15 minutes idle and takes ~50s to wake. The first request may be slow; that is a cold start, not a broken deploy. Use a generous `--max-time`:

```bash
curl --max-time 90 https://linkedin-profile-api-pdos.onrender.com/v1/profile/example
```

Example (truncated):

```json
{
  "success": true,
  "data": {
    "profile": {
      "public_identifier": "alex-rivera-demo",
      "full_name": "Alex Rivera",
      "headline": "Senior Software Engineer at Northwind | Ex-Contoso"
    },
    "experience": [],
    "skills": []
  },
  "meta": {
    "source": "fixture",
    "cached": false,
    "stale": false,
    "unverified_sections": [
      "volunteering", "honors", "publications", "patents",
      "courses", "organizations", "test_scores"
    ]
  }
}
```

### Live lookup

Open `http://127.0.0.1:8000/` after starting the server: paste a profile URL and session cookies, then read the profile on the same page.

```bash
uv sync
cp .env.example .env   # optional LINKEDIN_LI_AT / PROXY_URL
uv run uvicorn app.main:app --reload
```

### Local session troubleshooting (free path)

LinkedIn often kills `li_at` after one Voyager call from automation. If that happens on **both** Render and local:

1. **Do not use the Render URL for live lookups.** Cloud IPs revoke first.
2. Prefer **Windows native Python** over WSL2 for `uvicorn` (same network stack as Chrome).
3. Paste a **full Cookie string** from DevTools (`li_at` + `JSESSIONID` + `bcookie` / `li_a` / `liap`), not only `li_at`.
4. Mint a **fresh** cookie after any revoke — dead cookies stay dead.
5. Diagnose with one `/me` call before a profile lookup:

```bash
uv run python scripts/diagnose_session.py --cookies 'li_at=AQ…; JSESSIONID="ajax:…"; bcookie=…'
```

If diagnose fails from WSL but the browser still works, switch to Windows `uvicorn`. nginx cannot fix this.

```bash
curl --max-time 90 -X POST https://linkedin-profile-api-pdos.onrender.com/v1/profile \
  -H 'Content-Type: application/json' \
  -H 'X-LI-AT: <paste li_at>' \
  -d '{"url":"https://www.linkedin.com/in/<vanity-name>"}'
```

A lifted `li_at` is short-lived under automation (sessions were revoked after roughly ten automated requests). If the live call returns `401 SessionRevokedError`, **the deployment is working and the cookie has expired**. Paste a fresh `li_at` in the Render dashboard (`LINKEDIN_LI_AT`) immediately before a demo — not hours earlier.

## API reference

Interactive docs: `/docs`.

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/v1/profile` | `X-LI-AT` or body `li_at` or server `LINKEDIN_LI_AT`; `X-API-Key` if configured | Live lookup |
| `GET` | `/v1/profile?url=` | `X-LI-AT` or server fallback. **`li_at` is not accepted as a query parameter** | Same as POST |
| `GET` | `/v1/profile/example` | none | Fixture via the real mapper |
| `GET` | `/health` | none | `{"status":"ok","server_session_configured":bool}` — never hits LinkedIn |
| `GET` | `/` | none | Browser UI: paste a profile URL and `li_at`, results render on the same page. OpenAPI remains at `/docs` |

Session precedence: `X-LI-AT` header, then JSON body `li_at` (POST only), then `LINKEDIN_LI_AT`.

### `meta`

| Field | Meaning |
| --- | --- |
| `fetched_at` | When the **upstream** fetch happened (ISO-8601 UTC). On cache/stale hits this stays the original timestamp. |
| `duration_ms` | Time to serve **this** request |
| `source` | `live` \| `cache` \| `stale` \| `fixture` |
| `cached` / `stale` / `stale_reason` | See flag table below |
| `truncated` | Collections where `paging.total` > returned (skills are capped at 20) |
| `unverified_sections` | Seven sections whose field names were not observed on the captured profiles |

`source` pins the other flags:

| `source` | `cached` | `stale` | `stale_reason` |
| --- | --- | --- | --- |
| `live` | `false` | `false` | `null` |
| `cache` | `true` | `false` | `null` |
| `stale` | `true` | `true` | exception class name |
| `fixture` | `false` | `false` | `null` |

A `stale: true` response is a **200 carrying older data**, not a failure. `fetched_at` tells the caller how old it is.

### Errors

| `error.type` | HTTP |
| --- | --- |
| `InvalidProfileURLError` | 400 |
| `MissingCredentialsError` | 401 |
| `SessionRevokedError` | 401 |
| `SessionRejectedError` | 403 |
| `ProfileNotFoundError` | 404 |
| `RateLimitedError` | 429 |
| `UpstreamShapeError` | 502 |
| `UpstreamUnavailableError` | 503 |

Two different 429 bodies, neither of which means LinkedIn blocked you:

- Per-client: `per-client rate limit reached (N requests/minute); this request did not reach LinkedIn`
- Shared cookie ceiling: `local upstream ceiling reached (N requests/60s); this request did not reach LinkedIn`

## Approach: how this was reverse engineered

Voyager (`/voyager/api`) is LinkedIn's private REST API. One decoration — `FullProfileWithEntities-93` — returns Profile, positions, education, skills, certifications, languages, projects, featured media, and related Company/School/Geo entities in a single call. `/identity/profiles/{vanity}/profileView` is dead (HTTP 410). There is no GraphQL `queryId` scraping here because it is unnecessary.

**TLS impersonation, not a browser.** PerimeterX fingerprints the TLS/HTTP2 handshake; plain `requests`/`httpx` are rejected before headers are read. `curl_cffi` with `impersonate="chrome"` reproduces a Chrome handshake. Do not set `User-Agent`; curl_cffi injects a matching one.

**CSRF is a stateless double-submit.** Send cookie `JSESSIONID="ajax:<19 digits>"` and header `csrf-token: ajax:<same digits>` (unquoted). A synthesised value works, so `li_at` is the only real credential.

**Normalized JSON.** The envelope is `{data, included}`. Keys prefixed with `*` are URN references into `included`. Collections are two hops: `Profile["*profileSkills"]` → `CollectionResponse` → `*elements` → `Skill` entities. Image URLs are `rootUrl` concatenated with `fileIdentifyingUrlPathSegment` (no slash insertion — the root ends mid-path by design).

### What two profiles taught us that one could not

Voyager **omits empty keys** instead of emitting `null`. A single sample makes a member's blank field look like an API limitation. Two independently captured profiles were needed to establish that position descriptions **are** returned when written, that `originalImageReference` is owner-only (third-party profiles expose `displayImageReference` only), and that skills `paging.total` varies per member (26 vs 36) while the endpoint always returns 20.

## Architecture and trade-offs

**Synchronous, not a task queue.** The common pattern for scraping APIs is FastAPI plus Celery plus Redis returning `202` and a job id. That is right when completion time is unpredictable; this is one upstream call of one to two seconds, so a queue would add two services for no latency benefit. Global pacing of upstream calls comes from the single-flight lock and `UPSTREAM_LIMIT` instead.

**In-process cache and limiter, no Redis.** Render free web services cannot scale past a single instance, so single-process state is coherent rather than merely convenient. Honest cost: the tier spins down after ~15 minutes and has an ephemeral filesystem, so cache and counters reset on wake. A cold cache is harmless; a reset counter is why the ceiling is set low.

**One request per profile, no decoy traffic.** Established LinkedIn automation tools inject fake feed and notification calls to look organic. That suits tools doing hundreds of writes; here every decoy would spend from the same session budget as a real lookup, and one profile fetch already looks like a human opening one page.

**Two rate limits, not one.** `RATE_LIMIT_PER_MINUTE` (default 30) protects the service per client IP. `UPSTREAM_LIMIT` (default 8) is a process-wide ceiling on Voyager calls and protects the shared cookie. Several well-behaved callers can still exhaust the session if only a per-IP limit exists; a global-only limit would let one abusive client consume the entire budget.

**Single-flight and serve-stale.** Concurrent duplicate requests collapse into one upstream call. A transient upstream failure returns the last good response flagged `stale` rather than a `401` that reads as a broken deploy.

**Why not a browser.** The brief forbids Playwright/Selenium; TLS impersonation is what makes a direct HTTP client viable.

## Known limitations

- Skills are capped at 20 by the endpoint while `paging.total` reports the real count (26 and 36 on the two profiles tested). Surfaced in `meta.truncated` rather than worked around.
- Seven sections — volunteering, honors, publications, patents, courses, organizations and test scores — are returned by the endpoint but were empty on both profiles available for testing, so their field names are inferred rather than observed. They are mapped defensively and listed in `meta.unverified_sections`.
- The service imposes `UPSTREAM_LIMIT` (default 8) Voyager requests per rolling 60 seconds. Exceeding it returns 429 without contacting LinkedIn. Configurable; a 429 is not automatically an upstream block.
- Featured media can be a link or an uploaded document; `media_type` distinguishes them. For uploads the URL is a short-lived signed document URL, so it expires.
- Follower and connection counts are not present in this decoration and are not available from this endpoint.
- Background and profile images come from `displayImageReference`; the uncropped `originalImageReference` is only exposed to the profile's owner.
- Decoration IDs carry version suffixes that rotate. Two candidates are tried (`-93` then `-128`). If both fail with `UpstreamShapeError`, re-capture a current `decorationId` from browser devtools and add it to `DECORATION_CANDIDATES` in `app/linkedin/constants.py`.
- A lifted `li_at` is a login, not a durable session. LinkedIn revoked test sessions after roughly ten automated requests, replying `302` with `li_at="delete me"`. Serve-stale and `/v1/profile/example` keep the API demonstrable across a revocation.
- **The strongest revocation trigger is geographic, not behavioural.** A cookie minted in a browser in one country and replayed from a cloud datacenter in another is "impossible travel". Mitigate by deploying to the Render region nearest where the cookie was minted (`region: singapore` in `render.yaml` for India) and routing egress through a residential proxy in that country via `PROXY_URL`. Datacenter IP reputation compounds it independently of TLS fingerprint. `PROXY_URL` is close to required for a reliable live demo.
- **Free path (no paid proxy):** mint `li_at` in your home browser and run `uvicorn` on the same machine/network so LinkedIn sees your residential IP. nginx (or any reverse proxy in front of this app) does **not** change the egress IP LinkedIn sees. Free public proxy lists and Tor exits are usually already flagged. The hosted Render URL is fine for the UI and `/docs`; expect live Voyager lookups there to revoke quickly without a residential `PROXY_URL`.
- Cache and rate-limiter state are in-process and reset on free-tier spin-down.
- Behind a TLS-inspecting corporate proxy, the impersonated fingerprint never reaches LinkedIn; `CA_BUNDLE` can make local runs work but such an environment cannot validate the approach.
- Only person profiles (`/in/...`); no companies or schools.
- Undocumented private API; not for production use.

## Security notes

Cookies are accepted per request, never logged or persisted. A logging filter redacts configured secrets and any `li_at`-shaped token (`AQ…`). Secrets live in the environment / Render dashboard only.

Both the fresh and stale caches are keyed on the vanity name **alone** and are read **only after** authenticating, so neither can be used to bypass the API key or `MissingCredentialsError`.

The committed fixtures are anonymised, not merely hostname-rewritten: names, `publicIdentifier`s, member urns, media asset ids, artifact path segments, signed URL tokens, and company/school/geo urns are fabricated. Media URLs point at the non-resolving host `media.example.invalid`. Raw captures are gitignored under an allowlist (`fixtures/*` except the two `profile_*_sample.json` files).

## Testing

No credentials or network required:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
