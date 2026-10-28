# Cloudflare deployment

SANA keeps its Python/FastAPI backend and PostgreSQL models. Cloudflare Pages serves the
frontend at `https://learn-sana.pages.dev`; its `/api/*` and `/health/*` routes use a service
binding to the Python Worker `learn-sana`. Supabase Auth remains the identity provider.

**Deployment status (29 October 2026):** live at https://learn-sana.pages.dev. The backend,
queue, Hyperdrive and private Supabase schema are deployed. Three profiles, two materials and
the token ledger were copied from the local snapshot; the local database remains intact.
Public health/configuration and unauthenticated rejection checks passed. Supabase Site URL
and exact redirects use the public address. Public browser sign-in verification is pending. The real cloud Cron → Queue → Qwen →
Supabase generation passed: three quiz questions, one material, one 6-token charge, no
remaining reservation. Disposable test records were removed without changing user balances.

## Cloud runtime

- Python Workers + the existing FastAPI routes, SQLAlchemy models and transaction rules.
- Supabase PostgreSQL, private `sana` schema; `anon` and `authenticated` cannot access it.
- A dedicated `sana_runtime` role can read plans and modify application tables only.
- Hyperdrive uses verified TLS with the Supabase CA and disables query caching.
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
