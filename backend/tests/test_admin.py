import sys
import uuid

import pytest
from sqlalchemy import select

from app import manage
from app.models import Profile, Subscription, TokenAccount, TokenTransaction
from app.schemas import GenerationInput
from app.services import cancel_job, create_job, quote, settle

pytestmark = pytest.mark.postgres


def test_admin_grant_is_idempotent_and_capped(factory, owner, monkeypatch):
    monkeypatch.setattr(manage, "session_factory", lambda: factory)
    with factory.begin() as db:
        db.get(Subscription, owner.id).plan_code = "pro"
    operation = str(uuid.uuid4())
    args = [
        "manage",
        "grant",
        "--supabase-id",
        str(owner.supabase_id),
        "--amount",
        "900",
        "--operation-id",
        operation,
    ]
    monkeypatch.setattr(sys, "argv", args)
    manage.main()
    manage.main()
    with factory() as db:
        assert db.get(TokenAccount, owner.id).available == 1000
    monkeypatch.setattr(sys, "argv", args[:-1] + [str(uuid.uuid4())])
    with pytest.raises(SystemExit):
        manage.main()
    monkeypatch.setattr(
        sys,
        "argv",
        ["manage", "assign-plan", "--supabase-id", str(owner.supabase_id), "--plan", "basic"],
    )
    with pytest.raises(SystemExit):
        manage.main()
    with factory() as db:
        assert db.get(TokenAccount, owner.id).available == 1000
        assert db.get(Subscription, owner.id).plan_code == "pro"


@pytest.mark.parametrize("outcome", ["complete", "fail", "cancel"])
def test_admin_zero_balance_and_role_change_preserve_ledger(
    factory, owner, config, monkeypatch, outcome
):
    monkeypatch.setattr(manage, "session_factory", lambda: factory)
    monkeypatch.setattr(
        sys,
        "argv",
        ["manage", "set-admin", "--supabase-id", str(owner.supabase_id), "--admin", "true"],
    )
    manage.main()
    request = GenerationInput(kind="quiz", subject="Физика", topic="Ток", length=3)
    with factory.begin() as db:
        account = db.get(TokenAccount, owner.id)
        account.available = 0
        db.add(
            TokenTransaction(
                owner_id=owner.id,
                kind="adjustment",
                amount=100,
                available_delta=-100,
                reserved_delta=0,
                operation_key=str(uuid.uuid4()),
                reason="test",
            )
        )
    with factory.begin() as db:
        job, created = create_job(db, owner, request, "admin-test-0001", config)
        assert created and job.cost == quote(db, owner.id, request, config) == 0
        same, created = create_job(db, owner, request, "admin-test-0001", config)
        assert not created and same.id == job.id
        job_id = job.id
        db.get(Profile, owner.id).is_admin = False
    from app.models import Job
    from app.services import lock_account

    with factory.begin() as db:
        lock_account(db, owner.id)
        job = db.get(Job, job_id)
        if outcome == "cancel":
            cancel_job(db, owner.id, job_id)
        else:
            settle(db, job, outcome == "complete")
        settle(db, job, False)  # repeated delivery must never manufacture a refund
    with factory() as db:
        account = db.get(TokenAccount, owner.id)
        entries = db.scalars(
            select(TokenTransaction).where(TokenTransaction.owner_id == owner.id)
        ).all()
        assert (account.available, account.reserved) == (0, 0)
        assert (
            sum(x.available_delta for x in entries) == sum(x.reserved_delta for x in entries) == 0
        )
        assert quote(db, owner.id, request, config) == 6


def test_public_profile_cannot_enable_admin(client, factory, owner):
    headers = {"Authorization": f"Bearer {owner.supabase_id}"}
    response = client.patch(
        "/api/v1/profile",
        headers=headers,
        json={"display_name": "Учитель", "language": "ru", "is_admin": True},
    )
    assert response.status_code == 422
    assert client.get("/api/v1/me/tokens", headers=headers).json()["unlimited"] is False
    with factory.begin() as db:
        db.get(Profile, owner.id).is_admin = True
    assert client.get("/api/v1/dashboard", headers=headers).json()["tokens"]["unlimited"] is True


def test_admin_still_obeys_cloud_budget_and_plan_limits(factory, owner, config):
    from app.errors import AppError

    with factory.begin() as db:
        db.get(Profile, owner.id).is_admin = True
    config.daily_generation_limit = 1
    request = GenerationInput(kind="quiz", subject="Физика", topic="Ток", length=3)
    with factory.begin() as db:
        create_job(db, owner, request, "admin-budget-first", config)
    with factory.begin() as db, pytest.raises(AppError, match="daily_generation_limit"):
        create_job(db, owner, request, "admin-budget-second", config)
    with factory.begin() as db, pytest.raises(AppError, match="plan_limit"):
        quote(db, owner.id, request.model_copy(update={"length": 12}), config)


def test_granting_admin_does_not_change_existing_reservation(factory, owner, config):
    request = GenerationInput(kind="quiz", subject="Физика", topic="Ток", length=3)
    with factory.begin() as db:
        job, _ = create_job(db, owner, request, "paid-before-admin", config)
        assert job.cost == 6
        db.get(Profile, owner.id).is_admin = True
        settle(db, job, True)
        assert quote(db, owner.id, request, config) == 0
    with factory() as db:
        account = db.get(TokenAccount, owner.id)
        assert (account.available, account.reserved) == (94, 0)
