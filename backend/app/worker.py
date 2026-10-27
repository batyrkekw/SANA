import logging
import time
import uuid
from datetime import timedelta

from celery import Celery
from sqlalchemy import or_, select

from app.ai import LocalLLMProvider, image_provider
from app.config import get_settings
from app.db import session_factory
from app.errors import AppError
from app.models import Asset, Job, Material, utcnow
from app.schemas import EducationalContent, GenerationInput, validate_result
from app.services import image_count, lock_account, settle
from app.storage import LocalStorageProvider

logger = logging.getLogger("sana.worker")
settings = get_settings()
celery_app = Celery("sana", broker=settings.redis_url.get_secret_value())
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.job_timeout_seconds,
    task_time_limit=settings.job_timeout_seconds + 30,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={
        "visibility_timeout": settings.job_timeout_seconds + 120,
        "socket_timeout": 3,
        "socket_connect_timeout": 3,
    },
    task_publish_retry=False,
)


def locked_job(db, job_id):
    owner_id = db.scalar(select(Job.owner_id).where(Job.id == job_id))
    if owner_id is None:
        return None
    lock_account(db, owner_id)
    return db.scalar(select(Job).where(Job.id == job_id).with_for_update())


@celery_app.task(name="sana.generate")
def generate(job_id: str) -> None:
    run_job(uuid.UUID(job_id))


def run_job(job_id: uuid.UUID, text_provider=None, images=None, factory=None, config=None) -> None:
    config = config or get_settings()
    factory = factory or session_factory()
    execution = uuid.uuid4()
    with factory.begin() as db:
        job = locked_job(db, job_id)
        if not job or job.status != "queued":
            return
        job.status, job.execution_id, job.started_at = "processing", execution, utcnow()
        request = GenerationInput.model_validate(job.request)
        owner_id = job.owner_id
    start = time.monotonic()
    deadline = start + config.job_timeout_seconds
    logger.info("generation_started job=%s", job_id)
    storage = LocalStorageProvider(config.storage_dir)
    saved = []
    persisted = False
    try:
        if request.kind == "image":
            content = EducationalContent(
                title=request.topic, language=request.language, kind="image"
            ).model_dump()
        else:
            content = (text_provider or LocalLLMProvider(config)).generate(request)
            content = validate_result(content, request, config.max_result_bytes)
        count = image_count(request)
        prompts = (
            [panel["image_prompt"] for panel in content.get("panels", [])]
            if request.kind == "comic"
            else []
        )
        if count:
            provider = images or image_provider()
            for index in range(count):
                prompt = (
                    prompts[index]
                    if prompts
                    else f"{request.subject}: {request.topic}. {request.instructions}"
                )
                image = provider.generate_image(
                    prompt, request.style, request.aspect_ratio, deadline
                )
                key, size = storage.save_image(owner_id, image)
                saved.append((key, size, provider.get_model_info()))
        if time.monotonic() > deadline:
            raise AppError("generation_timeout", 504)
        with factory.begin() as db:
            job = locked_job(db, job_id)
            # A watchdog may have released the reservation while inference was running.
            if job.status != "processing" or job.execution_id != execution:
                return
            material = Material(
                owner_id=owner_id,
                job_id=job.id,
                title=content["title"],
                subject=request.subject,
                topic=request.topic,
                language=request.language,
                kind=request.kind,
                content=content,
            )
            db.add(material)
            db.flush()
            for index, (key, size, metadata) in enumerate(saved):
                db.add(
                    Asset(
                        owner_id=owner_id,
                        material_id=material.id,
                        storage_key=key,
                        size=size,
                        metadata_json={**metadata, "index": index},
                    )
                )
            settle(db, job, True)
            job.status, job.finished_at = "completed", utcnow()
        persisted = True
        logger.info("generation_completed job=%s duration=%.2f", job_id, time.monotonic() - start)
    except Exception as error:
        code = error.code if isinstance(error, AppError) else "generation_failed"
        with factory.begin() as db:
            job = locked_job(db, job_id)
            if job.status == "processing" and job.execution_id == execution:
                settle(db, job, False)
                job.status, job.error_code, job.finished_at = "failed", code, utcnow()
        # Avoid exception strings: providers may include prompts or authorization headers.
        logger.warning(
            "generation_failed job=%s code=%s duration=%.2f", job_id, code, time.monotonic() - start
        )
    finally:
        if not persisted:
            for key, _, _ in saved:
                try:
                    storage.delete(key)
                except OSError:
                    logger.warning("asset_cleanup_pending job=%s", job_id)


def maintenance(factory=None, config=None, publish=None) -> None:
    """Postgres outbox + watchdog, called by the API independently of worker capacity."""
    factory = factory or session_factory()
    config = config or get_settings()
    publish = publish or generate.delay
    now = utcnow()
    with factory() as db:
        ids = db.scalars(
            select(Job.id).where(Job.status.in_(["queued", "processing"])).limit(200)
        ).all()
    for job_id in ids:
        with factory.begin() as db:
            job = locked_job(db, job_id)
            if not job or job.status not in ("queued", "processing"):
                continue
            expired = job.status == "processing" and job.started_at < now - timedelta(
                seconds=config.job_timeout_seconds + 45
            )
            expired = expired or (
                job.status == "queued"
                and job.created_at < now - timedelta(seconds=config.queue_timeout_seconds)
            )
            if expired:
                settle(db, job, False)
                job.status, job.error_code, job.finished_at = "failed", "generation_timeout", now
                logger.warning("generation_recovered job=%s", job_id)
    with factory.begin() as db:
        jobs = db.scalars(
            select(Job)
            .where(
                Job.status == "queued",
                or_(Job.dispatched_at.is_(None), Job.dispatched_at < now - timedelta(seconds=60)),
            )
            .order_by(Job.created_at)
            .limit(30)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            try:
                publish(str(job.id))
            except Exception:
                logger.warning("queue_unavailable pending jobs retained")
                break
            job.dispatched_at = now
