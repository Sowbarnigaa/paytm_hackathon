"""Marketplace: wholesaler SALES (tiered, product price only), group POOLS on sales, merchant DEMANDS with bids.
Delivery charges are never part of a price here - the wholesaler quotes them on the order afterwards."""
import json
from datetime import datetime, timedelta, timezone

from . import db, groups, orders
from .db import ApiError

KINDS = ("bulk", "clearance", "seasonal")


def tier_for(tiers: list[dict], qty: float) -> dict | None:
    hit = None
    for t in tiers:
        if qty >= t["min_qty"]:
            hit = t
    return hit


def _clean_tiers(tiers: list[dict]) -> list[dict]:
    clean = []
    for t in tiers or []:
        try:
            mq, pr = float(t["min_qty"]), float(t["price"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "Each tier needs numeric min_qty and price") from None
        if mq < 0 or pr <= 0:
            raise ApiError(400, "Tier quantity must be >= 0 and price > 0")
        clean.append({"min_qty": mq, "price": pr})
    if not clean:
        raise ApiError(400, "Add at least one price tier")
    clean.sort(key=lambda t: t["min_qty"])
    if clean[0]["min_qty"] != 0:
        raise ApiError(400, "The first tier must start at quantity 0")
    if len({t["min_qty"] for t in clean}) != len(clean):
        raise ApiError(400, "Tier quantities must be distinct")
    for a, b in zip(clean, clean[1:]):
        if b["price"] >= a["price"]:
            raise ApiError(400, "Higher quantity tiers must have a lower price")
    return clean


def _reserved(sale_id: int, exclude_user: int | None = None, exclude_pool: int | None = None) -> float:
    r = db.one("SELECT COALESCE(SUM(pc.qty),0) q FROM pool_commitments pc JOIN pools p ON p.id=pc.pool_id"
               " WHERE p.sale_id=? AND p.status='open' AND (? IS NULL OR NOT (pc.user_id=? AND pc.pool_id=?))",
               (sale_id, exclude_user, exclude_user, exclude_pool))
    return r["q"]


# ------------------------------------------------------------------ sales

def create_sale(uid: int, product: str, kind: str, tiers: list[dict], qty_limit: float, days: int) -> dict:
    u = groups.get_user(uid)
    if u["role"] != "wholesaler":
        raise ApiError(403, "Only wholesalers can list sales")
    cat = db.one("SELECT * FROM catalog WHERE wholesaler_id=? AND product=?", (uid, product))
    if not cat:
        raise ApiError(400, "You do not stock this product - add it to your inventory first")
    if kind not in KINDS:
        raise ApiError(400, "Kind must be bulk, clearance or seasonal")
    try:
        qty_limit = float(qty_limit)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity must be a number") from None
    if qty_limit <= 0 or qty_limit > cat["stock_qty"]:
        raise ApiError(400, f"Sale quantity must be between 1 and your stock ({cat['stock_qty']:g})")
    clean = _clean_tiers(tiers)
    days = max(1, min(int(days or 7), 60))
    exp = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
    sid = db.run("INSERT INTO sales(wholesaler_id,product,kind,tiers,qty_limit,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
                 (uid, product, kind, json.dumps(clean), qty_limit, exp, db.now_iso()))
    unit = db.one("SELECT unit FROM products WHERE name=?", (product,))["unit"]
    label = {"bulk": "Bulk sale", "clearance": "Clearance", "seasonal": "Seasonal"}[kind]
    for m in db.rows("SELECT DISTINCT u.id FROM users u JOIN history h ON h.user_id=u.id WHERE u.role='merchant' AND h.product=? LIMIT 40", (product,)):
        db.notify(m["id"], "sale", f"{label}: {product} from {u['shop']} - Rs {clean[0]['price']:g}/{unit}, down to Rs {clean[-1]['price']:g}/{unit} in bulk.", f"sale:{sid}")
    return {"id": sid}


def sale_view(s: dict, uid: int) -> dict:
    tiers = json.loads(s["tiers"])
    prod = db.one("SELECT * FROM products WHERE name=?", (s["product"],))
    w = db.one("SELECT id, name, shop, city, rating_avg, rating_count, kyc_verified FROM users WHERE id=?", (s["wholesaler_id"],))
    cat = db.one("SELECT c.stock_qty, wh.name wh_name, wh.city wh_city, wh.handling_days FROM catalog c JOIN warehouses wh ON wh.id=c.warehouse_id"
                 " WHERE c.wholesaler_id=? AND c.product=?", (s["wholesaler_id"], s["product"]))
    me = groups.get_user(uid)
    reserved = _reserved(s["id"])
    remaining = max(0.0, s["qty_limit"] - s["sold_qty"] - reserved)
    expired = s["expires_at"] < db.now_iso()
    v = {**s, "tiers": tiers, "unit": prod["unit"], "category": prod["category"], "market_price": prod["base_price"],
         "wholesaler": w, "warehouse": cat["wh_name"] if cat else None, "warehouse_city": cat["wh_city"] if cat else w["city"],
         "remaining": remaining, "expired": expired, "is_open": s["status"] == "open" and not expired,
         "own": s["wholesaler_id"] == uid, "entry_price": tiers[0]["price"], "best_price": tiers[-1]["price"],
         "vs_market_pct": round((1 - tiers[0]["price"] / prod["base_price"]) * 100, 1),
         "delivery_note": "Price is for the product only. Delivery is quoted by the wholesaler after you order."}
    if me["role"] == "merchant" and cat:
        v["eta_days"] = db.eta_days(cat["wh_city"], me["city"], cat["handling_days"])
        v["pools"] = [pool_view(p, uid) for p in db.rows(
            "SELECT p.* FROM pools p JOIN memberships m ON m.group_id=p.group_id WHERE p.sale_id=? AND m.user_id=? AND m.status='active' AND p.status='open'",
            (s["id"], uid))]
        v["my_groups"] = [{"id": g["id"], "name": g["name"]} for g in groups.my_groups(uid)]
    return v


def list_sales(uid: int, q: str = "", category: str = "", product: str = "", city: str = "") -> list[dict]:
    me = groups.get_user(uid)
    sql = "SELECT s.* FROM sales s JOIN products p ON p.name=s.product WHERE 1=1"
    args: list = []
    if me["role"] == "wholesaler":                      # wholesalers see only their own sales
        sql += " AND s.wholesaler_id=?"
        args.append(uid)
    else:                                                # merchants see every live sale
        sql += " AND s.status='open' AND s.expires_at>?"
        args.append(db.now_iso())
    if category:
        sql += " AND p.category=?"
        args.append(category)
    if product:
        sql += " AND s.product=?"
        args.append(product)
    out = []
    for s in db.rows(sql + " ORDER BY s.id DESC", tuple(args)):
        v = sale_view(s, uid)
        if city and city not in (v["warehouse_city"], v["wholesaler"]["city"]):
            continue
        if q:
            hay = f"{v['product']} {v['wholesaler']['shop']} {v['kind']} {v['warehouse_city']}".lower()
            if q.strip().lower() not in hay:
                continue
        out.append(v)
    return out


def close_sale(sid: int, uid: int) -> dict:
    s = db.one("SELECT * FROM sales WHERE id=?", (sid,))
    if not s or s["wholesaler_id"] != uid:
        raise ApiError(404, "Sale not found")
    db.run("UPDATE sales SET status='closed' WHERE id=?", (sid,))
    return {"status": "closed"}


def buy_sale(sid: int, uid: int, qty: float) -> dict:
    """A merchant buys on their own at the tier their own quantity reaches."""
    s = db.one("SELECT * FROM sales WHERE id=?", (sid,))
    if not s:
        raise ApiError(404, "Sale not found")
    me = groups.get_user(uid)
    if me["role"] != "merchant":
        raise ApiError(403, "Only merchants can buy")
    v = sale_view(s, uid)
    if not v["is_open"]:
        raise ApiError(400, "This sale is closed")
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity must be a number") from None
    if qty <= 0 or qty > v["remaining"]:
        raise ApiError(400, f"Quantity must be between 1 and {v['remaining']:g}")
    price = tier_for(v["tiers"], qty)["price"]
    o = orders.place(uid, s["wholesaler_id"], [{"product": s["product"], "qty": qty}], source=f"sale:{sid}", unit_prices={s["product"]: price})
    db.run("UPDATE sales SET sold_qty=sold_qty+? WHERE id=?", (qty, sid))
    return o


# ------------------------------------------------------------------ pools (a group pooling its orders on one sale)

def pool_view(p: dict, uid: int) -> dict:
    s = db.one("SELECT * FROM sales WHERE id=?", (p["sale_id"],))
    tiers = json.loads(s["tiers"])
    prod = db.one("SELECT unit FROM products WHERE name=?", (s["product"],))
    w = db.one("SELECT shop, rating_avg, rating_count FROM users WHERE id=?", (s["wholesaler_id"],))
    g = db.one("SELECT name FROM groups WHERE id=?", (p["group_id"],))
    commits = db.rows("SELECT pc.user_id, pc.qty, u.shop FROM pool_commitments pc JOIN users u ON u.id=pc.user_id WHERE pc.pool_id=? ORDER BY pc.qty DESC", (p["id"],))
    total = sum(c["qty"] for c in commits)
    cur = tier_for(tiers, total)
    entry = tiers[0]["price"]
    unit_price = cur["price"] if cur else entry
    nxt = next((t for t in tiers if t["min_qty"] > total), None)
    per_unit = max(0.0, entry - unit_price)
    for c in commits:
        c["share_pct"] = round(100 * c["qty"] / total, 1) if total else 0
        c["cost"] = round(c["qty"] * unit_price, 2)
        c["savings"] = round(c["qty"] * per_unit, 2)
    expired = s["expires_at"] < db.now_iso()
    gm = db.one("SELECT admin_id FROM groups WHERE id=?", (p["group_id"],))
    return {"id": p["id"], "sale_id": s["id"], "group_id": p["group_id"], "group": g["name"], "product": s["product"], "unit": prod["unit"],
            "wholesaler": w, "tiers": tiers, "status": p["status"], "created_by": p["created_by"], "commitments": commits,
            "total_qty": total, "participants": len(commits), "entry_price": entry, "current_price": unit_price,
            "current_tier": cur, "next_tier": nxt, "to_next_tier": round(nxt["min_qty"] - total, 1) if nxt else 0,
            "total_savings": round(total * per_unit, 2), "my_commitment": next((c for c in commits if c["user_id"] == uid), None),
            "is_open": p["status"] == "open" and not expired and s["status"] == "open",
            "can_close": p["status"] == "open" and uid in (p["created_by"], gm["admin_id"]) and bool(commits),
            "expires_at": s["expires_at"]}


def group_pools(gid: int, uid: int) -> list[dict]:
    return [pool_view(p, uid) for p in db.rows("SELECT * FROM pools WHERE group_id=? ORDER BY id DESC", (gid,))]


def group_stats(gid: int) -> dict:
    ps = [pool_view(p, 0) for p in db.rows("SELECT * FROM pools WHERE group_id=?", (gid,))]
    return {"pools": len(ps), "open_pools": sum(1 for p in ps if p["is_open"]),
            "pooled_value": round(sum(p["total_qty"] * p["current_price"] for p in ps), 2),
            "total_savings": round(sum(p["total_savings"] for p in ps), 2)}


def start_pool(sid: int, gid: int, uid: int) -> dict:
    groups.require_member(gid, uid)
    s = db.one("SELECT * FROM sales WHERE id=?", (sid,))
    if not s or s["status"] != "open" or s["expires_at"] < db.now_iso():
        raise ApiError(400, "This sale is not open")
    ex = db.one("SELECT id FROM pools WHERE sale_id=? AND group_id=? AND status='open'", (sid, gid))
    if ex:
        raise ApiError(409, f"Your group already has an open pool for this sale (#{ex['id']})")
    pid = db.run("INSERT INTO pools(sale_id,group_id,created_by,created_at) VALUES(?,?,?,?)", (sid, gid, uid, db.now_iso()))
    g = groups.get_group_row(gid)
    u = groups.get_user(uid)
    for m in db.rows("SELECT user_id FROM memberships WHERE group_id=? AND status='active' AND user_id!=?", (gid, uid)):
        db.notify(m["user_id"], "pool", f"{u['shop']} started a pool for {s['product']} in {g['name']} - add your quantity.", f"group:{gid}")
    return {"id": pid}


def commit_pool(pid: int, uid: int, qty: float) -> dict:
    p = db.one("SELECT * FROM pools WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Pool not found")
    groups.require_member(p["group_id"], uid)
    if groups.get_user(uid)["role"] != "merchant":
        raise ApiError(403, "Only merchants can commit")
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity must be a number") from None
    v = pool_view(p, uid)
    if not v["is_open"]:
        raise ApiError(400, "This pool is closed")
    s = db.one("SELECT * FROM sales WHERE id=?", (p["sale_id"],))
    room = s["qty_limit"] - s["sold_qty"] - _reserved(s["id"], uid, pid)
    if qty < 0 or qty > room:
        raise ApiError(400, f"Quantity must be between 0 and {max(0, room):g}")
    if qty == 0:
        db.run("DELETE FROM pool_commitments WHERE pool_id=? AND user_id=?", (pid, uid))
    else:
        db.run("INSERT INTO pool_commitments VALUES(?,?,?) ON CONFLICT(pool_id,user_id) DO UPDATE SET qty=excluded.qty", (pid, uid, qty))
    return pool_view(p, uid)


def close_pool(pid: int, uid: int) -> dict:
    """Initiated by the pool creator or the group admin: one order per member at the final tier price."""
    p = db.one("SELECT * FROM pools WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Pool not found")
    g = groups.get_group_row(p["group_id"])
    if uid not in (p["created_by"], g["admin_id"]):
        raise ApiError(403, "Only the pool starter or the group admin can close it")
    if p["status"] != "open":
        raise ApiError(400, "Pool already closed")
    v = pool_view(p, uid)
    if not v["commitments"]:
        raise ApiError(400, "No commitments yet")
    s = db.one("SELECT * FROM sales WHERE id=?", (p["sale_id"],))
    ids = []
    for c in v["commitments"]:
        o = orders.place(c["user_id"], s["wholesaler_id"], [{"product": s["product"], "qty": c["qty"]}],
                         source=f"pool:{pid}", unit_prices={s["product"]: v["current_price"]})
        ids.append(o["order_id"])
        db.notify(c["user_id"], "order", f"Pool closed at Rs {v['current_price']:g}/{v['unit']} - order #{o['order_id']} created. Awaiting delivery quote.", "orders")
    db.run("UPDATE pools SET status='closed' WHERE id=?", (pid,))
    db.run("UPDATE sales SET sold_qty=sold_qty+? WHERE id=?", (v["total_qty"], s["id"]))
    return {"order_ids": ids, "final_price": v["current_price"], "total_savings": v["total_savings"]}


# ------------------------------------------------------------------ demands (reverse auction)

def create_demand(uid: int, product: str, qty: float, budget, note: str = "", group_id: int | None = None, participants: list[dict] | None = None) -> dict:
    u = groups.get_user(uid)
    if u["role"] != "merchant":
        raise ApiError(403, "Only merchants post demands")
    prod = db.one("SELECT * FROM products WHERE name=?", (product,))
    if not prod:
        raise ApiError(400, "Unknown product")
    try:
        qty = float(qty) if qty is not None else 0.0
        budget = float(budget) if budget not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity and budget must be numbers") from None

    parts_json = None
    cleaned_parts = []
    if participants and isinstance(participants, list) and len(participants) > 0:
        for p in participants:
            try:
                p_uid = int(p.get("user_id") or p.get("id"))
                p_shop = str(p.get("shop") or p.get("name") or "Merchant")
                p_qty = float(p.get("qty") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if p_qty > 0:
                cleaned_parts.append({"user_id": p_uid, "shop": p_shop, "qty": p_qty})
        if cleaned_parts:
            parts_json = json.dumps(cleaned_parts)
            qty = sum(p["qty"] for p in cleaned_parts)

    if qty <= 0:
        raise ApiError(400, "Quantity must be positive")

    did = db.run("INSERT INTO demands(user_id,product,qty,budget,note,group_id,participants,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (uid, product, qty, budget, (note or "").strip()[:200], group_id, parts_json, db.now_iso()))

    label = f"New demand: {qty:g} {prod['unit']} {product} wanted by {u['shop']} ({u['city']})."
    if group_id:
        g = db.one("SELECT name FROM groups WHERE id=?", (group_id,))
        if g:
            label = f"New Collective Group Auction: {qty:g} {prod['unit']} {product} wanted by {g['name']} ({len(cleaned_parts) if cleaned_parts else 1} merchants)."
            db.run("INSERT INTO posts(group_id,user_id,kind,body,status,created_at) VALUES(?,?,?,?,?,?)",
                   (group_id, uid, "announcement", f"📢 🤖 AI published Collective Reverse Auction for {qty:g} {prod['unit']} {product} on behalf of group merchants to regional wholesalers! Wholesalers are now bidding.", "visible", db.now_iso()))

    for w in db.rows("SELECT wholesaler_id FROM catalog WHERE product=? AND stock_qty>=?", (product, qty)):
        db.notify(w["wholesaler_id"], "demand", label, f"demand:{did}")
    return {"id": did}


def _rank_bids(d: dict, bids: list[dict]) -> list[dict]:
    if not bids:
        return []
    lo, hi = min(b["price"] for b in bids), max(b["price"] for b in bids)
    for b in bids:
        price_s = 1.0 if hi == lo else 1 - (b["price"] - lo) / (hi - lo) * 0.8
        rating_s = (b["rating_avg"] / 5) if b["rating_count"] else 0.7
        eta_s = max(0.0, 1 - (b["eta_days"] - 1) / 5)
        b["score"] = round(100 * (0.55 * price_s + 0.25 * rating_s + 0.20 * eta_s), 1)
        b["parts"] = {"price": round(55 * price_s, 1), "rating": round(25 * rating_s, 1), "eta": round(20 * eta_s, 1)}
        b["total"] = round(b["price"] * d["qty"], 2)
        b["within_budget"] = d["budget"] is None or b["total"] <= d["budget"]
    bids.sort(key=lambda b: -b["score"])
    for i, b in enumerate(bids):
        b["rank"] = i + 1
        b["reason"] = ("AI pick: best balance of price, rating and arrival time" if i == 0 else
                       f"Rs {b['price'] - bids[0]['price']:+.2f}/unit vs AI pick, {b['eta_days']}d arrival, rated {b['rating_avg']:.1f}/5")
    return bids


def demand_view(did: int, uid: int) -> dict:
    d = db.one("SELECT d.*, u.name buyer, u.shop buyer_shop, u.city buyer_city, u.rating_avg buyer_rating, u.rating_count buyer_rating_count,"
               " p.unit, p.base_price, p.category FROM demands d JOIN users u ON u.id=d.user_id JOIN products p ON p.name=d.product WHERE d.id=?", (did,))
    if not d:
        raise ApiError(404, "Demand not found")
    me = groups.get_user(uid)
    is_owner = d["user_id"] == uid

    parts = []
    if d.get("participants"):
        try:
            parts = json.loads(d["participants"])
        except Exception:
            parts = []
    d["participants"] = parts
    d["is_collective"] = bool(d.get("group_id") or parts)
    if d.get("group_id"):
        g = db.one("SELECT name, admin_id FROM groups WHERE id=?", (d["group_id"],))
        d["group_name"] = g["name"] if g else None
        d["group_admin_id"] = g["admin_id"] if g else None
    else:
        d["group_name"] = None
        d["group_admin_id"] = None

    latest: dict[int, dict] = {}
    for b in db.rows("SELECT b.*, w.shop, w.name, w.city, w.rating_avg, w.rating_count FROM bids b JOIN users w ON w.id=b.wholesaler_id WHERE b.demand_id=? ORDER BY b.id", (did,)):
        latest[b["wholesaler_id"]] = b
    for b in latest.values():
        cat = db.one("SELECT c.stock_qty, wh.name wh_name, wh.city wh_city, wh.handling_days FROM catalog c JOIN warehouses wh ON wh.id=c.warehouse_id"
                     " WHERE c.wholesaler_id=? AND c.product=?", (b["wholesaler_id"], d["product"]))
        b["warehouse"] = cat["wh_name"] if cat else None
        b["warehouse_city"] = cat["wh_city"] if cat else b["city"]
        b["eta_days"] = db.eta_days(b["warehouse_city"], d["buyer_city"], cat["handling_days"] if cat else 1)
    ranked = _rank_bids(d, list(latest.values()))
    d["lowest_bid"] = min((b["price"] for b in ranked), default=None)
    d["bid_count"] = len(ranked)
    d["market_total"] = round(d["base_price"] * d["qty"], 2)
    d["is_owner"] = is_owner
    d["my_bid"] = next((b for b in ranked if b["wholesaler_id"] == uid), None)
    stock = db.one("SELECT stock_qty FROM catalog WHERE wholesaler_id=? AND product=?", (uid, d["product"])) if me["role"] == "wholesaler" else None
    d["can_bid"] = d["status"] == "open" and me["role"] == "wholesaler" and bool(stock) and stock["stock_qty"] >= d["qty"]
    d["delivery_note"] = "Prices are for the product only. Delivery is quoted by the winning wholesaler after the deal is closed."

    is_participant = any(p.get("user_id") == uid for p in parts)
    is_group_admin = bool(d.get("group_admin_id") and d["group_admin_id"] == uid)
    can_view_bids = is_owner or is_participant or is_group_admin
    d["can_award"] = (is_owner or is_group_admin) and d["status"] == "open" and len(ranked) > 0
    d["bids"] = ranked if can_view_bids else ([d["my_bid"]] if d["my_bid"] else [])
    return d


def list_demands(uid: int, q: str = "", category: str = "", product: str = "", city: str = "", status: str = "") -> list[dict]:
    me = groups.get_user(uid)
    sql = "SELECT d.id FROM demands d JOIN users u ON u.id=d.user_id JOIN products p ON p.name=d.product WHERE 1=1"
    args: list = []
    if me["role"] == "merchant":
        sql += " AND (d.user_id=? OR (d.group_id IS NOT NULL AND d.group_id IN (SELECT group_id FROM memberships WHERE user_id=? AND status='active')))"
        args.extend([uid, uid])
    if status:
        sql += " AND d.status=?"
        args.append(status)
    if category:
        sql += " AND p.category=?"
        args.append(category)
    if product:
        sql += " AND d.product=?"
        args.append(product)
    if city:
        sql += " AND u.city=?"
        args.append(city)
    if q:
        sql += " AND (lower(d.product) LIKE ? OR lower(u.shop) LIKE ?)"
        args += [f"%{q.strip().lower()}%"] * 2
    return [demand_view(r["id"], uid) for r in db.rows(sql + " ORDER BY d.id DESC LIMIT 60", tuple(args))]


def place_bid(did: int, uid: int, price: float) -> dict:
    d = db.one("SELECT * FROM demands WHERE id=?", (did,))
    if not d:
        raise ApiError(404, "Demand not found")
    if d["status"] != "open":
        raise ApiError(400, "This demand is closed")
    me = groups.get_user(uid)
    if me["role"] != "wholesaler":
        raise ApiError(403, "Only wholesalers can bid")
    cat = db.one("SELECT * FROM catalog WHERE wholesaler_id=? AND product=?", (uid, d["product"]))
    if not cat:
        raise ApiError(400, "You do not stock this product")
    if cat["stock_qty"] < d["qty"]:
        raise ApiError(400, f"Insufficient stock (you have {cat['stock_qty']:g})")
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise ApiError(400, "Price must be a number") from None
    prod = db.one("SELECT base_price, unit FROM products WHERE name=?", (d["product"],))
    if price <= 0 or price > prod["base_price"] * 1.5:
        raise ApiError(400, "Price must be positive and within 50% of the market price")
    prev = db.one("SELECT price FROM bids WHERE demand_id=? AND wholesaler_id=? ORDER BY id DESC", (did, uid))
    if prev and price >= prev["price"]:
        raise ApiError(400, f"A revised bid must be lower than your current bid (Rs {prev['price']:g})")
    db.run("INSERT INTO bids(demand_id,wholesaler_id,price,created_at) VALUES(?,?,?,?)", (did, uid, price, db.now_iso()))
    db.notify(d["user_id"], "bid", f"{me['shop']} bid Rs {price:g}/{prod['unit']} on your {d['product']} demand.", f"demand:{did}")
    return demand_view(did, uid)


def close_deal(did: int, uid: int, bid_id: int | None) -> dict:
    """The merchant initiates the close. Creates an order (awaiting the wholesaler's delivery quote)."""
    d = db.one("SELECT * FROM demands WHERE id=?", (did,))
    if not d:
        raise ApiError(404, "Demand not found")
    is_owner = d["user_id"] == uid
    is_admin = False
    if d.get("group_id"):
        g = groups.get_group_row(d["group_id"])
        if g and g["admin_id"] == uid:
            is_admin = True
    if not (is_owner or is_admin):
        raise ApiError(404, "Demand not found")
    if d["status"] != "open":
        raise ApiError(400, "Already closed")
    v = demand_view(did, uid)
    if not v["bids"]:
        raise ApiError(400, "No bids yet")
    chosen = next((b for b in v["bids"] if b["id"] == bid_id), None) if bid_id else v["bids"][0]
    if not chosen:
        raise ApiError(400, "That bid is not a live bid on this demand")

    parts = v.get("participants") or []
    if parts:
        order_ids = []
        for p in parts:
            o = orders.place(p["user_id"], chosen["wholesaler_id"], [{"product": d["product"], "qty": p["qty"]}],
                             source=f"demand:{did}", unit_prices={d["product"]: chosen["price"]})
            order_ids.append(o["order_id"])
            db.notify(p["user_id"], "order", f"Collective auction for {d['product']} awarded to {chosen['shop']} at Rs {chosen['price']:g}/{v['unit']}. Order #{o['order_id']} created!", "orders")
        o_res = {"order_id": order_ids[0], "order_ids": order_ids, "items_total": round(chosen["price"] * d["qty"], 2)}
    else:
        o_res = orders.place(d["user_id"], chosen["wholesaler_id"], [{"product": d["product"], "qty": d["qty"]}],
                             source=f"demand:{did}", unit_prices={d["product"]: chosen["price"]})

    db.run("UPDATE demands SET status='closed', winner_bid_id=? WHERE id=?", (chosen["id"], did))
    for b in v["bids"]:
        if b["wholesaler_id"] != chosen["wholesaler_id"]:
            db.notify(b["wholesaler_id"], "bid", f"Demand #{did} ({d['product']}) was awarded to another wholesaler.")
    return {"order": o_res, "order_id": o_res.get("order_id"), "winner": chosen["shop"], "price": chosen["price"],
            "saved_vs_market": round((v["base_price"] - chosen["price"]) * d["qty"], 2)}


def cancel_demand(did: int, uid: int) -> dict:
    d = db.one("SELECT * FROM demands WHERE id=?", (did,))
    if not d or d["user_id"] != uid:
        raise ApiError(404, "Demand not found")
    if d["status"] != "open":
        raise ApiError(400, "Already closed")
    db.run("UPDATE demands SET status='cancelled' WHERE id=?", (did,))
    return {"status": "cancelled"}
