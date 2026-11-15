"""Credit scoring, CIBIL-style bureau check, loan offers and EMI autopay.
ALL SIMULATED: no real bureau pull, lending or UPI mandate. The 'bureau score' is a stored demo value per merchant."""
import json
from datetime import datetime, timedelta, timezone

from . import db
from .db import ApiError

# min composite score, name, limit (Rs), max tenure (months), rate % p.a., approval
TIERS = [
    (750, "Prime", 100000, 12, 12.0, "Instant"),
    (700, "Good", 60000, 9, 14.0, "Instant"),
    (650, "Fair", 30000, 6, 17.0, "Quick review"),
    (0, "Starter", 10000, 3, 20.0, "Group-backed"),
]


def emi(principal: float, rate_pa: float, months: int) -> float:
    r = rate_pa / 1200
    if r == 0:
        return round(principal / months, 2)
    f = (1 + r) ** months
    return round(principal * r * f / (f - 1), 2)


def breakdown(uid: int) -> dict:
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "User not found")
    bureau = u["credit_score"]
    ontime = round((u["on_time_rate"] - 0.85) * 100)
    n_orders = db.one("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status!='cancelled'", (uid,))["n"]
    orders = min(15, n_orders * 3)
    groups_n = db.one("SELECT COUNT(*) n FROM memberships WHERE user_id=? AND status='active'", (uid,))["n"]
    group = 0 if groups_n == 0 else (10 if groups_n == 1 else 15)
    rating = round((u["rating_avg"] - 3) * 5) if u["rating_count"] else 0           # +-10 pts from 1-5 star reviews
    paid = db.one("SELECT COALESCE(SUM(paid_emis),0) n FROM loans WHERE user_id=?", (uid,))["n"]
    emi_bonus = min(30, paid * 2)
    parts = [("Bureau score", bureau), ("On-time payment history", ontime),
             ("Procurement activity on Paytm", orders), ("Group membership", group),
             ("Review rating (1-5 stars)", rating), ("On-time EMIs repaid", emi_bonus)]
    composite = max(300, min(900, sum(v for _, v in parts)))
    return {"composite": composite, "groups": groups_n,
            "factors": [{"name": n, "points": v} for n, v in parts]}


def _tier(score: int) -> tuple:
    return next(t for t in TIERS if score >= t[0])


def outstanding(uid: int) -> float:
    return round(sum(l["amount"] * (1 - l["paid_emis"] / l["tenure"])
                     for l in db.rows("SELECT * FROM loans WHERE user_id=? AND status='active'", (uid,))), 2)


def offer(uid: int, amount: float | None = None) -> dict:
    b = breakdown(uid)
    _, name, limit, max_tenure, rate, approval = _tier(b["composite"])
    note = None
    if name == "Starter" and b["groups"] == 0:
        limit, note = 0, "Starter loans are group-backed - join a group to unlock credit."
    used = outstanding(uid)
    available = max(0, round(limit - used, 2))
    plans = []
    if available > 0:
        amt = min(amount, available) if amount else available
        for n in (1, 3, 6, 9, 12):
            if n <= max_tenure:
                e = emi(amt, rate, n)
                plans.append({"tenure": n, "emi": e, "total": round(e * n, 2), "interest": round(e * n - amt, 2)})
    return {"score": b["composite"], "factors": b["factors"], "tier": name, "approval": approval, "rate": rate,
            "limit": limit, "outstanding": used, "available": available, "max_tenure": max_tenure,
            "plans": plans, "plan_amount": (min(amount, available) if amount else available) if available else 0,
            "note": note, "eligible": available > 0}


def create_loan(uid: int, amount: float, tenure: int, autopay: bool, order_ids: list[int]) -> dict:
    o = offer(uid)
    if not o["eligible"]:
        raise ApiError(400, o["note"] or "No credit available")
    if amount <= 0 or amount > o["available"]:
        raise ApiError(400, f"Loan amount must be between 1 and Rs {o['available']:.0f}")
    if tenure not in {p["tenure"] for p in o["plans"]}:
        raise ApiError(400, f"Tenure must be one of {[p['tenure'] for p in o['plans']]} months")
    e = emi(amount, o["rate"], tenure)
    lid = db.run("INSERT INTO loans(user_id,amount,tenure,rate,emi,autopay,mandate,order_ids,created_at)"
                 " VALUES(?,?,?,?,?,?,?,?,?)",
                 (uid, amount, tenure, o["rate"], e, 1 if autopay else 0,
                  "SIM-UPI-AUTOPAY" if autopay else None, json.dumps(order_ids), db.now_iso()))
    return get_loan(lid, uid)


