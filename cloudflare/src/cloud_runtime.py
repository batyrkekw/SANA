"""Cloudflare transport adapters; shared SQLAlchemy models, quotas and validation."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import URL, create_engine, or_, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.errors import AppError
from app.models import Job, Material, utcnow
from app.prompts import generation_payload, parse_completion
from app.schemas import GenerationInput
from app.services import lock_account, settle

logger = logging.getLogger("sana.cloud")


class RequestLocalLock:
    """Serialize synchronous sockets without waking futures from another request.

    Workers binds pending I/O to the request that created it. An asyncio.Lock
    waiter resumed by a different request can be canceled as a hanging promise,
    leaving the isolate locked. Poll with the waiting request's own timer instead.
    Checking and taking the flag has no await, so it is atomic in this runtime.
    """

    def __init__(self):
        self._locked = False

    async def __aenter__(self):
        try:
            async with asyncio.timeout(15):
                while self._locked:
                    await asyncio.sleep(0.25)
                self._locked = True
        except TimeoutError as error:
            raise AppError("database_unavailable", 503) from error
        return self

    async def __aexit__(self, *_exc):
        self._locked = False


sql_lock = RequestLocalLock()


async def complete_request(operation, keep_alive):
    # A browser navigation can disconnect midway through synchronous SQL. Keep
    # the ASGI task alive so its transaction/session/guard finally blocks finish.
    task = asyncio.create_task(operation)
    keep_alive(task)
    return await asyncio.shield(task)


def factory_for(env):
    hd = env.HYPERDRIVE
    return cached_factory(hd.user, hd.password, hd.host, int(hd.port), hd.database)


@lru_cache(maxsize=2)
def cached_factory(user, password, host, port, database):
    # Cache dialect metadata/compiled SQL, never connections. NullPool closes each
    # socket with its request's session; a rotated binding gets a new factory.
    engine = create_engine(
        URL.create(
            "postgresql+pg8000",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        ),
        poolclass=NullPool,
        connect_args={"ssl_context": False, "timeout": 8},
        execution_options={"schema_translate_map": {None: "sana"}},
    )
    return sessionmaker(engine, expire_on_commit=False)


async def cloud_database(request: Request):
    # Python Workers require serialized synchronous socket/ORM operations.
    async with sql_lock:
        factory = factory_for(request.scope["env"])
        with factory() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise


def locked_job(db, job_id):
    owner_id = db.scalar(select(Job.owner_id).where(Job.id == job_id))
    if owner_id is None:
        return None
    lock_account(db, owner_id)
    return db.scalar(select(Job).where(Job.id == job_id).with_for_update())


class CloudRuntime:
    def __init__(self, env, config=None):
        self.env = env
        self.config = config or get_settings()

    async def ready(self):
        try:
            async with sql_lock:
                factory = factory_for(self.env)
                with factory() as db:
                    db.execute(text("SELECT version_num FROM sana.alembic_version"))
            return JSONResponse({"database": True, "queue_configured": bool(self.env.JOBS)})
        except Exception:
            return JSONResponse({"database": False}, 503)

    def models(self):
        return {
            "text": {"id": self.config.llm_model, "provider": "cloudflare_workers_ai"},
            "image": {"id": None, "provider": None},
        }

    def ai_status(self):
        # Binding configured is not a promise of remaining daily inference quota.
        return {
            "text": {**self.models()["text"], "status": "configured"},
            "image": {"status": "disabled"},
            "checked_at": datetime.now(UTC),
        }

    async def generate(self, job_id):
        job_id, execution = uuid.UUID(job_id), uuid.uuid4()
        async with sql_lock:
            factory = factory_for(self.env)
            with factory.begin() as db:
                job = locked_job(db, job_id)
                if not job or job.status != "queued":
                    return
                request = GenerationInput.model_validate(job.request)
                owner_id = job.owner_id
                job.status, job.execution_id, job.started_at = "processing", execution, utcnow()
        try:
            if request.include_images or request.kind == "image":
                raise AppError("image_model_not_enabled", 503)
            payload = generation_payload(request, self.config)
            payload.pop("model", None)
            payload.pop("reasoning_effort", None)
            result = await asyncio.wait_for(
                self.env.AI.run(self.config.llm_model, payload),
                timeout=self.config.llm_timeout_seconds,
            )
            try:
                content = parse_completion(result, request, self.config)
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
                raise AppError("invalid_model_output", 502) from error
            async with sql_lock:
                with factory.begin() as db:
                    job = locked_job(db, job_id)
                    if not job or job.status != "processing" or job.execution_id != execution:
                        return
                    db.add(
                        Material(
                            owner_id=owner_id,
                            job_id=job.id,
                            title=content["title"],
                            subject=request.subject,
                            topic=request.topic,
                            language=request.language,
                            kind=request.kind,
                            content=content,
                        )
                    )
                    settle(db, job, True)
                    job.status, job.finished_at = "completed", utcnow()
            logger.info("generation_completed job=%s", job_id)
        except Exception as error:
            code = error.code if isinstance(error, AppError) else "text_model_unavailable"
            async with sql_lock:
                with factory.begin() as db:
                    job = locked_job(db, job_id)
                    if job and job.status == "processing" and job.execution_id == execution:
                        settle(db, job, False)
                        job.status, job.error_code, job.finished_at = "failed", code, utcnow()
            logger.warning("generation_failed job=%s code=%s", job_id, code)

    async def dispatch_and_recover(self):
        now = utcnow()
        factory = factory_for(self.env)
        async with sql_lock:
            with factory() as db:
                ids = db.scalars(
                    select(Job.id)
                    .where(
                        or_(
                            (Job.status == "queued")
                            & (
                                Job.created_at
                                < now - timedelta(seconds=self.config.queue_timeout_seconds)
                            ),
                            (Job.status == "processing")
                            & (
                                Job.started_at
                                < now - timedelta(seconds=self.config.job_timeout_seconds + 45)
                            ),
                        )
                    )
                    .limit(30)
                ).all()
            for job_id in ids:
                with factory.begin() as db:
                    job = locked_job(db, job_id)
                    expired = job and (
                        (
                            job.status == "queued"
                            and job.created_at
                            < now - timedelta(seconds=self.config.queue_timeout_seconds)
                        )
                        or (
                            job.status == "processing"
                            and job.started_at
                            < now - timedelta(seconds=self.config.job_timeout_seconds + 45)
                        )
                    )
                    if expired:
                        settle(db, job, False)
                        job.status, job.error_code, job.finished_at = (
                            "failed",
                            "generation_timeout",
                            now,
                        )
            with factory() as db:
                pending = db.scalars(
                    select(Job.id)
                    .where(
                        Job.status == "queued",
                        or_(
                            Job.dispatched_at.is_(None),
                            Job.dispatched_at < now - timedelta(seconds=120),
                        ),
                    )
                    .order_by(Job.created_at)
                    .limit(10)
                ).all()
        for job_id in pending:
            await self.env.JOBS.send({"job_id": str(job_id)})
            async with sql_lock:
                with factory.begin() as db:
                    job = locked_job(db, job_id)
                    if job and job.status == "queued":
                        job.dispatched_at = now
