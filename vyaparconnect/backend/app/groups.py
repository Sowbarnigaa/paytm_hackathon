"""Group formation: create / join / approve, AI recommendations, AI-suggested groups, feed + moderation."""
import re

from . import db
from .db import ApiError

WHOLESALER_MAX_SHARE = 0.40   # anti-collusion: wholesalers may be at most 40% of a group
MIN_TRUST_AUTO = 60           # AI auto-approval threshold for public groups

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
    """Return a reason string if the text looks like collusion, else None."""
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


def member_role(g: dict, u: dict) -> str:
    if u["role"] == "wholesaler":
        return "wholesaler"
    return "admin" if g["admin_id"] == u["id"] else "member"


def counts(gid: int) -> dict:
    r = db.rows(
        "SELECT u.role, COUNT(*) n FROM memberships m JOIN users u ON u.id=m.user_id"
        " WHERE m.group_id=? AND m.status='active' GROUP BY u.role", (gid,))
    d = {x["role"]: x["n"] for x in r}
    merchants, wholesalers = d.get("merchant", 0), d.get("wholesaler", 0)
    return {"merchants": merchants, "wholesalers": wholesalers, "members": merchants + wholesalers}


def category_compatible(user_cat: str, group_cat: str) -> bool:
    return "both" in (user_cat, group_cat) or user_cat == group_cat


# ---------- listing / detail ----------

def list_groups(uid: int) -> list[dict]:
    out = []
    for g in db.rows("SELECT * FROM groups ORDER BY id"):
        m = membership(g["id"], uid)
        admin = db.one("SELECT name FROM users WHERE id=?", (g["admin_id"],))
        out.append({**g, **counts(g["id"]), "admin_name": admin["name"] if admin else "",
                    "my_status": m["status"] if m else None, "is_admin": g["admin_id"] == uid})
    return out


def my_groups(uid: int) -> list[dict]:
    return [g for g in list_groups(uid) if g["my_status"] == "active"]


def group_detail(gid: int, uid: int) -> dict:
    from . import deals  # lazy: deals imports this module

    g = get_group_row(gid)
    me = get_user(uid)
    m = membership(gid, uid)
    status = m["status"] if m else None
    is_admin = g["admin_id"] == uid
    active = status == "active"
    members = db.rows(
        "SELECT u.id, u.name, u.shop, u.role, u.city, u.trust, u.kyc_verified, m.joined_at FROM memberships m"
        " JOIN users u ON u.id=m.user_id WHERE m.group_id=? AND m.status='active' ORDER BY u.role DESC, u.name",
        (gid,))
    for x in members:
        x["group_role"] = "admin" if x["id"] == g["admin_id"] else ("wholesaler" if x["role"] == "wholesaler" else "member")
    detail = {**g, **counts(gid), "my_status": status, "is_admin": is_admin,
              "admin_name": next((x["name"] for x in members if x["id"] == g["admin_id"]), ""),
              "members": members}
    # Non-members only see the public shell (no feed, no deals)
    if not active:
        detail.update(feed=[], deals=[], pending=[], stats=None, locked=True)
        return detail
    posts = db.rows(
        "SELECT p.*, u.name author, u.role author_role FROM posts p JOIN users u ON u.id=p.user_id"
        " WHERE p.group_id=? AND (p.status='visible' OR p.user_id=? OR ?=1) AND p.status!='removed'"
        " ORDER BY p.id DESC", (gid, uid, 1 if is_admin else 0))
    pending = []
    if is_admin:
        pending = db.rows(
            "SELECT u.id, u.name, u.shop, u.role, u.city, u.trust, u.kyc_verified, m.note FROM memberships m"
            " JOIN users u ON u.id=m.user_id WHERE m.group_id=? AND m.status='pending'", (gid,))
        for p in pending:
            p["ai_check"] = ai_check(g, db.one("SELECT * FROM users WHERE id=?", (p["id"],)))
    detail.update(feed=posts, deals=deals.group_deals(gid, uid), pending=pending, stats=deals.group_stats(gid),
                  locked=False, role_in_group=member_role(g, me))
    return detail


# ---------- AI membership check ----------

