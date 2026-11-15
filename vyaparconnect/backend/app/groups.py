"""Group formation (merchant-only): search, AI pre-check BEFORE a request is sent, join/approve, invitations,
explainable recommendations, feed + anti-collusion moderation. Wholesalers reach merchants via sales/auctions, not groups."""
import re

from . import db
from .db import ApiError

MAX_GROUP_SIZE = 30            # anti-collusion: oversized groups can act as buying cartels
MIN_RATING = 3.0               # merchants rated below this (with >= 3 reviews) are routed to admin review

COLLUSION_PATTERNS = [
    (r"\bfix(ed|ing)?\b.{0,20}\bprice", "Possible price fixing"),
    (r"\bprice[- ]?fixing\b", "Possible price fixing"),
    (r"\b(don'?t|do not|never|won'?t)\b.{0,25}\bsell\b.{0,25}\b(below|under|less)\b", "Possible minimum-price agreement"),
    (r"\bagree(d)?\b.{0,25}\b(same|common|minimum|min)\b.{0,15}\bprice", "Possible price agreement"),
    (r"\bboycott\b", "Possible boycott / collusion"),
    (r"\bcartel\b", "Possible cartel behaviour"),
    (r"\b(don'?t|do not|never|won'?t)\b.{0,25}\b(buy|sell)\b.{0,25}\b(from|to)\b", "Possible exclusion of a supplier or buyer"),
    (r"\bsplit (the )?(market|area|customers)\b", "Possible market allocation"),
]


def moderate(text: str) -> str | None:
    t = text.lower()
    for pat, reason in COLLUSION_PATTERNS:
        if re.search(pat, t):
            return reason
    return None


def get_user(uid: int) -> dict:
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "User not found")
    return u


def require_merchant(uid: int) -> dict:
    u = get_user(uid)
    if u["role"] != "merchant":
        raise ApiError(403, "Groups are for merchants only")
    return u


def get_group_row(gid: int) -> dict:
    g = db.one("SELECT * FROM groups WHERE id=?", (gid,))
    if not g:
        raise ApiError(404, "Group not found")
    return g


def membership(gid: int, uid: int) -> dict | None:
    return db.one("SELECT * FROM memberships WHERE group_id=? AND user_id=?", (gid, uid))


def is_active_member(gid: int, uid: int) -> bool:
    m = membership(gid, uid)
    return bool(m and m["status"] == "active")


def require_member(gid: int, uid: int) -> None:
    if not is_active_member(gid, uid):
        raise ApiError(403, "Only active group members can do this")


def require_admin(gid: int, uid: int) -> dict:
    g = get_group_row(gid)
    if g["admin_id"] != uid:
        raise ApiError(403, "Only the group admin can do this")
    return g


def counts(gid: int) -> dict:
    n = db.one("SELECT COUNT(*) n FROM memberships WHERE group_id=? AND status='active'", (gid,))["n"]
    return {"members": n}


def category_compatible(a: str, b: str) -> bool:
    return "both" in (a, b) or a == b


def bought(uid: int) -> set[str]:
    return {r["product"] for r in db.rows("SELECT DISTINCT product FROM history WHERE user_id=?", (uid,))}


def my_group_ids(uid: int) -> set[int]:
    return {r["group_id"] for r in db.rows("SELECT group_id FROM memberships WHERE user_id=? AND status='active'", (uid,))}


# ---------- listing / search / detail ----------

def _decorate(g: dict, uid: int) -> dict:
    m = membership(g["id"], uid)
    admin = db.one("SELECT name, shop FROM users WHERE id=?", (g["admin_id"],))
    return {**g, **counts(g["id"]), "admin_name": admin["name"] if admin else "",
            "my_status": m["status"] if m else None, "is_admin": g["admin_id"] == uid}


def list_groups(uid: int, q: str = "", city: str = "", category: str = "") -> list[dict]:
    q = (q or "").strip().lower()
    out = []
    for g in db.rows("SELECT * FROM groups ORDER BY id"):
        if city and g["city"] != city:
            continue
        if category and g["category"] != category:
            continue
        if q and q not in (g["name"] + " " + (g["description"] or "") + " " + g["city"]).lower():
            continue
        out.append(_decorate(g, uid))
    return out


def my_groups(uid: int) -> list[dict]:
    return [g for g in list_groups(uid) if g["my_status"] == "active"]


