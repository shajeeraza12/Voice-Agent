"""Tests run against a throwaway SQLite file. DATABASE_URL must be set before the app is imported."""
import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["VAPI_WEBHOOK_SECRET"] = ""
os.environ["API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_patient():
    return {
        "first_name": "Jane", "last_name": "Doe", "date_of_birth": "04/12/1988", "sex": "Female",
        "phone_number": "415-555-0142", "address_line_1": "742 Evergreen Terrace",
        "city": "Springfield", "state": "IL", "zip_code": "62704",
    }
