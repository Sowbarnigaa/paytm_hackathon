"""Merchant/wholesaler utilities: Paytm-Business-style home dashboard (simulated POS data), nearby-merchant search,
stock tracking (how the forecast knows what is on the shelf), wholesaler inventory management, notifications."""
from datetime import date, timedelta

from . import db, groups
from .db import ApiError

# ------------------------------------------------------------------ home dashboard

SOURCES = [("upi", "UPI"), ("debit", "Debit card"), ("credit", "Credit card"), ("netbanking", "Netbanking"), ("emi", "EMI"), ("other", "Others")]


def home(uid: int, days: int = 30) -> dict:
    u = groups.get_user(uid)
    days = max(7, min(int(days or 30), 45))
    if u["role"] == "wholesaler":
        s = db.one("SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM orders WHERE wholesaler_id=? AND status IN ('confirmed','shipped','delivered')", (uid,))
        pend = db.one("SELECT COUNT(*) n FROM orders WHERE wholesaler_id=? AND status='quote_pending'", (uid,))["n"]
        ship = db.one("SELECT COUNT(*) n FROM orders WHERE wholesaler_id=? AND status='confirmed'", (uid,))["n"]
        return {"role": "wholesaler", "orders": s["n"], "revenue": round(s["t"], 2), "to_quote": pend, "to_ship": ship,
                "rating": {"avg": u["rating_avg"], "count": u["rating_count"]}}
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    prev_since = (date.today() - timedelta(days=2 * days - 1)).isoformat()
    rows = db.rows("SELECT * FROM pos_daily WHERE user_id=? AND day>=? ORDER BY day", (uid, since))
    prev = db.one("SELECT COALESCE(SUM(amount),0) a, COALESCE(SUM(count),0) c FROM pos_daily WHERE user_id=? AND day>=? AND day<?", (uid, prev_since, since))
    amt, cnt = sum(r["amount"] for r in rows), sum(r["count"] for r in rows)
    ref_amt, ref_cnt = sum(r["refund_amount"] for r in rows), sum(r["refund_count"] for r in rows)
    settled = amt - ref_amt
    src = {k: sum(r[k] for r in rows) for k, _ in SOURCES}
    pend_orders = db.one("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status IN ('quote_pending','quoted')", (uid,))["n"]
    return {"role": "merchant", "days": days, "simulated": True,
            "payments": {"amount": round(amt), "count": cnt, "prev_amount": round(prev["a"]),
                         "change_pct": round(100 * (amt - prev["a"]) / prev["a"], 1) if prev["a"] else None},
            "settlement": {"amount": round(settled), "pending": round(rows[-1]["amount"] * 0.9) if rows else 0, "last_settled": (date.today() - timedelta(days=1)).isoformat()},
            "refunds": {"amount": round(ref_amt), "count": ref_cnt},
            "chart": [{"day": r["day"], "amount": r["amount"], "count": r["count"]} for r in rows],
            "sources": [{"key": k, "label": lbl, "amount": round(src[k]), "pct": round(100 * src[k] / amt, 1) if amt else 0} for k, lbl in SOURCES],
            "open_orders": pend_orders, "rating": {"avg": u["rating_avg"], "count": u["rating_count"]}}


# ------------------------------------------------------------------ nearby merchants (group-formation discovery)

def nearby_merchants(uid: int, q: str = "", city: str = "", category: str = "", product: str = "", limit: int = 30) -> list[dict]:
    me = groups.require_merchant(uid)
    mine_groups = groups.my_group_ids(uid)
    mine = groups.bought(uid)
    q = (q or "").strip().lower()
    out = []
    for o in db.rows("SELECT id, name, shop, city, category, rating_avg, rating_count, kyc_verified FROM users WHERE role='merchant' AND id!=?", (uid,)):
        if city and o["city"] != city:
            continue
        if category and not groups.category_compatible(category, o["category"]) and o["category"] != category:
            continue
        theirs = groups.bought(o["id"])
        if product and product not in theirs:
            continue
        if q and q not in f"{o['name']} {o['shop']} {o['city']}".lower() and not any(q in p.lower() for p in theirs):
            continue
        km = db.distance_km(me["city"], o["city"])
        common = sorted(groups.my_group_ids(o["id"]) & mine_groups)
        shared = sorted(mine & theirs)
        o.update(distance_km=km, near_label="Same city" if o["city"] == me["city"] else f"{km:.0f} km away",
                 shared_products=shared, common_groups=len(common), items=sorted(theirs)[:4],
                 groups=[g["name"] for g in groups.my_groups(o["id"])][:2])
        out.append(o)
    out.sort(key=lambda x: (x["distance_km"], -len(x["shared_products"]), -x["rating_avg"]))
    return out[:limit]