def group_detail(gid: int, uid: int) -> dict:
    from . import market  # lazy: market imports this module

    g = get_group_row(gid)
    d = _decorate(g, uid)
    members = db.rows(
        "SELECT u.id, u.name, u.shop, u.city, u.category, u.rating_avg, u.rating_count, u.kyc_verified, m.joined_at"
        " FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.group_id=? AND m.status='active' ORDER BY u.name", (gid,))
    for x in members:
        x["group_role"] = "admin" if x["id"] == g["admin_id"] else "member"
    d["members"] = members
    if d["my_status"] != "active":
        d.update(feed=[], pools=[], pending=[], stats=None, locked=True)
        return d
    is_admin = g["admin_id"] == uid
    d["feed"] = db.rows(
        "SELECT p.*, u.name author, u.shop author_shop FROM posts p JOIN users u ON u.id=p.user_id"
        " WHERE p.group_id=? AND p.status!='removed' AND (p.status='visible' OR p.user_id=? OR ?=1) ORDER BY p.id DESC",
        (gid, uid, 1 if is_admin else 0))
    d["pending"] = []
    if is_admin:
        d["pending"] = db.rows(
            "SELECT u.id, u.name, u.shop, u.city, u.category, u.rating_avg, u.rating_count, u.kyc_verified, m.note"
            " FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.group_id=? AND m.status='pending'", (gid,))
        for p in d["pending"]:
            p["ai_check"] = ai_check(g, get_user(p["id"]))
    d.update(pools=market.group_pools(gid, uid), stats=market.group_stats(gid), locked=False)
    return d


# ---------- AI membership check (shown BEFORE the request is sent) ----------

def ai_check(g: dict, u: dict) -> dict:
    reasons, ok = [], True
    def add(passed: bool, yes: str, no: str, hard: bool = False) -> None:
        nonlocal ok
        reasons.append({"ok": passed, "text": yes if passed else no})
        if not passed:
            ok = False
    add(bool(u["kyc_verified"]), "KYC verified", "KYC not verified")
    low = u["rating_count"] >= 3 and u["rating_avg"] < MIN_RATING
    add(not low, f"Merchant rating {u['rating_avg']:.1f}/5" if u["rating_count"] else "New merchant - no ratings yet",
        f"Merchant rating {u['rating_avg']:.1f}/5 is below {MIN_RATING}")
    add(u["city"] == g["city"], "Same city", f"Different city ({u['city']} vs {g['city']})")
    add(category_compatible(u["category"], g["category"]), "Category match", f"Category mismatch ({u['category']} vs {g['category']})")
    add(counts(g["id"])["members"] < MAX_GROUP_SIZE, "Group has space", f"Group is full ({MAX_GROUP_SIZE} members)")
    return {"pass": ok, "reasons": reasons, "summary": "Looks like a good fit" if ok else "Needs admin review"}


def precheck(gid: int, uid: int) -> dict:
    g = get_group_row(gid)
    u = require_merchant(uid)
    m = membership(gid, uid)
    check = ai_check(g, u)
    will = "active" if (g["type"] == "public" and check["pass"]) else "pending"
    return {"group": {"id": g["id"], "name": g["name"], "type": g["type"], "city": g["city"]}, "ai_check": check,
            "outcome": will, "my_status": m["status"] if m else None,
            "message": "You will join instantly." if will == "active" else "Your request will be sent to the group admin."}


# ---------- create / join / decide / invite / leave ----------

