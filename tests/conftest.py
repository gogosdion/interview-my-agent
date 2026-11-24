import os
import tempfile

# Settings are read at import time, so configure the test environment first.
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["LLM_MODE"] = "fake"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["MAX_DAILY_MESSAGES"] = "100000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    from app import limits
    limits.reset()
    with TestClient(app) as c:
        yield c
