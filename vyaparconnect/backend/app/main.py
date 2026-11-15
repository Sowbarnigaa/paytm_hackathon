"""VyaparConnect AI - FastAPI app. Serves the REST API and the single-page UI from one process.

Auth is intentionally a demo role-switcher: the UI sends `X-User-Id`. Replace with Paytm SSO in production.
"""
import os
from datetime import date
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, auction, credit, db, deals, groups, orders, seed
from .db import ApiError

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="Paytm VyaparConnect AI", version="1.0")


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


@app.on_event("startup")
def startup() -> None:
    if not os.path.exists(db.db_path()):
        seed.seed()


def current_user(x_user_id: int = Header(...)) -> int:
    if not db.one("SELECT 1 x FROM users WHERE id=?", (x_user_id,)):
        raise ApiError(401, "Unknown user")
    return x_user_id


UID = Depends(current_user)


def _num(body: dict, key: str, default=None):
    return body.get(key, default)


# ---------------------------------------------------------------- session / reference data

@app.post("/api/reset")
def reset():
    seed.seed()
    return {"ok": True}


@app.get("/api/users")
def users():
    return db.rows("SELECT id, name, shop, role, city, category, trust, kyc_verified FROM users ORDER BY role DESC, id")


@app.get("/api/me")
def me(uid: int = UID):
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    u["groups"] = [{"id": g["id"], "name": g["name"]} for g in groups.my_groups(uid)]
    u["invites"] = groups.my_invites(uid)
    return u


@app.get("/api/products")
def products():
    return db.rows("SELECT * FROM products ORDER BY category, name")


@app.get("/api/catalog")
def catalog(product: str | None = None):
    q = ("SELECT c.*, w.name, w.shop, w.city, w.trust, p.unit FROM catalog c JOIN users w ON w.id=c.wholesaler_id"
         " JOIN products p ON p.name=c.product")
    return db.rows(q + (" WHERE c.product=? ORDER BY c.price" if product else " ORDER BY c.product, c.price"),
                   (product,) if product else ())


@app.get("/api/merchants/nearby")
def merchants_nearby(uid: int = UID):
    u = groups.get_user(uid)
    return db.rows("SELECT id, name, shop, city, category, trust FROM users WHERE role='merchant' AND city=? AND id!=?",
                   (u["city"], uid))


# ---------------------------------------------------------------- groups (priority feature)

@app.get("/api/groups")
def list_groups(uid: int = UID):
    return groups.list_groups(uid)


@app.post("/api/groups")
def create_group(body: dict = Body(...), uid: int = UID):
    return groups.create_group(uid, body.get("name"), body.get("description"), body.get("category"),
                               body.get("city"), body.get("type"))


@app.get("/api/groups/recommendations")
def group_recommendations(uid: int = UID):
    return groups.recommend(uid)


@app.get("/api/groups/suggestions")
def group_suggestions(uid: int = UID):
    return groups.suggest_clusters(uid)


@app.get("/api/groups/{gid}")
def group_detail(gid: int, uid: int = UID):
    return groups.group_detail(gid, uid)


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
    return groups.add_post(gid, uid, body.get("kind", "announcement"), body.get("body", ""))


@app.post("/api/groups/{gid}/posts/{pid}/review")
def review_post(gid: int, pid: int, body: dict = Body(...), uid: int = UID):
    return groups.review_post(gid, uid, pid, body.get("action"))


@app.post("/api/groups/{gid}/deals")
def create_deal(gid: int, body: dict = Body(...), uid: int = UID):
    return deals.create_deal(gid, uid, body.get("product"), body.get("kind", "bulk"), body.get("tiers"),
                             body.get("days", 7))


@app.post("/api/deals/{did}/commit")
def commit(did: int, body: dict = Body(...), uid: int = UID):
    return deals.commit(did, uid, body.get("qty"))


@app.post("/api/deals/{did}/close")
def close_deal(did: int, uid: int = UID):
    return deals.close_deal(did, uid)


# ---------------------------------------------------------------- AI features

@app.post("/api/ai/procure")
def procure(body: dict = Body(...), uid: int = UID):
    return ai.procurement(uid, body.get("text", ""))


