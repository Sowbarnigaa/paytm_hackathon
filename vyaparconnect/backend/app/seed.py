"""Deterministic demo seed (v2): wholesalers with warehouses + private floor prices, merchants, merchant-only groups,
reviews, 90 days of purchases and daily consumption, POS payments, sales, demands, notifications."""
import json
import random
from datetime import date, datetime, timedelta, timezone

from . import auth, db

DEMO_PASSWORD = "Demo@1234"                       # every seeded demo account signs in with this (demo data only)
_DEMO_HASH = auth.hash_password(DEMO_PASSWORD)    # hashed once - scrypt is deliberately slow


def demo_email(name: str) -> str:
    return name.split()[0].lower() + "@example.com"     # e.g. ravi@example.com, murugan@example.com

PRODUCTS = [
    ("Rice", "kg", 55, "grocery", 50), ("Sunflower Oil", "L", 130, "grocery", 20),
    ("Toor Dal", "kg", 120, "grocery", 25), ("Sugar", "kg", 42, "grocery", 40),
    ("Wheat Flour", "kg", 38, "grocery", 40), ("Tea Powder", "kg", 380, "grocery", 5),
    ("Biscuits", "carton", 480, "fmcg", 10), ("Detergent", "box", 620, "fmcg", 5),
    ("Soap", "carton", 540, "fmcg", 6), ("Shampoo Sachets", "carton", 700, "fmcg", 4),
    ("Noodles", "carton", 560, "fmcg", 8), ("Salt", "kg", 20, "grocery", 30),
]

# name, shop, city, category, phone, warehouses [(name, city, handling_days)], price factor
WHOLESALERS = [
    ("Murugan Traders", "Murugan Traders", "Erode", "both", "9840011111", [("Erode Main", "Erode", 1), ("Salem Depot", "Salem", 1)], 0.97),
    ("Kaveri Wholesale", "Kaveri Wholesale Mart", "Erode", "grocery", "9840022222", [("Erode Yard", "Erode", 1)], 0.95),
    ("Annapoorna Agencies", "Annapoorna Agencies", "Coimbatore", "both", "9840033333", [("Coimbatore Hub", "Coimbatore", 1), ("Tiruppur Depot", "Tiruppur", 1)], 0.96),
    ("Sri Lakshmi Distributors", "Sri Lakshmi Dist.", "Coimbatore", "fmcg", "9840044444", [("Coimbatore Godown", "Coimbatore", 2)], 1.0),
    ("Chennai Bulk Mart", "Chennai Bulk Mart", "Chennai", "both", "9840055555", [("Chennai Central", "Chennai", 1)], 0.98),
    ("Marina FMCG Hub", "Marina FMCG Hub", "Chennai", "fmcg", "9840066666", [("Chennai Port Road", "Chennai", 1)], 1.02),
]

MERCHANTS = [
    ("Ravi", "Ravi's Grocery", "Erode", "grocery"), ("Kumar", "Kumar Stores", "Erode", "grocery"),
    ("Lakshmi", "Lakshmi Provision", "Erode", "grocery"), ("Senthil", "Senthil Mart", "Erode", "grocery"),
    ("Priya", "Priya General Store", "Erode", "grocery"), ("Arun", "Arun Super", "Erode", "grocery"),
    ("Meena", "Meena Kirana", "Erode", "grocery"), ("Dinesh", "Dinesh Fancy & FMCG", "Erode", "fmcg"),
    ("Saraswathi", "Saraswathi Traders", "Erode", "fmcg"), ("Bala", "Bala Cosmetics", "Erode", "fmcg"),
    ("Gopal", "Gopal Tea & Snacks", "Erode", "both"),
    ("Anand", "Anand Provision", "Coimbatore", "grocery"), ("Selvi", "Selvi Stores", "Coimbatore", "grocery"),
    ("Vijay", "Vijay Mart", "Coimbatore", "grocery"), ("Nirmala", "Nirmala Kirana", "Coimbatore", "grocery"),
    ("Suresh", "Suresh FMCG", "Coimbatore", "fmcg"), ("Revathi", "Revathi Fancy", "Coimbatore", "fmcg"),
    ("Karthik", "Karthik Super", "Coimbatore", "both"), ("Deepa", "Deepa Daily Needs", "Coimbatore", "both"),
    ("Imran", "Imran General", "Chennai", "grocery"), ("Fathima", "Fathima Stores", "Chennai", "grocery"),
    ("Joseph", "Joseph Mart", "Chennai", "grocery"), ("Hari", "Hari FMCG", "Chennai", "fmcg"),
    ("Kavitha", "Kavitha Provision", "Chennai", "both"), ("Mohan", "Mohan Super", "Chennai", "both"),
    ("Rajan", "Rajan Stores", "Salem", "grocery"), ("Geetha", "Geetha Mart", "Salem", "grocery"),
    ("Mani", "Mani Traders", "Salem", "both"),
]

