import os
import uuid

import pytest
from alembic.config import Config
from fastapi import Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from alembic import command

os.environ["SANA_ENVIRONMENT"] = "test"

from app.config import Settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.manage import seed_plans  # noqa: E402
from app.security import Identity, get_identity  # noqa: E402
from app.services import ensure_profile  # noqa: E402


@pytest.fixture(scope="session")
def pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL transaction tests")
    schema = "sana_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, pool_size=12, max_overflow=12
    )
    with engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    yield engine
    engine.dispose()
    with admin.begin() as db:
        db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def factory(pg_engine):
    with pg_engine.begin() as connection:
        tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory.begin() as db:
        seed_plans(db)
    return factory


@pytest.fixture
def owner(factory):
    with factory.begin() as db:
        return ensure_profile(db, Identity(uuid.uuid4(), "Айдана"))


@pytest.fixture
def config(tmp_path):
    return Settings(
        _env_file=None,
        environment="test",
        llm_model="test-model",
        storage_dir=tmp_path / "assets",
        model_cache_dir=tmp_path / "models",
        image_enabled=True,
        max_active_jobs=10,
    )


@pytest.fixture
def client(factory, monkeypatch, config):
    from app import main

    monkeypatch.setattr(main, "config", config)

    def database():
        with factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def identity(authorization: str = Header()):
        return Identity(uuid.UUID(authorization.removeprefix("Bearer ")), "Тестовый учитель")

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_identity] = identity
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def quiz():
    return {
        "title": "Закон Ома",
        "language": "ru",
        "kind": "quiz",
        "questions": [
            {
                "prompt": f"Вопрос {i}: сколько будет 2 + 2?",
                "options": ["3", "4"],
                "correct_index": 1,
                "explanation": "Два плюс два равно четырём.",
            }
            for i in range(3)
        ],
    }
