"""Deterministic demo seed: 25 merchants, 6 wholesalers, 3 cities, 12 products, 4 groups, 90 days of history."""
import random
from datetime import date, timedelta

from . import db

PRODUCTS = [
    # name, unit, base price/unit, category, typical order qty
    ("Rice", "kg", 55, "grocery", 50),
    ("Sunflower Oil", "L", 130, "grocery", 20),
    ("Toor Dal", "kg", 120, "grocery", 25),
    ("Sugar", "kg", 42, "grocery", 40),
    ("Wheat Flour", "kg", 38, "grocery", 40),
    ("Tea Powder", "kg", 380, "grocery", 5),
    ("Biscuits", "carton", 480, "fmcg", 10),
    ("Detergent", "box", 620, "fmcg", 5),
    ("Soap", "carton", 540, "fmcg", 6),
    ("Shampoo Sachets", "carton", 700, "fmcg", 4),
    ("Noodles", "carton", 560, "fmcg", 8),
    ("Salt", "kg", 20, "grocery", 30),
]

CITIES = ["Erode", "Coimbatore", "Chennai"]

# id order matters (ids assigned sequentially): wholesalers 1-6, merchants 7-31
WHOLESALERS = [
    ("Murugan Traders", "Murugan Traders", "Erode", "both", 88, 0.97),
    ("Kaveri Wholesale", "Kaveri Wholesale Mart", "Erode", "grocery", 82, 0.93),
    ("Annapoorna Agencies", "Annapoorna Agencies", "Coimbatore", "both", 91, 0.98),
    ("Sri Lakshmi Distributors", "Sri Lakshmi Dist.", "Coimbatore", "fmcg", 74, 0.9),
    ("Chennai Bulk Mart", "Chennai Bulk Mart", "Chennai", "both", 85, 0.95),
    ("Marina FMCG Hub", "Marina FMCG Hub", "Chennai", "fmcg", 79, 0.92),
]

MERCHANTS = [
    # Erode (11)
    ("Ravi", "Ravi's Grocery", "Erode", "grocery"),
    ("Kumar", "Kumar Stores", "Erode", "grocery"),
    ("Lakshmi", "Lakshmi Provision", "Erode", "grocery"),
    ("Senthil", "Senthil Mart", "Erode", "grocery"),
    ("Priya", "Priya General Store", "Erode", "grocery"),
    ("Arun", "Arun Super", "Erode", "grocery"),
    ("Meena", "Meena Kirana", "Erode", "grocery"),
    ("Dinesh", "Dinesh Fancy & FMCG", "Erode", "fmcg"),
    ("Saraswathi", "Saraswathi Traders", "Erode", "fmcg"),
    ("Bala", "Bala Cosmetics", "Erode", "fmcg"),
    ("Gopal", "Gopal Tea & Snacks", "Erode", "both"),
    # Coimbatore (8)
    ("Anand", "Anand Provision", "Coimbatore", "grocery"),
    ("Selvi", "Selvi Stores", "Coimbatore", "grocery"),
    ("Vijay", "Vijay Mart", "Coimbatore", "grocery"),
    ("Nirmala", "Nirmala Kirana", "Coimbatore", "grocery"),
    ("Suresh", "Suresh FMCG", "Coimbatore", "fmcg"),
    ("Revathi", "Revathi Fancy", "Coimbatore", "fmcg"),
    ("Karthik", "Karthik Super", "Coimbatore", "both"),
    ("Deepa", "Deepa Daily Needs", "Coimbatore", "both"),
    # Chennai (6)
    ("Imran", "Imran General", "Chennai", "grocery"),
    ("Fathima", "Fathima Stores", "Chennai", "grocery"),
    ("Joseph", "Joseph Mart", "Chennai", "grocery"),
    ("Hari", "Hari FMCG", "Chennai", "fmcg"),
    ("Kavitha", "Kavitha Provision", "Chennai", "both"),
    ("Mohan", "Mohan Super", "Chennai", "both"),
]

# price factor vs base per wholesaler (index aligned with WHOLESALERS), delivery days
WHOLESALER_PRICE = [0.97, 0.95, 0.96, 1.0, 0.98, 1.02]
WHOLESALER_DELIVERY = [1, 2, 1, 3, 2, 1]


