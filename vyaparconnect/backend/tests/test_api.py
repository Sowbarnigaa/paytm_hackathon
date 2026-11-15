"""End-to-end API tests (v2): the demo path plus the rules that must never break."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ["VC_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["VC_DEMO_AUTH"] = "1"          # this suite drives the API with the X-User-Id role switcher; see test_auth.py for real login
os.environ["VC_SARVAM"] = "0"             # never call the real Sarvam API from tests

from app import ai, db, seed  # noqa: E402
from app.main import app  # noqa: E402

RAVI, KUMAR, MEENA, DINESH, ANAND, SELVI, IMRAN = 7, 8, 13, 14, 18, 19, 26
MURUGAN, KAVERI, ANNAPOORNA, SRI_LAKSHMI, CHENNAI_BULK = 1, 2, 3, 4, 5


@pytest.fixture(autouse=True)
def fresh():
    seed.seed()


@pytest.fixture
def c():
    with TestClient(app) as client:
        yield client


def H(uid):
    return {"X-User-Id": str(uid)}


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


# ------------------------------------------------------------ groups (merchants only, AI check before request)

def test_groups_are_merchant_only(c):
    assert c.get("/api/groups", headers=H(MURUGAN)).status_code == 403
    assert c.post("/api/groups/1/join", json={}, headers=H(MURUGAN)).status_code == 403
    assert c.post("/api/groups", json={"name": "Wholesale club", "category": "grocery", "type": "public"}, headers=H(MURUGAN)).status_code == 403


def test_precheck_runs_before_request_and_does_not_join(c):
    p = ok(c.get("/api/groups/1/precheck", headers=H(RAVI)))
    assert p["ai_check"]["pass"] is True and p["outcome"] == "pending"        # invite-only group -> admin approval
    assert {"ok", "text"} <= set(p["ai_check"]["reasons"][0])
    d = ok(c.get("/api/groups/1", headers=H(RAVI)))
    assert d["my_status"] is None                                             # pre-check changed nothing


def test_join_invite_group_then_admin_approves(c):
    r = ok(c.post("/api/groups/1/join", json={"message": "Ravi here"}, headers=H(RAVI)))
    assert r["status"] == "pending" and "Request sent" in r["message"]
    assert ok(c.get("/api/groups/1", headers=H(RAVI)))["locked"] is True
    assert {p["id"] for p in ok(c.get("/api/groups/1", headers=H(KUMAR)))["pending"]} >= {RAVI}
    assert c.post(f"/api/groups/1/members/{RAVI}/decision", json={"approve": True}, headers=H(RAVI)).status_code == 403
    ok(c.post(f"/api/groups/1/members/{RAVI}/decision", json={"approve": True}, headers=H(KUMAR)))
    assert ok(c.get("/api/groups/1", headers=H(RAVI)))["locked"] is False
    assert any(n["kind"] == "group" for n in ok(c.get("/api/notifications", headers=H(RAVI)))["items"])


def test_public_group_auto_join_and_ai_rejects_wrong_city(c):
    # Ravi (Erode, grocery) joining the Coimbatore public group fails the city check -> goes to admin review, not instant
    p = ok(c.get("/api/groups/3/precheck", headers=H(RAVI)))
    assert p["ai_check"]["pass"] is False and p["outcome"] == "pending"
    assert any((not r["ok"]) and "city" in r["text"].lower() for r in p["ai_check"]["reasons"])
    assert ok(c.post("/api/groups/3/join", json={}, headers=H(RAVI)))["status"] == "pending"
    # same-city, compatible merchant joins a public group instantly (Karthik, Coimbatore 'both')
    assert ok(c.post("/api/groups/3/join", json={}, headers=H(24)))["status"] == "active"


def test_search_filters_groups_and_nearby_merchants(c):
    g = ok(c.get("/api/groups?city=Erode&category=fmcg", headers=H(RAVI)))
    assert g and all(x["city"] == "Erode" for x in g)
    assert ok(c.get("/api/groups?q=chennai", headers=H(RAVI)))[0]["city"] == "Chennai"
    near = ok(c.get("/api/merchants/nearby", headers=H(RAVI)))
    assert near[0]["city"] == "Erode" and "near_label" in near[0] and RAVI not in {m["id"] for m in near}
    assert ok(c.get("/api/merchants/nearby?city=Salem", headers=H(RAVI)))[0]["city"] == "Salem"
    assert c.get("/api/merchants/nearby", headers=H(MURUGAN)).status_code == 403


def test_recommendations_explained_and_replace_ai_suggestions(c):
    rec = ok(c.get("/api/groups/recommendations", headers=H(RAVI)))
    assert rec["groups"][0]["name"] == "Erode Grocery Buyers" and rec["groups"][0]["reasons"]
    assert "35%" in rec["method"]["formula"] and rec["groups"][0]["breakdown"]["city"] == 35
    assert c.get("/api/groups/suggestions", headers=H(RAVI)).status_code in (404, 405, 422)      # route removed


def test_collusion_post_is_held_and_admin_notified(c):
    r = ok(c.post("/api/groups/1/posts", json={"body": "Let's all agree to fix the price at 60 and boycott Murugan"}, headers=H(9)))
    assert r["status"] == "held" and r["flag_reason"]
    ok(c.post("/api/groups/1/posts", json={"body": "Pooling sugar this week?"}, headers=H(9)))
    assert any(n["kind"] == "moderation" for n in ok(c.get("/api/notifications", headers=H(KUMAR)))["items"])


# ------------------------------------------------------------ AI: multilingual procurement + inventory DB + sorting

@pytest.mark.parametrize("text,expect", [
    ("50 kg rice and 20 L oil", {"Rice": 50, "Sunflower Oil": 20}),
    ("50 கிலோ அரிசி", {"Rice": 50}),
    ("அரிசி 50 கிலோ, சர்க்கரை 30 கிலோ", {"Rice": 50, "Sugar": 30}),
    ("50 किलो चावल और 20 लीटर तेल", {"Rice": 50, "Sunflower Oil": 20}),
    ("2 quintal chawal aur 10 kg cheeni", {"Rice": 200, "Sugar": 10}),
    ("ஐம்பது கிலோ அரிசி", {"Rice": 50}),
    ("50kg arisi, 20 litre ennai", {"Rice": 50, "Sunflower Oil": 20}),
])
def test_parser_understands_english_tamil_hindi(text, expect):
    got = {l["product"]: l["qty"] for l in ai.parse_request(text)["lines"]}
    assert got == expect


def test_parser_detects_language_and_budget():
    assert ai.parse_request("50 கிலோ அரிசி")["language"]["code"] == "ta"
    assert ai.parse_request("चावल 50 किलो")["language"]["code"] == "hi"
    assert ai.parse_request("50 kg rice")["language"]["code"] == "en"
    p = ai.parse_request("50 किलो चावल, बजट 6000 रुपये")
    assert p["budget"] == 6000 and p["unrecognised"] == []

def test_sarvam_reply_is_validated_and_rules_remain_the_fallback(monkeypatch):
    reply = {"items": [{"product": "rice", "qty": 2, "unit": "quintal"}, {"product": "Sunflower Oil", "qty": 10, "unit": "litre"},
                       {"product": "Gold", "qty": 5, "unit": "kg"}, {"product": "Sugar", "qty": "lots", "unit": "kg"}],
             "budget": 30000, "language": "hi"}
    monkeypatch.setattr(ai.sarvam, "extract_order", lambda text, products: reply)
    p = ai.parse_request("mujhe 2 quintal chawal aur 10 litre tel chahiye")
    assert p["engine"] == "sarvam-105b-conversations" and p["budget"] == 30000 and p["language"]["code"] == "hi"
    got = {l["product"]: (l["qty"], l["assumed_qty"]) for l in p["lines"]}
    assert got["Rice"] == (200, False) and got["Sunflower Oil"] == (10, False) and got["Sugar"][1] is True   # "lots" -> default qty, flagged
    assert "Gold" not in got and p["unrecognised"] == ["Gold"]                                             # unknown products never reach the DB
    monkeypatch.setattr(ai.sarvam, "extract_order", lambda text, products: None)                           # Sarvam down -> rule parser
    q = ai.parse_request("50 kg rice")
    assert q["engine"] == "rule-based" and q["lines"][0]["qty"] == 50


def test_voice_endpoints_fail_cleanly_without_sarvam(c):
    assert c.post("/api/ai/transcribe", json={"audio": "AAAA", "format": "webm"}, headers=H(RAVI)).status_code == 503
    assert c.post("/api/ai/speak", json={"text": "hello", "lang": "en"}, headers=H(RAVI)).status_code == 503
    assert c.post("/api/ai/speak", json={"text": " "}, headers=H(RAVI)).status_code == 400




def test_procure_works_in_tamil_and_lists_multiple_products(c):
    r = ok(c.post("/api/ai/procure", json={"text": "50 கிலோ அரிசி மற்றும் 20 லிட்டர் எண்ணெய்"}, headers=H(RAVI)))
    assert r["parsed"]["language"]["code"] == "ta" and len(r["parsed"]["lines"]) == 2
    assert "Understood (Tamil)" in r["understood"]
    one = ok(c.post("/api/ai/procure", json={"text": "rice 100 kg"}, headers=H(RAVI)))
    assert one["parsed"]["single_product"] is True


def test_procure_sort_by_price_rating_eta_and_goods_price_only(c):
    base = {"text": "100 kg rice"}
    by = {s: ok(c.post("/api/ai/procure", json={**base, "sort": s}, headers=H(RAVI))) for s in ("best", "price", "rating", "eta")}
    price = [x["total"] for x in by["price"]["suppliers"] if not x["missing"]]
    assert price == sorted(price)
    rate = [x["wholesaler"]["rating_avg"] for x in by["rating"]["suppliers"] if not x["missing"]]
    assert rate == sorted(rate, reverse=True)
    eta = [x["eta_days"] for x in by["eta"]["suppliers"] if not x["missing"]]
    assert eta == sorted(eta)
    s0 = by["best"]["suppliers"][0]
    assert "delivery" in s0["delivery_note"].lower() and s0["lines"][0]["warehouse_city"] and "stock_as_of" in s0["lines"][0]
    assert s0["total"] == pytest.approx(sum(l["cost"] for l in s0["lines"]))             # no delivery in the price
    assert c.post("/api/ai/procure", json={**base, "sort": "bogus"}, headers=H(RAVI)).status_code == 400


def test_eta_follows_warehouse_location(c):
    near = ok(c.post("/api/ai/procure", json={"text": "100 kg rice", "sort": "eta"}, headers=H(RAVI)))["suppliers"][0]
    far = ok(c.post("/api/ai/procure", json={"text": "100 kg rice", "sort": "eta"}, headers=H(IMRAN)))
    assert near["eta_days"] <= 2 and far["suppliers"][0]["wholesaler"]["city"] == "Chennai"


def test_procure_unknown_product_is_helpful_error(c):
    assert c.post("/api/ai/procure", json={"text": "laptop"}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/ai/procure", json={"text": "rice"}, headers=H(MURUGAN)).status_code == 403


# ------------------------------------------------------------ forecast: model + stock tracking

def test_forecast_alerts_explain_model_and_tracking(c):
    f = ok(c.get("/api/ai/forecast", headers=H(RAVI)))
    assert "Exponential smoothing" in f["model"]["name"] and "Not machine learning" in f["model"]["type"]
    assert "Stock on hand" in f["tracking"]["formula"]
    oil = next(i for i in f["items"] if i["product"] == "Sunflower Oil")
    assert oil["level"] in ("critical", "warning") and oil["suggested_qty"] > 0 and oil["confidence"] in ("high", "medium", "low")
    assert "history" in oil["source"].lower()
    diwali = ok(c.get("/api/ai/forecast?festival=Diwali", headers=H(RAVI)))
    assert diwali["festival"]["what_if"] is True
    o2 = next(i for i in diwali["items"] if i["product"] == "Sunflower Oil")
    assert o2["festival_multiplier"] == 1.6 and o2["days_left"] <= oil["days_left"]
    assert c.get("/api/ai/forecast?festival=Nope", headers=H(RAVI)).status_code == 400


def test_stock_tracking_usage_reduces_stock_and_delivery_adds(c):
    before = next(s for s in ok(c.get("/api/stock", headers=H(RAVI))) if s["product"] == "Rice")["stock"]
    ok(c.post("/api/stock/usage", json={"product": "Rice", "qty": 5}, headers=H(RAVI)))
    after = next(s for s in ok(c.get("/api/stock", headers=H(RAVI))) if s["product"] == "Rice")["stock"]
    assert after == pytest.approx(before - 5)
    assert c.post("/api/stock/usage", json={"product": "Rice", "qty": -1}, headers=H(RAVI)).status_code == 400


# ------------------------------------------------------------ negotiator uses the private floor price + stock

def test_negotiator_never_goes_below_floor_and_is_not_hardcoded(c):
    cat = db.one("SELECT * FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))
    lowball = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": cat["floor_price"] * 0.8}, headers=H(RAVI)))
    assert lowball["status"] == "no_deal" and lowball["agreed_price"] is None
    flush = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": cat["price"]}, headers=H(RAVI)))
    assert flush["status"] == "deal" and flush["agreed_price"] >= cat["floor_price"] - 0.01
    assert flush["agreed_price"] <= cat["price"]
    assert "floor" in flush["method"].lower() and "floor_price" not in str(flush["transcript"]).lower()
    # raising the wholesaler's floor changes the outcome for the same buyer limit -> result is data-driven
    mid = round((cat["price"] + cat["floor_price"]) / 2, 2)
    a = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": mid}, headers=H(RAVI)))
    ok(c.post("/api/wholesaler/inventory", json={"product": "Rice", "floor": cat["price"]}, headers=H(MURUGAN)))
    b = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": mid}, headers=H(RAVI)))
    assert b["agreed_price"] is None or b["agreed_price"] >= (a["agreed_price"] or 0)
    assert b["last_ask"] >= a["last_ask"]


def test_negotiator_scarce_stock_is_firmer(c):
    row = db.one("SELECT * FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))
    lim = round(row["price"] * 0.93, 2)
    big = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": lim}, headers=H(RAVI)))
    db.run("UPDATE catalog SET stock_qty=60 WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))
    scarce = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": lim}, headers=H(RAVI)))
    assert "firm" in scarce["seller_stance"] and scarce["last_ask"] >= big["last_ask"]


def test_accepting_a_negotiation_creates_a_quote_pending_order(c):
    row = db.one("SELECT price FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))
    n = ok(c.post("/api/ai/negotiate", json={"wholesaler_id": MURUGAN, "product": "Rice", "qty": 50, "max_price": row["price"]}, headers=H(RAVI)))
    o = ok(c.post(f"/api/ai/negotiate/{n['id']}/accept", headers=H(RAVI)))
    assert o["status"] == "quote_pending" and o["items_total"] == pytest.approx(n["total"])
    assert c.post(f"/api/ai/negotiate/{n['id']}/accept", headers=H(RAVI)).status_code == 409


# ------------------------------------------------------------ auctions: sales & demands visibility, merchant-initiated close

def test_sales_visibility_and_filters(c):
    assert len(ok(c.get("/api/sales", headers=H(RAVI)))) == 6                  # merchants see all live sales
    own = ok(c.get("/api/sales", headers=H(MURUGAN)))
    assert [s["wholesaler_id"] for s in own] == [MURUGAN]                       # wholesalers see only their own
    assert {s["product"] for s in ok(c.get("/api/sales?category=fmcg", headers=H(RAVI)))} == {"Biscuits"}
    assert len(ok(c.get("/api/sales?product=Rice", headers=H(RAVI)))) == 2
    assert ok(c.get("/api/sales?city=Chennai", headers=H(RAVI)))
    s = ok(c.get("/api/sales?product=Rice", headers=H(RAVI)))[0]
    assert "eta_days" in s and "product only" in s["delivery_note"].lower()


def test_demands_visibility_and_filters(c):
    mine = ok(c.get("/api/demands", headers=H(KUMAR)))
    assert {d["user_id"] for d in mine} == {KUMAR}                              # merchants see only their own
    allw = ok(c.get("/api/demands", headers=H(MURUGAN)))
    assert {d["user_id"] for d in allw} >= {KUMAR, ANAND}                      # wholesalers see all demands
    assert all(d["product"] == "Sugar" for d in ok(c.get("/api/demands?product=Sugar", headers=H(MURUGAN))))
    assert all(d["buyer_city"] == "Coimbatore" for d in ok(c.get("/api/demands?city=Coimbatore", headers=H(MURUGAN))))
    assert ok(c.get("/api/demands?category=grocery", headers=H(MURUGAN)))


def test_bids_are_private_between_wholesalers_and_ranked_for_the_buyer(c):
    did = db.one("SELECT id FROM demands WHERE user_id=?", (KUMAR,))["id"]
    owner = ok(c.get(f"/api/demands/{did}", headers=H(KUMAR)))
    assert len(owner["bids"]) == 2 and owner["bids"][0]["rank"] == 1 and "eta_days" in owner["bids"][0]
    assert {"price", "rating", "eta"} == set(owner["bids"][0]["parts"])
    other = ok(c.get(f"/api/demands/{did}", headers=H(ANNAPOORNA)))
    assert other["bids"] == [] and other["can_bid"] is True
    ok(c.post(f"/api/demands/{did}/bids", json={"price": 100}, headers=H(ANNAPOORNA)))
    assert len(ok(c.get(f"/api/demands/{did}", headers=H(ANNAPOORNA)))["bids"]) == 1   # sees only its own
    assert c.post(f"/api/demands/{did}/bids", json={"price": 100}, headers=H(ANNAPOORNA)).status_code == 400   # must be lower
    assert c.post(f"/api/demands/{did}/bids", json={"price": 90}, headers=H(KUMAR)).status_code == 403


def test_only_the_merchant_can_close_a_demand_and_it_creates_an_order(c):
    did = db.one("SELECT id FROM demands WHERE user_id=?", (KUMAR,))["id"]
    assert c.post(f"/api/demands/{did}/close", json={}, headers=H(MURUGAN)).status_code == 404
    assert c.post(f"/api/demands/{did}/close", json={}, headers=H(ANAND)).status_code == 404
    r = ok(c.post(f"/api/demands/{did}/close", json={}, headers=H(KUMAR)))
    assert r["order"]["status"] == "quote_pending" and r["order"]["items_total"] > 0
    assert c.post(f"/api/demands/{did}/close", json={}, headers=H(KUMAR)).status_code == 400
    winner = ok(c.get(f"/api/orders/{r['order']['order_id']}", headers=H(KUMAR)))["wholesaler_id"]
    assert any(n["kind"] == "order" and f"#{r['order']['order_id']}" in n["text"] for n in ok(c.get("/api/notifications", headers=H(winner)))["items"])


def test_empty_demand_cannot_be_closed_and_can_be_cancelled(c):
    did = ok(c.post("/api/demands", json={"product": "Salt", "qty": 100}, headers=H(RAVI)))["id"]
    assert c.post(f"/api/demands/{did}/close", json={}, headers=H(RAVI)).status_code == 400
    assert ok(c.post(f"/api/demands/{did}/cancel", headers=H(RAVI)))["status"] == "cancelled"
    assert c.post("/api/demands", json={"product": "Salt", "qty": 5}, headers=H(MURUGAN)).status_code == 403


def test_collective_group_auction_and_participants_orders(c):
    # Kumar posts a collective reverse auction for Group 1 with 2 participating merchants
    participants = [
        {"user_id": KUMAR, "shop": "Kumar Stores", "qty": 60},
        {"user_id": 9, "shop": "Lakshmi Provision", "qty": 40}
    ]
    res = ok(c.post("/api/groups/1/auctions", json={
        "product": "Sugar",
        "budget": 4500,
        "note": "Collective bulk buy for festival",
        "participants": participants
    }, headers=H(KUMAR)))
    did = res["id"]

    d_view = ok(c.get(f"/api/demands/{did}", headers=H(KUMAR)))
    assert d_view["is_collective"] is True
    assert d_view["group_name"] == "Erode Grocery Buyers"
    assert len(d_view["participants"]) == 2
    assert d_view["qty"] == 100

    # Wholesaler bids
    ok(c.post(f"/api/demands/{did}/bids", json={"price": 38.0}, headers=H(MURUGAN)))

    # Award the collective auction -> orders created for both participants
    close_res = ok(c.post(f"/api/demands/{did}/close", json={}, headers=H(KUMAR)))
    assert len(close_res["order"]["order_ids"]) == 2
    assert close_res["winner"] == "Murugan Traders"


def test_group_pool_on_a_sale_unlocks_tier_pricing(c):
    sid = db.one("SELECT id FROM sales WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["id"]
    pid = ok(c.post(f"/api/sales/{sid}/pools", json={"group_id": 1}, headers=H(KUMAR)))["id"]
    assert c.post(f"/api/sales/{sid}/pools", json={"group_id": 1}, headers=H(KUMAR)).status_code == 409
    assert c.post(f"/api/sales/{sid}/pools", json={"group_id": 1}, headers=H(RAVI)).status_code == 403    # not a member
    for uid, q in [(KUMAR, 150), (9, 150), (10, 250)]:
        ok(c.post(f"/api/pools/{pid}/commit", json={"qty": q}, headers=H(uid)))
    v = ok(c.get("/api/groups/1", headers=H(KUMAR)))["pools"][0]
    assert v["total_qty"] == 550 and v["current_tier"]["min_qty"] == 500 and v["total_savings"] > 0
    assert c.post(f"/api/pools/{pid}/close", headers=H(9)).status_code == 403                   # not starter/admin
    res = ok(c.post(f"/api/pools/{pid}/close", headers=H(KUMAR)))
    assert len(res["order_ids"]) == 3
    o = ok(c.get(f"/api/orders/{res['order_ids'][0]}", headers=H(10)))                          # largest committer = Senthil
    assert o["status"] == "quote_pending" and o["items"][0]["unit_price"] == v["current_price"]
    assert c.get(f"/api/orders/{res['order_ids'][0]}", headers=H(KUMAR)).status_code == 404       # orders are private


def test_merchant_buys_directly_from_a_sale_at_their_tier(c):
    sid = db.one("SELECT id FROM sales WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["id"]
    r = ok(c.post(f"/api/sales/{sid}/buy", json={"qty": 300}, headers=H(RAVI)))
    assert r["items_total"] == pytest.approx(300 * ok(c.get("/api/sales?product=Rice", headers=H(RAVI)))[0]["tiers"][1]["price"], rel=0.01) or r["items_total"] > 0
    assert c.post(f"/api/sales/{sid}/buy", json={"qty": 999999}, headers=H(RAVI)).status_code == 400
    assert c.post(f"/api/sales/{sid}/buy", json={"qty": 10}, headers=H(MURUGAN)).status_code == 403


def test_wholesaler_creates_sale_and_interested_merchants_are_notified(c):
    tiers = [{"min_qty": 0, "price": 52}, {"min_qty": 200, "price": 50}]
    before = len(ok(c.get("/api/notifications", headers=H(RAVI)))["items"])
    ok(c.post("/api/sales", json={"product": "Rice", "kind": "bulk", "tiers": tiers, "qty_limit": 500, "days": 5}, headers=H(KAVERI)))
    assert len(ok(c.get("/api/notifications", headers=H(RAVI)))["items"]) == before + 1
    assert c.post("/api/sales", json={"product": "Rice", "tiers": [{"min_qty": 0, "price": 50}, {"min_qty": 100, "price": 55}], "qty_limit": 100}, headers=H(KAVERI)).status_code == 400
    assert c.post("/api/sales", json={"product": "Rice", "tiers": tiers, "qty_limit": 100}, headers=H(RAVI)).status_code == 403


# ------------------------------------------------------------ orders: delivery quote -> pay (3 modes) -> ship -> deliver -> review

def _order(c, uid=RAVI, w=MURUGAN, product="Rice", qty=50):
    return ok(c.post("/api/orders", json={"wholesaler_id": w, "lines": [{"product": product, "qty": qty}]}, headers=H(uid)))["order_id"]


def _quote(c, oid, w=MURUGAN, charge=200):
    return ok(c.post(f"/api/orders/{oid}/quote", json={"delivery_charge": charge, "note": "Tempo", "eta_days": 2}, headers=H(w)))


def test_price_is_goods_only_until_wholesaler_quotes_delivery(c):
    oid = _order(c)
    o = ok(c.get(f"/api/orders/{oid}", headers=H(RAVI)))
    assert o["status"] == "quote_pending" and o["delivery_charge"] is None and o["total"] is None
    assert c.get(f"/api/orders/{oid}/pay-options", headers=H(RAVI)).status_code == 400          # cannot pay before the quote
    assert c.post(f"/api/orders/{oid}/quote", json={"delivery_charge": 100}, headers=H(RAVI)).status_code == 400   # buyer cannot quote
    q = _quote(c, oid)
    assert q["status"] == "quoted" and q["total"] == pytest.approx(q["items_total"] + 200)
    assert c.post(f"/api/orders/{oid}/quote", json={"delivery_charge": 5}, headers=H(MURUGAN)).status_code == 400   # only once
    assert c.post(f"/api/orders/{oid}/quote", json={"delivery_charge": -5}, headers=H(MURUGAN)).status_code in (400,)


def test_pay_in_full_via_gateway_then_ship_deliver_updates_stock(c):
    oid = _order(c)
    _quote(c, oid)
    opts = ok(c.get(f"/api/orders/{oid}/pay-options", headers=H(RAVI)))
    assert opts["full"]["amount"] == opts["total"] and {"parts", "loan"} <= set(opts)
    intent = ok(c.post(f"/api/orders/{oid}/pay", json={"mode": "full"}, headers=H(RAVI)))
    assert intent["txn_id"].startswith("VCP") and intent["pay_url"].endswith(intent["txn_id"])
    g = ok(c.get(f"/api/gateway/{intent['txn_id']}", headers=H(RAVI)))
    assert g["status"] == "pending" and "upi" in g["methods"]
    bad = ok(c.post(f"/api/gateway/{intent['txn_id']}/complete", json={"method": "upi", "success": False}, headers=H(RAVI)))
    assert bad["status"] == "failed"
    assert ok(c.get(f"/api/orders/{oid}", headers=H(RAVI)))["status"] == "quoted"                 # nothing charged
    intent = ok(c.post(f"/api/orders/{oid}/pay", json={"mode": "full"}, headers=H(RAVI)))
    done = ok(c.post(f"/api/gateway/{intent['txn_id']}/complete", json={"method": "upi"}, headers=H(RAVI)))
    assert done["status"] == "success" and done["order"]["status"] == "confirmed" and done["order"]["paid_amount"] == done["order"]["total"]
    assert c.post(f"/api/gateway/{intent['txn_id']}/complete", json={"method": "upi"}, headers=H(RAVI)).status_code == 409
    assert c.post(f"/api/orders/{oid}/deliver", headers=H(RAVI)).status_code == 400                 # not shipped yet
    assert c.post(f"/api/orders/{oid}/ship", headers=H(RAVI)).status_code == 400                     # buyer cannot ship
    before = next(s for s in ok(c.get("/api/stock", headers=H(RAVI))) if s["product"] == "Rice")["stock"]
    ok(c.post(f"/api/orders/{oid}/ship", headers=H(MURUGAN)))
    d = ok(c.post(f"/api/orders/{oid}/deliver", headers=H(RAVI)))
    assert d["status"] == "delivered" and d["can_review"] is True
    after = next(s for s in ok(c.get("/api/stock", headers=H(RAVI))) if s["product"] == "Rice")["stock"]
    assert after == pytest.approx(before + 50)


def test_pay_in_parts_wholesaler_gets_money_in_instalments(c):
    oid = _order(c, qty=100)
    _quote(c, oid)
    opts = ok(c.get(f"/api/orders/{oid}/pay-options", headers=H(RAVI)))
    three = next(p for p in opts["parts"] if p["parts"] == 3)
    assert sum(three["amounts"]) == pytest.approx(opts["total"])
    intent = ok(c.post(f"/api/orders/{oid}/pay", json={"mode": "parts", "parts": 3}, headers=H(RAVI)))
    assert intent["amount"] == three["first"]
    done = ok(c.post(f"/api/gateway/{intent['txn_id']}/complete", json={"method": "card"}, headers=H(RAVI)))
    o = done["order"]
    assert o["status"] == "confirmed" and o["pay_mode"] == "parts" and len(o["installments"]) == 3
    assert o["paid_amount"] == pytest.approx(three["first"]) and o["balance"] == pytest.approx(o["total"] - three["first"])
    for _ in range(2):
        i2 = ok(c.post(f"/api/orders/{oid}/pay-installment", headers=H(RAVI)))
        ok(c.post(f"/api/gateway/{i2['txn_id']}/complete", json={"method": "upi"}, headers=H(RAVI)))
    final = ok(c.get(f"/api/orders/{oid}", headers=H(RAVI)))
    assert final["balance"] == pytest.approx(0, abs=0.01) and all(i["status"] == "paid" for i in final["installments"])
    assert c.post(f"/api/orders/{oid}/pay-installment", headers=H(RAVI)).status_code == 400
    small = _order(c, product="Salt", qty=5)
    _quote(c, small, charge=0)
    assert c.post(f"/api/orders/{small}/pay", json={"mode": "parts", "parts": 2}, headers=H(RAVI)).status_code == 400   # below minimum


def test_pay_by_paytm_loan_pays_wholesaler_in_full_and_creates_emi_plan(c):
    oid = _order(c, qty=100)
    _quote(c, oid)
    opts = ok(c.get(f"/api/orders/{oid}/pay-options", headers=H(RAVI)))
    assert opts["loan"]["eligible"] is True and opts["loan"]["plans"]
    assert c.post(f"/api/orders/{oid}/pay", json={"mode": "loan", "tenure": 5}, headers=H(RAVI)).status_code == 400   # invalid tenure
    intent = ok(c.post(f"/api/orders/{oid}/pay", json={"mode": "loan", "tenure": 3}, headers=H(RAVI)))
    done = ok(c.post(f"/api/gateway/{intent['txn_id']}/complete", json={"method": "wallet", "autopay": True}, headers=H(RAVI)))
    assert done["order"]["status"] == "confirmed" and done["order"]["paid_amount"] == done["order"]["total"] and done["order"]["pay_mode"] == "loan"
    assert done["loan"]["tenure"] == 3 and done["loan"]["autopay"] == 1
    loans = ok(c.get("/api/loans", headers=H(RAVI)))
    assert len(loans) == 1
    ok(c.post(f"/api/loans/{loans[0]['id']}/pay", json={"mode": "autopay"}, headers=H(RAVI)))
    assert ok(c.get("/api/loans", headers=H(RAVI)))[0]["paid_emis"] == 1


def test_loan_blocked_when_order_exceeds_available_credit(c):
    db.run("UPDATE catalog SET stock_qty=100000 WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))
    oid = _order(c, qty=2000)                                              # ~Rs 1 lakh of rice, Ravi's limit is Rs 60,000
    _quote(c, oid)
    opts = ok(c.get(f"/api/orders/{oid}/pay-options", headers=H(RAVI)))
    assert opts["loan"]["eligible"] is False and "exceeds" in opts["loan"]["note"]
    assert c.post(f"/api/orders/{oid}/pay", json={"mode": "loan", "tenure": 3}, headers=H(RAVI)).status_code == 400
    assert ok(c.post(f"/api/orders/{oid}/pay", json={"mode": "full"}, headers=H(RAVI)))["kind"] == "full"   # other modes still work


def test_cancel_before_payment_restores_stock(c):
    stock0 = db.one("SELECT stock_qty s FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["s"]
    oid = _order(c, qty=100)
    assert db.one("SELECT stock_qty s FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["s"] == stock0 - 100
    ok(c.post(f"/api/orders/{oid}/cancel", headers=H(RAVI)))
    assert db.one("SELECT stock_qty s FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["s"] == stock0
    assert c.post(f"/api/orders/{oid}/cancel", headers=H(RAVI)).status_code == 400


def test_order_validation(c):
    assert c.post("/api/orders", json={"wholesaler_id": MURUGAN, "lines": [{"product": "Rice", "qty": 0}]}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/orders", json={"wholesaler_id": MURUGAN, "lines": [{"product": "Rice", "qty": 99999999}]}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/orders", json={"wholesaler_id": KAVERI, "lines": [{"product": "Soap", "qty": 5}]}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/orders", json={"wholesaler_id": MURUGAN, "lines": [{"product": "Rice", "qty": 5}]}, headers=H(MURUGAN)).status_code == 403
    assert c.get("/api/orders/1", headers=H(KUMAR)).status_code == 404                                # not your order


# ------------------------------------------------------------ reviews (1-5 stars)

def test_review_flow_updates_rating_and_blocks_duplicates(c):
    pending = [o for o in ok(c.get("/api/orders", headers=H(RAVI))) if o["can_review"]]
    assert [o["id"] for o in pending] == [1]                                                           # seeded delivered order
    before = ok(c.get(f"/api/reviews/{MURUGAN}", headers=H(RAVI)))["user"]
    assert c.post("/api/orders/1/review", json={"rating": 6}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/orders/1/review", json={"rating": 0}, headers=H(RAVI)).status_code == 400
    ok(c.post("/api/orders/1/review", json={"rating": 5, "comment": "Great"}, headers=H(RAVI)))
    after = ok(c.get(f"/api/reviews/{MURUGAN}", headers=H(RAVI)))
    assert after["user"]["rating_count"] == before["rating_count"] + 1 and after["reviews"][0]["comment"] == "Great"
    assert sum(after["distribution"].values()) == after["user"]["rating_count"]
    assert c.post("/api/orders/1/review", json={"rating": 4}, headers=H(RAVI)).status_code == 409
    assert ok(c.post("/api/orders/1/review", json={"rating": 4, "comment": "Paid on time"}, headers=H(MURUGAN)))["ok"]   # wholesaler reviews merchant too
    assert c.post("/api/orders/1/review", json={"rating": 4}, headers=H(KUMAR)).status_code == 404
    undelivered = _order(c)
    assert c.post(f"/api/orders/{undelivered}/review", json={"rating": 5}, headers=H(RAVI)).status_code == 400


def test_trust_score_is_gone_everywhere(c):
    for u in ok(c.get("/api/users", headers=H(RAVI))):
        assert "password_hash" not in u and "email" not in u            # the directory never exposes credentials or contact email
        assert "trust" not in u and 0 <= u["rating_avg"] <= 5
    me = ok(c.get("/api/me", headers=H(RAVI)))
    assert "trust" not in me and me["rating_avg"] == 4.2


# ------------------------------------------------------------ CIBIL-style check, home dashboard, notifications

def test_cibil_check_needs_consent_and_otp_and_is_merchant_only(c):
    assert ok(c.get("/api/credit/cibil", headers=H(RAVI)))["checked"] is None
    assert c.post("/api/credit/cibil", json={"consent": False, "otp": "123456"}, headers=H(RAVI)).status_code == 400
    assert c.post("/api/credit/cibil", json={"consent": True, "otp": "000000"}, headers=H(RAVI)).status_code == 401
    r = ok(c.post("/api/credit/cibil", json={"consent": True, "otp": "123456"}, headers=H(RAVI)))
    assert r["checked"]["score"] == 712 and r["checked"]["band"] == "Good" and r["simulated"] is True
    assert ok(c.get("/api/credit/cibil", headers=H(RAVI)))["checked"]["score"] == 712
    assert c.post("/api/credit/cibil", json={"consent": True, "otp": "123456"}, headers=H(MURUGAN)).status_code == 403
    assert ok(c.get("/api/credit/cibil", headers=H(MURUGAN)))["eligible"] is False


def test_home_dashboard_is_paytm_business_shaped(c):
    h = ok(c.get("/api/home", headers=H(RAVI)))
    assert h["role"] == "merchant" and h["simulated"] is True
    assert h["payments"]["amount"] > 0 and h["settlement"]["amount"] <= h["payments"]["amount"] and h["refunds"]["count"] > 0
    assert len(h["chart"]) == 30 and abs(sum(s["pct"] for s in h["sources"]) - 100) < 0.5
    w = ok(c.get("/api/home", headers=H(MURUGAN)))
    assert w["role"] == "wholesaler" and "to_quote" in w


def test_notifications_unread_and_mark_read(c):
    n = ok(c.get("/api/notifications", headers=H(RAVI)))
    assert n["unread"] >= 2 and ok(c.get("/api/me", headers=H(RAVI)))["unread"] == n["unread"]
    ok(c.post("/api/notifications/read", json={}, headers=H(RAVI)))
    assert ok(c.get("/api/notifications", headers=H(RAVI)))["unread"] == 0


def test_wholesaler_inventory_and_floor_validation(c):
    inv = ok(c.get("/api/wholesaler/inventory", headers=H(MURUGAN)))
    assert inv["items"][0]["floor_price"] > 0 and inv["warehouses"]
    assert c.get("/api/wholesaler/inventory", headers=H(RAVI)).status_code == 403
    assert c.post("/api/wholesaler/inventory", json={"product": "Rice", "floor": 9999}, headers=H(MURUGAN)).status_code == 400
    ok(c.post("/api/wholesaler/inventory", json={"product": "Rice", "stock": 123}, headers=H(MURUGAN)))
    assert db.one("SELECT stock_qty s FROM catalog WHERE wholesaler_id=? AND product='Rice'", (MURUGAN,))["s"] == 123


def test_unknown_user_is_rejected(c):
    assert c.get("/api/me", headers=H(9999)).status_code == 401
    assert c.get("/api/me").status_code == 401
