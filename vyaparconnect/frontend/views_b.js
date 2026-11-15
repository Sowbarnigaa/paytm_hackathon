/* Paytm VyaparConnect AI - Views (Part B): AI Buyer, Auctions & Demands, Orders, Credit & EMI, Inventory, Notifications */
"use strict";

// ------------------------------------------------------------------ AUCTIONS & DEMANDS (REVERSE AUCTIONS)
function demandRowHtml(removable) {
  const products = (S.products && S.products.length) ? S.products : [{ name: "Rice", unit: "kg" }, { name: "Sugar", unit: "kg" }];
  return html`
    <div class="dem-row row mt" style="align-items:flex-end;gap:10px;flex-wrap:wrap">
      <div class="field">
        <label>Product</label>
        <select name="product" required>
          ${products.map(p => html`<option value="${p.name}">${p.name}${p.unit ? ` (${p.unit})` : ""}</option>`)}
        </select>
      </div>
      <div class="field">
        <label>Quantity</label>
        <input name="qty" type="number" min="1" step="any" value="100" required>
      </div>
      <div class="field">
        <label>Target Budget (₹ optional)</label>
        <input name="budget" type="number" min="0" placeholder="e.g. 4500">
      </div>
      ${removable ? html`<button type="button" class="btn bad sm" data-a="removeDemandRow">Remove</button>` : ""}
    </div>
  `;
}

async function vAuctions() {
  const me = S.me;
  const isMerchantUser = isMerchant();
  const [demands, sales] = await Promise.all([
    api("/demands"),
    api("/sales")
  ]);

  return html`
    <div class="spread mb">
      <div>
        <h2>Auctions & Direct Sales</h2>
        <div class="sm muted">Post purchase requirements for supplier reverse bidding, or browse wholesale bulk & clearance sales.</div>
      </div>
      ${isWholesaler() ? html`<button class="btn cyan" data-a="openListSaleModal">+ List a Sale</button>` : ""}
    </div>

    ${isMerchantUser ? html`
      <div class="card hl mb">
        <h3>Post a Demand / Reverse Auction</h3>
        <form data-f="auction" class="mt">
          <div id="demRows">${demandRowHtml(false)}</div>
          <div class="row mt">
            <button type="button" class="btn sec sm" data-a="addDemandRow">+ Add another product</button>
          </div>
          <div class="field mt" style="max-width:520px">
            <label for="aucNote">Note (applies to all products)</label>
            <input id="aucNote" name="note" placeholder="Quality grade, preferred delivery...">
          </div>
          <button class="btn cyan mt">Post to Wholesalers</button>
        </form>
      </div>
    ` : ""}

    <h3>${isMerchantUser ? "My Active Demands & Live Bids" : "Merchant Demands (Bid as Wholesaler)"}</h3>
    ${demands.length === 0 ? html`
      <div class="card mb"><p class="muted">No active demands listed.</p></div>
    ` : html`
      <div class="grid g2 mb">
        ${demands.map(d => demandCard(d))}
      </div>
    `}

    <h3 class="mt">Wholesale Direct & Clearance Sales</h3>
    ${sales.length === 0 ? html`
      <div class="card"><p class="muted">No direct sales listed currently.</p></div>
    ` : html`
      <div class="grid g2">
        ${sales.map(s => saleCard(s))}
      </div>
    `}
  `;
}

