"""Copy local SANA data into a private Supabase schema without altering Auth or public data.

Run from backend: uv run --no-sync python ../cloudflare/migrate.py
Reads root .env.cloudflare.local. Never prints connection strings or passwords.
"""

import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from psycopg import sql
from sqlalchemy import URL, create_engine, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from alembic.config import Config  # noqa: E402

from alembic import command  # noqa: E402
from app import models  # noqa: E402, F401
from app.db import Base, get_engine  # noqa: E402


def credentials():
    path = ROOT / ".env.cloudflare.local"
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            value = v.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[k.strip()] = value
    if not values.get("SUPABASE_DATABASE_PASSWORD"):
        raise SystemExit("Save SUPABASE_DATABASE_PASSWORD in .env.cloudflare.local first")
    return path, values


def main():
    path, values = credentials()
    admin = create_engine(
        URL.create(
            "postgresql+psycopg",
            username="postgres.xbmphrhmgahqydrdbgbi",
            password=values["SUPABASE_DATABASE_PASSWORD"],
            host="aws-0-ap-southeast-1.pooler.supabase.com",
            port=5432,
            database="postgres",
        ),
        connect_args={
            "sslmode": "verify-full",
            "sslrootcert": str(ROOT / "cloudflare/certs/supabase-ca.crt"),
            "connect_timeout": 10,
        },
    )
    # Stable snapshot; do not migrate any token reservations or local image files implicitly.
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as source:
        with source.begin():
            if source.scalar(
                text("SELECT count(*) FROM generation_jobs WHERE status IN ('queued','processing')")
            ):
                raise SystemExit(
                    "Finish or cancel local generations before taking the migration snapshot"
                )
            if source.scalar(text("SELECT count(*) FROM generated_assets")):
                raise SystemExit(
                    "Local image files require a separate storage migration; no data copied"
                )
            snapshot = {
                table.name: [dict(row) for row in source.execute(select(table)).mappings()]
                for table in Base.metadata.sorted_tables
            }
    backup = (
        ROOT
        / ".data/backups"
        / ("cloudflare-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(snapshot, f, default=str, ensure_ascii=False)

    with admin.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(76155219)"))
        db.execute(text("CREATE SCHEMA IF NOT EXISTS sana"))
        db.execute(text("REVOKE ALL ON SCHEMA sana FROM PUBLIC, anon, authenticated"))
        db.execute(text("SET LOCAL search_path TO sana"))
        cfg = Config(str(ROOT / "backend/alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
        cfg.attributes["connection"] = db
        command.upgrade(cfg, "head")
        # Only a new, empty destination may receive a snapshot. Never overwrite live balances.
        counts = {
            t.name: db.scalar(select(__import__("sqlalchemy").func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }
        if any(counts.values()):
            raise SystemExit("Cloud schema already contains data; refusing to merge/overwrite it")
        for table in Base.metadata.sorted_tables:
            if snapshot[table.name]:
                db.execute(table.insert(), snapshot[table.name])
        role_exists = db.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='sana_runtime')")
        )
        if role_exists:
            raise SystemExit("Role sana_runtime already exists; inspect it before proceeding")
        runtime_password = secrets.token_urlsafe(36)
        with db.connection.driver_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE sana_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}"
                ).format(sql.Literal(runtime_password))
            )
        db.execute(text("GRANT USAGE ON SCHEMA sana TO sana_runtime"))
        db.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA sana TO sana_runtime"))
        for table in Base.metadata.sorted_tables:
            if table.name != "plans":
                db.execute(
                    text(f'GRANT INSERT, UPDATE, DELETE ON sana."{table.name}" TO sana_runtime')
                )
        # No public API roles can access application data even if API schemas change later.
        db.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA sana FROM PUBLIC, anon, authenticated"))
        # Persist before committing: a local write failure must roll back role creation too.
        # A failed remote commit can leave an unused value; a retry appends the current one.
        with path.open("a") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("\nSANA_CLOUD_RUNTIME_PASSWORD=" + runtime_password + "\n")
            f.flush()
            os.fsync(f.fileno())
    print("Copied to private schema sana:", {k: len(v) for k, v in snapshot.items()})
    print("Local backup saved; original database unchanged. Runtime credential saved locally.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        # DB exceptions can include parameters or connection credentials.
        print(
            "Migration failed:",
            type(error).__name__,
            "(credential details suppressed)",
            file=sys.stderr,
        )
        sys.exit(1)
