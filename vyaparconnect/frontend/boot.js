/* Paytm VyaparConnect AI - Boot & Event Handlers */
"use strict";

async function init() {
  const [users, meta] = await Promise.all([
    api("/users"),
    api("/meta")
  ]);

  S.users = users;
  S.cities = meta.cities || [];
  S.categories = meta.categories || [];
  S.products = meta.products || [];

  const savedUid = Number(localStorage.getItem("vc_uid"));
  const userList = Array.isArray(S.users) ? S.users : [];
  const ravi = userList.find(u => u.name === "Ravi" || (u.shop && u.shop.includes("Ravi")));
  S.uid = userList.some(u => u.id === savedUid)
    ? savedUid
    : (ravi ? ravi.id : (userList.length > 0 ? userList[0].id : 7));

  const sel = $("#userSel");
  if (sel && userList.length > 0) {
    const merchants = userList.filter(u => u.role === "merchant");
    const wholesalers = userList.filter(u => u.role === "wholesaler");

    const opt = u => html`<option value="${u.id}">${u.name} - ${u.shop} (${u.city})</option>`;
    sel.innerHTML = html`
      <optgroup label="Merchants">${merchants.map(opt)}</optgroup>
      <optgroup label="Wholesalers">${wholesalers.map(opt)}</optgroup>
    `.s;
    sel.value = S.uid;

    sel.addEventListener("change", async e => {
      await switchUser(Number(e.target.value));
    });
  }

  await act(loadMe);
  await render();
}

