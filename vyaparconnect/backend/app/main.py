"""Paytm VyaparConnect AI - FastAPI app (v2). Serves the REST API and the single-page UI from one process.

Auth: email + password sign-up / sign-in, then `Authorization: Bearer <token>` (see auth.py).
Set VC_DEMO_AUTH=1 to also accept the demo role-switcher header `X-User-Id` (and enable /api/reset).
"""
import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, auth, credit, db, groups, market, merchant, orders, payments, seed
from .db import ApiError

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="Paytm VyaparConnect AI", version="2.0")


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


def _has_auth_schema() -> bool:
    with closing(sqlite3.connect(db.db_path())) as c:
        return any(r[1] == "email" for r in c.execute("PRAGMA table_info(users)"))


@app.on_event("startup")
def startup() -> None:
    # A database created before login existed has no email/password columns: rebuild the (demo) data once.
    if not os.path.exists(db.db_path()) or not _has_auth_schema():
        seed.seed()


def current_user(authorization: str | None = Header(None), x_user_id: int | None = Header(None)) -> int:
    return auth.authenticate(authorization, x_user_id)


UID = Depends(current_user)


# ---------------------------------------------------------------- authentication

@app.get("/api/auth/config")
def auth_config():
    return {"demo": auth.demo_auth(), "cities": db.CITIES, "demo_password": seed.DEMO_PASSWORD if auth.demo_auth() else None}


@app.post("/api/auth/register")
def auth_register(body: dict = Body(...)):
    return auth.register(body)


@app.post("/api/auth/login")
def auth_login(body: dict = Body(...)):
    return auth.login(body)


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(None), uid: int = UID):
    return auth.logout(authorization)


# ---------------------------------------------------------------- session / reference data

@app.post("/api/reset")
def reset():
    if not auth.demo_auth():
        raise ApiError(403, "Reset is only available in demo mode (VC_DEMO_AUTH=1)")
    seed.seed()
    return {"ok": True}


@app.get("/api/users")
def users(uid: int = UID):
    return db.rows("SELECT id, name, shop, role, city, category, rating_avg, rating_count, kyc_verified FROM users ORDER BY role DESC, id")


@app.get("/api/me")
def me(uid: int = UID):
    u = db.one("SELECT id, name, shop, role, city, category, phone, email, email_verified, kyc_verified, rating_avg, rating_count FROM users WHERE id=?", (uid,))
    u["groups"] = [{"id": g["id"], "name": g["name"]} for g in groups.my_groups(uid)] if u["role"] == "merchant" else []
    u["invites"] = groups.my_invites(uid) if u["role"] == "merchant" else []
    u["unread"] = merchant.notifications(uid, 1)["unread"]
    return u


@app.get("/api/meta")
def meta():
    return {"cities": db.CITIES, "categories": ["grocery", "fmcg"], "products": db.rows("SELECT * FROM products ORDER BY category, name"),
            "kinds": list(market.KINDS)}


@app.get("/api/catalog")
def catalog(product: str | None = None):
    q = ("SELECT c.product, c.price, c.stock_qty, c.updated_at, w.id wholesaler_id, w.shop, w.city, w.rating_avg, w.rating_count, p.unit,"
         " wh.name warehouse, wh.city warehouse_city FROM catalog c JOIN users w ON w.id=c.wholesaler_id JOIN products p ON p.name=c.product"
         " JOIN warehouses wh ON wh.id=c.warehouse_id")
    return db.rows(q + (" WHERE c.product=? ORDER BY c.price" if product else " ORDER BY c.product, c.price"), (product,) if product else ())


# ---------------------------------------------------------------- home / merchants / notifications

@app.get("/api/home")
def home(days: int = 30, uid: int = UID):
    return merchant.home(uid, days)


@app.get("/api/merchants/nearby")
def merchants_nearby(q: str = "", city: str = "", category: str = "", product: str = "", uid: int = UID):
    return merchant.nearby_merchants(uid, q, city, category, product)


@app.get("/api/notifications")
def notifications(uid: int = UID):
    return merchant.notifications(uid)


@app.post("/api/notifications/read")
def notifications_read(body: dict = Body(default={}), uid: int = UID):
    return merchant.mark_read(uid, body.get("id"))


@app.get("/api/credit/cibil")
def cibil_status(uid: int = UID):
    return credit.cibil_status(uid)


@app.post("/api/credit/cibil")
def cibil_check(body: dict = Body(...), uid: int = UID):
    return credit.cibil_check(uid, bool(body.get("consent")), body.get("otp"))


# ---------------------------------------------------------------- groups (merchants only)

@app.get("/api/groups")
def list_groups(q: str = "", city: str = "", category: str = "", uid: int = UID):
    groups.require_merchant(uid)
    return groups.list_groups(uid, q, city, category)


