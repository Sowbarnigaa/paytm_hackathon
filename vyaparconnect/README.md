# Paytm VyaparConnect AI - Hackathon build

A two-sided B2B procurement app. **Priority feature: Group Formation** - verified groups where merchants and
wholesalers join to unlock bulk, clearance and seasonal pricing. The other pitch items plug into those groups.

## Run it (2 minutes)

```bash
cd backend
/usr/local/bin/python3.11 -m venv .venv          # any Python 3.10+ works; see "Known issue" below
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8000
# open http://localhost:8000
```

The database is created and seeded automatically on first start. **Reset demo data** with the button in the
top bar (or `POST /api/reset`). No internet, API keys or build step are needed - everything works offline.

> Known issue (this Mac only): `pip` crashed on Python 3.12/3.14 (`platform.mac_ver()` returns empty in the
> sandbox). Python 3.11 works. On a normal machine any recent Python is fine.

## What is built

| Pitch item | Where | What it does |
|---|---|---|
| **Group formation** (priority) | `app/groups.py` | Create public / invite-only groups, join requests, admin approve/reject, invitations, leave, member list, group feed |
| AI group recommendations | `groups.recommend` | Score = 40% category + 30% city + 30% overlap between the merchant's regular items and what the group's wholesalers stock; shows reasons |
| AI-suggested group | `groups.suggest_clusters` | Finds nearby merchants buying the same items, proposes a group, one click creates it and invites them |
| AI membership check | `groups.ai_check` | KYC, trust, city, category, wholesaler cap - auto-approves public groups, pre-screens for admins with reasons |
| Anti-collusion moderation | `groups.moderate`, 40% wholesaler cap | Price-fixing / boycott posts are held for admin review; wholesalers cannot exceed 40% of a group |
| Group Buying AI | `app/deals.py` | Wholesaler posts tiered deal (Rs 55 -> 52 -> 49/kg); members commit; tier unlocks live; savings split by share; closing creates orders |
| AI Procurement Agent | `ai.procurement` | Parses "50 kg rice, 20 L oil, budget 6000" (also Tamil/Hindi words, voice input), ranks suppliers (50% price, 25% delivery, 25% trust), explains each pick, surfaces open group pools |
| AI Reverse Auction | `app/auction.py` | Merchant posts need (open market or one group), wholesalers bid (lower revised bids only), AI-ranked live leaderboard, award creates order |
| Predictive Demand AI | `ai.forecast` | 60-day usage x festival multiplier (Diwali, Pongal, Eid, Ugadi) -> days to stock-out, reorder quantity, alerts |
| AI Smart Negotiator | `ai.negotiate` | Buyer and Seller agents trade up to 5 rounds within the merchant's ceiling; seller floor stays private; accept -> order |
| Merchant loans + EMI autopay | `app/credit.py` | Composite score -> 4 tiers from the pitch (750+/700-749/650-699/below 650), EMI plans, pay-with-loan at checkout, UPI AutoPay opt-in (**simulated**), auto-debit / manual EMI, on-time EMIs raise score |
| Voice ordering | `frontend/app.js` | Browser speech recognition (Tamil, Hindi, Telugu, Marathi, English) feeds the procurement agent. Needs Chrome/Edge |

All AI is deterministic rules (no API keys, never fails on stage). Loans and AutoPay are **simulated**; there is no real
lending, bureau, UPI mandate or KYC integration.

## Demo script (5 minutes)

Use the user dropdown at the top right to switch roles. Click **Reset demo** first.

1. **Ravi** (merchant, Erode) - Home shows an AI-recommended group (100% match), an AI-suggested group, and
   "Sunflower Oil will run out in ~3 days".
2. Ravi clicks **Request to join** on *Erode Grocery Buyers* - the AI membership check is shown.
3. Switch to **Kumar** (group admin) -> Groups -> Open -> **Requests** -> read the AI pre-check -> **Approve**.
4. Switch to **Murugan** (wholesaler) -> the group -> **Deals** -> **Post pooled deal** -> Rice, tiers 55 / 52 (250+) / 49 (500+) -> Publish.
5. Switch between Kumar, Lakshmi, Senthil, Priya, Ravi - each commits 100 kg. Watch the price drop to **Rs 49/kg**, group savings **Rs 3,000**, Rs 600 each.
6. **Ravi** -> AI Buyer -> "50 kg arisi, 20 L oil, budget 6000" -> ranked suppliers with reasons + a nudge to the open group pool.
7. Same screen -> **Smart negotiator** -> watch agents haggle -> Accept.
8. **Auctions**: Ravi posts 100 kg sugar; switch to Murugan and Kaveri to bid; Ravi sees the AI leaderboard and awards.
9. Order with **Pay with loan** + AutoPay -> **Credit & EMI** -> simulate auto-debit.
10. As **Lakshmi**, post "Let's all fix the price of rice at 60" -> held by AI moderation.

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q                 # 25 API tests (rules, edge cases, permissions)
# UI end-to-end (drives the real page in headless Chrome through the demo above):
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --remote-debugging-port=9222 about:blank &
.venv/bin/python -m uvicorn app.main:app --port 8000 &
node tests/e2e_ui.mjs
```

## 6-hour solo execution plan (as executed)

| Time | Work | Done when |
|---|---|---|
| 0:00-0:30 | Schema, seed data (31 users, 12 products, 4 groups, 90 days history) | `python -m app.seed` works |
| 0:30-2:00 | **Group formation**: create / join / approve / invite / feed / moderation | Join -> approve flow works |
| 2:00-2:45 | AI group features: recommendations, suggested group, membership check | Scores differ per user |
| 2:45-3:30 | Deals + pooled buying with tier unlock and savings split | Rs 55 -> Rs 49 demo |
| 3:30-4:15 | Procurement agent, forecast, negotiator, auction | Each returns ranked/explained output |
| 4:15-4:45 | Loans + EMI autopay | Checkout with loan works |
| 4:45-5:30 | UI polish, tests, bug fixes | Tests green |
| 5:30-6:00 | Rehearse the demo twice, record a backup video | Video saved |

## Limits to say out loud in the pitch

- Auth is a demo role switcher, not Paytm SSO. Orders and payments are recorded, not settled.
- Loans, credit bureau and UPI AutoPay are simulated.
- Forecast is a moving average with festival multipliers, not Prophet / XGBoost (a drop-in upgrade in `ai.forecast`).
- Real-time bidding uses 3-second polling instead of WebSockets.
