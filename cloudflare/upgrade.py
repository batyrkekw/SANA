"""Upgrade the existing private cloud schema; never copy or overwrite user data."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from migrate import credentials
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def admin_engine():
    _, values = credentials()
    return create_engine(
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


def main():
    engine = admin_engine()
    try:
        with engine.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(76155219)"))
            db.execute(text("SET LOCAL search_path TO sana"))
            if not db.scalar(text("SELECT to_regclass('sana.alembic_version')")):
                raise RuntimeError("Cloud schema must already exist")
            cfg = Config(str(ROOT / "backend/alembic.ini"))
            cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
            cfg.attributes["connection"] = db
            command.upgrade(cfg, "head")
        print("Private cloud schema upgraded; existing balances and materials preserved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"Upgrade failed: {type(error).__name__} (details suppressed)") from None