def ai_check(g: dict, u: dict) -> dict:
    """Explainable pre-screen used for auto-approval and shown to admins."""
    reasons, ok, cap_exceeded = [], True, False
    if not u["kyc_verified"]:
        ok = False
        reasons.append("KYC not verified")
    else:
        reasons.append("KYC verified")
    if u["trust"] < MIN_TRUST_AUTO:
        ok = False
        reasons.append(f"Trust score {u['trust']} below {MIN_TRUST_AUTO}")
    else:
        reasons.append(f"Trust score {u['trust']}")
    if u["city"] != g["city"]:
        ok = False
        reasons.append(f"Different city ({u['city']} vs {g['city']})")
    else:
        reasons.append("Same city")
    if not category_compatible(u["category"], g["category"]):
        ok = False
        reasons.append(f"Category mismatch ({u['category']} vs {g['category']})")
    else:
        reasons.append("Category match")
    if u["role"] == "wholesaler":
        c = counts(g["id"])
        total = c["members"] + 1
        if (c["wholesalers"] + 1) / total > WHOLESALER_MAX_SHARE:
            ok = False
            cap_exceeded = True
            reasons.append(f"Wholesaler share would exceed {int(WHOLESALER_MAX_SHARE * 100)}% (anti-collusion cap)")
        else:
            reasons.append("Within wholesaler cap")
    return {"pass": ok, "reasons": reasons, "cap_exceeded": cap_exceeded}


# ---------- create / join / decide / leave ----------

