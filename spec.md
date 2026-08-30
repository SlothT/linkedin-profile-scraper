# Implementation Spec — LinkedIn Profile API

> **Audience:** an AI coding agent in a fresh session with no prior context.
> Everything needed is in this file plus the two committed fixtures,
> `fixtures/profile_sample.json` and `fixtures/profile_rich_sample.json`.
> Do not research LinkedIn's API. Do not second-guess the endpoint, auth, CSRF or TLS
> choices below — those were verified against a live session and are recorded in Section 0.2.
>
> **One thing you may not skip:** where 0.2 says a field is present, absent, or
> owner-only, that distinction was established by comparing **two** profiles, and getting
> it wrong is the most likely way to ship something that passes tests and fails on real
> input. Read 0.2's "Absent keys" row and the 0.7 fixture comparison before writing the
> mapper.

---



## 0. Preamble — read fully before writing code



### 0.1 Mission

Build and deploy an HTTPS API that accepts a LinkedIn profile URL and returns the
profile as structured JSON. Data comes from LinkedIn's private "Voyager" API, called
directly over HTTP. **No browser, no Playwright, no Selenium, no JS execution** — this
is a hard requirement of the brief.

### 0.2 Verified ground truth (do not re-derive)

These facts were established by probing a real authenticated session against **two
different profiles**: the account that owns the cookie, and an unrelated third-party
profile. Facts confirmed on both are marked "both". Trust them.

> **Why two profiles matters.** An earlier revision of this spec recorded several
> single-profile observations as API behaviour and got them wrong — a field that one
> member had left blank was written down as "this decoration never returns that field".
> Voyager **omits a key entirely when the member left the field empty**; it does not
> return `null`. Never infer from one profile that a field is unsupported. See the
> "Absent keys" row below — this is the single most important rule in this document.