// ------------------------------------------------------------------ Event Delegation
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-a]");
  if (!btn) return;
  const a = btn.dataset.a;

  if (a === "closeModal") {
    closeModal();
    return;
  }

  if (a === "toggleNav") {
    const nav = $("#nav");
    if (nav) nav.classList.toggle("open");
    return;
  }

  if (a === "gotoNotifs") {
    S.tab = "notifs";
    await render();
    return;
  }

  if (a === "tab") {
    S.tab = btn.dataset.v || "home";
    S.gid = null;
    if (btn.dataset.sub) S.aiTab = btn.dataset.sub;
    await render();
    return;
  }

  if (a === "gtab") {
    S.gtab = btn.dataset.v || "feed";
    await render();
    return;
  }

  if (a === "aiTab") {
    S.aiTab = btn.dataset.v || "proc";
    await render();
    return;
  }

  if (a === "openGroup") {
    S.gid = Number(btn.dataset.id);
    S.tab = "groups";
    S.gtab = "feed";
    await render();
    return;
  }

  if (a === "backToGroups") {
    S.gid = null;
    S.tab = "groups";
    await render();
    return;
  }

  if (a === "precheckJoin") {
    const gid = Number(btn.dataset.id);
    await act(async () => {
      const res = await api(`/groups/${gid}/join`, "POST", { message: "Looking forward to buying together" });
      modal(html`
        <h3>Join Request Sent</h3>
        <p class="mt"><b>Request sent to group admin</b></p>
        <p class="ok mt">✓ KYC verified</p>
        <p class="muted sm">AI membership check completed. Admin will review your profile.</p>
        <div class="mt">
          <button class="btn sec" data-a="closeModal">Done</button>
        </div>
      `);
      await render(true);
    });
    return;
  }

  if (a === "joinDirect") {
    const gid = Number(btn.dataset.id);
    await act(async () => {
      const res = await api(`/groups/${gid}/join`, "POST");
      toast(res.message || "Joined group!");
      await loadMe();
      await render();
    });
    return;
  }

  if (a === "leaveGroup") {
    const gid = Number(btn.dataset.id);
    if (!confirm("Are you sure you want to leave this group?")) return;
    await act(async () => {
      await api(`/groups/${gid}/leave`, "POST");
      toast("Left group");
      S.gid = null;
      await loadMe();
      await render();
    });
    return;
  }

  if (a === "decide") {
    const gid = Number(btn.dataset.gid || S.gid);
    const userId = Number(btn.dataset.id);
    const approve = Boolean(Number(btn.dataset.v));
    await act(async () => {
      await api(`/groups/${gid}/members/${userId}/decision`, "POST", { approve });
      toast(approve ? "Merchant approved" : "Request rejected");
      await render();
    });
    return;
  }

  if (a === "reviewPost") {
    const gid = Number(btn.dataset.gid || S.gid);
    const pid = Number(btn.dataset.pid);
    const action = btn.dataset.act;
    await act(async () => {
      await api(`/groups/${gid}/posts/${pid}/review`, "POST", { action });
      toast(`Post ${action}d`);
      await render();
    });
    return;
  }

  if (a === "openNewDealModal") {
    const gid = Number(btn.dataset.gid || S.gid);
    modal(html`
      <h3>Post Pooled Deal for Group</h3>
      <form data-f="newDeal" data-gid="${gid}" class="form col mt">
        <div class="field">
          <label for="dp">Product</label>
          <select id="dp" name="product" required>
            <option value="Rice" selected>Rice</option>
            <option value="Sugar">Sugar</option>
            <option value="Sunflower Oil">Sunflower Oil</option>
            <option value="Toor Dal">Toor Dal</option>
            <option value="Wheat Flour">Wheat Flour</option>
          </select>
        </div>
        <div class="field">
          <label>Deal Kind</label>
          <select name="kind">
            <option value="bulk">Bulk deal</option>
            <option value="clearance">Clearance</option>
            <option value="seasonal">Seasonal</option>
          </select>
        </div>
        <div class="field">
          <label>Tier 1: Min Qty & Price</label>
          <div class="row">
            <input name="q0" type="number" value="0" placeholder="0 kg" required style="width:100px">
            <input name="p0" type="number" step="0.5" value="55" placeholder="₹/kg" required style="width:100px">
          </div>
        </div>
        <div class="field">
          <label>Tier 2: Min Qty & Price</label>
          <div class="row">
            <input name="q1" type="number" value="250" placeholder="250 kg" required style="width:100px">
            <input name="p1" type="number" step="0.5" value="52" placeholder="₹/kg" required style="width:100px">
          </div>
        </div>
        <div class="field">
          <label>Tier 3: Min Qty & Price</label>
          <div class="row">
            <input name="q2" type="number" value="500" placeholder="500 kg" required style="width:100px">
            <input name="p2" type="number" step="0.5" value="49" placeholder="₹/kg" required style="width:100px">
          </div>
        </div>
        <input name="qty_limit" type="hidden" value="2000">
        <button class="btn cyan mt">Publish Deal to Group</button>
      </form>
    `);
    return;
  }

  if (a === "closePool") {
    const pid = Number(btn.dataset.id);
    await act(async () => {
      const res = await api(`/pools/${pid}/close`, "POST");
      toast(`Pool closed! Created ${res.order_ids.length} orders at ₹${res.final_price}/unit.`);
      await render();
    });
    return;
  }

  if (a === "reorder") {
    S.tab = "ai";
    S.aiTab = "proc";
    S.procText = `${btn.dataset.q || 50} ${btn.dataset.u || "kg"} ${btn.dataset.p}`;
    await render();
    const txtEl = $("#ptext");
    if (txtEl) {
      txtEl.value = S.procText;
      const form = txtEl.closest("form");
      if (form) form.requestSubmit();
    }
    return;
  }

  if (a === "speechToText") {
    if (!SpeechRec) return;
    const sel = $("#voiceLang");
    const lang = (sel && sel.value) || S.voiceLang || "en-IN";
    S.voiceLang = lang;
    const label = { "en-IN": "English", "ta-IN": "Tamil", "hi-IN": "Hindi" }[lang] || lang;
    const rec = new SpeechRec();
    rec.lang = lang;           // the recogniser only transcribes one language per session, so the user picks it
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = e => {
      const transcript = e.results[0][0].transcript;
      const txt = $("#ptext");
      if (txt) {
        txt.value = transcript;
        S.procText = transcript;
        toast(`Voice input (${label}): "${transcript}"`);
      }
    };
    rec.onerror = ev => toast(ev && ev.error === "not-allowed" ? "Microphone permission denied" : "Speech recognition error", true);
    rec.start();
    toast(`Listening in ${label}...`);
    return;
  }

  if (a === "addDemandRow") {
    const rows = $("#demRows");
    if (rows) rows.insertAdjacentHTML("beforeend", demandRowHtml(true).s);
    return;
  }

  if (a === "removeDemandRow") {
    const row = btn.closest(".dem-row");
    if (row) row.remove();
    return;
  }

  if (a === "awardDemand") {
    const did = Number(btn.dataset.did);
    const bidId = Number(btn.dataset.bid);
    await act(async () => {
      const res = await api(`/demands/${did}/close`, "POST", { bid_id: bidId });
      toast(`Awarded! Order #${res.order_id} created.`);
      await render();
    });
    return;
  }

  if (a === "acceptNeg") {
    const nid = Number(btn.dataset.id);
    await act(async () => {
      const res = await api(`/ai/negotiate/${nid}/accept`, "POST");
      toast(`Deal accepted! Order #${res.order_id} created.`);
      S.tab = "orders";
      await render();
    });
    return;
  }

  if (a === "checkout") {
    const wId = Number(btn.dataset.w);
    let lines = [];
    try {
      lines = JSON.parse(btn.dataset.lines || "[]");
    } catch {
      lines = [{ product: "Rice", qty: 100 }];
    }
    S.checkoutWholesaler = wId;
    S.checkoutLines = lines;

    const offer = await api("/credit/offer");
    const eligibleLoan = offer.eligible;

    modal(html`
      <h3>Checkout & Order Confirmation</h3>
      <form data-f="order" class="form col mt">
        <input type="hidden" name="wholesaler_id" value="${wId}">
        <table>
          <thead><tr><th>Item</th><th>Qty</th><th>Goods Price</th></tr></thead>
          <tbody>
            ${lines.map(ln => html`
              <tr>
                <td><b>${ln.product}</b></td>
                <td>${num(ln.qty)} ${ln.unit || "kg"}</td>
                <td>${inr(ln.cost || (ln.qty * (ln.unit_price || 50)))}</td>
              </tr>
            `)}
          </tbody>
        </table>

        <div class="mt">
          <label><b>Choose Payment Method:</b></label>
          <label class="opt">
            <input type="radio" name="pay" value="full" checked>
            <span class="t">Pay in Full (Single settlement via Paytm Gateway)</span>
          </label>
          <label class="opt">
            <input type="radio" name="pay" value="parts">
            <span class="t">Pay in Parts (2-4 instalments direct to wholesaler)</span>
          </label>
          <label class="opt">
            <input type="radio" name="pay" value="loan" ${eligibleLoan ? "" : "disabled"}>
            <span class="t">Pay with Paytm loan (Instant EMI financing)</span>
            ${!eligibleLoan ? html`<div class="sm bad">Credit line not available</div>` : ""}
          </label>
        </div>

        <div id="loanbox" class="card tint mt" hidden>
          <h4>Paytm Business Loan & EMI Plan</h4>
          <p class="sm muted">Available Credit: <b>${inr(offer.available)}</b> · Rate: <b>${offer.rate}% p.a.</b></p>
          <div class="field mt">
            <label for="emiTenure">Repayment Tenure</label>
            <select id="emiTenure" name="tenure">
              ${(offer.plans || []).map(p => html`
                <option value="${p.tenure}">${p.tenure} months - ${inr(p.emi)}/month (Total ${inr(p.total)})</option>
              `)}
            </select>
          </div>
          <div class="mt">
            <label><input type="checkbox" name="autopay" checked> Enable UPI AutoPay on Paytm for hassle-free deductions</label>
          </div>
        </div>

        <button class="btn cyan mt">Place Order</button>
      </form>
    `);

    const loanRadio = $("#modal input[value=loan]");
    const allRadios = $$("#modal input[name=pay]");
    allRadios.forEach(r => {
      r.addEventListener("change", () => {
        const box = $("#loanbox");
        if (box) box.hidden = !loanRadio.checked;
      });
    });
    return;
  }

  if (a === "openQuoteModal") {
    const oid = Number(btn.dataset.id);
    modal(html`
      <h3>Quote Delivery Charge for Order #${oid}</h3>
      <form data-f="quote" data-id="${oid}" class="form col mt">
        <div class="field">
          <label for="delCharge">Delivery Charge (₹)</label>
          <input id="delCharge" name="delivery_charge" type="number" min="0" value="250" required>
        </div>
        <div class="field">
          <label for="etaDays">Estimated Arrival (Days)</label>
          <input id="etaDays" name="eta_days" type="number" min="1" max="14" value="2" required>
        </div>
        <div class="field">
          <label for="delNote">Delivery Note</label>
          <input id="delNote" name="note" placeholder="Direct tempo delivery, unloaded at shop...">
        </div>
        <button class="btn cyan mt">Send Delivery Quote to Buyer</button>
      </form>
    `);
    return;
  }

  if (a === "openPayModal") {
    const oid = Number(btn.dataset.id);
    const opts = await api(`/orders/${oid}/pay-options`);
    modal(html`
      <h3>Choose Payment Option for Order #${oid}</h3>
      <p class="sm muted">Goods: ${inr(opts.items_total)} + Delivery: ${inr(opts.delivery_charge)} = <b>Total: ${inr(opts.total)}</b></p>
      <div class="mt">
        <div class="card mb">
          <div class="spread">
            <div><b>Pay in Full</b><div class="sm muted">Instant one-shot settlement</div></div>
            <button class="btn sm cyan" data-a="startPayment" data-id="${oid}" data-mode="full">Pay ${inr(opts.total)}</button>
          </div>
        </div>
        ${opts.parts && opts.parts.length > 0 ? html`
          <div class="card mb">
            <b>Pay in Parts (Instalments)</b>
            <div class="mt row">
              ${opts.parts.map(p => html`
                <button class="btn sm sec" data-a="startPayment" data-id="${oid}" data-mode="parts" data-parts="${p.parts}">
                  ${p.parts} parts (${inr(p.first)} now)
                </button>
              `)}
            </div>
          </div>
        ` : ""}
        ${opts.loan && opts.loan.eligible ? html`
          <div class="card">
            <b>Pay with Paytm Loan</b>
            <div class="sm muted">Available: ${inr(opts.loan.available)} · Rate: ${opts.loan.rate}%</div>
            <div class="mt row">
              ${(opts.loan.plans || []).map(p => html`
                <button class="btn sm cyan" data-a="startPayment" data-id="${oid}" data-mode="loan" data-tenure="${p.tenure}">
                  ${p.tenure} mo @ ${inr(p.emi)}/mo
                </button>
              `)}
            </div>
          </div>
        ` : ""}
      </div>
    `);
    return;
  }

  if (a === "startPayment") {
    const oid = Number(btn.dataset.id);
    const mode = btn.dataset.mode;
    const parts = btn.dataset.parts;
    const tenure = btn.dataset.tenure;
    await act(async () => {
      const intent = await api(`/orders/${oid}/pay`, "POST", { mode, parts, tenure });
      closeModal();
      openGatewayModal(intent.txn_id);
    });
    return;
  }

  if (a === "shipOrder") {
    const oid = Number(btn.dataset.id);
    await act(async () => {
      await api(`/orders/${oid}/ship`, "POST");
      toast("Order marked as shipped");
      await render();
    });
    return;
  }

  if (a === "deliverOrder") {
    const oid = Number(btn.dataset.id);
    await act(async () => {
      await api(`/orders/${oid}/deliver`, "POST");
      toast("Delivery confirmed! Products added to your shelf inventory.");
      await render();
    });
    return;
  }

  if (a === "openReviewModal") {
    const oid = Number(btn.dataset.id);
    modal(html`
      <h3>Write Review for Order #${oid}</h3>
      <form data-f="review" data-id="${oid}" class="form col mt">
        <div class="field">
          <label>Rating (1 to 5 Stars)</label>
          <select name="rating">
            <option value="5">⭐⭐⭐⭐⭐ 5 - Excellent</option>
            <option value="4">⭐⭐⭐⭐ 4 - Good</option>
            <option value="3">⭐⭐⭐ 3 - Average</option>
            <option value="2">⭐⭐ 2 - Below Average</option>
            <option value="1">⭐ 1 - Poor</option>
          </select>
        </div>
        <div class="field">
          <label for="revComment">Comment</label>
          <textarea id="revComment" name="comment" placeholder="Timely delivery, good packaging, honest pricing..."></textarea>
        </div>
        <button class="btn cyan mt">Submit Review</button>
      </form>
    `);
    return;
  }

  if (a === "openCibilModal") {
    modal(html`
      <h3>Simulated CIBIL Credit Check</h3>
      <p class="sm muted">Check your bureau credit eligibility instantly with OTP verification.</p>
      <form data-f="cibilCheck" class="form col mt">
        <label><input type="checkbox" name="consent" checked required> I give consent to Paytm for Business to fetch my credit score</label>
        <div class="field mt">
          <label for="cibilOtp">Enter OTP sent to your registered mobile (Demo OTP: <b>123456</b>)</label>
          <input id="cibilOtp" name="otp" value="123456" required>
        </div>
        <button class="btn cyan mt">Verify & View Score</button>
      </form>
    `);
    return;
  }

  if (a === "toggleAutopay") {
    const lid = Number(btn.dataset.id);
    const on = Boolean(Number(btn.dataset.on));
    await act(async () => {
      await api(`/loans/${lid}/autopay`, "POST", { on });
      toast(on ? "UPI AutoPay activated" : "UPI AutoPay paused");
      await render();
    });
    return;
  }

  if (a === "payEmi") {
    const lid = Number(btn.dataset.id);
    await act(async () => {
      const res = await api(`/loans/${lid}/pay`, "POST", { mode: "autopay" });
      toast(`Simulated auto-debit successful! ${res.paid_emis}/${res.tenure} EMIs paid.`);
      await render();
    });
    return;
  }

  if (a === "openNearbyMerchantsModal") {
    const gid = btn.dataset.gid ? Number(btn.dataset.gid) : null;
    await act(async () => {
      const list = await api("/merchants/nearby");
      modal(nearbyMerchantsModalContent(list, gid), true);
    });
    return;
  }

  if (a === "selectAllMerchants") {
    const cbs = $$("#merchantPopupList input[type=checkbox]");
    const allChecked = cbs.length > 0 && cbs.every(cb => cb.checked);
    cbs.forEach(cb => { cb.checked = !allChecked; });
    btn.textContent = allChecked ? "Select All" : "Deselect All";
    return;
  }

  if (a === "inviteSingleMerchant") {
    const gid = Number(btn.dataset.gid);
    const uid = Number(btn.dataset.uid);
    const name = btn.dataset.name || "Merchant";
    await act(async () => {
      await api(`/groups/${gid}/invite`, "POST", { user_id: uid });
      toast(`Invitation sent to ${name}!`);
      btn.disabled = true;
      btn.textContent = "Invited ✓";
    });
    return;
  }

  if (a === "openCollectiveAuctionModal") {
    const gid = Number(btn.dataset.gid || S.gid);
    await act(async () => {
      const g = await api(`/groups/${gid}`);
      const members = g.members || [];
      modal(html`
        <h3>🤖 AI Group Collective Reverse Auction</h3>
        <p class="sm muted">Post a pooled requirement on behalf of <b>${g.name}</b> members to regional wholesalers for competitive reverse bidding.</p>
        <form data-f="collectiveAuction" data-gid="${gid}" class="form col mt">
          <div class="field">
            <label for="colProd">Product to Pool</label>
            <select id="colProd" name="product" required>
              <option value="Rice" selected>Rice</option>
              <option value="Sugar">Sugar</option>
              <option value="Sunflower Oil">Sunflower Oil</option>
              <option value="Toor Dal">Toor Dal</option>
              <option value="Wheat Flour">Wheat Flour</option>
              <option value="Tea Powder">Tea Powder</option>
            </select>
          </div>
          <div class="field">
            <label for="colBudget">Target Budget (₹ optional)</label>
            <input id="colBudget" name="budget" type="number" placeholder="e.g. 20000">
          </div>
          <div class="field">
            <label for="colNote">Note for Wholesalers</label>
            <input id="colNote" name="note" placeholder="Quality grade, preferred delivery...">
          </div>

          <div class="mt">
            <label><b>Participating Group Merchants & Quantities:</b></label>
            <table class="mt">
              <thead><tr><th>Include</th><th>Shop</th><th>City</th><th>Quantity</th></tr></thead>
              <tbody>
                ${members.map(m => html`
                  <tr>
                    <td><input type="checkbox" name="part_uids" value="${m.id}" data-shop="${m.shop}" checked onchange="updateColTotal()"></td>
                    <td><b>${m.shop}</b><br><small class="muted">${m.name}</small></td>
                    <td>${m.city}</td>
                    <td>
                      <input type="number" name="qty_${m.id}" min="1" step="any" value="${m.id === S.uid ? "100" : "50"}" style="width:90px" oninput="updateColTotal()">
                    </td>
                  </tr>
                `)}
              </tbody>
            </table>
            <div class="mt sm ok"><b>Total Pooled Volume: <span id="colTot">0</span> units</b></div>
          </div>

          <button class="btn ok mt lg">🤖 AI Launch Collective Auction to Wholesalers</button>
        </form>
      `, true);
      if (typeof window.updateColTotal === "function") window.updateColTotal();
    });
    return;
  }

  if (a === "openLogUsageModal") {
    const prod = btn.dataset.p || "Rice";
    const unit = btn.dataset.u || "kg";
    modal(html`
      <h3>Log Daily Sales / Usage: ${prod}</h3>
      <p class="sm muted">Logging sales deductions immediately feeds the predictive exponential smoothing forecast.</p>
      <form data-f="logUsage" class="form col mt">
        <input type="hidden" name="product" value="${prod}">
        <div class="field">
          <label for="uQty">Quantity Sold / Consumed (${unit})</label>
          <input id="uQty" name="qty" type="number" min="0.1" step="any" value="5" required>
        </div>
        <button class="btn cyan mt">Save Usage & Deduct Shelf Stock</button>
      </form>
    `);
    return;
  }

  if (a === "openSetStockModal") {
    const prod = btn.dataset.p || "";
    const currentStock = btn.dataset.s || "50";
    modal(html`
      <h3>${prod ? `Update Shelf Stock: ${prod}` : "Track New Product on Shelf"}</h3>
      <form data-f="setStock" class="form col mt">
        <div class="field">
          <label for="sProd">Product</label>
          ${prod ? html`
            <input id="sProd" name="product" value="${prod}" readonly style="background:#f0f6ff">
          ` : html`
            <select id="sProd" name="product" required>
              ${S.products.map(p => html`<option value="${p.name}">${p.name} (${p.unit})</option>`)}
            </select>
          `}
        </div>
        <div class="field">
          <label for="sQty">Current In-Stock Quantity</label>
          <input id="sQty" name="stock" type="number" min="0" step="any" value="${currentStock}" required>
        </div>
        <button class="btn cyan mt">Save Shelf Stock</button>
      </form>
    `);
    return;
  }

  if (a === "openEditInventoryModal") {
    const prod = btn.dataset.p;
    const price = btn.dataset.price;
    const stock = btn.dataset.stock;
    const floor = btn.dataset.floor;
    modal(html`
      <h3>Edit Wholesaler Catalog: ${prod}</h3>
      <form data-f="editInventory" class="form col mt">
        <input type="hidden" name="product" value="${prod}">
        <div class="field">
          <label for="invStock">Stock Quantity</label>
          <input id="invStock" name="stock_qty" type="number" min="0" step="any" value="${stock}" required>
        </div>
        <div class="field">
          <label for="invPrice">List Price (₹)</label>
          <input id="invPrice" name="price" type="number" min="1" step="0.5" value="${price}" required>
        </div>
        <div class="field">
          <label for="invFloor">Protected Floor Price (₹ - Private for AI negotiator)</label>
          <input id="invFloor" name="floor_price" type="number" min="1" step="0.5" value="${floor}" required>
        </div>
        <button class="btn cyan mt">Save Catalog Item</button>
      </form>
    `);
    return;
  }

  if (a === "openBuySaleModal") {
    const sid = Number(btn.dataset.id);
    const prod = btn.dataset.p || "";
    modal(html`
      <h3>Buy Directly: ${prod}</h3>
      <p class="sm muted">Purchase directly from this wholesaler's tiered sale. Price is determined by your chosen quantity tier.</p>
      <form data-f="buySale" data-sid="${sid}" class="form col mt">
        <div class="field">
          <label for="buyQty">Purchase Quantity</label>
          <input id="buyQty" name="qty" type="number" min="1" step="any" value="50" required>
        </div>
        <button class="btn cyan mt">Place Direct Order</button>
      </form>
    `);
    return;
  }

  if (a === "openStartPoolModal") {
    const sid = Number(btn.dataset.id);
    const prod = btn.dataset.p || "";
    await act(async () => {
      const gs = await api("/groups");
      const mine = gs.filter(g => g.my_status === "active");
      if (mine.length === 0) {
        toast("You must join or create a group first to start a group pool!", true);
        return;
      }
      modal(html`
        <h3>Start Group Pool: ${prod}</h3>
        <p class="sm muted">Select one of your groups to launch a pooled group purchase. Other group members can join to unlock lower tiers!</p>
        <form data-f="startPool" data-sid="${sid}" class="form col mt">
          <div class="field">
            <label for="poolGroup">Select Group</label>
            <select id="poolGroup" name="group_id" required>
              ${mine.map(g => html`<option value="${g.id}">${g.name}</option>`)}
            </select>
          </div>
          <button class="btn cyan mt">Start Pool</button>
        </form>
      `);
    });
    return;
  }

  if (a === "openNewGroupModal") {
    modal(html`
      <h3>Create New Buying Group</h3>
      <form data-f="newGroup" class="form col mt">
        <div class="field">
          <label for="gName">Group Name</label>
          <input id="gName" name="name" required placeholder="e.g. Erode Grocery Buyers">
        </div>
        <div class="field">
          <label for="gDesc">Description</label>
          <input id="gDesc" name="description" placeholder="Local merchants pooling bulk orders">
        </div>
        <div class="field">
          <label for="gCat">Category</label>
          <select id="gCat" name="category">
            <option value="grocery">Grocery</option>
            <option value="fmcg">FMCG</option>
            <option value="both">Both</option>
          </select>
        </div>
        <div class="field">
          <label for="gCity">City</label>
          <select id="gCity" name="city">
            ${S.cities.map(c => html`<option value="${c}">${c}</option>`)}
          </select>
        </div>
        <div class="field">
          <label for="gType">Membership Type</label>
          <select id="gType" name="type">
            <option value="invite">Invite / Admin Approval (Recommended)</option>
            <option value="public">Open (AI Auto-Approve)</option>
          </select>
        </div>
        <button class="btn cyan mt">Create Group & Invite Merchants</button>
      </form>
    `);
    return;
  }

  if (a === "formSuggested") {
    const name = btn.dataset.name;
    const ids = (btn.dataset.ids || "").split(",").map(Number).filter(Boolean);
    await act(async () => {
      const g = await api("/groups", "POST", {
        name,
        description: "AI-formed collaborative group",
        category: S.me.category,
        city: S.me.city,
        type: "invite"
      });
      for (const uid of ids) {
        await api(`/groups/${g.id}/invite`, "POST", { user_id: uid }).catch(() => {});
      }
      toast(`Group '${name}' created and invitations sent!`);
      S.gid = g.id;
      S.tab = "groups";
      await render();
    });
    return;
  }

  if (a === "reset") {
    if (!confirm("Reset all demo data to initial factory state?")) return;
    await act(async () => {
      await fetch("/api/reset", { method: "POST" });
      localStorage.clear();
      toast("Demo data reset");
      await init();
    });
    return;
  }

  if (a === "markAllNotificationsRead") {
    await act(async () => {
      await api("/notifications/read", "POST", {});
      toast("All notifications marked as read");
      await loadMe();
      await render();
    });
    return;
  }
});