@app.post("/api/groups")
def create_group(body: dict = Body(...), uid: int = UID):
    return groups.create_group(uid, body.get("name"), body.get("description"), body.get("category"), body.get("city"), body.get("type"))


@app.get("/api/groups/recommendations")
def group_recommendations(q: str = "", uid: int = UID):
    return {"groups": groups.recommend(uid, q), "merchants": groups.recommended_merchants(uid)["merchants"],
            "method": {"formula": "score = 35% same city + 30% category fit + 35% overlap of your regular items with what members buy",
                       "weights": groups.WEIGHTS, "note": "Rule-based scoring over your purchase history. No LLM."}}


@app.get("/api/groups/{gid}")
def group_detail(gid: int, uid: int = UID):
    return groups.group_detail(gid, uid)


@app.get("/api/groups/{gid}/precheck")
def group_precheck(gid: int, uid: int = UID):
    return groups.precheck(gid, uid)


@app.post("/api/groups/{gid}/join")
def join_group(gid: int, body: dict = Body(default={}), uid: int = UID):
    return groups.join(gid, uid, body.get("message", ""))


@app.post("/api/groups/{gid}/leave")
def leave_group(gid: int, uid: int = UID):
    return groups.leave(gid, uid)


@app.post("/api/groups/{gid}/members/{user_id}/decision")
def decide(gid: int, user_id: int, body: dict = Body(...), uid: int = UID):
    return groups.decide(gid, uid, user_id, bool(body.get("approve")))


@app.post("/api/groups/{gid}/invite")
def invite(gid: int, body: dict = Body(...), uid: int = UID):
    return groups.invite(gid, uid, int(body.get("user_id", 0)))


@app.post("/api/groups/{gid}/posts")
def add_post(gid: int, body: dict = Body(...), uid: int = UID):
    return groups.add_post(gid, uid, body.get("body", ""))


@app.post("/api/groups/{gid}/posts/{pid}/review")
def review_post(gid: int, pid: int, body: dict = Body(...), uid: int = UID):
    return groups.review_post(gid, uid, pid, body.get("action"))


# ---------------------------------------------------------------- auctions: sales + demands + pools

@app.get("/api/sales")
def sales(q: str = "", category: str = "", product: str = "", city: str = "", uid: int = UID):
    return market.list_sales(uid, q, category, product, city)


@app.post("/api/sales")
def create_sale(body: dict = Body(...), uid: int = UID):
    return market.create_sale(uid, body.get("product"), body.get("kind", "bulk"), body.get("tiers"), body.get("qty_limit"), body.get("days", 7))


@app.post("/api/sales/{sid}/close")
def close_sale(sid: int, uid: int = UID):
    return market.close_sale(sid, uid)


@app.post("/api/sales/{sid}/buy")
def buy_sale(sid: int, body: dict = Body(...), uid: int = UID):
    return market.buy_sale(sid, uid, body.get("qty"))


@app.post("/api/sales/{sid}/pools")
def start_pool(sid: int, body: dict = Body(...), uid: int = UID):
    return market.start_pool(sid, int(body.get("group_id", 0)), uid)


@app.post("/api/pools/{pid}/commit")
def commit_pool(pid: int, body: dict = Body(...), uid: int = UID):
    return market.commit_pool(pid, uid, body.get("qty"))


@app.post("/api/pools/{pid}/close")
def close_pool(pid: int, uid: int = UID):
    return market.close_pool(pid, uid)


@app.get("/api/demands")
def demands(q: str = "", category: str = "", product: str = "", city: str = "", status: str = "", uid: int = UID):
    return market.list_demands(uid, q, category, product, city, status)


@app.post("/api/demands")
def create_demand(body: dict = Body(...), uid: int = UID):
    return market.create_demand(uid, body.get("product"), body.get("qty"), body.get("budget"), body.get("note", ""))


@app.get("/api/demands/{did}")
def demand_view(did: int, uid: int = UID):
    return market.demand_view(did, uid)


@app.post("/api/demands/{did}/bids")
def place_bid(did: int, body: dict = Body(...), uid: int = UID):
    return market.place_bid(did, uid, body.get("price"))


@app.post("/api/demands/{did}/close")
def close_demand(did: int, body: dict = Body(default={}), uid: int = UID):
    return market.close_deal(did, uid, body.get("bid_id"))


@app.post("/api/demands/{did}/cancel")
def cancel_demand(did: int, uid: int = UID):
    return market.cancel_demand(did, uid)


# ---------------------------------------------------------------- AI features

@app.post("/api/ai/procure")
def procure(body: dict = Body(...), uid: int = UID):
    return ai.procurement(uid, body.get("text", ""), body.get("sort", "best"))


@app.post("/api/ai/parse")
def parse(body: dict = Body(...), uid: int = UID):
    return ai.parse_request(body.get("text", ""))


@app.get("/api/ai/forecast")
def forecast(festival: str | None = None, uid: int = UID):
    return ai.forecast(uid, festival, date.today())


