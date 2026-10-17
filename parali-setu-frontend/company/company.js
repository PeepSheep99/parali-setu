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
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${resp.status})`);
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
      h("button", { type: "button", class: "primary", onclick: placeOrder }, "Place this order"));
  }

  async function quote(e) {
    e.preventDefault();
    try {
      state.quote = await postJson(`/customers/${encodeURIComponent(state.customerId)}/quote`, request());
      renderQuote(state.quote);
    } catch (err) { toast(err.message); }
  }

  async function placeOrder(e) {
    const button = e.currentTarget;
    button.disabled = true;
    try {
      const body = await postJson(`/customers/${encodeURIComponent(state.customerId)}/orders`, request());
      const short = body.delivery_plan.shortfall.filter((s) => s.order_id === body.order.id);
      toast(short.length ? `Order placed. We can't cover ${fmt(short.reduce((n, s) => n + s.tonnes, 0))} t of it yet; our team will call you.` : "Order placed. Every month is covered by the delivery plan.");
      $("quote").hidden = true;
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
      return h("div", { class: "table-wrap" }, h("p", { class: "small" }, h("strong", {}, `${fmt(o.total_t)} t at ${rs(o.quote.price_per_t)}/t`), ` · from ${o.quote.depot_name}`),
        h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Month"), h("th", { class: "num" }, "Ordered"), h("th", { class: "num" }, "Planned"), h("th", {}, ""))),
          h("tbody", {}, months.map((m) => h("tr", {}, h("td", {}, month(m)), h("td", { class: "n" }, `${fmt(o.tonnes_by_month[m])} t`),
            h("td", { class: "n" }, `${fmt(delivered[m] || 0)} t`),
            h("td", {}, shortBy[m] ? h("span", { class: "pill warn" }, `short ${fmt(shortBy[m])} t`)
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