# ------------------------------------------------------------------ stock tracking

def my_stock(uid: int) -> list[dict]:
    rows = db.rows("SELECT i.product, i.stock, p.unit, (SELECT MAX(day) FROM consumption c WHERE c.user_id=i.user_id AND c.product=i.product) last_usage"
                   " FROM inventory i JOIN products p ON p.name=i.product WHERE i.user_id=? ORDER BY i.product", (uid,))
    return rows


def log_usage(uid: int, product: str, qty) -> dict:
    """Manual usage log (stands in for item-level POS sales): reduces stock and feeds the forecast."""
    groups.require_merchant(uid)
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity must be a number") from None
    if qty <= 0:
        raise ApiError(400, "Quantity must be positive")
    inv = db.one("SELECT stock FROM inventory WHERE user_id=? AND product=?", (uid, product))
    if not inv:
        raise ApiError(404, "You do not track this product yet - set a stock count first")
    day = date.today().isoformat()
    db.run("INSERT INTO consumption VALUES(?,?,?,?) ON CONFLICT(user_id,product,day) DO UPDATE SET qty=qty+excluded.qty", (uid, product, day, qty))
    db.run("UPDATE inventory SET stock=MAX(0,stock-?) WHERE user_id=? AND product=?", (qty, uid, product))
    return {"product": product, "stock": round(max(0.0, inv["stock"] - qty), 1)}


def set_stock(uid: int, product: str, stock) -> dict:
    groups.require_merchant(uid)
    if not db.one("SELECT 1 x FROM products WHERE name=?", (product,)):
        raise ApiError(400, "Unknown product")
    try:
        stock = float(stock)
    except (TypeError, ValueError):
        raise ApiError(400, "Stock must be a number") from None
    if stock < 0:
        raise ApiError(400, "Stock cannot be negative")
    db.run("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(user_id,product) DO UPDATE SET stock=excluded.stock", (uid, product, stock))
    return {"product": product, "stock": stock}


# ------------------------------------------------------------------ wholesaler inventory (the database behind prices)

def wholesaler_inventory(uid: int) -> dict:
    u = groups.get_user(uid)
    if u["role"] != "wholesaler":
        raise ApiError(403, "Wholesalers only")
    items = db.rows("SELECT c.product, c.price, c.floor_price, c.stock_qty, c.updated_at, p.unit, p.base_price, wh.name warehouse, wh.city warehouse_city"
                    " FROM catalog c JOIN products p ON p.name=c.product JOIN warehouses wh ON wh.id=c.warehouse_id WHERE c.wholesaler_id=? ORDER BY c.product", (uid,))
    return {"items": items, "warehouses": db.rows("SELECT * FROM warehouses WHERE wholesaler_id=?", (uid,)),
            "demand": [{"product": d["product"], "merchants": d["m"], "qty": d["q"]} for d in db.rows(
                "SELECT product, COUNT(DISTINCT user_id) m, ROUND(SUM(qty),0) q FROM history WHERE day>=date('now','-30 day') GROUP BY product ORDER BY q DESC LIMIT 6")]}


def update_inventory(uid: int, product: str, price=None, stock=None, floor=None) -> dict:
    u = groups.get_user(uid)
    if u["role"] != "wholesaler":
        raise ApiError(403, "Wholesalers only")
    row = db.one("SELECT * FROM catalog WHERE wholesaler_id=? AND product=?", (uid, product))
    if not row:
        raise ApiError(404, "You do not stock this product")
    try:
        price = float(price) if price not in (None, "") else row["price"]
        stock = float(stock) if stock not in (None, "") else row["stock_qty"]
        floor = float(floor) if floor not in (None, "") else row["floor_price"]
    except (TypeError, ValueError):
        raise ApiError(400, "Price, stock and floor must be numbers") from None
    if price <= 0 or stock < 0 or floor <= 0:
        raise ApiError(400, "Price and floor must be positive; stock cannot be negative")
    if floor > price:
        raise ApiError(400, "Floor price cannot be above your list price")
    db.run("UPDATE catalog SET price=?, stock_qty=?, floor_price=?, updated_at=? WHERE wholesaler_id=? AND product=?", (price, stock, floor, db.now_iso(), uid, product))
    return {"product": product, "price": price, "stock_qty": stock, "floor_price": floor}


# ------------------------------------------------------------------ notifications

def notifications(uid: int, limit: int = 40) -> dict:
    items = db.rows("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    return {"items": items, "unread": db.one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0", (uid,))["n"]}


def mark_read(uid: int, nid: int | None = None) -> dict:
    if nid:
        db.run("UPDATE notifications SET is_read=1 WHERE user_id=? AND id=?", (uid, nid))
    else:
        db.run("UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,))
    return {"ok": True}
