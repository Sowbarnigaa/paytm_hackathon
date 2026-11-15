"""SQLite helpers + schema (v2). Plain sqlite3 keeps the hackathon stack dependency-free."""
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "vyapar.db"

# City centroids used for warehouse -> merchant distance / ETA (demo geography: Tamil Nadu)
CITY_COORDS = {
    "Erode": (11.341, 77.717), "Coimbatore": (11.0168, 76.9558), "Chennai": (13.0827, 80.2707),
    "Salem": (11.6643, 78.146), "Tiruppur": (11.1085, 77.3411),
}
CITIES = sorted(CITY_COORDS)


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def db_path() -> str:
    return os.environ.get("VC_DB", str(DEFAULT_DB))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = rows(sql, args)
    return r[0] if r else None


def run(sql: str, args: tuple = ()) -> int:
    with closing(conn()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def distance_km(a: str, b: str) -> float:
    """Great-circle distance between two known cities, x1.25 for road distance."""
    if a == b or a not in CITY_COORDS or b not in CITY_COORDS:
        return 0.0
    (la1, lo1), (la2, lo2) = CITY_COORDS[a], CITY_COORDS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dl, dp = math.radians(lo2 - lo1), p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)) * 1.25, 0)


def eta_days(warehouse_city: str, buyer_city: str, handling: int = 1) -> int:
    """Handling days + one transit day per ~350 km of road distance."""
    d = distance_km(warehouse_city, buyer_city)
    return handling + (math.ceil(d / 350) if d else 0)


def notify(uid: int, kind: str, text: str, link: str | None = None) -> None:
    run("INSERT INTO notifications(user_id,kind,text,link,created_at) VALUES(?,?,?,?,?)",
        (uid, kind, text, link, now_iso()))


def recompute_rating(uid: int) -> None:
    r = one("SELECT COUNT(*) n, COALESCE(AVG(rating),0) a FROM reviews WHERE target_id=?", (uid,))
    run("UPDATE users SET rating_avg=?, rating_count=? WHERE id=?", (round(r["a"], 2), r["n"], uid))


