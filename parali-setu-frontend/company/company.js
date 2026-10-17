// Customer portal: quotes and forward orders. Display only -- every price
// comes from costs.py through the API, every delivery from deliveries.py.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { customerId: null, quote: null };
  const saved = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* blocked storage */ } },
  };
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
    return el;
  }
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { el.hidden = true; }, 4500);
  }
  async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try { body = await resp.json(); } catch { /* no body */ }
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : (body.detail && body.detail.message) || `Request failed (${resp.status})`);
    return body;
  }
  const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  const fmt = (n, d = 0) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: d });
  const rs = (n) => `₹${fmt(n, 0)}`;
  const month = (iso) => {
    const [y, m] = String(iso).split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
  };

  function request() {
    return {
      tonnes_per_month: Number($("q-tonnes").value), months: Number($("q-months").value),
      start_month: `${$("q-start").value}-01`,
    };
  }

  function renderQuote(body) {
    const q = body.quote;
    const rows = [
      ["Paid to farmers (today's average posted price)", q.farm_gate_per_t],
      ["Collection: baling, loading, haul to depot", q.collection_per_t],
      ["Storage until delivery", q.storage_per_t],
      [`Haul from ${q.depot_name} (${fmt(q.road_km)} km by road)`, q.haul_per_t],
      ["Our margin", q.margin_per_t],
    ];
    const diff = q.price_per_t - q.in_season_benchmark_per_t;
    const box = $("quote");
    box.hidden = false;
    box.replaceChildren(
      h("p", { class: "muted small" }, "Delivered price per tonne"),
      h("p", { class: "quote-price" }, `${rs(q.price_per_t)} / t`),
      h("table", { class: "breakdown" }, h("tbody", {},
        rows.map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, rs(v)))),
        h("tr", { class: "total" }, h("td", {}, "Delivered price"), h("td", {}, rs(q.price_per_t))))),
      h("p", { class: "compare" }, `In-season, plants pay about ${rs(q.in_season_benchmark_per_t)}/t for straw delivered at harvest and must store it themselves. `,
        diff > 0 ? `Our year-round price is ${rs(diff)}/t more because it includes storage and monthly delivery.` : `Our price is ${rs(-diff)}/t below that.`),
      h("p", {}, h("strong", {}, `${fmt(body.total_t)} t`), ` over ${request().months} month(s): `, h("strong", {}, rs(body.total_inr))),
      commitBlock(body.commit));
  }

  // What we can promise. Signed orders keep their stock, so this is what is left for a new order.
  function commitBlock(c) {
    if (c.can_fill) {
      return h("div", {}, h("p", { class: "pill booked" }, `We can supply all ${fmt(c.asked_t)} t`),
        h("button", { type: "button", class: "primary", onclick: (e) => placeOrder(e, false) }, "Place this order"));
    }
    const perMonth = Math.floor(c.max_t_per_month);
    return h("div", {},
      h("p", { class: "pill warn" }, `We can commit ${fmt(c.committable_t)} t of the ${fmt(c.asked_t)} t you asked for`),
      h("p", { class: "small muted" }, "Orders already signed keep their stock, so a new order only gets what is left. You can order a smaller amount now, and we will tell you when more becomes available."),
      h("button", { type: "button", class: "primary", disabled: perMonth < 1,
        onclick: () => { $("q-tonnes").value = perMonth; $("quote-form").requestSubmit(); } },
        perMonth >= 1 ? `Order what we can commit (${fmt(perMonth)} t a month)` : "Nothing can be committed for these months"));
  }

  async function quote(e) {
    e.preventDefault();
    try {
      state.quote = await postJson(`/customers/${encodeURIComponent(state.customerId)}/quote`, request());
      renderQuote(state.quote);
    } catch (err) { toast(err.message); }
  }

  async function placeOrder(e, allowPartial) {
    const button = e.currentTarget;
    button.disabled = true;
    try {
      const body = await postJson(`/customers/${encodeURIComponent(state.customerId)}/orders`, { ...request(), allow_partial: !!allowPartial });
      const short = body.delivery_plan.shortfall.filter((s) => s.order_id === body.order.id);
      showConfirmation(body.order, short);
      await loadOrders();
    } catch (err) { toast(err.message); button.disabled = false; }
  }

  // Order confirmation: a reference, the terms and the schedule, printable as a page.
  function showConfirmation(order, short) {
    const q = order.quote;
    const months = Object.keys(order.tonnes_by_month).sort();
    const box = $("quote");
    box.hidden = false;
    box.replaceChildren(
      h("p", { class: "pill booked" }, "Order placed"),
      h("p", { class: "quote-price" }, order.order_code),
      h("p", {}, `${fmt(order.total_t)} t of baled paddy straw at ${rs(q.price_per_t)}/t, from ${q.depot_name}. Total ${rs(order.total_t * q.price_per_t)}.`),
      h("p", { class: "small muted" }, `Monthly delivery: ${months.map((m) => `${month(m)} ${fmt(order.tonnes_by_month[m])} t`).join(", ")}.`),
      short.length ? h("p", { class: "pill warn" }, `${fmt(short.reduce((n, x) => n + x.tonnes, 0))} t is not planned yet. Our team will call you.`) : null,
      h("p", { class: "small muted" }, "Prototype: this is a demo order. No contract, invoice or payment is created."),
      h("button", { type: "button", onclick: () => printConfirmation(order) }, "Download confirmation (print)"));
    window.scrollTo({ top: box.offsetTop - 12, behavior: "smooth" });
  }

  function printConfirmation(order) {
    const q = order.quote;
    const w = window.open("", "_blank");
    if (!w) { toast("Allow pop-ups to open the confirmation."); return; }
    const rows = Object.keys(order.tonnes_by_month).sort().map((m) => `<tr><td>${month(m)}</td><td>${fmt(order.tonnes_by_month[m])} t</td></tr>`).join("");
    w.document.write(`<!doctype html><meta charset="utf-8"><title>${order.order_code}</title>
      <body style="font:15px system-ui;max-width:560px;margin:32px auto"><h1>Parali Setu: order ${order.order_code}</h1>
      <p><strong>DEMO ORDER.</strong> No real contract, invoice or payment.</p>
      <p>${fmt(order.total_t)} t baled paddy straw at ${rs(q.price_per_t)}/t, delivered from ${q.depot_name}.</p>
      <table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>Month</th><th>Tonnes</th></tr>${rows}</table>
      <p>Total ${rs(order.total_t * q.price_per_t)}. Placed ${new Date(order.created_at).toLocaleString("en-IN")}.</p></body>`);
    w.document.close();
    w.print();
  }

  async function cancelOrder(order, button) {
    if (!window.confirm(`Cancel order ${order.order_code}? Its stock goes back to the queue.`)) return;
    button.disabled = true;
    try {
      await postJson(`/customers/${encodeURIComponent(state.customerId)}/orders/${encodeURIComponent(order.id)}/cancel`, {});
      toast(`Order ${order.order_code} cancelled.`);
      await loadOrders();
    } catch (err) { toast(err.message); button.disabled = false; }
  }

  async function loadOrders() {
    const { orders } = await api(`/customers/${encodeURIComponent(state.customerId)}/orders`);
    $("orders").replaceChildren(...(orders.length ? orders.map((o) => {
      const delivered = {};
      o.deliveries.forEach((d) => { delivered[d.month] = (delivered[d.month] || 0) + d.tonnes; });
      const shortBy = Object.fromEntries((o.shortfall || []).map((s) => [s.month, s.tonnes]));
      const months = Object.keys(o.tonnes_by_month).sort();
      const cancelled = o.status === "cancelled";
      return h("div", { class: "table-wrap" }, h("p", { class: "small" }, h("strong", {}, `${o.order_code} · ${fmt(o.total_t)} t at ${rs(o.quote.price_per_t)}/t`), ` · from ${o.quote.depot_name} `,
        cancelled ? h("span", { class: "pill" }, "cancelled")
          : h("button", { type: "button", class: "ghost", onclick: (e) => cancelOrder(o, e.currentTarget) }, "Cancel order")),
        h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Month"), h("th", { class: "num" }, "Ordered"), h("th", { class: "num" }, "Planned"), h("th", {}, ""))),
          h("tbody", {}, months.map((m) => h("tr", {}, h("td", {}, month(m)), h("td", { class: "n" }, `${fmt(o.tonnes_by_month[m])} t`),
            h("td", { class: "n" }, `${fmt(delivered[m] || 0)} t`),
            h("td", {}, cancelled ? null : shortBy[m] ? h("span", { class: "pill warn" }, `short ${fmt(shortBy[m])} t`)
              : (delivered[m] || 0) + 0.05 >= o.tonnes_by_month[m] ? h("span", { class: "pill booked" }, "covered")
              : h("span", { class: "pill" }, "not planned yet")))))));
    }) : [h("p", { class: "empty" }, "No orders yet. Get a quote to start.")]));
  }

  async function init() {
    const { customers } = await api("/customers");
    const select = $("customer");
    select.replaceChildren(...customers.map((c) => h("option", { value: c.id }, c.name)));
    const remembered = saved.get("company_id");
    state.customerId = customers.some((c) => c.id === remembered) ? remembered : customers[0]?.id;
    select.value = state.customerId;
    select.addEventListener("change", () => { state.customerId = select.value; saved.set("company_id", state.customerId); $("quote").hidden = true; loadOrders(); });
    const next = new Date();
    next.setMonth(next.getMonth() + 1);
    $("q-start").value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
    $("quote-form").addEventListener("submit", quote);
    await loadOrders();
  }
  init().catch((err) => toast(err.message));
})();
