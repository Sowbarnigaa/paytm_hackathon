/* Paytm VyaparConnect AI - single-page UI (vanilla JS, no build step, no CDN). */
"use strict";

// ------------------------------------------------------------------ helpers
class Raw { constructor(s) { this.s = s; } }
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const val = v => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(val).join("") : (v === false || v == null) ? "" : esc(v);
const html = (s, ...v) => { let o = s[0]; v.forEach((x, i) => { o += val(x) + s[i + 1]; }); return new Raw(o); };
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const num = n => Number(n).toLocaleString("en-IN", { maximumFractionDigits: 1 });
const $ = s => document.querySelector(s);
const ago = iso => { const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000)); return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago"; };
const daysTo = iso => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 86400000));
const KIND = { bulk: "Bulk deal", clearance: "Clearance", seasonal: "Seasonal", flash_sale: "Flash sale", announcement: "Announcement" };

const S = { users: [], uid: null, me: null, tab: "home", gid: null, gtab: "feed", aiTab: "proc", lastHtml: "", proc: null, neg: null, catalog: [], products: [] };

async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, { method, headers: { "Content-Type": "application/json", "X-User-Id": S.uid }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Request failed (" + r.status + ")");
  return j;
}
let toastT;
function toast(msg, err) { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 3800); }
async function act(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }
function modal(content) { const m = $("#modal"); m.innerHTML = html`<div class="modal" role="dialog" aria-modal="true"><button class="x" data-a="closeModal" aria-label="Close">×</button>${content}</div>`.s; m.hidden = false; }
function closeModal() { $("#modal").hidden = true; $("#modal").innerHTML = ""; }
const isMerchant = () => S.me && S.me.role === "merchant";

// ------------------------------------------------------------------ shell
function tabsFor() {
  return isMerchant()
    ? [["home", "Home"], ["groups", "Groups"], ["ai", "AI Buyer"], ["auctions", "Auctions"], ["credit", "Credit & EMI"], ["orders", "Orders"]]
    : [["home", "Dashboard"], ["groups", "Groups"], ["auctions", "Auctions"]];
}

async function loadMe() { S.me = await api("/me"); }

async function boot() {
  S.users = await (await fetch("/api/users")).json();
  const saved = Number(localStorage.getItem("vc_uid"));
  const ravi = S.users.find(u => u.name === "Ravi");
  S.uid = S.users.some(u => u.id === saved) ? saved : ravi.id;
  const sel = $("#userSel");
  const opt = u => html`<option value="${u.id}">${u.name} - ${u.shop} (${u.city})</option>`;
  sel.innerHTML = html`<optgroup label="Merchants">${S.users.filter(u => u.role === "merchant").map(opt)}</optgroup><optgroup label="Wholesalers">${S.users.filter(u => u.role === "wholesaler").map(opt)}</optgroup>`.s;
  sel.value = S.uid;
  S.products = await (await fetch("/api/products")).json();
  S.catalog = await (await fetch("/api/catalog")).json();
  await switchUser(S.uid);
}

async function switchUser(uid) {
  S.uid = Number(uid); localStorage.setItem("vc_uid", S.uid);
  S.gid = null; S.gtab = "feed"; S.proc = null; S.neg = null; S.tab = "home";
  await act(loadMe);
  await render();
}