COMMENTS_GOOD = ["Fresh stock, on-time delivery.", "Fair price and honest weights.", "Quick quote and careful packing.",
                 "Reliable - will order again.", "Good quality, delivered earlier than promised."]
COMMENTS_MID = ["Okay overall, delivery was a day late.", "Price fine, packaging average."]
COMMENTS_M = ["Paid on time.", "Clear requirements, easy to deal with.", "Prompt payment, genuine buyer."]


def _tier_json(price: float, m1: float = 0.95, m2: float = 0.90, q1: float = 250, q2: float = 500) -> str:
    return json.dumps([{"min_qty": 0, "price": round(price, 2)}, {"min_qty": q1, "price": round(price * m1, 2)},
                       {"min_qty": q2, "price": round(price * m2, 2)}])


def seed() -> None:
    db.create_schema()
    rnd = random.Random(42)
    ts = db.now_iso()
    today = date.today()
    in7 = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds")
    with db.conn() as c:
        c.executemany("INSERT INTO products VALUES(?,?,?,?,?)", PRODUCTS)
        pcat = {p[0]: p[3] for p in PRODUCTS}
        typical = {p[0]: p[4] for p in PRODUCTS}
        base = {p[0]: p[2] for p in PRODUCTS}

        # ---- wholesalers, warehouses, inventory catalogue (price + private floor)
        for name, shop, city, cat, phone, whs, factor in WHOLESALERS:
            wid = c.execute("INSERT INTO users(name,shop,role,city,category,phone,credit_score,on_time_rate,email,password_hash,email_verified)"
                            " VALUES(?,?,?,?,?,?,750,?,?,?,1)", (name, shop, "wholesaler", city, cat, phone,
                                                                 round(rnd.uniform(0.92, 0.99), 2), demo_email(name), _DEMO_HASH)).lastrowid
            wh_ids = [c.execute("INSERT INTO warehouses(wholesaler_id,name,city,handling_days) VALUES(?,?,?,?)",
                                (wid, n, wc, h)).lastrowid for n, wc, h in whs]
            for i, (pname, _u, bp, pc, _q) in enumerate([p for p in PRODUCTS]):
                if cat != "both" and cat != pc:
                    continue
                price = round(bp * factor * rnd.uniform(0.99, 1.02), 2)
                floor = round(price * rnd.uniform(0.88, 0.94), 2)
                c.execute("INSERT INTO catalog VALUES(?,?,?,?,?,?,?)",
                          (wid, pname, wh_ids[i % len(wh_ids)], price, floor, rnd.choice([800, 1500, 3000, 6000]), ts))

        # ---- merchants
        for name, shop, city, cat in MERCHANTS:
            score = rnd.choice([590, 640, 660, 690, 710, 735, 760, 790])
            ontime = round(min(0.99, max(0.6, 0.6 + (score - 580) / 600 + rnd.uniform(-0.05, 0.05))), 2)
            c.execute("INSERT INTO users(name,shop,role,city,category,phone,credit_score,on_time_rate,email,password_hash,email_verified)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                      (name, shop, "merchant", city, cat, f"98{rnd.randint(10000000, 99999999)}", score, ontime, demo_email(name), _DEMO_HASH))
        c.execute("UPDATE users SET credit_score=712, on_time_rate=0.92 WHERE name='Ravi'")
        n_w, n_m = len(WHOLESALERS), len(MERCHANTS)
        merchant_ids = list(range(n_w + 1, n_w + n_m + 1))
        wholesaler_ids = list(range(1, n_w + 1))
        uid_of = {m[0]: n_w + 1 + i for i, m in enumerate(MERCHANTS)}

        # ---- reviews (1..5) in both directions so ratings exist for everyone
        for wid in wholesaler_ids:
            quality = rnd.choice([4.8, 4.6, 4.3, 3.9])
            for rid in rnd.sample(merchant_ids, k=rnd.randint(5, 9)):
                r = max(1, min(5, round(rnd.gauss(quality, 0.7))))
                c.execute("INSERT INTO reviews(order_id,reviewer_id,target_id,rating,comment,created_at) VALUES(NULL,?,?,?,?,?)",
                          (rid, wid, r, rnd.choice(COMMENTS_GOOD if r >= 4 else COMMENTS_MID), ts))
        for mid in merchant_ids:
            if rnd.random() < 0.9:
                for wid in rnd.sample(wholesaler_ids, k=rnd.randint(1, 3)):
                    r = max(2, min(5, round(rnd.gauss(4.3, 0.7))))
                    c.execute("INSERT INTO reviews(order_id,reviewer_id,target_id,rating,comment,created_at) VALUES(NULL,?,?,?,?,?)",
                              (wid, mid, r, rnd.choice(COMMENTS_M), ts))
        for uid in wholesaler_ids + merchant_ids:
            a = c.execute("SELECT COUNT(*) n, COALESCE(AVG(rating),0) a FROM reviews WHERE target_id=?", (uid,)).fetchone()
            c.execute("UPDATE users SET rating_avg=?, rating_count=? WHERE id=?", (round(a["a"], 2), a["n"], uid))
        # Ravi: modest, known rating
        c.execute("UPDATE users SET rating_avg=4.2, rating_count=6 WHERE name='Ravi'")

        # ---- merchant-only groups (admin ids by name)
        groups = [
            ("Erode Grocery Buyers", "Pool rice, oil and dal orders across Erode kirana stores.", "grocery", "Erode", "invite", "Kumar"),
            ("Erode FMCG Circle", "Biscuits, soaps and detergents - weekly bulk pools.", "fmcg", "Erode", "public", "Dinesh"),
            ("Coimbatore Kirana Collective", "Coimbatore grocery merchants buying together.", "grocery", "Coimbatore", "public", "Anand"),
            ("Chennai Daily Needs", "Chennai grocery + FMCG pooled procurement.", "both", "Chennai", "invite", "Imran"),
            ("Salem Grocery Pool", "Salem merchants pooling staples.", "grocery", "Salem", "public", "Rajan"),
        ]
        members = {1: ["Lakshmi", "Senthil", "Priya", "Arun"], 2: ["Saraswathi", "Bala", "Gopal"],
                   3: ["Selvi", "Vijay", "Nirmala"], 4: ["Fathima", "Joseph", "Kavitha"], 5: ["Geetha"]}
        for gid, (name, desc, cat, city, typ, admin) in enumerate(groups, start=1):
            c.execute("INSERT INTO groups(name,description,category,city,type,admin_id,created_at) VALUES(?,?,?,?,?,?,?)",
                      (name, desc, cat, city, typ, uid_of[admin], ts))
            c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid_of[admin], "active", "admin", ts))
            for m in members[gid]:
                c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid_of[m], "active", "member", ts))
        c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (1, uid_of["Meena"], "pending", "Meena wants to join - sells rice & dal.", ts))
        for gid, uid, kind, body in [(1, "Kumar", "announcement", "Welcome! Pool orders close every Friday 6 PM."),
                                     (1, "Lakshmi", "announcement", "Anyone buying sugar this week? Let's pool."),
                                     (2, "Dinesh", "announcement", "Biscuit clearance sale is running - join a pool."),
                                     (3, "Anand", "announcement", "Diwali stocking started - ask for dal & oil pooled rates.")]:
            c.execute("INSERT INTO posts(group_id,user_id,kind,body,created_at) VALUES(?,?,?,?,?)", (gid, uid_of[uid], kind, body, ts))

        # ---- purchase history, consumption (what forecasting learns from) and stock on hand
        for uid in merchant_ids:
            m = MERCHANTS[uid - n_w - 1]
            wanted = [p for p in pcat if m[3] == "both" or pcat[p] == m[3]]
            staples = rnd.sample(wanted, k=min(len(wanted), 5))
            if m[0] == "Ravi":
                staples = ["Rice", "Sunflower Oil", "Biscuits", "Detergent", "Toor Dal"]
            for p in staples:
                interval = rnd.choice([7, 10, 14])
                q = typical[p] * rnd.uniform(0.8, 1.2)
                if m[0] == "Ravi":
                    interval, q = {"Rice": (7, 50), "Sunflower Oil": (7, 20), "Biscuits": (10, 10),
                                   "Detergent": (14, 5), "Toor Dal": (14, 25)}[p]
                d = today - timedelta(days=rnd.randint(1, interval))
                while (today - d).days <= 90:
                    c.execute("INSERT INTO history(user_id,product,qty,day) VALUES(?,?,?,?)",
                              (uid, p, round(q * rnd.uniform(0.9, 1.1), 1), d.isoformat()))
                    d -= timedelta(days=interval)
                daily = q / interval
                for k in range(90, 0, -1):
                    day = today - timedelta(days=k)
                    wk = 1.25 if day.weekday() >= 5 else 1.0          # weekend lift in shop sales
                    c.execute("INSERT INTO consumption VALUES(?,?,?,?)",
                              (uid, p, day.isoformat(), round(max(0.0, daily * wk * rnd.uniform(0.75, 1.25)), 2)))
                c.execute("INSERT INTO inventory VALUES(?,?,?)", (uid, p, round(daily * rnd.choice([2, 3, 9, 12, 20]), 1)))
        c.execute("UPDATE inventory SET stock=? WHERE user_id=? AND product='Sunflower Oil'", (round(20 / 7 * 3.2, 1), uid_of["Ravi"]))
        c.execute("UPDATE inventory SET stock=? WHERE user_id=? AND product='Rice'", (round(50 / 7 * 12, 1), uid_of["Ravi"]))

        # ---- Paytm for Business POS data (simulated) - 45 days
        for uid in merchant_ids:
            scale = rnd.uniform(0.7, 1.4) * (1.6 if uid == uid_of["Ravi"] else 1.0)
            for k in range(0, 45):
                day = (today - timedelta(days=k)).isoformat()
                cnt = int(rnd.uniform(70, 150) * scale)
                amt = round(cnt * rnd.uniform(330, 470), 0)
                sh = [0.39, 0.21, 0.12, 0.09, 0.08]
                parts = [round(amt * s * rnd.uniform(0.92, 1.08), 0) for s in sh]
                other = max(0.0, amt - sum(parts))
                rc = max(1, int(cnt * 0.01 * rnd.uniform(0.6, 1.6)))
                c.execute("INSERT INTO pos_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (uid, day, cnt, amt, *parts, other, rc, round(rc * rnd.uniform(250, 450), 0)))

        # ---- sales (wholesaler listings) + open demands with bids
        def sale(w: int, product: str, kind: str, factor: float, limit: float, m1=0.95, m2=0.90) -> None:
            row = c.execute("SELECT price FROM catalog WHERE wholesaler_id=? AND product=?", (w, product)).fetchone()
            price = round(row["price"] * factor, 2)
            c.execute("INSERT INTO sales(wholesaler_id,product,kind,tiers,qty_limit,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
                      (w, product, kind, _tier_json(price, m1, m2), limit, in7, ts))
        sale(1, "Rice", "bulk", 1.0, 2000)
        sale(2, "Sugar", "clearance", 0.9, 1500, 0.97, 0.93)
        sale(3, "Sunflower Oil", "seasonal", 1.0, 800, 0.96, 0.92)
        sale(4, "Biscuits", "clearance", 0.88, 400, 0.96, 0.92)
        sale(5, "Rice", "bulk", 1.01, 3000)
        sale(5, "Toor Dal", "seasonal", 1.0, 1200)

        def demand(user: str, product: str, qty: float, budget, note: str, bids: list[tuple[int, float]]) -> None:
            did = c.execute("INSERT INTO demands(user_id,product,qty,budget,note,created_at) VALUES(?,?,?,?,?,?)",
                            (uid_of[user], product, qty, budget, note, ts)).lastrowid
            for w, f in bids:
                row = c.execute("SELECT price FROM catalog WHERE wholesaler_id=? AND product=?", (w, product)).fetchone()
                if row:
                    c.execute("INSERT INTO bids(demand_id,wholesaler_id,price,created_at) VALUES(?,?,?,?)",
                              (did, w, round(row["price"] * f, 2), ts))
        demand("Kumar", "Toor Dal", 300, 36000, "Need before Friday", [(1, 0.97), (2, 0.95)])
        demand("Anand", "Sugar", 200, None, "Weekly stock", [(3, 0.99)])
        demand("Imran", "Rice", 400, None, "", [])

        # ---- Ravi: one delivered order awaiting review (shows the 'rate your purchase' flow)
        items = json.dumps([{"product": "Rice", "qty": 50, "unit_price": 53.5}])
        c.execute("INSERT INTO orders(user_id,wholesaler_id,items,items_total,delivery_charge,delivery_note,total,source,status,"
                  "pay_mode,paid_amount,eta_days,eta_date,origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (uid_of["Ravi"], 1, items, 2675.0, 150.0, "Tempo from Erode Main", 2825.0, "direct", "delivered",
                   "full", 2825.0, 1, today.isoformat(), "Erode", ts, ts))

        # ---- notifications
        for uid, kind, text in [(uid_of["Kumar"], "group", "Meena Kirana requested to join Erode Grocery Buyers."),
                                (uid_of["Ravi"], "order", "Order #1 from Murugan Traders was delivered - rate your purchase."),
                                (uid_of["Ravi"], "sale", "New sale: Sunflower Oil seasonal tiers from Annapoorna Agencies.")]:
            c.execute("INSERT INTO notifications(user_id,kind,text,created_at) VALUES(?,?,?,?)", (uid, kind, text, ts))
        c.commit()


if __name__ == "__main__":
    seed()
    print("Seeded", db.db_path())
