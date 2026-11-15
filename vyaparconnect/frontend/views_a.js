/* Paytm VyaparConnect AI - Views (Part A): Home, Merchants, Groups, Feed, Pooling */
"use strict";

// ------------------------------------------------------------------ Card helpers
function groupCard(g, recs = false) {
  const st = g.my_status;
  const isPending = st === "pending";
  const isInvited = st === "invited";
  const isActive = st === "active";
  const isRejected = st === "rejected";
  const memberCount = g.merchants !== undefined ? g.merchants : (g.members !== undefined ? g.members : 0);

  return html`<div class="card ${isActive ? "hl" : ""}">
    <div class="spread">
      <h3>${g.name}</h3>
      ${recs && g.score ? html`<span class="badge ai" title="AI match score">AI match ${g.score}%</span>` : ""}
    </div>
    <div class="sm muted">${g.description || "Local merchant buying collective"}</div>
    <div class="mt">
      <span class="badge">${g.city}</span>
      <span class="badge">${g.category}</span>
      <span class="badge ${g.type === "public" ? "ok" : "warn"}">${g.type === "public" ? "Open (AI auto-approve)" : "Invite / admin approval"}</span>
    </div>
    <div class="sm mt">${memberCount} merchants · admin ${g.admin_name || "Admin"}</div>
    ${recs && g.reasons && g.reasons.length > 0 ? html`<ul class="tight sm muted">${g.reasons.map(r => html`<li>${r}</li>`)}</ul>` : ""}
    <div class="row mt">
      <button class="btn sec sm" data-a="openGroup" data-id="${g.id}">${isActive ? "Open group" : "Open group"}</button>
      ${st === null ? html`
        <button class="btn sm" data-a="precheckJoin" data-id="${g.id}">
          ${g.type === "public" ? "Join" : "Request to join"}
        </button>
      ` : ""}
      ${isPending ? html`<span class="badge warn">Request pending</span>` : ""}
      ${isInvited ? html`<button class="btn cyan sm" data-a="joinDirect" data-id="${g.id}">Accept invite</button>` : ""}
      ${isRejected ? html`<span class="badge bad">Rejected</span>` : ""}
      ${isActive ? html`<span class="badge ok">${g.is_admin ? "You are admin" : "Member"}</span>` : ""}
    </div>
  </div>`;
}

