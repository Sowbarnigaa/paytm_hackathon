# Paytm VyaparConnect AI (v2) — Hackathon Build

A two-sided B2B procurement and group-buying platform for Indian kirana merchants and regional wholesalers, embedded directly into the **Paytm for Business** ecosystem.

**Priority Core Feature: Group Formation & Pooled Buying** — Verified merchant groups in the same city pool bulk, seasonal, and clearance purchase orders to unlock wholesale tiered pricing, eliminate middleman markups, and prevent supplier price collusion.

---

## Quick Start (Run in 2 minutes)

```bash
cd vyaparconnect/backend

# 1. Setup virtual environment (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Run the unified FastAPI server & single-page UI
PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --port 8000
```

Open **`http://localhost:8000`** in your browser.

- The database (`vyapar.db`) is automatically initialized and seeded with 34 realistic users (merchants & wholesalers across Erode, Coimbatore, Chennai, Salem), 12 catalog products, 5 buying groups, and 90 days of daily POS history.
- **Reset demo state anytime**: Click the **Reset** button in the top bar (or `POST /api/reset`).
- **100% Offline Runnable**: Zero external cloud LLM dependencies, zero API keys required, deterministic and instant.
## Sign-in (merchants and wholesalers)

Open `http://localhost:8000` and you are sent to `/login`:

- **Create account**: pick *Merchant* or *Wholesaler*, enter email + password (min 8 chars). You are signed in immediately (no email verification - this is a demo).
- **Sign in**: email + password. Sessions are bearer tokens valid for 7 days; **Sign out** revokes the token.

Passwords are hashed with scrypt, tokens are stored only as hashes, and 5 failed logins lock an email for 5 minutes.

| Env var | Purpose |
|---|---|
| `VC_DEMO_AUTH=1` | Demo only: re-enables the old `X-User-Id` role switcher and `POST /api/reset`; the login page shows demo credentials |

Seeded demo accounts use `<firstname>@example.com` with password `Demo@1234` (e.g. `ravi@example.com` merchant, `murugan@example.com` wholesaler). An existing `vyapar.db` from before login was added is re-seeded automatically on startup. In the demo script below, "switch to X" means sign out and sign in as that user (or run with `VC_DEMO_AUTH=1` to use the dropdown).



---

## What Is Built & Delivered

| Capability / Pitch Item | Module | Description & Business Value |
|---|---|---|
| **Merchant Group Formation** | `app/groups.py` | Create public / invite-only merchant groups, AI membership pre-check, admin approval workflow, directory, group feed. |
| **AI Group Recommendations** | `groups.recommend` | Rule-based cluster matching formula: $35\% \text{ City} + 30\% \text{ Category} + 35\% \text{ Item Overlap}$. Displays transparent reasons. |
| **AI Anti-Collusion Shield** | `groups.moderate` | Screens group feed for price-fixing / boycott / cartel language. Holds posts for admin review; enforces 30-merchant size caps. |
| **Group Buying & Tier Pools** | `app/market.py` | Wholesalers list tiered sales (₹55 $\rightarrow$ ₹52 $\rightarrow$ ₹49/kg); merchants pool volume; unlocks live lower tiers; splits savings by share. |
| **AI Multilingual Procurement** | `app/ai.py` | Understands free-text & voice inputs in English, Tamil (*அரிசி, arisi, ennai*), and Hindi (*chawal, tel, cheeni*). Ranks suppliers by price, rating, and ETA. |
| **Autonomous Faratin Negotiator** | `app/ai.py` | 6-round bilateral haggling between buyer and seller AI agents using time-dependent concession curves. Protects wholesaler's private floor price. |
| **Predictive Demand AI** | `app/ai.py` | Exponential smoothing ($\alpha=0.3$) on daily POS usage + day-of-week seasonality + festival multipliers (Diwali, Pongal, Eid) to predict stock-outs. |
| **Paytm Business Loans & EMI** | `app/credit.py` | 6-factor composite scoring engine $\rightarrow$ 4 risk tiers (Prime 750+, Good, Fair, Starter). Simulated CIBIL bureau pull with OTP consent. |
| **UPI AutoPay Mandates** | `app/credit.py` | One-click EMI mandate opt-in at checkout. Simulated auto-debit processing that dynamically raises credit scores upon on-time repayments. |
| **Complete Order Lifecycle** | `app/orders.py` | 5-stage state machine: `quote_pending` $\rightarrow$ `quoted` $\rightarrow$ `confirmed` $\rightarrow$ `shipped` $\rightarrow$ `delivered`. Direct, pooled, and auction orders. |
| **Simulated Payment Gateway** | `app/payments.py` | Paytm Payment Gateway modal simulating Paytm UPI, Debit/Credit Cards, Netbanking, and Wallet settlements. |
| **Two-Way Verified Reviews** | `app/orders.py` | Verified 1–5 star reviews and comments after delivery; dynamically recalculates wholesaler and merchant star averages. |
| **Paytm for Business Shell** | `frontend/` | Vanilla ES6+ SPA without build steps or CDNs. Responsive sidebar navigation, notification drawer, merchant directory, dark/light accents. |