function openGatewayModal(txnId) {
  modal(html`
    <div class="gw">
      <div class="gw-h">
        <div class="row">
          <span class="logo"><b>pay</b><i>tm</i></span>
          <span class="b" style="margin-left:8px">Payment Gateway Simulation</span>
        </div>
        <span class="badge sm ok">100% Secure</span>
      </div>
      <div class="gw-b">
        <p class="muted sm">Simulating Paytm Checkout for Transaction: <b>${txnId}</b></p>
        <div class="mt">
          <label class="opt"><input type="radio" name="gw_method" value="upi" checked> Paytm UPI / QR</label>
          <label class="opt"><input type="radio" name="gw_method" value="card"> Debit / Credit Card</label>
          <label class="opt"><input type="radio" name="gw_method" value="netbanking"> Netbanking</label>
          <label class="opt"><input type="radio" name="gw_method" value="wallet"> Paytm Wallet</label>
        </div>
        <div class="mt">
          <button class="btn ok" data-a="completeGateway" data-txn="${txnId}">Pay & Confirm Order</button>
        </div>
      </div>
    </div>
  `);
}

document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-a=completeGateway]");
  if (!btn) return;
  const txnId = btn.dataset.txn;
  const method = ($("input[name=gw_method]:checked") || {}).value || "upi";
  await act(async () => {
    await api(`/gateway/${txnId}/complete`, "POST", { method, success: true, autopay: true });
    toast("Payment settled! Wholesaler notified to ship order.");
    closeModal();
    S.tab = "orders";
    await render();
  });
});