function dealCard(d, g = {}) {
  const me = S.me;
  const canClose = d.is_open && d.commitments && d.commitments.length > 0 && (d.wholesaler_id === me.id || g.is_admin || d.can_close);
  const maxQ = d.next_tier ? d.next_tier.min_qty : (d.tiers && d.tiers.length ? (d.tiers[d.tiers.length - 1].min_qty || 1) : 1);
  const totalQ = d.total_qty || 0;
  const pct = Math.min(100, Math.round(100 * totalQ / (maxQ || 1)));
  const unit = d.unit || "kg";

  return html`<div class="card">
    <div class="spread">
      <h3>${d.product} <span class="badge ${d.kind === "clearance" ? "bad" : d.kind === "seasonal" ? "warn" : "ok"}">${KIND[d.kind] || d.kind || "Pooled deal"}</span>
        ${!d.is_open ? html`<span class="badge">Closed</span>` : ""}
      </h3>
      <span class="sm muted">${d.wholesaler ? d.wholesaler.shop : ""} · ${d.is_open ? "ends in " + daysTo(d.expires_at) + "d" : "ended"}</span>
    </div>
    <div class="tier">
      ${(d.tiers || []).map(t => html`
        <span class="chip ${d.current_tier && d.current_tier.min_qty === t.min_qty ? "on" : ""}">
          ${t.min_qty ? num(t.min_qty) + "+ " + unit : "Any qty"}: ${inr(t.price)}/${unit}
        </span>
      `)}
    </div>
    <div class="bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
    <div class="sm">
      <b>${num(totalQ)} ${unit}</b> pooled by ${d.participants || (d.commitments ? d.commitments.length : 0)} merchant(s) → now <b>${inr(d.current_price)}/${unit}</b>.
      ${d.next_tier ? html`<span class="muted"> ${num(d.to_next_tier)} ${unit} more unlocks ${inr(d.next_tier.price)}/${unit}.</span>` : html`<span class="ok"> Best tier unlocked!</span>`}
    </div>
    ${d.total_savings > 0 ? html`<div class="sm ok">Group savings so far: <b>${inr(d.total_savings)}</b> (auto-split by share)</div>` : ""}
    ${d.commitments && d.commitments.length > 0 ? html`
      <table class="mt">
        <thead>
          <tr><th>Merchant</th><th>Qty</th><th>Share</th><th>Cost</th><th>Saved</th></tr>
        </thead>
        <tbody>
          ${d.commitments.map(c => html`
            <tr>
              <td>${c.shop}</td>
              <td>${num(c.qty)}</td>
              <td>${c.share_pct}%</td>
              <td>${inr(c.cost)}</td>
              <td class="ok">${inr(c.savings)}</td>
            </tr>
          `)}
        </tbody>
      </table>
    ` : ""}
    ${d.is_open && isMerchant() ? html`
      <form data-f="commit" data-id="${d.id}" class="form mt">
        <div class="field">
          <label for="q${d.id}">My quantity (${unit})</label>
          <input id="q${d.id}" name="qty" type="number" min="0" step="any" value="${d.my_commitment ? d.my_commitment.qty : ""}" required>
        </div>
        <button class="btn cyan">Commit to pool</button>
        ${d.my_commitment ? html`<button type="button" class="btn bad sm" data-a="withdrawPool" data-id="${d.id}">Withdraw</button>` : ""}
      </form>
    ` : ""}
    ${canClose ? html`<div class="mt"><button class="btn sec" data-a="closePool" data-id="${d.id}">Close pool & create orders</button></div>` : ""}
  </div>`;
}

