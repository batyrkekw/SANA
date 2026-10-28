import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import Job, Plan, Profile, Subscription, TokenAccount, TokenTransaction, utcnow
from app.schemas import GenerationInput
from app.security import Identity


def ensure_profile(db: Session, identity: Identity) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.supabase_id == identity.id))
    if profile:
        return profile
    plan = db.get(Plan, "basic")
    if not plan:
        raise AppError("plans_not_configured", 503)
    profile_id = uuid.uuid4()
    # The unique external identity serializes racing first requests across API processes.
    created = db.execute(
        insert(Profile)
        .values(
            id=profile_id,
            supabase_id=identity.id,
            display_name=identity.display_name,
            language=identity.language,
            settings={},
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["supabase_id"])
        .returning(Profile.id)
    ).scalar()
    if created:
        db.add(Subscription(profile_id=profile_id, plan_code="basic"))
        db.add(TokenAccount(profile_id=profile_id, available=plan.initial_tokens, reserved=0))
        db.add(
            TokenTransaction(
                owner_id=profile_id,
                kind="grant",
                amount=plan.initial_tokens,
                available_delta=plan.initial_tokens,
                reserved_delta=0,
                reason="welcome",
                operation_key=f"welcome:{profile_id}",
            )
        )
        db.flush()
    return db.scalar(select(Profile).where(Profile.supabase_id == identity.id))


def user_plan(db: Session, profile_id: uuid.UUID) -> Plan:
    return db.scalar(select(Plan).join(Subscription).where(Subscription.profile_id == profile_id))


def image_count(request: GenerationInput) -> int:
    if request.kind == "image":
        return request.image_count
    if request.include_images:
        return request.length if request.kind == "comic" else request.image_count
    return 0


def quote(db: Session, profile_id: uuid.UUID, request: GenerationInput, settings: Settings) -> int:
    plan = user_plan(db, profile_id)
    limits = plan.limits
    count = image_count(request)
    if request.kind not in limits["kinds"] or (count and not limits["images"]):
        raise AppError("plan_restriction", 403)
    if (
        len(request.instructions) > limits["max_prompt"]
        or request.length > limits["max_length"]
        or (request.kind == "comic" and request.length > limits["max_panels"])
        or count > min(limits["max_images"], settings.image_max_count)
    ):
        raise AppError("plan_limit", 422)
    # Length and image pixels affect the quote; identical formula is used at reservation time.
    scale = max(1, (request.length + 3) // 4)
    image_scale = max(1, (settings.image_size * settings.image_size + 512 * 512 - 1) // (512 * 512))
    base = 0 if request.kind == "image" else settings.costs[request.kind] * scale
    return base + count * settings.costs["image"] * image_scale


def lock_account(db: Session, owner_id: uuid.UUID) -> TokenAccount:
    return db.scalar(
        select(TokenAccount).where(TokenAccount.profile_id == owner_id).with_for_update()
    )


def create_job(
    db: Session, profile: Profile, request: GenerationInput, key: str, settings: Settings
) -> tuple[Job, bool]:
    # Consistent lock ordering: account -> job, including completion/cancellation/recovery.
    account = lock_account(db, profile.id)
    payload = request.model_dump()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(Job).where(Job.owner_id == profile.id, Job.idempotency_key == key))
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("idempotency_conflict", 409)
        return existing, False
    if settings.daily_generation_limit:
        # Transaction-scoped locking works with pooling and keeps plan access read-only.
        db.execute(select(func.pg_advisory_xact_lock(76155220)))
        day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = db.scalar(select(func.count()).select_from(Job).where(Job.created_at >= day))
        if daily_count >= settings.daily_generation_limit:
            raise AppError("daily_generation_limit", 429)
    recent = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.owner_id == profile.id, Job.created_at > utcnow() - timedelta(minutes=1))
    )
    if recent >= 20:
        raise AppError("too_many_jobs", 429)
    cost = quote(db, profile.id, request, settings)
    if request.kind != "image" and not settings.llm_model:
        raise AppError("text_model_not_configured", 503)
    if image_count(request) and not settings.image_enabled:
        raise AppError("image_model_not_enabled", 503)
    active = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.owner_id == profile.id, Job.status.in_(["queued", "processing"]))
    )
    if active >= settings.max_active_jobs:
        raise AppError("too_many_jobs", 429)
    if account.available < cost:
        raise AppError("insufficient_tokens", 409)
    job = Job(
        owner_id=profile.id,
        request=payload,
        request_hash=fingerprint,
        idempotency_key=key,
        cost=cost,
    )
    db.add(job)
    db.flush()
    account.available -= cost
    account.reserved += cost
    db.add(
        TokenTransaction(
            owner_id=profile.id,
            kind="reserve",
            amount=cost,
            available_delta=-cost,
            reserved_delta=cost,
            reason="generation",
            operation_key=f"reserve:{job.id}",
            job_id=job.id,
        )
    )
    db.flush()
    return job, True


def settle(db: Session, job: Job, success: bool) -> None:
    """Caller holds account and job locks. The unique key makes settlement auditable."""
    key = f"settle:{job.id}"
    if db.scalar(select(TokenTransaction.id).where(TokenTransaction.operation_key == key)):
        return
    result = db.execute(
        update(TokenAccount)
        .where(TokenAccount.profile_id == job.owner_id, TokenAccount.reserved >= job.cost)
        .values(
            reserved=TokenAccount.reserved - job.cost,
            available=TokenAccount.available + (0 if success else job.cost),
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("Token reservation invariant violated")
    db.add(
        TokenTransaction(
            owner_id=job.owner_id,
            kind="charge" if success else "refund",
            amount=job.cost,
            available_delta=0 if success else job.cost,
            reserved_delta=-job.cost,
            reason="generation_completed" if success else "generation_released",
            operation_key=key,
            job_id=job.id,
        )
    )


def cancel_job(db: Session, owner_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    lock_account(db, owner_id)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner_id).with_for_update())
    if not job:
        raise AppError("not_found", 404)
    if job.status == "cancelled":
        return job
    if job.status != "queued":
        raise AppError("cannot_cancel", 409)
    job.status = "cancelled"
    job.finished_at = utcnow()
    settle(db, job, False)
    return job
