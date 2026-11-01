"""Enable only the comic limits in the existing SANA plans. No balance changes."""

import sys
from pathlib import Path

from sqlalchemy import URL, create_engine, select, text
from sqlalchemy.orm import Session

from migrate import credentials
from app.models import Plan

ROOT = Path(__file__).resolve().parents[1]


def enable():
    _, saved = credentials()
    url = URL.create(
        "postgresql+psycopg",
        username="postgres.xbmphrhmgahqydrdbgbi",
        password=saved["SUPABASE_DATABASE_PASSWORD"],
        host="aws-0-ap-southeast-1.pooler.supabase.com",
        port=5432,
        database="postgres",
    )
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "sslmode": "verify-full",
            "sslrootcert": str(ROOT / "cloudflare/certs/supabase-ca.crt"),
            "connect_timeout": 10,
        },
        execution_options={"schema_translate_map": {None: "sana"}},
    )
    try:
        with Session(engine) as db, db.begin():
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            plans = list(
                db.scalars(
                    select(Plan)
                    .where(Plan.code.in_(["basic", "pro", "plus"]))
                    .with_for_update()
                )
            )
            if len(plans) != 3:
                raise RuntimeError("Missing SANA plans")
            for plan in plans:
                limits = {**plan.limits, "max_comic_images": 4}
                if plan.code == "basic":
                    limits["max_panels"] = max(4, limits["max_panels"])
                    limits["kinds"] = list(dict.fromkeys([*limits["kinds"], "comic"]))
                plan.limits = limits
        print(
            "Comic limits enabled for existing plans; individual accounts were not modified."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        enable()
    except Exception as exc:
        sys.exit(f"Plan update failed: {type(exc).__name__} (credentials suppressed)")