// ------------------------------------------------------------------ HOME
async function vHome() {
  if (!isMerchant()) return vWholesalerHome();
  const me = S.me;
  const [fc, recsData, posHome, stockList] = await Promise.all([
    api("/ai/forecast"),
    api("/groups/recommendations"),
    api("/home"),
    api("/stock")
  ]);

  const recs = recsData.groups || [];
  const nearbyMerchants = recsData.merchants || [];

  // Construct suggested group proposal if nearby candidates exist
  let suggested = null;
  if (nearbyMerchants.length > 0) {
    const topCandidates = nearbyMerchants.slice(0, 3);
    const sharedItems = topCandidates[0].shared_products ? topCandidates[0].shared_products.join(", ") : "Rice, Sugar";
    suggested = {
      name: `${me.city} ${me.category === "fmcg" ? "FMCG" : "Grocery"} Alliance`,
      reason: `3 nearby merchants buy the same key items (${sharedItems}) and could pool bulk orders together.`,
      candidates: topCandidates
    };
  }

  return html`
    <h2>Namaste, ${me.name} 👋</h2>
    <div class="grid g4 mb">
      <div class="stat">
        <div class="k"><span>Today's Collections</span><span class="pill">POS</span></div>
        <div class="v">${inr(posHome.payments ? posHome.payments.amount : 12450)}</div>
        <div class="d muted">${posHome.payments ? posHome.payments.count : 42} transactions settled</div>
      </div>
      <div class="stat">
        <div class="k"><span>Groups Joined</span><span class="pill">Network</span></div>
        <div class="v">${me.groups ? me.groups.length : 0}</div>
        <div class="d ok">Active member</div>
      </div>
      <div class="stat">
        <div class="k"><span>Rating</span><span class="pill">Reviews</span></div>
        <div class="v">⭐ ${me.rating_avg ? me.rating_avg.toFixed(1) : "5.0"}</div>
        <div class="d muted">${me.rating_count || 0} verified reviews</div>
      </div>
      <div class="stat">
        <div class="k"><span>Open Orders</span><span class="pill">Procurement</span></div>
        <div class="v">${posHome.open_orders || 0}</div>
        <div class="d muted">Pending quote / delivery</div>
      </div>
    </div>

    ${me.invites && me.invites.length > 0 ? html`
      <div class="card hl mb">
        <h3>Group invitations</h3>
        ${me.invites.map(i => html`
          <div class="row spread mt">
            <span><b>${i.name}</b> (${i.city} · ${i.category})</span>
            <button class="btn cyan sm" data-a="joinDirect" data-id="${i.id}">Accept invite</button>
          </div>
        `)}
      </div>
    ` : ""}

    <div class="card mb">
      <div class="spread">
        <h3>🔮 Predictive demand alerts ${fc.festival ? html`<span class="badge warn">${fc.festival.name} in ${fc.festival.days_away} days</span>` : ""}</h3>
        <button class="btn sec sm" data-a="tab" data-v="ai" data-sub="fc">Full forecast</button>
      </div>
      ${fc.alerts && fc.alerts.length > 0 ? html`
        <div class="mt">
          ${fc.alerts.slice(0, 4).map(a => html`
            <div class="alert ${a.level}">
              <div>
                <span class="lvl ${a.level}"></span>
                <b>${a.message}</b>
                <div class="sm muted mt">${a.source || ""}</div>
              </div>
              <div class="sm row">
                <span>Suggested reorder: <b>${num(a.suggested_qty)} ${a.unit}</b></span>
                <button class="btn sm cyan" data-a="reorder" data-p="${a.product}" data-q="${a.suggested_qty}" data-u="${a.unit}">Find best deal</button>
              </div>
            </div>
          `)}
        </div>
      ` : html`<p class="muted">All tracked inventory looks healthy.</p>`}
    </div>

    <div class="card mb">
      <div class="spread">
        <div>
          <h3>📦 Store Shelf Inventory & Usage</h3>
          <div class="sm muted">Track in-store goods, log customer sales, and feed predictive AI demand replenishment.</div>
        </div>
        <button class="btn cyan sm" data-a="openSetStockModal">+ Track New Product</button>
      </div>
      ${(stockList || []).length === 0 ? html`
        <p class="muted mt">No shelf inventory tracked yet. Click '+ Track New Product' above to start tracking shelf stock.</p>
      ` : html`
        <table class="mt">
          <thead>
            <tr><th>Product</th><th>Shelf Stock</th><th>Unit</th><th>Last Usage Logged</th><th>Quick Actions</th></tr>
          </thead>
          <tbody>
            ${(stockList || []).map(it => html`
              <tr>
                <td><b>${it.product}</b></td>
                <td><span class="badge ${it.stock <= 15 ? "warn" : "ok"}"><b>${num(it.stock)}</b></span></td>
                <td>${it.unit}</td>
                <td class="muted">${it.last_usage || "Today"}</td>
                <td class="row">
                  <button class="btn sec sm" data-a="openLogUsageModal" data-p="${it.product}" data-u="${it.unit}">Log Sale (Usage)</button>
                  <button class="btn sec sm" data-a="openSetStockModal" data-p="${it.product}" data-s="${it.stock}">Update Stock</button>
                  <button class="btn cyan sm" data-a="reorder" data-p="${it.product}" data-q="50" data-u="${it.unit}">Find Deal</button>
                </td>
              </tr>
            `)}
          </tbody>
        </table>
      `}
    </div>

    ${suggested ? html`
      <div class="card hl mb">
        <h3>🤝 AI-suggested group</h3>
        <p><b>${suggested.name}</b> - ${suggested.reason}</p>
        <table>
          <thead>
            <tr><th>Merchant</th><th>City</th><th>Shared items</th><th>Match</th></tr>
          </thead>
          <tbody>
            ${suggested.candidates.map(c => html`
              <tr>
                <td><b>${c.shop}</b><br><small class="muted">${c.name}</small></td>
                <td>${c.city}</td>
                <td>${(c.shared_products || []).join(", ")}</td>
                <td><span class="badge ok">${c.similarity || 85}% match</span></td>
              </tr>
            `)}
          </tbody>
        </table>
        <div class="mt">
          <button class="btn cyan" data-a="formSuggested" data-name="${suggested.name}" data-ids="${suggested.candidates.map(c => c.id).join(",")}">
            Form group & invite ${suggested.candidates.length} merchants
          </button>
        </div>
      </div>
    ` : ""}
  `;
}

