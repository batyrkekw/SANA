import asyncio
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Job, Material, TokenAccount, TokenTransaction, utcnow
from app.schemas import GenerationInput
from app.services import create_job

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare/src"))
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


def test_cloud_disconnect_keeps_transaction_cleanup_alive():
    async def scenario():
        lock = cloud.RequestLocalLock()
        entered, complete = asyncio.Event(), asyncio.Event()
        retained, finished = [], []

        async def application():
            async with lock:
                entered.set()
                await complete.wait()
                finished.append("transaction closed")

        request = asyncio.create_task(cloud.complete_request(application(), retained.append))
        await entered.wait()
        request.cancel()
        import pytest

        with pytest.raises(asyncio.CancelledError):
            await request
        assert len(retained) == 1 and not retained[0].done()
        complete.set()
        await asyncio.wait_for(retained[0], timeout=1)
        assert finished == ["transaction closed"]
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


@pytest.mark.parametrize(
    "message,code",
    [
        ("private provider error", "text_model_unavailable"),
        (
            "you have used up your daily free allocation of 10,000 neurons",
            "ai_daily_quota_exhausted",
        ),
    ],
)
def test_cloud_quota_or_provider_failure_refunds(
    factory, owner, config, monkeypatch, message, code
):
    job_id = prepared(factory, owner, config)

    async def unavailable(*args):
        raise RuntimeError(message)

    worker = runtime(factory, config, monkeypatch, unavailable)
    asyncio.run(worker.generate(str(job_id)))
    with factory() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(Job, job_id).error_code == code
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


def test_illustrated_comic_pipeline(factory, owner, config, monkeypatch):
    from app.errors import AppError
    from app.models import Asset

    config.runtime = "cloudflare"
    req = GenerationInput(
        kind="comic", include_images=True, subject="Физика", topic="Свет", length=4
    )
    content = {
        "title": "Свет",
        "kind": "comic",
        "language": "ru",
        "objectives": ["Увидеть свет"],
        "panels": [
            {
                "scene": "Опыт",
                "narration": "Проверяем лампу.",
                "dialogue": "Смотри!",
                "image_prompt": f"A lamp lights up a white wall in scene {i}",
            }
            for i in range(4)
        ],
    }

    async def text_model(*_):
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    worker = runtime(factory, config, monkeypatch, text_model)
    storage, calls = {}, []

    class KV:
        async def delete(self, key):
            storage.pop(key, None)

    worker.env.COMIC_ART = KV()
    fail = True

    async def draw(ai, briefs, style):
        calls.append(briefs)
        if fail:
            raise AppError("image_inference_failed", 503)
        if not fail and len(calls) == 1:
            raise cloud.TransientRenderError("image_inference_failed", 503)
        return b"one complete page", "image/jpeg"

    async def put(_, key, image):
        storage[key] = image

    monkeypatch.setattr(cloud, "render_page", draw)
    monkeypatch.setattr(cloud, "store_panel", put)

    def run(key):
        with factory.begin() as db:
            job, _ = create_job(db, owner, req, key, config)
            assert job.cost == 22
            job_id = job.id
        asyncio.run(worker.generate(str(job_id)))
        asyncio.run(worker.generate(str(job_id)))
        return job_id

    failed = run("partial-pilot")
    with factory() as db:
        assert db.get(Job, failed).status == "failed"
        assert db.get(TokenAccount, owner.id).available == 100
        assert not storage and db.scalar(select(func.count()).select_from(Asset)) == 0
    fail = False
    calls.clear()
    done = run("complete-pilot")
    assert len(calls) == 2  # one bounded transient retry, not four image requests
    assert all(len(briefs) == 4 for briefs in calls)
    with factory() as db:
        material = db.scalar(select(Material).where(Material.job_id == done))
        assets = sorted(db.scalars(select(Asset)).all(), key=lambda a: a.metadata_json["index"])
        assert material.owner_id == owner.id and len(assets) == len(storage) == 1
        assert storage[assets[0].storage_key][0] == b"one complete page"
        assert assets[0].metadata_json["layout"] == "comic_page"
        assert assets[0].metadata_json["panel_count"] == 4
        assert len(material.content["panels"]) == 4
        assert all(a.material_id == material.id and a.owner_id == owner.id for a in assets)
        account = db.get(TokenAccount, owner.id)
        assert (account.available, account.reserved) == (78, 0)