SCHEMA = """
CREATE TABLE users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, shop TEXT, role TEXT NOT NULL CHECK(role IN ('merchant','wholesaler')),
  city TEXT NOT NULL, category TEXT NOT NULL,                -- grocery | fmcg | both
  phone TEXT, kyc_verified INTEGER NOT NULL DEFAULT 1,
  credit_score INTEGER NOT NULL DEFAULT 650, on_time_rate REAL NOT NULL DEFAULT 0.9,
  rating_avg REAL NOT NULL DEFAULT 0, rating_count INTEGER NOT NULL DEFAULT 0,  -- 1..5 review scale
  email TEXT UNIQUE, password_hash TEXT, email_verified INTEGER NOT NULL DEFAULT 0   -- login (see auth.py)
);
CREATE TABLE sessions(                                        -- bearer sessions; only the SHA-256 of the token is stored
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE products(
  name TEXT PRIMARY KEY, unit TEXT NOT NULL, base_price REAL NOT NULL, category TEXT NOT NULL, typical_qty REAL NOT NULL
);
CREATE TABLE warehouses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wholesaler_id INTEGER NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, city TEXT NOT NULL, handling_days INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE catalog(                                         -- wholesaler inventory (the "database" behind prices)
  wholesaler_id INTEGER NOT NULL REFERENCES users(id), product TEXT NOT NULL REFERENCES products(name),
  warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
  price REAL NOT NULL,                                        -- product price only; delivery is quoted per order
  floor_price REAL NOT NULL,                                  -- PRIVATE reservation price used by the negotiator
  stock_qty REAL NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(wholesaler_id, product)
);
CREATE TABLE groups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
  category TEXT NOT NULL, city TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('public','invite')),
  admin_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE memberships(                                     -- merchants only
  group_id INTEGER NOT NULL REFERENCES groups(id), user_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK(status IN ('active','pending','invited','rejected')),
  note TEXT, joined_at TEXT NOT NULL, PRIMARY KEY(group_id, user_id)
);
CREATE TABLE posts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL REFERENCES groups(id),
  user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL DEFAULT 'announcement',
  body TEXT NOT NULL, flagged INTEGER NOT NULL DEFAULT 0, flag_reason TEXT, sale_id INTEGER,
  status TEXT NOT NULL DEFAULT 'visible' CHECK(status IN ('visible','held','removed')), created_at TEXT NOT NULL
);
CREATE TABLE sales(                                           -- wholesaler listings (tiered, product price only)
  id INTEGER PRIMARY KEY AUTOINCREMENT, wholesaler_id INTEGER NOT NULL REFERENCES users(id),
  product TEXT NOT NULL REFERENCES products(name), kind TEXT NOT NULL DEFAULT 'bulk',   -- bulk|clearance|seasonal
  tiers TEXT NOT NULL, qty_limit REAL NOT NULL, sold_qty REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open', expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE pools(                                           -- a group pooling its orders on one sale
  id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL REFERENCES sales(id),
  group_id INTEGER NOT NULL REFERENCES groups(id), created_by INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE pool_commitments(
  pool_id INTEGER NOT NULL REFERENCES pools(id), user_id INTEGER NOT NULL REFERENCES users(id),
  qty REAL NOT NULL, PRIMARY KEY(pool_id, user_id)
);
CREATE TABLE demands(                                         -- merchant requirements; wholesalers bid
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  product TEXT NOT NULL REFERENCES products(name), qty REAL NOT NULL, budget REAL, note TEXT,
  status TEXT NOT NULL DEFAULT 'open', winner_bid_id INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE bids(
  id INTEGER PRIMARY KEY AUTOINCREMENT, demand_id INTEGER NOT NULL REFERENCES demands(id),
  wholesaler_id INTEGER NOT NULL REFERENCES users(id), price REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  wholesaler_id INTEGER NOT NULL REFERENCES users(id), items TEXT NOT NULL,
  items_total REAL NOT NULL, delivery_charge REAL, delivery_note TEXT, total REAL,
  source TEXT NOT NULL DEFAULT 'direct',
  status TEXT NOT NULL DEFAULT 'quote_pending',   -- quote_pending|quoted|confirmed|shipped|delivered|cancelled
  pay_mode TEXT, paid_amount REAL NOT NULL DEFAULT 0, eta_days INTEGER NOT NULL DEFAULT 2, eta_date TEXT,
  origin TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE installments(
  order_id INTEGER NOT NULL REFERENCES orders(id), no INTEGER NOT NULL, amount REAL NOT NULL, due_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'due', paid_at TEXT, txn_id TEXT, PRIMARY KEY(order_id, no)
);
CREATE TABLE payment_intents(                                 -- simulated Paytm Payment Gateway transactions
  txn_id TEXT PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), user_id INTEGER NOT NULL,
  amount REAL NOT NULL, kind TEXT NOT NULL, parts INTEGER, installment_no INTEGER,
  status TEXT NOT NULL DEFAULT 'pending', method TEXT, created_at TEXT NOT NULL
);
CREATE TABLE payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id), user_id INTEGER NOT NULL,
  wholesaler_id INTEGER NOT NULL, amount REAL NOT NULL, kind TEXT NOT NULL, method TEXT, txn_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE loans(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  amount REAL NOT NULL, tenure INTEGER NOT NULL, rate REAL NOT NULL, emi REAL NOT NULL,
  autopay INTEGER NOT NULL DEFAULT 0, mandate TEXT, paid_emis INTEGER NOT NULL DEFAULT 0,
  order_ids TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
);
CREATE TABLE reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, reviewer_id INTEGER NOT NULL REFERENCES users(id),
  target_id INTEGER NOT NULL REFERENCES users(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
  comment TEXT, created_at TEXT NOT NULL, UNIQUE(order_id, reviewer_id)
);
CREATE TABLE notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
  text TEXT NOT NULL, link TEXT, is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE history(                                         -- purchase history (what a merchant buys)
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  product TEXT NOT NULL REFERENCES products(name), qty REAL NOT NULL, day TEXT NOT NULL
);
CREATE TABLE inventory(                                       -- merchant stock on hand
  user_id INTEGER NOT NULL REFERENCES users(id), product TEXT NOT NULL REFERENCES products(name),
  stock REAL NOT NULL, PRIMARY KEY(user_id, product)
);
CREATE TABLE consumption(                                     -- daily usage per SKU (derived from Paytm POS/QR sales + manual logs)
  user_id INTEGER NOT NULL REFERENCES users(id), product TEXT NOT NULL REFERENCES products(name),
  day TEXT NOT NULL, qty REAL NOT NULL, PRIMARY KEY(user_id, product, day)
);
CREATE TABLE pos_daily(                                       -- Paytm for Business dashboard data (simulated)
  user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL, count INTEGER NOT NULL, amount REAL NOT NULL,
  upi REAL NOT NULL, debit REAL NOT NULL, credit REAL NOT NULL, netbanking REAL NOT NULL, emi REAL NOT NULL,
  other REAL NOT NULL, refund_count INTEGER NOT NULL, refund_amount REAL NOT NULL, PRIMARY KEY(user_id, day)
);
CREATE TABLE negotiations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
  wholesaler_id INTEGER NOT NULL REFERENCES users(id), product TEXT NOT NULL REFERENCES products(name),
  qty REAL NOT NULL, list_price REAL NOT NULL, buyer_limit REAL NOT NULL, agreed_price REAL,
  status TEXT NOT NULL, transcript TEXT NOT NULL, order_id INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE cibil_checks(
  user_id INTEGER PRIMARY KEY REFERENCES users(id), score INTEGER NOT NULL, checked_at TEXT NOT NULL
);
"""


def create_schema() -> None:
    path = db_path()
    if os.path.exists(path):
        os.remove(path)
    with closing(conn()) as c:
        c.executescript(SCHEMA)
        c.commit()
