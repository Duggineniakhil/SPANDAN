"""Tests run against the spandan_test database in the docker-compose Postgres.

Start it first:  docker compose up -d
"""
import os

# Point the app at the test database before any app module creates its engine.
from app.config import Settings

_test_url = Settings().test_database_url
os.environ["DATABASE_URL"] = _test_url
os.environ["API_TOKEN"] = "test-token"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", _test_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=AUTH)


@pytest.fixture
def owner(client) -> dict:
    r = client.post("/api/v1/owners", json={
        "name": "Ramesh", "phone": "+919876543210", "language": "kn", "spending_limit_inr": 2500,
        "idle_windows": [{"dow": 6, "start": "09:00", "end": "14:00"}],
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def machine(client, owner) -> dict:
    r = client.post("/api/v1/machines", json={
        "owner_id": owner["id"], "name": "Main grinder motor", "motor_rpm": 2880,
        "bearing_model": "6205-2RS", "sensor_id": "replay-cwru-001",
    })
    assert r.status_code == 201, r.text
    return r.json()