def test_cloud_assets_obey_ownership_and_deletion(client, factory, monkeypatch, config, quiz):
    from app import main
    from app.models import Asset, Profile

    config.runtime = "cloudflare"
    calls = []

    class Store:
        async def read_panel(self, key):
            calls.append(("read", key))
            return b"image"

        async def delete_panels(self, keys):
            calls.append(("delete", keys))

    monkeypatch.setattr(main.app.state, "cloud", Store(), raising=False)
    # Source profile is created through the same authenticated dependency as other resources.
    from uuid import UUID, uuid4

    actor = str(uuid4())
    headers = {"Authorization": f"Bearer {actor}"}
    client.get("/api/v1/profile", headers=headers)
    with factory.begin() as db:
        owner_id = db.scalar(select(Profile.id).where(Profile.supabase_id == UUID(actor)))
        material = Material(
            owner_id=owner_id,
            subject="Наука",
            topic="Урок",
            kind="quiz",
            language="ru",
            title="Урок",
            content=quiz,
        )
        db.add(material)
        db.flush()
        asset = Asset(
            owner_id=owner_id,
            material_id=material.id,
            storage_key="private/key",
            mime_type="image/jpeg",
            size=5,
            metadata_json={"index": 0},
        )
        db.add(asset)
        db.flush()
        asset_id, mid = asset.id, material.id
    assert (
        client.get(
            f"/api/v1/assets/{asset_id}", headers={"Authorization": f"Bearer {uuid4()}"}
        ).status_code
        == 404
    )
    response = client.get(f"/api/v1/assets/{asset_id}", headers=headers)
    assert response.content == b"image" and "no-store" in response.headers["cache-control"]
    assert client.delete(f"/api/v1/materials/{mid}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/assets/{asset_id}", headers=headers).status_code == 404
    assert calls == [("read", "private/key"), ("delete", ["private/key"])]


@pytest.mark.parametrize("brief", ["Белый корешок", "WhiteRootGrowingFromBeanSeedInPetriDish"])
def test_art_briefs_repair_once_and_keep_dialogue(brief):
    import pytest
    from comic_art import visual_briefs

    from app.errors import AppError

    script = {"panels": [{"image_prompt": brief, "dialogue": "Вижу корешок!"}]}
    calls = []

    async def run(_, payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"prompts":["A white root grows from a bean on damp paper"]}'
                    }
                }
            ]
        }

    assert asyncio.run(visual_briefs(SimpleNamespace(run=run), "qwen", script)) == [
        "A white root grows from a bean on damp paper"
    ]
    assert len(calls) == 1 and script["panels"][0]["dialogue"] == "Вижу корешок!"

    async def invalid(*_):
        return {"choices": [{"message": {"content": '{"prompts":[]}'}}]}

    with pytest.raises(AppError, match="invalid_model_output"):
        asyncio.run(visual_briefs(SimpleNamespace(run=invalid), "qwen", script))


def test_image_provider_retry_does_not_retry_quota_or_safety_failures():
    from comic_art import TransientRenderError, provider_error

    assert isinstance(provider_error(TimeoutError()), TransientRenderError)
    assert isinstance(provider_error(RuntimeError("503 Service Unavailable")), TransientRenderError)
    quota = provider_error(
        RuntimeError("you have used up your daily free allocation of 10,000 neurons")
    )
    assert quota.code == "ai_daily_quota_exhausted" and quota.status == 429
    for message in [
        "429 quota exceeded",
        "content safety policy",
        "model unavailable",
        "403 forbidden",
    ]:
        assert not isinstance(provider_error(RuntimeError(message)), TransientRenderError)
