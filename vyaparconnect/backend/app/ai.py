"""Rule-based AI: Procurement Agent, Predictive Demand, Smart Negotiator.

Everything is deterministic so the demo never depends on an external LLM. The parser accepts English plus a few
Tamil/Hindi product words ("arisi", "chawal", "tel"), which is also what the voice input feeds into.
"""
import json
import math
import re
from datetime import date, datetime, timedelta

from . import db, orders
from .db import ApiError

# ---------------------------------------------------------------- procurement agent

ALIASES = {
    "Rice": ["rice", "arisi", "chawal", "basmati"],
    "Sunflower Oil": ["sunflower oil", "cooking oil", "oil", "ennai", "tel"],
    "Toor Dal": ["toor dal", "tur dal", "dal", "dhal", "paruppu", "toor"],
    "Sugar": ["sugar", "cheeni", "sakkarai"],
    "Wheat Flour": ["wheat flour", "flour", "atta", "maida", "wheat"],
    "Tea Powder": ["tea powder", "tea", "chai"],
    "Biscuits": ["biscuits", "biscuit"],
    "Detergent": ["detergent", "washing powder"],
    "Soap": ["soap", "soaps"],
    "Shampoo Sachets": ["shampoo sachets", "shampoo"],
    "Noodles": ["noodles", "maggi"],
    "Salt": ["salt", "uppu", "namak"],
}
_ALIAS_LIST = sorted(((a, p) for p, al in ALIASES.items() for a in al), key=lambda x: -len(x[0]))
_BUDGET = re.compile(
    r"(?:budget|within|under|upto|up to|max(?:imum)?|only)\s*(?:of|is|:)?\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*(?:\.\d+)?)"
    r"|(?:rs\.?|inr|₹)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:budget|max)", re.I)
_QTY = re.compile(r"(\d+(?:\.\d+)?)")


