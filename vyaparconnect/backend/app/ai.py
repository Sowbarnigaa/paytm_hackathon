"""Rule-based / statistical AI for VyaparConnect. Deterministic - NO LLM, no external model calls.

1. Procurement agent  - multilingual rule-based parser (English, Tamil, Hindi; native script + romanised) -> inventory
                        database lookup -> weighted supplier ranking (price, rating, ETA) with user-selectable sorting.
2. Demand forecast    - exponential smoothing (alpha 0.3) on daily usage x day-of-week index x festival multiplier.
3. Smart negotiator   - Faratin-style time-dependent concession between a buyer agent and a seller agent whose
                        reservation price is the wholesaler's PRIVATE floor price, shaped by live stock and order size.
"""
import json
import math
import re
import unicodedata
from datetime import date, timedelta

from . import db, market, orders
from .db import ApiError


def _n(s: str) -> str:
    return unicodedata.normalize("NFC", s)


# ================================================================== 1. multilingual vocabulary

# product -> {lang_tag: [aliases]}.  lang_tags: en | ta (Tamil script) | ta_tr (romanised Tamil) | hi (Devanagari) | hi_tr (romanised Hindi)
VOCAB = {
    "Rice": {"en": ["rice", "basmati"], "ta": ["அரிசி"], "ta_tr": ["arisi"], "hi": ["चावल"], "hi_tr": ["chawal", "chaval", "chaaval"]},
    "Sunflower Oil": {"en": ["sunflower oil", "sunflower", "cooking oil", "oil"], "ta": ["சூரியகாந்தி எண்ணெய்", "எண்ணெய்", "எண்ணை"],
                      "ta_tr": ["ennai", "ennei", "enna"], "hi": ["सूरजमुखी तेल", "तेल"], "hi_tr": ["tel", "tail"]},
    "Toor Dal": {"en": ["toor dal", "tur dal", "arhar dal", "dal", "dhal", "toor"], "ta": ["துவரம் பருப்பு", "பருப்பு"], "ta_tr": ["thuvaram paruppu", "paruppu"],
                 "hi": ["तुअर दाल", "अरहर", "दाल"], "hi_tr": ["daal"]},
    "Sugar": {"en": ["sugar"], "ta": ["சர்க்கரை", "சீனி"], "ta_tr": ["sakkarai", "sarkarai", "seeni"], "hi": ["चीनी", "शक्कर"], "hi_tr": ["cheeni", "chini", "shakkar"]},
    "Wheat Flour": {"en": ["wheat flour", "flour", "atta", "maida", "wheat"], "ta": ["கோதுமை மாவு", "கோதுமை", "மாவு"], "ta_tr": ["godhumai maavu", "godhumai", "maavu"],
                    "hi": ["गेहूं का आटा", "आटा", "मैदा"], "hi_tr": ["aata"]},
    "Tea Powder": {"en": ["tea powder", "tea", "chai"], "ta": ["தேயிலை", "தேநீர்", "டீத்தூள்", "டீ"], "ta_tr": ["theyilai"], "hi": ["चायपत्ती", "चाय"], "hi_tr": ["chaipatti"]},
    "Biscuits": {"en": ["biscuits", "biscuit", "cookies"], "ta": ["பிஸ்கட்", "பிஸ்கெட்"], "ta_tr": [], "hi": ["बिस्किट", "बिस्कुट"], "hi_tr": ["biskut"]},
    "Detergent": {"en": ["detergent", "washing powder"], "ta": ["சலவை தூள்", "டிடர்ஜென்ட்"], "ta_tr": [], "hi": ["डिटर्जेंट", "सर्फ"], "hi_tr": ["surf"]},
    "Soap": {"en": ["soap", "soaps"], "ta": ["சோப்பு", "சோப்"], "ta_tr": ["soappu"], "hi": ["साबुन"], "hi_tr": ["sabun"]},
    "Shampoo Sachets": {"en": ["shampoo sachets", "shampoo", "sachets"], "ta": ["ஷாம்பு"], "ta_tr": [], "hi": ["शैम्पू", "शैंपू"], "hi_tr": []},
    "Noodles": {"en": ["noodles", "maggi"], "ta": ["நூடுல்ஸ்"], "ta_tr": [], "hi": ["नूडल्स", "मैगी"], "hi_tr": []},
    "Salt": {"en": ["salt"], "ta": ["உப்பு"], "ta_tr": ["uppu"], "hi": ["नमक"], "hi_tr": ["namak"]},
}
LANG_NAME = {"en": "English", "ta": "Tamil", "hi": "Hindi"}
ALIAS_MAP: dict[str, tuple[str, str]] = {}
for _p, _d in VOCAB.items():
    for _tag, _al in _d.items():
        for _a in _al:
            ALIAS_MAP[_n(_a.lower())] = (_p, _tag)
MAX_PHRASE = max(len(a.split()) for a in ALIAS_MAP)

