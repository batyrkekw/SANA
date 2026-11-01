# Cloudflare deployment

SANA keeps its Python/FastAPI backend and PostgreSQL models. Cloudflare Pages serves the
frontend at `https://learn-sana.pages.dev`; its `/api/*` and `/health/*` routes use a service
binding to the Python Worker `learn-sana`. Supabase Auth remains the identity provider.

**Deployment status (29 October 2026):** live at https://learn-sana.pages.dev. The backend,
queue, Hyperdrive and private Supabase schema are deployed. Three profiles, two materials and
the token ledger were copied from the local snapshot; the local database remains intact.
Public health/configuration and unauthenticated rejection checks passed. Supabase Site URL
and exact redirects use the public address. The signed-in public browser loaded the overview,
materials, generation history, token ledger, plans, settings and generation form. Rapid
section changes, a reload during an active read, opening a saved lesson and a generation
quote also passed. The real cloud Cron → Queue → Qwen →
Supabase generation passed: three quiz questions, one material, one 6-token charge, no
remaining reservation. Disposable test records were removed without changing user balances.

## Cloud runtime

- Python Workers + the existing FastAPI routes, SQLAlchemy models and transaction rules.
- Supabase PostgreSQL, private `sana` schema; `anon` and `authenticated` cannot access it.
- A dedicated `sana_runtime` role can read plans and modify application tables only.
- Hyperdrive uses verified TLS with the Supabase CA and disables query caching.
- The fetch handler is placed near Supabase in `aws:ap-southeast-1` (Singapore).
  `cf-placement: remote-SIN` confirms placement. `Server-Timing` reports application,
  database and SQL-guard wait durations without exposing queries or credentials.
- Synchronous SQL operations are serialized with request-local timer waits. A plain
  `asyncio.Lock` caused concurrent HTTP requests to be canceled as hanging promises
  and left the isolate locked. Authentication completes before acquiring the SQL guard.
- HTTP tasks are retained with `waitUntil` and shielded from client cancellation so
  navigating away cannot interrupt transaction cleanup and strand the SQL guard.
- Engine metadata and compiled SQL are reused within an isolate, while `NullPool` closes
  every session's connection. Request-local lock polling is limited to four wakeups per
  second, and response headers use pure ASGI middleware to reduce runtime overhead.
- Cabinet navigation detaches obsolete view subscriptions; duplicate reads share one
  request, so switching sections cannot cancel a request another view/prefetch needs.
  Initial dashboard data is reused; token balances arrive with transaction history.
- Material pages batch attachments in one query and omit full lesson content; job history
  joins saved material IDs instead of querying each row. A 12-material page takes five SQL
  statements including profile lookup; a job page takes three. Token history includes its
  balance in the same response.
- Pages serves public Auth configuration from the generated `sana-config.json` asset and
  caches the public plan catalogue for 60 seconds. Private routes always reach the API.
  Cabinet snapshots use a user-scoped memory/sessionStorage cache (at most 40 entries,
  30-minute lifetime, 500,000-character persistence budget). Reads are fresh for 15 seconds
  (plans: five minutes; jobs: four seconds); older snapshots render immediately while
  revalidating. Reloads restore only the authenticated user's snapshots. No credentials are
  added to this cache. Writes invalidate snapshots and in-flight responses; price quotes do
  not. Sign-out/account changes clear them, and 403/404 responses evict invalid resources.
  One background prefetch at a time warms the main sections and up to three recent lessons;
  hover/keyboard intent warms individual targets. Active jobs poll fresh data and invalidate
  dependent lists/balances when their status changes. Forms keep unsaved input during refresh.
  Cold routes use neutral skeletons; cached routes and job polls never replace data with a
  loading message. Background network failures leave data visible with a saved-data notice.
- Cloudflare Queues execute text and illustrated comic generation. A one-minute Cron drains the database outbox
  and refunds expired jobs. Duplicate delivery never creates a second charge/material.
- Workers AI: `@cf/qwen/qwen3-30b-a3b-fp8`, not the local `sana-qwen3:4b` model.
- Cloud inference has a deployment-wide cap of 100 new jobs per UTC day, in addition to
  user token balances. Failed jobs refund user tokens but still count toward the daily cap.
- Illustrated comics use Workers AI FLUX.2 klein 4B and a private COMIC_ART KV namespace. Non-comic image generation remains local. The migration
  stops if local image assets exist instead of silently losing those files.
- Quotas of the free Cloudflare/Supabase plans still apply. No paid plan is enabled by these
  scripts. The cap does not reserve the account's free AI allowance against other projects.

## First deployment

Requirements: Node 22+, uv **0.13.4+**, an existing Wrangler login with Workers, Pages,
Queues, Hyperdrive/connectivity and certificate permissions. CLI versions verified: 4.154.0 and 4.155.0.
The account configured here is the owner's existing main Cloudflare account
`1f10d8debbf323a3c6778e33f1cb1f78`; the account open in the browser can differ.

1. Save the Supabase database password in root `.env.cloudflare.local` as
   `SUPABASE_DATABASE_PASSWORD=...`. Keep the file private (mode 0600). It is Git-ignored.
   This is not a Supabase login password or Gmail app password.