async function render(silent) {
  $("#tabs").innerHTML = tabsFor().map(([k, l]) => `<button class="tab${S.tab === k ? " on" : ""}" data-a="tab" data-v="${k}">${esc(l)}</button>`).join("");
  const views = { home: vHome, groups: vGroups, ai: vAI, auctions: vAuctions, credit: vCredit, orders: vOrders };
  let out;
  try { out = await views[S.tab](); } catch (e) { out = html`<div class="card bad">${e.message}</div>`; }
  const s = out.s;
  if (silent) {
    const ae = document.activeElement;
    if (s === S.lastHtml || (ae && ae.closest("main") && /INPUT|TEXTAREA|SELECT/.test(ae.tagName))) return;
  }
  S.lastHtml = s; $("#app").innerHTML = s;
  if (!silent) window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ shared fragments
function groupCard(g, recs) {
  const st = g.my_status;
  return html`<div class="card ${st === "active" ? "hl" : ""}">
    <div class="spread"><h3>${g.name}</h3>${recs && html`<span class="badge ai" title="AI match score">AI match ${g.score}%</span>`}</div>
    <div class="sm muted">${g.description}</div>
    <div class="mt"><span class="badge">${g.city}</span><span class="badge">${g.category}</span>
      <span class="badge ${g.type === "public" ? "ok" : "warn"}">${g.type === "public" ? "Open (AI auto-approve)" : "Invite / admin approval"}</span></div>
    <div class="sm mt">${g.merchants} merchants · ${g.wholesalers} wholesalers · admin ${g.admin_name || ""}</div>
    ${recs && html`<ul class="tight sm muted">${(g.reasons || []).map(r => html`<li>${r}</li>`)}</ul>`}
    <div class="row mt">
      <button class="btn sec sm" data-a="openGroup" data-id="${g.id}">${st === "active" ? "Open group" : "View"}</button>
      ${st === null && html`<button class="btn sm" data-a="join" data-id="${g.id}">${g.instant_join || g.type === "public" ? "Join" : "Request to join"}</button>`}
      ${st === "pending" && html`<span class="badge warn">Request pending</span>`}
      ${st === "invited" && html`<button class="btn cyan sm" data-a="join" data-id="${g.id}">Accept invite</button>`}
      ${st === "rejected" && html`<span class="badge bad">Rejected</span>`}
      ${st === "active" && html`<span class="badge ok">${g.is_admin ? "You are admin" : "Member"}</span>`}
    </div></div>`;
}

function dealCard(d, g) {
  const me = S.me, canClose = d.is_open && d.commitments.length && (d.wholesaler_id === me.id || g.is_admin);
  const maxQ = d.next_tier ? d.next_tier.min_qty : (d.tiers.at(-1).min_qty || 1);
  const pct = Math.min(100, Math.round(100 * d.total_qty / maxQ));
  return html`<div class="card">
    <div class="spread"><h3>${d.product} <span class="badge ${d.kind === "clearance" ? "bad" : d.kind === "seasonal" ? "warn" : "ok"}">${KIND[d.kind]}</span>
      ${!d.is_open && html`<span class="badge">Closed</span>`}</h3>
      <span class="sm muted">${d.wholesaler.shop} · ${d.is_open ? "ends in " + daysTo(d.expires_at) + "d" : "ended"}</span></div>
    <div class="tier">${d.tiers.map(t => html`<span class="chip ${d.current_tier && d.current_tier.min_qty === t.min_qty ? "on" : ""}">${t.min_qty ? num(t.min_qty) + "+ " + d.unit : "Any qty"}: ${inr(t.price)}/${d.unit}</span>`)}</div>
    <div class="bar" aria-hidden="true"><i style="width:${pct}%"></i></div>
    <div class="sm"><b>${num(d.total_qty)} ${d.unit}</b> pooled by ${d.participants} merchant(s) → now <b>${inr(d.current_price)}/${d.unit}</b>.
      ${d.next_tier ? html`<span class="muted"> ${num(d.to_next_tier)} ${d.unit} more unlocks ${inr(d.next_tier.price)}/${d.unit}.</span>` : html`<span class="ok"> Best tier unlocked!</span>`}</div>
    ${d.total_savings > 0 && html`<div class="sm ok">Group savings so far: <b>${inr(d.total_savings)}</b> (auto-split by share)</div>`}
    ${d.commitments.length > 0 && html`<table class="mt"><tr><th>Merchant</th><th>Qty</th><th>Share</th><th>Cost</th><th>Saved</th></tr>
      ${d.commitments.map(c => html`<tr><td>${c.shop}</td><td>${num(c.qty)}</td><td>${c.share_pct}%</td><td>${inr(c.cost)}</td><td class="ok">${inr(c.savings)}</td></tr>`)}</table>`}
    ${d.is_open && isMerchant() && html`<form data-f="commit" data-id="${d.id}" class="form mt">
      <div class="field"><label for="q${d.id}">My quantity (${d.unit})</label><input id="q${d.id}" name="qty" type="number" min="0" step="any" value="${d.my_commitment ? d.my_commitment.qty : ""}" required></div>
      <button class="btn cyan">${d.my_commitment ? "Update commitment" : "Commit to pool"}</button>
      ${d.my_commitment && html`<button type="button" class="btn bad sm" data-a="withdraw" data-id="${d.id}">Withdraw</button>`}</form>`}
    ${canClose && html`<div class="mt"><button class="btn sec" data-a="closeDeal" data-id="${d.id}">Close pool & create orders</button></div>`}
  </div>`;
}

// ------------------------------------------------------------------ HOME
async function vHome() {
  if (!isMerchant()) return vWholesalerHome();
  const [fc, recs, sug] = await Promise.all([api("/ai/forecast"), api("/groups/recommendations"), api("/groups/suggestions")]);
  const me = S.me;
  return html`
  <h2>Namaste, ${me.name} 👋</h2>
  <div class="stats">
    <div class="stat">Shop<b>${me.shop}</b></div><div class="stat">Groups joined<b>${me.groups.length}</b></div>
    <div class="stat">Trust score<b>${me.trust}</b></div><div class="stat">Credit score<b>${me.credit_score}</b></div></div>
  ${me.invites.length > 0 && html`<div class="card hl"><h3>Group invitations</h3>${me.invites.map(i => html`<div class="row spread"><span>${i.name} (${i.city})</span><button class="btn cyan sm" data-a="join" data-id="${i.id}">Accept invite</button></div>`)}</div>`}
  <div class="card"><div class="spread"><h3>🔮 Predictive demand alerts ${fc.festival && html`<span class="badge warn">${fc.festival.name} in ${fc.festival.days_away} days</span>`}</h3>
    <button class="btn sec sm" data-a="tab" data-v="ai" data-sub="fc">Full forecast</button></div>
    ${fc.alerts.length === 0 ? html`<p class="muted">All stock looks healthy.</p>` : fc.alerts.slice(0, 4).map(a => html`<div class="alert ${a.level}"><b>${a.message}</b>
      <div class="sm">Suggested reorder: ${num(a.suggested_qty)} ${a.unit} · <button class="btn sm cyan" data-a="reorder" data-p="${a.product}" data-q="${a.suggested_qty}" data-u="${a.unit}">Find best deal</button></div></div>`)}</div>
  ${sug.proposal && html`<div class="card hl"><h3>🤝 AI-suggested group</h3><p><b>${sug.proposal.name}</b> - ${sug.proposal.reason}</p>
    <table><tr><th>Merchant</th><th>Shared items</th><th>Match</th></tr>${sug.candidates.map(c => html`<tr><td>${c.shop}</td><td>${c.shared_products.join(", ")}</td><td>${c.similarity}%</td></tr>`)}</table>
    <div class="mt"><button class="btn cyan" data-a="formSuggested">Form group & invite ${sug.candidates.length} merchants</button></div></div>`}
  <h2>Recommended groups for you</h2>
  ${recs.length === 0 ? html`<p class="muted">No new groups match yet - create one in the Groups tab.</p>` : html`<div class="grid">${recs.map(g => groupCard({ ...g, my_status: null, is_admin: false }, true))}</div>`}`;
}

async function vWholesalerHome() {
  const d = await api("/wholesaler/dashboard");
  return html`<h2>${S.me.shop}</h2>
  <div class="stats"><div class="stat">Groups<b>${d.groups.length}</b></div><div class="stat">Orders<b>${d.revenue.n}</b></div><div class="stat">Revenue<b>${inr(d.revenue.t)}</b></div></div>
  <div class="grid"><div class="card"><h3>Demand in your groups (30 days)</h3>${d.demand.length === 0 ? html`<p class="muted">No demand data yet.</p>` : html`<table><tr><th>Product</th><th>Merchants</th><th>Qty</th></tr>${d.demand.map(x => html`<tr><td>${x.product}</td><td>${x.merchants}</td><td>${num(x.qty)}</td></tr>`)}</table>`}
    <p class="sm muted">Use this to post a pooled deal in the right group.</p></div>
  <div class="card"><h3>My groups</h3>${d.groups.map(g => html`<div class="row spread"><span>${g.name}</span><button class="btn sec sm" data-a="openGroup" data-id="${g.id}">Open</button></div>`)}</div>
  <div class="card"><h3>Recent orders</h3>${d.orders.length === 0 ? html`<p class="muted">No orders yet.</p>` : html`<table><tr><th>Buyer</th><th>Total</th><th>Source</th></tr>${d.orders.map(o => html`<tr><td>${o.buyer}</td><td>${inr(o.total)}</td><td>${o.source}</td></tr>`)}</table>`}</div></div>`;
}

// ------------------------------------------------------------------ GROUPS (priority)
async function vGroups() {
  if (S.gid) return vGroup();
  const gs = await api("/groups");
  const mine = gs.filter(g => g.my_status === "active"), others = gs.filter(g => g.my_status !== "active");
  return html`<div class="spread"><h2>Groups</h2>${isMerchant() && html`<button class="btn cyan" data-a="newGroup">+ Create group</button>`}</div>
  <p class="muted sm">Verified B2B groups where merchants and wholesalers unlock bulk, clearance and seasonal deals together.</p>
  <h3>My groups</h3>${mine.length === 0 ? html`<p class="muted">You have not joined any group yet.</p>` : html`<div class="grid">${mine.map(g => groupCard(g))}</div>`}
  <h3 class="mt">Discover</h3><div class="grid">${others.map(g => groupCard(g))}</div>`;
}

async function vGroup() {
  const d = await api("/groups/" + S.gid), me = S.me;
  const subs = [["feed", "Feed"], ["deals", "Deals & pooling"], ["members", "Members (" + d.members.length + ")"]];
  if (d.is_admin) subs.push(["requests", "Requests (" + d.pending.length + ")"]);
  if (!subs.some(s => s[0] === S.gtab)) S.gtab = "feed";
  const head = html`<button class="btn sec sm" data-a="backGroups">← All groups</button>
    <div class="spread mt"><div><h2>${d.name}</h2><div class="sm muted">${d.description}</div>
      <div class="mt"><span class="badge">${d.city}</span><span class="badge">${d.category}</span><span class="badge ${d.type === "public" ? "ok" : "warn"}">${d.type === "public" ? "Open" : "Invite only"}</span><span class="badge">${d.merchants} merchants · ${d.wholesalers} wholesalers</span></div></div>
      <div>${d.my_status === "active" && !d.is_admin && html`<button class="btn bad sm" data-a="leave" data-id="${d.id}">Leave</button>`}</div></div>`;
  if (d.locked) {
    return html`${head}<div class="card mt"><h3>🔒 Members only</h3><p>Join to see the group feed, deals and pooled prices.</p>
      ${d.my_status === null && html`<button class="btn" data-a="join" data-id="${d.id}">${d.type === "public" ? "Join" : "Request to join"}</button>`}
      ${d.my_status === "pending" && html`<span class="badge warn">Request pending admin approval</span>`}
      ${d.my_status === "invited" && html`<button class="btn cyan" data-a="join" data-id="${d.id}">Accept invite</button>`}
      ${d.my_status === "rejected" && html`<span class="badge bad">Your request was rejected</span>`}</div>`;
  }
  const st = d.stats;
  let body;
  if (S.gtab === "feed") body = gFeed(d);
  else if (S.gtab === "deals") body = gDeals(d);
  else if (S.gtab === "members") body = gMembers(d);
  else body = gRequests(d);
  return html`${head}
    <div class="stats mt"><div class="stat">Open deals<b>${st.open_deals}</b></div><div class="stat">Pooled volume<b>${num(st.pooled_qty)}</b></div>
      <div class="stat">Pooled value<b>${inr(st.pooled_value)}</b></div><div class="stat">Group savings<b class="ok">${inr(st.total_savings)}</b></div></div>
    <div class="sub">${subs.map(([k, l]) => html`<button class="${S.gtab === k ? "on" : ""}" data-a="gtab" data-v="${k}">${l}</button>`)}</div>${body}`;
}

function gFeed(d) {
  const w = S.me.role === "wholesaler";
  return html`<div class="card"><form data-f="post" class="form">
    <div class="field" style="flex:1;min-width:220px"><label for="pb">Post to group</label><textarea id="pb" name="body" maxlength="500" required placeholder="${w ? "Announce a flash sale or clearance…" : "Ask the group or share a tip…"}"></textarea></div>
    <div class="field">${w && html`<label for="pk">Type</label><select id="pk" name="kind"><option value="announcement">Announcement</option><option value="flash_sale">Flash sale</option><option value="clearance">Clearance</option><option value="seasonal">Seasonal</option></select>`}</div>
    <button class="btn">Post</button></form>
    <p class="sm muted">🛡️ AI moderation screens posts for price-fixing and collusion language before they reach the group.</p></div>
    ${d.feed.length === 0 ? html`<p class="muted">No posts yet.</p>` : d.feed.map(p => html`<div class="post ${p.status === "held" ? "held" : ""}">
      <div class="spread"><span><b>${p.author}</b> <span class="badge ${p.author_role === "wholesaler" ? "ai" : ""}">${p.author_role}</span><span class="badge ${p.kind === "clearance" ? "bad" : p.kind === "flash_sale" ? "warn" : ""}">${KIND[p.kind] || p.kind}</span></span><span class="sm muted">${ago(p.created_at)}</span></div>
      <div>${p.body}</div>
      ${p.status === "held" && html`<div class="sm bad">⚠ Held by AI moderation: ${p.flag_reason}. ${d.is_admin ? "" : "Only you and the admin can see this."}</div>`}
      ${p.status === "held" && d.is_admin && html`<div class="row mt"><button class="btn sm" data-a="review" data-id="${p.id}" data-v="approve">Approve</button><button class="btn bad sm" data-a="review" data-id="${p.id}" data-v="remove">Remove</button></div>`}</div>`)}`;
}

function gDeals(d) {
  return html`${S.me.role === "wholesaler" && html`<div class="mt"><button class="btn cyan" data-a="newDeal">+ Post pooled deal</button></div>`}
    ${d.deals.length === 0 ? html`<p class="muted mt">No deals yet. ${S.me.role === "wholesaler" ? "Post one with price tiers so merchants can pool their orders." : "Wholesalers in this group will post bulk, clearance and seasonal deals here."}</p>` : html`<div class="mt">${d.deals.map(x => dealCard(x, d))}</div>`}`;
}

function gMembers(d) {
  return html`<div class="card"><table><tr><th>Name</th><th>Shop</th><th>Role</th><th>Trust</th></tr>
    ${d.members.map(m => html`<tr><td>${m.name}</td><td>${m.shop}</td><td><span class="badge ${m.role === "wholesaler" ? "ai" : ""}">${m.group_role}</span>${m.role === "wholesaler" && html`<span class="badge ok">KYC ✓</span>`}</td><td>${m.trust}</td></tr>`)}</table>
    <p class="sm muted">Anti-collusion rule: wholesalers can be at most 40% of a group.</p></div>
    ${d.is_admin && html`<div class="card"><h3>Invite a nearby merchant</h3><div id="invbox" class="muted sm">Loading…</div></div>`}`;
}

function gRequests(d) {
  if (!d.pending.length) return html`<p class="muted">No pending requests.</p>`;
  return html`${d.pending.map(p => html`<div class="card"><div class="spread"><div><h3>${p.shop} <span class="badge">${p.role}</span></h3><div class="sm muted">${p.name} · ${p.city} · trust ${p.trust}</div>
    <div class="sm">“${p.note}”</div></div><div class="row"><button class="btn sm" data-a="decide" data-id="${p.id}" data-v="1">Approve</button><button class="btn bad sm" data-a="decide" data-id="${p.id}" data-v="0">Reject</button></div></div>
    <h4>🤖 AI pre-check: ${p.ai_check.pass ? html`<span class="ok">recommended</span>` : html`<span class="bad">review needed</span>`}</h4>
    <ul class="tight sm">${p.ai_check.reasons.map(r => html`<li>${r}</li>`)}</ul></div>`)}`;
}

async function loadInviteBox() {
  const box = $("#invbox"); if (!box) return;
  const [near, d] = await Promise.all([api("/merchants/nearby"), api("/groups/" + S.gid)]);
  const inGroup = new Set(d.members.map(m => m.id)), pend = new Set(d.pending.map(p => p.id));
  const list = near.filter(m => !inGroup.has(m.id) && !pend.has(m.id));
  box.innerHTML = list.length ? html`${list.map(m => html`<div class="row spread"><span>${m.shop} <span class="badge">${m.category}</span> <span class="muted">trust ${m.trust}</span></span><button class="btn sec sm" data-a="invite" data-id="${m.id}">Invite</button></div>`)}`.s : "No more merchants nearby.";
}

// ------------------------------------------------------------------ AI BUYER
async function vAI() {
  const subs = [["proc", "Procurement agent"], ["neg", "Smart negotiator"], ["fc", "Demand forecast"]];
  const head = html`<h2>AI Buyer</h2><div class="sub">${subs.map(([k, l]) => html`<button class="${S.aiTab === k ? "on" : ""}" data-a="aiTab" data-v="${k}">${l}</button>`)}</div>`;
  if (S.aiTab === "proc") return html`${head}${aiProc()}`;
  if (S.aiTab === "neg") return html`${head}${aiNeg()}`;
  return html`${head}${await aiForecast()}`;
}

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function aiProc() {
  const r = S.proc;
  return html`<div class="card"><form data-f="procure">
    <label for="ptext">Tell the agent what you need (English / Tamil / Hindi words work: arisi, chawal…)</label>
    <textarea id="ptext" name="text" required>${S.procText || "50 kg rice, 20 L oil, 10 cartons biscuits, budget 6000"}</textarea>
    <div class="row mt"><button class="btn cyan">Find best suppliers</button>
      ${SR && html`<select id="vlang" aria-label="Voice language"><option value="en-IN">English</option><option value="ta-IN">தமிழ்</option><option value="hi-IN">हिन्दी</option><option value="te-IN">తెలుగు</option><option value="mr-IN">मराठी</option></select><button type="button" class="btn sec" data-a="mic">🎤 Speak</button>`}</div></form></div>
    ${r && html`<div class="card hl"><h3>🤖 ${r.summary}</h3>
      <div class="sm">Understood: ${r.parsed.lines.map(l => html`<span class="badge">${num(l.qty)} ${l.unit} ${l.product}${l.assumed_qty ? " (assumed)" : ""}</span>`)} ${r.parsed.budget && html`<span class="badge ok">Budget ${inr(r.parsed.budget)}</span>`}</div>
      ${r.parsed.unrecognised.length > 0 && html`<div class="sm bad">Couldn't understand: ${r.parsed.unrecognised.join(", ")}</div>`}
      ${r.budget_note && html`<div class="sm mt"><b>${r.budget_note}</b></div>`}
      ${r.group_pools.length > 0 && html`<div class="mt"><h4>💡 Group pools you can join (cheaper than buying alone)</h4>${r.group_pools.map(p => html`<div class="alert"><b>${p.product}</b> in ${p.group}: ${inr(p.current_price)}/${p.unit} now, down to ${inr(p.best_tier_price)}/${p.unit} at ${num(p.best_tier_qty)}+ ${p.unit}
        <button class="btn sm cyan" data-a="gotoDeal" data-g="${p.group_id}">Open</button></div>`)}</div>`}</div>
    <div class="grid">${r.suppliers.map(s => html`<div class="card ${s.rank === 1 ? "hl" : ""}"><div class="spread"><h3>#${s.rank} ${s.wholesaler.shop}</h3><span class="score" title="Price 50 · Delivery 25 · Trust 25">${s.score}/100</span></div>
      <div class="sm muted">${s.wholesaler.city} · trust ${s.wholesaler.trust} · ${s.delivery_days}d delivery · ${s.coverage}% of your list</div>
      <table class="mt">${s.lines.map(l => html`<tr><td>${l.product}</td><td>${num(l.qty)} ${l.unit} @ ${inr(l.unit_price)}</td><td class="right">${inr(l.cost)}</td></tr>`)}
        <tr><td colspan="2"><b>Total</b></td><td class="right"><b>${inr(s.total)}</b></td></tr></table>
      <div class="sm mt">${s.reason}</div>
      <div class="row mt">${s.within_budget ? html`<span class="badge ok">Within budget</span>` : html`<span class="badge bad">Over budget</span>`}
        <button class="btn sm" data-a="checkout" data-w="${s.wholesaler.id}" data-lines='${JSON.stringify(s.lines.map(l => ({ product: l.product, qty: l.qty })))}' data-total="${s.total}" data-shop="${s.wholesaler.shop}">Order</button>
        ${s.lines.length === 1 && html`<button class="btn sec sm" data-a="negFrom" data-w="${s.wholesaler.id}" data-p="${s.lines[0].product}" data-q="${s.lines[0].qty}">Negotiate</button>`}</div></div>`)}</div>`}`;
}

function aiNeg() {
  const n = S.neg, prods = [...new Set(S.catalog.map(c => c.product))];
  const cur = S.negForm || { product: "Rice", qty: 100, wholesaler_id: null, max_price: 53 };
  const ws = S.catalog.filter(c => c.product === cur.product);
  return html`<div class="card"><p class="sm muted">Set your ceiling price. Your Buyer Agent negotiates with the wholesaler's Seller Agent - it never goes above your limit and the seller's floor stays private.</p>
    <form data-f="negotiate" class="form">
      <div class="field"><label for="np">Product</label><select id="np" name="product" data-change="negProduct">${prods.map(p => html`<option ${p === cur.product ? "selected" : ""}>${p}</option>`)}</select></div>
      <div class="field"><label for="nw">Wholesaler</label><select id="nw" name="wholesaler_id">${ws.map(c => html`<option value="${c.wholesaler_id}" ${c.wholesaler_id == cur.wholesaler_id ? "selected" : ""}>${c.shop} - list ${inr(c.price)}/${c.unit}</option>`)}</select></div>
      <div class="field"><label for="nq">Quantity</label><input id="nq" name="qty" type="number" min="1" step="any" value="${cur.qty}" required></div>
      <div class="field"><label for="nm">My max price / unit</label><input id="nm" name="max_price" type="number" min="1" step="any" value="${cur.max_price}" required></div>
      <button class="btn cyan">Start negotiation</button></form></div>
    ${n && html`<div class="card ${n.status === "deal" ? "hl" : ""}"><h3>${n.product} · ${n.wholesaler}</h3><div class="chat">${n.transcript.map(t => html`<div class="bubble ${t.agent}">${t.text}</div>`)}</div>
      ${n.status === "deal" ? html`<div class="row"><span class="badge ok">Deal ${inr(n.agreed_price)}/${n.unit} · total ${inr(n.total)} · you save ${inr(n.savings)}</span>
        ${n.order_done ? html`<span class="badge ok">Order placed ✓</span>` : html`<button class="btn" data-a="acceptNeg" data-id="${n.id}">Accept & order</button>`}</div>` : html`<span class="badge bad">No deal - try a higher limit or a different wholesaler</span>`}</div>`}`;
}

async function aiForecast() {
  const f = await api("/ai/forecast" + (S.fest ? "?festival=" + encodeURIComponent(S.fest) : ""));
  return html`<div class="card"><div class="row spread"><div><h3>Predictive demand</h3><div class="sm muted">Based on your last 60 days of purchases, current stock and festival demand.</div></div>
    <div class="field"><label for="fest">Festival scenario</label><select id="fest" data-change="fest"><option value="">Auto (${f.festival && !S.fest ? f.festival.name : "none upcoming"})</option>${["Diwali", "Pongal", "Eid", "Ugadi"].map(x => html`<option ${S.fest === x ? "selected" : ""}>${x}</option>`)}</select></div></div></div>
    <div class="card"><table><tr><th>Product</th><th>Stock</th><th>Daily use</th><th>Runs out in</th><th>Status</th><th></th></tr>
    ${f.items.map(i => html`<tr><td>${i.product}</td><td>${num(i.stock)} ${i.unit}</td><td>${i.daily_use} ${i.festival_multiplier > 1 ? html`<span class="badge warn">x${i.festival_multiplier}</span>` : ""}</td><td>${i.days_left >= 999 ? "-" : num(i.days_left) + " days"}</td>
      <td><span class="badge ${i.level === "critical" ? "bad" : i.level === "warning" ? "warn" : "ok"}">${i.level}</span></td>
      <td>${i.suggested_qty > 0 && html`<button class="btn sm cyan" data-a="reorder" data-p="${i.product}" data-q="${i.suggested_qty}" data-u="${i.unit}">Reorder ${num(i.suggested_qty)}</button>`}</td></tr>`)}</table></div>`;
}

// ------------------------------------------------------------------ AUCTIONS
async function vAuctions() {
  const [list, gs] = await Promise.all([api("/auctions"), isMerchant() ? api("/groups") : Promise.resolve([])]);
  const mine = gs.filter(g => g.my_status === "active");
  const form = isMerchant() && html`<div class="card"><h3>Post a requirement - wholesalers bid, AI ranks</h3><form data-f="auction" class="form">
    <div class="field"><label for="ap">Product</label><select id="ap" name="product">${S.products.map(p => html`<option>${p.name}</option>`)}</select></div>
    <div class="field"><label for="aq">Quantity</label><input id="aq" name="qty" type="number" min="1" step="any" value="200" required></div>
    <div class="field"><label for="ab">Budget (₹, optional)</label><input id="ab" name="budget" type="number" min="0" step="any"></div>
    <div class="field"><label for="ag">Open to</label><select id="ag" name="group_id"><option value="">All wholesalers</option>${mine.map(g => html`<option value="${g.id}">${g.name} wholesalers</option>`)}</select></div>
    <button class="btn cyan">Post</button></form></div>`;
  const open = list.filter(r => r.status === "open"), closed = list.filter(r => r.status !== "open");
  return html`<h2>Reverse auctions</h2>${form}
    ${list.length === 0 ? html`<p class="muted">${isMerchant() ? "No auctions yet." : "No open requirements you can bid on right now."}</p>` : html`${open.map(auctionCard)}${closed.length > 0 && html`<h3>Closed</h3>${closed.map(auctionCard)}`}`}
    <p class="sm muted">Live: this page refreshes automatically as bids arrive.</p>`;
}

function auctionCard(r) {
  const bidForm = r.can_bid && html`<form data-f="bid" data-id="${r.id}" class="form mt">
    <div class="field"><label for="bp${r.id}">My price / ${r.unit}</label><input id="bp${r.id}" name="price" type="number" min="1" step="any" placeholder="${r.my_bid ? "below " + r.my_bid.price : "market " + r.base_price}" required></div>
    <div class="field"><label for="bd${r.id}">Delivery (days)</label><select id="bd${r.id}" name="delivery_days">${[1, 2, 3, 4, 5, 7].map(d => html`<option ${d === 2 ? "selected" : ""}>${d}</option>`)}</select></div>
    <button class="btn">${r.my_bid ? "Revise bid" : "Place bid"}</button></form>`;
  return html`<div class="card ${r.status === "open" ? "hl" : ""}"><div class="spread"><h3>${num(r.qty)} ${r.unit} ${r.product} ${r.status === "closed" && html`<span class="badge">Closed</span>`}</h3>
    <span class="sm muted">by ${r.buyer_shop} ${r.group_name ? "· " + r.group_name : "· open market"} ${r.budget ? "· budget " + inr(r.budget) : ""}</span></div>
    <div class="sm muted">Market reference: ${inr(r.base_price)}/${r.unit} (${inr(r.market_total)})</div>
    ${r.bids.length === 0 ? html`<p class="muted">Waiting for bids…</p>` : html`<table class="mt"><tr><th>Rank</th><th>Wholesaler</th><th>Price</th><th>Total</th><th>Delivery</th><th>AI score</th><th></th></tr>
      ${r.bids.map(b => html`<tr class="${b.rank === 1 ? "ok" : ""}"><td>${b.rank === 1 ? "🏆 1" : b.rank}</td><td>${b.shop}<div class="sm muted">${b.reason}</div></td><td>${inr(b.price)}</td><td>${inr(b.total)} ${r.budget && !b.within_budget ? html`<span class="badge bad">over</span>` : ""}</td><td>${b.delivery_days}d</td><td class="score">${b.score}</td>
        <td>${r.is_owner && r.status === "open" && html`<button class="btn ${b.rank === 1 ? "cyan" : "sec"} sm" data-a="award" data-id="${r.id}" data-bid="${b.id}">Award</button>`}</td></tr>`)}</table>`}
    ${bidForm}</div>`;
}

// ------------------------------------------------------------------ CREDIT
async function vCredit() {
  const [o, loans] = await Promise.all([api("/credit/offer"), api("/loans")]);
  return html`<h2>Credit & EMI Autopay <span class="badge warn">Simulated</span></h2>
  <div class="grid"><div class="card hl"><h3>Your procurement credit</h3><div class="stats"><div class="stat">Credit score<b>${o.score}</b></div><div class="stat">Tier<b>${o.tier}</b></div><div class="stat">Available<b class="ok">${inr(o.available)}</b></div></div>
    <div class="sm">Limit ${inr(o.limit)} · used ${inr(o.outstanding)} · ${o.rate}% p.a. · ${o.approval} approval · up to ${o.max_tenure} months</div>
    ${o.note && html`<div class="alert mt">${o.note}</div>`}
    ${o.plans.length > 0 && html`<h4>EMI plans for ${inr(o.plan_amount)}</h4><table><tr><th>Tenure</th><th>EMI</th><th>Interest</th></tr>${o.plans.map(p => html`<tr><td>${p.tenure} mo</td><td>${inr(p.emi)}</td><td>${inr(p.interest)}</td></tr>`)}</table>`}
    <p class="sm muted mt">Choose “Pay with loan” at checkout - funds go straight to the wholesaler.</p></div>
  <div class="card"><h3>How your score is built</h3><table>${o.factors.map(f => html`<tr><td>${f.name}</td><td class="right">${f.points >= 0 ? "+" : ""}${f.points}</td></tr>`)}<tr><td><b>Composite</b></td><td class="right"><b>${o.score}</b></td></tr></table>
    <p class="sm muted">On-time EMIs and group membership raise your score and unlock higher limits.</p></div></div>
  <h3 class="mt">My loans</h3>${loans.length === 0 ? html`<p class="muted">No loans yet.</p>` : loans.map(l => html`<div class="card"><div class="spread"><h3>${inr(l.amount)} · ${l.tenure} months · ${l.rate}% <span class="badge ${l.status === "active" ? "warn" : "ok"}">${l.status}</span></h3>
    <label class="row"><input type="checkbox" ${l.autopay ? "checked" : ""} ${l.status !== "active" ? "disabled" : ""} data-change="autopay" data-id="${l.id}"> UPI AutoPay ${l.autopay ? "on" : "off"}</label></div>
    <div class="sm muted">EMI ${inr(l.emi)} · ${l.paid_emis}/${l.tenure} paid · remaining ${inr(l.remaining)}</div>
    <div class="tier mt">${l.schedule.map(s => html`<span class="chip ${s.status === "paid" ? "on" : ""}">#${s.no} ${s.due} ${s.status === "paid" ? "✓" : ""}</span>`)}</div>
    ${l.status === "active" && html`<div class="row mt"><button class="btn sec sm" data-a="payEmi" data-id="${l.id}" data-m="manual">Pay EMI now</button>${l.autopay ? html`<button class="btn sm" data-a="payEmi" data-id="${l.id}" data-m="autopay">Simulate auto-debit</button>` : ""}</div>`}</div>`)}`;
}

async function vOrders() {
  const os = await api("/orders");
  return html`<h2>My orders</h2>${os.length === 0 ? html`<p class="muted">No orders yet.</p>` : html`<div class="card"><table><tr><th>#</th><th>Wholesaler</th><th>Items</th><th>Total</th><th>Source</th><th>Paid by</th></tr>
    ${os.map(o => html`<tr><td>${o.id}</td><td>${o.wholesaler}</td><td>${o.items.map(i => num(i.qty) + " " + i.product + " @" + i.unit_price).join(", ")}</td><td>${inr(o.total)}</td><td>${o.source}</td><td>${o.paid_by_loan ? "Loan" : "Wallet"}</td></tr>`)}</table></div>`}`;
}

// ------------------------------------------------------------------ checkout
async function checkout(w, lines, total, shop) {
  const o = await api("/credit/offer?amount=" + total);
  const canLoan = o.eligible && total <= o.available;
  S.co = { w, lines, total, shop, plans: o.plans };
  modal(html`<h3>Checkout · ${shop}</h3>
    <table>${lines.map(l => html`<tr><td>${l.product}</td><td class="right">${num(l.qty)}</td></tr>`)}<tr><td><b>Total</b></td><td class="right"><b>${inr(total)}</b></td></tr></table>
    <form data-f="order" class="mt"><label class="row"><input type="radio" name="pay" value="wallet" checked> Pay now from Paytm wallet / UPI</label>
      <label class="row"><input type="radio" name="pay" value="loan" ${canLoan ? "" : "disabled"}> Pay with procurement loan (${o.tier} tier) ${canLoan ? "" : html`<span class="muted">- ${o.note || "exceeds your available " + inr(o.available)}</span>`}</label>
      ${canLoan && html`<div id="loanbox" class="card mt" hidden><label for="ten">EMI plan</label><select id="ten" name="tenure">${o.plans.map(p => html`<option value="${p.tenure}">${p.tenure} month(s) - ${inr(p.emi)}/month</option>`)}</select>
        <label class="row mt"><input type="checkbox" name="autopay" checked> Opt in to UPI AutoPay - EMI auto-debited on due date (pause or cancel anytime)</label></div>`}
      <div class="mt"><button class="btn cyan">Confirm order</button></div></form>`);
}

// ------------------------------------------------------------------ actions
const A = {
  closeModal, noop() { },
  async reset() { if (!confirm("Reset all demo data?")) return; await act(async () => { await fetch("/api/reset", { method: "POST" }); toast("Demo data reset"); S.users = await (await fetch("/api/users")).json(); S.catalog = await (await fetch("/api/catalog")).json(); await switchUser(S.uid); }); },
  async tab(el) { S.tab = el.dataset.v; if (el.dataset.sub) S.aiTab = el.dataset.sub; if (S.tab !== "groups") S.gid = null; await render(); },
  async openGroup(el) { S.tab = "groups"; S.gid = Number(el.dataset.id); S.gtab = "feed"; await render(); await loadInviteBox(); },
  async backGroups() { S.gid = null; await render(); },
  async gtab(el) { S.gtab = el.dataset.v; await render(); await loadInviteBox(); },
  async gotoDeal(el) { S.tab = "groups"; S.gid = Number(el.dataset.g); S.gtab = "deals"; await render(); },
  async join(el) {
    await act(async () => {
      const r = await api(`/groups/${el.dataset.id}/join`, "POST", {});
      await loadMe();
      modal(html`<h3>${r.status === "active" ? "✅ " : "⏳ "}${r.message}</h3><h4>🤖 AI membership check</h4><ul class="tight">${r.ai_check.reasons.map(x => html`<li>${x}</li>`)}</ul>
        <button class="btn mt" data-a="closeModal">OK</button>`);
      await render();
    });
  },
  async leave(el) { if (!confirm("Leave this group?")) return; await act(async () => { await api(`/groups/${el.dataset.id}/leave`, "POST"); await loadMe(); S.gid = null; toast("You left the group"); await render(); }); },
  async decide(el) { await act(async () => { const ok = el.dataset.v === "1"; await api(`/groups/${S.gid}/members/${el.dataset.id}/decision`, "POST", { approve: ok }); toast(ok ? "Member approved" : "Request rejected"); await render(); }); },
  async invite(el) { await act(async () => { await api(`/groups/${S.gid}/invite`, "POST", { user_id: Number(el.dataset.id) }); toast("Invitation sent"); await loadInviteBox(); }); },
  async review(el) { await act(async () => { await api(`/groups/${S.gid}/posts/${el.dataset.id}/review`, "POST", { action: el.dataset.v }); toast("Post " + (el.dataset.v === "approve" ? "approved" : "removed")); await render(); }); },
  async withdraw(el) { await act(async () => { await api(`/deals/${el.dataset.id}/commit`, "POST", { qty: 0 }); toast("Commitment withdrawn"); await render(); }); },
  async closeDeal(el) {
    if (!confirm("Close this pool and create an order for every merchant at the final tier price?")) return;
    await act(async () => { const r = await api(`/deals/${el.dataset.id}/close`, "POST"); toast(`Pool closed at ${inr(r.final_price)} - ${r.order_ids.length} order(s) created, ${inr(r.total_savings)} saved`); await render(); });
  },
  async newGroup() {
    modal(html`<h3>Create a group</h3><form data-f="newGroup" class="form" style="flex-direction:column;align-items:stretch">
      <div class="field"><label for="gn">Name</label><input id="gn" name="name" required minlength="3" placeholder="${S.me.city} ${S.me.category === "fmcg" ? "FMCG" : "Grocery"} Buyers"></div>
      <div class="field"><label for="gd">Description</label><textarea id="gd" name="description"></textarea></div>
      <div class="row"><div class="field"><label for="gc">Category</label><select id="gc" name="category">${["grocery", "fmcg", "both"].map(c => html`<option ${c === S.me.category ? "selected" : ""}>${c}</option>`)}</select></div>
        <div class="field"><label for="gt">Type</label><select id="gt" name="type"><option value="invite">Invite / admin approval</option><option value="public">Open (AI auto-approve)</option></select></div></div>
      <button class="btn cyan">Create group</button></form>`);
  },
  async formSuggested() {
    await act(async () => {
      const s = await api("/groups/suggestions"), p = s.proposal; if (!p) return;
      const g = await api("/groups", "POST", { name: p.name, description: p.description, category: p.category, city: p.city, type: p.type });
      for (const c of s.candidates) await api(`/groups/${g.id}/invite`, "POST", { user_id: c.id });
      await loadMe(); toast(`Group created - ${s.candidates.length} merchants invited`);
      S.tab = "groups"; S.gid = g.id; S.gtab = "members"; await render(); await loadInviteBox();
    });
  },
  async newDeal() {
    await act(async () => {
      const dash = await api("/wholesaler/dashboard");
      modal(html`<h3>Post a pooled deal</h3><p class="sm muted">Price falls as the group's combined quantity grows. Members commit quantities; the tier unlocks live.</p>
      <form data-f="newDeal" class="form" style="flex-direction:column;align-items:stretch">
        <div class="row"><div class="field"><label for="dp">Product</label><select id="dp" name="product" data-change="dealProduct">${dash.catalog.map(c => html`<option value="${c.product}" data-price="${c.price}">${c.product} (list ${inr(c.price)}/${c.unit})</option>`)}</select></div>
          <div class="field"><label for="dk">Type</label><select id="dk" name="kind"><option value="bulk">Bulk deal</option><option value="clearance">Clearance</option><option value="seasonal">Seasonal</option></select></div>
          <div class="field"><label for="dd">Valid (days)</label><input id="dd" name="days" type="number" min="1" max="60" value="7"></div></div>
        <table><tr><th>Min qty</th><th>Price / unit (₹)</th></tr>${[0, 1, 2].map(i => html`<tr><td><input name="q${i}" type="number" min="0" step="any" ${i === 0 ? "value=0 readonly" : ""} aria-label="Tier ${i + 1} min qty"></td><td><input name="p${i}" type="number" min="1" step="any" aria-label="Tier ${i + 1} price"></td></tr>`)}</table>
        <button class="btn cyan">Publish deal</button></form>`);
      A.dealProduct($("#dp"));
    });
  },
  dealProduct(el) {
    const price = Number(el.selectedOptions[0].dataset.price), f = el.form;
    [[0, 0, 1], [100, 1, 0.95], [300, 2, 0.9]].forEach(([q, i, m]) => { f["q" + i].value = q; f["p" + i].value = Math.round(price * m * 100) / 100; });
  },
  async reorder(el) {
    S.tab = "ai"; S.aiTab = "proc"; S.procText = `${el.dataset.q} ${el.dataset.u} ${el.dataset.p}`; await render();
    document.querySelector('form[data-f="procure"]').requestSubmit();
  },
  async aiTab(el) { S.aiTab = el.dataset.v; await render(); },
  mic() {
    const rec = new SR(); rec.lang = $("#vlang").value; rec.interimResults = false;
    rec.onresult = e => { $("#ptext").value = e.results[0][0].transcript; toast("Heard: " + e.results[0][0].transcript); };
    rec.onerror = () => toast("Couldn't hear that - please try again", true); rec.start(); toast("Listening…");
  },
  async checkout(el) { await act(() => checkout(Number(el.dataset.w), JSON.parse(el.dataset.lines), Number(el.dataset.total), el.dataset.shop)); },
  negFrom(el) { S.aiTab = "neg"; S.negForm = { product: el.dataset.p, qty: Number(el.dataset.q), wholesaler_id: Number(el.dataset.w), max_price: Math.round((S.catalog.find(c => c.product === el.dataset.p && c.wholesaler_id == el.dataset.w)?.price || 50) * 0.93) }; return render(); },
  async acceptNeg(el) { await act(async () => { const r = await api(`/ai/negotiate/${el.dataset.id}/accept`, "POST"); S.neg.order_done = true; toast("Order #" + r.order_id + " placed at " + inr(r.total)); await render(); }); },
  async award(el) { await act(async () => { const r = await api(`/auctions/${el.dataset.id}/award`, "POST", { bid_id: Number(el.dataset.bid) }); toast(`Awarded to ${r.winner} at ${inr(r.price)}/unit - order #${r.order.order_id}, ${inr(r.saved_vs_market)} vs market`); await render(); }); },
  async payEmi(el) { await act(async () => { await api(`/loans/${el.dataset.id}/pay`, "POST", { mode: el.dataset.m }); toast(el.dataset.m === "autopay" ? "Auto-debit processed (simulated)" : "EMI paid"); await render(); }); },
};

const CHANGE = {
  negProduct(el) { S.negForm = { product: el.value, qty: el.form.qty.value, wholesaler_id: null, max_price: el.form.max_price.value }; render(); },
  fest(el) { S.fest = el.value; render(); },
  dealProduct: el => A.dealProduct(el),
  async autopay(el) { await act(async () => { await api(`/loans/${el.dataset.id}/autopay`, "POST", { on: el.checked }); toast("AutoPay " + (el.checked ? "enabled (simulated mandate)" : "disabled")); await render(); }); },
};

const FORMS = {
  async commit(f, d) { await act(async () => { const v = await api(`/deals/${f.dataset.id}/commit`, "POST", { qty: Number(d.get("qty")) }); toast(`Committed - pool price now ${inr(v.current_price)}/${v.unit}`); await render(); }); },
  async post(f, d) { await act(async () => { const r = await api(`/groups/${S.gid}/posts`, "POST", { body: d.get("body"), kind: d.get("kind") || "announcement" }); toast(r.status === "held" ? "⚠ Held by AI moderation: " + r.flag_reason : "Posted", r.status === "held"); await render(); }); },
  async newGroup(f, d) { await act(async () => { const r = await api("/groups", "POST", { name: d.get("name"), description: d.get("description"), category: d.get("category"), type: d.get("type"), city: S.me.city }); closeModal(); await loadMe(); S.tab = "groups"; S.gid = r.id; toast("Group created - you are the admin"); await render(); await loadInviteBox(); }); },
  async newDeal(f, d) {
    const tiers = [0, 1, 2].filter(i => d.get("p" + i)).map(i => ({ min_qty: Number(d.get("q" + i) || 0), price: Number(d.get("p" + i)) }));
    await act(async () => { await api(`/groups/${S.gid}/deals`, "POST", { product: d.get("product"), kind: d.get("kind"), days: Number(d.get("days")), tiers }); closeModal(); toast("Deal published to the group"); S.gtab = "deals"; await render(); });
  },
  async procure(f, d) { S.procText = d.get("text"); await act(async () => { S.proc = await api("/ai/procure", "POST", { text: S.procText }); await render(); }); },
  async negotiate(f, d) {
    S.negForm = { product: d.get("product"), qty: d.get("qty"), wholesaler_id: d.get("wholesaler_id"), max_price: d.get("max_price") };
    await act(async () => { S.neg = await api("/ai/negotiate", "POST", { wholesaler_id: Number(d.get("wholesaler_id")), product: d.get("product"), qty: Number(d.get("qty")), max_price: Number(d.get("max_price")) }); await render(); });
  },
  async auction(f, d) { await act(async () => { await api("/auctions", "POST", { product: d.get("product"), qty: Number(d.get("qty")), budget: d.get("budget") ? Number(d.get("budget")) : null, group_id: d.get("group_id") ? Number(d.get("group_id")) : null }); toast("Requirement posted - wholesalers can bid now"); await render(); }); },
  async bid(f, d) { await act(async () => { await api(`/auctions/${f.dataset.id}/bids`, "POST", { price: Number(d.get("price")), delivery_days: Number(d.get("delivery_days")) }); toast("Bid placed"); await render(); }); },
  async order(f, d) {
    const c = S.co, pay = d.get("pay");
    await act(async () => {
      const r = await api("/orders", "POST", { wholesaler_id: c.w, lines: c.lines, pay, tenure: pay === "loan" ? Number(d.get("tenure")) : null, autopay: d.get("autopay") === "on" });
      modal(html`<h3>✅ Order #${r.order_id} placed</h3><p>${inr(r.total)} to ${r.wholesaler}, paid via ${pay === "loan" ? "procurement loan" : "wallet"}.</p>
        ${r.loan && html`<div class="card"><b>EMI ${inr(r.loan.emi)} × ${r.loan.tenure} months</b> · ${r.loan.autopay ? "UPI AutoPay on (simulated mandate)" : "manual payment"}<div class="tier mt">${r.loan.schedule.map(s => html`<span class="chip">#${s.no} ${s.due}</span>`)}</div></div>`}
        <button class="btn mt" data-a="closeModal">Done</button>`);
      await loadMe(); S.proc = null;
    });
  },
};

// ------------------------------------------------------------------ wiring
document.addEventListener("click", e => {
  if (e.target.id === "modal") return closeModal();
  const el = e.target.closest("[data-a]");
  if (el && A[el.dataset.a]) A[el.dataset.a](el);
});
document.addEventListener("submit", e => {
  const f = e.target.closest("form[data-f]");
  if (f && FORMS[f.dataset.f]) { e.preventDefault(); FORMS[f.dataset.f](f, new FormData(f)); }
});
document.addEventListener("change", e => {
  if (e.target.id === "userSel") return switchUser(e.target.value);
  if (e.target.name === "pay") { const b = $("#loanbox"); if (b) b.hidden = e.target.value !== "loan"; return; }
  const k = e.target.dataset && e.target.dataset.change;
  if (k && CHANGE[k]) CHANGE[k](e.target);
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
setInterval(() => {
  if (!$("#modal").hidden || document.hidden) return;
  if (S.tab === "auctions" || (S.tab === "groups" && S.gid) || S.tab === "home") render(true);
}, 3000);

boot().catch(e => { $("#app").innerHTML = `<div class="card bad">Could not start: ${esc(e.message)}</div>`; });
