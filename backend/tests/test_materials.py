import uuid

import pytest
from sqlalchemy import event

from app.models import Asset, Job, Material

pytestmark = pytest.mark.postgres


def test_profiles_materials_and_ownership(client, quiz):
    alice = {"Authorization": f"Bearer {uuid.uuid4()}"}
    bob = {"Authorization": f"Bearer {uuid.uuid4()}"}
    first = client.get("/api/v1/profile", headers=alice)
    assert first.status_code == 200
    assert client.get("/api/v1/profile", headers=alice).json()["id"] == first.json()["id"]
    assert client.get("/api/v1/me/tokens", headers=alice).json() == {
        "available": 100,
        "reserved": 0,
    }
    assert client.get("/api/v1/profile", headers=bob).json()["id"] != first.json()["id"]
    invalid = client.patch(
        "/api/v1/profile",
        headers=alice,
        json={"display_name": "Test", "language": "ru", "user_id": str(uuid.uuid4())},
    )
    assert invalid.status_code == 422
    created = client.post(
        "/api/v1/materials",
        headers=alice,
        json={"subject": "Физика", "topic": "Ток", "content": quiz},
    )
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    assert (
        client.get(f"/api/v1/materials/{mid}", headers=alice).json()["content"]["title"]
        == quiz["title"]
    )
    for method in ("get", "delete"):
        assert getattr(client, method)(f"/api/v1/materials/{mid}", headers=bob).status_code == 404
    assert (
        client.patch(
            f"/api/v1/materials/{mid}", headers=bob, json={"title": "Hijacked"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/materials", headers=bob).json()["total"] == 0
    assert (
        client.patch(
            f"/api/v1/materials/{mid}", headers=alice, json={"title": "Переименовано"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/materials?search=Переименовано", headers=alice).json()["total"] == 1
    assert client.delete(f"/api/v1/materials/{mid}", headers=alice).status_code == 204
    assert client.get(f"/api/v1/materials/{mid}", headers=alice).status_code == 404


def test_generations_api_does_not_trust_client_cost_or_owner(client):
    headers = {"Authorization": f"Bearer {uuid.uuid4()}", "Idempotency-Key": "client-request-01"}
    body = {"kind": "quiz", "subject": "Физика", "topic": "Ток", "length": 3}
    assert (
        client.post("/api/v1/generations", headers=headers, json={**body, "cost": 0}).status_code
        == 422
    )
    first = client.post("/api/v1/generations", headers=headers, json=body)
    assert first.status_code == 202, first.text
    assert first.json()["cost"] == 6
    assert (
        client.post("/api/v1/generations", headers=headers, json=body).json()["id"]
        == first.json()["id"]
    )
    assert client.get("/api/v1/me/tokens", headers=headers).json()["available"] == 94
    stranger = {"Authorization": f"Bearer {uuid.uuid4()}"}
    assert (
        client.get(f"/api/v1/generations/{first.json()['id']}", headers=stranger).status_code == 404
    )
    assert client.get(f"/api/v1/assets/{uuid.uuid4()}", headers=stranger).status_code == 404


def test_large_request_rejected_without_echoing_body(client):
    response = client.post(
        "/api/v1/generations", content=b"x" * 70000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert "xxxx" not in response.text


def test_list_query_count_stays_bounded_and_attachments_belong_to_owner(
    client, factory, owner, pg_engine, quiz
):
    headers = {"Authorization": f"Bearer {owner.supabase_id}"}
    with factory.begin() as db:
        for i in range(12):
            job = Job(
                owner_id=owner.id,
                idempotency_key=f"list-{i}",
                request_hash="x",
                request={},
                status="completed",
                cost=6,
            )
            db.add(job)
            db.flush()
            material = Material(
                owner_id=owner.id,
                job_id=job.id,
                title=f"Quiz {i}",
                subject="Math",
                topic="Addition",
                language="ru",
                kind="quiz",
                content=quiz,
            )
            db.add(material)
            db.flush()
            db.add(
                Asset(
                    owner_id=owner.id,
                    material_id=material.id,
                    storage_key=f"test/{i}.png",
                    size=10,
                    metadata_json={"index": i},
                )
            )
    statements = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(pg_engine, "before_cursor_execute", count)
    try:
        page = client.get("/api/v1/materials", headers=headers)
        assert page.status_code == 200
        assert len(statements) <= 5
        assert page.json()["total"] == 12
        assert all(len(row["assets"]) == 1 and "content" not in row for row in page.json()["items"])
        assert len({row["assets"][0]["id"] for row in page.json()["items"]}) == 12
        statements.clear()
        overview = client.get("/api/v1/dashboard", headers=headers)
        assert overview.status_code == 200
        assert len(statements) <= 5
        assert overview.json()["material_count"] == 12
        statements.clear()
        jobs = client.get("/api/v1/generations", headers=headers)
        assert jobs.status_code == 200
        assert len(statements) <= 3
        assert all(row["material_id"] for row in jobs.json()["items"])
    finally:
        event.remove(pg_engine, "before_cursor_execute", count)
    outsider = {"Authorization": f"Bearer {uuid.uuid4()}"}
    assert client.get("/api/v1/materials", headers=outsider).json()["items"] == []
    history = client.get("/api/v1/me/tokens/transactions", headers=headers).json()
    assert history["tokens"] == {"available": 100, "reserved": 0}
