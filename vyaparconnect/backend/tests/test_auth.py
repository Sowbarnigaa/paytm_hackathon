"""Authentication tests: email + password sign-up / sign-in, bearer sessions, lockout, demo-mode gating."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("VC_DB", os.path.join(tempfile.mkdtemp(), "auth.db"))

from app import auth, db, seed  # noqa: E402
from app.main import app  # noqa: E402

NEW = {"name": "Anbu", "shop": "Anbu Stores", "role": "merchant", "city": "Erode", "category": "grocery",
       "phone": "9876543210", "email": "Anbu@Example.com", "password": "s3cret-pass"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("VC_DEMO_AUTH", raising=False)       # real auth: X-User-Id must NOT work
    seed.seed()
    auth._fails.clear()


@pytest.fixture
def c():
    with TestClient(app) as client:
        yield client


def signup(c, **over):
    return c.post("/api/auth/register", json={**NEW, **over})


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def login(c, email="ravi@example.com", pw=seed.DEMO_PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": pw})


# ------------------------------------------------------------ demo mode is off by default

def test_header_auth_is_rejected_without_demo_mode(c):
    assert c.get("/api/me", headers={"X-User-Id": "7"}).status_code == 401
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/users").status_code == 401
    assert c.post("/api/reset").status_code == 403
    assert c.get("/api/auth/config").json()["demo_password"] is None


def test_demo_mode_still_allows_role_switcher(c, monkeypatch):
    monkeypatch.setenv("VC_DEMO_AUTH", "1")
    assert c.get("/api/me", headers={"X-User-Id": "7"}).status_code == 200
    assert c.get("/api/me", headers={"X-User-Id": "9999"}).status_code == 401


# ------------------------------------------------------------ sign-up (signs the user straight in)

def test_register_signs_in_for_merchant_and_wholesaler(c):
    for role, email in (("merchant", "anbu@example.com"), ("wholesaler", "wally@example.com")):
        r = signup(c, role=role, email=email)
        assert r.status_code == 200, r.text
        tok, user = r.json()["token"], r.json()["user"]
        assert user["role"] == role and "password_hash" not in user
        assert c.get("/api/me", headers=bearer(tok)).json()["email"] == email
        assert login(c, email, NEW["password"]).status_code == 200


def test_email_is_case_insensitive_and_duplicates_rejected(c):
    assert signup(c).status_code == 200
    assert signup(c, email="ANBU@example.com").status_code == 409
    assert login(c, "ANBU@EXAMPLE.COM", NEW["password"]).status_code == 200


@pytest.mark.parametrize("over", [
    {"email": "not-an-email"}, {"password": "short"}, {"role": "admin"}, {"city": "Mumbai"},
    {"category": "cars"}, {"name": ""}, {"shop": " "}, {"phone": "12ab"}, {"password": None}, {"email": 5},
])
def test_register_validation(c, over):
    assert signup(c, **over).status_code == 400
    assert db.one("SELECT 1 x FROM users WHERE email=?", ("anbu@example.com",)) is None


def test_password_is_hashed(c):
    signup(c)
    row = db.one("SELECT password_hash FROM users WHERE email='anbu@example.com'")
    assert row["password_hash"].startswith("scrypt$") and NEW["password"] not in row["password_hash"]


# ------------------------------------------------------------ login, sessions, lockout

def test_seeded_demo_accounts_can_sign_in(c):
    for email, role in (("ravi@example.com", "merchant"), ("murugan@example.com", "wholesaler")):
        r = login(c, email)
        assert r.status_code == 200 and r.json()["user"]["role"] == role
        assert c.get("/api/me", headers=bearer(r.json()["token"])).status_code == 200


def test_bad_credentials_look_identical(c):
    a = login(c, "ravi@example.com", "wrong-password")
    b = login(c, "ghost@example.com", "wrong-password")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert login(c, "ravi@example.com", 12345).status_code == 401


def test_login_lockout_after_repeated_failures(c):
    for _ in range(auth.MAX_LOGIN_FAILS):
        assert login(c, pw="nope-nope").status_code == 401
    assert login(c).status_code == 429                                         # even the right password is refused while locked
    auth._fails.clear()
    assert login(c).status_code == 200


def test_logout_and_expired_and_garbage_tokens(c):
    tok = login(c).json()["token"]
    assert c.post("/api/auth/logout", headers=bearer(tok)).status_code == 200
    assert c.get("/api/me", headers=bearer(tok)).status_code == 401
    assert c.get("/api/me", headers=bearer("garbage")).status_code == 401
    assert c.get("/api/me", headers={"Authorization": "Basic abc"}).status_code == 401
    tok2 = login(c).json()["token"]
    db.run("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    assert c.get("/api/me", headers=bearer(tok2)).status_code == 401


def test_session_token_is_not_stored_in_clear(c):
    tok = login(c).json()["token"]
    assert db.one("SELECT 1 x FROM sessions WHERE token_hash=?", (tok,)) is None


def test_roles_are_still_enforced_with_a_real_session(c):
    wtok = login(c, "murugan@example.com").json()["token"]
    assert c.get("/api/groups", headers=bearer(wtok)).status_code == 403
    mtok = login(c).json()["token"]
    assert c.get("/api/groups", headers=bearer(mtok)).status_code == 200


def test_login_page_is_served(c):
    r = c.get("/login")
    assert r.status_code == 200 and "Sign in" in r.text
