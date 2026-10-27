import uuid

import pytest

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
