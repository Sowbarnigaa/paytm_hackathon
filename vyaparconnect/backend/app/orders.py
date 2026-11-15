"""Order lifecycle: quote_pending -> quoted -> confirmed -> shipped -> delivered (or cancelled), plus two-way reviews.

Prices on an order are PRODUCT prices only. The wholesaler quotes the delivery charge afterwards (`quote`), and the
merchant then chooses how to pay (see payments.py)."""
import json
from datetime import date, timedelta

from . import db
from .db import ApiError

MAX_DELIVERY_CHARGE = 25000


def _num(v, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number") from None


def place(uid: int, wholesaler_id: int, lines: list[dict], source: str = "direct", unit_prices: dict | None = None) -> dict:
    """Create an order awaiting the wholesaler's delivery quote. Reserves wholesaler stock."""
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or user["role"] != "merchant":
        raise ApiError(403, "Only merchants can place orders")
    w = db.one("SELECT * FROM users WHERE id=? AND role='wholesaler'", (wholesaler_id,))
    if not w:
        raise ApiError(404, "Wholesaler not found")
    if not lines:
        raise ApiError(400, "Order has no items")
    items, eta = [], 1
    for ln in lines:
        qty = _num(ln.get("qty"), "Quantity")
        if qty <= 0:
            raise ApiError(400, "Quantity must be positive")
        cat = db.one("SELECT c.*, p.unit, wh.city wh_city, wh.handling_days FROM catalog c JOIN products p ON p.name=c.product"
                     " JOIN warehouses wh ON wh.id=c.warehouse_id WHERE c.wholesaler_id=? AND c.product=?",
                     (wholesaler_id, ln.get("product")))
        if not cat:
            raise ApiError(400, f"{w['shop']} does not stock {ln.get('product')}")
        if cat["stock_qty"] < qty:
            raise ApiError(400, f"Only {cat['stock_qty']:g} {cat['unit']} of {ln['product']} in stock")
        price = _num((unit_prices or {}).get(ln["product"], cat["price"]), "Price")
        if price <= 0:
            raise ApiError(400, "Price must be positive")
        items.append({"product": ln["product"], "qty": qty, "unit": cat["unit"], "unit_price": round(price, 2),
                      "warehouse_city": cat["wh_city"]})
        eta = max(eta, db.eta_days(cat["wh_city"], user["city"], cat["handling_days"]))
    for i in items:
        db.run("UPDATE catalog SET stock_qty=MAX(0,stock_qty-?), updated_at=? WHERE wholesaler_id=? AND product=?",
               (i["qty"], db.now_iso(), wholesaler_id, i["product"]))
    total = round(sum(i["qty"] * i["unit_price"] for i in items), 2)
    ts = db.now_iso()
    oid = db.run("INSERT INTO orders(user_id,wholesaler_id,items,items_total,source,eta_days,origin,created_at,updated_at)"
                 " VALUES(?,?,?,?,?,?,?,?,?)",
                 (uid, wholesaler_id, json.dumps(items), total, source, eta, items[0]["warehouse_city"], ts, ts))
    db.notify(wholesaler_id, "order", f"New order #{oid} from {user['shop']} ({user['city']}) - Rs {total:,.0f} for the goods. Please quote delivery.", f"order:{oid}")
    return {"order_id": oid, "items_total": total, "status": "quote_pending", "eta_days": eta,
            "message": "Order placed. The wholesaler will quote the delivery charge next."}


def _decorate(o: dict, uid: int) -> dict:
    o["items"] = json.loads(o["items"])
    w = db.one("SELECT id, shop, name, city, rating_avg, rating_count FROM users WHERE id=?", (o["wholesaler_id"],))
    b = db.one("SELECT id, shop, name, city, rating_avg, rating_count FROM users WHERE id=?", (o["user_id"],))
    o["wholesaler"], o["buyer"] = w, b
    o["installments"] = db.rows("SELECT * FROM installments WHERE order_id=? ORDER BY no", (o["id"],))
    o["payments"] = db.rows("SELECT amount, kind, method, txn_id, created_at FROM payments WHERE order_id=? ORDER BY id", (o["id"],))
    o["balance"] = round((o["total"] or 0) - o["paid_amount"], 2) if o["total"] is not None else None
    me_buyer, me_seller = o["user_id"] == uid, o["wholesaler_id"] == uid
    o["role"] = "buyer" if me_buyer else "seller"
    st = o["status"]
    o["can_quote"] = me_seller and st == "quote_pending"
    o["can_pay"] = me_buyer and st == "quoted"
    o["can_ship"] = me_seller and st == "confirmed"
    o["can_deliver"] = me_buyer and st == "shipped"
    o["can_cancel"] = st in ("quote_pending", "quoted")
    o["next_installment"] = next((i for i in o["installments"] if i["status"] == "due"), None) if me_buyer and st in ("confirmed", "shipped", "delivered") else None
    reviewed = db.one("SELECT rating, comment FROM reviews WHERE order_id=? AND reviewer_id=?", (o["id"], uid))
    o["my_review"] = reviewed
    o["can_review"] = st == "delivered" and (me_buyer or me_seller) and not reviewed
    o["review_target"] = (w if me_buyer else b) if (me_buyer or me_seller) else None
    o["delivery_note"] = o["delivery_note"] or ("Delivery charge not quoted yet" if o["delivery_charge"] is None else "")
    return o


def get_order(oid: int, uid: int) -> dict:
    o = db.one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o or uid not in (o["user_id"], o["wholesaler_id"]):
        raise ApiError(404, "Order not found")
    return _decorate(o, uid)


def my_orders(uid: int) -> list[dict]:
    return [_decorate(o, uid) for o in db.rows(
        "SELECT * FROM orders WHERE user_id=? OR wholesaler_id=? ORDER BY id DESC LIMIT 40", (uid, uid))]


def quote(oid: int, uid: int, delivery_charge, note: str = "", eta_days=None) -> dict:
    o = get_order(oid, uid)
    if not o["can_quote"]:
        raise ApiError(400, "Only the wholesaler can quote, and only once")
    charge = _num(delivery_charge, "Delivery charge")
    if charge < 0 or charge > MAX_DELIVERY_CHARGE:
        raise ApiError(400, f"Delivery charge must be between 0 and Rs {MAX_DELIVERY_CHARGE:,}")
    eta = int(_num(eta_days, "ETA")) if eta_days not in (None, "") else o["eta_days"]
    if eta < 1 or eta > 14:
        raise ApiError(400, "ETA must be 1-14 days")
    total = round(o["items_total"] + charge, 2)
    db.run("UPDATE orders SET delivery_charge=?, delivery_note=?, total=?, eta_days=?, eta_date=?, status='quoted', updated_at=? WHERE id=?",
           (charge, (note or "").strip()[:120], total, eta, (date.today() + timedelta(days=eta)).isoformat(), db.now_iso(), oid))
    db.notify(o["user_id"], "order", f"{o['wholesaler']['shop']} quoted Rs {charge:,.0f} delivery for order #{oid}. Total Rs {total:,.0f} - choose how to pay.", f"order:{oid}")
    return get_order(oid, uid)


def cancel(oid: int, uid: int) -> dict:
    o = get_order(oid, uid)
    if not o["can_cancel"]:
        raise ApiError(400, "Only orders not yet paid can be cancelled")
    for i in o["items"]:
        db.run("UPDATE catalog SET stock_qty=stock_qty+? WHERE wholesaler_id=? AND product=?", (i["qty"], o["wholesaler_id"], i["product"]))
    db.run("UPDATE orders SET status='cancelled', updated_at=? WHERE id=?", (db.now_iso(), oid))
    other = o["wholesaler_id"] if uid == o["user_id"] else o["user_id"]
    db.notify(other, "order", f"Order #{oid} was cancelled.", f"order:{oid}")
    return {"status": "cancelled"}


def ship(oid: int, uid: int) -> dict:
    o = get_order(oid, uid)
    if not o["can_ship"]:
        raise ApiError(400, "Order must be confirmed (first payment or loan) before shipping")
    db.run("UPDATE orders SET status='shipped', updated_at=? WHERE id=?", (db.now_iso(), oid))
    db.notify(o["user_id"], "order", f"Order #{oid} is on its way - arriving in about {o['eta_days']} day(s).", f"order:{oid}")
    return get_order(oid, uid)


def deliver(oid: int, uid: int) -> dict:
    """Merchant confirms receipt: stock is added to their inventory and the purchase enters history (feeds the forecast)."""
    o = get_order(oid, uid)
    if not o["can_deliver"]:
        raise ApiError(400, "Only the buyer can confirm delivery of a shipped order")
    day = date.today().isoformat()
    for i in o["items"]:
        db.run("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(user_id,product) DO UPDATE SET stock=stock+excluded.stock", (uid, i["product"], i["qty"]))
        db.run("INSERT INTO history(user_id,product,qty,day) VALUES(?,?,?,?)", (uid, i["product"], i["qty"], day))
    db.run("UPDATE orders SET status='delivered', updated_at=? WHERE id=?", (db.now_iso(), oid))
    db.notify(o["wholesaler_id"], "order", f"{o['buyer']['shop']} received order #{oid}.", f"order:{oid}")
    db.notify(uid, "review", f"Order #{oid} delivered - rate {o['wholesaler']['shop']}.", f"order:{oid}")
    return get_order(oid, uid)


# ------------------------------------------------------------------ reviews (1-5 stars, both directions)

def review(oid: int, uid: int, rating, comment: str = "") -> dict:
    o = get_order(oid, uid)
    if o["status"] != "delivered":
        raise ApiError(400, "You can review once the order is delivered")
    if o["my_review"]:
        raise ApiError(409, "You already reviewed this order")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise ApiError(400, "Rating must be 1 to 5 stars") from None
    if not 1 <= rating <= 5:
        raise ApiError(400, "Rating must be 1 to 5 stars")
    target = o["wholesaler_id"] if uid == o["user_id"] else o["user_id"]
    db.run("INSERT INTO reviews(order_id,reviewer_id,target_id,rating,comment,created_at) VALUES(?,?,?,?,?,?)",
           (oid, uid, target, rating, (comment or "").strip()[:300], db.now_iso()))
    db.recompute_rating(target)
    me = db.one("SELECT shop FROM users WHERE id=?", (uid,))
    db.notify(target, "review", f"{me['shop']} rated you {rating}/5 for order #{oid}.")
    return {"ok": True, "rating": rating}


def reviews_for(target_id: int, limit: int = 20) -> dict:
    t = db.one("SELECT id, name, shop, role, city, rating_avg, rating_count FROM users WHERE id=?", (target_id,))
    if not t:
        raise ApiError(404, "User not found")
    revs = db.rows("SELECT r.rating, r.comment, r.created_at, u.shop reviewer FROM reviews r JOIN users u ON u.id=r.reviewer_id"
                   " WHERE r.target_id=? ORDER BY r.id DESC LIMIT ?", (target_id, limit))
    dist = {str(s): 0 for s in range(5, 0, -1)}
    for r in db.rows("SELECT rating, COUNT(*) n FROM reviews WHERE target_id=? GROUP BY rating", (target_id,)):
        dist[str(r["rating"])] = r["n"]
    return {"user": t, "reviews": revs, "distribution": dist}


def pending_reviews(uid: int) -> list[dict]:
    return [o for o in my_orders(uid) if o["can_review"]]