---

## 5-Minute Live Demo Script

Switch demo personas using the user dropdown at the top right of the navigation bar.

1. **Ravi** (Merchant, Erode) — Home screen displays AI-recommended group *Erode Grocery Buyers* (86% match), AI-suggested group alliance, and predictive alert: *"Sunflower Oil will run out in ~3 days"*.
2. Ravi clicks **Request to join** on *Erode Grocery Buyers* — instant AI pre-check confirms KYC, rating, and local city fit.
3. Switch to **Kumar** (Group Admin) $\rightarrow$ Groups $\rightarrow$ *Erode Grocery Buyers* $\rightarrow$ **Requests** $\rightarrow$ review AI pre-check $\rightarrow$ **Approve**.
4. Switch to **Murugan** (Wholesaler) $\rightarrow$ Auctions $\rightarrow$ List tiered sale for Rice (₹55 / ₹52 / ₹49/kg). Kumar pools it in the group.
5. Switch between Kumar, Lakshmi, Senthil, Priya, and Ravi — each commits 100 kg. Watch live volume reach **500 kg**, unlocking the best tier **₹49/kg** and saving **₹3,000** for the group (₹600 each).
6. **Ravi** $\rightarrow$ AI Buyer $\rightarrow$ Enter `"50 kg arisi, 20 L oil, budget 6000"` $\rightarrow$ view AI-ranked suppliers, cost breakdown, and group pool recommendations.
7. Same screen $\rightarrow$ **Smart negotiator** $\rightarrow$ select Murugan Traders and target price $\rightarrow$ watch autonomous buyer and seller agents haggle over 6 rounds $\rightarrow$ **Accept deal**.
8. **Auctions**: Ravi posts a demand for 100 kg Sugar; Murugan (₹41) and Kaveri (₹40) submit private wholesale bids; Ravi reviews the AI-scored leaderboard and awards Kaveri.
9. Checkout with **Pay with loan** + UPI AutoPay $\rightarrow$ **Credit & EMI** $\rightarrow$ click **Simulate auto-debit** $\rightarrow$ watch EMI advance to *1/3 paid*.
10. Switch to **Lakshmi** $\rightarrow$ Post *"Let's all fix the price of rice at 60"* in group feed $\rightarrow$ post is instantly **Held by AI moderation** for price-fixing prevention.

---

## Automated Test Verification

### 1. Backend Integration & Unit Test Suite (46 Tests)
```bash
cd vyaparconnect/backend
PYTHONPATH=. .venv/bin/pytest tests/test_api.py -v
```
*Result: 68 passed (46 API tests in `test_api.py`, 22 sign-in tests in `test_auth.py`).*

### 2. End-to-End Headless Chrome UI Automation (10 Demo Steps)
```bash
# Terminal 1: Launch headless Chrome with remote debugging
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --remote-debugging-port=9222 --disable-gpu about:blank

# Terminal 2: Run FastAPI server
cd vyaparconnect/backend
PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --port 8000

# Terminal 3: Run the CDP automation script
node vyaparconnect/backend/tests/e2e_ui.mjs
```
*Result: All 10 demo steps passed, 0 JavaScript errors.*

---

## Technical Documentation
For deep-dive mathematical formulas, algorithmic concession models, single exponential smoothing formulas, and database schema mappings, see [`TECH_STACK_AND_AI.md`](./TECH_STACK_AND_AI.md).
