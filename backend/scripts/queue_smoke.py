"""Explicit local integration check with real Redis, Celery, PostgreSQL and AI.

Creates and drops ONLY its randomly named schema. Never uses a real Supabase identity.
Run from backend/: uv run --no-sync python scripts/queue_smoke.py --kind quiz
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import command  # noqa: E402
from app.config import ROOT, get_settings  # noqa: E402
from app.manage import seed_plans  # noqa: E402
from app.models import Asset, Job, Material, Subscription, TokenAccount, TokenTransaction  # noqa: E402
from app.schemas import GenerationInput  # noqa: E402
from app.security import Identity  # noqa: E402
from app.services import create_job, ensure_profile  # noqa: E402
from app.worker import generate  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["quiz", "image"], default="quiz")
    parser.add_argument("--language", choices=["ru", "kk"], default="ru")
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    schema = "sana_smoke_" + uuid.uuid4().hex
    queue = schema
    settings = get_settings().model_copy(update={"llm_model": args.model, "image_enabled": True})
    url = settings.database_url.get_secret_value()
    isolated_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    admin = create_engine(url)
    engine = create_engine(isolated_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    output = ROOT / ".data/smoke"
    output.mkdir(parents=True, exist_ok=True)
    process = None
    started = time.monotonic()
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.begin() as db:
            config = Config("alembic.ini")
            config.attributes["connection"] = db
            command.upgrade(config, "head")
        with factory.begin() as db:
            seed_plans(db)
            owner = ensure_profile(db, Identity(uuid.uuid4(), "Local integration check"))
            if args.kind == "image":
                db.get(Subscription, owner.id).plan_code = "pro"
                db.flush()
            request = GenerationInput(
                kind=args.kind,
                subject="Математика",
                topic="Сложение натуральных чисел",
                language=args.language,
                grade=5,
                length=3,
                instructions="A blue school book and two colorful pencils, simple classroom illustration"
                if args.kind == "image"
                else "",
            )
            job, _ = create_job(db, owner, request, "local-smoke-" + uuid.uuid4().hex, settings)
            job_id, cost = job.id, job.cost
        environment = {
            **os.environ,
            "SANA_DATABASE_URL": isolated_url.render_as_string(hide_password=False),
            "SANA_ENVIRONMENT": "test",
            "SANA_LLM_MODEL": args.model,
            "SANA_IMAGE_ENABLED": "true",
            "SANA_STORAGE_DIR": str(output / "assets"),
        }
        with (output / "queue-worker.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "app.worker:celery_app",
                    "worker",
                    "--pool=solo",
                    "--concurrency=1",
                    "--loglevel=INFO",
                    "-Q",
                    queue,
                    "-n",
                    queue + "@localhost",
                    "--without-gossip",
                    "--without-mingle",
                ],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            generate.apply_async(args=[str(job_id)], queue=queue)
            deadline = time.monotonic() + settings.job_timeout_seconds + 60
            while time.monotonic() < deadline:
                with factory() as db:
                    job = db.get(Job, job_id)
                    if job.status in ("completed", "failed", "cancelled"):
                        if job.status != "completed":
                            raise RuntimeError(f"Real queue check failed: {job.error_code}")
                        account = db.get(TokenAccount, owner.id)
                        entries = db.scalars(select(TokenTransaction)).all()
                        assert (account.available, account.reserved) == (100 - cost, 0)
                        assert len(entries) == 3
                        material = db.scalar(select(Material))
                        assets = db.scalars(select(Asset)).all()
                        report = {
                            "status": "completed",
                            "kind": args.kind,
                            "language": args.language,
                            "cost": cost,
                            "available": account.available,
                            "reserved": account.reserved,
                            "ledger_entries": len(entries),
                            "content": material.content,
                            "assets": [str(output / "assets" / a.storage_key) for a in assets],
                            "seconds": round(time.monotonic() - started, 2),
                        }
                        path = output / f"queue-{args.kind}-{args.language}.json"
                        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                        print(
                            json.dumps(
                                {
                                    "status": "completed",
                                    "report": str(path),
                                    "seconds": report["seconds"],
                                }
                            ),
                            flush=True,
                        )
                        return
                if process.poll() is not None:
                    raise RuntimeError("Worker exited; inspect .data/smoke/queue-worker.log")
                time.sleep(1)
            raise TimeoutError("Real queue check timed out")
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
