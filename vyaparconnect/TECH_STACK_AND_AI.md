# Paytm VyaparConnect AI — Technical Architecture & AI Engine Specification

## 1. System Architecture & Tech Stack

Paytm VyaparConnect AI is an enterprise-grade, two-sided B2B procurement and group-buying platform designed for local kirana merchants and regional wholesalers. It incorporates an authentic **Paytm for Business** design system, full offline capabilities, and deterministic algorithmic intelligence.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Paytm for Business Web Frontend                       │
│  (Vanilla ES6+ SPA, No CDN/Node Build Step, Custom Reactive Template Tags)  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ REST API (JSON / X-User-Id Auth)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                           FastAPI Backend (v2)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  • groups.py     - Merchant Group Formation & AI Anti-Collusion Moderation  │
│  • market.py     - Tiered Sales, Group Pools, Demands & Reverse Auctions    │
│  • orders.py     - 5-Stage Order Lifecycle & Wholesaler Delivery Quotation  │
│  • payments.py   - Simulated Paytm Payment Gateway (Full/Parts/Loan)        │
│  • ai.py         - Multilingual Parser, Faratin Negotiator, SES Forecast    │
│  • credit.py     - Composite Scoring, CIBIL Check, EMI & UPI AutoPay        │
│  • merchant.py   - POS Home Dashboard, Inventory & Notification Feeds       │
├─────────────────────────────────────────────────────────────────────────────┤
│                       SQLite 3 (WAL Mode & ACID State)                      │
│     (20 Relational Tables, Atomic Transactions, Full Referential Data)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Engineering Decisions
- **Zero External Dependencies / No Cloud LLM Failure Risk**: All AI algorithms are statistical, mathematical, or rule-based. Zero API keys required; 100% predictable execution on stage during live demos.
- **FastAPI + Asynchronous Architecture**: Sub-millisecond response latency with typed request/response validation.
- **Single Process Monolith**: Serves REST endpoints (`/api/*`) and production static SPA frontend (`/static/*`) from a unified runner.
- **Chrome DevTools Protocol (CDP) End-to-End Suite**: Real-world browser automation testing 10 complete demo flows with 0 console warnings or JavaScript errors.

---

## 2. AI Modules & Mathematical Formulations

### A. Autonomous Faratin Bilateral Price Negotiator (`app/ai.py`)
Implements an autonomous multi-agent bargaining mechanism based on Faratin's time-dependent concession model for automated B2B deal-making.

#### Mathematical Concession Formula
For a negotiation over $T = 6$ rounds, the seller agent's counter-offer at round $t \in [1, T]$ is computed as:

$$P_{ask}(t) = P_{list} - (P_{list} - P_{reserve}) \times \left(\frac{t}{T}\right)^{\frac{1}{\beta}}$$

where:
- $P_{list}$ is the wholesaler's catalog list price.
- $P_{reserve}$ is the seller agent's **private reservation price**, guaranteed strictly $\ge P_{floor}$ (the wholesaler's confidential floor price).
- $\beta$ is the concession strategy exponent derived dynamically from live catalog stock level ($S$) and order quantity ($Q$):

$$\text{Coverage} = \frac{S}{Q}, \quad \text{VolumeRatio} = \frac{Q}{Q_{typical}}$$

$$\beta = \begin{cases}
0.5 & \text{if } \text{Coverage} < 3 \quad (\text{Firm: scarce inventory}) \\
0.75 & \text{if } \text{Coverage} < 8 \quad (\text{Slightly firm: moderate stock}) \\
1.0 & \text{default} \quad (\text{Balanced}) \\
2.0 & \text{if } \text{Coverage} > 20 \text{ and } \text{VolumeRatio} \ge 2 \quad (\text{Flexible: surplus stock \& bulk volume})
\end{cases}$$

The buyer agent concedes linearly up to the merchant's private maximum budget ceiling:

$$P_{bid}(t) = P_{open} + (P_{max} - P_{open}) \times \frac{t - 1}{T - 1}, \quad \text{where } P_{open} = \min(P_{max}, 0.85 \times P_{list})$$

**Convergence & Deal Execution**: If $P_{bid}(t) \ge P_{ask}(t)$, a deal is struck immediately at $P_{agreed} = P_{bid}(t)$, automatically generating an order with unit price $P_{agreed}$.

---

### B. Predictive Demand Forecasting & Stock Replenishment (`app/ai.py`)
Predicts stock-out dates and calculates optimal replenishment quantities using single exponential smoothing combined with day-of-week seasonality and regional festival surge multipliers.

#### Mathematical Formulation
1. **Exponential Smoothing Level**:
   For daily consumption series $Y_1, Y_2, \dots, Y_n$ with $\alpha = 0.3$:
   $$L_t = \alpha Y_t + (1 - \alpha) L_{t-1}$$

2. **Day-of-Week Seasonality Index**:
   $$I_{dow} = \frac{\bar{Y}_{dow}}{\bar{Y}_{overall}}, \quad \forall dow \in \{0, 1, \dots, 6\}$$

