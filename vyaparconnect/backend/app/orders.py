"""Order creation (wallet or loan-funded)."""
import json

from . import credit, db
from .db import ApiError


def create_order(uid: int, wholesaler_id: int, items: list[dict], source: str = "direct", check_stock: bool = True) -> dict:
    """items: [{product, qty, unit_price}]. Updates buyer inventory + history so forecasts stay current."""
    total = round(sum(i["qty"] * i["unit_price"] for i in items), 2)
    if check_stock:
        for i in items:
            row = db.one("SELECT stock_qty FROM catalog WHERE wholesaler_id=? AND product=?", (wholesaler_id, i["product"]))
            if not row:
                raise ApiError(400, f"Wholesaler does not stock {i['product']}")
            if row["stock_qty"] < i["qty"]:
                raise ApiError(400, f"Only {row['stock_qty']:g} of {i['product']} in stock")
    ts = db.now_iso()
    oid = db.run("INSERT INTO orders(user_id,wholesaler_id,items,total,source,created_at) VALUES(?,?,?,?,?,?)",
                 (uid, wholesaler_id, json.dumps(items), total, source, ts))
    for i in items:
        db.run("UPDATE catalog SET stock_qty=MAX(0,stock_qty-?) WHERE wholesaler_id=? AND product=?",
               (i["qty"], wholesaler_id, i["product"]))
        db.run("INSERT INTO inventory VALUES(?,?,?) ON CONFLICT(user_id,product) DO UPDATE SET stock=stock+excluded.stock",
               (uid, i["product"], i["qty"]))
        db.run("INSERT INTO history(user_id,product,qty,day) VALUES(?,?,?,?)", (uid, i["product"], i["qty"], ts[:10]))
    return {"order_id": oid, "total": total}


def place(uid: int, wholesaler_id: int, lines: list[dict], pay: str = "wallet", tenure: int | None = None,
          autopay: bool = False, source: str = "direct", unit_prices: dict | None = None) -> dict:
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not user or user["role"] != "merchant":
        raise ApiError(403, "Only merchants can place orders")
    w = db.one("SELECT * FROM users WHERE id=? AND role='wholesaler'", (wholesaler_id,))
    if not w:
        raise ApiError(404, "Wholesaler not found")
    if not lines:
        raise ApiError(400, "Order has no items")
    items = []
    for ln in lines:
        try:
            qty = float(ln["qty"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "Each line needs a numeric qty") from None
        if qty <= 0:
            raise ApiError(400, "Quantity must be positive")
        cat = db.one("SELECT price FROM catalog WHERE wholesaler_id=? AND product=?", (wholesaler_id, ln.get("product")))
        if not cat:
            raise ApiError(400, f"Wholesaler does not stock {ln.get('product')}")
        price = (unit_prices or {}).get(ln["product"], cat["price"])
        items.append({"product": ln["product"], "qty": qty, "unit_price": round(price, 2)})
    total = round(sum(i["qty"] * i["unit_price"] for i in items), 2)
    if pay not in ("wallet", "loan"):
        raise ApiError(400, "pay must be wallet or loan")
    if pay == "loan":  # validate credit before creating the order
        o = credit.offer(uid)
        if not o["eligible"] or total > o["available"]:
            raise ApiError(400, f"Order Rs {total:.0f} exceeds available credit Rs {o['available']:.0f}")
        if tenure not in {p["tenure"] for p in credit.offer(uid, total)["plans"]}:
            raise ApiError(400, "Choose a valid EMI tenure")
    res = create_order(uid, wholesaler_id, items, source)
    out = {**res, "items": items, "wholesaler": w["shop"], "pay": pay, "loan": None}
    if pay == "loan":
        db.run("UPDATE orders SET paid_by_loan=1 WHERE id=?", (res["order_id"],))
        out["loan"] = credit.create_loan(uid, total, tenure, autopay, [res["order_id"]])
    return out


def my_orders(uid: int) -> list[dict]:
    out = db.rows("SELECT o.*, w.shop wholesaler FROM orders o JOIN users w ON w.id=o.wholesaler_id"
                  " WHERE o.user_id=? ORDER BY o.id DESC LIMIT 30", (uid,))
    for o in out:
        o["items"] = json.loads(o["items"])
    return out
