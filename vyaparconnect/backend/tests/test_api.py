"""End-to-end API tests: the hackathon demo path plus the rules that must never break."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ["VC_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app import seed  # noqa: E402
from app.main import app  # noqa: E402

RAVI, KUMAR, MEENA = 7, 8, 13
MURUGAN, KAVERI, ANNAPOORNA = 1, 2, 3


@pytest.fixture(autouse=True)
def fresh():
    seed.seed()


@pytest.fixture
def c():
    with TestClient(app) as client:
        yield client


def H(uid):
    return {"X-User-Id": str(uid)}


# ------------------------------------------------------------ group formation

def test_recommendations_are_personal_and_same_city(c):
    recs = c.get("/api/groups/recommendations", headers=H(RAVI)).json()
    assert recs[0]["name"] == "Erode Grocery Buyers"
    assert all(r["city"] == "Erode" for r in recs)
    other = c.get("/api/groups/recommendations", headers=H(19)).json()  # Coimbatore merchant already in group 3
    assert all(r["city"] == "Coimbatore" for r in other)


def test_invite_group_needs_admin_approval_then_membership(c):
    r = c.post("/api/groups/1/join", json={"message": "Ravi here"}, headers=H(RAVI)).json()
    assert r["status"] == "pending"
    d = c.get("/api/groups/1", headers=H(RAVI)).json()
    assert d["locked"] is True and d["feed"] == []            # non-members see no feed
    adm = c.get("/api/groups/1", headers=H(KUMAR)).json()
    assert {p["id"] for p in adm["pending"]} >= {RAVI}
    assert c.post(f"/api/groups/1/members/{RAVI}/decision", json={"approve": True}, headers=H(RAVI)).status_code == 403
    assert c.post(f"/api/groups/1/members/{RAVI}/decision", json={"approve": True}, headers=H(KUMAR)).status_code == 200
    d = c.get("/api/groups/1", headers=H(RAVI)).json()
    assert d["locked"] is False and d["my_status"] == "active" and len(d["feed"]) >= 2


def test_public_group_auto_approves_when_ai_check_passes(c):
    r = c.post("/api/groups/2/join", json={}, headers=H(RAVI)).json()   # Erode FMCG Circle is public
    # Ravi is grocery, group is fmcg -> category mismatch -> must NOT auto approve
    assert r["status"] == "pending"
    r = c.post("/api/groups/3/join", json={}, headers=H(RAVI))          # other city
    assert r.json()["status"] == "pending" and not r.json()["ai_check"]["pass"]


def test_public_group_instant_join_for_matching_user(c):
    gid = c.post("/api/groups", json={"name": "Erode Open Pool", "category": "grocery", "city": "Erode",
                                     "type": "public"}, headers=H(KUMAR)).json()["id"]
    r = c.post(f"/api/groups/{gid}/join", json={}, headers=H(RAVI)).json()
    assert r["status"] == "active" and r["ai_check"]["pass"]
    assert c.post(f"/api/groups/{gid}/join", json={}, headers=H(RAVI)).status_code == 409


def test_create_group_validation_and_roles(c):
    assert c.post("/api/groups", json={"name": "ab", "category": "grocery", "type": "public"}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/groups", json={"name": "Erode Grocery Buyers", "category": "grocery", "type": "public"},
                  headers=H(RAVI)).status_code == 409
    assert c.post("/api/groups", json={"name": "Wholesaler Club", "category": "grocery", "type": "public"},
                  headers=H(MURUGAN)).status_code == 403


def test_wholesaler_cap_blocks_collusion_heavy_groups(c):
    # a city mismatch is a soft failure: it goes to the admin instead of auto-approving
    r = c.post("/api/groups/1/join", json={}, headers=H(ANNAPOORNA)).json()
    assert r["status"] == "pending" and not r["ai_check"]["pass"]
    new = c.post("/api/groups", json={"name": "Tiny Pool", "category": "grocery", "city": "Erode", "type": "invite"},
                 headers=H(RAVI)).json()["id"]
    # 1 merchant + 1 wholesaler = 50% wholesalers > 40% cap -> blocked outright
    r = c.post(f"/api/groups/{new}/join", json={}, headers=H(MURUGAN))
    assert r.status_code == 400 and "anti-collusion" in r.json()["detail"]
    # once the group has 2 more merchants (3 merchants + 1 wholesaler = 25%) a wholesaler may request to join
    for uid in (KUMAR, 9):
        c.post(f"/api/groups/{new}/join", json={}, headers=H(uid))
        c.post(f"/api/groups/{new}/members/{uid}/decision", json={"approve": True}, headers=H(RAVI))
    assert c.post(f"/api/groups/{new}/join", json={}, headers=H(MURUGAN)).json()["status"] == "pending"
    assert c.post(f"/api/groups/{new}/members/{MURUGAN}/decision", json={"approve": True}, headers=H(RAVI)).status_code == 200


def test_collusion_post_is_held_and_admin_can_remove(c):
    r = c.post("/api/groups/1/posts", json={"body": "Let's all fix the price of rice at 60"}, headers=H(9)).json()
    assert r["status"] == "held" and r["flag_reason"]
    feed_other = c.get("/api/groups/1", headers=H(10)).json()["feed"]
    assert all(p["id"] != r["id"] for p in feed_other)               # hidden from other members
    feed_admin = c.get("/api/groups/1", headers=H(KUMAR)).json()["feed"]
    assert any(p["id"] == r["id"] and p["flagged"] for p in feed_admin)
    assert c.post(f"/api/groups/1/posts/{r['id']}/review", json={"action": "remove"}, headers=H(KUMAR)).status_code == 200
    assert all(p["id"] != r["id"] for p in c.get("/api/groups/1", headers=H(KUMAR)).json()["feed"])
    ok = c.post("/api/groups/1/posts", json={"body": "Anyone need sugar this week?"}, headers=H(9)).json()
    assert ok["status"] == "visible"


def test_only_wholesalers_post_sales_and_only_members_post(c):
    assert c.post("/api/groups/1/posts", json={"kind": "flash_sale", "body": "Sale"}, headers=H(9)).status_code == 403
    assert c.post("/api/groups/1/posts", json={"body": "hi"}, headers=H(RAVI)).status_code == 403


def test_ai_suggested_group_for_unconnected_merchant(c):
    s = c.get("/api/groups/suggestions", headers=H(RAVI)).json()
    assert s["proposal"] and len(s["candidates"]) >= 2
    assert all(x["similarity"] >= 25 for x in s["candidates"])
    assert c.get("/api/groups/suggestions", headers=H(MURUGAN)).json()["proposal"] is None


def test_invite_flow(c):
    assert c.post("/api/groups/1/invite", json={"user_id": RAVI}, headers=H(RAVI)).status_code == 403
    assert c.post("/api/groups/1/invite", json={"user_id": RAVI}, headers=H(KUMAR)).status_code == 200
    me = c.get("/api/me", headers=H(RAVI)).json()
    assert me["invites"][0]["id"] == 1
    assert c.post("/api/groups/1/join", json={}, headers=H(RAVI)).json()["status"] == "active"


# ------------------------------------------------------------ deals & pooled buying

def _rice_deal(c):
    return c.post("/api/groups/1/deals", headers=H(MURUGAN), json={
        "product": "Rice", "kind": "bulk", "days": 7,
        "tiers": [{"min_qty": 0, "price": 55}, {"min_qty": 250, "price": 52}, {"min_qty": 500, "price": 49}]}).json()["id"]


def test_pooled_buying_unlocks_tier_and_splits_savings(c):
    did = _rice_deal(c)
    for uid, q in [(8, 100), (9, 100), (10, 100), (11, 100), (12, 100)]:
        r = c.post(f"/api/deals/{did}/commit", json={"qty": q}, headers=H(uid))
        assert r.status_code == 200
    v = r.json()
    assert v["total_qty"] == 500 and v["current_price"] == 49 and v["next_tier"] is None
    assert v["total_savings"] == 3000.0                          # (55-49) * 500
    assert all(x["savings"] == 600.0 and x["share_pct"] == 20.0 for x in v["commitments"])


def test_commit_rules(c):
    did = _rice_deal(c)
    assert c.post(f"/api/deals/{did}/commit", json={"qty": 10}, headers=H(RAVI)).status_code == 403       # not a member
    assert c.post(f"/api/deals/{did}/commit", json={"qty": 10}, headers=H(MURUGAN)).status_code == 403    # wholesaler
    assert c.post(f"/api/deals/{did}/commit", json={"qty": -5}, headers=H(9)).status_code == 400
    assert c.post(f"/api/deals/{did}/commit", json={"qty": "abc"}, headers=H(9)).status_code == 400
    v = c.post(f"/api/deals/{did}/commit", json={"qty": 260}, headers=H(9)).json()
    assert v["current_price"] == 52 and v["to_next_tier"] == 240
    v = c.post(f"/api/deals/{did}/commit", json={"qty": 0}, headers=H(9)).json()                           # withdraw
    assert v["participants"] == 0 and v["current_price"] == 55


def test_deal_validation(c):
    base = {"product": "Rice", "days": 3}
    assert c.post("/api/groups/1/deals", json={**base, "tiers": []}, headers=H(MURUGAN)).status_code == 400
    assert c.post("/api/groups/1/deals", json={**base, "tiers": [{"min_qty": 0, "price": 50}, {"min_qty": 100, "price": 60}]},
                  headers=H(MURUGAN)).status_code == 400                       # price must fall as qty rises
    assert c.post("/api/groups/1/deals", json={**base, "tiers": [{"min_qty": 0, "price": 50}]}, headers=H(9)).status_code == 403
    assert c.post("/api/groups/1/deals", json={"product": "Gold", "tiers": [{"min_qty": 0, "price": 5}]},
                  headers=H(MURUGAN)).status_code == 400


def test_close_deal_creates_orders_at_final_price(c):
    did = _rice_deal(c)
    c.post(f"/api/deals/{did}/commit", json={"qty": 300}, headers=H(8))
    assert c.post(f"/api/deals/{did}/close", headers=H(9)).status_code == 403
    r = c.post(f"/api/deals/{did}/close", headers=H(MURUGAN)).json()
    assert r["final_price"] == 52 and len(r["order_ids"]) == 1
    assert c.post(f"/api/deals/{did}/close", headers=H(MURUGAN)).status_code == 400
    assert c.post(f"/api/deals/{did}/commit", json={"qty": 5}, headers=H(9)).status_code == 400
    orders = c.get("/api/orders", headers=H(8)).json()
    assert orders[0]["total"] == 15600.0


# ------------------------------------------------------------ AI features

def test_procurement_agent_parses_and_ranks(c):
    r = c.post("/api/ai/procure", json={"text": "50 kg rice, 20 L oil, 10 cartons biscuits, budget 6000"}, headers=H(RAVI)).json()
    assert {l["product"] for l in r["parsed"]["lines"]} == {"Rice", "Sunflower Oil", "Biscuits"}
    assert r["parsed"]["budget"] == 6000
    scores = [s["score"] for s in r["suppliers"]]
    assert scores == sorted(scores, reverse=True) and r["suppliers"][0]["reason"]
    assert c.post("/api/ai/procure", json={"text": ""}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/ai/procure", json={"text": "unicorn horns"}, headers=H(RAVI)).status_code == 400


def test_procurement_voice_style_and_single_item_budget(c):
    r = c.post("/api/ai/procure", json={"text": "100 kg arisi, budget Rs 5,000"}, headers=H(RAVI)).json()
    assert r["parsed"]["lines"][0]["product"] == "Rice" and r["parsed"]["budget"] == 5000
    assert "kg" in r["budget_note"]


def test_procurement_surfaces_open_group_pool(c):
    _rice_deal(c)
    r = c.post("/api/ai/procure", json={"text": "50 kg rice"}, headers=H(KUMAR)).json()
    assert r["group_pools"] and r["group_pools"][0]["best_tier_price"] == 49


def test_forecast_flags_ravis_oil_and_festival_boost(c):
    f = c.get("/api/ai/forecast", headers=H(RAVI)).json()
    oil = next(i for i in f["items"] if i["product"] == "Sunflower Oil")
    assert oil["level"] == "critical" and oil["days_left"] < 4 and oil["suggested_qty"] > 0
    f2 = c.get("/api/ai/forecast?festival=Pongal", headers=H(RAVI)).json()
    rice1 = next(i for i in f["items"] if i["product"] == "Rice")
    rice2 = next(i for i in f2["items"] if i["product"] == "Rice")
    assert rice2["days_left"] < rice1["days_left"] and f2["festival"]["name"] == "Pongal"
    assert c.get("/api/ai/forecast?festival=Xmas", headers=H(RAVI)).status_code == 400


def test_negotiator_respects_limits(c):
    ok = c.post("/api/ai/negotiate", json={"wholesaler_id": KAVERI, "product": "Rice", "qty": 100, "max_price": 54}, headers=H(RAVI)).json()
    assert ok["status"] == "deal" and ok["agreed_price"] <= 54 and ok["agreed_price"] < ok["list_price"]
    assert ok["transcript"][0]["agent"] == "seller"
    no = c.post("/api/ai/negotiate", json={"wholesaler_id": KAVERI, "product": "Rice", "qty": 100, "max_price": 30}, headers=H(RAVI)).json()
    assert no["status"] == "no_deal" and no["agreed_price"] is None
    assert c.post(f"/api/ai/negotiate/{no['id']}/accept", headers=H(RAVI)).status_code == 400
    acc = c.post(f"/api/ai/negotiate/{ok['id']}/accept", headers=H(RAVI)).json()
    assert acc["total"] == round(ok["agreed_price"] * 100, 2)
    assert c.post(f"/api/ai/negotiate/{ok['id']}/accept", headers=H(RAVI)).status_code == 409
    assert c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 0, "max_price": 50},
                  headers=H(RAVI)).status_code == 400


# ------------------------------------------------------------ auction

def test_reverse_auction_full_flow(c):
    rid = c.post("/api/auctions", json={"product": "Rice", "qty": 200, "budget": 11000, "group_id": 1}, headers=H(KUMAR)).json()["id"]
    assert c.post(f"/api/auctions/{rid}/bids", json={"price": 52, "delivery_days": 2}, headers=H(ANNAPOORNA)).status_code == 403
    assert c.post(f"/api/auctions/{rid}/bids", json={"price": 53, "delivery_days": 1}, headers=H(MURUGAN)).status_code == 200
    v = c.post(f"/api/auctions/{rid}/bids", json={"price": 50, "delivery_days": 3}, headers=H(KAVERI)).json()
    assert len(v["bids"]) == 2 and v["bids"][0]["rank"] == 1 and v["bids"][0]["reason"]
    assert c.post(f"/api/auctions/{rid}/bids", json={"price": 49, "delivery_days": 3}, headers=H(KAVERI)).status_code == 200
    assert c.post(f"/api/auctions/{rid}/bids", json={"price": 49, "delivery_days": 3}, headers=H(KAVERI)).status_code == 400
    assert c.post(f"/api/auctions/{rid}/award", json={}, headers=H(9)).status_code == 404
    r = c.post(f"/api/auctions/{rid}/award", json={}, headers=H(KUMAR)).json()
    assert r["order"]["total"] == round(r["price"] * 200, 2)
    assert c.post(f"/api/auctions/{rid}/bids", json={"price": 40, "delivery_days": 1}, headers=H(MURUGAN)).status_code == 400


# ------------------------------------------------------------ credit / loans

def test_loan_offer_tiers_and_autopay_flow(c):
    o = c.get("/api/credit/offer", headers=H(RAVI)).json()
    assert o["tier"] == "Good" and o["limit"] == 60000 and o["max_tenure"] == 9
    order = c.post("/api/orders", headers=H(RAVI), json={
        "wholesaler_id": KAVERI, "lines": [{"product": "Rice", "qty": 100}], "pay": "loan", "tenure": 3, "autopay": True}).json()
    loan = order["loan"]
    assert loan["autopay"] == 1 and loan["emi"] > order["total"] / 3 and len(loan["schedule"]) == 3
    assert c.post(f"/api/loans/{loan['id']}/pay", json={"mode": "autopay"}, headers=H(RAVI)).json()["paid_emis"] == 1
    assert c.post(f"/api/loans/{loan['id']}/autopay", json={"on": False}, headers=H(RAVI)).json()["autopay"] == 0
    assert c.post(f"/api/loans/{loan['id']}/pay", json={"mode": "autopay"}, headers=H(RAVI)).status_code == 400
    assert c.get("/api/credit/offer", headers=H(RAVI)).json()["outstanding"] > 0
    assert c.get("/api/loans", headers=H(KUMAR)).json() == []


def test_loan_rejects_over_limit_and_bad_tenure(c):
    big = c.post("/api/orders", headers=H(RAVI), json={
        "wholesaler_id": KAVERI, "lines": [{"product": "Tea Powder", "qty": 500}], "pay": "loan", "tenure": 3})
    assert big.status_code == 400
    bad = c.post("/api/orders", headers=H(RAVI), json={
        "wholesaler_id": KAVERI, "lines": [{"product": "Rice", "qty": 10}], "pay": "loan", "tenure": 12})
    assert bad.status_code == 400


def test_starter_tier_needs_group_backing(c):
    # Kumar-ish merchants are in groups; find a low-score merchant outside any group
    low = c.get("/api/users").json()
    free = [u for u in low if u["role"] == "merchant"]
    for u in free:
        o = c.get("/api/credit/offer", headers=H(u["id"])).json()
        if o["tier"] == "Starter" and o["note"]:
            assert o["limit"] == 0 and not o["eligible"]
            return


# ------------------------------------------------------------ misc

def test_auth_and_reset(c):
    assert c.get("/api/groups").status_code == 422
    assert c.get("/api/groups", headers=H(9999)).status_code == 401
    c.post("/api/groups/1/join", json={}, headers=H(RAVI))
    assert c.post("/api/reset").status_code == 200
    assert c.get("/api/groups/1", headers=H(KUMAR)).json()["pending"][0]["id"] == MEENA


def test_wholesaler_dashboard(c):
    d = c.get("/api/wholesaler/dashboard", headers=H(MURUGAN)).json()
    assert d["groups"] and d["catalog"]
    assert c.get("/api/wholesaler/dashboard", headers=H(RAVI)).status_code == 403