| Fact                                | Detail                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Base URL                            | `https://www.linkedin.com/voyager/api`                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| The only endpoint needed            | `GET /identity/dash/profiles?q=memberIdentity&memberIdentity={vanity}&decorationId={decoration}`                                                                                                                                                                                                                                                                                                                                                                                            |
| Working decoration                  | `com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93` (both)                                                                                                                                                                                                                                                                                                                                                                                                         |
| Third-party profiles                | The decoration returns full data for **any** profile, not only the cookie owner's. Confirmed on an unrelated profile.                                                                                                                                                                                                                                                                                                                                                                       |
| Second decoration                   | same but `-128`. Accepted during probing; **treated as an unverified fallback only** — do not rely on its output being identical.                                                                                                                                                                                                                                                                                                                                                           |
| Auth                                | Cookie `li_at` only                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| CSRF                                | Stateless double-submit. Send cookie `JSESSIONID="ajax:<19 random digits>"` **and** header `csrf-token: ajax:<same digits>`. A synthesised value works; it need not be a real session id. Strip surrounding `"` from the header value — a quoted header 403s.                                                                                                                                                                                                                               |
| Session check                       | `GET /me` returns 200 with `included[].publicIdentifier` for the logged-in user                                                                                                                                                                                                                                                                                                                                                                                                             |
| TLS                                 | Plain `requests`/`httpx` are rejected by PerimeterX fingerprinting. **Must** use `curl_cffi` with `impersonate="chrome"`.                                                                                                                                                                                                                                                                                                                                                                   |
| User-Agent                          | **Do not set one.** `curl_cffi` injects a matching Chrome UA; overriding breaks fingerprint consistency.                                                                                                                                                                                                                                                                                                                                                                                    |
| Revocation mechanics                | When LinkedIn kills a session it replies `302` with `set-cookie: li_at="delete me"; Max-Age=0` and `Location` equal to the requested URL. Following redirects produces an infinite loop, which is why `allow_redirects=False` is mandatory.                                                                                                                                                                                                                                                 |
| Revocation **triggers**             | Three, in rough order of strength: **impossible travel** (the cookie was minted from one country's residential IP and is then used from a datacenter in another), **datacenter IP reputation**, and uniform request timing. Volume alone is the weakest of the three. This matters for deployment, not code — see 0.10.                                                                                                                                                                     |
| One call is enough                  | The decoration returns, in a single response: Profile, Position, PositionGroup, Education, Skill, Certification, Language, Project, TreasuryMedia (the "Featured" section), Company, School, Geo, Industry, EmploymentType, StandardizedDegree.                                                                                                                                                                                                                                             |
| **Absent keys**                     | **Voyager omits any key whose value the member left empty, rather than emitting** `null`**.** Proven by diffing `Position` entities across the two profiles: profile A has `*employmentType` and no `description`; profile B has `description` and no `*employmentType`. Same decoration, same entity type. Therefore: use `.get()` everywhere, and never conclude from a missing key that the decoration does not support that field.                                                      |
| Position descriptions               | **Returned** when the member wrote one (present on all three positions in `profile_rich_sample.json`, at 329, 430 and 667 characters). Absent when they did not.                                                                                                                                                                                                                                                                                                                            |
| Skills truncate                     | Always 20 returned; `paging.total` varies by profile (26 and 36 observed). Detect and report via `meta.truncated`; do not attempt to fetch the remainder.                                                                                                                                                                                                                                                                                                                                   |
| Image references                    | `profilePicture` / `backgroundPicture` expose `displayImageReference` on **both** profiles, but `originalImageReference` **only on the cookie owner's own profile** — LinkedIn appears to withhold the uncropped original from third parties. **Always prefer** `displayImageReference`**.** Reading only `originalImageReference` yields empty images for every third-party profile, which is the entire use case.                                                                         |
| Collections on Profile              | The root `Profile` carries **17** `*`-prefixed references, not 5 — 16 collections plus `*industry`, which is a single URN rather than a collection. All are returned; most collections are simply empty (`paging.total: 0`) for any given member. Full list in 0.8.                                                                                                                                                                                                                         |
| Featured media is not always a link | `TreasuryMedia.data` is a **union**, and only one arm carries a URL. `profile_rich_sample.json` has `{"Url": ...}` on both entries (external links, with `providerName`). `profile_sample.json`'s single entry is `{"NativeDocument": {...}}` — an uploaded PDF, with **no** `Url` **and no** `providerName`, but with `transcribedDocumentUrl` and `manifestUrl` inside. A mapper that reads only `data["Url"]` returns a title and nothing else for every uploaded document. See Step 10. |
| Dangling entities in `included`     | `included` may carry entities that no collection references. `profile_sample.json` contains **two** `TreasuryMedia` records while the profile collection has one and the education collection has none. Therefore `entities_of_type` is **not** a safe substitute for `follow` on any collection — it over-counts.                                                                                                                                                                          |
| No follower/connection counts       | Verified absent from this decoration on both profiles. Not obtainable here; state as a limitation rather than attempting another endpoint.                                                                                                                                                                                                                                                                                                                                                  |
| Stub entities                       | Some referenced entities resolve to a record containing **only** `entityUrn` — observed for `Geo` and `StandardizedDegree`. Resolution must tolerate a resolved entity having no usable fields.                                                                                                                                                                                                                                                                                             |


**Explicitly out of scope — do not build these.** They were investigated and rejected:

- `/identity/profiles/{vanity}/profileView` — returns HTTP 410, endpoint is dead.
- Voyager GraphQL (`/graphql`, `queryId=voyagerIdentityDashProfileCards.*`) — unnecessary, since the single REST call above returns everything. No `queryId` resolution logic anywhere.
- Scraping `queryId` hashes out of page HTML — verified to yield zero matches.



### 0.3 Response envelope format

Voyager returns "normalized JSON": `{"data": {...}, "included": [...]}`.

- `included` is a flat array of entities, each with `entityUrn` and `$type`.
- Keys prefixed with `*` are **references**: either a single URN string or a list of URN strings, resolvable against `included` by `entityUrn`.
- Collections are indirect: `Profile["*profileSkills"]` → a `CollectionResponse` entity → its `["*elements"]` list → the actual `Skill` entities. **Two hops.**
- `CollectionResponse.paging.total` vs `len(*elements)` reveals truncation.
- `data["*elements"][0]` is the root `Profile` URN.
- `$type` and `$recipeTypes` values are schema identifiers (e.g. `com.linkedin.common.Date`). Dispatch on `$type`; never mutate these strings.
- A reference may resolve to a **stub** carrying only `entityUrn` (seen for `Geo`, `StandardizedDegree`). Treat a resolved-but-empty entity the same as unresolved.
- Image references come in **two shapes**. Most are `{"vectorImage": {"rootUrl", "artifacts"}}`. Featured media instead nests one level deeper: `previewImage["attributes"][0]["detailDataUnion"]["vectorImage"]`. One helper must handle both (Step 8).



### 0.4 Stack and dependencies

Python 3.13, FastAPI, managed with `uv`. Exact runtime dependencies:

```
fastapi
uvicorn[standard]
curl_cffi
pydantic
pydantic-settings
cachetools
slowapi
```

Dev dependencies: `pytest`, `pytest-asyncio`, `httpx` (for FastAPI's `TestClient` only — never for calling LinkedIn), `ruff`.

Install with `uv add <pkg>`; never hand-write pinned versions.

### 0.5 Global constraints (apply in every file)

- **Never log, echo, persist, or include a cookie value in any response, error message, or exception string.** Section 3 Step 5 adds a redaction filter; do not defeat it.
- Variable names must be descriptive, never single letters. `for entity in included`, not `for e in included`.
- Every field of every **profile data** model (`ProfileCore` through `TestScore`) is `Optional` with a default. A sparse profile must yield `null`s, never a 500. `ResponseMeta` is the deliberate exception: its fields are server-generated, so a missing one is a bug rather than sparse input, and they stay required.
- All Voyager I/O is `async`. `curl_cffi.requests.AsyncSession`, awaited. Never call the sync `Session` from an `async def` — it blocks the event loop.
- `allow_redirects=False` on every Voyager request, always.
- No bare `except:`. Catch specific exceptions and re-raise as the taxonomy in 0.6.
- Type-hint every function signature.
- No comment should restate what the code does. Comment only non-obvious constraints (e.g. why the CSRF header is synthesised).



### 0.6 Error taxonomy

Define in `app/errors.py`. All inherit `LinkedInAPIError(Exception)` which carries
`message: str` and `status_code: int`.


| Exception                  | HTTP | Raised when                                                                                      |
| -------------------------- | ---- | ------------------------------------------------------------------------------------------------ |
| `InvalidProfileURLError`   | 400  | URL is not a `/in/{vanity}` LinkedIn profile URL                                                 |
| `MissingCredentialsError`  | 401  | No caller `li_at` and no server fallback configured                                              |
| `SessionRevokedError`      | 401  | Response is a redirect with `li_at="delete me"`, or `Location` == request URL                    |
| `SessionRejectedError`     | 403  | Voyager returns 401 or 403                                                                       |
| `ProfileNotFoundError`     | 404  | Voyager 404, or a 200 whose `included` has no `Profile` entity                                   |
| `RateLimitedError`         | 429  | Voyager returns 429 or 999                                                                       |
| `UpstreamShapeError`       | 502  | 200 received but the payload cannot be parsed (all decorations exhausted, missing envelope keys) |
| `UpstreamUnavailableError` | 503  | Network/TLS failure reaching LinkedIn                                                            |


A single FastAPI exception handler maps `LinkedInAPIError` →
`JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"type": type(exc).__name__, "message": exc.message}})`.

### 0.7 Test infrastructure

- Framework: `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`).
- **No test may make a network call.** There is no mocking library that can intercept `curl_cffi`; instead `VoyagerClient` takes an injectable transport (Step 11), and tests pass a fake.
- **There are two committed fixtures, and both must be used.** `tests/conftest.py` loads each and exposes them as `sample_payload` and `rich_payload`. They were captured from two different real profiles and anonymised.

Using only one is how the earlier errors in this spec were introduced. The two are
deliberately complementary:


|                                  | `profile_sample.json` (`sample_payload`)                                | `profile_rich_sample.json` (`rich_payload`)                                                                                 |
| -------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Captured from                    | the cookie owner's own profile                                          | an unrelated third-party profile                                                                                            |
| name / `publicIdentifier`        | Alex Rivera / `alex-rivera-demo`                                        | Taylor Quinn / `taylor-quinn-demo`                                                                                          |
| headline                         | `Senior Software Engineer at Northwind | Ex-Contoso`                    | `Software Engineer | Backend & AI/ML Systems | Ex-Meridian, Ex-Foodline` (note the **double space** — preserved on purpose) |
| location                         | `Springfield, Example State, Exampleland`, code `IN`                    | country `Exampleland`, code `IN`                                                                                            |
| industry                         | `Information Technology & Services`                                     | `Computer Software`                                                                                                         |
| positions                        | 5 across 3 groups (Northwind ×3, Contoso ×1, Fabrikam ×1)               | 3 across 3 groups                                                                                                           |
| position `description`           | **absent on all 5**                                                     | **present on all 3**                                                                                                        |
| position `*employmentType`       | present                                                                 | **present on only 2 of 3**                                                                                                  |
| educations                       | 1, grade `8.09`                                                         | 1, grade `CGPA: 8.4 / 10` (free text, not numeric)                                                                          |
| skills                           | 20 of `paging.total` 26                                                 | 20 of `paging.total` 36                                                                                                     |
| certifications                   | 7                                                                       | 4                                                                                                                           |
| languages                        | 2                                                                       | 3                                                                                                                           |
| projects                         | 0                                                                       | **2**                                                                                                                       |
| featured media (`TreasuryMedia`) | 1                                                                       | **2**                                                                                                                       |
| featured media `data` shape      | `NativeDocument` — an uploaded PDF, **no** `Url`**, no** `providerName` | `Url` on both — external links, both with `providerName`                                                                    |
| `profilePicture` keys            | `originalImageReference` **and** `displayImageReference`                | `displayImageReference` **only**                                                                                            |
| `backgroundPicture` keys         | both                                                                    | `displayImageReference` **only**                                                                                            |


**What each fixture exists to catch.** `sample_payload` is the only one with
`originalImageReference`, so a mapper that reads only that key passes on it and silently
fails on every real third-party profile — `rich_payload` is what catches that.
`rich_payload` is the only one with position descriptions, projects and a
`*employmentType` that is absent on some positions, so it is what catches both the
absent-key rule and the dropped sections. `sample_payload` is also the only one whose
featured media is an uploaded document rather than a link, so it is what catches a
`data["Url"]`-only mapper.

**Fixture hygiene — both files are scrubbed, and they must stay that way.** Every media
asset id, artifact path segment, signed `t=` token, expiry, `collectionResponse` urn and
identifying `fsd_company` / `fsd_school` / `fsd_geo` urn is fabricated, and all media URLs
use the non-resolving host `media.example.invalid`. Global taxonomy urns
(`fsd_industry`, `fsd_employmentType`, `fsd_degree`) are real, because they identify
nothing about a member. Do **not** assert on any of these fabricated values in a test:
assert on structure and counts, so a future re-scrub does not break the suite. The two
files are the only committable things under `fixtures/`; see Step 13 and Section 3.

### 0.8 Every collection on the root Profile

All 17 are returned by the decoration. "A" / "B" are element counts in
`profile_sample.json` and `profile_rich_sample.json` respectively. A count of 0 means
**those two members have nothing in that section**, never that the field is unsupported.


| Reference key                  | A   | B   | Mapped to                                                                            |
| ------------------------------ | --- | --- | ------------------------------------------------------------------------------------ |
| `*profilePositionGroups`       | 3   | 3   | `experience` (via each group's `*profilePositionInPositionGroup`)                    |
| `*profileEducations`           | 1   | 1   | `education`                                                                          |
| `*profileSkills`               | 20  | 20  | `skills`                                                                             |
| `*profileCertifications`       | 7   | 4   | `certifications`                                                                     |
| `*profileLanguages`            | 2   | 3   | `languages`                                                                          |
| `*profileProjects`             | 0   | 2   | `projects`                                                                           |
| `*profileTreasuryMediaProfile` | 1   | 2   | `featured_media`                                                                     |
| `*profileVolunteerExperiences` | 0   | 0   | `volunteering` — **field names unverified**                                          |
| `*profileHonors`               | 0   | 0   | `honors` — **field names unverified**                                                |
| `*profilePublications`         | 0   | 0   | `publications` — **field names unverified**                                          |
| `*profilePatents`              | 0   | 0   | `patents` — **field names unverified**                                               |
| `*profileCourses`              | 0   | 0   | `courses` — **field names unverified**                                               |
| `*profileOrganizations`        | 0   | 0   | `organizations` — **field names unverified**                                         |
| `*profileTestScores`           | 0   | 0   | `test_scores` — **field names unverified**                                           |
| `*profileRingStatusCollection` | 0   | 0   | not mapped (open-to-work / hiring badge)                                             |
| `*profileVideoPreview`         | 0   | 0   | not mapped (profile video)                                                           |
| `*industry`                    | —   | —   | `profile.industry`. **Not a collection** — a single URN, use `resolve` not `follow`. |


**The seven "unverified" sections.** They are volunteering, honors, publications,
patents, courses, organizations and test scores — **seven, not eight**; count the rows
marked "field names unverified" above if in doubt, and use seven everywhere in code,
tests and the README. Both captured profiles have these empty, so their
entity field names could not be observed. They are mapped in Step 10 using a
**candidate-key** helper that tries several plausible names and falls back to `None`,
and each is listed in `meta.unverified_sections` in the response. Do **not** silently
present guessed field names as verified, and do not delete these sections either — a
profile that has them would otherwise lose the data entirely.

### 0.9 Architecture decisions, and why

Each of these is a deliberate choice with a cheaper-looking alternative. Implement them as
described, and reproduce the reasoning in the README — a reviewer can tell the difference
between a considered trade-off and an unconsidered default.

**Synchronous request/response, not a job queue.** The common pattern for scraping APIs is
FastAPI plus Celery plus Redis, returning `202` and a job id to poll. That is right when
completion time is unpredictable; ours is a single upstream call of one to two seconds.
A queue would add two services to a free-tier deploy for no latency benefit, and the brief
asks for a URL in and JSON out. The one real advantage a queue would bring — global
serialisation and pacing of upstream calls — is obtained far more cheaply by the
single-flight lock and global ceiling below.

**In-process cache and rate limiter, with no external store.** Render free web services
**cannot scale beyond a single instance**, so there is exactly one process holding this
state and it is therefore coherent, not merely convenient. Do not add Redis. Two honest
consequences to document rather than hide: the free tier spins down after 15 minutes idle
and may restart at any time, and its filesystem is ephemeral with no persistent disks
available — so both the cache and the limiter counter reset on every wake. A cold cache is
harmless. A reset **limiter** is a real if minor safety regression, since that counter
exists to protect the cookie; the ceiling is therefore set conservatively low. Persisting
it is not possible on this tier, and an external store is the fix only if this were ever
run for real.

**One upstream request per profile, and no decoy traffic.** Established automation tools
inject fake feed and notification requests to make traffic look organic. That is correct
for tools performing hundreds of writes; it is wrong here, because every decoy spends from
the same session budget as a real lookup, and a single profile fetch already resembles a
human opening one page. Deliberately diverging from common practice — say so, with the
reason.

**Single-flight, because upstream requests are the scarce resource.** Sessions were revoked
after roughly ten requests, so concurrent duplicate work is a correctness problem rather
than a performance one (Step 12).

**Serve-stale on upstream failure.** Sessions die unpredictably. Returning the last good
response with an explicit `meta.stale` flag beats a hard `401` that a reviewer will read as
a broken deployment (Step 12).

### 0.10 Deployment posture (this decides whether the demo works)

The dominant failure mode is not the code — it is **where the request comes from**. A
`li_at` minted in a browser in one country and then replayed from a cloud datacenter in
another is the exact pattern LinkedIn's detection is tuned for, and it is the most likely
reason a working local build returns `SessionRevokedError` the moment it is deployed.

Two mitigations, in order of cost:

1. **Set the Render region to the one geographically closest to where the cookie was
  minted.** Render offers Singapore, Frankfurt, Ohio, Oregon and Virginia; the default is
   Oregon. For a cookie created in India, Singapore is dramatically closer than any US
   region. This is free and must be set explicitly in `render.yaml` (Step 14).
2. **Route egress through a residential proxy in the cookie's origin country** via
  `PROXY_URL`. This is the actual fix, not a nice-to-have. Treat a live demo without it as
   likely to fail on the first request.



### 0.11 Commands

```bash
uv sync                                  # install
uv run pytest -q                         # all tests
uv run pytest tests/test_mapper.py -q    # one file
uv run ruff check .                      # lint
uv run uvicorn app.main:app --reload     # dev server
```

`uv run pytest -q` passing with zero failures is the gate after every step that adds tests.

---



## 1. Target file tree

Create exactly this. Do not add modules not listed here.

```
linkedin-scraper/
├── README.md
├── SPEC.md                      # this file (already exists)
├── pyproject.toml
├── uv.lock                      # generated by `uv add`/`uv sync`; MUST be committed
├── Dockerfile
├── .dockerignore
├── render.yaml
├── .env.example
├── .gitignore                   # already exists
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, routes, handlers
│   ├── config.py                # Settings
│   ├── errors.py                # exception hierarchy
│   ├── logging_setup.py         # cookie redaction
│   ├── schemas.py               # Pydantic response models
│   └── linkedin/
│       ├── __init__.py
│       ├── constants.py
│       ├── urls.py              # URL → vanity
│       ├── normalize.py         # EntityGraph
│       ├── images.py            # VectorImage → variants
│       ├── client.py            # VoyagerClient
│       └── mapper.py            # payload → schemas
├── scripts/
│   └── capture_fixture.py
├── fixtures/                    # all already exist; do not regenerate
│   ├── profile_sample.json      # committed, anonymised (own profile)
│   ├── profile_rich_sample.json # committed, anonymised (third-party profile)
│   └── raw_*.json               # real captures, gitignored — never commit, never edit
└── tests/
    ├── __init__.py              # empty
    ├── conftest.py
    ├── test_urls.py
    ├── test_normalize.py
    ├── test_images.py
    ├── test_mapper.py
    ├── test_client.py
    └── test_api.py
```

`.gitignore` uses an **allowlist** for `fixtures/`: everything there is ignored except the
two `profile_*_sample`-style files named above. Do not weaken this to a denylist, and do
not add a new file to `fixtures/` expecting it to be committed.

---



## 2. Implementation steps

Execute in order. Run the verification gate at the end of each step before starting the next.

---



### Step 1 — Project scaffold

**Action:** Create
**Files:** `pyproject.toml`, `app/__init__.py`, `app/linkedin/__init__.py`, `tests/__init__.py` (empty), `.env.example`

`pyproject.toml`: project name `linkedin-profile-api`, `requires-python = ">=3.13"`, dependencies from 0.4 added via `uv add`. Include:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 110
```

`.env.example` — documents every variable, with no real values:

```
# Optional server-side fallback session. Callers may instead send X-LI-AT per request.
LINKEDIN_LI_AT=
# Optional. If set, callers must send a matching X-API-Key header.
API_KEY=
# Optional outbound proxy, e.g. http://user:pass@host:port
PROXY_URL=
# Optional custom CA bundle. Needed only behind a TLS-inspecting corporate proxy.
CA_BUNDLE=
# Seconds to cache a successful profile response. Default 900.
CACHE_TTL=900
# Max Voyager requests this process will make per rolling 60s, across all callers.
# Protects the shared cookie. Default 8. Raise only if you have a session to spare.
UPSTREAM_LIMIT=8
# Per-client-IP request limit per minute on /v1/profile. Protects the service. Default 30.
RATE_LIMIT_PER_MINUTE=30
# Fixture served by GET /v1/profile/example. Default fixtures/profile_sample.json.
EXAMPLE_FIXTURE_PATH=fixtures/profile_sample.json
```

**Verify:** `uv sync` succeeds; `uv run python -c "import app"` exits 0.
**Acceptance proof:** `uv run pytest -q` runs and reports "no tests ran" rather than an import error.
**Must NOT:** commit a populated `.env`. Do **not** gitignore `uv.lock` — Step 14 builds
with `uv sync --frozen`, which fails without it, and the failure surfaces only at deploy time.

---



### Step 2 — Configuration

**Action:** Create
**File:** `app/config.py`

```python
class Settings(BaseSettings):
    linkedin_li_at: str | None = None
    api_key: str | None = None
    proxy_url: str | None = None
    ca_bundle: str | None = None
    cache_ttl: int = 900
    upstream_limit: int = 8
    rate_limit_per_minute: int = 30
    example_fixture_path: str = "fixtures/profile_sample.json"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings: ...
```

**Domain invariant:** `linkedin_li_at` is a secret. Never include it in `__repr__`, logs, or `/health` output — expose only the boolean `bool(settings.linkedin_li_at)`.

**Verify:** `uv run python -c "from app.config import get_settings; print(get_settings().cache_ttl)"` prints `900`.

---



### Step 3 — Error taxonomy

**Action:** Create
**File:** `app/errors.py`

Implement exactly the table in 0.6. Base class:

```python
class LinkedInAPIError(Exception):
    status_code: int = 500
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
```

Each subclass sets `status_code` as a class attribute and provides a sensible default message.

**Verify:** `uv run python -c "from app.errors import SessionRevokedError as E; print(E('x').status_code)"` prints `401`.
**Must NOT:** include any cookie or credential value in a default message.

---



### Step 4 — URL parsing

**Action:** Create
**Files:** `app/linkedin/urls.py`, `tests/test_urls.py`

```python
def extract_vanity_name(profile_url: str) -> str:
    """Return the vanity slug from a LinkedIn profile URL.
    Raises InvalidProfileURLError for anything that is not a person profile."""
```

Must accept: `https://www.linkedin.com/in/alex-rivera-demo`, with or without a
trailing slash, with a query string or fragment, `http://`, no scheme
(`linkedin.com/in/foo`), locale subdomains (`in.linkedin.com`, `uk.linkedin.com`),
uppercase host, extra path segments after the vanity (`/in/foo/detail/skills`), and
percent-encoded non-ASCII slugs (return them decoded).

Must reject with `InvalidProfileURLError`: `/company/...`, `/school/...`, `/pub/...`,
`/feed/...`, a bare vanity with no `/in/` segment, empty string, non-LinkedIn hosts,
and a `/in/` with an empty slug.

Write `tests/test_urls.py` covering every accept case and every reject case above,
one assertion each.

**Verify:** `uv run pytest tests/test_urls.py -q` — all pass.
**Must NOT:** use a single catch-all regex that silently accepts company URLs.

---



### Step 5 — Cookie-safe logging

**Action:** Create
**File:** `app/logging_setup.py`

```python
def configure_logging(secrets: Iterable[str]) -> None:
    """Install a logging filter that replaces any occurrence of each secret with '[REDACTED]'."""
```

The filter must scrub `record.msg` and every element of `record.args`. Call it from
`app/main.py` startup with the configured `li_at` (when set). Also redact any string
matching `r'AQ[A-Za-z0-9_\-]{20,}'`, which is the `li_at` shape, so caller-supplied
cookies are covered too.

**Verify:** add to `tests/test_api.py` later; for now
`uv run python -c "..."` demonstrating a logged secret comes out as `[REDACTED]`.
**Must NOT:** rely solely on the exact-match list — the regex arm is what protects
per-request caller cookies.

---



### Step 6 — Constants

**Action:** Create
**File:** `app/linkedin/constants.py`

```python
VOYAGER_BASE = "https://www.linkedin.com/voyager/api"
PROFILE_PATH = "/identity/dash/profiles"
ME_PATH = "/me"

DECORATION_CANDIDATES: tuple[str, ...] = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-128",
)

IMPERSONATE_TARGET = "chrome"

CLIENT_VERSION = "1.13.36270"   # value that was accepted by Voyager during probing
```

Also a `build_headers(csrf_token: str, referer: str | None) -> dict[str, str]` helper
returning exactly:

- `csrf-token`: the token, unquoted
- `x-restli-protocol-version`: `2.0.0`
- `accept`: `application/vnd.linkedin.normalized+json+2.1`
- `x-li-lang`: `en_US`
- `x-li-track`: `json.dumps({"clientVersion": CLIENT_VERSION, "mpVersion": CLIENT_VERSION, "osName": "web", "timezoneOffset": 5.5, "deviceFormFactor": "DESKTOP", "mpName": "voyager-web"})` — use `5.5`, which is the exact payload Voyager accepted during probing. Do not "tidy" it to `0`; no other value has been tested.
- `accept-language`: `en-US,en;q=0.9`
- `referer` only when provided

**Must NOT:** add a `user-agent` key (see 0.2).

---



### Step 7 — Normalized-JSON resolver

**Action:** Create
**Files:** `app/linkedin/normalize.py`, `tests/test_normalize.py`

```python
class EntityGraph:
    """Index of a Voyager normalized-JSON payload."""
    def __init__(self, payload: dict) -> None: ...          # builds {entityUrn: entity}
    def resolve(self, urn: str | None) -> dict | None: ...   # single URN → entity
    def root_profile(self) -> dict: ...                      # via data["*elements"][0]; raises ProfileNotFoundError
    def follow(self, owner: dict, star_key: str) -> list[dict]: ...
    def collection_paging(self, owner: dict, star_key: str) -> tuple[int, int | None]: ...
    def entities_of_type(self, type_suffix: str) -> list[dict]: ...
```

`follow` implements the **two-hop** traversal: read `owner[star_key]`; if absent or
unresolvable return `[]`; resolve it to a `CollectionResponse`; return its
`["*elements"]` resolved in order, skipping any that don't resolve. If
`owner[star_key]` happens to be a list of URNs rather than a collection reference,
resolve those directly.

`collection_paging` returns `(returned_count, paging_total)` for truncation reporting.

`root_profile` must raise `ProfileNotFoundError` when `data["*elements"]` is missing/empty
or the referenced entity is not a `profile.Profile`.

`tests/test_normalize.py` against `sample_payload`, asserting:

- `root_profile()["publicIdentifier"] == "alex-rivera-demo"`
- `follow(profile, "*profileSkills")` returns 20 entities
- `collection_paging(profile, "*profileSkills") == (20, 26)`
- `follow(profile, "*profileEducations")` returns 1
- `follow(profile, "*profilePositionGroups")` returns 3
- following each position group's `*profilePositionInPositionGroup` yields 5 positions in total
- `resolve(None)` returns `None`; `resolve("urn:li:nonexistent:1")` returns `None`
- `follow(profile, "*noSuchKey")` returns `[]`
- `entities_of_type("profile.Position")` returns 5
- `root_profile()` on `{"data": {}, "included": []}` raises `ProfileNotFoundError`

And against `rich_payload`:

- `root_profile()["publicIdentifier"] == "taylor-quinn-demo"`
- `collection_paging(profile, "*profileSkills") == (20, 36)` — proves `total` is per-profile
- `follow(profile, "*profileProjects")` returns 2 and `follow(profile, "*profileTreasuryMediaProfile")` returns 2
- each of the seven unverified collections returns `[]` and reports `collection_paging(...) == (0, 0)`
- `resolve` on the education's `*degree` returns a **stub** entity whose only non-`$` key is `entityUrn` — the caller must tolerate this without raising

**Verify:** `uv run pytest tests/test_normalize.py -q` — all pass.
**Must NOT:** mutate the input payload; `EntityGraph` is read-only.

---



### Step 8 — Image URL assembly

**Action:** Create
**Files:** `app/linkedin/images.py`, `tests/test_images.py`

```python
def image_variants(image_reference: dict | None) -> list[ImageVariant]:
    """Expand a Voyager image reference into concrete URLs, largest first."""

def picture_variants(picture_node: dict | None) -> list[ImageVariant]:
    """Expand a profilePicture / backgroundPicture node, preferring the display reference."""
```

`image_variants` must locate the `vectorImage` under **either** supported shape (see 0.3):

1. `image_reference["vectorImage"]` — the common case.
2. `image_reference["attributes"][0]["detailDataUnion"]["vectorImage"]` — featured media
  `previewImage`. Scan `attributes` for the first entry that yields a `vectorImage`.

Then read `rootUrl` and `artifacts`, and for each artifact produce `{"width", "height", "url"}`
where `url = rootUrl + artifact["fileIdentifyingUrlPathSegment"]` — plain string
concatenation, no path joining, no slash insertion. Sort descending by `width`.
Return `[]` for `None`, a missing `vectorImage` under both shapes, or empty `artifacts`.

`picture_variants` takes the **whole** `profilePicture` / `backgroundPicture` node and tries
`displayImageReference` **first**, then `originalImageReference`, returning the first that
yields a non-empty list.

> **Why the order matters — do not reverse it.** `originalImageReference` is present only
> on the cookie owner's own profile; third-party profiles carry `displayImageReference`
> alone (0.2). A mapper that reads `originalImageReference` first returns empty images for
> every real lookup, while still passing tests against `sample_payload`, which happens to
> have both. `rich_payload` has only the display reference and is the guard against this.

Add a convenience `def pick_image(image_reference: dict | None) -> str | None` returning
the largest variant's URL or `None`.

`tests/test_images.py` must assert, against **both** fixtures:

- `sample_payload`: profile picture yields 4 variants sorted `[800, 400, 200, 100]`; each URL starts with the `rootUrl`; background image yields 2; a company logo yields 3.
- `rich_payload`: `picture_variants(profile["profilePicture"])` is non-empty **and** `picture_variants(profile["backgroundPicture"])` is non-empty, even though `originalImageReference` is absent from both. This test fails if the preference order is reversed.
- `rich_payload`: a `TreasuryMedia` entity's `previewImage` yields a non-empty list via the `attributes` / `detailDataUnion` shape.
- `image_variants(None) == []`; `image_variants({"vectorImage": {"rootUrl": "x", "artifacts": []}}) == []`; `image_variants({"attributes": []}) == []`.

**Verify:** `uv run pytest tests/test_images.py -q` — all pass.
**Must NOT:** use `urljoin` or insert a `/` — the root URL ends mid-path by design
(e.g. `.../profile-displayphoto-` + `scale_200_200/...`). Do not read
`originalImageReference` before `displayImageReference`.

---



### Step 9 — Response schemas

**Action:** Create
**File:** `app/schemas.py`

Pydantic v2 models. Every field `Optional` with a default of `None` or `[]`.
Use `snake_case` field names.

```python
class ImageVariant(BaseModel):
    width: int | None = None
    height: int | None = None
    url: str | None = None

class DatePart(BaseModel):
    month: int | None = None
    year: int | None = None

class DateRange(BaseModel):
    start: DatePart | None = None
    end: DatePart | None = None
    is_current: bool = False

class Location(BaseModel):
    full: str | None = None            # Geo.defaultLocalizedName
    city_region: str | None = None     # Geo.defaultLocalizedNameWithoutCountryName
    country: str | None = None         # country Geo's defaultLocalizedName
    country_code: str | None = None    # Profile.location.countryCode

class ProfileCore(BaseModel):
    public_identifier: str | None = None
    profile_urn: str | None = None
    member_urn: str | None = None       # Profile.objectUrn
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None        # computed, space-joined, stripped
    headline: str | None = None
    about: str | None = None            # Profile.summary
    location: Location | None = None
    industry: str | None = None
    is_premium: bool | None = None
    is_influencer: bool | None = None
    is_creator: bool | None = None
    profile_picture: list[ImageVariant] = []
    background_image: list[ImageVariant] = []

class Experience(BaseModel):
    title: str | None = None
    company_name: str | None = None
    company_urn: str | None = None
    company_url: str | None = None
    company_logo: list[ImageVariant] = []
    employment_type: str | None = None  # absent on some positions; see 0.2 "Absent keys"
    location: str | None = None
    description: str | None = None      # returned when the member wrote one; see 0.2
    date_range: DateRange | None = None

class Education(BaseModel):
    school_name: str | None = None
    school_url: str | None = None
    school_logo: list[ImageVariant] = []
    degree: str | None = None
    field_of_study: str | None = None
    grade: str | None = None
    activities: str | None = None
    description: str | None = None
    date_range: DateRange | None = None

class Certification(BaseModel):
    name: str | None = None
    authority: str | None = None
    license_number: str | None = None
    url: str | None = None
    display_source: str | None = None
    issued_on: DatePart | None = None

class Language(BaseModel):
    name: str | None = None
    proficiency: str | None = None

# --- verified against rich_payload ---

class Project(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    date_range: DateRange | None = None   # observed null even when the project exists

class FeaturedMedia(BaseModel):
    """The profile's "Featured" section. Voyager calls these TreasuryMedia."""
    title: str | None = None
    description: str | None = None
    media_type: str | None = None         # "link" | "document" | "image" | "video" | None
    url: str | None = None                # link URL, or the document URL for an upload
    provider_name: str | None = None      # links only; absent on uploads
    preview_image: list[ImageVariant] = []

# --- shape UNVERIFIED: both captured profiles have these sections empty. ---
# Field names below are plausible candidates, not observed facts. The mapper tries
# several candidate keys per field (Step 10) and every one of these is reported in
# meta.unverified_sections. Do not present them as verified.

class VolunteerExperience(BaseModel):
    role: str | None = None
    organization_name: str | None = None
    cause: str | None = None
    description: str | None = None
    date_range: DateRange | None = None

class Honor(BaseModel):
    title: str | None = None
    issuer: str | None = None
    description: str | None = None
    issued_on: DatePart | None = None

class Publication(BaseModel):
    name: str | None = None
    publisher: str | None = None
    description: str | None = None
    url: str | None = None
    published_on: DatePart | None = None

class Patent(BaseModel):
    title: str | None = None
    number: str | None = None
    description: str | None = None
    url: str | None = None
    issued_on: DatePart | None = None

class Course(BaseModel):
    name: str | None = None
    number: str | None = None

class Organization(BaseModel):
    name: str | None = None
    position: str | None = None
    description: str | None = None
    date_range: DateRange | None = None

class TestScore(BaseModel):
    name: str | None = None
    score: str | None = None
    description: str | None = None
    taken_on: DatePart | None = None

class TruncationInfo(BaseModel):
    returned: int
    total: int

class ResponseMeta(BaseModel):
    fetched_at: str                     # ISO-8601 UTC, when the UPSTREAM fetch happened
    duration_ms: int                    # time to serve THIS request
    decoration_id: str
    source: str = "live"                # "live" | "cache" | "stale" | "fixture"
    cached: bool = False
    stale: bool = False                 # served from the stale store after an upstream failure
    stale_reason: str | None = None     # the error type that forced the stale response
    truncated: dict[str, TruncationInfo] = {}
    unverified_sections: list[str] = [] # sections whose field mapping is unconfirmed

class ProfileData(BaseModel):
    profile: ProfileCore
    experience: list[Experience] = []
    education: list[Education] = []
    skills: list[str] = []
    certifications: list[Certification] = []
    languages: list[Language] = []
    projects: list[Project] = []
    featured_media: list[FeaturedMedia] = []
    volunteering: list[VolunteerExperience] = []
    honors: list[Honor] = []
    publications: list[Publication] = []
    patents: list[Patent] = []
    courses: list[Course] = []
    organizations: list[Organization] = []
    test_scores: list[TestScore] = []

class ProfileResponse(BaseModel):
    success: bool = True
    data: ProfileData
    meta: ResponseMeta

class ProfileRequest(BaseModel):
    url: str
    li_at: str | None = None
```

**Domain invariants:** dates are structured, never raw display strings. `is_current`
is `True` exactly when a `dateRange` has a `start` and no `end`.

`fetched_at` describes the **data**, `duration_ms` describes the **request**. On a cache
hit `fetched_at` keeps the original upstream timestamp — that is the provenance the caller
needs — while `duration_ms` is remeasured and `cached` is `True`. Only what is cached is
`(ProfileData, truncated, decoration_id, fetched_at)`; the rest of `meta` is rebuilt per
request. Storing a fully assembled `ProfileResponse` and returning it verbatim reports a
stale `duration_ms` and claims `cached: False` on a cache hit.

The four `source` values are mutually exclusive and each pins the other flags, so there is
exactly one legal combination per source. `live`: `cached=False, stale=False`. `cache`: a
fresh TTL hit, `cached=True, stale=False`. `stale`: an expired entry served because the
upstream call failed, `cached=True, stale=True`, and `stale_reason` set to the failing
exception's class name. `fixture`: the `/v1/profile/example` route, all flags `False`.
`stale_reason` is `None` unless `stale` is `True`. Assert this table in a test — these
flags are the response's honesty about its own provenance, and a reviewer reading
`stale: false` over week-old data is worse than a plain error.

**Verify:** `uv run python -c "from app.schemas import ProfileResponse"` exits 0.

---



### Step 10 — Mapper

**Action:** Create
**Files:** `app/linkedin/mapper.py`, `tests/test_mapper.py`

```python
UNVERIFIED_SECTIONS: tuple[str, ...] = (
    "volunteering", "honors", "publications", "patents",
    "courses", "organizations", "test_scores",
)

def build_profile_data(payload: dict) -> tuple[ProfileData, dict[str, TruncationInfo]]:
    """Map a raw Voyager payload to the response schema. Returns data plus truncation report."""
```

`app/main.py` copies `UNVERIFIED_SECTIONS` into `meta.unverified_sections`.

Use `EntityGraph`. Field mapping, exactly:

**ProfileCore** — from the root `Profile` entity:


| Output                                        | Source                                                       |
| --------------------------------------------- | ------------------------------------------------------------ |
| `public_identifier`                           | `publicIdentifier`                                           |
| `profile_urn`                                 | `entityUrn`                                                  |
| `member_urn`                                  | `objectUrn`                                                  |
| `first_name` / `last_name`                    | `firstName` / `lastName`                                     |
| `full_name`                                   | `f"{firstName} {lastName}"`, stripped; `None` if both absent |
| `headline`                                    | `headline`                                                   |
| `about`                                       | `summary`                                                    |
| `industry`                                    | `resolve(profile["*industry"])["name"]`                      |
| `is_premium` / `is_influencer` / `is_creator` | `premium` / `influencer` / `creator`                         |
| `profile_picture`                             | `picture_variants(profile["profilePicture"])`                |
| `background_image`                            | `picture_variants(profile["backgroundPicture"])`             |


Both images go through `picture_variants` (Step 8), **not** `image_variants` on a
hand-picked reference key. Reading `originalImageReference` directly returns nothing for
third-party profiles — see 0.2 and the Step 8 warning.

**Location** — resolve `profile["geoLocation"]["*geo"]` to a `Geo` entity, then
`full` ← `defaultLocalizedName`, `city_region` ← `defaultLocalizedNameWithoutCountryName`,
`country_code` ← `profile["location"]["countryCode"]`. Every hop may be missing;
tolerate `None` at each level. Note some `Geo` entities carry only `entityUrn`.

`country` needs two cases, because the geo a member points at is not always city-level:

1. If `geo["*country"]` is present, resolve it and take its `defaultLocalizedName`.
  This is the city-level case (`sample_payload`: `Springfield, Example State, Exampleland`
   → country `Exampleland`).
2. If `*country` is **absent** and `defaultLocalizedName == defaultLocalizedNameWithoutCountryName`,
  the geo **is itself a country** — the member set their location to just a country — so
   use its own `defaultLocalizedName` (`rich_payload`: both names are `Exampleland`).
   In this case `countryUrn` is present but `null`, so it is not a usable fallback.
3. Otherwise `None`.

Without case 2, `country` is `null` for every member whose location is country-level,
which is common. This is the same omitted-key pattern as 0.2's "Absent keys" row, showing
up a third time — the absence of `*country` carries meaning rather than indicating an error.

**Experience** — iterate `follow(profile, "*profilePositionGroups")` in order; for each
group iterate `follow(group, "*profilePositionInPositionGroup")`; flatten. This
preserves LinkedIn's display order. Only if that yields **nothing at all**, fall back to
`entities_of_type("profile.Position")` — a last resort that loses display order and can
pick up dangling entities (0.2), so never use it to supplement a non-empty result, and
never use it for the other collections where counts are asserted.


| Output                         | Source (on the `Position`)                                                                         |
| ------------------------------ | -------------------------------------------------------------------------------------------------- |
| `title`                        | `title`                                                                                            |
| `company_name`                 | `companyName`, else the group's `companyName`                                                      |
| `company_urn`                  | `companyUrn`                                                                                       |
| `company_url` / `company_logo` | from `resolve(position["*company"])`: `url`, `image_variants(company["logo"])`                     |
| `employment_type`              | `resolve(position["*employmentType"])["name"]` — the key is absent on some positions; yield `None` |
| `location`                     | `locationName`, else `geoLocationName`                                                             |
| `description`                  | `position.get("description")` — **real content when the member wrote one.** Do not hardcode `None` |
| `date_range`                   | `dateRange` via the shared date converter                                                          |


**Education** — `follow(profile, "*profileEducations")`; `school_name` ← `schoolName`,
`degree` ← `degreeName`, `field_of_study` ← `fieldOfStudy` (**strip trailing whitespace** —
real data contains `"Computer Science and Engineering "`), `grade`, `activities`,
`description`, `date_range`; `school_url`/`school_logo` from `resolve(education["*school"])`.

**skills** — `[skill["name"] for skill in follow(profile, "*profileSkills")]`, dropping `None`.

**certifications** — `follow(profile, "*profileCertifications")`; `name`, `authority`,
`license_number` ← `licenseNumber`, `url`, `display_source` ← `displaySource`,
`issued_on` ← `dateRange.start`.

**languages** — `follow(profile, "*profileLanguages")`; `name`, `proficiency`.

**projects** — `follow(profile, "*profileProjects")`; `title`, `description`, `url`,
`date_range` ← `dateRange`. Ignore `contributors` (it embeds other members' profiles;
mapping it would return third-party personal data we were not asked for).

**featured_media** — `follow(profile, "*profileTreasuryMediaProfile")` (never
`entities_of_type` — see 0.2 "Dangling entities"); `title`, `description`,
`provider_name` ← `providerName`, `preview_image` ← `image_variants(media["previewImage"])`.

`media["data"]` is a union, so `url` and `media_type` are derived from **which arm is
present**, checked in this order:


| `data` key                                  | `media_type` | `url`                                                          |
| ------------------------------------------- | ------------ | -------------------------------------------------------------- |
| `Url`                                       | `"link"`     | `data["Url"]` — note the **capital U**                         |
| `NativeDocument`                            | `"document"` | that object's `transcribedDocumentUrl`, else its `manifestUrl` |
| `NativeVideo` / anything containing `Video` | `"video"`    | `None`                                                         |
| `VectorImage` / anything containing `Image` | `"image"`    | `None`                                                         |
| nothing recognised                          | `None`       | `None`                                                         |


Both fixtures exercise this: `rich_payload`'s two entries are links, `sample_payload`'s one
entry is an uploaded PDF whose `data` has no `Url` at all. Reading `data["Url"]` alone
yields a title with no URL and no type for every uploaded document, which is the more
common case on real profiles. Ignore the remaining `NativeDocument` internals
(`coverPages`, `manifestUrlExpiresAt`, page counts) — they add bulk, expire quickly, and
`preview_image` already covers the thumbnail.

**The seven unverified sections** — map with a shared candidate-key helper so that a
wrong guess degrades to `None` instead of losing the record:

```python
def _first_key(entity: dict, *candidate_keys: str) -> object | None:
    """Return the first present, non-empty value among candidate_keys."""
```


| Output field                       | Collection                     | Candidate keys, in order                        |
| ---------------------------------- | ------------------------------ | ----------------------------------------------- |
| `volunteering[].role`              | `*profileVolunteerExperiences` | `role`, `title`                                 |
| `volunteering[].organization_name` |                                | `companyName`, `organizationName`, `name`       |
| `volunteering[].cause`             |                                | `cause`, `causeName`                            |
| `honors[].title`                   | `*profileHonors`               | `title`, `name`                                 |
| `honors[].issuer`                  |                                | `issuer`, `issuerName`                          |
| `honors[].issued_on`               |                                | `issuedOn`, `issueDate`, then `dateRange.start` |
| `publications[].name`              | `*profilePublications`         | `name`, `title`                                 |
| `publications[].publisher`         |                                | `publisher`, `publisherName`                    |
| `publications[].published_on`      |                                | `publishedOn`, `date`, then `dateRange.start`   |
| `patents[].title`                  | `*profilePatents`              | `title`, `name`                                 |
| `patents[].number`                 |                                | `number`, `applicationNumber`, `patentNumber`   |
| `patents[].issued_on`              |                                | `issuedOn`, `issueDate`, then `dateRange.start` |
| `courses[].name`                   | `*profileCourses`              | `name`, `title`                                 |
| `courses[].number`                 |                                | `number`, `courseNumber`                        |
| `organizations[].name`             | `*profileOrganizations`        | `name`, `organizationName`                      |
| `organizations[].position`         |                                | `position`, `role`, `title`                     |
| `test_scores[].name`               | `*profileTestScores`           | `name`, `title`                                 |
| `test_scores[].score`              |                                | `score` — coerce to `str` if numeric            |
| `test_scores[].taken_on`           |                                | `date`, `takenOn`, then `dateRange.start`       |


`description` and `url` on all of the above use the plain `description` / `url` keys, and
`date_range` uses `dateRange`. Every one of these sections is empty in both fixtures, so
each will map to `[]` — that is the expected, correct result, and the tests assert exactly
that. `build_profile_data` must add all **seven** names to the returned
`unverified_sections` list unconditionally, so the response is honest about them even
when empty.

**Date converter** — a module-private helper:

```python
def _to_date_range(raw: dict | None) -> DateRange | None:
```

`start`/`end` each map `{month, year}` (either may be absent — educations carry
year only). `is_current = start is not None and end is None`.

**Truncation report** — call `collection_paging` for **every** mapped collection:
`skills`, `certifications`, `educations`, `languages`, `positionGroups`, `projects`,
`featuredMedia`, and the seven unverified ones. When `total is not None and total > returned`,
add `TruncationInfo(returned=..., total=...)` under that name. Both fixtures must produce
exactly one entry: `{"skills": {"returned": 20, "total": 26}}` for `sample_payload` and
`{"skills": {"returned": 20, "total": 36}}` for `rich_payload`.

`tests/test_mapper.py` must run against **both** fixtures.

Against `sample_payload`:

- `full_name == "Alex Rivera"`, `public_identifier == "alex-rivera-demo"`
- `headline` and `about` are non-empty strings
- `location.full == "Springfield, Example State, Exampleland"`, `location.country_code == "IN"`
- `industry == "Information Technology & Services"`
- `len(experience) == 5`; first entry's `company_name == "Northwind"`; every entry has a non-`None` `title`
- exactly one experience has `is_current is True`
- `all(item.description is None for item in experience)` — **this member wrote no descriptions**, which is a property of this fixture, not of the API. Assert it with that comment attached, so nobody re-derives the old wrong conclusion.
- `len(education) == 1`; `field_of_study` has no trailing space; `grade == "8.09"`; `date_range.start.year == 2018` and `date_range.start.month is None`
- `len(skills) == 20`; all are non-empty strings
- `len(certifications) == 7`; first has `authority == "OpenCourse"` and a non-`None` `issued_on.year`
- `len(languages) == 2`; one has `proficiency == "FULL_PROFESSIONAL"`
- `len(profile.profile_picture) == 4`, ordered largest-first
- `len(projects) == 0`; `len(featured_media) == 1`
- that one featured entry has `media_type == "document"`, a `url` that is a non-empty string, and `provider_name is None` — the uploaded-document arm of the `data` union. A `data["Url"]`-only mapper fails this.
- truncation report `== {"skills": TruncationInfo(returned=20, total=26)}`

Against `rich_payload` — these are the assertions that guard the corrected facts:

- `full_name == "Taylor Quinn"`, `public_identifier == "taylor-quinn-demo"`
- `industry == "Computer Software"`; `location.country_code == "IN"`
- `location.full == "Exampleland"` and `location.country == "Exampleland"`, resolved through **case 2** of the Location rule — the geo has no `*country` key. A mapper implementing only case 1 returns `None` here and fails this assertion.
- `len(experience) == 3`; **every** entry has a `description` that is a non-empty string of more than 100 characters
- exactly **one** experience has `employment_type is None` while the other two do not — this is the absent-key rule in action
- `profile.profile_picture` is non-empty **and** `profile.background_image` is non-empty, despite `originalImageReference` being absent from both nodes
- `len(projects) == 2`; both have a non-empty `description`; one `title` starts with `"ATLAS"`; both have `date_range is None`
- `len(featured_media) == 2`; every entry has `media_type == "link"`, a `url` starting with `https://`, a non-`None` `provider_name`, and a non-empty `preview_image`
- `len(education) == 1`; `grade == "CGPA: 8.4 / 10"` — grade is **free text**, never assume numeric
- `len(languages) == 3`; `len(certifications) == 4`; `len(skills) == 20`
- truncation report `== {"skills": TruncationInfo(returned=20, total=36)}`
- all seven unverified sections map to `[]`, and `UNVERIFIED_SECTIONS` has exactly seven entries

Against both:

- `build_profile_data({"data": {"*elements": []}, "included": []})` raises `ProfileNotFoundError`
- a payload whose Profile has only `entityUrn` maps without raising, yielding `None`s and empty lists

**Verify:** `uv run pytest tests/test_mapper.py -q` — all pass.
**Must NOT:** raise on any missing field; use `.get()` and the resolver's `None`-tolerance
throughout. Do not read `multiLocale*` variants — always prefer the plain key. Do not
assert any field is *always* absent: that is how this spec was wrong before.

---



### Step 11 — Voyager client

> **Context so far:** `app/errors.py`, `app/config.py`, `app/logging_setup.py`,
> `app/schemas.py`, and under `app/linkedin/`: `constants.py`, `urls.py`,
> `normalize.py` (`EntityGraph`), `images.py`, `mapper.py`
> (`build_profile_data`). Tests exist for urls, normalize, images, mapper.

**Action:** Create
**Files:** `app/linkedin/client.py`, `tests/test_client.py`

```python
@dataclass
class VoyagerResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str
    def json(self) -> dict: ...

class Transport(Protocol):
    async def get(self, url: str, headers: Mapping[str, str]) -> VoyagerResponse: ...

class CurlTransport:
    """Real transport. curl_cffi AsyncSession with Chrome impersonation."""
    def __init__(self, proxy_url: str | None = None, ca_bundle: str | None = None) -> None: ...
    async def get(self, url: str, headers: Mapping[str, str]) -> VoyagerResponse: ...

class VoyagerClient:
    def __init__(self, li_at: str, transport: Transport | None = None) -> None: ...
    async def fetch_profile(self, vanity_name: str) -> tuple[dict, str]: ...
```

`CurlTransport.get` constructs `AsyncSession(impersonate=IMPERSONATE_TARGET, verify=ca_bundle or True, proxies=...)`,
issues the GET with `allow_redirects=False`, and wraps any `curl_cffi` exception in
`UpstreamUnavailableError`. Sets no `user-agent`.

`VoyagerClient.__init__` generates the synthetic CSRF token once:
`"ajax:" + "".join(random.choices(string.digits, k=19))`, and builds the cookie header
`f'li_at={li_at}; JSESSIONID="{token}"'`. The header value passed as `csrf-token` is the
**unquoted** token.

`fetch_profile` loops `DECORATION_CANDIDATES`; for each, builds the URL
`{VOYAGER_BASE}{PROFILE_PATH}?q=memberIdentity&memberIdentity={quote(vanity)}&decorationId={decoration}`
with referer `https://www.linkedin.com/in/{vanity}/`, calls the transport, then applies
`_classify` (below). On success returns `(payload, decoration_used)`.

**Retry policy — retry on** `UpstreamShapeError` **only.** Every other error must propagate
immediately without trying the next decoration:


| Error from a decoration                                                | Action                                                                                      |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `UpstreamShapeError`                                                   | try the next decoration — a stale decoration is exactly what this looks like                |
| `ProfileNotFoundError`                                                 | **raise immediately.** The profile does not exist; a different decoration cannot conjure it |
| `SessionRevokedError`                                                  | raise immediately. The cookie is dead; a retry cannot succeed                               |
| `SessionRejectedError`, `RateLimitedError`, `UpstreamUnavailableError` | raise immediately                                                                           |


> **Why this matters more than it looks.** LinkedIn revoked test sessions after roughly
> ten requests. Retrying a 404 doubles the upstream cost of every bad URL, so a handful of
> typo'd requests can burn the session before any real lookup happens. Requests are the
> scarce resource in this system; spend at most one per profile.

If all decorations are exhausted with shape errors, raise the last error. Sleep a short
randomised interval (`random.uniform(0.8, 1.6)` seconds) between attempts only — never
before the first request.

`_classify(response) -> None` raises per 0.6:

1. status in `(301,302,303,307,308)`: if `"delete me"` appears in the `set-cookie` header, or `Location` equals the request URL → `SessionRevokedError`; otherwise `SessionRejectedError`.
2. status in `(401, 403)` → `SessionRejectedError`
3. status in `(429, 999)` → `RateLimitedError`
4. status `404` → `ProfileNotFoundError`
5. status `200` but body is not JSON, or lacks `data`/`included` → `UpstreamShapeError`
6. any other non-200 → `UpstreamShapeError`

Also add `async def validate_session(self) -> bool` calling `ME_PATH`, used by nothing
in the request path — it exists for the capture script and manual diagnosis.

`tests/test_client.py` uses a `FakeTransport` implementing `Transport` and returning
canned `VoyagerResponse` objects. Assert:

- 200 + `sample_payload` → `fetch_profile` returns the payload and the first decoration
- `302` with `set-cookie: li_at="delete me"; Max-Age=0` → `SessionRevokedError`
- `302` with `Location` equal to the request URL → `SessionRevokedError`
- `403` → `SessionRejectedError`; `429` → `RateLimitedError`; `999` → `RateLimitedError`
- 200 with body `"not json"` on the first decoration and a valid payload on the second → succeeds with the **second** decoration (shape errors are the only retryable case)
- `404` on the first decoration → `ProfileNotFoundError`, and the fake transport records **exactly one** call (proves the 404 is not retried)
- 200 with body `"not json"` on both → `UpstreamShapeError`
- 200 with `{"data": {}}` (no `included`) on both → `UpstreamShapeError`
- `302` with `li_at="delete me"` on the first decoration → the fake transport records exactly one call
- the `csrf-token` header equals the `JSESSIONID` cookie value, unquoted, on every call
- no `user-agent` key is present in the headers
- the cookie header contains the `li_at` exactly once

**Verify:** `uv run pytest tests/test_client.py -q` — all pass, and no test performs real I/O.
**Must NOT:** follow redirects; retry a `SessionRevokedError` (the cookie is dead — retrying cannot help); or include the cookie in any raised message.

---



### Step 12 — HTTP surface

> **Context so far:** everything above plus `VoyagerClient` / `Transport` /
> `CurlTransport` in `app/linkedin/client.py`.

**Action:** Create
**Files:** `app/main.py`, `tests/test_api.py`

Routes:

- `POST /v1/profile` — body `ProfileRequest`. Session precedence: `X-LI-AT` header, then body `li_at`, then `settings.linkedin_li_at`. None available → `MissingCredentialsError`.
- `GET /v1/profile?url=...` — same logic but `li_at` **must not be accepted as a query parameter**; only the `X-LI-AT` header or the server fallback.
- `GET /v1/profile/example` — no credentials, no rate limit, no network. Loads
`settings.example_fixture_path`, runs it through the **real** `build_profile_data`, and
returns a normal `ProfileResponse` with `meta.source == "fixture"` and
`meta.decoration_id` set to the primary decoration. If the file is missing, return 404
with `{"success": false, ...}` rather than raising.
- `GET /health` — `{"status": "ok", "server_session_configured": bool(settings.linkedin_li_at)}`. Must never touch the network and must respond fast (Render free tier cold-starts, and this is the wake-up path).
- `GET /` — redirect to `/docs`.

> **Why** `/v1/profile/example` **exists, and why it is not cheating.** A lifted `li_at`
> survives roughly ten automated requests (0.2), so the single most likely thing a reviewer
> sees on a deployed instance is `401 SessionRevokedError` and no JSON at all. This route
> guarantees the schema and the mapper are always demonstrable, costs one file read, and is
> honest because `meta.source` says `fixture` and the README says so too. It must share the
> mapper with the live path — a hand-written JSON blob would prove nothing. Do **not** let
> it fall back to serving fixture data from `/v1/profile`: that route stays live-only.

Both `/v1/profile` routes declare `response_model=ProfileResponse` and
`responses={...}` documenting the error statuses from 0.6 — this is what makes `/docs`
serve as the API documentation deliverable, so it is not optional.

Cross-cutting:

- `configure_logging` on startup.
- API key: if `settings.api_key` is set, require a matching `X-API-Key` on the two
`/v1/profile` lookup routes, else 401. If unset, the service is open (so a reviewer is
never locked out). `/v1/profile/example`, `/health` and `/docs` are **never** gated — the
example route holds anonymised fixture data and exists precisely so that a reviewer with
no key and no working cookie can still see a real response.
- One exception handler for `LinkedInAPIError` per 0.6, plus a catch-all handler for unexpected exceptions returning a generic 500 that leaks no internals.
- FastAPI metadata: title `LinkedIn Profile API`, a description, version `1.0.0`.

**Injectable transport.** Define a module-level dependency so tests can substitute a fake
without patching:

```python
def get_transport() -> Transport:
    settings = get_settings()
    return CurlTransport(proxy_url=settings.proxy_url, ca_bundle=settings.ca_bundle)
```

Both `/v1/profile` handlers take `transport: Transport = Depends(get_transport)` and pass
it to `VoyagerClient(li_at, transport=transport)`. Tests use
`app.dependency_overrides[get_transport] = lambda: fake_transport`. Without this
dependency there is no seam to override and the tests below cannot be written.

**Rate limiting.** Two independent limits. **Keep both** — they protect different things,
and neither substitutes for the other:

1. Per-client, via `slowapi`: `settings.rate_limit_per_minute` requests/minute keyed on
  client IP, default 30. Protects the **service** from a single noisy caller, and is the
   conventional, expected control on a public API — a reviewer looks for it, and its absence
   reads as an omission rather than a choice. Roughly five lines once wired.
2. **A global ceiling on upstream calls**, which the per-client limit cannot provide: a
  process-wide counter allowing at most `settings.upstream_limit` Voyager requests per
   rolling 60 seconds across all callers, default 8. On exceeding it, raise
   `RateLimitedError` **without** calling LinkedIn. Protects the **cookie**.

Why one is not enough: the per-IP limit is per-client while the cookie is a single shared
resource, so several callers each staying under 30/minute will still burn the session. The
global ceiling covers that. Conversely the global ceiling would let one abusive client
consume the whole budget, which the per-IP limit prevents. Both limits are configurable by
environment variable and documented in the README.

The second is the one that matters. Sessions were revoked after roughly ten requests, and
the cookie is a single shared resource while the per-IP limit is not — several clients each
staying under 30/minute will still destroy the session. Cache hits do not count against it,
since they make no upstream call.

Because tripping this ceiling produces the same 429 as a real LinkedIn block, its message
must distinguish the two — something like "local upstream ceiling reached (8 requests/60s);
this request did not reach LinkedIn". A reviewer who sees a bare 429 will read it as the
integration being broken. Keep it configurable via `UPSTREAM_LIMIT` so the value can be
raised without a code change, and state the default in the README.

`slowapi` wiring, in this order, or the limiter silently does nothing:
`limiter = Limiter(key_func=get_remote_address)`; `app.state.limiter = limiter`;
`app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)`; and every decorated
route **must** accept a `request: Request` parameter.

**Caching — two stores, both keyed on the vanity name only**, never on the cookie, so one
caller's cookie is never part of a cache key:

1. `fresh_cache = TTLCache(maxsize=256, ttl=settings.cache_ttl)` — the normal cache. A hit
  here is served immediately with `meta.source="cache"`, `meta.cached=True`.
2. `stale_cache = TTLCache(maxsize=256, ttl=STALE_TTL)` with `STALE_TTL = 86_400` — the
  last known-good response per profile, kept far longer. Written on every success,
   alongside the fresh cache. Read **only** on upstream failure.

Both stores hold the tuple `(ProfileData, truncated, decoration_id, fetched_at)` rather
than an assembled `ProfileResponse`, because `meta` is per-request; see the Step 9 note.

**Serve-stale on upstream failure.** When `fetch_profile` raises one of the
"cannot reach it right now" errors — `SessionRevokedError`, `SessionRejectedError`,
`RateLimitedError`, `UpstreamUnavailableError`, `UpstreamShapeError` (all decoration
suffixes rotated, per Section 4) — check `stale_cache`. On a hit, return
`200` with the cached payload, `meta.source="stale"`, `meta.stale=True`, and
`meta.stale_reason` set to the exception's class name. On a miss, let the error propagate
per 0.6.

Never serve stale for `ProfileNotFoundError` or `InvalidProfileURLError`: those are
definitive answers about the request, not transient upstream conditions, and masking them
with old data would be wrong.

> Why this exists: a `li_at` dies without warning, and a reviewer hitting a dead cookie sees
> a `401` and concludes the deployment is broken. A clearly-flagged stale response is both
> more useful and more honest. It must be visibly flagged — silently serving old data as
> fresh would be worse than the `401`.

**Single-flight.** Hold a `dict[str, asyncio.Lock]` keyed on vanity name. Before fetching,
acquire that profile's lock; once inside, **re-check** `fresh_cache` before going upstream,
because a concurrent request may have populated it while this one waited. Without this,
N concurrent requests for the same profile cost N upstream calls.

> This is not a performance optimisation. Sessions were revoked after roughly ten requests,
> so duplicated upstream work spends a budget that cannot be replenished without a human
> fetching a new cookie. Treat upstream requests as the scarce resource in this system.

Prune the lock dict opportunistically (drop entries whose lock is unlocked once it exceeds,
say, 1024 keys) so it cannot grow without bound across many distinct vanity names.

**Handler flow — the order is security-relevant:**

1. verify `X-API-Key` (if configured)
2. apply the per-client rate limit
3. extract the vanity name from the URL
4. **resolve the session** — `X-LI-AT`, then body `li_at`, then the server fallback; raise `MissingCredentialsError` if there is none
5. `fresh_cache` lookup, and on a hit assemble the response with `source="cache"` and return
6. acquire this vanity's single-flight lock, then **re-check** `fresh_cache` — a concurrent request may have filled it while this one waited — and return a hit the same way
7. check the global upstream ceiling, then `VoyagerClient(li_at, transport=transport).fetch_profile(...)`
8. on a transient upstream failure, apply the serve-stale rule: return the `stale_cache` entry with `source="stale"` if there is one, else let the error propagate
9. `build_profile_data` → assemble `ProfileResponse` with `source="live"`, `fetched_at` = now, `duration_ms` = time to serve this request
10. write the cache tuple to **both** `fresh_cache` and `stale_cache`, release the lock, return

> **Do not move the cache lookup above step 4.** Because the cache key is the vanity name
> alone, a lookup before credential resolution lets an unauthenticated caller read any
> profile another caller already fetched, bypassing both the API key check and
> `MissingCredentialsError`. Authenticate first, then read the cache.

`tests/test_api.py` uses FastAPI's `TestClient` with `get_transport` overridden to a fake
returning `sample_payload` (and, where noted, `rich_payload`). Assert:

- `POST /v1/profile` with a valid URL and `X-LI-AT` → 200, `data.profile.full_name == "Alex Rivera"`
- `GET /v1/profile?url=...` with `X-LI-AT` → 200
- with the fake returning `rich_payload` → 200 and `data.projects` has 2 entries and `data.featured_media` has 2, proving the new sections survive serialisation
- `meta.unverified_sections` has exactly seven entries and names all seven sections
- invalid URL → 400 with `error.type == "InvalidProfileURLError"`
- no cookie anywhere and no server fallback → 401 `MissingCredentialsError`
- a company URL → 400
- `/health` → 200, and `server_session_configured` is a bool
- with `API_KEY` set, a missing/incorrect `X-API-Key` on `/v1/profile` → 401; correct → 200; and `/v1/profile/example` → **200 even with no key**
- a fake transport raising `SessionRevokedError` **with an empty** `stale_cache` → 401 with that `error.type`. State the empty-stale precondition in the test name: once serve-stale exists, this assertion only holds for a profile that was never fetched successfully, and a test that primes the cache first will get a 200 instead.
- a fake transport raising `RateLimitedError` with an empty `stale_cache` → 429
- the second identical request is served from cache (fake transport call count stays 1), and that second response has `meta.cached is True` and `meta.source == "cache"` while the first has `cached is False` and `source == "live"`
- both responses carry the **same** `meta.fetched_at`, because that timestamp describes the data rather than the request
- `GET /v1/profile/example` → 200 with no `X-LI-AT` and no server fallback, `meta.source == "fixture"`, `data.profile.full_name == "Alex Rivera"`, and the fake transport records **zero** calls
- `GET /v1/profile/example` with `EXAMPLE_FIXTURE_PATH` pointed at a nonexistent file → 404, `success is False`, and no traceback in the body
- **cache does not bypass auth:** prime the cache with an authorised request, then, with `API_KEY` set, repeat it with no `X-API-Key` → **401, not a cached 200**
- **cache does not bypass credentials:** prime the cache, then repeat with no cookie and no server fallback → **401** `MissingCredentialsError`
- **serve-stale:** prime a success, expire `fresh_cache` (construct the app with `cache_ttl=0`, or clear it directly), then make the transport raise `SessionRevokedError` → **200** with `meta.source == "stale"`, `meta.stale is True`, `meta.cached is True`, `meta.stale_reason == "SessionRevokedError"`, the same `meta.fetched_at` as the primed response, and identical `data`
- **stale does not mask a definitive answer:** prime a success, expire `fresh_cache`, then make the transport raise `ProfileNotFoundError` → **404, not a stale 200**
- **stale does not bypass auth:** prime a success, expire `fresh_cache`, set `API_KEY`, then request with no `X-API-Key` while the transport raises `SessionRevokedError` → **401**, never a stale 200
- **meta flag legality:** for each of the four `source` values reachable in tests (`live`, `cache`, `stale`, `fixture`), assert the exact `(cached, stale, stale_reason)` combination from the Step 9 table
- **single-flight:** with `httpx.AsyncClient(transport=ASGITransport(app=app))`, fire two concurrent `GET /v1/profile?url=...` for the **same** vanity via `asyncio.gather` against a fake transport that awaits a short sleep before responding → both return 200 with identical `data`, and the fake records **exactly one** call. Then two concurrent requests for **different** vanities → the fake records two calls, proving the lock is per-vanity and not global.
- the global upstream ceiling: with cache disabled and `upstream_limit` at its default 8, the 9th distinct vanity within the window → 429 and the fake transport call count stays at 8; the error message makes clear the request never reached LinkedIn
- with `upstream_limit` overridden to 2, the 3rd distinct vanity → 429 (proves the limit is configuration, not a constant)
- **per-client rate limit:** with `rate_limit_per_minute` overridden to 2, a 3rd request from the same client inside the window → 429, and the body distinguishes it from both the upstream ceiling and a LinkedIn block
- **the two limits are independent:** the per-client 429 fires without incrementing the upstream counter, and `/v1/profile/example` is exempt from both
- **no response body and no emitted log record contains the test cookie value**

**Verify:** `uv run pytest -q` — the entire suite passes.
**Must NOT:** accept `li_at` as a query parameter; cache on a key that includes the cookie;
consult the cache before authenticating; return a stack trace or internal detail in any
error body.

---



### Step 13 — Capture script

**Action:** Create
**File:** `scripts/capture_fixture.py`

A standalone CLI: reads `LINKEDIN_LI_AT` from the environment or `--li-at`, takes
`--url` (default: the authenticated user's own profile, resolved via `/me`), makes the
**minimum** number of requests, and writes the raw payload to
`fixtures/raw_<vanity>.json`. Prints a `$type` inventory and the truncation audit,
including the count of **every** collection from 0.8 so a future capture immediately
reveals any section that is populated for that member.

Write to a **new** `fixtures/raw_<vanity>.json`, and refuse to overwrite an existing file
unless `--force` is passed. The existing raw captures are the source of the two committed
fixtures and must not be clobbered.

Include a prominent module docstring warning that LinkedIn revokes sessions under
automated access — observed revocation after roughly ten requests — so the script
must not be run in a loop.

The two committed fixtures were anonymised by hand. **There is deliberately no committed
anonymisation script:** the replacement table maps real names, employers and asset ids to
their fake counterparts, so committing it would leak exactly the data the anonymisation
removed.

If a third fixture is ever needed, scrub it ad hoc and run this audit. It is written out in
full because the obvious version — rewriting hostnames and names — is not enough: an earlier
revision of these fixtures rewrote the media host to `example.invalid` while leaving the real
asset ids and signed `t=` tokens intact, so restoring the original host reproduced live URLs
to the member's real photos and uploaded résumé.

Against the raw capture the fixture was derived from, the scrubbed file must share **zero**:

- media asset ids, matched by `/(?:image|document)/(?:media/|pl/)?v2/([A-Za-z0-9_\-]{10,})`
- artifact path segments, matched by `/([A-Za-z0-9_\-]{8,})/0/\d+`
- signed tokens, matched by `[?&]t=([A-Za-z0-9_\-]{10,})`
- identifying urns: `fsd_company`, `fsd_school`, `fsd_geo`, `collectionResponse`, `digitalmediaAsset`
- first name, last name, `publicIdentifier`, `objectUrn`, `trackingId`, `$anti_abuse_uuid`, and any personal domain in a project or featured-media URL

and must contain zero occurrences of `licdn.com`. Keep `fsd_industry`,
`fsd_employmentType` and `fsd_degree` — global taxonomy, identifying nobody, and the
fixtures are more realistic with them.

Every replacement must be applied as a **global string substitution over the whole file**,
longest match first, so that a value used as both an `entityUrn` and a `*`-reference stays
consistent and the graph still resolves. Then confirm the structure is untouched: identical
`included` length, identical `$type` counts, identical root-`Profile` key set, and no
`*`-reference on the root `Profile` that resolved before and does not resolve after.

**Verify:** `uv run python scripts/capture_fixture.py --help` exits 0 without network access.
**Must NOT:** print the cookie; write to or modify either committed `profile_*sample.json`;
overwrite an existing raw capture without `--force`.

---



### Step 14 — Containerisation and deploy config

**Action:** Create
**Files:** `Dockerfile`, `.dockerignore`, `render.yaml`

`Dockerfile`: base `python:3.13-slim`; copy `pyproject.toml` **and** `uv.lock`; install
with `uv sync --frozen --no-dev`; copy `app/`; copy **only** the two committed fixture
files, which `/v1/profile/example` needs at runtime:

```dockerfile
COPY fixtures/profile_sample.json fixtures/profile_rich_sample.json ./fixtures/
```

`curl_cffi` ships prebuilt wheels, so no compiler layer is needed. Do **not** copy
`tests/`, `.env`, or any `fixtures/raw_*`.

The start command **must be shell form** so Render's injected `$PORT` is expanded:

```dockerfile
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Exec form without `sh -c` passes `${PORT:-8000}` to uvicorn as a literal string. The
container starts, the port never binds, and Render fails the health check with nothing
obviously wrong in the build log — this is the most likely way this deploy silently fails.

`.dockerignore`: `.env*`, `fixtures/raw_*`, `tests/`, `.venv/`, `__pycache__/`, `.git/`.
Note this must not exclude `fixtures/` wholesale, or the `COPY` above fails the build.

`render.yaml`: one `web` service, `healthCheckPath: /health`, and env vars
`LINKEDIN_LI_AT`, `API_KEY`, `PROXY_URL`, `CACHE_TTL`, `UPSTREAM_LIMIT`,
`RATE_LIMIT_PER_MINUTE` declared with `sync: false` so values are set in the Render
dashboard and never committed. Use
`runtime: docker`; the older key was `env: docker`, so check the current Render blueprint
schema before committing and use whichever that documents — a wrong key here is accepted
quietly and the service is built with the wrong runtime.

**Set** `region` **explicitly** — do not accept the default. Per 0.10, the geographic distance
between where the `li_at` was minted and where it is replayed is the strongest revocation
trigger, and Render defaults to Oregon. For a cookie created in India, use `singapore`:

```yaml
services:
  - type: web
    name: linkedin-profile-api
    runtime: docker
    region: singapore        # closest to where the li_at is minted; see 0.10
    plan: free
    healthCheckPath: /health
```

Add a comment in the file saying what the region is for, so whoever redeploys with a cookie
from elsewhere knows to change it rather than silently inheriting a bad choice.

**Verify:** `docker build -t linkedin-profile-api .` succeeds; `docker run -e PORT=9000 -p 9000:9000`
then curling `http://localhost:9000/health` returns 200, and `/v1/profile/example` returns
200 with `meta.source == "fixture"` — that last one proves the fixture `COPY` and the port
expansion both worked, which is exactly what breaks on the real deploy.
**Must NOT:** bake any secret into the image or `render.yaml`; copy `fixtures/raw_`* into
the image; use exec-form `CMD` with `${PORT}`.

---



### Step 15 — README

**Action:** Create
**File:** `README.md`

Sections, in order:

1. **What this is** — one paragraph, plus the deployed URL.
2. **Quickstart** — `uv sync`, `.env` setup, run, and a working `curl` example with real (anonymised) output. Note that Render's free tier sleeps after ~15 minutes idle and takes ~50s to wake, so the first request may be slow — this prevents a reviewer reading a cold start as a broken deploy. Use a generous `--max-time` in the examples.
  Lead this section with a **"try it in 10 seconds"** block that hits
   `GET /v1/profile/example` on the deployed URL, needing no credentials, and say plainly
   that it returns anonymised fixture data through the same mapper as the live path
   (`meta.source: "fixture"`). Then show the live `POST /v1/profile` call. State directly
   that a lifted `li_at` is short-lived under automation, so if the live call returns
   `401 SessionRevokedError` the deployment is working and the cookie has expired — and
   include the paste-a-fresh-cookie instruction for the Render dashboard right there.
   Do not bury this: it is the difference between a reviewer seeing a working API and
   concluding the integration is broken.
3. **API reference** — every endpoint including `/v1/profile/example`, headers, the full response schema, the `meta` fields and what `source` / `cached` / `stale` / `stale_reason` mean, and the error table from 0.6. Point at `/docs` for the interactive version. Be explicit that a `stale: true` response is a **200 carrying older data**, not a failure, and that `fetched_at` tells the caller how old it is.
4. **Approach: how this was reverse engineered** — the honest, differentiating section. Cover: Voyager as LinkedIn's private API; why `curl_cffi` TLS impersonation rather than a browser, and that PerimeterX fingerprints the TLS/HTTP2 handshake so plain `requests` is rejected before headers are read; the CSRF double-submit finding, that a synthesised `JSESSIONID` works and therefore `li_at` is the only real credential; the normalized-JSON `included` graph with `*`-prefixed references and two-hop collections; how image URLs are assembled from `rootUrl` plus artifact path segments; and that `profileView` is dead (410) while one dash decoration returns everything, which is why there is no GraphQL code here.
  Include a short **"what two profiles taught us that one could not"** note: Voyager omits
   empty keys instead of nulling them, so a single sample makes a member's blank field look
   like an API limitation. Two independently captured profiles were needed to establish that
   position descriptions are returned, that `originalImageReference` is owner-only, and that
   `paging.total` for skills varies per member. This is a genuinely differentiating detail —
   it shows the API was characterised rather than just called once.
5. **Architecture and trade-offs** — short, and the section that shows judgement rather than
  just output. Source the reasoning from 0.9 and 0.10, one short paragraph each:
  - **Synchronous, not a task queue.** The common pattern for scraping APIs is FastAPI plus Celery plus Redis returning `202` and a job id. That is right when completion time is unpredictable; this is one upstream call of one to two seconds, so a queue would add two services for no latency benefit. The one thing a queue would genuinely provide — global pacing of upstream calls — is obtained from the single-flight lock and the `UPSTREAM_LIMIT` ceiling instead.
  - **In-process cache and limiter, no Redis.** Render free web services cannot scale past a single instance, so single-process state is coherent rather than merely convenient. State the honest cost: the tier spins down after ~15 minutes and has an ephemeral filesystem with no persistent disk available, so cache and counters reset on wake. A cold cache is harmless; a reset counter is why the ceiling is set low.
  - **One request per profile, no decoy traffic.** Established LinkedIn automation tools inject fake feed and notification calls to look organic. That suits tools doing hundreds of writes; here every decoy would spend from the same session budget as a real lookup, and one profile fetch already looks like a human opening one page. Diverging deliberately, with the reason.
  - **Two rate limits, not one.** A conventional per-IP limit (`RATE_LIMIT_PER_MINUTE`, default 30) protects the service, and a process-wide ceiling on upstream calls (`UPSTREAM_LIMIT`, default 8) protects the shared LinkedIn session. Explain why one does not cover the other: the per-IP limit is per-client while the cookie is a single shared resource, so several well-behaved callers can still exhaust the session; and a global-only limit would let one abusive client consume the entire budget. Show both 429 bodies, since they mean different things and neither means LinkedIn blocked you.
  - **Single-flight and serve-stale.** Both exist because upstream requests, not CPU, are the scarce resource. Concurrent duplicate requests collapse into one upstream call, and a transient upstream failure returns the last good response flagged `stale` rather than a `401` that reads as a broken deploy.
  - **Why not a browser.** One line tying back to the brief: no Playwright or Selenium anywhere, and the TLS-impersonation approach is what makes that possible.
6. **Known limitations** — stated plainly, no hedging:
  - Skills are capped at 20 by the endpoint while `paging.total` reports the real count (26 and 36 on the two profiles tested). Surfaced in `meta.truncated` rather than worked around, because fetching the remainder costs additional requests and sessions are the scarce resource.
  - Seven sections — volunteering, honors, publications, patents, courses, organizations and test scores — are returned by the endpoint but were empty on both profiles available for testing, so their field names are inferred rather than observed. They are mapped defensively and listed in `meta.unverified_sections`. Say this plainly; it is more credible than pretending they are verified.
  - The service imposes its own ceiling of `UPSTREAM_LIMIT` (default 8) Voyager requests per rolling 60 seconds across all callers, to protect the shared cookie from exactly the automated-access pattern that gets sessions revoked. Exceeding it returns 429 without contacting LinkedIn. Explain that this is deliberate and configurable, so a 429 is not mistaken for an upstream block.
  - Featured media can be a link or an uploaded document; `media_type` distinguishes them. For uploads the URL is a short-lived signed document URL, so it expires.
  - Follower and connection counts are not present in this decoration's response and are not available from this endpoint.
  - Background and profile images come from `displayImageReference`; the uncropped `originalImageReference` is only exposed to the profile's owner, so it is unavailable for third-party lookups.
  - Decoration IDs carry version suffixes that rotate on LinkedIn deploys; two candidates are tried, and both going stale needs a re-capture — include the instructions.
  - A lifted `li_at` is a login, not a durable session: LinkedIn revoked test sessions after roughly ten automated requests, replying `302` with `li_at="delete me"`. Sessions are short-lived under automation, which is why serve-stale and `/v1/profile/example` exist — the API stays demonstrable across a revocation instead of returning only a `401`.
  - **The strongest revocation trigger is geographic, not behavioural.** A cookie minted in a browser in one country and then replayed from a cloud datacenter in another is the pattern LinkedIn's detection is built for — "impossible travel" — and it is the most likely reason a build that works locally fails immediately once deployed. Mitigated by deploying to the Render region nearest where the cookie was minted and by routing egress through a residential proxy in that country via `PROXY_URL`. Datacenter IP reputation compounds it independently of TLS fingerprint. Be direct that `PROXY_URL` is close to required for a reliable live demo rather than an optional extra.
  - Cache and rate-limiter state are in-process and reset whenever the free tier spins down or restarts, so the upstream ceiling is not durable across restarts. Deliberate: an external store is the fix, and it is not warranted at this scope.
  - Behind a TLS-inspecting corporate proxy, the impersonated fingerprint never reaches LinkedIn; `CA_BUNDLE` makes local runs work but such an environment cannot validate the approach.
  - Only person profiles (`/in/...`); no companies or schools.
  - This uses an undocumented private API and contravenes LinkedIn's Terms of Service. Built for a hiring challenge; not for production use.
7. **Security notes** — cookies accepted per request, never logged or persisted, redaction filter plus test; secrets only via environment; both the fresh and stale caches are keyed on the vanity name alone and are read only after authenticating, so neither can be used to bypass the API key. On the fixtures, be specific rather than just claiming "anonymised": names, `publicIdentifier`s, member urns, media asset ids, artifact path segments, signed URL tokens, and company/school/geo urns are all fabricated, media URLs point at the non-resolving host `media.example.invalid`, and the raw captures they were derived from are gitignored under an allowlist.
8. **Testing** — how to run, and that the suite needs no credentials or network.



**Verify:** every command in the README runs as written.
**Must NOT:** include a real cookie, API key, or personal data anywhere.

---



## 3. Final gate

All of the following must hold before the work is considered done:

1. `uv run pytest -q` — all pass, zero network calls.
2. `uv run ruff check .` — clean.
3. `docker build` succeeds; `docker run -e PORT=9000 -p 9000:9000` then curling
  `/health` **and** `/v1/profile/example` both return 200. The second call is the one that
   catches a missing fixture `COPY` or an unexpanded `${PORT}`, neither of which the build
   surfaces.
4. `uv.lock` is tracked by git (`git ls-files uv.lock` prints it). Without it
  `uv sync --frozen` in the Dockerfile fails, and only on the deploy host.
5. No cookie in anything committable. Scan only the files git would actually include, so a
  correctly-ignored local `.env` does not produce a false alarm, and use a length-bounded
   pattern rather than the literal prefix so the command does not match its own documentation:
   must return nothing. (A real `li_at` is ~200 characters; the bound avoids false positives.
   Running plain `grep -r` over the working tree instead **will** match your local `.env` and
   is not the check you want.)
6. **Nothing but the two allowlisted fixtures is committable from** `fixtures/`**.** Verify with
  `git add -An .` and read the output: it must list no `raw_*.json` and no other derived
   file. This is a stronger check than a cookie grep, because a leaked capture contains
   personal data but no cookie-shaped string.
7. Neither committed fixture contains `licdn.com`, a `t=` token other than the placeholder,
  or any media asset id or path segment that also appears in a `fixtures/raw_*.json`.
   This is the Step 13 audit; run it, do not assume it, because the fixtures previously
   passed a hostname check while still carrying live signed URLs:
   must report 0 for both.
8. `git status --porcelain` shows no `.env`.
9. `UNVERIFIED_SECTIONS`, `meta.unverified_sections` in a live response, and the README all
  say **seven** sections, and name the same seven.
10. A real third-party profile returns a populated `experience[].description`, a non-empty
  `profile.background_image`, and `meta.unverified_sections`. These three are the
   regression checks for the errors this spec previously contained.
11. Deployed to Render over HTTPS; `/health`, `/docs` and `/v1/profile/example` load; a real
  profile URL returns populated JSON (requires a fresh `li_at` in the Render dashboard).
   Paste the fresh cookie immediately before submitting, not hours earlier.
12. Pushed to a public GitHub repository.



## 4. If the live run fails after deploying

The overwhelmingly likely case is the first one, and the fix is usually not in the code.

1. `SessionRevokedError` **immediately, especially if it worked locally.** This is the
  expected default outcome of replaying a residential cookie from a cloud datacenter — see
   0.10. In order: confirm `region` in `render.yaml` is the one nearest where the cookie was
   minted; set `PROXY_URL` to a residential proxy in that country; then paste a **fresh**
   cookie, because the old one is already dead and no amount of proxying revives it. Do not
   start debugging the client — a working local run against the same code is proof the
   transport is fine.
2. `SessionRejectedError` **or** `RateLimitedError` **on every call.** Render's egress IP is
  flagged. Same fix: `PROXY_URL`.
3. `RateLimitedError` **with no upstream call in the logs.** That is our own
  `UPSTREAM_LIMIT` ceiling, not LinkedIn. Raise `UPSTREAM_LIMIT` if the traffic is
   legitimate, and remember it resets on every spin-down.
4. `UpstreamShapeError` **from all decorations.** The version suffixes rotated. Re-capture a
  current `decorationId` from browser devtools and add it to `DECORATION_CANDIDATES`.
5. **Reviewer reports a** `401` **but** `/health` **is fine.** Point them at
  `GET /v1/profile/example`, which needs no credentials and exercises the same mapper. If
   that returns 200, the deployment is healthy and only the cookie has expired.

