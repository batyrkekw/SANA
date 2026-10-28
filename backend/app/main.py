import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import ROOT, get_settings
from app.db import get_db, get_engine
from app.errors import AppError
from app.models import Asset, Job, Material, Plan, Profile, TokenAccount, TokenTransaction, utcnow
from app.schemas import GenerationInput, MaterialInput, MaterialUpdate, ProfileUpdate
from app.security import Identity, get_identity
from app.services import cancel_job, create_job, ensure_profile, quote, user_plan

logger = logging.getLogger("sana.api")
config = get_settings()


async def upkeep():
    from app.worker import maintenance

    while True:
        try:
            await asyncio.to_thread(maintenance)
        except Exception:
            logger.warning("maintenance_unavailable: check database, migrations and Redis")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app):
    task = (
        asyncio.create_task(upkeep())
        if config.environment != "test" and config.runtime == "local"
        else None
    )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="SANA API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if config.environment != "production" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.environment != "production" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


class BodyLimitMiddleware:
    def __init__(self, application, limit):
        self.application, self.limit = application, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.application(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"error": {"code": "request_too_large"}}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.application(scope, replay, send)


# Middleware keyword must match the ASGI constructor's app parameter.
class RequestLimit(BodyLimitMiddleware):
    def __init__(self, app, limit):
        super().__init__(app, limit)


app.add_middleware(RequestLimit, limit=config.max_request_bytes)


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def application_error(_request, error):
    return JSONResponse(
        {"error": {"code": error.code}},
        error.status,
        headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else None,
    )


@app.exception_handler(RequestValidationError)
async def invalid_input(_request, error):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "fields": [".".join(map(str, issue["loc"])) for issue in error.errors()],
            }
        },
        422,
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _error):
    logger.error("database_unavailable: inspect configuration and migration status")
    return JSONResponse({"error": {"code": "database_unavailable"}}, 503)


@app.exception_handler(Exception)
async def unexpected_error(_request, _error):
    logger.error("unexpected_request_error")
    return JSONResponse({"error": {"code": "internal_error"}}, 500)


DB = Annotated[Session, Depends(get_db, scope="function")]


def current_profile(db: DB, identity: Annotated[Identity, Depends(get_identity)]) -> Profile:
    return ensure_profile(db, identity)


User = Annotated[Profile, Depends(current_profile)]


def plan_data(plan):
    return {
        "code": plan.code,
        "name": plan.name,
        "initial_tokens": plan.initial_tokens,
        "limits": plan.limits,
        "development_limits": True,
    }


def profile_data(profile):
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "language": profile.language,
        "created_at": profile.created_at,
    }


def material_data(db, material, detail=False):
    assets = db.scalars(
        select(Asset).where(Asset.material_id == material.id).order_by(Asset.created_at)
    ).all()
    result = {
        "id": material.id,
        "title": material.title,
        "subject": material.subject,
        "topic": material.topic,
        "language": material.language,
        "kind": material.kind,
        "created_at": material.created_at,
        "status": material.status,
        "assets": [
            {
                "id": asset.id,
                "url": f"/api/v1/assets/{asset.id}",
                "index": asset.metadata_json.get("index", 0),
            }
            for asset in assets
        ],
    }
    if detail:
        result["content"] = material.content
        result["teacher_review_required"] = True
    return result


def job_data(db, job):
    material_id = db.scalar(select(Material.id).where(Material.job_id == job.id))
    return {
        "id": job.id,
        "status": job.status,
        "cost": job.cost,
        "request": job.request,
        "error_code": job.error_code,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "material_id": material_id,
        "can_cancel": job.status == "queued",
    }


def owned(db, model, object_id, owner_id):
    value = db.scalar(select(model).where(model.id == object_id, model.owner_id == owner_id))
    if value is None:
        raise AppError("not_found", 404)
    return value


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    if config.runtime == "cloudflare":
        return await app.state.cloud.ready()
    from redis import Redis

    checks = {"database": False, "redis": False}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT version_num FROM alembic_version"))
            checks["database"] = True
    except Exception:
        pass
    try:
        checks["redis"] = bool(
            Redis.from_url(
                config.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
            ).ping()
        )
    except Exception:
        pass
    return JSONResponse(checks, 200 if all(checks.values()) else 503)