# unit token -> (canonical unit, factor into that unit)
_UNIT_GROUPS = [
    ("kg", 1, ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "கிலோ", "கிலோகிராம்", "किलो", "किलोग्राम", "केजी"]),
    ("L", 1, ["l", "ltr", "ltrs", "litre", "litres", "liter", "liters", "லிட்டர்", "லிட்", "लीटर", "लिटर"]),
    ("kg", 100, ["quintal", "quintals", "குவிண்டால்", "क्विंटल"]),
    ("kg", 1000, ["ton", "tons", "tonne", "tonnes", "டன்", "टन"]),
    ("kg", 0.001, ["g", "gm", "gms", "gram", "grams", "கிராம்", "ग्राम"]),
    ("carton", 1, ["carton", "cartons", "ctn", "கார்டன்", "कार्टन"]),
    ("box", 1, ["box", "boxes", "pack", "packs", "packet", "packets", "பெட்டி", "பாக்கெட்", "डिब्बा", "डिब्बे", "पैकेट"]),
]
UNITS = {_n(t): (c, f) for c, f, toks in _UNIT_GROUPS for t in toks}

_NUM_GROUPS = [
    # English
    {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
     "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
     "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000},
    # romanised Hindi
    {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
     "das": 10, "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20, "pachees": 25, "tees": 30, "chalis": 40, "pachas": 50,
     "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90, "sau": 100, "hazaar": 1000, "hazar": 1000},
    # romanised Tamil
    {"onru": 1, "oru": 1, "rendu": 2, "moonru": 3, "moonu": 3, "naangu": 4, "naalu": 4, "ainthu": 5, "anju": 5, "aaru": 6, "ezhu": 7,
     "ettu": 8, "onbathu": 9, "pathu": 10, "irubathu": 20, "irupathu": 20, "muppathu": 30, "naarpathu": 40, "aimbathu": 50,
     "ambathu": 50, "aravathu": 60, "ezhubathu": 70, "enbathu": 80, "thonnooru": 90, "nooru": 100, "irunooru": 200,
     "ainooru": 500, "aayiram": 1000},
    # Tamil script
    {"ஒன்று": 1, "ஒரு": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "அஞ்சு": 5, "ஆறு": 6, "ஏழு": 7, "எட்டு": 8,
     "ஒன்பது": 9, "பத்து": 10, "இருபது": 20, "முப்பது": 30, "நாற்பது": 40, "ஐம்பது": 50, "அறுபது": 60, "எழுபது": 70,
     "எண்பது": 80, "தொண்ணூறு": 90, "நூறு": 100, "இருநூறு": 200, "ஐநூறு": 500, "ஆயிரம்": 1000},
    # Devanagari
    {"एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
     "बीस": 20, "पच्चीस": 25, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
     "सौ": 100, "हज़ार": 1000, "हजार": 1000},
]
NUMWORDS = {_n(k): v for g in _NUM_GROUPS for k, v in g.items()}
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")} | {ord(c): str(i) for i, c in enumerate("௦௧௨௩௪௫௬௭௮௯")}
_SEP = re.compile(r"[,;\n+&|]|(?<!\S)(?:and|aur|mattrum|matrum|மற்றும்|மேலும்|और|तथा)(?!\S)", re.I)
_RUPEE = r"(?:rs\.?|inr|₹|rupees?|ரூபாய்\S*|ரூ\.?|रुपये|रुपए|रु\.?)"
_NUM = r"(\d+(?:\.\d+)?)"
_BUDGET_RES = [
    re.compile(r"(?:budget|பட்ஜெட்\S*|बजट|within|under|upto|up to|below|max(?:imum)?)\s*(?:of|is|:|=)?\s*" + _RUPEE + r"?\s*" + _NUM + r"(?:\s*" + _RUPEE + r")?", re.I),
    re.compile(_RUPEE + r"\s*" + _NUM, re.I),
    re.compile(_NUM + r"\s*" + _RUPEE, re.I),
]


def _lookup(table: dict, tok: str):
    if tok in table:
        return table[tok]
    if tok.isascii():
        if len(tok) > 3 and tok.endswith("s") and tok[:-1] in table:
            return table[tok[:-1]]
        return None
    for k in range(len(tok) - 1, 2, -1):          # Tamil/Hindi suffixes: அரிசியும் -> அரிசி
        if tok[:k] in table and not tok[:k].isascii():
            return table[tok[:k]]
    return None


def detect_language(text: str) -> dict:
    ta = sum(1 for c in text if "஀" <= c <= "௿")
    hi = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    toks = [_n(t.strip(".,;:!?()").lower()) for t in text.split()]
    tr = {"ta": 0, "hi": 0}
    for t in toks:
        hit = ALIAS_MAP.get(t)
        if hit and hit[1] in ("ta_tr", "hi_tr"):
            tr[hit[1][:2]] += 1
    if ta >= hi and ta > 0:
        return {"code": "ta", "name": "Tamil", "script": "Tamil", "method": "Unicode script detection"}
    if hi > 0:
        return {"code": "hi", "name": "Hindi", "script": "Devanagari", "method": "Unicode script detection"}
    if tr["ta"] > tr["hi"]:
        return {"code": "ta", "name": "Tamil (romanised)", "script": "Latin", "method": "Romanised vocabulary match"}
    if tr["hi"] > 0:
        return {"code": "hi", "name": "Hindi (romanised)", "script": "Latin", "method": "Romanised vocabulary match"}
    return {"code": "en", "name": "English", "script": "Latin", "method": "Default (no Tamil/Hindi script or vocabulary found)"}


def _normalise(text: str) -> str:
    t = _n(text).translate(_DIGIT_MAP)
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)                 # 6,000 -> 6000
    t = re.sub(r"(?<=\d)(?=[^\W\d_]|[^\x00-\x7f])", " ", t)         # 50kg -> 50 kg ; 50கிலோ -> 50 கிலோ
    t = re.sub(r"(?<=[^\x00-\x7f])(?=\d)", " ", t)
    return t


def _extract_budget(text: str) -> tuple[float | None, str]:
    for rx in _BUDGET_RES:
        m = rx.search(text)
        if m:
            return float(m.group(m.lastindex)), (text[:m.start()] + " " + text[m.end():])
    return None, text


def _scan(tokens: list[str]) -> list[dict]:
    """Walk tokens left to right and emit product / number / unit events."""
    low = [_n(t.lower()) for t in tokens]

    def prod_at(i: int):
        for n in range(min(MAX_PHRASE, len(low) - i), 0, -1):
            ph = " ".join(low[i:i + n])
            hit = ALIAS_MAP.get(ph)
            if not hit and n == 1:
                hit = _lookup(ALIAS_MAP, ph)
            if hit:
                return hit, n
        return None, 0

    ev, i = [], 0
    while i < len(low):
        hit, n = prod_at(i)
        if hit:
            ev.append({"k": "prod", "s": i, "e": i + n, "product": hit[0], "tag": hit[1], "text": " ".join(tokens[i:i + n])})
            i += n
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", low[i]):
            ev.append({"k": "num", "s": i, "e": i + 1, "v": float(low[i])})
            i += 1
            continue
        u = _lookup(UNITS, low[i])
        if u:
            ev.append({"k": "unit", "s": i, "e": i + 1, "u": u, "text": tokens[i]})
            i += 1
            continue
        if _lookup(NUMWORDS, low[i]) is not None:                     # number words: "ஐம்பது", "pachas", "fifty"
            j, total, cur = i, 0, 0
            while j < len(low) and _lookup(NUMWORDS, low[j]) is not None:
                v = _lookup(NUMWORDS, low[j])
                cur = (cur or 1) * v if v in (100, 1000) else cur + v
                j += 1
            total = cur
            nxt_prod, _ = prod_at(j) if j < len(low) else (None, 0)
            if (j < len(low) and _lookup(UNITS, low[j])) or nxt_prod:   # only count as a quantity next to a unit/product
                ev.append({"k": "num", "s": i, "e": j, "v": float(total), "words": True})
                i = j
                continue
        i += 1
    return ev


def _assign(ev: list[dict]) -> dict[int, dict]:
    """Pair each product with the nearest number(+unit) block. Style (number-first vs product-first) decides tie-breaks."""
    blocks = []
    for k, e in enumerate(ev):
        if e["k"] == "num":
            nxt = ev[k + 1] if k + 1 < len(ev) and ev[k + 1]["k"] == "unit" and ev[k + 1]["s"] == e["e"] else None
            blocks.append({"s": e["s"], "e": nxt["e"] if nxt else e["e"], "v": e["v"], "unit": nxt["u"] if nxt else None, "ut": nxt["text"] if nxt else None})
    first_is_num = bool(ev) and ev[0]["k"] in ("num",) or (len(ev) > 1 and ev[0]["k"] == "unit")
    pairs = []
    for pi, p in enumerate(ev):
        if p["k"] != "prod":
            continue
        for bi, b in enumerate(blocks):
            before, after = p["s"] - b["e"], b["s"] - p["e"]
            if before >= 0:
                pairs.append((before + (0 if first_is_num else 0.5), pi, bi))
            if after >= 0:
                pairs.append((after + (0.5 if first_is_num else 0), pi, bi))
    pairs.sort()
    used_p, used_b, out = set(), set(), {}
    for _, pi, bi in pairs:
        if pi in used_p or bi in used_b:
            continue
        used_p.add(pi), used_b.add(bi)
        out[pi] = blocks[bi]
    return out


def _convert(qty: float, unit, prod_unit: str) -> tuple[float, str | None]:
    if not unit:
        return qty, None
    canon, factor = unit
    q = qty * factor
    if canon == prod_unit or (canon in ("box", "carton") and prod_unit in ("box", "carton")):
        return q, None
    if canon in ("kg", "L") and prod_unit in ("kg", "L"):
        return q, f"treated {canon} as {prod_unit}"
    return qty, f"unit '{canon}' does not fit - assumed {prod_unit}"


def parse_request(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ApiError(400, "Tell me what you need, e.g. '50 kg rice and 20 L oil, budget 6000' (Tamil/Hindi also works)")
    lang = detect_language(raw)
    budget, rest = _extract_budget(_normalise(raw))
    lines: dict[str, dict] = {}
    unknown: list[str] = []
    for chunk in _SEP.split(rest):
        toks = [t.strip(".,;:!?()[]{}\"'") for t in chunk.split()]
        toks = [t for t in toks if t]
        if not toks:
            continue
        ev = _scan(toks)
        prods = [e for e in ev if e["k"] == "prod"]
        if not prods:
            if any(c.isalpha() for c in chunk) and not all(_lookup(NUMWORDS, _n(t.lower())) is not None or t.isdigit() for t in toks):
                unknown.append(chunk.strip())
            continue
        pairing = _assign(ev)
        for pi, e in enumerate(ev):
            if e["k"] != "prod":
                continue
            meta = db.one("SELECT typical_qty, unit FROM products WHERE name=?", (e["product"],))
            blk = pairing.get(pi)
            qty, note, assumed = meta["typical_qty"], None, True
            if blk:
                qty, note = _convert(blk["v"], blk["unit"], meta["unit"])
                assumed = False
            cur = lines.get(e["product"])
            if cur:
                cur["qty"] = round(cur["qty"] + qty, 3)
                cur["assumed_qty"] = cur["assumed_qty"] and assumed
            else:
                lines[e["product"]] = {"product": e["product"], "qty": round(qty, 3), "unit": meta["unit"], "assumed_qty": assumed,
                                       "heard": e["text"], "note": note}
    ls = list(lines.values())
    english = ", ".join(f"{l['qty']:g} {l['unit']} {l['product']}" for l in ls)
    if budget:
        english += f" (budget Rs {budget:,.0f})"
    return {"lines": ls, "budget": budget, "unrecognised": unknown, "language": lang, "english": english,
            "single_product": len(ls) == 1}


def match_products(text: str) -> list[str]:
    """Product names mentioned anywhere in the text (any supported language) - used by search."""
    toks = [t.strip(".,;:!?()") for t in _normalise(text or "").split()]
    return list(dict.fromkeys(e["product"] for e in _scan([t for t in toks if t]) if e["k"] == "prod"))


# ================================================================== 1b. procurement ranking (inventory database)

SORTS = ("best", "price", "rating", "eta")
W_PRICE, W_RATING, W_ETA = 0.50, 0.30, 0.20


def _score_suppliers(uid: int, lines: list[dict]) -> list[dict]:
    me = db.one("SELECT * FROM users WHERE id=?", (uid,))
    cands = []
    for w in db.rows("SELECT id, name, shop, city, rating_avg, rating_count, on_time_rate FROM users WHERE role='wholesaler'"):
        covered, missing, total, ref, eta = [], [], 0.0, 0.0, 1
        for ln in lines:
            row = db.one("SELECT c.price, c.stock_qty, c.updated_at, p.base_price, p.unit, wh.name wh_name, wh.city wh_city, wh.handling_days"
                         " FROM catalog c JOIN products p ON p.name=c.product JOIN warehouses wh ON wh.id=c.warehouse_id"
                         " WHERE c.wholesaler_id=? AND c.product=?", (w["id"], ln["product"]))
            if not row or row["stock_qty"] < ln["qty"]:
                missing.append(ln["product"])
                continue
            cost = round(row["price"] * ln["qty"], 2)
            total += cost
            ref += row["base_price"] * ln["qty"]
            line_eta = db.eta_days(row["wh_city"], me["city"], row["handling_days"])
            eta = max(eta, line_eta)
            covered.append({"product": ln["product"], "qty": ln["qty"], "unit": row["unit"], "unit_price": row["price"], "cost": cost,
                            "stock_qty": row["stock_qty"], "stock_as_of": row["updated_at"][:10], "warehouse": row["wh_name"],
                            "warehouse_city": row["wh_city"], "eta_days": line_eta})
        if covered:
            cands.append({"wholesaler": w, "lines": covered, "missing": missing, "total": round(total, 2), "ratio": total / ref,
                          "eta_days": eta, "same_city": w["city"] == me["city"],
                          "ships_from": sorted({c["warehouse_city"] for c in covered})})
    if not cands:
        return []
    best = min(c["ratio"] for c in cands)
    for c in cands:
        w = c["wholesaler"]
        price_s = max(0.0, 1 - (c["ratio"] - best) / 0.10)
        rating_s = (w["rating_avg"] / 5) if w["rating_count"] else 0.7
        eta_s = max(0.0, 1 - (c["eta_days"] - 1) / 5)
        cover = len(c["lines"]) / len(lines)
        c["score"] = round(100 * (W_PRICE * price_s + W_RATING * rating_s + W_ETA * eta_s) * cover, 1)
        c["score_parts"] = {"price": round(100 * W_PRICE * price_s, 1), "rating": round(100 * W_RATING * rating_s, 1), "eta": round(100 * W_ETA * eta_s, 1)}
        c["coverage"] = round(100 * cover)
        c["vs_market_pct"] = round((1 - c["ratio"]) * 100, 1)
    return cands


def _sort(c: list[dict], mode: str) -> list[dict]:
    full = lambda x: 1 if x["missing"] else 0                      # suppliers that cover everything always come first
    keys = {"best": lambda x: (full(x), -x["score"]),
            "price": lambda x: (full(x), x["ratio"], x["eta_days"]),
            "rating": lambda x: (full(x), -x["wholesaler"]["rating_avg"], -x["wholesaler"]["rating_count"], x["ratio"]),
            "eta": lambda x: (full(x), x["eta_days"], x["ratio"])}
    return sorted(c, key=keys[mode])


def procurement(uid: int, text: str, sort: str = "best") -> dict:
    if sort not in SORTS:
        raise ApiError(400, f"sort must be one of {', '.join(SORTS)}")
    me = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not me or me["role"] != "merchant":
        raise ApiError(403, "The procurement agent is for merchants")
    parsed = parse_request(text)
    lines = parsed["lines"]
    if not lines:
        raise ApiError(400, "I couldn't recognise any product. Try e.g. '50 kg rice and 20 L oil' (Tamil/Hindi also works).")
    ranked = _sort(_score_suppliers(uid, lines), sort)
    if not ranked:
        raise ApiError(404, "No supplier currently has these items in stock")
    budget = parsed["budget"]
    for i, c in enumerate(ranked):
        c["rank"] = i + 1
        c["within_budget"] = budget is None or c["total"] <= budget
        w = c["wholesaler"]
        why = [{"best": "Best overall mix of price, rating and arrival time", "price": "Lowest price vs market",
                "rating": "Highest rated", "eta": "Fastest arrival"}[sort] if i == 0 else None]
        if c["vs_market_pct"] > 0:
            why.append(f"{c['vs_market_pct']}% below market price")
        why.append(f"arrives in ~{c['eta_days']} day(s) from {', '.join(c['ships_from'])}")
        why.append(f"rated {w['rating_avg']:.1f}/5 ({w['rating_count']} reviews)" if w["rating_count"] else "no ratings yet")
        if c["missing"]:
            why.append("cannot supply: " + ", ".join(c["missing"]))
        if budget is not None and not c["within_budget"]:
            why.append(f"Rs {c['total'] - budget:,.0f} over budget")
        c["reason"] = "; ".join(x for x in why if x)
        c["delivery_note"] = "Goods price only. Delivery is quoted by the wholesaler after you order."
        c["rank_basis"] = sort
    top = ranked[:5]
    note = None
    if budget is not None:
        ok = [c for c in ranked if c["within_budget"] and not c["missing"]]
        if ok:
            note = f"{len(ok)} supplier(s) fit your budget of Rs {budget:,.0f} (goods only, delivery extra)."
        else:
            best = ranked[0]
            if len(lines) == 1 and best["lines"]:
                ln = best["lines"][0]
                note = (f"Rs {budget:,.0f} buys about {math.floor(budget / ln['unit_price'])} {ln['unit']} of {ln['product']} "
                        f"at the best price (Rs {ln['unit_price']:g}/{ln['unit']}).")
            else:
                over = round((best["total"] / budget - 1) * 100) if budget else 0
                note = f"Your list costs Rs {best['total']:,.0f} at the best supplier - about {over}% over your Rs {budget:,.0f} budget. Reduce quantities or use a group pool."
    split = None
    if len(lines) > 1:
        picks, total = [], 0.0
        for ln in lines:
            r = db.one("SELECT c.wholesaler_id, c.price, u.shop FROM catalog c JOIN users u ON u.id=c.wholesaler_id"
                       " WHERE c.product=? AND c.stock_qty>=? ORDER BY c.price LIMIT 1", (ln["product"], ln["qty"]))
            if r:
                picks.append({"product": ln["product"], "wholesaler_id": r["wholesaler_id"], "shop": r["shop"], "unit_price": r["price"],
                              "cost": round(r["price"] * ln["qty"], 2)})
                total += r["price"] * ln["qty"]
        if len(picks) == len(lines) and len({p["wholesaler_id"] for p in picks}) > 1:
            split = {"picks": picks, "total": round(total, 2), "deliveries": len({p["wholesaler_id"] for p in picks}),
                     "note": "Cheapest wholesaler per product - but each wholesaler quotes its own delivery charge."}
    pools, sales = [], []
    for ln in lines:
        for p in db.rows("SELECT p.* FROM pools p JOIN sales s ON s.id=p.sale_id JOIN memberships m ON m.group_id=p.group_id"
                         " WHERE m.user_id=? AND m.status='active' AND p.status='open' AND s.product=?", (uid, ln["product"])):
            v = market.pool_view(p, uid)
            if v["is_open"]:
                pools.append({"pool_id": v["id"], "group_id": v["group_id"], "group": v["group"], "product": v["product"], "unit": v["unit"],
                              "current_price": v["current_price"], "best_tier_price": v["tiers"][-1]["price"], "best_tier_qty": v["tiers"][-1]["min_qty"]})
        for s in market.list_sales(uid, product=ln["product"])[:2]:
            sales.append({"sale_id": s["id"], "product": s["product"], "unit": s["unit"], "wholesaler": s["wholesaler"]["shop"],
                          "entry_price": s["entry_price"], "best_price": s["best_price"], "kind": s["kind"]})
    lang = parsed["language"]
    return {"parsed": parsed, "sort": sort, "suppliers": top, "all_count": len(ranked), "budget_note": note, "split_basket": split,
            "group_pools": pools, "live_sales": sales,
            "understood": (f"Understood ({lang['name']}): {parsed['english']}" if lang["code"] != "en" else f"Understood: {parsed['english']}"),
            "summary": f"Compared {len(ranked)} supplier(s) from the live inventory database, ranked by '{sort}'. Top: {top[0]['wholesaler']['shop']} at Rs {top[0]['total']:,.0f} for the goods.",
            "method": "Rule-based parser + weighted scoring (50% price, 30% rating, 20% arrival time). No LLM."}


# ================================================================== 2. demand forecast

FESTIVALS = [  # (name, date, product multipliers) - demo calendar
    ("Diwali", date(2026, 11, 8), {"Sugar": 1.8, "Sunflower Oil": 1.6, "Toor Dal": 1.3, "Biscuits": 1.7, "Soap": 1.3}),
    ("Christmas", date(2026, 12, 25), {"Sugar": 1.5, "Wheat Flour": 1.5, "Biscuits": 1.6, "Tea Powder": 1.2}),
    ("Pongal", date(2027, 1, 14), {"Rice": 1.8, "Sugar": 1.6, "Sunflower Oil": 1.4, "Toor Dal": 1.4}),
    ("Eid", date(2027, 3, 10), {"Rice": 1.6, "Sugar": 1.5, "Sunflower Oil": 1.5, "Tea Powder": 1.3}),
    ("Ugadi / Tamil New Year", date(2027, 4, 14), {"Rice": 1.4, "Sugar": 1.3, "Sunflower Oil": 1.3}),
]
ALPHA, WINDOW_DAYS, FESTIVAL_LEAD, COVER_DAYS = 0.3, 60, 14, 14

MODEL_INFO = {
    "name": "Exponential smoothing x weekday index x festival multiplier",
    "type": "Classical statistics, hand-coded in Python. Not machine learning - no Prophet, XGBoost or LLM.",
    "steps": [
        "1. Take the last 60 days of daily usage per product (units sold/used, from POS item sales and manual logs).",
        "2. Weekday index = average usage on that weekday / overall average (captures weekend lifts).",
        "3. Remove the weekday effect, then smooth with exponential smoothing (alpha = 0.3) to get today's base daily demand.",
        "4. Forecast each future day = base demand x weekday index x festival multiplier (only in the 14 days before a festival).",
        "5. Walk the stock forward day by day; the day it hits zero is the predicted stock-out. Suggested order = 14-day demand minus stock.",
    ],
    "alert_rule": "Critical: stock-out in 4 days or less. Warning: 7 days or less.",
}
TRACKING_INFO = {
    "formula": "Stock on hand = last stock count + deliveries received - daily usage logged",
    "sources": [
        "Deliveries: when you confirm an order as received, the quantity is added to your stock automatically.",
        "Usage: item-level sales from Paytm POS / QR (simulated in this demo) or your manual 'log usage' entries reduce stock.",
        "Stock count: you can reset the figure any time after a physical count.",
    ],
}


def _festival(as_of: date, force: str | None):
    if force:
        f = next((x for x in FESTIVALS if x[0].lower().startswith(force.lower())), None)
        if not f:
            raise ApiError(400, "Unknown festival. Try Diwali, Christmas, Pongal, Eid or Ugadi.")
        return (f[0], as_of + timedelta(days=10), f[2], True)          # what-if: pretend it is 10 days away
    for f in sorted(FESTIVALS, key=lambda x: x[1]):
        if 0 <= (f[1] - as_of).days <= 30:
            return (f[0], f[1], f[2], False)
    return None


def _model(uid: int, product: str, as_of: date):
    rows = db.rows("SELECT day, qty FROM consumption WHERE user_id=? AND product=? AND day>=? AND day<? ORDER BY day",
                   (uid, product, (as_of - timedelta(days=WINDOW_DAYS)).isoformat(), as_of.isoformat()))
    if len(rows) < 7:
        return None
    by = {r["day"]: r["qty"] for r in rows}
    d0 = date.fromisoformat(rows[0]["day"])
    days = [d0 + timedelta(days=k) for k in range((as_of - d0).days)]
    xs = [by.get(d.isoformat(), 0.0) for d in days]
    mean = sum(xs) / len(xs)
    if mean <= 0:
        return None
    idx = []
    for wd in range(7):
        v = [x for d, x in zip(days, xs) if d.weekday() == wd]
        idx.append(max(0.6, min(1.6, (sum(v) / len(v)) / mean)) if len(v) >= 3 else 1.0)
    level = None
    for d, x in zip(days, xs):
        z = x / idx[d.weekday()]
        level = z if level is None else ALPHA * z + (1 - ALPHA) * level
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))
    cv = sd / mean
    return {"level": level, "idx": idx, "n": len(xs), "cv": cv, "last_logged": rows[-1]["day"]}