async function vWholesalerHome() {
  const me = S.me;
  const [d, inv] = await Promise.all([
    api("/home"),
    api("/wholesaler/inventory")
  ]);

  return html`
    <h2>${me.shop} - Wholesaler Dashboard</h2>
    <div class="grid g4 mb">
      <div class="stat">
        <div class="k"><span>Completed Orders</span></div>
        <div class="v">${d.orders || 0}</div>
        <div class="d ok">Fulfilled</div>
      </div>
      <div class="stat">
        <div class="k"><span>Total Revenue</span></div>
        <div class="v">${inr(d.revenue || 0)}</div>
        <div class="d muted">Gross goods sales</div>
      </div>
      <div class="stat">
        <div class="k"><span>Pending Quotes</span></div>
        <div class="v">${d.to_quote || 0}</div>
        <div class="d warn">Needs delivery quote</div>
      </div>
      <div class="stat">
        <div class="k"><span>To Ship</span></div>
        <div class="v">${d.to_ship || 0}</div>
        <div class="d ok">Ready for dispatch</div>
      </div>
    </div>

    <div class="grid g2 mb">
      <div class="card">
        <h3>Top Demand in Your Region (Last 30 Days)</h3>
        <p class="sm muted">High-volume items actively ordered by regional merchants:</p>
        ${inv.demand && inv.demand.length > 0 ? html`
          <table>
            <thead>
              <tr><th>Product</th><th>Merchants</th><th>Total Qty</th><th>Action</th></tr>
            </thead>
            <tbody>
              ${inv.demand.map(x => html`
                <tr>
                  <td><b>${x.product}</b></td>
                  <td>${x.merchants} buyers</td>
                  <td>${num(x.qty)}</td>
                  <td><button class="btn sm sec" data-a="quickSale" data-p="${x.product}">List Sale</button></td>
                </tr>
              `)}
            </tbody>
          </table>
        ` : html`<p class="muted">No recent demand logged.</p>`}
      </div>

      <div class="card">
        <h3>Quick Catalog Stock & Floor Prices</h3>
        <table>
          <thead>
            <tr><th>Product</th><th>Stock</th><th>List Price</th><th>Floor (Min)</th></tr>
          </thead>
          <tbody>
            ${(inv.items || []).slice(0, 6).map(it => html`
              <tr>
                <td><b>${it.product}</b></td>
                <td>${num(it.stock_qty)} ${it.unit}</td>
                <td>${inr(it.price)}</td>
                <td class="muted">${inr(it.floor_price)}</td>
              </tr>
            `)}
          </tbody>
        </table>
        <div class="mt">
          <button class="btn sm cyan" data-a="tab" data-v="inventory">Manage full inventory & floor prices</button>
        </div>
      </div>
    </div>
  `;
}