def seed() -> None:
    db.create_schema()
    rnd = random.Random(42)
    ts = db.now_iso()
    with db.conn() as c:
        c.executemany("INSERT INTO products VALUES(?,?,?,?,?)", PRODUCTS)

        for name, shop, city, cat, trust, ontime in WHOLESALERS:
            c.execute(
                "INSERT INTO users(name,shop,role,city,category,trust,kyc_verified,credit_score,on_time_rate)"
                " VALUES(?,?,?,?,?,?,1,750,?)",
                (name, shop, "wholesaler", city, cat, trust, ontime),
            )
        for name, shop, city, cat in MERCHANTS:
            score = rnd.choice([590, 640, 660, 690, 710, 735, 760, 790])
            ontime = round(min(0.99, max(0.6, 0.6 + (score - 580) / 600 + rnd.uniform(-0.05, 0.05))), 2)
            c.execute(
                "INSERT INTO users(name,shop,role,city,category,trust,kyc_verified,credit_score,on_time_rate)"
                " VALUES(?,?,?,?,?,?,1,?,?)",
                (name, shop, "merchant", city, cat, rnd.randint(55, 90), score, ontime),
            )
        # Ravi is the demo hero: predictable profile
        c.execute("UPDATE users SET credit_score=712, on_time_rate=0.92, trust=78 WHERE name='Ravi'")

        # Catalog: wholesalers carry products matching their category, in their city
        for wid in range(1, 7):
            w = WHOLESALERS[wid - 1]
            for pname, _unit, base, pcat, _q in PRODUCTS:
                if w[3] != "both" and w[3] != pcat:
                    continue
                price = round(base * WHOLESALER_PRICE[wid - 1] * rnd.uniform(0.99, 1.02), 2)
                c.execute(
                    "INSERT INTO catalog VALUES(?,?,?,?,?)",
                    (wid, pname, price, WHOLESALER_DELIVERY[wid - 1], rnd.choice([500, 1000, 2500, 5000])),
                )

        # Groups. Ravi (id 7) is deliberately NOT in any group, so he can discover/join one.
        groups = [
            ("Erode Grocery Buyers", "Pool rice, oil and dal orders across Erode kirana stores.", "grocery", "Erode", "invite", 8),   # admin Kumar
            ("Erode FMCG Circle", "Biscuits, soaps and detergents - weekly bulk deals.", "fmcg", "Erode", "public", 14),               # admin Dinesh
            ("Coimbatore Kirana Collective", "Coimbatore grocery merchants buying together.", "grocery", "Coimbatore", "public", 18),   # admin Anand
            ("Chennai Daily Needs", "Chennai grocery + FMCG pooled procurement.", "both", "Chennai", "invite", 26),                    # admin Imran
        ]
        for name, desc, cat, city, typ, admin in groups:
            gid = c.execute(
                "INSERT INTO groups(name,description,category,city,type,admin_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (name, desc, cat, city, typ, admin, ts),
            ).lastrowid
            c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, admin, "active", "admin", ts))

        def add_member(gid: int, uid: int, note: str = "member") -> None:
            c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (gid, uid, "active", note, ts))

        # Erode Grocery Buyers (gid 1): Kumar(admin 8) + Lakshmi, Senthil, Priya, Arun + wholesaler Murugan, Kaveri
        for uid in (9, 10, 11, 12):
            add_member(1, uid)
        for wid in (1, 2):
            add_member(1, wid, "wholesaler")
        # Erode FMCG Circle (gid 2): Dinesh(admin 14) + Saraswathi, Bala, Gopal + Murugan
        for uid in (15, 16, 17):
            add_member(2, uid)
        add_member(2, 1, "wholesaler")
        # Coimbatore (gid 3): Anand(18) admin + Selvi, Vijay, Nirmala + Annapoorna
        for uid in (19, 20, 21):
            add_member(3, uid)
        add_member(3, 3, "wholesaler")
        # Chennai (gid 4): Imran(26) admin + Fathima, Joseph, Kavitha + Chennai Bulk
        for uid in (27, 28, 30):
            add_member(4, uid)
        add_member(4, 5, "wholesaler")

        # Pending join request so the admin queue is non-empty for the demo
        c.execute("INSERT INTO memberships VALUES(?,?,?,?,?)", (1, 13, "pending", "Meena wants to join - sells rice & dal.", ts))

        # Posts
        seed_posts = [
            (1, 1, "flash_sale", "Flash sale: Sugar Rs 40/kg for orders above 200 kg, valid till Sunday."),
            (1, 8, "announcement", "Welcome! Pool orders close every Friday 6 PM."),
            (2, 1, "clearance", "Clearance: Biscuits cartons (best before 3 months) - 15% off."),
            (3, 3, "announcement", "Diwali stocking started - ask for dal & oil pooled rates."),
        ]
        for gid, uid, kind, body in seed_posts:
            c.execute(
                "INSERT INTO posts(group_id,user_id,kind,body,created_at) VALUES(?,?,?,?,?)", (gid, uid, kind, body, ts)
            )

        # 90 days purchase history per merchant + inventory
        today = date.today()
        pcat = {p[0]: p[3] for p in PRODUCTS}
        typical = {p[0]: p[4] for p in PRODUCTS}
        for uid in range(7, 7 + len(MERCHANTS)):
            m = MERCHANTS[uid - 7]
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
                # stock: roughly (daily use * random days left)
                daily = q / interval
                stock = round(daily * rnd.choice([2, 3, 9, 12, 20]), 1)
                c.execute("INSERT INTO inventory VALUES(?,?,?)", (uid, p, stock))
        # Ravi: oil is about to stock out (hero alert)
        c.execute("UPDATE inventory SET stock=? WHERE user_id=7 AND product='Sunflower Oil'", (20 / 7 * 3.5,))
        c.execute("UPDATE inventory SET stock=? WHERE user_id=7 AND product='Rice'", (50 / 7 * 12,))
        c.commit()


if __name__ == "__main__":
    seed()
    print("Seeded", db.db_path())