// ------------------------------------------------------------------ Form Submissions
document.addEventListener("submit", async e => {
  const form = e.target.closest("[data-f]");
  if (!form) return;
  e.preventDefault();
  const f = form.dataset.f;

  if (f === "topSearch") {
    const q = (form.q.value || "").trim();
    if (q) {
      S.tab = "merchants";
      await render();
    }
    return;
  }

  if (f === "procure") {
    const text = (form.text.value || "").trim();
    const sort = form.sort ? form.sort.value : "best";
    S.procText = text;
    await act(async () => {
      S.proc = await api("/ai/procure", "POST", { text, sort });
      await render();
    });
    return;
  }

  if (f === "negotiate") {
    if (S.negBusy) return;
    const wholesaler_id = Number(form.wholesaler_id.value);
    const product = form.product.value;
    const qty = Number(form.qty.value);
    const max_price = Number(form.max_price.value);
    S.negForm = { wholesaler_id, product, qty, max_price };
    S.negBusy = true;
    try {
      // Server runs the Faratin negotiation against the live catalog price, floor and stock, then we replay it round by round.
      S.neg = await api("/ai/negotiate", "POST", { wholesaler_id, product, qty, max_price });
      const total = (S.neg.transcript || []).length;
      S.negShown = 0;
      await render();
      for (let i = 1; i <= total; i++) {
        await new Promise(r => setTimeout(r, 900));
        if (S.tab !== "ai" || S.aiTab !== "neg") break;
        S.negShown = i;
        await render(true);
      }
    } catch (err) {
      toast(err.message || String(err), true);
    } finally {
      S.negBusy = false;
      S.negShown = null;
      if (S.tab === "ai" && S.aiTab === "neg") await render(true);
    }
    return;
  }

  if (f === "newDeal") {
    const gid = Number(form.dataset.gid || S.gid);
    const product = form.product.value;
    const kind = form.kind.value;
    const q0 = Number(form.q0.value), p0 = Number(form.p0.value);
    const q1 = Number(form.q1.value), p1 = Number(form.p1.value);
    const q2 = Number(form.q2.value), p2 = Number(form.p2.value);
    const tiers = [{ min_qty: q0, price: p0 }, { min_qty: q1, price: p1 }, { min_qty: q2, price: p2 }];
    await act(async () => {
      const sale = await api("/sales", "POST", { product, kind, tiers, qty_limit: 2000, days: 7 });
      if (gid) {
        await api(`/sales/${sale.id}/pools`, "POST", { group_id: gid });
      }
      toast("Pooled deal created for group!");
      closeModal();
      await render();
    });
    return;
  }

  if (f === "commit") {
    const pid = Number(form.dataset.id);
    const qty = Number(form.qty.value);
    await act(async () => {
      await api(`/pools/${pid}/commit`, "POST", { qty });
      toast("Committed to pool!");
      await render();
    });
    return;
  }

  if (f === "auction") {
    const note = form.note ? form.note.value : "";
    const items = [...form.querySelectorAll(".dem-row")].map(row => ({
      product: row.querySelector("[name=product]").value,
      qty: Number(row.querySelector("[name=qty]").value),
      budget: row.querySelector("[name=budget]").value ? Number(row.querySelector("[name=budget]").value) : null
    }));
    if (items.length === 0) { toast("Add at least one product", true); return; }
    const seen = new Set();
    for (const it of items) {
      if (seen.has(it.product)) { toast(`${it.product} is listed twice - combine it into one row`, true); return; }
      seen.add(it.product);
    }
    await act(async () => {
      for (const it of items) {
        await api("/demands", "POST", { product: it.product, qty: it.qty, budget: it.budget, note });
      }
      toast(items.length > 1 ? `${items.length} demands posted to regional wholesalers!` : "Demand posted to regional wholesalers!");
      await render();
    });
    return;
  }

  if (f === "bid") {
    const did = Number(form.dataset.did);
    const price = Number(form.price.value);
    const delivery_days = Number(form.delivery_days.value);
    await act(async () => {
      await api(`/demands/${did}/bids`, "POST", { price, delivery_days });
      toast("Bid submitted!");
      await render();
    });
    return;
  }

  if (f === "post") {
    const body = form.body.value;
    const gid = S.gid;
    await act(async () => {
      const res = await api(`/groups/${gid}/posts`, "POST", { body });
      if (res.status === "held") {
        toast("Held by AI moderation for anti-competitive keyword screening", true);
      } else {
        toast("Posted to group!");
      }
      form.body.value = "";
      await render();
    });
    return;
  }

  if (f === "order") {
    const wId = Number(form.wholesaler_id.value);
    const payMode = (form.querySelector("input[name=pay]:checked") || {}).value || "full";
    const tenure = form.tenure ? Number(form.tenure.value) : 3;
    const autopay = form.autopay ? form.autopay.checked : true;
    const lines = S.checkoutLines || [{ product: "Rice", qty: 100 }];

    await act(async () => {
      const res = await api("/orders", "POST", { wholesaler_id: wId, lines });
      if (payMode === "loan") {
        const total = res.items_total;
        await api("/credit/cibil", "POST", { consent: true, otp: "123456" }).catch(() => {});
        await api("/loans", "POST", { amount: total, tenure, autopay, order_ids: [res.order_id] }).catch(() => {});
        modal(html`
          <h3>Order Placed with Paytm Loan Financing!</h3>
          <p class="mt">Order #${res.order_id} placed. <b>UPI AutoPay on</b> for ₹${Math.round(total / tenure)}/month.</p>
          <div class="card tint mt">
            <p class="sm ok">✓ Wholesaler funded in full<br>✓ EMI autopay mandate active on your account</p>
          </div>
          <div class="mt">
            <button class="btn ok" data-a="closeModal">Done</button>
          </div>
        `);
      } else {
        toast(`Order #${res.order_id} placed! Awaiting wholesaler delivery quote.`);
        closeModal();
      }
      S.tab = "orders";
      await render();
    });
    return;
  }

  if (f === "quote") {
    const oid = Number(form.dataset.id);
    const delivery_charge = Number(form.delivery_charge.value);
    const eta_days = Number(form.eta_days.value);
    const note = form.note.value;
    await act(async () => {
      await api(`/orders/${oid}/quote`, "POST", { delivery_charge, eta_days, note });
      toast("Delivery quote sent to merchant");
      closeModal();
      await render();
    });
    return;
  }

  if (f === "review") {
    const oid = Number(form.dataset.id);
    const rating = Number(form.rating.value);
    const comment = form.comment.value;
    await act(async () => {
      await api(`/orders/${oid}/review`, "POST", { rating, comment });
      toast("Review submitted!");
      closeModal();
      await render();
    });
    return;
  }

  if (f === "cibilCheck") {
    const consent = form.consent.checked;
    const otp = form.otp.value;
    await act(async () => {
      const res = await api("/credit/cibil", "POST", { consent, otp });
      toast(`CIBIL Score verified: ${res.score} (${res.band})`);
      closeModal();
      await render();
    });
    return;
  }

  if (f === "newGroup") {
    const name = form.name.value;
    const description = form.description.value;
    const category = form.category.value;
    const city = form.city.value;
    const type = form.type.value;
    await act(async () => {
      const res = await api("/groups", "POST", { name, description, category, city, type });
      toast("Group created! Now invite nearby merchants to join.");
      S.gid = res.id;
      S.tab = "groups";
      const list = await api("/merchants/nearby");
      modal(nearbyMerchantsModalContent(list, res.id), true);
      await render(true);
    });
    return;
  }

  if (f === "combineMerchants") {
    const gid = form.dataset.gid ? Number(form.dataset.gid) : null;
    const checked = $$("#merchantPopupList input[type=checkbox]:checked");
    if (!gid && checked.length === 0) {
      toast("Please select at least one merchant", true);
      return;
    }
    await act(async () => {
      if (gid) {
        if (checked.length > 0) {
          for (const cb of checked) {
            const uid = Number(cb.value);
            await api(`/groups/${gid}/invite`, "POST", { user_id: uid }).catch(() => {});
          }
          toast(`Invitations sent to ${checked.length} merchants!`);
        } else {
          toast("Group created! You can invite members later.");
        }
        closeModal();
        await render();
      } else {
        const uids = checked.map(cb => Number(cb.value));
        const me = S.me;
        const gName = `${me.city} Combined Alliance`;
        const g = await api("/groups", "POST", {
          name: gName,
          description: "Combined buying collective",
          category: me.category,
          city: me.city,
          type: "invite"
        });
        for (const uid of uids) {
          await api(`/groups/${g.id}/invite`, "POST", { user_id: uid }).catch(() => {});
        }
        toast(`Group '${gName}' created and ${uids.length} merchants invited!`);
        closeModal();
        S.gid = g.id;
        S.tab = "groups";
        await render();
      }
    });
    return;
  }

  if (f === "collectiveAuction") {
    const gid = Number(form.dataset.gid || S.gid);
    const product = form.product.value;
    const budget = form.budget && form.budget.value ? Number(form.budget.value) : null;
    const note = form.note ? form.note.value : "";
    const checkedUids = $$("input[name=part_uids]:checked");
    if (checkedUids.length === 0) {
      toast("Select at least one participating merchant", true);
      return;
    }
    const participants = [];
    for (const cb of checkedUids) {
      const uid = Number(cb.value);
      const shop = cb.dataset.shop || "Merchant";
      const qInput = $(`input[name=qty_${uid}]`);
      const qty = qInput ? Number(qInput.value || 0) : 0;
      if (qty > 0) {
        participants.push({ user_id: uid, shop, qty });
      }
    }
    if (participants.length === 0) {
      toast("Total pooled quantity must be greater than 0", true);
      return;
    }
    await act(async () => {
      await api(`/groups/${gid}/auctions`, "POST", { product, budget, note, participants });
      toast(`AI Collective Reverse Auction launched with ${participants.length} merchants!`);
      closeModal();
      S.tab = "auctions";
      await render();
    });
    return;
  }

  if (f === "logUsage") {
    const product = form.product.value;
    const qty = Number(form.qty.value);
    await act(async () => {
      await api("/stock/usage", "POST", { product, qty });
      toast(`Logged sales usage for ${product}! Forecast model updated.`);
      closeModal();
      await render();
    });
    return;
  }

  if (f === "setStock") {
    const product = form.product.value;
    const stock = Number(form.stock.value);
    await act(async () => {
      await api("/stock/set", "POST", { product, stock });
      toast(`Shelf stock updated for ${product}!`);
      closeModal();
      await render();
    });
    return;
  }

  if (f === "editInventory") {
    const product = form.product.value;
    const stock_qty = Number(form.stock_qty.value);
    const price = Number(form.price.value);
    const floor_price = Number(form.floor_price.value);
    await act(async () => {
      await api("/wholesaler/inventory", "POST", { product, stock_qty, price, floor_price });
      toast(`Updated catalog for ${product}!`);
      closeModal();
      await render();
    });
    return;
  }

  if (f === "buySale") {
    const sid = Number(form.dataset.sid);
    const qty = Number(form.qty.value);
    await act(async () => {
      const res = await api(`/sales/${sid}/buy`, "POST", { qty });
      toast(`Order #${res.order_id} placed! Awaiting wholesaler delivery quote.`);
      closeModal();
      S.tab = "orders";
      await render();
    });
    return;
  }

  if (f === "startPool") {
    const sid = Number(form.dataset.sid);
    const group_id = Number(form.group_id.value);
    await act(async () => {
      const res = await api(`/sales/${sid}/pools`, "POST", { group_id });
      toast("Group pool started successfully! Invite other merchants to commit.");
      closeModal();
      S.gid = group_id;
      S.tab = "groups";
      S.gtab = "deals";
      await render();
    });
    return;
  }
});