// ------------------------------------------------------------------ NEARBY MERCHANTS MODAL HELPER
function nearbyMerchantsModalContent(list, gid = null) {
  const me = S.me;
  return html`
    <div class="spread mb">
      <div>
        <h3>🔍 Nearby Merchants Directory</h3>
        <div class="sm muted">Connect and combine verified merchants in ${me ? me.city : ""} and neighboring hubs to form buying groups.</div>
      </div>
    </div>

    <div class="info-banner mb">
      <b>💡 How merchants data shared with you is found:</b>
      VyaparConnect AI compares your store's regular inventory and POS purchase history against other verified stores in your area. When merchants purchase the same staple goods (e.g., Rice, Sugar, Oil), they are highlighted below as <b>Shared with you</b> so you can connect and pool wholesale orders to unlock lowest tier prices!
    </div>

    <div class="field mb">
      <label for="mSearchInput">Filter merchants by name, shop, city or product:</label>
      <input id="mSearchInput" placeholder="Type to filter (e.g. Rice, Kumar, Erode)..." oninput="filterMerchantPopupList(this.value)">
    </div>

    <form data-f="combineMerchants" data-gid="${gid || ""}" class="form col">
      <div class="spread sm">
        <span><b>${list.length} nearby merchants found</b></span>
        <button type="button" class="btn ghost sm" data-a="selectAllMerchants">Select All</button>
      </div>

      <div class="merchant-select-list" id="merchantPopupList">
        ${list.map(m => html`
          <label class="merchant-item" data-text="${(m.shop + ' ' + m.name + ' ' + m.city + ' ' + (m.shared_products || []).join(' ') + ' ' + (m.items || []).join(' ')).toLowerCase()}">
            <input type="checkbox" name="merchant_ids" value="${m.id}" data-shop="${m.shop}">
            <div class="grow">
              <div class="spread">
                <b>${m.shop}</b>
                <span class="sm muted">${m.near_label || m.city} · ⭐ ${(m.rating_avg || 5).toFixed(1)}</span>
              </div>
              <div class="sm muted">${m.name} · ${m.city} · ${m.category} ${m.kyc_verified ? "· KYC ✓" : ""}</div>
              ${m.shared_products && m.shared_products.length > 0 ? html`
                <div class="mt">
                  <span class="badge ok">Shared with you: ${m.shared_products.join(", ")}</span>
                </div>
              ` : html`
                <div class="sm muted mt">Key items: ${(m.items || []).join(", ") || "Groceries"}</div>
              `}
            </div>
            ${gid ? html`
              <button type="button" class="btn cyan sm" data-a="inviteSingleMerchant" data-gid="${gid}" data-uid="${m.id}" data-name="${m.shop}">Invite</button>
            ` : ""}
          </label>
        `)}
      </div>

      <div class="spread mt">
        <button type="button" class="btn sec" data-a="closeModal">Cancel</button>
        ${gid ? html`
          <button type="submit" class="btn cyan">Invite Selected Merchants to Group</button>
        ` : html`
          <button type="submit" class="btn cyan">Form New Group with Selected Merchants</button>
        `}
      </div>
    </form>
  `;
}