def _schedule(l: dict) -> list[dict]:
    start = datetime.fromisoformat(l["created_at"])
    out = []
    for k in range(1, l["tenure"] + 1):
        out.append({"no": k, "due": (start + timedelta(days=30 * k)).date().isoformat(), "amount": l["emi"],
                    "status": "paid" if k <= l["paid_emis"] else ("next" if k == l["paid_emis"] + 1 else "upcoming")})
    return out


def get_loan(lid: int, uid: int) -> dict:
    l = db.one("SELECT * FROM loans WHERE id=?", (lid,))
    if not l or l["user_id"] != uid:
        raise ApiError(404, "Loan not found")
    l["schedule"] = _schedule(l)
    l["order_ids"] = json.loads(l["order_ids"])
    l["remaining"] = round(l["emi"] * (l["tenure"] - l["paid_emis"]), 2)
    return l


def my_loans(uid: int) -> list[dict]:
    return [get_loan(r["id"], uid) for r in db.rows("SELECT id FROM loans WHERE user_id=? ORDER BY id DESC", (uid,))]


def set_autopay(lid: int, uid: int, on: bool) -> dict:
    l = get_loan(lid, uid)
    if l["status"] != "active":
        raise ApiError(400, "Loan is closed")
    db.run("UPDATE loans SET autopay=?, mandate=? WHERE id=?", (1 if on else 0, "SIM-UPI-AUTOPAY" if on else None, lid))
    return get_loan(lid, uid)


def pay_emi(lid: int, uid: int, mode: str) -> dict:
    """mode='manual' = merchant pays; mode='autopay' simulates the scheduled debit (requires an active mandate)."""
    l = get_loan(lid, uid)
    if l["status"] != "active":
        raise ApiError(400, "Loan is already closed")
    if mode == "autopay" and not l["autopay"]:
        raise ApiError(400, "Autopay is not enabled for this loan")
    if mode not in ("manual", "autopay"):
        raise ApiError(400, "Mode must be manual or autopay")
    paid = l["paid_emis"] + 1
    db.run("UPDATE loans SET paid_emis=?, status=? WHERE id=?", (paid, "closed" if paid >= l["tenure"] else "active", lid))
    return get_loan(lid, uid)


# ------------------------------------------------------------------ CIBIL-style bureau check (SIMULATED)

DEMO_OTP = "123456"          # stand-in for the OTP a real bureau/consent flow would send to the merchant's mobile
BANDS = [(750, "Excellent", "Eligible for the best Paytm credit offers."), (700, "Good", "Eligible for most offers."),
         (650, "Fair", "Limited offers - improve on-time payments."), (0, "Needs work", "Build history with small, on-time orders.")]


def _band(score: int) -> dict:
    _, name, tip = next(b for b in BANDS if score >= b[0])
    return {"band": name, "tip": tip}


def cibil_status(uid: int) -> dict:
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "User not found")
    if u["role"] != "merchant":
        return {"eligible": False, "reason": "Credit score check is for merchants only", "checked": None}
    c = db.one("SELECT * FROM cibil_checks WHERE user_id=?", (uid,))
    return {"eligible": True, "checked": ({"score": c["score"], "checked_at": c["checked_at"], **_band(c["score"])} if c else None),
            "simulated": True}


def cibil_check(uid: int, consent: bool, otp: str) -> dict:
    """Authenticated (consent + OTP) soft check. The returned score is the merchant's stored demo bureau value."""
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u or u["role"] != "merchant":
        raise ApiError(403, "Credit score check is available to merchants only")
    if not consent:
        raise ApiError(400, "Please give consent to fetch your credit score")
    if str(otp or "").strip() != DEMO_OTP:
        raise ApiError(401, "Invalid OTP")
    score = max(300, min(900, int(u["credit_score"])))
    db.run("INSERT INTO cibil_checks VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET score=excluded.score, checked_at=excluded.checked_at",
           (uid, score, db.now_iso()))
    return cibil_status(uid)
