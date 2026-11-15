/* Session guard for the main app. Loaded first in index.html.
   - no token (and not in demo mode)  -> redirect to /login
   - adds `Authorization: Bearer <token>` to every /api call, and redirects to /login on a 401
   - replaces the demo user switcher with the signed-in user's name and a Sign out button */
"use strict";
(() => {
  const token = localStorage.getItem("vc_token");
  const goLogin = () => { localStorage.removeItem("vc_token"); location.replace("/login"); };
  const nativeFetch = window.fetch.bind(window);
  const isApi = u => { try { return new URL(u, location.href).pathname.startsWith("/api/") && !new URL(u, location.href).pathname.startsWith("/api/auth/"); } catch { return false; } };

  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (token && isApi(url)) init = { ...init, headers: { ...(init.headers || {}), Authorization: "Bearer " + token } };
    const r = await nativeFetch(input, init);
    if (r.status === 401 && token && isApi(url)) goLogin();
    return r;
  };

  if (!token) {
    // Demo deployments (VC_DEMO_AUTH=1) may still use the role switcher; everything else must sign in.
    nativeFetch("/api/auth/config").then(r => r.json()).then(c => { if (!c.demo) goLogin(); }).catch(goLogin);
    return;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const who = document.querySelector(".who"), sel = document.getElementById("userSel");
    if (!who) return;
    sel?.setAttribute("hidden", ""); sel?.previousElementSibling?.setAttribute("hidden", "");
    document.querySelector('[data-a="reset"]')?.setAttribute("hidden", "");
    const label = document.createElement("span"); label.className = "sm"; label.id = "whoami";
    const out = document.createElement("button"); out.className = "btn ghost sm"; out.textContent = "Sign out";
    out.onclick = async () => { await nativeFetch("/api/auth/logout", { method: "POST", headers: { Authorization: "Bearer " + token } }).catch(() => {}); goLogin(); };
    who.append(label, out);
    const me = await fetch("/api/me").then(r => r.ok ? r.json() : null).catch(() => null);
    if (me) label.textContent = me.name + " (" + me.role + ")";
  });
})();