// ------------------------------------------------------------------ GROUPS
async function vGroups() {
  if (S.gid) return vGroup(S.gid);
  const [gs, recsData] = await Promise.all([
    api("/groups"),
    api("/groups/recommendations")
  ]);
  const mine = gs.filter(g => g.my_status === "active");
  const invited = gs.filter(g => g.my_status === "invited");
  const others = gs.filter(g => g.my_status !== "active" && g.my_status !== "invited");
  const recs = recsData.groups || [];

  return html`
    <div class="spread mb">
      <div>
        <h2>Groups</h2>
        <div class="sm muted">Verified merchant groups to pool bulk orders, unlock volume tiers, and prevent supplier collusion.</div>
      </div>
      ${isMerchant() ? html`<button class="btn cyan" data-a="openNewGroupModal">+ Create group</button>` : ""}
    </div>

    ${invited.length > 0 ? html`
      <div class="card hl mb">
        <h3>📩 Group invitations (${invited.length})</h3>
        <p class="sm muted">You have been invited by a group admin. Accept to join instantly - no approval needed.</p>
        ${invited.map(g => html`
          <div class="row spread mt">
            <span><b>${g.name}</b> <span class="muted sm">(${g.city} · ${g.category} · ${g.merchants !== undefined ? g.merchants : (g.members || 0)} merchants · admin ${g.admin_name || "Admin"})</span></span>
            <span class="row">
              <button class="btn sec sm" data-a="openGroup" data-id="${g.id}">View</button>
              <button class="btn cyan sm" data-a="joinDirect" data-id="${g.id}">Accept invite</button>
            </span>
          </div>
        `)}
      </div>
    ` : ""}

    <h3>My groups</h3>
    ${mine.length === 0 ? html`
      <div class="card mb"><p class="muted">You have not joined any group yet. Explore recommendations below or create your own.</p></div>
    ` : html`
      <div class="grid g2 mb">${mine.map(g => groupCard(g))}</div>
    `}

    ${recs.length > 0 ? html`
      <h3 class="mt">🤖 Recommended Groups for You</h3>
      <div class="grid g2 mb">
        ${recs.map(g => groupCard({ ...g, my_status: null, is_admin: false }, true))}
      </div>
    ` : ""}

    <h3 class="mt">Discover & Join Groups</h3>
    ${others.length === 0 ? html`
      <div class="card"><p class="muted">No other groups found.</p></div>
    ` : html`
      <div class="grid g2">${others.map(g => groupCard(g))}</div>
    `}
  `;
}

async function vGroup(gid) {
  const d = await api("/groups/" + gid);
  const me = S.me;
  const isMember = d.my_status === "active";
  const isAdmin = d.is_admin;

  const subs = [
    ["feed", "Feed"],
    ["deals", "Deals"],
    ["members", `Members (${d.members ? d.members.length : 0})`]
  ];
  if (isAdmin) {
    subs.push(["requests", `Requests (${d.pending ? d.pending.length : 0})`]);
  }

  if (!subs.some(s => s[0] === S.gtab)) S.gtab = "feed";

  const head = html`
    <button class="btn sec sm mb" data-a="backToGroups">← All groups</button>
    <div class="spread mt mb">
      <div>
        <h2>${d.name}</h2>
        <div class="sm muted">${d.description || "Local merchant buying collective"}</div>
        <div class="mt">
          <span class="badge">${d.city}</span>
          <span class="badge">${d.category}</span>
          <span class="badge ${d.type === "public" ? "ok" : "warn"}">${d.type === "public" ? "Open" : "Invite only"}</span>
          <span class="badge">${d.members ? d.members.length : 0} members · Admin: ${d.admin_name || "Admin"}</span>
        </div>
      </div>
      <div>
        ${isMember && !isAdmin ? html`<button class="btn bad sm" data-a="leaveGroup" data-id="${d.id}">Leave group</button>` : ""}
      </div>
    </div>
  `;

  if (d.locked || !isMember) {
    return html`
      ${head}
      <div class="card mt">
        <h3>🔒 Members only</h3>
        <p class="muted">Join this group to access the private discussion feed, group-pooled bulk deals, and collective bargaining power.</p>
        <div class="mt">
          ${d.my_status === null ? html`
            <button class="btn cyan" data-a="precheckJoin" data-id="${d.id}">
              ${d.type === "public" ? "Join Group" : "Request to join"}
            </button>
          ` : ""}
          ${d.my_status === "pending" ? html`<span class="badge warn">Request pending admin approval</span>` : ""}
          ${d.my_status === "invited" ? html`<button class="btn cyan" data-a="joinDirect" data-id="${d.id}">Accept invite</button>` : ""}
          ${d.my_status === "rejected" ? html`<span class="badge bad">Your join request was rejected</span>` : ""}
        </div>
      </div>
    `;
  }

  const st = d.stats || { pools: 0, open_pools: 0, pooled_value: 0, total_savings: 0 };
  let bodyContent;
  if (S.gtab === "feed") bodyContent = gFeed(d);
  else if (S.gtab === "deals") bodyContent = gDeals(d);
  else if (S.gtab === "members") bodyContent = gMembers(d);
  else bodyContent = gRequests(d);

  return html`
    ${head}
    <div class="grid g4 mb mt">
      <div class="stat">
        <div class="k"><span>Active Pools</span></div>
        <div class="v">${st.open_pools || 0}</div>
      </div>
      <div class="stat">
        <div class="k"><span>Total Pools</span></div>
        <div class="v">${st.pools || 0}</div>
      </div>
      <div class="stat">
        <div class="k"><span>Pooled Value</span></div>
        <div class="v">${inr(st.pooled_value || 0)}</div>
      </div>
      <div class="stat">
        <div class="k"><span>Group Savings</span></div>
        <div class="v ok">${inr(st.total_savings || 0)}</div>
      </div>
    </div>

    <div class="tabs mb">
      ${subs.map(([k, l]) => html`
        <button class="tab ${S.gtab === k ? "on" : ""}" data-a="gtab" data-v="${k}">${l}</button>
      `)}
    </div>

    ${bodyContent}
  `;
}