3. **Festival Multiplier**:
   $$F_{prod} \in [1.2, 1.8] \quad \text{during active lead-up windows (e.g. Diwali, Pongal, Eid)}$$

4. **Forward Projected Daily Demand**:
   $$D(d) = L_n \times I_{dow(d)} \times F_{prod}(d)$$

5. **Days to Stock-Out**:
   $$\text{DaysLeft} = \min \left\{ k \;\middle|\; \text{Stock} < \sum_{i=1}^k D(d_i) \right\}$$

6. **Suggested Reorder Quantity (14-day target inventory coverage)**:
   $$\text{ReorderQty} = \max\left(0, \sum_{i=1}^{14} D(d_i) - \text{Stock}\right)$$

---

### C. Multilingual Semantic Procurement Agent (`app/ai.py`)
Parses free-text procurement requests in **English, Tamil (Native & Romanised transliteration), and Hindi (Devanagari & Romanised transliteration)** without external NLP APIs.

- **Vocabulary & Transliteration Mapping**:
  - *Rice*: "rice", "basmati", "அரிசி" (ta), "arisi" (ta_tr), "चावल" (hi), "chawal" (hi_tr)
  - *Sunflower Oil*: "cooking oil", "சூரியகாந்தி எண்ணெய்" (ta), "ennai" (ta_tr), "सूरजमुखी तेल" (hi), "tel" (hi_tr)
  - *Sugar*: "sugar", "சர்க்கரை" (ta), "sakkarai" (ta_tr), "चीनी" (hi), "cheeni" (hi_tr)
- **Unit Normalization**: Automatically converts grams, quintals ($100\text{ kg}$), tonnes ($1000\text{ kg}$), litres, cartons, and packets into canonical standard units.
- **Supplier Scoring Formula**:
  $$Score = 100 \times \left(0.50 \cdot S_{price} + 0.30 \cdot S_{rating} + 0.20 \cdot S_{eta}\right) \times \text{ItemCoverage}$$

---

### D. Group Formation & Cluster Recommendation (`app/groups.py`)
Calculates affinity between kirana merchants and buying collectives:

$$Score = 35\% \cdot \text{CityMatch} + 30\% \cdot \text{CategoryFit} + 35\% \cdot \text{ItemOverlap}$$

- **Item Overlap**: Jaccard similarity between the merchant's 60-day purchase history and goods actively purchased by group members.
- **AI Pre-check**: Automatically verifies KYC verification, merchant star rating ($\ge 3.0$), regional proximity, category alignment, and 30-member anti-collusion capacity caps prior to join request submission.

---

### E. AI Anti-Collusion & Content Moderation Engine (`app/groups.py`)
Screens group discussions for illegal anti-competitive behaviors:
- **Detection Patterns**: Price-fixing proposals (*"fix price at 60"*), supplier boycotts (*"boycott Murugan"*), territorial market division, and cartel agreements.
- **Automated Workflow**: Flags message, conceals post from group feed, and routes with infraction details to group admin for moderation review.

---

### F. Composite Credit Scoring & Simulated CIBIL Engine (`app/credit.py`)
Evaluates creditworthiness across 6 dynamic parameters:

$$\text{CompositeScore} = \text{BureauScore} + \Delta_{\text{OnTime}} + \text{ActivityPts} + \text{GroupPts} + \text{ReviewPts} + \text{EMIPts}$$

| Tier | Score Range | Credit Limit | Max Tenure | Interest Rate | Approval |
|---|---|---|---|---|---|
| **Prime** | $750 - 900$ | ₹1,00,000 | 12 months | 12.0% p.a. | Instant |
| **Good** | $700 - 749$ | ₹60,000 | 9 months | 14.0% p.a. | Instant |
| **Fair** | $650 - 699$ | ₹30,000 | 6 months | 17.0% p.a. | Quick review |
| **Starter** | $< 650$ | ₹10,000 | 3 months | 20.0% p.a. | Group-backed |

Includes interactive simulated CIBIL bureau pull with mobile OTP authentication and simulated UPI AutoPay mandate generation.

---

## 3. Order Lifecycle State Machine (`app/orders.py`)

```
  [Merchant places order (Goods price only)]
                      │
                      ▼
               quote_pending
                      │
     [Wholesaler quotes delivery charge & ETA]
                      │
                      ▼
                   quoted
                      │
     [Merchant pays: Full / Parts / Paytm Loan]
                      │
                      ▼
                  confirmed
                      │
         [Wholesaler ships dispatch]
                      │
                      ▼
                   shipped
                      │
   [Merchant confirms receipt & restocks inventory]
                      │
                      ▼
                  delivered
                      │
        [Two-way 1-5 Star Review Rating]
```

---

## 4. Test Suite & Quality Verification

- **Backend API Tests**: 46 passed in ~5 seconds (`pytest`).
- **Frontend Headless Chrome e2e**: 10 end-to-end interactive demo flows verified via CDP with 0 JS console errors.