@app.post("/api/ai/negotiate")
def negotiate(body: dict = Body(...), uid: int = UID):
    return ai.negotiate(uid, int(body.get("wholesaler_id", 0)), body.get("product"), body.get("qty"), body.get("max_price"))


@app.post("/api/ai/negotiate/{nid}/accept")
def accept_negotiation(nid: int, uid: int = UID):
    return ai.accept_negotiation(nid, uid)


# ---------------------------------------------------------------- stock tracking

@app.get("/api/stock")
def stock(uid: int = UID):
    return merchant.my_stock(uid)


@app.post("/api/stock/usage")
def stock_usage(body: dict = Body(...), uid: int = UID):
    return merchant.log_usage(uid, body.get("product"), body.get("qty"))


@app.post("/api/stock/set")
def stock_set(body: dict = Body(...), uid: int = UID):
    return merchant.set_stock(uid, body.get("product"), body.get("stock"))


# ---------------------------------------------------------------- orders, payments, reviews

@app.post("/api/orders")
def place_order(body: dict = Body(...), uid: int = UID):
    return orders.place(uid, int(body.get("wholesaler_id", 0)), body.get("lines") or [], "direct")


@app.get("/api/orders")
def my_orders(uid: int = UID):
    return orders.my_orders(uid)


@app.get("/api/orders/{oid}")
def get_order(oid: int, uid: int = UID):
    return orders.get_order(oid, uid)


@app.post("/api/orders/{oid}/quote")
def quote(oid: int, body: dict = Body(...), uid: int = UID):
    return orders.quote(oid, uid, body.get("delivery_charge"), body.get("note", ""), body.get("eta_days"))


@app.post("/api/orders/{oid}/cancel")
def cancel(oid: int, uid: int = UID):
    return orders.cancel(oid, uid)


@app.post("/api/orders/{oid}/ship")
def ship(oid: int, uid: int = UID):
    return orders.ship(oid, uid)


@app.post("/api/orders/{oid}/deliver")
def deliver(oid: int, uid: int = UID):
    return orders.deliver(oid, uid)


@app.post("/api/orders/{oid}/review")
def review(oid: int, body: dict = Body(...), uid: int = UID):
    return orders.review(oid, uid, body.get("rating"), body.get("comment", ""))


@app.get("/api/reviews/{target_id}")
def reviews(target_id: int, uid: int = UID):
    return orders.reviews_for(target_id)


@app.get("/api/orders/{oid}/pay-options")
def pay_options(oid: int, uid: int = UID):
    return payments.options(oid, uid)


@app.post("/api/orders/{oid}/pay")
def pay(oid: int, body: dict = Body(...), uid: int = UID):
    return payments.start(oid, uid, body.get("mode"), body.get("parts"), body.get("tenure"))


@app.post("/api/orders/{oid}/pay-installment")
def pay_installment(oid: int, uid: int = UID):
    return payments.pay_installment(oid, uid)


@app.get("/api/gateway/{txn_id}")
def gateway(txn_id: str, uid: int = UID):
    return payments.gateway(txn_id, uid)


@app.post("/api/gateway/{txn_id}/complete")
def gateway_complete(txn_id: str, body: dict = Body(...), uid: int = UID):
    return payments.complete(txn_id, uid, body.get("method"), bool(body.get("success", True)), bool(body.get("autopay")))


# ---------------------------------------------------------------- credit / loans

@app.get("/api/credit/offer")
def credit_offer(amount: float | None = None, uid: int = UID):
    return credit.offer(uid, amount)


@app.get("/api/loans")
def loans(uid: int = UID):
    return credit.my_loans(uid)


@app.post("/api/loans")
def apply_loan(body: dict = Body(...), uid: int = UID):
    return credit.create_loan(uid, float(body.get("amount", 0)), int(body.get("tenure", 3)), bool(body.get("autopay", True)), body.get("order_ids") or [])


@app.post("/api/loans/{lid}/autopay")
def autopay(lid: int, body: dict = Body(...), uid: int = UID):
    return credit.set_autopay(lid, uid, bool(body.get("on")))


@app.post("/api/loans/{lid}/pay")
def pay_emi(lid: int, body: dict = Body(default={}), uid: int = UID):
    return credit.pay_emi(lid, uid, body.get("mode", "manual"))


# ---------------------------------------------------------------- wholesaler inventory

@app.get("/api/wholesaler/inventory")
def wholesaler_inventory(uid: int = UID):
    return merchant.wholesaler_inventory(uid)


@app.post("/api/wholesaler/inventory")
def update_inventory(body: dict = Body(...), uid: int = UID):
    return merchant.update_inventory(uid, body.get("product"), body.get("price"), body.get("stock"), body.get("floor"))


# ---------------------------------------------------------------- UI

@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(FRONTEND / "login.html")


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
