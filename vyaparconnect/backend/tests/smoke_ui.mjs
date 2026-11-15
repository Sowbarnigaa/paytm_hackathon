// Signs in through the real login page in headless Chrome (CDP), opens every screen for a merchant and a wholesaler,
// and fails on any JS error or error card.   Run: node tests/smoke_ui.mjs
// Needs: server on :8000, Chrome started with --remote-debugging-port=9222, demo accounts (Demo@1234).
const base = "http://localhost:8000";
const target = await (await fetch("http://localhost:9222/json/new?about:blank", { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => (ws.onopen = r));
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push("console.error: " + d.params.args.map(a => a.value || a.description).join(" "));
  if (d.method === "Log.entryAdded" && d.params.entry.level === "error") errors.push("[" + (globalThis.__step||"?") + "] " + "log: " + d.params.entry.text + " " + (d.params.entry.url || ""));
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "eval failed: " + expr); return r.result.result.value; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const waitFor = async (expr, label, ms = 8000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(`!!(${expr})`)) return; await sleep(100); } throw new Error("timeout waiting for: " + label); };
const ok = (c, m) => { if (!c) throw new Error("ASSERT FAILED: " + m); console.log("  ok -", m); };
globalThis.__step="start"; const nav = async url => { await send("Page.navigate", { url }); await sleep(500); };

await send("Runtime.enable"); await send("Page.enable"); await send("Log.enable");

async function session(email, label) {
  globalThis.__step = label;
  console.log("\n" + label);
  await nav(base + "/login"); await ev("localStorage.clear()"); await nav(base + "/login");
  await waitFor("document.getElementById('lEmail')", "login form");
  await ev(`(()=>{document.getElementById('lEmail').value=${JSON.stringify(email)};document.getElementById('lPw').value='Demo@1234';document.getElementById('fLogin').requestSubmit()})()`);
  await waitFor("document.querySelector('#nav .ni')", "app shell after login");
  ok(await ev("localStorage.getItem('vc_token')") != null, "signed in, token stored");
  ok(await ev("document.getElementById('whoami')?.textContent.length > 0"), "signed-in name shown, Sign out available");
  const keys = await ev("[...document.querySelectorAll('#nav [data-v]')].map(b=>b.dataset.v)");
  ok(keys.length >= 4, "nav lists " + keys.length + " screens: " + keys.join(", "));
  for (const key of keys) {
    const name = key;
    await ev(`document.querySelector('#nav [data-v="${key}"]').click()`);
    await sleep(900);
    const bad = await ev("document.querySelector('#app .card.bad')?.innerText || ''");
    const len = await ev("document.querySelector('#app').innerText.trim().length");
    ok(!bad && len > 40, `${name} renders` + (bad ? " - ERROR: " + bad : ""));
  }
  return true;
}

console.log("(nav items are discovered from the page, so the test follows whichever frontend is deployed)");
await session("ravi@example.com", "Merchant (Ravi)");
await send("Page.navigate", { url: base + "/" }); await sleep(300);
await waitFor("document.querySelector('#nav .ni')", "reload keeps the session"); ok(true, "reload keeps the session");
globalThis.__step="sign-out"; await ev("[...document.querySelectorAll('button')].find(b=>b.textContent==='Sign out').click()");
await waitFor("location.pathname==='/login'", "sign out redirects to /login");
ok(true, "Sign out returns to the login page");
await session("murugan@example.com", "Wholesaler (Murugan)");

console.log("\nJS errors");
const real = errors.filter(e => !(e.startsWith("[sign-out]") && e.includes("401")));  // a poll in flight when the session is revoked
ok(real.length === 0, "no JS errors or failed requests" + (real.length ? ": " + real.join(" | ") : ""));
ws.close();
console.log("\nSMOKE PASSED");