function demandCard(d) {
  const me = S.me;
  const isOwner = d.is_owner || (me && d.user_id === me.id);
  const isWholesale = isWholesaler();
  const bids = d.bids || [];
  const isOpen = d.status === "open";
  const isCollective = d.is_collective || (d.participants && d.participants.length > 0);

  return html`
    <div class="card ${isOwner || isCollective ? "hl" : ""}">
      <div class="spread">
        <div>
          <h3>
            ${d.product} - ${num(d.qty)} ${d.unit}
            ${isCollective ? html`<span class="badge ai">👥 Collective Group Auction (${d.group_name || "Group"})</span>` : ""}
          </h3>
          <div class="sm muted">${d.buyer_shop || d.buyer || "Merchant"} (${d.buyer_city || ""}) · ${ago(d.created_at)}</div>
        </div>
        <span class="badge ${isOpen ? "ok" : ""}">${isOpen ? (d.bid_count > 0 ? `${d.bid_count} bid(s)` : "Waiting for bids") : "Closed"}</span>
      </div>

      <div class="mt sm">
        ${d.budget ? html`<span>Target budget: <b>${inr(d.budget)}</b> (max ${inr(d.budget / d.qty)}/${d.unit})</span>` : ""}
        ${d.note ? html`<div class="muted mt">“${d.note}”</div>` : ""}
      </div>

      ${isCollective && d.participants && d.participants.length > 0 ? html`
        <div class="mt sm ok">
          <b>👥 Participating Merchants (${d.participants.length}):</b>
          <div class="row mt" style="gap:4px">
            ${d.participants.map(p => html`
              <span class="participant-tag"><b>${p.shop}</b>: ${num(p.qty)} ${d.unit}</span>
            `)}
          </div>
        </div>
      ` : ""}

      ${bids.length > 0 ? html`
        <div class="mt">
          <h4>Ranked Wholesaler Bids (AI Evaluated)</h4>
          <table>
            <thead>
              <tr><th>Rank</th><th>Wholesaler</th><th>Price</th><th>ETA</th><th>Score</th><th>Action</th></tr>
            </thead>
            <tbody>
              ${bids.map(b => html`
                <tr>
                  <td><b>${b.rank === 1 ? "🏆 1" : `#${b.rank}`}</b></td>
                  <td>${b.shop}</td>
                  <td><b>${inr(b.price)}/${d.unit}</b><br><small class="muted">Total: ${inr(b.total)}</small></td>
                  <td>${b.eta_days}d</td>
                  <td><span class="badge ai">AI score ${b.score}</span></td>
                  <td>
                    ${d.can_award ? html`
                      <button class="btn sm ok" data-a="awardDemand" data-did="${d.id}" data-bid="${b.id}">
                        ${isCollective ? "Award & Split Orders" : "Award Bid"}
                      </button>
                    ` : (isOpen ? html`<span class="muted sm">Live</span>` : html`<span class="badge ok">Awarded</span>`)}
                  </td>
                </tr>
              `)}
            </tbody>
          </table>
        </div>
      ` : ""}

      ${isWholesale && isOpen ? html`
        <div class="mt card tint2">
          <h4>Place Private Wholesale Bid</h4>
          <form data-f="bid" data-did="${d.id}" class="form mt">
            <div class="field">
              <label for="bp${d.id}">Price per ${d.unit} (₹)</label>
              <input id="bp${d.id}" name="price" type="number" step="0.5" min="1" value="${d.my_bid ? d.my_bid.price : ""}" required>
            </div>
            <div class="field">
              <label for="bd${d.id}">Delivery days</label>
              <input id="bd${d.id}" name="delivery_days" type="number" min="1" max="14" value="${d.my_bid ? d.my_bid.eta_days : 2}" required>
            </div>
            <button class="btn sm cyan">${d.my_bid ? "Revise Bid" : "Submit Bid"}</button>
          </form>
          ${d.my_bid ? html`<div class="sm ok mt">Your current bid: ${inr(d.my_bid.price)}/${d.unit} (${d.my_bid.eta_days}d delivery)</div>` : ""}
        </div>
      ` : ""}
    </div>
  `;
}

function saleCard(s) {
  const me = S.me;
  const isMerchantUser = isMerchant();
  const tiers = s.tiers || [];
  const unit = s.unit || "kg";

  return html`
    <div class="card">
      <div class="spread">
        <div>
          <h3>${s.product} <span class="badge ${s.kind === "clearance" ? "bad" : s.kind === "seasonal" ? "warn" : "ok"}">${KIND[s.kind] || s.kind}</span></h3>
          <div class="sm muted">${s.wholesaler ? s.wholesaler.shop : ""} · Ships from ${s.warehouse_city || s.warehouse || "Warehouse"}</div>
        </div>
        <span class="badge">${s.is_open ? "Ends in " + daysTo(s.expires_at) + "d" : "Closed"}</span>
      </div>

      <div class="tier mt">
        ${tiers.map(t => html`
          <span class="chip">
            ${t.min_qty ? num(t.min_qty) + "+ " + unit : "Any qty"}: ${inr(t.price)}/${unit}
          </span>
        `)}
      </div>

      <div class="sm muted mt">
        ${s.delivery_note || "Price is for product only. Delivery quoted after order."}
      </div>

      ${isMerchantUser && s.is_open ? html`
        <div class="row mt">
          <button class="btn sec sm" data-a="openBuySaleModal" data-id="${s.id}" data-p="${s.product}">Buy directly</button>
          <button class="btn cyan sm" data-a="openStartPoolModal" data-id="${s.id}" data-p="${s.product}">Start group pool</button>
        </div>
      ` : ""}
    </div>
  `;
}

// ------------------------------------------------------------------ AI BUYER
async function vAI() {
  const subs = [
    ["proc", "Procurement agent"],
    ["neg", "Smart negotiator"],
    ["fc", "Demand forecast"]
  ];
  if (!subs.some(s => s[0] === S.aiTab)) S.aiTab = "proc";

  const head = html`
    <div class="spread mb">
      <div>
        <h2>AI Buyer & Automated Procurement</h2>
        <div class="sm muted">Multilingual natural language procurement, autonomous Faratin price negotiation, and exponential smoothing demand forecast.</div>
      </div>
    </div>
    <div class="tabs mb">
      ${subs.map(([k, l]) => html`
        <button class="tab ${S.aiTab === k ? "on" : ""}" data-a="aiTab" data-v="${k}">${l}</button>
      `)}
    </div>
  `;

  if (S.aiTab === "proc") return html`${head}${aiProc()}`;
  if (S.aiTab === "neg") return html`${head}${await aiNeg()}`;
  return html`${head}${await aiForecast()}`;
}

const SpeechRec = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

function aiProc() {
  const r = S.proc;

  return html`
    <div class="card hl mb">
      <form data-f="procure">
        <label for="ptext"><b>Tell the agent what you need</b> (Supports English, Tamil & Hindi terms: e.g. <i>50 kg arisi, 20 L oil, 2 quintal chawal, budget 6000</i>)</label>
        <div class="composer mt" id="composer">
          <textarea id="ptext" name="text" required rows="3" placeholder="e.g. 50 kg rice, 20 L oil, budget 6000">${S.procText || "50 kg rice, 20 L oil, budget 6000"}</textarea>
          ${SpeechRec ? html`
            <div class="composer-bar">
              <div class="rec-idle">
                <select id="voiceLang" class="lang" aria-label="Voice language" title="Voice language">
                  ${[["en-IN", "English"], ["ta-IN", "தமிழ்"], ["hi-IN", "हिन्दी"]].map(([v, l]) => html`<option value="${v}" ${(S.voiceLang || "en-IN") === v ? "selected" : ""}>${l}</option>`)}
                </select>
              </div>
              <div class="rec-live" aria-live="polite">
                <span class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>
                <span class="rec-label sm">Listening…</span>
              </div>
              <div class="composer-actions">
                <button type="button" class="mic mic-idle rec-idle" id="micBtn" data-a="speechToText" aria-label="Dictate with voice" title="Dictate">
                  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7"/></svg>
                </button>
                <button type="button" class="mic mic-cancel rec-live" data-a="micCancel" aria-label="Cancel dictation" title="Cancel">
                  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
                </button>
                <button type="button" class="mic mic-done rec-live" data-a="micDone" aria-label="Use dictated text" title="Done">
                  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
                </button>
              </div>
            </div>
          ` : ""}
        </div>
        <div class="row spread mt">
          <div class="field">
            <label for="sortMode">Sort suppliers by</label>
            <select id="sortMode" name="sort">
              <option value="best">Best overall (Price 50%, Rating 30%, ETA 20%)</option>
              <option value="price">Lowest goods price</option>
              <option value="rating">Highest rated supplier</option>
              <option value="eta">Fastest arrival time</option>
            </select>
          </div>
          <button class="btn cyan lg">🔍 Find Best Suppliers</button>
        </div>
      </form>
    </div>

    ${r ? html`
      <div class="card mb">
        <h3>🤖 Top pick: ${r.suppliers && r.suppliers.length > 0 ? r.suppliers[0].wholesaler.shop : "Found"} - ${r.suppliers && r.suppliers.length > 0 ? inr(r.suppliers[0].total) : ""}</h3>
        <p class="sm">${r.understood || r.summary}</p>
        ${r.budget_note ? html`<div class="sm ok mt"><b>Budget analysis:</b> ${r.budget_note}</div>` : ""}

        ${r.group_pools && r.group_pools.length > 0 ? html`
          <div class="card tint mt">
            <h4>👥 Group pools you can join</h4>
            <p class="sm muted">Your group has an active pool for these items at lower tiered prices:</p>
            ${r.group_pools.map(gp => html`
              <div class="row spread mt">
                <span><b>${gp.product}</b> in <b>${gp.group}</b>: current ${inr(gp.current_price)}/${gp.unit} (best tier ${inr(gp.best_tier_price)}/${gp.unit})</span>
                <button class="btn sm cyan" data-a="openGroup" data-id="${gp.group_id}">Join Pool</button>
              </div>
            `)}
          </div>
        ` : ""}

        <h4 class="mt">Ranked Supplier Comparison (${r.suppliers ? r.suppliers.length : 0} options)</h4>
        <div class="grid g2 mt">
          ${(r.suppliers || []).map(s => html`
            <div class="card ${s.rank === 1 ? "hl" : ""}">
              <div class="spread">
                <div>
                  <h4>#${s.rank} ${s.wholesaler.shop}</h4>
                  <div class="sm muted">${s.wholesaler.city} · ⭐ ${(s.wholesaler.rating_avg || 5).toFixed(1)} (${s.wholesaler.rating_count || 0} reviews)</div>
                </div>
                <div class="right">
                  <div class="b ok" style="font-size:18px">${inr(s.total)}</div>
                  <span class="badge ai">AI Score ${s.score}</span>
                </div>
              </div>
              <div class="sm mt">
                <b>Arrival:</b> ~${s.eta_days} day(s) from ${s.ships_from.join(", ")}
              </div>
              <div class="sm muted mt">${s.reason}</div>
              <div class="mt row spread">
                <span class="sm muted">${s.delivery_note || "Goods price only"}</span>
                <button class="btn sm cyan" data-a="checkout" data-w="${s.wholesaler.id}" data-lines='${JSON.stringify(s.lines)}'>Order / Checkout</button>
              </div>
            </div>
          `)}
        </div>
      </div>
    ` : ""}
  `;
}

// Live negotiator form: options come from the wholesaler catalog (live DB prices & stock), not hard-coded lists.
function negSuggestedMax(price) { return Math.round(price * 0.93 * 2) / 2; }

function negProductOptions(rows, selected) {
  return html`${rows.map(r => html`<option value="${r.product}" ${r.product === selected ? "selected" : ""}>${r.product} - ${inr(r.price)}/${r.unit} (${num(r.stock_qty)} ${r.unit} in stock)</option>`)}`;
}

async function aiNeg() {
  const cat = await api("/catalog");
  S.catalog = cat;
  const wholesalers = [...new Map(cat.map(c => [c.wholesaler_id, c])).values()];
  const neg = S.neg;

  const nf = S.negForm || {};
  const wid = wholesalers.some(w => w.wholesaler_id === nf.wholesaler_id) ? nf.wholesaler_id : (wholesalers[0] ? wholesalers[0].wholesaler_id : 0);
  const rows = cat.filter(c => c.wholesaler_id === wid);
  const row = rows.find(r => r.product === nf.product) || rows[0];
  const qty = nf.qty || Math.min(50, row ? row.stock_qty : 50);
  const maxP = nf.max_price || (row ? negSuggestedMax(row.price) : 0);

  const total = neg && neg.transcript ? neg.transcript.length : 0;
  const shown = neg ? Math.min(S.negShown == null ? total : S.negShown, total) : 0;
  const finished = neg && shown >= total;

  return html`
    <div class="card hl mb">
      <h3>Autonomous Faratin Price Negotiator</h3>
      <p class="sm muted">Buyer and Seller AI agents negotiate price within 6 rounds using time-dependent concession curves, starting from the wholesaler's live catalog price and stock. The wholesaler's floor price stays completely private.</p>
      <form data-f="negotiate" class="form mt">
        <div class="field">
          <label for="negW">Wholesaler</label>
          <select id="negW" name="wholesaler_id" required>
            ${wholesalers.map(w => html`<option value="${w.wholesaler_id}" ${w.wholesaler_id === wid ? "selected" : ""}>${w.shop} (${w.city})</option>`)}
          </select>
        </div>
        <div class="field">
          <label for="negProd">Product (live catalog)</label>
          <select id="negProd" name="product" required>${negProductOptions(rows, row && row.product)}</select>
        </div>
        <div class="field">
          <label for="negQty">Quantity</label>
          <input id="negQty" name="qty" type="number" min="1" step="any" value="${qty}" required>
        </div>
        <div class="field">
          <label for="negMax">Max price per unit you will pay (₹)</label>
          <input id="negMax" name="max_price" type="number" step="0.5" min="0.5" value="${maxP}" required>
        </div>
        <button class="btn cyan lg" ${S.negBusy ? "disabled" : ""}>⚡ Start Autonomous Haggling</button>
      </form>
      <div class="sm muted mt" id="negLive">${row ? html`Live list price: <b>${inr(row.price)}/${row.unit}</b> · stock ${num(row.stock_qty)} ${row.unit}. Suggested limit ${inr(negSuggestedMax(row.price))}/${row.unit}.` : ""}</div>
    </div>

    ${neg ? html`
      <div class="card mb">
        <div class="spread">
          <div>
            <h3>Negotiation Transcript: ${neg.product} (${neg.qty} ${neg.unit})</h3>
            <div class="sm muted">Wholesaler: ${neg.wholesaler} · List price: ${inr(neg.list_price)}/${neg.unit} · Seller Stance: <span class="badge">${neg.seller_stance || "balanced"}</span></div>
          </div>
          ${!finished ? html`<span class="badge ai">Negotiating live...</span>` : neg.status === "deal" ? html`
            <div class="right">
              <span class="badge ok" style="font-size:14px">Deal at ${inr(neg.agreed_price)}/${neg.unit}</span>
              <div class="sm ok mt">Saves ${inr(neg.savings)} total</div>
            </div>
          ` : html`<span class="badge bad">No deal reached</span>`}
        </div>

        <div class="chat mt">
          ${(neg.transcript || []).slice(0, shown).map(m => html`
            <div class="msg ${m.agent} bubble ${m.agent} ${m.agent === "system" && neg.status !== "deal" ? "no" : ""}">
              <b>${m.agent === "buyer" ? "Buyer Agent" : m.agent === "seller" ? "Seller Agent" : "System"}:</b>
              ${m.text}
            </div>
          `)}
        </div>

        ${finished && neg.status === "deal" && !neg.order_id ? html`
          <div class="mt row">
            <button class="btn ok lg" data-a="acceptNeg" data-id="${neg.id}">🤝 Accept Deal & Place Order (${inr(neg.agreed_price)}/${neg.unit})</button>
          </div>
        ` : ""}
      </div>
    ` : ""}
  `;
}

async function aiForecast() {
  const fc = await api("/ai/forecast");
  const items = fc.items || [];

  return html`
    <div class="card mb">
      <div class="spread">
        <div>
          <h3>Predictive Demand Forecast & Stock Alerts</h3>
          <div class="sm muted">Exponential smoothing (α = 0.3) on historical POS consumption + seasonal/festival demand spikes.</div>
        </div>
        ${fc.festival ? html`<span class="badge warn">Upcoming: ${fc.festival.name} in ${fc.festival.days_away} days</span>` : ""}
      </div>

      <div class="grid g3 mt">
        ${items.map(it => html`
          <div class="card ${it.level === "critical" ? "bad" : it.level === "warning" ? "warnbg" : ""}">
            <div class="spread">
              <h4>${it.product}</h4>
              <span class="badge ${it.level === "critical" ? "bad" : it.level === "warning" ? "warn" : "ok"}">${it.level}</span>
            </div>
            <div class="mt">
              <b>Stock:</b> ${num(it.stock)} ${it.unit}
              <br><small class="muted">Avg daily use: ${num(it.daily_use)} ${it.unit}/day</small>
            </div>
            <div class="mt sm">
              <b>Status:</b> ${it.message}
            </div>
            ${it.suggested_qty > 0 ? html`
              <div class="mt row">
                <span class="sm ok">Reorder: <b>${num(it.suggested_qty)} ${it.unit}</b></span>
                <button class="btn sm cyan" data-a="reorder" data-p="${it.product}" data-q="${it.suggested_qty}" data-u="${it.unit}">Procure</button>
              </div>
            ` : ""}
          </div>
        `)}
      </div>
    </div>
  `;
}

// ------------------------------------------------------------------ ORDERS
async function vOrders() {
  const me = S.me;
  const list = await api("/orders");

  return html`
    <div class="spread mb">
      <div>
        <h2>Orders & Deliveries</h2>
        <div class="sm muted">Track procurement orders, delivery quotes, Paytm payment gateway settlements, shipments and merchant reviews.</div>
      </div>
    </div>

    ${list.length === 0 ? html`
      <div class="card"><p class="muted">No orders found.</p></div>
    ` : html`
      <div class="orders-list">
        ${list.map(o => orderCard(o))}
      </div>
    `}
  `;
}

function orderCard(o) {
  const me = S.me;
  const isMerchantUser = isMerchant();
  const isWholesale = isWholesaler();
  const st = o.status;

  const stBadge = {
    quote_pending: "warn",
    quoted: "warn",
    confirmed: "ok",
    shipped: "ai",
    delivered: "ok",
    cancelled: "bad"
  }[st] || "";

  return html`
    <div class="card mb">
      <div class="spread">
        <div>
          <h3>Order #${o.id} <span class="badge ${stBadge}">${st.replace("_", " ")}</span></h3>
          <div class="sm muted">
            ${isMerchantUser ? `Supplier: ${o.wholesaler ? o.wholesaler.shop : "Wholesaler"}` : `Buyer: ${o.buyer ? o.buyer.shop : "Merchant"}`}
            · ${ago(o.created_at)} · Source: ${o.source}
          </div>
        </div>
        <div class="right">
          <div class="b" style="font-size:18px">${inr(o.total || o.items_total)}</div>
          <small class="muted">${o.delivery_charge !== null ? `Goods: ${inr(o.items_total)} + Deliv: ${inr(o.delivery_charge)}` : `Goods: ${inr(o.items_total)} (Delivery unquoted)`}</small>
        </div>
      </div>

      <div class="mt">
        <table>
          <thead>
            <tr><th>Item</th><th>Quantity</th><th>Unit Price</th><th>Cost</th></tr>
          </thead>
          <tbody>
            ${(o.items || []).map(it => html`
              <tr>
                <td><b>${it.product}</b></td>
                <td>${num(it.qty)} ${it.unit}</td>
                <td>${inr(it.unit_price)}</td>
                <td>${inr(it.qty * it.unit_price)}</td>
              </tr>
            `)}
          </tbody>
        </table>
      </div>

      <div class="spread mt">
        <div class="sm muted">
          ${o.delivery_note ? `Note: ${o.delivery_note}` : ""}
          ${o.eta_days ? ` · Estimated Arrival: ${o.eta_days} day(s)` : ""}
        </div>

        <div class="row">
          ${o.can_quote ? html`
            <button class="btn sm cyan" data-a="openQuoteModal" data-id="${o.id}">Quote Delivery Charge</button>
          ` : ""}

          ${o.can_pay ? html`
            <button class="btn sm cyan" data-a="openPayModal" data-id="${o.id}">Choose Payment Mode</button>
          ` : ""}

          ${o.can_ship ? html`
            <button class="btn sm navy" data-a="shipOrder" data-id="${o.id}">Mark as Shipped</button>
          ` : ""}

          ${o.can_deliver ? html`
            <button class="btn sm ok" data-a="deliverOrder" data-id="${o.id}">Confirm Delivery & Add to Stock</button>
          ` : ""}

          ${o.can_review ? html`
            <button class="btn sm sec" data-a="openReviewModal" data-id="${o.id}">Leave Review</button>
          ` : ""}

          ${o.can_cancel ? html`
            <button class="btn sm bad" data-a="cancelOrder" data-id="${o.id}">Cancel</button>
          ` : ""}
        </div>
      </div>
    </div>
  `;
}

// ------------------------------------------------------------------ CREDIT & EMI
async function vCredit() {
  const me = S.me;
  if (!isMerchant()) {
    return html`<div class="card"><p class="muted">Merchant loans and CIBIL checks are for merchants only.</p></div>`;
  }

  const [offer, loans, cibil] = await Promise.all([
    api("/credit/offer"),
    api("/loans"),
    api("/credit/cibil")
  ]);

  return html`
    <div class="spread mb">
      <div>
        <h2>Paytm Business Credit & EMI</h2>
        <div class="sm muted">Instant working capital credit lines, simulated CIBIL score checks, and UPI AutoPay EMI repayments.</div>
      </div>
    </div>

    <div class="grid g3 mb">
      <div class="card hl">
        <h3>Composite Credit Score</h3>
        <div class="v ok mt" style="font-size:32px;font-weight:700">${offer.score || 720}</div>
        <div class="sm muted">Tier: <span class="badge ok">${offer.tier || "Good"}</span> · Approval: ${offer.approval || "Instant"}</div>
        <div class="sm mt">Interest rate: <b>${offer.rate}% p.a.</b></div>
      </div>

      <div class="card">
        <h3>Available Credit Limit</h3>
        <div class="v" style="font-size:32px;font-weight:700">${inr(offer.available || 0)}</div>
        <div class="sm muted">Total Line: ${inr(offer.limit || 0)} · Outstanding: ${inr(offer.outstanding || 0)}</div>
        <div class="bar mt"><i style="width:${Math.round(100 * (offer.outstanding || 0) / (offer.limit || 1))}%"></i></div>
      </div>

      <div class="card">
        <h3>Simulated CIBIL Check</h3>
        ${cibil.checked ? html`
          <div class="v ok mt" style="font-size:28px;font-weight:700">${cibil.checked.score}</div>
          <div class="sm ok">${cibil.checked.band} · ${cibil.checked.tip}</div>
        ` : html`
          <p class="sm muted">Perform a simulated soft-check of your CIBIL bureau score with OTP consent.</p>
          <button class="btn sm sec mt" data-a="openCibilModal">Check CIBIL Score</button>
        `}
      </div>
    </div>

    <div class="card mb">
      <h3>Score Factor Breakdown</h3>
      <table>
        <thead>
          <tr><th>Factor</th><th>Contribution Points</th></tr>
        </thead>
        <tbody>
          ${(offer.factors || []).map(f => html`
            <tr>
              <td>${f.name}</td>
              <td class="b ${f.points >= 0 ? "ok" : "bad"}">${f.points > 0 ? "+" + f.points : f.points} pts</td>
            </tr>
          `)}
        </tbody>
      </table>
    </div>

    <h3>My loans</h3>
    ${loans.length === 0 ? html`
      <div class="card"><p class="muted">No active loans. You can choose "Pay with Paytm loan" at order checkout to unlock EMI financing.</p></div>
    ` : html`
      <div class="loans-list">
        ${loans.map(l => html`
          <div class="card mb">
            <div class="spread">
              <div>
                <h3>Loan #${l.id} - ${inr(l.amount)}</h3>
                <div class="sm muted">${l.tenure} months @ ${l.rate}% p.a. · EMI: ${inr(l.emi)}/mo · Created ${ago(l.created_at)}</div>
              </div>
              <div class="right">
                <span class="badge ${l.status === "active" ? "ok" : "muted"}">${l.status}</span>
                <div class="sm ok mt"><b>${l.paid_emis}/${l.tenure} paid</b></div>
              </div>
            </div>
            <div class="spread mt">
              <div class="sm row">
                <span>UPI AutoPay: <b>${l.autopay ? "Enabled" : "Disabled"}</b></span>
                <button class="btn sm sec" data-a="toggleAutopay" data-id="${l.id}" data-on="${l.autopay ? "0" : "1"}">
                  ${l.autopay ? "Turn off AutoPay" : "Enable AutoPay"}
                </button>
              </div>
              <div>
                ${l.status === "active" ? html`
                  <button class="btn sm cyan" data-a="payEmi" data-id="${l.id}">Simulate auto-debit</button>
                ` : ""}
              </div>
            </div>
          </div>
        `)}
      </div>
    `}
  `;
}

// ------------------------------------------------------------------ STOCK / INVENTORY
async function vStock() {
  const me = S.me;
  if (isWholesaler()) {
    const inv = await api("/wholesaler/inventory");
    return html`
      <div class="spread mb">
        <div>
          <h2>Wholesaler Catalog & Inventory</h2>
          <div class="sm muted">Manage product stocks, list prices, and private protected floor prices for negotiation.</div>
        </div>
      </div>
      <div class="card">
        <table>
          <thead>
            <tr><th>Product</th><th>Warehouse</th><th>Stock Qty</th><th>List Price (₹)</th><th>Floor Price (₹)</th><th>Actions</th></tr>
          </thead>
          <tbody>
            ${(inv.items || []).map(it => html`
              <tr>
                <td><b>${it.product}</b></td>
                <td>${it.warehouse || it.warehouse_city}</td>
                <td>${num(it.stock_qty)} ${it.unit}</td>
                <td>${inr(it.price)}</td>
                <td><b>${inr(it.floor_price)}</b></td>
                <td>
                  <button class="btn sm sec" data-a="openEditInventoryModal" data-p="${it.product}" data-price="${it.price}" data-stock="${it.stock_qty}" data-floor="${it.floor_price}">Edit</button>
                </td>
              </tr>
            `)}
          </tbody>
        </table>
      </div>
    `;
  }

  const stockList = await api("/stock");
  return html`
    <div class="spread mb">
      <div>
        <h2>Merchant Shelf Inventory</h2>
        <div class="sm muted">Track in-store goods, log daily sales consumption, and feed the predictive demand forecasting engine.</div>
      </div>
      <button class="btn sm cyan" data-a="openSetStockModal">+ Track New Product</button>
    </div>

    <div class="card mb">
      <h3>Current Stock on Shelf</h3>
      <table>
        <thead>
          <tr><th>Product</th><th>Stock Level</th><th>Unit</th><th>Last Usage Logged</th><th>Quick Actions</th></tr>
        </thead>
        <tbody>
          ${stockList.map(it => html`
            <tr>
              <td><b>${it.product}</b></td>
              <td><b>${num(it.stock)}</b></td>
              <td>${it.unit}</td>
              <td class="muted">${it.last_usage || "Today"}</td>
              <td class="row">
                <button class="btn sm sec" data-a="openLogUsageModal" data-p="${it.product}" data-u="${it.unit}">Log Usage (Sale)</button>
                <button class="btn sm sec" data-a="openSetStockModal" data-p="${it.product}" data-s="${it.stock}">Set Stock</button>
              </td>
            </tr>
          `)}
        </tbody>
      </table>
    </div>
  `;
}

// ------------------------------------------------------------------ NOTIFICATIONS
async function vNotifications() {
  const notifs = await api("/notifications");
  const items = notifs.items || [];

  // Automatically mark all notifications as read when viewing this page
  const unreadCount = items.filter(n => !n.is_read).length;
  if (unreadCount > 0) {
    try {
      await api("/notifications/read", "POST", {});
      await loadMe();
    } catch (e) {
      console.error("Failed to auto-mark notifications as read", e);
    }
  }

  return html`
    <div class="spread mb">
      <div>
        <h2>Notifications</h2>
        <div class="sm muted">Real-time alerts for orders, quotes, bids, pool updates and AI moderation flags.</div>
      </div>
      <button class="btn sm sec" data-a="markAllNotificationsRead">Mark all as read</button>
    </div>

    <div class="card">
      ${items.length === 0 ? html`<p class="muted">No notifications.</p>` : html`
        <div class="notifs-list">
          ${items.map(n => html`
            <div class="post notif ${n.is_read ? "" : "hl"}" role="button" tabindex="0" data-a="openNotif" data-kind="${n.kind || ""}" data-link="${n.link || ""}" title="Open">
              <div class="spread">
                <span><b>${String(n.kind || "").toUpperCase()}</b> · ${n.text}</span>
                <span class="sm muted">${ago(n.created_at)} ›</span>
              </div>
              ${n.link && /^group:\d+$/.test(n.link) && /invited/i.test(n.text) ? html`<div class="row mt">
                <button class="btn cyan sm" data-a="joinDirect" data-id="${n.link.split(":")[1]}">Accept invite</button>
              </div>` : ""}
            </div>
          `)}
        </div>
      `}
    </div>
  `;
}
