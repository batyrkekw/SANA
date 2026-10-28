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
- Cloudflare Queues execute text generation. A one-minute Cron drains the database outbox
  and refunds expired jobs. Duplicate delivery never creates a second charge/material.
- Workers AI: `@cf/qwen/qwen3-30b-a3b-fp8`, not the local `sana-qwen3:4b` model.
- Cloud inference has a deployment-wide cap of 20 new jobs per UTC day, in addition to
  user token balances. Failed jobs refund user tokens but still count toward the daily cap.
- Image generation remains local; the cloud runtime disables it explicitly. The migration
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
application services could answer during this check. Cloud images remain disabled.

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