def create_group(uid: int, name: str, description: str, category: str, city: str, gtype: str) -> dict:
    u = get_user(uid)
    if u["role"] != "merchant":
        raise ApiError(403, "Only merchants can create groups (wholesalers join them)")
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
    u = get_user(uid)
    m = membership(gid, uid)
    if m and m["status"] == "active":
        raise ApiError(409, "Already a member")
    if m and m["status"] == "pending":
        raise ApiError(409, "Join request already pending")
    check = ai_check(g, u)
    ts = db.now_iso()
    if m and m["status"] == "invited":
        status = "active"
        db.run("UPDATE memberships SET status='active', joined_at=? WHERE group_id=? AND user_id=?", (ts, gid, uid))
        return {"status": status, "ai_check": check, "message": "Invitation accepted"}
    # Hard blocks that no admin should override
    if u["role"] == "wholesaler" and not u["kyc_verified"]:
        raise ApiError(400, "Wholesalers must be KYC verified")
    if u["role"] == "wholesaler" and check["cap_exceeded"]:
        raise ApiError(400, "Group already has the maximum share of wholesalers (anti-collusion rule)")
    auto = g["type"] == "public" and check["pass"]
    status = "active" if auto else "pending"
    note = message.strip() or ("Auto-approved by AI check" if auto else "Join request")
    if m:  # previously rejected -> re-apply
        db.run("UPDATE memberships SET status=?, note=?, joined_at=? WHERE group_id=? AND user_id=?",
               (status, note, ts, gid, uid))
    else:
        db.run("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid, status, note, ts))
    msg = "Joined instantly (AI auto-approved)" if auto else "Request sent to group admin"
    return {"status": status, "ai_check": check, "message": msg}


def decide(gid: int, admin_id: int, user_id: int, approve: bool) -> dict:
    g = require_admin(gid, admin_id)
    m = membership(gid, user_id)
    if not m or m["status"] != "pending":
        raise ApiError(404, "No pending request for this user")
    u = get_user(user_id)
    if approve:
        if u["role"] == "wholesaler":
            check = ai_check(g, u)
            if check["cap_exceeded"]:
                raise ApiError(400, "Approving would exceed the wholesaler cap (anti-collusion rule)")
        db.run("UPDATE memberships SET status='active', joined_at=? WHERE group_id=? AND user_id=?",
               (db.now_iso(), gid, user_id))
    else:
        db.run("UPDATE memberships SET status='rejected' WHERE group_id=? AND user_id=?", (gid, user_id))
    return {"status": "active" if approve else "rejected"}


def invite(gid: int, admin_id: int, user_id: int) -> dict:
    require_admin(gid, admin_id)
    get_user(user_id)
    m = membership(gid, user_id)
    if m and m["status"] in ("active", "pending"):
        raise ApiError(409, "User is already a member or has a pending request")
    ts = db.now_iso()
    if m:
        db.run("UPDATE memberships SET status='invited', note='Invited by admin', joined_at=? WHERE group_id=? AND user_id=?",
               (ts, gid, user_id))
    else:
        db.run("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, user_id, "invited", "Invited by admin", ts))
    return {"status": "invited"}


def my_invites(uid: int) -> list[dict]:
    return db.rows(
        "SELECT g.id, g.name, g.city, g.category FROM memberships m JOIN groups g ON g.id=m.group_id"
        " WHERE m.user_id=? AND m.status='invited'", (uid,))


def leave(gid: int, uid: int) -> dict:
    g = get_group_row(gid)
    if g["admin_id"] == uid:
        raise ApiError(400, "Admin cannot leave; transfer or keep the group")
    if not membership(gid, uid):
        raise ApiError(404, "Not a member")
    db.run("DELETE FROM commitments WHERE user_id=? AND deal_id IN (SELECT id FROM deals WHERE group_id=?)", (uid, gid))
    db.run("DELETE FROM memberships WHERE group_id=? AND user_id=?", (gid, uid))
    return {"ok": True}


# ---------- feed + moderation ----------

POST_KINDS = ("announcement", "flash_sale", "clearance", "seasonal")


def add_post(gid: int, uid: int, kind: str, body: str) -> dict:
    require_member(gid, uid)
    u = get_user(uid)
    body = (body or "").strip()
    if not body:
        raise ApiError(400, "Post cannot be empty")
    if len(body) > 500:
        raise ApiError(400, "Post is too long (max 500 characters)")
    if kind not in POST_KINDS:
        kind = "announcement"
    if kind != "announcement" and u["role"] != "wholesaler":
        raise ApiError(403, "Only wholesalers can post flash sales, clearance and seasonal alerts")
    reason = moderate(body)
    status = "held" if reason else "visible"
    pid = db.run(
        "INSERT INTO posts(group_id,user_id,kind,body,flagged,flag_reason,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (gid, uid, kind, body, 1 if reason else 0, reason, status, db.now_iso()))
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


# ---------- AI: recommendations & suggestions ----------

def _bought_products(uid: int) -> set[str]:
    return {r["product"] for r in db.rows("SELECT DISTINCT product FROM history WHERE user_id=?", (uid,))}


def recommend(uid: int) -> list[dict]:
    """Score = 0.4 category match + 0.3 same city + 0.3 overlap of user's items with group's wholesaler catalogue."""
    u = get_user(uid)
    mine = _bought_products(uid)
    out = []
    for g in db.rows("SELECT * FROM groups"):
        if membership(g["id"], uid) or g["city"] != u["city"]:
            continue  # other-city groups can't be joined (see ai_check), so don't recommend them
        cat = 1.0 if category_compatible(u["category"], g["category"]) else 0.0
        city = 1.0 if u["city"] == g["city"] else 0.0
        offered = {r["product"] for r in db.rows(
            "SELECT DISTINCT c.product FROM catalog c JOIN memberships m ON m.user_id=c.wholesaler_id"
            " WHERE m.group_id=? AND m.status='active'", (g["id"],))}
        overlap = (len(mine & offered) / len(mine)) if mine else 0.0
        score = round(100 * (0.4 * cat + 0.3 * city + 0.3 * overlap))
        why = []
        if city:
            why.append(f"In your city ({g['city']})")
        if cat:
            why.append(f"Matches your {u['category']} business")
        if offered:
            why.append(f"Group suppliers stock {len(mine & offered)} of your {len(mine)} regular items")
        out.append({**g, **counts(g["id"]), "score": score, "reasons": why,
                    "instant_join": g["type"] == "public" and ai_check(g, u)["pass"]})
    out.sort(key=lambda x: -x["score"])
    return [x for x in out if x["score"] >= 30]


def suggest_clusters(uid: int) -> dict:
    """Find nearby merchants who buy the same items and propose forming a new group with them."""
    u = get_user(uid)
    if u["role"] != "merchant":
        return {"candidates": [], "proposal": None}
    mine = _bought_products(uid)
    my_groups_ids = {g["id"] for g in my_groups(uid)}
    cands = []
    for o in db.rows("SELECT * FROM users WHERE role='merchant' AND city=? AND id!=?", (u["city"], uid)):
        if not category_compatible(u["category"], o["category"]):
            continue
        theirs = _bought_products(o["id"])
        shared = mine & theirs
        union = mine | theirs
        sim = len(shared) / len(union) if union else 0
        # skip anyone who already shares a group with the user - they're already connected
        if any(is_active_member(gid, o["id"]) for gid in my_groups_ids):
            continue
        if sim >= 0.25 and o["trust"] >= MIN_TRUST_AUTO:
            cands.append({"id": o["id"], "name": o["name"], "shop": o["shop"], "trust": o["trust"],
                          "similarity": round(sim * 100), "shared_products": sorted(shared)})
    cands.sort(key=lambda x: (-x["similarity"], -x["trust"]))
    cands = cands[:6]
    if len(cands) < 2:
        return {"candidates": cands, "proposal": None}
    freq: dict[str, int] = {}
    for c in cands:
        for p in c["shared_products"]:
            freq[p] = freq.get(p, 0) + 1
    top = sorted(freq, key=lambda p: -freq[p])[:3]
    cat = u["category"]
    return {"candidates": cands, "proposal": {
        "name": f"{u['city']} {'Grocery' if cat == 'grocery' else 'FMCG' if cat == 'fmcg' else 'Daily Needs'} Pool",
        "category": cat, "city": u["city"], "type": "invite", "top_products": top,
        "description": f"Pooled buying of {', '.join(top)} for {u['city']} merchants.",
        "reason": f"{len(cands)} nearby merchants buy the same items ({', '.join(top)}) but are not in a group with you."}}
