import asyncio
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from app.models import Job, Material, TokenAccount, TokenTransaction, utcnow
from app.schemas import GenerationInput
from app.services import create_job

spec = importlib.util.spec_from_file_location(
    "sana_cloud_test", Path(__file__).resolve().parents[2] / "cloudflare/src/cloud_runtime.py"
)
cloud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cloud
spec.loader.exec_module(cloud)


def prepared(factory, owner, config, key="cloud-test-0001"):
    request = GenerationInput(
        kind="quiz", language="ru", topic="Сложение", subject="Математика", length=3
    )
    with factory.begin() as db:
        job, _ = create_job(db, owner, request, key, config)
        return job.id


def runtime(factory, config, monkeypatch, generate):
    monkeypatch.setattr(cloud, "factory_for", lambda _: factory)
    # Each test runs its own loop. Keep one SQL lock per deployed isolate in production.
    monkeypatch.setattr(cloud, "sql_lock", cloud.RequestLocalLock())
    return cloud.CloudRuntime(SimpleNamespace(AI=SimpleNamespace(run=generate)), config)


def test_cloud_sql_requests_remain_serialized_after_waiter_cancellation():
    async def scenario():
        lock = cloud.RequestLocalLock()
        entered = []

        async def request(number):
            async with lock:
                entered.append(number)
                await asyncio.sleep(0.01)
                assert entered[-1] == number

        async with lock:
            canceled = asyncio.create_task(request(0))
            queued = [asyncio.create_task(request(number)) for number in range(1, 4)]
            await asyncio.sleep(0.01)
            canceled.cancel()
            import pytest

            with pytest.raises(asyncio.CancelledError):
                await canceled
            assert entered == []
        await asyncio.wait_for(asyncio.gather(*queued), timeout=1)
        assert sorted(entered) == [1, 2, 3]
        await request(4)
        assert entered[-1] == 4

    asyncio.run(scenario())


def test_cloud_sql_canceled_owner_releases_following_requests():
    async def scenario():
        lock = cloud.RequestLocalLock()
        entered = asyncio.Event()

        async def owner():
            async with lock:
                entered.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(owner())
        await entered.wait()
        task.cancel()
        import pytest

        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(1), lock:
            pass

    asyncio.run(scenario())


def test_cloud_delivery_is_idempotent_and_charges_once(factory, owner, config, quiz, monkeypatch):
    job_id = prepared(factory, owner, config)
    calls = []
    for question in quiz["questions"]:
        question["correct_answer"] = question["options"][question.pop("correct_index")]

    async def generate(model, payload):
        calls.append(model)
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(quiz)}}]}

    worker = runtime(factory, config, monkeypatch, generate)

    async def twice():
        await asyncio.gather(worker.generate(str(job_id)), worker.generate(str(job_id)))

    asyncio.run(twice())
    with factory() as db:
        assert db.get(Job, job_id).status == "completed"
        assert (
            db.scalar(select(func.count()).select_from(Material).where(Material.job_id == job_id))
            == 1
        )
        assert db.get(TokenAccount, owner.id).reserved == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(TokenTransaction)
                .where(TokenTransaction.operation_key == f"settle:{job_id}")
            )
            == 1
        )
    assert len(calls) == 1


def test_cloud_quota_or_provider_failure_refunds(factory, owner, config, monkeypatch):
    job_id = prepared(factory, owner, config)

    async def unavailable(*args):
        raise RuntimeError("private provider error")

    worker = runtime(factory, config, monkeypatch, unavailable)
    asyncio.run(worker.generate(str(job_id)))
    with factory() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(Job, job_id).error_code == "text_model_unavailable"
        assert db.get(TokenAccount, owner.id).available == 100
        assert db.get(TokenAccount, owner.id).reserved == 0


def test_cloud_outbox_retains_job_when_queue_is_down(factory, owner, config, monkeypatch):
    job_id = prepared(factory, owner, config)

    async def unavailable(*args):
        raise RuntimeError("queue unavailable")

    worker = runtime(factory, config, monkeypatch, unavailable)
    worker.env.JOBS = SimpleNamespace(send=unavailable)
    import pytest

    with pytest.raises(RuntimeError):
        asyncio.run(worker.dispatch_and_recover())
    with factory() as db:
        job = db.get(Job, job_id)
        assert job.status == "queued" and job.dispatched_at is None
        assert db.get(TokenAccount, owner.id).reserved == job.cost


def test_cloud_watchdog_refunds_abandoned_generation_once(factory, owner, config, monkeypatch):
    job_id = prepared(factory, owner, config)
    with factory.begin() as db:
        job = db.get(Job, job_id)
        job.status, job.started_at = "processing", utcnow() - timedelta(hours=3)

    async def forbidden(*args):
        raise AssertionError("Timed out jobs must not be dispatched")

    worker = runtime(factory, config, monkeypatch, forbidden)
    worker.env.JOBS = SimpleNamespace(send=forbidden)
    asyncio.run(worker.dispatch_and_recover())
    asyncio.run(worker.dispatch_and_recover())
    with factory() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(TokenAccount, owner.id).available == 100
        assert db.get(TokenAccount, owner.id).reserved == 0


def test_daily_cloud_limit_does_not_reserve_tokens_and_allows_idempotent_retry(
    factory, owner, config
):
    import pytest

    from app.errors import AppError

    config.daily_generation_limit = 1
    job_id = prepared(factory, owner, config)
    assert prepared(factory, owner, config) == job_id
    with pytest.raises(AppError, match="daily_generation_limit"):
        prepared(factory, owner, config, "cloud-second-request")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.get(TokenAccount, owner.id).reserved == db.get(Job, job_id).cost
