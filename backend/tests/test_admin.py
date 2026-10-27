import sys
import uuid

import pytest

from app import manage
from app.models import Subscription, TokenAccount

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