2. Run the migration from `backend/`:

   ```sh
   uv run --no-sync python ../cloudflare/migrate.py
   ```

   This saves a local snapshot under ignored `.data/backups`, applies the existing Alembic
   migration in a private Supabase schema, copies users/materials/balances, and creates the
   restricted runtime role. It never modifies Supabase Auth. It refuses to overwrite a
   destination with existing application rows. The original local database remains intact.
3. Upload the public CA certificate once if using another Cloudflare account:

   ```sh
   npx wrangler@4.154.0 cert upload certificate-authority --name sana-supabase-ca --ca-cert cloudflare/certs/supabase-ca.crt
   ```

   Record its ID in `cloudflare/certs/cloudflare.json`. The existing account already has it.
4. Run `python3 cloudflare/provision.py` to create Hyperdrive. It reads the existing Wrangler
   login from its normal macOS configuration path and the newly generated database role
   password from `.env.cloudflare.local`; neither secret is placed in command arguments.
   It saves only the public Hyperdrive binding ID in `cloudflare/hyperdrive.json`.
5. The queue `sana-generations` and Pages project `learn-sana` already exist. For a fresh
   account, create the queue with 24-hour retention and the Pages project with production
   branch `main`. Do not create duplicates.
6. Build the frontend and cloud package, then deploy the backend first:

   ```sh
   npm ci
   npm run build
   python3 cloudflare/build.py
   cd cloudflare
   uv run pywrangler deploy --config wrangler.local.json
   cd pages
   CLOUDFLARE_ACCOUNT_ID=1f10d8debbf323a3c6778e33f1cb1f78 npx wrangler@4.154.0 pages deploy --project-name learn-sana --branch main
   ```

   If the system uv is older, the isolated equivalent is
   `uvx --from uv==0.13.4 uv run pywrangler ...`.
   `.build`, `python_modules`, `.venv-workers`, `.wrangler` and `wrangler.local.json` are ignored.
   The package copies selected backend sources and public Supabase settings only.
7. In Supabase Auth URL Configuration, set Site URL to `https://learn-sana.pages.dev` and add
   exact redirects `https://learn-sana.pages.dev/auth.html` and
   `https://learn-sana.pages.dev/auth.html?recovery=1`. Keep the existing localhost redirects.
8. Verify `/health/ready`, anonymous API rejection, sign-in, a generation through the real
   queue, the saved material, and one token settlement. A build/upload alone is not success.

Updates after the first deployment use step 6; **do not run the data migration again**.
The checked-in dependency locks pin the Python runtime packages. `backend/` continues to use
its own dependencies for local Uvicorn/Celery/Diffusers operation.

Regression checks must include simultaneous `/api/v1/plans`, `/health/ready`, and an
invalid-bearer `/api/v1/dashboard` request, followed by an authenticated dashboard load.
Also abort a read request while it is accessing the database, then repeat the concurrent
checks. Sequential health checks alone did not expose either request-lock failure. Both
the concurrent and disconnect checks passed on the public deployment (200/200/401).
All 54 backend tests passed, including cancellation, retained transaction cleanup and
rejecting authentication before opening a DB session. Cloud generation was rechecked:
one completed three-question quiz, one 6-token charge, no remaining reservation.
The 13 browser regression tests include delayed reads, switching away from settings,
blocked-network cache navigation, stale revalidation, reload restoration, preserved form
input, logout cleanup and job completion without a loading flash; they use API fixtures.
The 29 Node tests include cache expiry, ownership, shared requests, invalidation races and
permission/deletion errors. The public authenticated browser was checked
separately with real account data and a quote that did not reserve or spend tokens.

### Performance and Mac independence check, 29 October 2026

These are observed single-client timings, not a load-test guarantee. Before optimization,
the overview took about 8 seconds; public plans took 1.6–2.2 seconds. Afterward, a fresh
material read took 1.11 seconds, the overview 0.63 seconds, a full cabinet reload 1.33 seconds,
and a cached return 0.35 seconds. Edge configuration returned in 0.15 seconds and cached
public plans in 0.08 seconds. A cold catalogue miss can still take longer.

The local frontend, FastAPI, Celery and Ollama processes were suspended and the project's
PostgreSQL/Redis containers paused. Local HTTP probes timed out while public readiness and
configuration returned 200. A fresh authenticated cabinet reload and saved lesson worked.
A disposable cloud job completed through Cron → Queue → Workers AI → Supabase: three quiz
questions, exactly one 6-token charge, zero remaining reservation. Test rows were removed
and all previously running local services resumed. The Mac was not powered off; none of its
application services could answer during this check. At the time of that check, cloud images were disabled.

## Email delivery

SMTP currently uses Gmail. A stable website URL does not authenticate an email sending
domain or guarantee inbox delivery. Recipients can mark legitimate SANA messages as
“Not spam”. For general availability, use an owned sending domain with a transactional
email provider and its SPF/DKIM/DMARC records. `pages.dev` is a hosting address, not a sender
domain whose mail DNS records we can edit. Do not disable confirmation to hide spam issues.

