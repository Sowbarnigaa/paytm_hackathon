/* Sign-in / sign-up page. Vanilla JS; all dynamic text is set with textContent. */
"use strict";
const $ = id => document.getElementById(id);
const show = name => {
  for (const f of ["fLogin", "fReg"]) $(f).hidden = f !== name;
  const reg = name === "fReg";
  $("tabLogin").className = "btn " + (reg ? "ghost" : "sec"); $("tabLogin").setAttribute("aria-selected", String(!reg));
  $("tabReg").className = "btn " + (reg ? "sec" : "ghost"); $("tabReg").setAttribute("aria-selected", String(reg));
  $("title").textContent = reg ? "Create your account" : "Sign in";
  say("");
};
const say = (t, bad) => { $("msg").textContent = t; $("msg").className = "msg sm " + (bad ? "bad" : "ok"); };

async function post(path, body) {
  const r = await fetch("/api/auth/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Something went wrong (" + r.status + ")");
  return j;
}
const busy = (form, on) => form.querySelectorAll("button").forEach(b => { b.disabled = on; });
const run = (form, fn) => async e => {
  e.preventDefault(); say(""); busy(form, true);
  try { await fn(new FormData(form)); } catch (err) { say(err.message, true); } finally { busy(form, false); }
};
const body = d => Object.fromEntries(d.entries());

function done(j) {
  localStorage.setItem("vc_token", j.token);
  localStorage.setItem("vc_uid", String(j.user.id));       // the main app keys its state by this id
  location.replace("/");
}

$("tabLogin").onclick = () => show("fLogin");
$("tabReg").onclick = () => show("fReg");

$("fLogin").addEventListener("submit", run($("fLogin"), async d => done(await post("login", body(d)))));
$("fReg").addEventListener("submit", run($("fReg"), async d => done(await post("register", body(d)))));

(async () => {
  const cfg = await fetch("/api/auth/config").then(r => r.json()).catch(() => ({ cities: [] }));
  $("rCity").replaceChildren(...cfg.cities.map(c => new Option(c, c)));
  if (cfg.demo) {
    $("demo").hidden = false;
    $("demo").textContent = "Demo mode: sign in as ravi@example.com (merchant) or murugan@example.com (wholesaler), password " + cfg.demo_password + ".";
  }
  if (localStorage.getItem("vc_token")) {                  // already signed in? go straight to the app
    const r = await fetch("/api/me", { headers: { Authorization: "Bearer " + localStorage.getItem("vc_token") } }).catch(() => null);
    if (r && r.ok) return location.replace("/");
    localStorage.removeItem("vc_token");
  }
})();