def create_group(uid: int, name: str, description: str, category: str, city: str, gtype: str) -> dict:
    u = require_merchant(uid)
    name = (name or "").strip()
    if len(name) < 3:
        raise ApiError(400, "Group name must be at least 3 characters")
    if category not in ("grocery", "fmcg", "both"):
        raise ApiError(400, "Category must be grocery, fmcg or both")
    if gtype not in ("public", "invite"):
        raise ApiError(400, "Type must be public or invite")
    if db.one("SELECT 1 x FROM groups WHERE lower(name)=lower(?)", (name,)):
        raise ApiError(409, "A group with this name already exists")
    ts = db.now_iso()
    gid = db.run("INSERT INTO groups(name,description,category,city,type,admin_id,created_at) VALUES(?,?,?,?,?,?,?)",
                 (name, (description or "").strip(), category, city or u["city"], gtype, uid, ts))
    db.run("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid, "active", "admin", ts))
    return {"id": gid}


def join(gid: int, uid: int, message: str = "") -> dict:
    g = get_group_row(gid)
    u = require_merchant(uid)
    m = membership(gid, uid)
    if m and m["status"] == "active":
        raise ApiError(409, "Already a member")
    if m and m["status"] == "pending":
        raise ApiError(409, "Join request already sent")
    ts = db.now_iso()
    if m and m["status"] == "invited":
        db.run("UPDATE memberships SET status='active', joined_at=? WHERE group_id=? AND user_id=?", (ts, gid, uid))
        db.notify(g["admin_id"], "group", f"{u['shop']} accepted your invitation to {g['name']}.")
        return {"status": "active", "message": f"Welcome to {g['name']}!"}
    check = ai_check(g, u)
    if counts(gid)["members"] >= MAX_GROUP_SIZE:
        raise ApiError(400, "This group is full")
    auto = g["type"] == "public" and check["pass"]
    status = "active" if auto else "pending"
    note = (message or "").strip() or "Join request"
    if m:
        db.run("UPDATE memberships SET status=?, note=?, joined_at=? WHERE group_id=? AND user_id=?", (status, note, ts, gid, uid))
    else:
        db.run("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid, status, note, ts))
    if status == "pending":
        db.notify(g["admin_id"], "group", f"{u['shop']} requested to join {g['name']}.", f"group:{gid}")
    else:
        db.notify(g["admin_id"], "group", f"{u['shop']} joined {g['name']}.", f"group:{gid}")
    return {"status": status, "message": f"Welcome to {g['name']}!" if auto else "Request sent to the group admin."}


def decide(gid: int, admin_id: int, user_id: int, approve: bool) -> dict:
    g = require_admin(gid, admin_id)
    m = membership(gid, user_id)
    if not m or m["status"] != "pending":
        raise ApiError(404, "No pending request for this user")
    if approve:
        if counts(gid)["members"] >= MAX_GROUP_SIZE:
            raise ApiError(400, "Group is full")
        db.run("UPDATE memberships SET status='active', joined_at=? WHERE group_id=? AND user_id=?", (db.now_iso(), gid, user_id))
        db.notify(user_id, "group", f"You were approved to join {g['name']}.", f"group:{gid}")
    else:
        db.run("UPDATE memberships SET status='rejected' WHERE group_id=? AND user_id=?", (gid, user_id))
        db.notify(user_id, "group", f"Your request to join {g['name']} was declined.")
    return {"status": "active" if approve else "rejected"}


def invite(gid: int, admin_id: int, user_id: int) -> dict:
    g = require_admin(gid, admin_id)
    target = get_user(user_id)
    if target["role"] != "merchant":
        raise ApiError(400, "Only merchants can be invited to groups")
    m = membership(gid, user_id)
    if m and m["status"] in ("active", "pending"):
        raise ApiError(409, "User is already a member or has a pending request")
    ts = db.now_iso()
    if m:
        db.run("UPDATE memberships SET status='invited', note='Invited by admin', joined_at=? WHERE group_id=? AND user_id=?", (ts, gid, user_id))
    else:
        db.run("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, user_id, "invited", "Invited by admin", ts))
    db.notify(user_id, "group", f"You are invited to join {g['name']}.", f"group:{gid}")
    return {"status": "invited"}


def my_invites(uid: int) -> list[dict]:
    return db.rows("SELECT g.id, g.name, g.city, g.category FROM memberships m JOIN groups g ON g.id=m.group_id"
                   " WHERE m.user_id=? AND m.status='invited'", (uid,))


def leave(gid: int, uid: int) -> dict:
    g = get_group_row(gid)
    if g["admin_id"] == uid:
        raise ApiError(400, "Admin cannot leave; the group needs an admin")
    if not membership(gid, uid):
        raise ApiError(404, "Not a member")
    db.run("DELETE FROM pool_commitments WHERE user_id=? AND pool_id IN (SELECT id FROM pools WHERE group_id=? AND status='open')", (uid, gid))
    db.run("DELETE FROM memberships WHERE group_id=? AND user_id=?", (gid, uid))
    return {"ok": True}


# ---------- feed + moderation ----------

def add_post(gid: int, uid: int, body: str) -> dict:
    require_member(gid, uid)
    body = (body or "").strip()
    if not body:
        raise ApiError(400, "Post cannot be empty")
    if len(body) > 500:
        raise ApiError(400, "Post is too long (max 500 characters)")
    reason = moderate(body)
    status = "held" if reason else "visible"
    pid = db.run("INSERT INTO posts(group_id,user_id,kind,body,flagged,flag_reason,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (gid, uid, "announcement", body, 1 if reason else 0, reason, status, db.now_iso()))
    if reason:
        g = get_group_row(gid)
        db.notify(g["admin_id"], "moderation", f"A post in {g['name']} was held by AI moderation: {reason}.", f"group:{gid}")
    return {"id": pid, "status": status, "flag_reason": reason}


def review_post(gid: int, admin_id: int, post_id: int, action: str) -> dict:
    require_admin(gid, admin_id)
    p = db.one("SELECT * FROM posts WHERE id=? AND group_id=?", (post_id, gid))
    if not p:
        raise ApiError(404, "Post not found")
    if action not in ("approve", "remove"):
        raise ApiError(400, "Action must be approve or remove")
    db.run("UPDATE posts SET status=? WHERE id=?", ("visible" if action == "approve" else "removed", post_id))
    return {"status": "visible" if action == "approve" else "removed"}


# ---------- recommendations (explainable) ----------

WEIGHTS = {"city": 0.35, "category": 0.30, "items": 0.35}


def recommend(uid: int, q: str = "") -> list[dict]:
    """score = 35% same city + 30% category fit + 35% overlap between the merchant's regular items and what group members buy."""
    u = require_merchant(uid)
    mine = bought(uid)
    out = []
    for g in list_groups(uid, q=q):
        if g["my_status"] is not None:
            continue
        city = 1.0 if u["city"] == g["city"] else 0.0
        cat = 1.0 if category_compatible(u["category"], g["category"]) else 0.0
        member_items: dict[str, int] = {}
        n = max(1, g["members"])
        for r in db.rows("SELECT h.product, COUNT(DISTINCT h.user_id) c FROM history h JOIN memberships m ON m.user_id=h.user_id"
                         " WHERE m.group_id=? AND m.status='active' GROUP BY h.product", (g["id"],)):
            member_items[r["product"]] = r["c"]
        shared = sorted(p for p in mine if member_items.get(p, 0) / n >= 0.3)
        items = len(shared) / len(mine) if mine else 0.0
        score = round(100 * (WEIGHTS["city"] * city + WEIGHTS["category"] * cat + WEIGHTS["items"] * items))
        why = []
        if city:
            why.append(f"Based in your city ({g['city']})")
        if cat:
            why.append(f"Matches your {u['category']} business")
        if shared:
            why.append(f"{len(shared)} of your {len(mine)} regular items are bought by members: {', '.join(shared[:3])}")
        out.append({**g, "score": score, "reasons": why,
                    "breakdown": {"city": round(100 * WEIGHTS["city"] * city), "category": round(100 * WEIGHTS["category"] * cat),
                                  "items": round(100 * WEIGHTS["items"] * items)}})
    out.sort(key=lambda x: -x["score"])
    return [x for x in out if x["score"] >= 30]


def recommended_merchants(uid: int, limit: int = 6) -> dict:
    """Nearby merchants who buy the same items and are not yet connected through a shared group - candidates to invite."""
    u = require_merchant(uid)
    mine = bought(uid)
    connected = {r["user_id"] for r in db.rows(
        "SELECT user_id FROM memberships WHERE status='active' AND group_id IN (SELECT group_id FROM memberships WHERE user_id=? AND status='active')", (uid,))}
    out = []
    for o in db.rows("SELECT * FROM users WHERE role='merchant' AND city=? AND id!=?", (u["city"], uid)):
        if o["id"] in connected or not category_compatible(u["category"], o["category"]):
            continue
        theirs = bought(o["id"])
        shared = mine & theirs
        sim = len(shared) / len(mine | theirs) if (mine | theirs) else 0
        if sim >= 0.25:
            out.append({"id": o["id"], "name": o["name"], "shop": o["shop"], "city": o["city"], "category": o["category"],
                        "rating_avg": o["rating_avg"], "rating_count": o["rating_count"], "similarity": round(sim * 100),
                        "shared_products": sorted(shared)})
    out.sort(key=lambda x: (-x["similarity"], -x["rating_avg"]))
    return {"merchants": out[:limit]}
