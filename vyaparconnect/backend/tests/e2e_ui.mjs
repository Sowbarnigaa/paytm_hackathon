// Drives the real UI in headless Chrome (CDP) through the hackathon demo path.
// Run: node tests/e2e_ui.mjs   (server on :8000 and Chrome on --remote-debugging-port=9222)
const base = "http://localhost:8000";
const targets = await (await fetch("http://localhost:9222/json/new?about:blank", { method: "PUT" })).json();
const ws = new WebSocket(targets.webSocketDebuggerUrl);
await new Promise(r => (ws.onopen = r));
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push("console.error: " + d.params.args.map(a => a.value || a.description).join(" "));
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "eval failed: " + expr); return r.result.result.value; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const waitFor = async (expr, label, ms = 6000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(`!!(${expr})`)) return; await sleep(100); } throw new Error("timeout waiting for: " + label); };
const text = () => ev("document.body.innerText");
const click = sel => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)throw new Error('missing '+${JSON.stringify(sel)});e.click();return true})()`);
const clickText = (sel, t) => ev(`(()=>{const e=[...document.querySelectorAll(${JSON.stringify(sel)})].find(x=>x.innerText.includes(${JSON.stringify(t)}));if(!e)throw new Error('missing '+${JSON.stringify(t)});e.click();return true})()`);
const setVal = (sel, v) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});e.value=${JSON.stringify(v)};e.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
const submit = sel => ev(`document.querySelector(${JSON.stringify(sel)}).requestSubmit()`);
const asUser = async name => { await ev(`(async()=>{const s=document.querySelector('#userSel');const o=[...s.options].find(o=>o.text.startsWith(${JSON.stringify(name + " ")}));s.value=o.value;s.dispatchEvent(new Event('change',{bubbles:true}))})()`); await sleep(500); };
const ok = (c, m) => { if (!c) throw new Error("ASSERT FAILED: " + m); console.log("  ok -", m); };
const step = n => console.log("\n" + n);

await send("Runtime.enable"); await send("Page.enable");
await send("Page.navigate", { url: base + "/" });
await ev("fetch('/api/reset',{method:'POST'}).then(r=>r.status)").catch(() => {});
await send("Page.navigate", { url: base + "/" });
await sleep(800);
await ev("localStorage.clear()"); await send("Page.navigate", { url: base + "/" });
await waitFor("document.body.innerText.includes('Namaste, Ravi')", "home");

step("1. Ravi sees AI recommendations, suggested group and stock alert");
let t = await text();
ok(t.includes("Erode Grocery Buyers") && t.includes("AI match 100%"), "recommended group with AI match score");
ok(t.includes("AI-suggested group"), "AI-suggested group card");
ok(t.includes("Sunflower Oil will run out"), "forecast stock-out alert");

step("2. Ravi requests to join the invite-only group");
await clickText("button.btn", "Request to join");
await waitFor("document.querySelector('.modal')", "join modal");
t = await text(); ok(t.includes("Request sent to group admin") && t.includes("KYC verified"), "AI membership check shown, request pending");
await click("[data-a=closeModal].btn");

step("3. Kumar (admin) approves with AI pre-check");
await asUser("Kumar"); await clickText(".tab", "Groups");
await waitFor("document.body.innerText.includes('Erode Grocery Buyers')", "groups tab");
await clickText("button", "Open group"); await waitFor("document.querySelector('.sub')", "group page");
await clickText(".sub button", "Requests");
await waitFor("document.body.innerText.includes('AI pre-check')", "request list");
t = await text(); ok(t.includes("Ravi's Grocery") && t.includes("Meena Kirana"), "both pending requests listed");
await ev(`document.querySelector('[data-a=decide][data-id="7"][data-v="1"]').click()`);
await waitFor(`!document.querySelector('[data-a=decide][data-id="7"]')`, "Ravi approved");
ok(true, "Ravi approved");

step("4. Murugan (wholesaler) posts a tiered rice deal");
await asUser("Murugan"); await clickText(".tab", "Groups");
await waitFor("document.body.innerText.includes('Erode Grocery Buyers')", "wholesaler groups");
await ev(`[...document.querySelectorAll('.card')].find(c=>c.innerText.includes('Erode Grocery Buyers')).querySelector('[data-a=openGroup]').click()`);
await waitFor("document.querySelector('.sub')", "group page w"); await clickText(".sub button", "Deals");
await waitFor("document.body.innerText.includes('Post pooled deal')", "deals tab");
await clickText("button", "Post pooled deal"); await waitFor("document.querySelector('#dp')", "deal form");
await setVal("#dp", "Rice");
await ev(`(()=>{const f=document.querySelector('form[data-f=newDeal]');f.q0.value=0;f.p0.value=55;f.q1.value=250;f.p1.value=52;f.q2.value=500;f.p2.value=49})()`);
await submit("form[data-f=newDeal]");
await waitFor("document.body.innerText.includes('Any qty: ₹55/kg')", "deal visible");
ok(true, "deal published with 3 tiers");

step("5. Five merchants commit; tier unlocks and savings split");
for (const [n, q] of [["Kumar", 100], ["Lakshmi", 100], ["Senthil", 100], ["Priya", 100], ["Ravi", 100]]) {
  await asUser(n); await clickText(".tab", "Groups");
  await waitFor("document.body.innerText.includes('Erode Grocery Buyers')", "g"); 
  await ev(`[...document.querySelectorAll('.card')].find(c=>c.innerText.includes('Erode Grocery Buyers')).querySelector('[data-a=openGroup]').click()`);
  await waitFor("document.querySelector('.sub')", "gp"); await clickText(".sub button", "Deals");
  await waitFor("document.querySelector('form[data-f=commit]')", "commit form");
  await ev(`document.querySelector('form[data-f=commit] input[name=qty]').value=${q}`);
  await submit("form[data-f=commit]"); await sleep(400);
}
t = await text();
ok(t.includes("500 kg") && t.includes("₹49/kg") && t.includes("Best tier unlocked"), "500 kg pooled at ₹49/kg");
ok(t.includes("₹3,000") && t.includes("₹600"), "₹3,000 group savings, ₹600 each");

step("6. Procurement agent");
await clickText(".tab", "AI Buyer"); await waitFor("document.querySelector('#ptext')", "ai tab");
await ev("document.querySelector('#ptext').value='50 kg arisi, 20 L oil, budget 6000'");
await submit("form[data-f=procure]"); await waitFor("document.body.innerText.includes('Top pick')", "agent results");
t = await text(); ok(t.includes("#1") && t.includes("Group pools you can join"), "ranked suppliers + group pool nudge");

step("7. Negotiator");
await clickText(".sub button", "Smart negotiator"); await waitFor("document.querySelector('form[data-f=negotiate]')", "neg form");
await submit("form[data-f=negotiate]"); await waitFor("document.querySelector('.bubble.system')", "transcript");
t = await text(); ok(/Deal at|No deal/.test(t), "agent transcript produced");

step("8. Reverse auction (Ravi posts, wholesalers bid, Ravi awards)");
await clickText(".tab", "Auctions"); await waitFor("document.querySelector('form[data-f=auction]')", "auction form");
await ev("document.querySelector('form[data-f=auction] [name=product]').value='Sugar'; document.querySelector('form[data-f=auction] [name=qty]').value=100");
await submit("form[data-f=auction]"); await waitFor("document.body.innerText.includes('Waiting for bids')", "auction posted");
for (const [n, p, d] of [["Murugan", 41, 1], ["Kaveri", 40, 3]]) {
  await asUser(n); await clickText(".tab", "Auctions"); await waitFor("document.querySelector('form[data-f=bid]')", "bid form for " + n);
  await ev(`(()=>{const f=document.querySelector('form[data-f=bid]');f.price.value=${p};f.delivery_days.value=${d}})()`);
  await submit("form[data-f=bid]"); await sleep(500);
}
await asUser("Ravi"); await clickText(".tab", "Auctions"); await waitFor("document.body.innerText.includes('AI score')", "ranked bids");
t = await text(); ok(t.includes("🏆 1"), "AI-ranked leaderboard");
await clickText("button", "Award"); await waitFor("document.body.innerText.includes('Closed')", "awarded");
ok(true, "award creates order and closes auction");

step("9. Checkout with loan + AutoPay, then EMI");
await clickText(".tab", "AI Buyer"); await waitFor("document.querySelector('.sub')", "ai sub-tabs"); await clickText(".sub button", "Procurement agent");
await waitFor("document.querySelector('form[data-f=procure]')", "ai");
await ev("document.querySelector('#ptext').value='100 kg rice'"); await submit("form[data-f=procure]");
await waitFor("document.querySelector('[data-a=checkout]')", "order btn"); await click("[data-a=checkout]");
await waitFor("document.querySelector('input[name=pay][value=loan]:not([disabled])')", "loan option");
await click("input[name=pay][value=loan]"); await waitFor("!document.querySelector('#loanbox').hidden", "loan box");
await submit("form[data-f=order]"); await waitFor("document.body.innerText.includes('UPI AutoPay on')", "order placed w/ loan");
ok(true, "loan-funded order with AutoPay mandate");
await click("[data-a=closeModal].btn"); await clickText(".tab", "Credit & EMI"); await waitFor("document.body.innerText.includes('My loans')", "credit");
await clickText("button", "Simulate auto-debit"); await waitFor("document.body.innerText.includes('1/3 paid') || /1\\/\\d+ paid/.test(document.body.innerText)", "emi paid");
ok(true, "auto-debit EMI processed");

step("10. Moderation blocks collusion post");
await asUser("Lakshmi"); await clickText(".tab", "Groups");
await waitFor("document.body.innerText.includes('Erode Grocery Buyers')", "g");
await ev(`[...document.querySelectorAll('.card')].find(c=>c.innerText.includes('Erode Grocery Buyers')).querySelector('[data-a=openGroup]').click()`);
await waitFor("document.querySelector('form[data-f=post]')", "post form");
await ev("document.querySelector('form[data-f=post] textarea').value=\"Let's all fix the price of rice at 60\"");
await submit("form[data-f=post]"); await waitFor("document.body.innerText.includes('Held by AI moderation')", "held");
ok(true, "collusion post held for admin review");

console.log("\nJS errors:", errors.length ? errors : "none");
ws.close(); process.exit(errors.length ? 1 : 0);