References: [Python/FastAPI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/),
[Python/Hyperdrive](https://developers.cloudflare.com/hyperdrive/examples/python-workers/),
[Workers AI allowance](https://developers.cloudflare.com/workers-ai/platform/pricing/),
[Supabase SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

### Cabinet cache verification, 29 October 2026

With the published cache and a real signed-in account, six prepared sections switched in
95–138 ms, including automated click/wait overhead; reloading an already opened lesson
took 513 ms. Clicking a prefetched saved lesson took 70 ms. These are single-client observations, not a latency guarantee. Background
API reads completed successfully in the Worker tail. The browser fixtures now distinguish
Supabase Auth IDs from internal profile IDs, matching production.

## Single-page comics and administrator testing

Current cloud comics use one FLUX.2 klein 4B image request for a 512×512 page (1–4 scenes).
Qwen3-30B-A3B-FP8 generates the script and individual visual briefs; a deterministic prompt
assigns the panels to reading-order positions. RU/KK captions remain accessible HTML.
One private asset has `layout: comic_page` and `panel_count` metadata. It is both the cover
and full reader page. Older per-panel assets still render correctly.

A normal illustrated comic costs 22 internal SANA tokens. Server-owned `profiles.is_admin`
sets new jobs to cost 0; zero-delta reserve/charge/refund records preserve idempotency.
Toggling admin never changes an existing job's charge or the numerical token balance.
No public API accepts the flag. `python -m app.manage set-admin --supabase-id UUID --admin true`
grants it; `--admin false` revokes it. Apply the existing-cloud schema upgrade with
`backend/.venv/bin/python cloudflare/upgrade.py` before deploying. Never rerun `migrate.py`.

The image estimate is 26.05 Neurons/page before Qwen/retries, within the shared daily free
10,000-Neuron allocation. No paid plan is enabled. App limits remain 100 new jobs/day,
two active jobs per user and 128 MiB published image storage; admin bypasses only SANA credit.
Image phase timeout is 160 seconds with one transient retry; quota/safety failures are not
retried. Failed jobs release their reservation and delete staged bytes. Duplicate queue
deliveries do not regenerate. Ownership checks and authenticated asset reads are unchanged.

Both selected models publish Apache-2.0 weights. The undistilled klein base 4B is a future
training candidate, not the current hosted model. Custom image LoRA deployment is not currently
supported by this Workers AI endpoint. See [AI and training notes](../docs/AI.md).

## Historical per-panel pilot results (superseded configuration)

The original klein 4B live pilot on 1 November completed in about 33 seconds after queue pickup: four 512×512
JPEGs, one 52-token charge and zero remaining reservation. A separate failed provider call
returned the full reservation. One retry per job is allowed only for recognized transient
image-service errors; quota and content-policy failures are not retried. The image phase
has a five-minute overall deadline. Storage binary roundtrip also passed in the native
Workers runtime; API ownership/delete checks use PostgreSQL test fixtures.

Visual review found real errors: the root and shoot were rendered as a root vegetable and
seed pod. The public technical sample at /examples/bean-comic/ explicitly annotates these
mistakes. These images are not verified science diagrams. The creation form and reader
retain review guidance. This limitation should be evaluated before promoting illustrated
lessons more widely.

## Historical reader and dev experiment, 1 November 2026

FLUX.2 dev temporarily replaced the 4B pilot model after a bounded comparison against klein 9B on an
identical bean-root prompt. Both generated the main object correctly; dev was chosen for
its detail and lower estimated cost at 512px/20 steps. Four images + three references cost
approximately 4125 Neurons, before Qwen and retries. The 10,000/day free account allowance
therefore supports roughly two illustrated comics, not the entire 20-job application cap.
Keep the account on Workers Free; exceeding the allowance fails and refunds the job.

Private images now use a per-account, per-tab memory cache (16 MiB, 48 images, two concurrent
loads). Shared image requests survive route/background refreshes, cached covers are reused
inside the reader, and sign-out/account changes reject late responses and clear the cache.
Delete also invalidates image memory. No public asset URLs or shared HTTP caching are added.
New reader images take priority over covers still queued by an old view.
Material cards are full keyboard-accessible links and use panel zero as the cover. Recent
lesson data is prefetched ahead of auxiliary sections and remains fresh for five minutes;
mutations still invalidate it immediately. Deep links request lesson data while the dashboard loads.

The first full dev run completed in 43.4 seconds but visual review still found an incorrect
root: Qwen had returned CamelCase tags that passed the original language-only check. Art
brief validation now requires at least eight English words, and a single repair requests
ordinary sentences with explicit scale and physical connections. Regression tests cover
both Cyrillic and CamelCase inputs. This is a prompt-quality guard, not scientific validation.

The repaired two-panel cloud run completed in 34.5 seconds after 37.2 seconds in the outbox;
metadata confirmed flux-2-dev, two images, one 32-token charge and zero reservation. Review
still found two roots instead of one and a missing dish. /examples/seed-root/ preserves
the original outputs with explicit notes; no claim of scientific correctness is made.
