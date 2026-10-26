import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="los-engine-test-")
os.environ["ENGINE_DATABASE_URL"] = "sqlite:///" + os.path.join(_tmp, "test.db")
os.environ["ENGINE_INTERNAL_SECRET"] = "test-secret"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import engine.auth as auth  # noqa: E402
from engine import seed as seed_mod  # noqa: E402
from engine.api.app import create_app  # noqa: E402
from engine.db import SessionLocal  # noqa: E402
from engine.models import ApiKey, Base  # noqa: E402
from engine.db import engine as db_engine  # noqa: E402
from engine.auth import hash_key  # noqa: E402


FAKE_OWNER = {"id": "owner-user-1", "email": "laurel@example.com"}

SAMPLE_HTML = """<html><head>
<title>Bluebonnet Dental — Family Dentist in Houston</title>
<meta name="description" content="Bluebonnet Dental offers family, cosmetic and emergency dentistry in Houston, TX.">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body><h1>Bluebonnet Dental</h1>
<p>Call us at (713) 555-0182 or email hello@bluebonnetdental.example for appointments. </p>
<p>Bluebonnet Dental has served Houston families since 2010 with gentle care.</p>
</body></html>"""


@pytest.fixture(autouse=True)
def isolate_skills_dir(tmp_path, monkeypatch):
    """Never let tests write into the real skills/ directory or git repo."""
    import shutil

    import engine.config as config

    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    dst = tmp_path / "skills"
    shutil.copytree(src, dst)
    monkeypatch.setattr(config, "SKILLS_DIR", str(dst))
    monkeypatch.setattr(config, "REPO_ROOT", str(tmp_path))  # no .git → commits skipped
    yield


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    yield


@pytest.fixture()
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def owner(monkeypatch):
    monkeypatch.setattr(auth, "verify_supabase_token", lambda token: FAKE_OWNER)
    return FAKE_OWNER


@pytest.fixture()
def seeded(owner):
    seed_mod.seed()
    return True


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def owner_headers(owner):
    return {"Authorization": "Bearer fake-owner-token"}


@pytest.fixture()
def machine_headers(session, seeded):
    raw = "losk_test_machine_key"
    from engine.auth import get_org_id
    org_id = get_org_id(session)
    session.add(ApiKey(organization_id=org_id, name="test-worker",
                       key_hash=hash_key(raw),
                       scopes=["task.create", "task.read", "skill.read", "agent.read"]))
    session.commit()
    return {"X-Engine-Key": raw}


def fake_fetch(html=SAMPLE_HTML):
    def _fetch(url, timeout=15.0):
        return html
    return _fetch
