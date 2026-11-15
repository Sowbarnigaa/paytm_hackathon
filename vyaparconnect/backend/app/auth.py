"""Authentication for merchants and wholesalers: email + password accounts and bearer-token sessions.
Sign-up signs the user in straight away (no email verification - this is a demo). Standard library only (scrypt, secrets, hmac)."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import db
from .db import ApiError

SESSION_DAYS = 7
MAX_LOGIN_FAILS = 5
LOCKOUT_S = 300
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PUBLIC_COLS = "id, name, shop, role, city, category, phone, email, kyc_verified"

_fails: dict[str, tuple[int, float]] = {}      # email -> (failed attempts, lock expiry); per-process


def demo_auth() -> bool:
    """Demo mode: the X-User-Id header (role switcher) is accepted instead of a login. Off by default."""
    return os.environ.get("VC_DEMO_AUTH") == "1"


# ---------------------------------------------------------------- passwords

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _scrypt(pw: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${_b64(salt)}${_b64(_scrypt(pw, salt))}"


def verify_password(pw: str, stored: str | None) -> bool:
    try:
        scheme, salt, digest = (stored or "").split("$")
        return scheme == "scrypt" and hmac.compare_digest(_scrypt(pw, base64.b64decode(salt)), base64.b64decode(digest))
    except ValueError:
        return False


_DUMMY = hash_password("timing-equaliser")      # verified against when the email is unknown, so timing does not leak accounts


# ---------------------------------------------------------------- helpers

def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _in(**kw) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat(timespec="seconds")


def _norm_email(v) -> str:
    return _s(v).lower()


def public_user(uid: int) -> dict:
    return db.one(f"SELECT {PUBLIC_COLS} FROM users WHERE id=?", (uid,))


def _user_by_email(email: str) -> dict | None:
    return db.one("SELECT * FROM users WHERE email=?", (email,))


# ---------------------------------------------------------------- sessions

def create_session(uid: int) -> str:
    token = secrets.token_urlsafe(32)
    db.run("DELETE FROM sessions WHERE expires_at<=?", (db.now_iso(),))
    db.run("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
           (_sha(token), uid, db.now_iso(), _in(days=SESSION_DAYS)))
    return token


def _bearer(authorization: str | None) -> str:
    scheme, _, tok = (authorization or "").partition(" ")
    return tok.strip() if scheme.lower() == "bearer" else ""


def authenticate(authorization: str | None, x_user_id: int | None) -> int:
    """Resolve the caller. Bearer token always works; X-User-Id only in demo mode."""
    if authorization:
        s = db.one("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", (_sha(_bearer(authorization)), db.now_iso()))
        if not s:
            raise ApiError(401, "Invalid or expired session - please sign in again")
        return s["user_id"]
    if demo_auth() and x_user_id is not None:
        if not db.one("SELECT 1 x FROM users WHERE id=?", (x_user_id,)):
            raise ApiError(401, "Unknown user")
        return x_user_id
    raise ApiError(401, "Authentication required")


def logout(authorization: str | None) -> dict:
    db.run("DELETE FROM sessions WHERE token_hash=?", (_sha(_bearer(authorization)),))
    return {"ok": True}


# ---------------------------------------------------------------- sign-up

def register(body: dict) -> dict:
    name, shop, role = _s(body.get("name")), _s(body.get("shop")), _s(body.get("role"))
    city, category, phone = _s(body.get("city")), _s(body.get("category")), _s(body.get("phone"))
    email, pw = _norm_email(body.get("email")), body.get("password")
    if not 2 <= len(name) <= 60:
        raise ApiError(400, "Name must be 2-60 characters")
    if not 2 <= len(shop) <= 80:
        raise ApiError(400, "Shop name must be 2-80 characters")
    if role not in ("merchant", "wholesaler"):
        raise ApiError(400, "Role must be merchant or wholesaler")
    if city not in db.CITIES:
        raise ApiError(400, "Choose one of: " + ", ".join(db.CITIES))
    if category not in ("grocery", "fmcg", "both"):
        raise ApiError(400, "Category must be grocery, fmcg or both")
    if phone and not re.fullmatch(r"\d{10}", phone):
        raise ApiError(400, "Phone must be 10 digits")
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email address")
    if not isinstance(pw, str) or not 8 <= len(pw) <= 128:
        raise ApiError(400, "Password must be 8-128 characters")
    try:
        uid = db.run("INSERT INTO users(name,shop,role,city,category,phone,password_hash,kyc_verified,email,email_verified)"
                     " VALUES(?,?,?,?,?,?,?,0,?,1)", (name, shop, role, city, category, phone or None, hash_password(pw), email))
    except sqlite3.IntegrityError:
        raise ApiError(409, "An account with this email already exists") from None
    return {"token": create_session(uid), "user": public_user(uid)}


# ---------------------------------------------------------------- login

def login(body: dict) -> dict:
    email, pw = _norm_email(body.get("email")), body.get("password")
    n, until = _fails.get(email, (0, 0.0))
    if n >= MAX_LOGIN_FAILS and time.time() < until:
        raise ApiError(429, "Too many failed attempts - try again in a few minutes")
    u = _user_by_email(email)
    pw = pw if isinstance(pw, str) else ""
    good = verify_password(pw, u["password_hash"] if u else _DUMMY) and u is not None
    if not good:
        now = time.time()
        if len(_fails) > 5000:                           # bound memory: drop expired entries
            for k in [k for k, (_, t) in _fails.items() if t < now]:
                del _fails[k]
        _fails[email] = ((n if now < until else 0) + 1, now + LOCKOUT_S)
        raise ApiError(401, "Invalid email or password")
    _fails.pop(email, None)
    return {"token": create_session(u["id"]), "user": public_user(u["id"])}