def parse_request(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ApiError(400, "Tell me what you need, e.g. '50 kg rice, 20 L oil, budget 6000'")
    budget = None
    m = _BUDGET.search(text)
    if m:
        budget = float((m.group(1) or m.group(2)).replace(",", ""))
        text = (text[:m.start()] + " " + text[m.end():])
    lines, unknown = [], []
    for chunk in re.split(r",|;|\band\b|&|\+|\n", text, flags=re.I):
        c = chunk.strip().lower()
        if not c:
            continue
        found = next((p for a, p in _ALIAS_LIST if re.search(rf"\b{re.escape(a)}\b", c)), None)
        q = _QTY.search(c)
        if found and q:
            lines.append({"product": found, "qty": float(q.group(1))})
        elif found:
            lines.append({"product": found, "qty": None})
        elif re.sub(r"[^a-z]", "", c):
            unknown.append(chunk.strip())
    merged: dict[str, dict] = {}
    for ln in lines:
        typical = db.one("SELECT typical_qty, unit FROM products WHERE name=?", (ln["product"],))
        qty = ln["qty"] if ln["qty"] else typical["typical_qty"]
        prev = merged.get(ln["product"])
        merged[ln["product"]] = {"product": ln["product"], "qty": (prev["qty"] if prev else 0) + qty,
                                 "unit": typical["unit"], "assumed_qty": ln["qty"] is None}
    return {"lines": list(merged.values()), "budget": budget, "unrecognised": unknown}


def _score_suppliers(uid: int, lines: list[dict]) -> list[dict]:
    me = db.one("SELECT * FROM users WHERE id=?", (uid,))
    my_wholesalers = {r["user_id"] for r in db.rows(
        "SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE u.role='wholesaler' AND m.status='active'"
        " AND m.group_id IN (SELECT group_id FROM memberships WHERE user_id=? AND status='active')", (uid,))}
    cands = []
    for w in db.rows("SELECT * FROM users WHERE role='wholesaler'"):
        covered, missing, total, ref, days = [], [], 0.0, 0.0, 0
        for ln in lines:
            row = db.one("SELECT c.*, p.base_price, p.unit FROM catalog c JOIN products p ON p.name=c.product"
                         " WHERE c.wholesaler_id=? AND c.product=?", (w["id"], ln["product"]))
            if not row or row["stock_qty"] < ln["qty"]:
                missing.append(ln["product"])
                continue
            cost = round(row["price"] * ln["qty"], 2)
            total += cost
            ref += row["base_price"] * ln["qty"]
            days = max(days, row["delivery_days"])
            covered.append({"product": ln["product"], "qty": ln["qty"], "unit": row["unit"],
                            "unit_price": row["price"], "cost": cost})
        if not covered:
            continue
        extra = 0 if w["city"] == me["city"] else 2
        cands.append({"wholesaler": {k: w[k] for k in ("id", "name", "shop", "city", "trust", "on_time_rate")},
                      "lines": covered, "missing": missing, "total": round(total, 2), "ratio": total / ref,
                      "delivery_days": days + extra, "same_city": w["city"] == me["city"],
                      "in_my_groups": w["id"] in my_wholesalers})
    if not cands:
        return []
    best = min(c["ratio"] for c in cands)
    for c in cands:
        price_s = max(0.0, 1 - (c["ratio"] - best) / 0.10)
        deliv_s = max(0.0, 1 - (c["delivery_days"] - 1) / 4)
        trust_s = c["wholesaler"]["trust"] / 100
        cover = len(c["lines"]) / len(lines)
        base = 0.5 * price_s + 0.25 * deliv_s + 0.25 * trust_s
        c["score"] = round(100 * base * cover + (3 if c["in_my_groups"] else 0), 1)
        c["score_parts"] = {"price": round(50 * price_s, 1), "delivery": round(25 * deliv_s, 1),
                            "trust": round(25 * trust_s, 1)}
        c["coverage"] = round(100 * cover)
        c["vs_market_pct"] = round((1 - c["ratio"]) * 100, 1)
        del c["ratio"]
    cands.sort(key=lambda c: -c["score"])
    return cands


def procurement(uid: int, text: str) -> dict:
    from . import deals  # lazy: deals -> groups -> db only, but keep module graph simple

    parsed = parse_request(text)
    lines = parsed["lines"]
    if not lines:
        raise ApiError(400, "I couldn't recognise any product. Try e.g. '50 kg rice and 20 L oil'.")
    ranked = _score_suppliers(uid, lines)
    if not ranked:
        raise ApiError(404, "No supplier currently has these items in stock")
    budget = parsed["budget"]
    for i, c in enumerate(ranked):
        c["rank"] = i + 1
        c["within_budget"] = budget is None or c["total"] <= budget
        why = []
        if c["rank"] == 1:
            why.append("Best overall mix of price, delivery and trust")
        if c["vs_market_pct"] > 0:
            why.append(f"{c['vs_market_pct']}% below market price")
        why.append(f"delivers in {c['delivery_days']} day(s)")
        why.append(f"trust {c['wholesaler']['trust']}/100")
        if c["in_my_groups"]:
            why.append("already a supplier in your group")
        if c["missing"]:
            why.append("cannot supply: " + ", ".join(c["missing"]))
        if budget is not None and not c["within_budget"]:
            why.append(f"Rs {c['total'] - budget:,.0f} over budget")
        c["reason"] = "; ".join(why)
    top = ranked[:3]
    note = None
    if budget is not None:
        ok = [c for c in ranked if c["within_budget"] and not c["missing"]]
        if ok:
            note = f"{len(ok)} supplier(s) fit your budget of Rs {budget:,.0f}."
        else:
            best = ranked[0]
            scale = budget / best["total"] if best["total"] else 0
            if len(lines) == 1:
                ln = best["lines"][0]
                note = (f"Rs {budget:,.0f} buys about {math.floor(budget / ln['unit_price'])} {ln['unit']} of "
                        f"{ln['product']} at the best price (Rs {ln['unit_price']:g}/{ln['unit']}).")
            else:
                note = (f"Your list costs Rs {best['total']:,.0f} at the best supplier - about "
                        f"{round((1 - scale) * 100)}% over your Rs {budget:,.0f} budget. Reduce quantities or use a group pool.")
    pools = []
    for ln in lines:
        for d in db.rows("SELECT d.* FROM deals d JOIN memberships m ON m.group_id=d.group_id"
                         " WHERE m.user_id=? AND m.status='active' AND d.product=? AND d.status='open'",
                         (uid, ln["product"])):
            v = deals.deal_view(d, uid)
            if v["is_open"]:
                g = db.one("SELECT name FROM groups WHERE id=?", (d["group_id"],))
                pools.append({"deal_id": v["id"], "group_id": d["group_id"], "group": g["name"], "product": v["product"],
                              "current_price": v["current_price"], "best_tier_price": v["tiers"][-1]["price"],
                              "best_tier_qty": v["tiers"][-1]["min_qty"], "unit": v["unit"]})
    return {"parsed": parsed, "suppliers": top, "all_count": len(ranked), "budget_note": note, "group_pools": pools,
            "summary": (f"Compared {len(ranked)} supplier(s). Top pick: {top[0]['wholesaler']['shop']} at "
                        f"Rs {top[0]['total']:,.0f} ({top[0]['delivery_days']} day delivery).")}


# ---------------------------------------------------------------- predictive demand

FESTIVALS = [  # (name, date, product multipliers)  -- approximate dates, demo data
    ("Diwali", date(2026, 11, 8), {"Sugar": 1.8, "Sunflower Oil": 1.6, "Toor Dal": 1.3, "Biscuits": 1.7, "Soap": 1.3}),
    ("Pongal", date(2027, 1, 14), {"Rice": 1.8, "Sugar": 1.6, "Sunflower Oil": 1.4, "Toor Dal": 1.4}),
    ("Ugadi / Tamil New Year", date(2027, 4, 14), {"Rice": 1.4, "Sugar": 1.3, "Sunflower Oil": 1.3}),
    ("Eid", date(2027, 3, 10), {"Rice": 1.6, "Sugar": 1.5, "Sunflower Oil": 1.5, "Tea Powder": 1.3}),
]


def _festival(as_of: date, force: str | None) -> tuple[str, date, dict] | None:
    if force:
        f = next((x for x in FESTIVALS if x[0].lower().startswith(force.lower())), None)
        if not f:
            raise ApiError(400, "Unknown festival. Try Diwali, Pongal, Eid or Ugadi.")
        return f
    for f in sorted(FESTIVALS, key=lambda x: x[1]):
        if 0 <= (f[1] - as_of).days <= 21:
            return f
    return None


def forecast(uid: int, festival: str | None = None, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    fest = _festival(as_of, festival)
    out = []
    for inv in db.rows("SELECT i.*, p.unit, p.typical_qty FROM inventory i JOIN products p ON p.name=i.product"
                       " WHERE i.user_id=?", (uid,)):
        since = (as_of - timedelta(days=60)).isoformat()
        h = db.rows("SELECT qty, day FROM history WHERE user_id=? AND product=? AND day>=? ORDER BY day",
                    (uid, inv["product"], since))
        if not h:
            continue
        window = max(14, min(60, (as_of - date.fromisoformat(h[0]["day"])).days + 1))
        daily = sum(x["qty"] for x in h) / window
        # purchases that were just added to inventory shouldn't be double counted as use
        mult = fest[2].get(inv["product"], 1.0) if fest else 1.0
        need = daily * mult
        days_left = inv["stock"] / need if need > 0 else 999
        level = "critical" if days_left <= 4 else ("warning" if days_left <= 7 else "ok")
        reorder = max(0.0, need * 14 - inv["stock"])
        reorder = math.ceil(reorder / 5) * 5 if inv["unit"] in ("kg", "L") else math.ceil(reorder)
        stock_out = (as_of + timedelta(days=int(days_left))).isoformat() if days_left < 999 else None
        out.append({"product": inv["product"], "unit": inv["unit"], "stock": round(inv["stock"], 1),
                    "daily_use": round(daily, 2), "festival_multiplier": mult,
                    "days_left": round(days_left, 1), "stock_out_date": stock_out, "level": level,
                    "suggested_qty": reorder if level != "ok" else 0,
                    "message": (f"{inv['product']} will run out in ~{max(0, math.floor(days_left))} day(s)"
                                + (f" ({fest[0]} demand x{mult})" if mult > 1 else "")) if level != "ok" else
                               f"{inv['product']} stock is healthy (~{math.floor(days_left)} days)"})
    order = {"critical": 0, "warning": 1, "ok": 2}
    out.sort(key=lambda x: (order[x["level"]], x["days_left"]))
    return {"as_of": as_of.isoformat(),
            "festival": ({"name": fest[0], "date": fest[1].isoformat(), "days_away": (fest[1] - as_of).days}
                         if fest else None),
            "items": out, "alerts": [x for x in out if x["level"] != "ok"]}


# ---------------------------------------------------------------- smart negotiator

def _seller_floor(list_price: float, qty: float, typical: float) -> float:
    return round(list_price * (1 - min(0.12, 0.04 + 0.01 * qty / typical)), 2)


def negotiate(uid: int, wholesaler_id: int, product: str, qty: float, max_price: float) -> dict:
    """Buyer agent vs seller agent. The merchant only sets a ceiling; the seller's floor is private."""
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u or u["role"] != "merchant":
        raise ApiError(403, "Only merchants can negotiate")
    try:
        qty, max_price = float(qty), float(max_price)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity and max price must be numbers") from None
    if qty <= 0 or max_price <= 0:
        raise ApiError(400, "Quantity and max price must be positive")
    row = db.one("SELECT c.*, p.typical_qty, p.unit, w.shop FROM catalog c JOIN products p ON p.name=c.product"
                 " JOIN users w ON w.id=c.wholesaler_id WHERE c.wholesaler_id=? AND c.product=?", (wholesaler_id, product))
    if not row:
        raise ApiError(404, "That wholesaler does not stock this product")
    if row["stock_qty"] < qty:
        raise ApiError(400, f"Only {row['stock_qty']:g} {row['unit']} in stock")
    lp = row["price"]
    floor = _seller_floor(lp, qty, row["typical_qty"])
    buyer = round(min(max_price, lp * 0.85), 2)
    seller = lp
    unit = row["unit"]
    t = [{"agent": "seller", "price": seller, "text": f"Seller Agent ({row['shop']}): List price Rs {seller:g}/{unit} for {qty:g} {unit}."}]
    agreed, status = None, "no_deal"
    for rnd_no in range(1, 6):
        t.append({"agent": "buyer", "price": buyer,
                  "text": f"Buyer Agent: I can offer Rs {buyer:g}/{unit} for {qty:g} {unit}."})
        if buyer >= seller:
            agreed, status = seller, "deal"
            break
        if buyer >= floor:  # seller accepts anything at/above floor
            agreed, status = buyer, "deal"
            t.append({"agent": "seller", "price": buyer, "text": f"Seller Agent: Accepted at Rs {buyer:g}/{unit}."})
            break
        new_seller = round(max(floor, seller - (seller - floor) * 0.5), 2)
        if rnd_no == 5 or new_seller >= seller - 0.01:
            break
        seller = new_seller
        t.append({"agent": "seller", "price": seller, "text": f"Seller Agent: Counter - Rs {seller:g}/{unit}."})
        # buyer concedes 60% of the gap but never beyond the user's ceiling
        buyer = round(min(max_price, buyer + (seller - buyer) * 0.6), 2)
        if buyer >= seller:
            t.append({"agent": "buyer", "price": buyer, "text": f"Buyer Agent: Meeting you at Rs {seller:g}/{unit}."})
            agreed, status = seller, "deal"
            break
    if status != "deal" and seller <= max_price:  # the last counter is within the user's limit
        agreed, status = seller, "deal"
        t.append({"agent": "buyer", "price": seller, "text": f"Buyer Agent: Rs {seller:g}/{unit} is within my limit - deal."})
    if status == "deal":
        t.append({"agent": "system", "price": agreed,
                  "text": f"Deal at Rs {agreed:g}/{unit} - saves Rs {(lp - agreed) * qty:,.0f} versus list."})
    else:
        t.append({"agent": "system", "price": None,
                  "text": f"No deal: seller would not go below Rs {seller:g}/{unit}; your limit is Rs {max_price:g}."})
    nid = db.run("INSERT INTO negotiations(user_id,wholesaler_id,product,qty,list_price,buyer_limit,agreed_price,status,"
                 "transcript,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (uid, wholesaler_id, product, qty, lp, max_price, agreed, status, json.dumps(t), db.now_iso()))
    return {"id": nid, "status": status, "list_price": lp, "agreed_price": agreed, "qty": qty, "unit": unit,
            "product": product, "wholesaler": row["shop"], "transcript": t,
            "savings": round((lp - agreed) * qty, 2) if agreed else 0, "total": round(agreed * qty, 2) if agreed else None}


def accept_negotiation(nid: int, uid: int) -> dict:
    n = db.one("SELECT * FROM negotiations WHERE id=?", (nid,))
    if not n or n["user_id"] != uid:
        raise ApiError(404, "Negotiation not found")
    if n["status"] != "deal":
        raise ApiError(400, "There is no deal to accept")
    if n["order_id"]:
        raise ApiError(409, "Already ordered")
    res = orders.place(uid, n["wholesaler_id"], [{"product": n["product"], "qty": n["qty"]}],
                       source=f"negotiation:{nid}", unit_prices={n["product"]: n["agreed_price"]})
    db.run("UPDATE negotiations SET order_id=? WHERE id=?", (res["order_id"], nid))
    return res