def forecast(uid: int, festival: str | None = None, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    fest = _festival(as_of, festival)
    out = []
    for inv in db.rows("SELECT i.*, p.unit FROM inventory i JOIN products p ON p.name=i.product WHERE i.user_id=?", (uid,)):
        m = _model(uid, inv["product"], as_of)
        if not m:
            continue
        mults = fest[2].get(inv["product"], 1.0) if fest else 1.0

        def demand(day: date) -> float:
            f = mults if fest and 0 <= (fest[1] - day).days <= FESTIVAL_LEAD else 1.0
            return m["level"] * m["idx"][day.weekday()] * f

        stock, days_left = inv["stock"], 999.0
        for k in range(WINDOW_DAYS):
            dem = demand(as_of + timedelta(days=k))
            if stock < dem:
                days_left = k + (stock / dem if dem else 0)
                break
            stock -= dem
        need14 = sum(demand(as_of + timedelta(days=k)) for k in range(COVER_DAYS))
        reorder = max(0.0, need14 - inv["stock"])
        reorder = math.ceil(reorder / 5) * 5 if inv["unit"] in ("kg", "L") else math.ceil(reorder)
        level = "critical" if days_left <= 4 else ("warning" if days_left <= 7 else "ok")
        stock_out = (as_of + timedelta(days=int(days_left))).isoformat() if days_left < 999 else None
        conf = "high" if m["cv"] < 0.25 else ("medium" if m["cv"] < 0.5 else "low")
        base = m["level"] * m["idx"][as_of.weekday()]
        left = f"~{max(0, math.floor(days_left))} day(s)" if days_left < 999 else "60+ days"
        msg = (f"{inv['product']} will run out in {left}" + (f" (festival demand x{mults})" if mults > 1 and fest else "")) if level != "ok" else \
              f"{inv['product']} stock is healthy ({left})"
        out.append({"product": inv["product"], "unit": inv["unit"], "stock": round(inv["stock"], 1), "daily_use": round(base, 2),
                    "festival_multiplier": mults if fest else 1.0, "days_left": round(days_left, 1), "stock_out_date": stock_out, "level": level,
                    "suggested_qty": reorder if level != "ok" else 0, "message": msg, "confidence": conf,
                    "history_days": m["n"], "last_usage_logged": m["last_logged"],
                    "source": f"Smoothed usage {base:.1f} {inv['unit']}/day over {m['n']} days of history; stock {inv['stock']:.0f} {inv['unit']}"})
    order = {"critical": 0, "warning": 1, "ok": 2}
    out.sort(key=lambda x: (order[x["level"]], x["days_left"]))
    return {"as_of": as_of.isoformat(),
            "festival": ({"name": fest[0], "date": fest[1].isoformat(), "days_away": (fest[1] - as_of).days, "what_if": fest[3]} if fest else None),
            "items": out, "alerts": [x for x in out if x["level"] != "ok"], "model": MODEL_INFO, "tracking": TRACKING_INFO}


# ================================================================== 3. smart negotiator (floor-price driven)

ROUNDS = 6


def seller_profile(price: float, floor: float, stock: float, qty: float, typical: float) -> dict:
    """The seller agent's private strategy. reserve >= the wholesaler's floor price; beta shapes how fast it concedes."""
    cover = stock / qty if qty else 99
    volume = qty / typical if typical else 1
    premium, beta, stance = 0.0, 1.0, "balanced"
    if cover < 3:
        premium, beta, stance = 0.04, 0.5, "firm - limited stock"
    elif cover < 8:
        premium, beta, stance = 0.02, 0.75, "slightly firm - moderate stock"
    elif cover > 20 and volume >= 2:
        beta, stance = 2.0, "flexible - plenty of stock and a bulk order"
    if volume >= 3:
        beta *= 1.3
    return {"reserve": round(min(price * 0.99, floor * (1 + premium)), 2), "beta": beta, "stance": stance}


def _ask(price: float, reserve: float, beta: float, t: int) -> float:
    """Faratin time-dependent tactic: price - (price - reserve) * (t/T)^(1/beta)."""
    return round(price - (price - reserve) * (t / ROUNDS) ** (1 / beta), 2)


def negotiate(uid: int, wholesaler_id: int, product: str, qty, max_price) -> dict:
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u or u["role"] != "merchant":
        raise ApiError(403, "Only merchants can negotiate")
    try:
        qty, limit = float(qty), float(max_price)
    except (TypeError, ValueError):
        raise ApiError(400, "Quantity and max price must be numbers") from None
    if qty <= 0 or limit <= 0:
        raise ApiError(400, "Quantity and max price must be positive")
    row = db.one("SELECT c.*, p.typical_qty, p.unit, w.shop FROM catalog c JOIN products p ON p.name=c.product"
                 " JOIN users w ON w.id=c.wholesaler_id WHERE c.wholesaler_id=? AND c.product=?", (wholesaler_id, product))
    if not row:
        raise ApiError(404, "That wholesaler does not stock this product")
    if row["stock_qty"] < qty:
        raise ApiError(400, f"Only {row['stock_qty']:g} {row['unit']} in stock")
    lp, unit = row["price"], row["unit"]
    sp = seller_profile(lp, row["floor_price"], row["stock_qty"], qty, row["typical_qty"])
    open_bid = round(min(limit, lp * 0.85), 2)

    def bid(t: int) -> float:
        return round(open_bid + (limit - open_bid) * (t - 1) / (ROUNDS - 1), 2)

    t = [{"agent": "seller", "price": lp, "text": f"Seller agent ({row['shop']}): list price Rs {lp:g}/{unit} for {qty:g} {unit}."}]
    agreed, status = None, "no_deal"
    last_ask = lp
    for r in range(1, ROUNDS + 1):
        b = bid(r)
        t.append({"agent": "buyer", "price": b, "text": f"Buyer agent (round {r}): I can pay Rs {b:g}/{unit}."})
        ask = _ask(lp, sp["reserve"], sp["beta"], r)
        if b >= ask:
            agreed, status = b, "deal"
            t.append({"agent": "seller", "price": b, "text": f"Seller agent: accepted at Rs {b:g}/{unit}."})
            break
        last_ask = ask
        t.append({"agent": "seller", "price": ask, "text": f"Seller agent: counter - Rs {ask:g}/{unit}."})
        nxt = bid(min(r + 1, ROUNDS))
        if ask <= nxt or (r == ROUNDS and ask <= limit):
            agreed, status = ask, "deal"
            t.append({"agent": "buyer", "price": ask, "text": f"Buyer agent: Rs {ask:g}/{unit} is within my plan - deal."})
            break
    if status == "deal":
        t.append({"agent": "system", "price": agreed, "text": f"Deal at Rs {agreed:g}/{unit} - saves Rs {(lp - agreed) * qty:,.0f} versus list (goods only; delivery quoted later)."})
    else:
        t.append({"agent": "system", "price": None, "text": f"No deal: the seller would not go below Rs {last_ask:g}/{unit}; your limit is Rs {limit:g}."})
    nid = db.run("INSERT INTO negotiations(user_id,wholesaler_id,product,qty,list_price,buyer_limit,agreed_price,status,transcript,created_at)"
                 " VALUES(?,?,?,?,?,?,?,?,?,?)", (uid, wholesaler_id, product, qty, lp, limit, agreed, status, json.dumps(t), db.now_iso()))
    return {"id": nid, "status": status, "list_price": lp, "agreed_price": agreed, "qty": qty, "unit": unit, "product": product,
            "wholesaler": row["shop"], "transcript": t, "seller_stance": sp["stance"], "last_ask": last_ask,
            "savings": round((lp - agreed) * qty, 2) if agreed else 0, "total": round(agreed * qty, 2) if agreed else None,
            "method": "Faratin time-dependent concession over 6 rounds. The seller's reserve is the wholesaler's private floor price, "
                      "adjusted for live stock and order size. The buyer concedes linearly up to your limit."}


def accept_negotiation(nid: int, uid: int) -> dict:
    n = db.one("SELECT * FROM negotiations WHERE id=?", (nid,))
    if not n or n["user_id"] != uid:
        raise ApiError(404, "Negotiation not found")
    if n["status"] != "deal":
        raise ApiError(400, "There is no deal to accept")
    if n["order_id"]:
        raise ApiError(409, "Already ordered")
    res = orders.place(uid, n["wholesaler_id"], [{"product": n["product"], "qty": n["qty"]}], source=f"negotiation:{nid}",
                       unit_prices={n["product"]: n["agreed_price"]})
    db.run("UPDATE negotiations SET order_id=? WHERE id=?", (res["order_id"], nid))
    return res
