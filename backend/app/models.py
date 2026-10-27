import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Record:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Plan(Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[dict] = mapped_column(JSON)
    initial_tokens: Mapped[int]
    limits: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (CheckConstraint("initial_tokens >= 0"),)


class Profile(Record, Base):
    __tablename__ = "profiles"
    supabase_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(2), default="ru")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("language IN ('ru', 'kk')"),)


class Subscription(Base):
    __tablename__ = "user_subscriptions"
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TokenAccount(Base):
    __tablename__ = "token_accounts"
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    available: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint("available >= 0"), CheckConstraint("reserved >= 0"))


class Job(Record, Base):
    __tablename__ = "generation_jobs"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    cost: Mapped[int]
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_id: Mapped[uuid.UUID | None]
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key"),
        CheckConstraint("cost > 0"),
        CheckConstraint("status IN ('queued','processing','completed','failed','cancelled')"),
        Index("ix_jobs_dispatch", "status", "dispatched_at"),
    )


class TokenTransaction(Record, Base):
    __tablename__ = "token_transactions"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int]
    available_delta: Mapped[int]
    reserved_delta: Mapped[int]
    reason: Mapped[str] = mapped_column(String(80))
    operation_key: Mapped[str] = mapped_column(String(150), unique=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_jobs.id"))
    __table_args__ = (
        CheckConstraint("kind IN ('grant','reserve','charge','refund','adjustment')"),
        CheckConstraint("amount >= 0"),
    )


class Material(Record, Base):
    __tablename__ = "educational_materials"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_jobs.id"), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(2))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ready")
    content: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("language IN ('ru','kk')"),
        CheckConstraint("kind IN ('lesson','quiz','comic','flashcards','image')"),
        Index("ix_materials_owner_created", "owner_id", "created_at"),
    )


class Asset(Record, Base):
    __tablename__ = "generated_assets"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"), index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("educational_materials.id"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    mime_type: Mapped[str] = mapped_column(String(80), default="image/png")
    size: Mapped[int]
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("size > 0"),)
