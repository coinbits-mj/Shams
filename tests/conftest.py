# tests/conftest.py
from __future__ import annotations

import os
import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", os.environ.get("DATABASE_URL", ""))

@pytest.fixture(scope="session")
def setup_db():
    """Ensure tables exist before running tests that need the DB."""
    if not TEST_DATABASE_URL:
        pytest.skip("No DATABASE_URL set")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import db
    db.init_pool()
    import memory
    memory.ensure_tables()
    yield
    db.close_pool()