@app.get("/api/v1/config")
def public_config():
    return {
        "auth_configured": config.auth_configured,
        "supabase_url": config.supabase_url,
        "supabase_publishable_key": config.supabase_publishable_key,
        "google_oauth_enabled": config.google_oauth_enabled,
        "api_base": "/api/v1",
    }


@app.get("/api/v1/profile")
def get_profile(user: User):
    return profile_data(user)


@app.patch("/api/v1/profile")
def patch_profile(body: ProfileUpdate, user: User, db: DB):
    user.display_name, user.language = body.display_name, body.language
    db.flush()
    return profile_data(user)


@app.get("/api/v1/plans")
def plans(db: DB):
    return [plan_data(plan) for plan in db.scalars(select(Plan).order_by(Plan.initial_tokens))]


@app.get("/api/v1/me/plan")
def my_plan(user: User, db: DB):
    return plan_data(user_plan(db, user.id))


@app.get("/api/v1/me/tokens")
def balance(user: User, db: DB):
    account = db.get(TokenAccount, user.id)
    return {"available": account.available, "reserved": account.reserved}


@app.get("/api/v1/me/tokens/transactions")
def transactions(user: User, db: DB, page: int = Query(1, ge=1, le=100000)):
    statement = select(TokenTransaction).where(TokenTransaction.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    entries = db.scalars(
        statement.order_by(TokenTransaction.created_at.desc(), TokenTransaction.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return {
        "total": total,
        "page": page,
        "page_size": 20,
        "items": [
            {
                "id": entry.id,
                "kind": entry.kind,
                "amount": entry.amount,
                "available_delta": entry.available_delta,
                "reserved_delta": entry.reserved_delta,
                "reason": entry.reason,
                "job_id": entry.job_id,
                "created_at": entry.created_at,
            }
            for entry in entries
        ],
    }


@app.get("/api/v1/materials")
def materials(
    user: User,
    db: DB,
    search: str = Query("", max_length=100),
    subject: str = Query("", max_length=100),
    kind: str = Query("", max_length=20),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1, le=100000),
):
    statement = select(Material).where(Material.owner_id == user.id)
    if search:
        statement = statement.where(Material.title.icontains(search, autoescape=True))
    if subject:
        statement = statement.where(Material.subject == subject)
    if kind:
        statement = statement.where(Material.kind == kind)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(
        statement.order_by(
            Material.created_at.desc() if order == "desc" else Material.created_at.asc(),
            Material.id,
        )
        .offset((page - 1) * 12)
        .limit(12)
    ).all()
    subjects = db.scalars(
        select(Material.subject).where(Material.owner_id == user.id).distinct()
    ).all()
    return {
        "items": [material_data(db, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": 12,
        "subjects": sorted(subjects),
    }


@app.post("/api/v1/materials", status_code=201)
def add_material(body: MaterialInput, user: User, db: DB):
    if body.content.kind not in user_plan(db, user.id).limits["kinds"]:
        raise AppError("plan_restriction", 403)
    material = Material(
        owner_id=user.id,
        title=body.content.title,
        subject=body.subject,
        topic=body.topic,
        language=body.content.language,
        kind=body.content.kind,
        content=body.content.model_dump(),
    )
    db.add(material)
    db.flush()
    return material_data(db, material, True)


@app.get("/api/v1/materials/{material_id}")
def read_material(material_id: uuid.UUID, user: User, db: DB):
    return material_data(db, owned(db, Material, material_id, user.id), True)


@app.patch("/api/v1/materials/{material_id}")
def rename_material(material_id: uuid.UUID, body: MaterialUpdate, user: User, db: DB):
    material = owned(db, Material, material_id, user.id)
    material.title, material.updated_at = body.title, utcnow()
    material.content = {**material.content, "title": body.title}
    db.flush()
    return material_data(db, material, True)


@app.delete("/api/v1/materials/{material_id}", status_code=204)
def remove_material(material_id: uuid.UUID, user: User, db: DB):
    material = owned(db, Material, material_id, user.id)
    keys = db.scalars(select(Asset.storage_key).where(Asset.material_id == material.id)).all()
    db.execute(delete(Asset).where(Asset.material_id == material.id))
    db.delete(material)
    db.commit()
    if not keys:
        return
    from app.storage import LocalStorageProvider

    for key in keys:
        try:
            LocalStorageProvider(config.storage_dir).delete(key)
        except OSError:
            logger.warning("asset_cleanup_pending after material deletion")


@app.get("/api/v1/assets/{asset_id}")
def read_asset(asset_id: uuid.UUID, user: User, db: DB):
    if config.runtime == "cloudflare":
        raise AppError("image_model_not_enabled", 503)
    from app.storage import LocalStorageProvider

    asset = owned(db, Asset, asset_id, user.id)
    path = LocalStorageProvider(config.storage_dir).resolve(asset.storage_key)
    if not path.is_file():
        raise AppError("not_found", 404)
    return FileResponse(
        path, media_type=asset.mime_type, headers={"Cache-Control": "private, no-store"}
    )


@app.get("/api/v1/dashboard")
def dashboard(user: User, db: DB):
    return {
        "profile": profile_data(user),
        "plan": plan_data(user_plan(db, user.id)),
        "tokens": balance(user, db),
        "material_count": db.scalar(
            select(func.count()).select_from(Material).where(Material.owner_id == user.id)
        ),
        "recent_materials": [
            material_data(db, material)
            for material in db.scalars(
                select(Material)
                .where(Material.owner_id == user.id)
                .order_by(Material.created_at.desc())
                .limit(4)
            )
        ],
    }


@app.post("/api/v1/generations/quote")
def generation_quote(body: GenerationInput, user: User, db: DB):
    return {"cost": quote(db, user.id, body, config), "development_pricing": True}


@app.post("/api/v1/generations", status_code=202)
def start_generation(
    body: GenerationInput,
    user: User,
    db: DB,
    idempotency_key: Annotated[
        str, Header(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    job, _created = create_job(db, user, body, idempotency_key, config)
    # Committed job rows are the durable outbox; an unavailable broker cannot lose the job.
    db.commit()
    logger.info("generation_queued job=%s", job.id)
    return job_data(db, job)


@app.get("/api/v1/generations")
def generations(user: User, db: DB, page: int = Query(1, ge=1, le=100000)):
    statement = select(Job).where(Job.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    jobs = db.scalars(statement.order_by(Job.created_at.desc()).offset((page - 1) * 20).limit(20))
    return {
        "items": [job_data(db, job) for job in jobs],
        "total": total,
        "page": page,
        "page_size": 20,
    }


@app.get("/api/v1/generations/{job_id}")
def generation(job_id: uuid.UUID, user: User, db: DB):
    return job_data(db, owned(db, Job, job_id, user.id))


@app.post("/api/v1/generations/{job_id}/cancel")
def cancel(job_id: uuid.UUID, user: User, db: DB):
    return job_data(db, cancel_job(db, user.id, job_id))


@app.get("/api/v1/ai/status")
def ai_status(_user: User):
    if config.runtime == "cloudflare":
        return app.state.cloud.ai_status()
    from app.ai import LocalDiffusersProvider, LocalLLMProvider

    return {
        "text": LocalLLMProvider(config).health_check(),
        "image": LocalDiffusersProvider(config).health_check(),
        "checked_at": datetime.now(UTC),
    }


@app.get("/api/v1/ai/models")
def models(_user: User):
    if config.runtime == "cloudflare":
        return app.state.cloud.models()
    from app.ai import LocalDiffusersProvider

    return {
        "text": {"id": config.llm_model or None, "provider": "local_openai_compatible"},
        "image": LocalDiffusersProvider(config).get_model_info(),
    }


if (ROOT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