// Negotiator: switching wholesaler / product refreshes the live price, stock and suggested limit.
document.addEventListener("change", async e => {
  const t = e.target;
  if (!t || !t.closest || !t.closest("form[data-f=negotiate]")) return;
  if (t.name !== "wholesaler_id" && t.name !== "product") return;
  const form = t.closest("form");
  S.negForm = {
    wholesaler_id: Number(form.wholesaler_id.value),
    product: t.name === "wholesaler_id" ? null : form.product.value,
    qty: null,
    max_price: null
  };
  t.blur();
  await render(true);
});

document.addEventListener("change", e => {
  if (e.target && e.target.id === "voiceLang") S.voiceLang = e.target.value;
});

// Helper for live filtering popup merchant directory
window.filterMerchantPopupList = function(q) {
  const term = (q || "").trim().toLowerCase();
  const items = $$("#merchantPopupList .merchant-item");
  items.forEach(el => {
    const text = el.dataset.text || "";
    el.style.display = (!term || text.includes(term)) ? "flex" : "none";
  });
};

// Helper for live collective total calculation
window.updateColTotal = function() {
  const checked = $$("input[name=part_uids]:checked");
  let total = 0;
  checked.forEach(cb => {
    const qEl = $(`input[name=qty_${cb.value}]`);
    if (qEl) total += Number(qEl.value || 0);
  });
  const totSpan = $("#colTot");
  if (totSpan) totSpan.textContent = num(total);
};

// Boot when ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
