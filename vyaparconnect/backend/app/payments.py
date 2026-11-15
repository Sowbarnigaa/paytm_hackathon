"""Payments for a quoted order via a SIMULATED Paytm Payment Gateway (no real money moves).

Three ways to pay:  full  - single shot
                    parts - pay the wholesaler in 2-4 instalments (first now, rest every 7 days)
                    loan  - Paytm loan pays the wholesaler in full; the merchant repays EMIs (see credit.py)

Flow: start() creates a payment intent (txn_id + pay_url) -> the UI shows the gateway page -> complete() settles it."""
import secrets
from datetime import date, timedelta

from . import credit, db, orders
from .db import ApiError

METHODS = ("upi", "card", "netbanking", "wallet")
MIN_PARTS_TOTAL = 1000
INSTALLMENT_GAP_DAYS = 7


def split(total: float, parts: int) -> list[float]:
    """Equal instalments; any paise left over go on the first one."""
    each = int(total * 100 // parts) / 100
    amounts = [each] * parts
    amounts[0] = round(total - each * (parts - 1), 2)
    return amounts


def options(oid: int, uid: int) -> dict:
    o = orders.get_order(oid, uid)
    if o["status"] != "quoted" or o["role"] != "buyer":
        raise ApiError(400, "Payment options appear once the wholesaler has quoted delivery")
    total = o["total"]
    parts = []
    if total >= MIN_PARTS_TOTAL:
        for n in (2, 3, 4):
            a = split(total, n)
            parts.append({"parts": n, "first": a[0], "then": a[-1], "gap_days": INSTALLMENT_GAP_DAYS, "amounts": a})
    offer = credit.offer(uid, total)
    loan = {"eligible": offer["eligible"] and total <= offer["available"], "available": offer["available"], "tier": offer["tier"],
            "rate": offer["rate"], "plans": offer["plans"], "note": offer["note"]}
    if offer["eligible"] and total > offer["available"]:
        loan["note"] = f"Order total Rs {total:,.0f} exceeds your available credit Rs {offer['available']:,.0f}."
    return {"order_id": oid, "items_total": o["items_total"], "delivery_charge": o["delivery_charge"], "total": total,
            "full": {"amount": total}, "parts": parts, "parts_note": None if parts else f"Pay in parts needs an order of Rs {MIN_PARTS_TOTAL:,} or more.",
            "loan": loan, "methods": list(METHODS)}


def _intent(o: dict, uid: int, amount: float, kind: str, parts=None, installment_no=None) -> dict:
    txn = "VCP" + secrets.token_hex(6).upper()
    db.run("INSERT INTO payment_intents(txn_id,order_id,user_id,amount,kind,parts,installment_no,created_at) VALUES(?,?,?,?,?,?,?,?)",
           (txn, o["id"], uid, amount, kind, parts, installment_no, db.now_iso()))
    return {"txn_id": txn, "pay_url": f"/#/pay/{txn}", "amount": amount, "kind": kind, "order_id": o["id"]}


def start(oid: int, uid: int, mode: str, parts=None, tenure=None) -> dict:
    o = orders.get_order(oid, uid)
    if o["role"] != "buyer":
        raise ApiError(403, "Only the buyer can pay")
    if o["status"] != "quoted":
        raise ApiError(400, "Order is not awaiting payment")
    for i in db.rows("SELECT txn_id FROM payment_intents WHERE order_id=? AND status='pending'", (oid,)):
        db.run("UPDATE payment_intents SET status='expired' WHERE txn_id=?", (i["txn_id"],))
    total = o["total"]
    if mode == "full":
        return _intent(o, uid, total, "full")
    if mode == "parts":
        try:
            n = int(parts)
        except (TypeError, ValueError):
            raise ApiError(400, "Choose 2, 3 or 4 parts") from None
        if n not in (2, 3, 4) or total < MIN_PARTS_TOTAL:
            raise ApiError(400, f"Pay in parts needs 2-4 parts and an order of Rs {MIN_PARTS_TOTAL:,}+")
        return _intent(o, uid, split(total, n)[0], "parts", parts=n)
    if mode == "loan":
        offer = credit.offer(uid, total)
        if not offer["eligible"] or total > offer["available"]:
            raise ApiError(400, f"Order Rs {total:,.0f} exceeds your available credit Rs {offer['available']:,.0f}")
        try:
            tenure = int(tenure)
        except (TypeError, ValueError):
            raise ApiError(400, "Choose an EMI tenure") from None
        if tenure not in {p["tenure"] for p in offer["plans"]}:
            raise ApiError(400, "Choose a valid EMI tenure")
        return _intent(o, uid, total, "loan", parts=tenure)
    raise ApiError(400, "Pay mode must be full, parts or loan")


def pay_installment(oid: int, uid: int) -> dict:
    o = orders.get_order(oid, uid)
    nxt = o["next_installment"]
    if o["role"] != "buyer" or not nxt:
        raise ApiError(400, "No instalment is due on this order")
    return _intent(o, uid, nxt["amount"], "installment", installment_no=nxt["no"])


def gateway(txn_id: str, uid: int) -> dict:
    t = db.one("SELECT * FROM payment_intents WHERE txn_id=?", (txn_id,))
    if not t or t["user_id"] != uid:
        raise ApiError(404, "Transaction not found")
    o = orders.get_order(t["order_id"], uid)
    t["merchant"] = o["wholesaler"]["shop"]
    t["order_total"] = o["total"]
    t["methods"] = list(METHODS)
    t["description"] = {"full": "Single payment", "parts": f"Part 1 of {t['parts']}", "installment": f"Instalment {t['installment_no']}",
                        "loan": f"Paytm loan - {t['parts']} month EMI"}[t["kind"]]
    return t


def _record(o: dict, uid: int, amount: float, kind: str, method: str | None, txn: str) -> None:
    db.run("INSERT INTO payments(order_id,user_id,wholesaler_id,amount,kind,method,txn_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
           (o["id"], uid, o["wholesaler_id"], amount, kind, method, txn, db.now_iso()))
    db.run("UPDATE orders SET paid_amount=ROUND(paid_amount+?,2), updated_at=? WHERE id=?", (amount, db.now_iso(), o["id"]))


def complete(txn_id: str, uid: int, method: str, success: bool = True, autopay: bool = False) -> dict:
    t = db.one("SELECT * FROM payment_intents WHERE txn_id=?", (txn_id,))
    if not t or t["user_id"] != uid:
        raise ApiError(404, "Transaction not found")
    if t["status"] != "pending":
        raise ApiError(409, f"Transaction already {t['status']}")
    if method not in METHODS:
        raise ApiError(400, "Choose UPI, card, netbanking or wallet")
    if not success:
        db.run("UPDATE payment_intents SET status='failed', method=? WHERE txn_id=?", (method, txn_id))
        return {"status": "failed", "txn_id": txn_id, "message": "Payment failed - nothing was charged. Try again."}
    o = orders.get_order(t["order_id"], uid)
    kind = t["kind"]
    ts = db.now_iso()
    loan = None
    if kind == "full":
        _record(o, uid, t["amount"], "full", method, txn_id)
    elif kind == "parts":
        amounts = split(o["total"], t["parts"])
        for k, a in enumerate(amounts, start=1):
            due = (date.today() + timedelta(days=INSTALLMENT_GAP_DAYS * (k - 1))).isoformat()
            db.run("INSERT INTO installments(order_id,no,amount,due_date,status,paid_at,txn_id) VALUES(?,?,?,?,?,?,?)",
                   (o["id"], k, a, due, "paid" if k == 1 else "due", ts if k == 1 else None, txn_id if k == 1 else None))
        _record(o, uid, t["amount"], "part", method, txn_id)
    elif kind == "installment":
        db.run("UPDATE installments SET status='paid', paid_at=?, txn_id=? WHERE order_id=? AND no=?", (ts, txn_id, o["id"], t["installment_no"]))
        _record(o, uid, t["amount"], "installment", method, txn_id)
    elif kind == "loan":
        loan = credit.create_loan(uid, o["total"], t["parts"], autopay, [o["id"]])
        _record(o, uid, o["total"], "loan", "paytm_loan", txn_id)
    db.run("UPDATE payment_intents SET status='success', method=? WHERE txn_id=?", (method, txn_id))
    if o["status"] == "quoted":
        db.run("UPDATE orders SET status='confirmed', pay_mode=?, updated_at=? WHERE id=?", (kind if kind != "installment" else "parts", ts, o["id"]))
        db.notify(o["wholesaler_id"], "payment", f"Order #{o['id']} confirmed - {o['buyer']['shop']} paid Rs {t['amount']:,.0f}"
                  + (" via a Paytm loan" if kind == "loan" else (" (part payment)" if kind == "parts" else "")) + ". Please ship.", f"order:{o['id']}")
    else:
        db.notify(o["wholesaler_id"], "payment", f"Instalment of Rs {t['amount']:,.0f} received for order #{o['id']}.", f"order:{o['id']}")
    return {"status": "success", "txn_id": txn_id, "amount": t["amount"], "order": orders.get_order(o["id"], uid), "loan": loan,
            "message": "Payment successful"}