function gFeed(d) {
  const me = S.me;
  const isWholesale = isWholesaler();

  return html`
    <div class="collective-box mb">
      <div class="spread">
        <div>
          <h3 style="color:#065f46">🤖 AI Group Reverse Auction Assistant</h3>
          <p class="sm" style="color:#047857;margin:2px 0 0">
            Discussed a bulk item with group members? Once agreed, let VyaparConnect AI launch a collective reverse auction across participating group members to get competitive wholesaler bids in the Auctions marketplace!
          </p>
        </div>
        <button class="btn ok sm" data-a="openCollectiveAuctionModal" data-gid="${d.id}">+ AI Post to Auctions</button>
      </div>
    </div>

    <div class="card mb">
      <form data-f="post" class="form col">
        <label for="postText">Share an update, stock alert or procurement tip with the group</label>
        <textarea id="postText" name="body" maxlength="500" required placeholder="${isWholesale ? "Announce a special wholesale deal..." : "Share local pricing or suggest a bulk item to pool..."}"></textarea>
        <div class="row spread mt">
          <div class="sm muted">🛡️ AI moderation active: automatically flags and holds anti-competitive price-fixing or cartel discussions for admin review.</div>
          <button class="btn">Post to group</button>
        </div>
      </form>
    </div>

    ${d.feed && d.feed.length > 0 ? html`
      <div class="feed-list">
        ${d.feed.map(p => html`
          <div class="post ${p.status === "held" ? "held" : ""}">
            <div class="spread">
              <span>
                <b>${p.author_shop || p.author}</b>
                <span class="badge sm">${p.author || ""}</span>
                <span class="badge sm ok">${p.kind || "announcement"}</span>
              </span>
              <span class="sm muted">${ago(p.created_at)}</span>
            </div>
            <div class="mt">${p.body}</div>
            ${p.status === "held" ? html`
              <div class="mt sm bad">
                <b>⚠ Held by AI moderation:</b> ${p.flag_reason || "Anti-competitive keyword detected"}.
                ${d.is_admin ? " (As group admin, you can approve or remove this post below)" : " (Visible to you and group admins)"}
              </div>
              ${d.is_admin ? html`
                <div class="row mt">
                  <button class="btn sm ok" data-a="reviewPost" data-gid="${d.id}" data-pid="${p.id}" data-act="approve">Approve Post</button>
                  <button class="btn sm bad" data-a="reviewPost" data-gid="${d.id}" data-pid="${p.id}" data-act="remove">Remove Post</button>
                </div>
              ` : ""}
            ` : ""}
          </div>
        `)}
      </div>
    ` : html`<p class="muted">No posts yet in this group feed. Start the conversation above!</p>`}
  `;
}

