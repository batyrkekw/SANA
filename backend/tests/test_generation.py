import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.errors import AppError
from app.models import Asset, Job, Material, Subscription, TokenAccount, TokenTransaction, utcnow
from app.schemas import GenerationInput
from app.security import Identity
from app.services import cancel_job, create_job, ensure_profile
from app.worker import maintenance, run_job

pytestmark = pytest.mark.postgres


def request(**changes):
    return GenerationInput(kind="quiz", subject="Физика", topic="Закон Ома", **changes)


def queue(factory, owner, config, key="request-001", body=None):
    with factory.begin() as db:
        job, _ = create_job(db, owner, body or request(), key, config)
        return job.id


def assert_ledger(factory, owner):
    with factory() as db:
        account = db.get(TokenAccount, owner.id)
        entries = db.scalars(
            select(TokenTransaction).where(TokenTransaction.owner_id == owner.id)
        ).all()
        assert account.available == sum(e.available_delta for e in entries)
        assert account.reserved == sum(e.reserved_delta for e in entries)
        assert account.available >= 0 and account.reserved >= 0
        return account.available, account.reserved


def test_profile_bootstrap_once_under_race(factory):
    identity = Identity(uuid.uuid4(), "Айдана")

    def bootstrap(_):
        with factory.begin() as db:
            return ensure_profile(db, identity)

    with ThreadPoolExecutor(max_workers=8) as pool:
        profiles = list(pool.map(bootstrap, range(8)))
    assert len({profile.id for profile in profiles}) == 1
    assert assert_ledger(factory, profiles[0]) == (100, 0)


def test_parallel_idempotency_reserves_once(factory, owner, config):
    def submit(_):
        return queue(factory, owner, config)

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(submit, range(8)))
    assert len(set(ids)) == 1
    assert assert_ledger(factory, owner) == (94, 6)


def test_conflicting_repeat_rejected(factory, owner, config):
    queue(factory, owner, config)
    with pytest.raises(AppError, match="idempotency_conflict"):
        queue(factory, owner, config, body=request(length=4))
    assert assert_ledger(factory, owner) == (94, 6)


def test_concurrent_spending_never_negative(factory, owner, config):
    config = config.model_copy(update={"costs": {**config.costs, "quiz": 30}})

    def submit(i):
        try:
            return queue(factory, owner, config, key=f"request-{i:03}")
        except AppError as error:
            assert error.code == "insufficient_tokens"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(submit, range(8)))
    assert len([i for i in ids if i]) == 3
    assert assert_ledger(factory, owner) == (10, 90)


def test_success_saves_material_and_charges_once(factory, owner, config, quiz):
    class Provider:
        def generate(self, request):
            return quiz

    job_id = queue(factory, owner, config)
    run_job(job_id, text_provider=Provider(), factory=factory, config=config)
    run_job(job_id, text_provider=Provider(), factory=factory, config=config)
    with factory() as db:
        assert db.get(Job, job_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(Material)) == 1
    assert assert_ledger(factory, owner) == (94, 0)


@pytest.mark.parametrize("invalid", [False, True])
def test_provider_failure_and_invalid_output_refund(factory, owner, config, invalid):
    class Provider:
        def generate(self, request):
            if invalid:
                return {"title": "Bad"}
            raise AppError("text_model_unavailable")

    job_id = queue(factory, owner, config)
    run_job(job_id, text_provider=Provider(), factory=factory, config=config)
    run_job(job_id, text_provider=Provider(), factory=factory, config=config)
    assert assert_ledger(factory, owner) == (100, 0)
    with factory() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.scalar(select(func.count()).select_from(Material)) == 0


def test_cancel_only_owned_queued_jobs_and_no_double_refund(factory, owner, config):
    job_id = queue(factory, owner, config)
    with factory.begin() as db:
        other = ensure_profile(db, Identity(uuid.uuid4(), "Другой"))
    with factory.begin() as db, pytest.raises(AppError, match="not_found"):
        cancel_job(db, other.id, job_id)
    for _ in range(2):
        with factory.begin() as db:
            assert cancel_job(db, owner.id, job_id).status == "cancelled"
    assert assert_ledger(factory, owner) == (100, 0)


def test_dead_worker_recovers_reservation(factory, owner, config):
    job_id = queue(factory, owner, config)
    with factory.begin() as db:
        job = db.get(Job, job_id)
        job.status = "processing"
        job.started_at = utcnow() - timedelta(hours=2)
    maintenance(factory=factory, config=config, publish=lambda _: None)
    maintenance(factory=factory, config=config, publish=lambda _: None)
    assert assert_ledger(factory, owner) == (100, 0)


def test_durable_outbox_recovers_broker_failure(factory, owner, config):
    job_id = queue(factory, owner, config)

    def unavailable(_):
        raise ConnectionError()

    maintenance(factory=factory, config=config, publish=unavailable)
    with factory() as db:
        assert db.get(Job, job_id).dispatched_at is None
    sent = []
    maintenance(factory=factory, config=config, publish=sent.append)
    maintenance(factory=factory, config=config, publish=sent.append)
    assert sent == [str(job_id)]


def test_images_stored_as_files_not_database_blobs(factory, owner, config):
    from PIL import Image

    class Images:
        def generate_image(self, *args):
            return Image.new("RGB", (512, 512), "white")

        def get_model_info(self):
            return {"id": "test-only"}

    with factory.begin() as db:
        db.get(Subscription, owner.id).plan_code = "pro"
    job_id = queue(
        factory, owner, config, body=GenerationInput(kind="image", subject="Физика", topic="Ток")
    )
    run_job(job_id, images=Images(), factory=factory, config=config)
    with factory() as db:
        asset = db.scalar(select(Asset))
        assert asset.owner_id == owner.id
        assert (config.storage_dir / asset.storage_key).is_file()
        assert asset.mime_type == "image/png"
    assert assert_ledger(factory, owner) == (90, 0)


def test_plan_and_configuration_fail_before_reserving(factory, owner, config):
    with pytest.raises(AppError, match="plan_restriction"):
        queue(
            factory,
            owner,
            config,
            body=GenerationInput(kind="image", subject="Физика", topic="Ток"),
        )
    with pytest.raises(AppError, match="text_model_not_configured"):
        queue(factory, owner, config.model_copy(update={"llm_model": ""}))
    assert assert_ledger(factory, owner) == (100, 0)
