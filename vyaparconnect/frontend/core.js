/* Paytm VyaparConnect AI - Core state, helpers, API client & routing */
"use strict";

class Raw { constructor(s) { this.s = s; } }
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const val = v => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(val).join("") : (v === false || v == null) ? "" : esc(v);
const html = (s, ...v) => { let o = s[0]; v.forEach((x, i) => { o += val(x) + s[i + 1]; }); return new Raw(o); };
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const num = n => Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 1 });
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const ago = iso => {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago";
};
const daysTo = iso => {
  if (!iso) return 0;
  return Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 86400000));
};

const KIND = {
  bulk: "Bulk deal",
  clearance: "Clearance",
  seasonal: "Seasonal",
  flash_sale: "Flash sale",
  announcement: "Announcement"
};

const S = {
  users: [],
  uid: null,
  me: null,
  tab: "home",
  subTab: null,
  gid: null,
  gtab: "feed",
  aiTab: "proc",
  ordersTab: "all",
  proc: null,
  procText: "50 kg rice, 20 L oil, budget 6000",
  neg: null,
  catalog: [],
  products: [],
  cities: [],
  categories: [],
  lastHtml: "",
  searchQuery: "",
  checkoutLines: null,
  checkoutWholesaler: null
};

async function api(path, method = "GET", body) {
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": String(S.uid || 1)
    }
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = typeof j.detail === "string" ? j.detail : "Request failed (" + r.status + ")";
    throw new Error(detail);
  }
  return j;
}

let toastT;
function toast(msg, err = false) {
  const t = $("#toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.hidden = true; }, 3800);
}

async function act(fn) {
  try {
    return await fn();
  } catch (e) {
    toast(e.message || String(e), true);
  }
}

function modal(content, wide = false) {
  const m = $("#modal");
  if (!m) return;
  m.innerHTML = html`<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
    <button class="x btn ghost sm" data-a="closeModal" aria-label="Close modal">×</button>
    ${content}
  </div>`.s;
  m.hidden = false;
}

function closeModal() {
  const m = $("#modal");
  if (!m) return;
  m.hidden = true;
  m.innerHTML = "";
}

const isMerchant = () => S.me && S.me.role === "merchant";
const isWholesaler = () => S.me && S.me.role === "wholesaler";

function tabsFor() {
  if (isMerchant()) {
    return [
      ["home", "Home"],
      ["groups", "Groups"],
      ["merchants", "Merchants"],
      ["auctions", "Auctions"],
      ["ai", "AI Buyer"],
      ["orders", "Orders"],
      ["credit", "Credit & EMI"],
      ["stock", "Inventory"]
    ];
  }
  return [
    ["home", "Dashboard"],
    ["auctions", "Auctions"],
    ["orders", "Orders"],
    ["inventory", "Inventory"]
  ];
}

async function loadMe() {
  try {
    S.me = await api("/me");
  } catch (e) {
    const userList = Array.isArray(S.users) ? S.users : [];
    const ravi = userList.find(u => u.name === "Ravi" || (u.shop && u.shop.includes("Ravi")));
    S.uid = ravi ? ravi.id : 7;
    localStorage.setItem("vc_uid", String(S.uid));
    try {
      S.me = await api("/me");
    } catch {
      S.me = null;
    }
  }
  const bell = $("#bellN");
  if (bell && S.me) {
    const unread = Number(S.me.unread || 0);
    bell.textContent = unread;
    bell.hidden = unread === 0;
  }
}

async function switchUser(uid) {
  S.uid = Number(uid);
  localStorage.setItem("vc_uid", String(S.uid));
  S.gid = null;
  S.gtab = "feed";
  S.proc = null;
  S.neg = null;
  S.tab = "home";
  await act(loadMe);
  await render();
}

async function render(silent = false) {
  const nav = $("#nav");
  if (nav) {
    const tabs = tabsFor();
    const titleObj = {
      home: isMerchant() ? "Home" : "Dashboard",
      groups: "Groups",
      merchants: "Merchants",
      auctions: "Auctions & Deals",
      ai: "AI Buyer",
      orders: "Orders",
      credit: "Credit & EMI",
      stock: "Inventory",
      inventory: "Inventory",
      notifs: "Notifications"
    };
    const titleEl = $("#pageTitle");
    if (titleEl) titleEl.textContent = titleObj[S.tab] || "VyaparConnect";

    const greeting = S.me ? `${S.me.name}` : "User";
    const shop = S.me ? S.me.shop : "";
    const city = S.me ? S.me.city : "";

    nav.innerHTML = html`
      <div class="hello">${greeting}<small>${shop} · ${city}</small></div>
      <div class="nav-links">
        ${tabs.map(([k, l]) => html`
          <button class="ni tab ${S.tab === k ? "on" : ""}" data-a="tab" data-v="${k}">
            <span class="dot"></span>
            <span>${l}</span>
          </button>
        `)}
      </div>
      <div class="seg">
        <div class="seg-h"><span>Quick Actions</span></div>
        <button class="ni sm" data-a="gotoNotifs">
          <span class="dot"></span>
          <span>Notifications</span>
          ${S.me && S.me.unread > 0 ? html`<span class="cnt">${S.me.unread}</span>` : ""}
        </button>
      </div>
    `.s;
  }

  const views = {
    home: vHome,
    groups: vGroups,
    merchants: vMerchants,
    auctions: vAuctions,
    ai: vAI,
    orders: vOrders,
    credit: vCredit,
    stock: vStock,
    inventory: vStock,
    notifs: vNotifications
  };

  const viewFn = views[S.tab] || vHome;
  let out;
  try {
    out = await viewFn();
  } catch (e) {
    out = html`<div class="card bad"><h3>Error loading view</h3><p>${e.message || String(e)}</p></div>`;
  }
  const s = out.s;
  if (silent) {
    const ae = document.activeElement;
    if (s === S.lastHtml || (ae && ae.closest("main") && /INPUT|TEXTAREA|SELECT/.test(ae.tagName))) return;
  }
  S.lastHtml = s;
  const appEl = $("#app");
  if (appEl) appEl.innerHTML = s;
  if (!silent) window.scrollTo(0, 0);
}