function gDeals(d) {
  const pools = d.pools || [];
  const isWholesale = isWholesaler();

  return html`
    <div class="spread mb">
      <h3>Active Group Pools & Collective Auctions</h3>
      <div class="row">
        <button class="btn ok sm" data-a="openCollectiveAuctionModal" data-gid="${d.id}">+ AI Post Collective Auction</button>
        ${isWholesale ? html`
          <button class="btn cyan sm" data-a="openNewDealModal" data-gid="${d.id}">+ Post pooled deal</button>
        ` : ""}
      </div>
    </div>

    ${pools.length === 0 ? html`
      <div class="card">
        <p class="muted">No active pooled deals in this group right now.
        ${isWholesale ? "Click 'Post pooled deal' above to list a tiered bulk price for group members." : "When wholesalers list tiered sales, you can pool quantities together here to unlock the lowest tier."}</p>
      </div>
    ` : html`
      <div class="deals-list">
        ${pools.map(p => dealCard(p, d))}
      </div>
    `}
  `;
}

function gMembers(d) {
  const members = d.members || [];
  const isAdmin = d.is_admin;

  return html`
    <div class="card mb">
      <h3>Group Members (${members.length}/30)</h3>
      <p class="sm muted mb">Anti-collusion safeguard: groups are capped at 30 members to maintain fair local competitive balance.</p>
      <table>
        <thead>
          <tr><th>Shop</th><th>Contact</th><th>City</th><th>Category</th><th>Role</th><th>Rating</th></tr>
        </thead>
        <tbody>
          ${members.map(m => html`
            <tr>
              <td><b>${m.shop}</b></td>
              <td>${m.name}</td>
              <td>${m.city}</td>
              <td>${m.category}</td>
              <td><span class="badge ${m.group_role === "admin" ? "ai" : ""}">${m.group_role}</span></td>
              <td>⭐ ${(m.rating_avg || 5).toFixed(1)}</td>
            </tr>
          `)}
        </tbody>
      </table>
    </div>

    <div class="card">
      <div class="spread">
        <div>
          <h3>🤝 Expand Group Buying Power — Invite Nearby Merchants</h3>
          <p class="sm muted">Discover and combine local merchants in ${d.city} buying similar products to pool larger bulk volumes and unlock maximum tier discounts.</p>
        </div>
        <button class="btn cyan sm" data-a="openNearbyMerchantsModal" data-gid="${d.id}">🔍 Find & Combine Merchants</button>
      </div>
    </div>
  `;
}

function gRequests(d) {
  const pending = d.pending || [];
  if (pending.length === 0) {
    return html`<div class="card"><p class="muted">No pending join requests.</p></div>`;
  }

  return html`
    <div class="requests-list">
      ${pending.map(p => html`
        <div class="card mb">
          <div class="spread">
            <div>
              <h3>${p.shop} <span class="badge sm">${p.category}</span></h3>
              <div class="sm muted">${p.name} · ${p.city} · Rating: ⭐ ${(p.rating_avg || 5).toFixed(1)}</div>
              ${p.note ? html`<div class="sm mt">“${p.note}”</div>` : ""}
            </div>
            <div class="row">
              <button class="btn sm" data-a="decide" data-gid="${d.id}" data-id="${p.id}" data-v="1">Approve</button>
              <button class="btn bad sm" data-a="decide" data-gid="${d.id}" data-id="${p.id}" data-v="0">Reject</button>
            </div>
          </div>
          <div class="mt">
            <h4>🤖 AI pre-check: ${p.ai_check && p.ai_check.pass ? html`<span class="ok">recommended</span>` : html`<span class="bad">review needed</span>`}</h4>
            <ul class="tight sm">
              ${(p.ai_check ? p.ai_check.reasons : []).map(r => html`<li class="${r.ok ? "ok" : "no"}">${r.text || r}</li>`)}
            </ul>
          </div>
        </div>
      `)}
    </div>
  `;
}