@app.get("/api/ai/forecast")
def forecast(festival: str | None = None, uid: int = UID):
    return ai.forecast(uid, festival, date.today())


@app.post("/api/ai/negotiate")
def negotiate(body: dict = Body(...), uid: int = UID):
    return ai.negotiate(uid, int(body.get("wholesaler_id", 0)), body.get("product"), body.get("qty"),
                        body.get("max_price"))


@app.post("/api/ai/negotiate/{nid}/accept")
def accept_negotiation(nid: int, uid: int = UID):
    return ai.accept_negotiation(nid, uid)


# ---------------------------------------------------------------- auction

@app.get("/api/auctions")
def auctions(uid: int = UID):
    return auction.list_for(uid)


@app.post("/api/auctions")
def create_auction(body: dict = Body(...), uid: int = UID):
    return auction.create(uid, body.get("product"), body.get("qty"), body.get("budget"), body.get("group_id"))


@app.get("/api/auctions/{rid}")
def auction_view(rid: int, uid: int = UID):
    return auction.view(rid, uid)


@app.post("/api/auctions/{rid}/bids")
def bid(rid: int, body: dict = Body(...), uid: int = UID):
    return auction.place_bid(rid, uid, body.get("price"), body.get("delivery_days", 2))


@app.post("/api/auctions/{rid}/award")
def award(rid: int, body: dict = Body(default={}), uid: int = UID):
    return auction.award(rid, uid, body.get("bid_id"))


# ---------------------------------------------------------------- orders + credit

@app.post("/api/orders")
def place_order(body: dict = Body(...), uid: int = UID):
    return orders.place(uid, int(body.get("wholesaler_id", 0)), body.get("lines") or [], body.get("pay", "wallet"),
                        body.get("tenure"), bool(body.get("autopay")))


@app.get("/api/orders")
def my_orders(uid: int = UID):
    return orders.my_orders(uid)


@app.get("/api/credit/offer")
def credit_offer(amount: float | None = None, uid: int = UID):
    return credit.offer(uid, amount)


@app.get("/api/loans")
def loans(uid: int = UID):
    return credit.my_loans(uid)


@app.post("/api/loans/{lid}/autopay")
def autopay(lid: int, body: dict = Body(...), uid: int = UID):
    return credit.set_autopay(lid, uid, bool(body.get("on")))


@app.post("/api/loans/{lid}/pay")
def pay_emi(lid: int, body: dict = Body(default={}), uid: int = UID):
    return credit.pay_emi(lid, uid, body.get("mode", "manual"))


# ---------------------------------------------------------------- wholesaler dashboard

@app.get("/api/wholesaler/dashboard")
def wholesaler_dashboard(uid: int = UID):
    u = groups.get_user(uid)
    if u["role"] != "wholesaler":
        raise ApiError(403, "Wholesalers only")
    return {"groups": groups.my_groups(uid),
            "catalog": db.rows("SELECT c.*, p.unit FROM catalog c JOIN products p ON p.name=c.product"
                               " WHERE wholesaler_id=? ORDER BY product", (uid,)),
            "orders": db.rows("SELECT o.id, o.total, o.source, o.created_at, u.shop buyer FROM orders o"
                              " JOIN users u ON u.id=o.user_id WHERE o.wholesaler_id=? ORDER BY o.id DESC LIMIT 15",
                              (uid,)),
            "revenue": db.one("SELECT COALESCE(SUM(total),0) t, COUNT(*) n FROM orders WHERE wholesaler_id=?", (uid,)),
            "demand": [{"product": d["product"], "merchants": d["m"], "qty": d["q"]} for d in db.rows(
                "SELECT product, COUNT(DISTINCT user_id) m, ROUND(SUM(qty),0) q FROM history"
                " WHERE day>=date('now','-30 day') AND user_id IN (SELECT user_id FROM memberships WHERE status='active'"
                " AND group_id IN (SELECT group_id FROM memberships WHERE user_id=? AND status='active'))"
                " GROUP BY product ORDER BY q DESC LIMIT 6", (uid,))]}


# ---------------------------------------------------------------- UI

@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
