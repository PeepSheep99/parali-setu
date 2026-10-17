// Customer portal: quotes and forward orders. Display only -- every price
// comes from costs.py through the API, every delivery from deliveries.py.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { customerId: null, customers: [], quote: null };
  const saved = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* blocked storage */ } },
  };
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "style") el.setAttribute("style", v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
    return el;
  }
  const svg = (tag, attrs = {}, ...children) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    children.flat().forEach((c) => c && el.append(c.nodeType ? c : document.createTextNode(String(c))));
    return el;
  };
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
  const month = (iso) => { const [y, m] = String(iso).split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short" }); };
  const monthYear = (iso) => { const [y, m] = String(iso).split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" }); };

  function request() {
    return { tonnes_per_month: Number($("q-tonnes").value), months: Number($("q-months").value), start_month: `${$("q-start").value}-01` };
  }

  // ---- the quote: price, how it is built, and what we can commit
  function renderQuote(body) {
    const q = body.quote;
    const req = request();
    const diff = q.price_per_t - q.in_season_benchmark_per_t;
    $("quote").replaceChildren(
      h("div", { class: "price-line" },
        h("span", { class: "big" }, rs(q.price_per_t)), h("span", { class: "per" }, "a tonne, delivered"),
        h("span", { class: "total" }, `${fmt(body.total_t)} t over ${req.months} month${req.months === 1 ? "" : "s"}: ${rs(body.total_inr)}`)),
      h("div", { class: "chart" }, buildUp(q)),
      h("p", { class: "compare" }, `In the harvest weeks, plants pay about ${rs(q.in_season_benchmark_per_t)} a tonne for straw delivered on the spot and must store it themselves. `,
        diff > 0 ? `Ours is ${rs(diff)} more because it includes storage and a delivery every month.` : `Ours is ${rs(-diff)} less.`),
      commitBlock(body.commit, req));
  }

  // The price built up step by step, with the in-season spot price for comparison.
  function buildUp(q) {
    const rows = [
      ["Paid to farmers", q.farm_gate_per_t, "today's average posted price"],
      ["Collection", q.collection_per_t, "baling, loading, haul to depot"],
      ["Storage until delivery", q.storage_per_t, ""],
      [`Haul from ${q.depot_name}`, q.haul_per_t, `${fmt(q.road_km)} km by road`],
      ["Our margin", q.margin_per_t, "10%"],
    ];
    const W = 720, rowH = 30, m = { l: 210, r: 90, t: 8, b: 26 }, H = m.t + m.b + rowH * (rows.length + 1);
    const max = Math.ceil(Math.max(q.price_per_t, q.in_season_benchmark_per_t) / 500) * 500;
    const x = (v) => m.l + (v / max) * (W - m.l - m.r);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Delivered price built up from costs: ${rows.map((r) => `${r[0]} ${rs(r[1])}`).join(", ")}, total ${rs(q.price_per_t)} a tonne` });
    const axis = svg("g", { class: "axis" });
    for (let v = 0; v <= max; v += max <= 2000 ? 500 : 1000) {
      chart.append(svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b, stroke: "var(--line)", "stroke-width": "1" }));
      axis.append(svg("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle" }, `₹${fmt(v)}`));
    }
    chart.append(axis);
    let acc = 0;
    rows.forEach(([label, v, note], i) => {
      const cy = m.t + rowH * i + rowH / 2;
      chart.append(svg("text", { class: "lbl dark", x: m.l - 10, y: cy + 4, "text-anchor": "end" }, label));
      const bar = svg("rect", { x: x(acc), y: cy - 9, width: Math.max(2, x(acc + v) - x(acc)), height: 18, rx: 4, fill: "var(--silk)" });
      bar.append(svg("title", {}, `${label}: ${rs(v)}${note ? ` (${note})` : ""}`));
      chart.append(bar, svg("text", { class: "lbl", x: x(acc + v) + 6, y: cy + 4 }, rs(v)));
      acc += v;
    });
    const cy = m.t + rowH * rows.length + rowH / 2;
    chart.append(svg("text", { class: "lbl dark", x: m.l - 10, y: cy + 4, "text-anchor": "end" }, "Delivered price"),
      svg("rect", { x: x(0), y: cy - 10, width: x(q.price_per_t) - x(0), height: 20, rx: 4, fill: "var(--madder)" }),
      svg("text", { class: "lbl dark", x: x(q.price_per_t) + 6, y: cy + 4 }, rs(q.price_per_t)),
      svg("line", { x1: x(q.in_season_benchmark_per_t), x2: x(q.in_season_benchmark_per_t), y1: m.t, y2: H - m.b, stroke: "var(--thread)", "stroke-width": "1.5", "stroke-dasharray": "4 3" }),
      svg("text", { class: "lbl", x: x(q.in_season_benchmark_per_t) + 4, y: m.t + 10 }, `in-season spot ${rs(q.in_season_benchmark_per_t)}`));
    return chart;
  }

  // What we can promise, month by month. Signed orders keep their stock, so
  // this is what is left for a new one.
  function commitBlock(c, req) {
    const asked = req.tonnes_per_month;
    const months = Object.keys(c.by_month).sort();
    const strip = h("div", { class: "months" }, months.map((m) => {
      const ok = c.by_month[m], pct = asked ? Math.min(100, (100 * ok) / asked) : 0;
      return h("div", { class: "mcell", title: `${monthYear(m)}: ${fmt(ok)} of ${fmt(asked)} t` },
        h("div", { class: `b${ok + 0.5 < asked ? " gap" : ""}` }, h("i", { style: `height:${pct}%` })), month(m));
    }));
    const head = c.can_fill
      ? h("div", { class: "commit-head" }, h("span", { class: "pill ok" }, `We can supply all ${fmt(c.asked_t)} t`))
      : h("div", { class: "commit-head" }, h("span", { class: "pill warn" }, `We can commit ${fmt(c.committable_t)} of ${fmt(c.asked_t)} t`),
          h("span", { class: "fine" }, "Orders already signed keep their stock, so a new order gets what is left."));
    const actions = h("div", { class: "actions" });
    if (c.can_fill) {
      actions.append(h("button", { type: "button", class: "btn", onclick: (e) => placeOrder(e, false) }, "Place this order"));
    } else {
      const per = Math.floor(c.max_t_per_month);
      actions.append(h("button", { type: "button", class: "btn", disabled: per < 1,
        onclick: () => { $("q-tonnes").value = per; $("quote-form").requestSubmit(); } },
        per >= 1 ? `Price ${fmt(per)} t a month instead` : "Nothing can be committed for these months"));
    }
    return h("div", { class: "commit" }, head, strip, actions);
  }

  async function quote(e) {
    e.preventDefault();
    const button = e.submitter || $("quote-form").querySelector("button");
    button.disabled = true;
    $("quote").replaceChildren(h("p", { class: "hint" }, "Pricing your order and checking what we can commit…"));
    try {
      state.quote = await postJson(`/customers/${encodeURIComponent(state.customerId)}/quote`, request());
      renderQuote(state.quote);
    } catch (err) {
      $("quote").replaceChildren(h("p", { class: "hint" }, err.message));
    } finally { button.disabled = false; }
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

  function showConfirmation(order, short) {
    const q = order.quote;
    const months = Object.keys(order.tonnes_by_month).sort();
    $("quote").replaceChildren(h("div", { class: "po" },
      h("span", { class: "pill ok" }, "Order placed"),
      h("span", { class: "code" }, order.order_code),
      h("p", {}, `${fmt(order.total_t)} t of baled paddy straw at ${rs(q.price_per_t)} a tonne, from ${q.depot_name}. Total ${rs(order.total_t * q.price_per_t)}.`),
      h("p", { class: "fine" }, `Monthly delivery: ${months.map((m) => `${monthYear(m)} ${fmt(order.tonnes_by_month[m])} t`).join(", ")}.`),
      short.length ? h("p", { class: "pill warn" }, `${fmt(short.reduce((n, x) => n + x.tonnes, 0))} t not planned yet. Our team will call you.`) : null,
      h("p", { class: "fine" }, "Prototype: this is a demo order. No contract, invoice or payment is created."),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "btn quiet", onclick: () => printConfirmation(order) }, "Print or save as PDF"),
        h("button", { type: "button", class: "btn quiet", onclick: () => $("quote").replaceChildren(h("p", { class: "hint" }, "Change the numbers above to price another order.")) }, "Price another order"))));
  }

  function printConfirmation(order) {
    const q = order.quote;
    const w = window.open("", "_blank");
    if (!w) { toast("Allow pop-ups to open the confirmation."); return; }
    const rows = Object.keys(order.tonnes_by_month).sort().map((m) => `<tr><td>${monthYear(m)}</td><td style="text-align:right">${fmt(order.tonnes_by_month[m])} t</td></tr>`).join("");
    w.document.write(`<!doctype html><meta charset="utf-8"><title>${order.order_code}</title>
      <body style="font:15px system-ui;max-width:560px;margin:32px auto;color:#2a1a1f"><h1 style="color:#8e1f33">Parali Setu: order ${order.order_code}</h1>
      <p><strong>DEMO ORDER.</strong> No real contract, invoice or payment.</p>
      <p>${fmt(order.total_t)} t baled paddy straw at ${rs(q.price_per_t)} a tonne, delivered from ${q.depot_name}.</p>
      <table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>Month</th><th>Tonnes</th></tr>${rows}</table>
      <p>Total ${rs(order.total_t * q.price_per_t)}. Placed ${new Date(order.created_at).toLocaleString("en-IN")}.</p></body>`);
    w.document.close();
    w.print();
  }

  // ---- orders: each a strip of months, planned or short
  async function loadOrders() {
    const { orders } = await api(`/customers/${encodeURIComponent(state.customerId)}/orders`);
    $("orders").replaceChildren(...(orders.length ? orders.map(orderCard) : [h("p", { class: "empty" }, "No orders yet. Price one on the left to start.")]),
      orders.length ? h("div", { class: "legend" }, h("span", {}, h("i", { style: "background:var(--ok)" }), "planned"),
        h("span", {}, h("i", { style: "background:var(--warn-soft);box-shadow:inset 0 0 0 1.5px var(--warn)" }), "short"),
        h("span", {}, h("i", { style: "box-shadow:inset 0 0 0 1.5px var(--line-strong)" }), "not planned yet")) : null);
  }

  function orderCard(o) {
    const delivered = {};
    o.deliveries.forEach((d) => { delivered[d.month] = (delivered[d.month] || 0) + d.tonnes; });
    const shortBy = Object.fromEntries((o.shortfall || []).map((s) => [s.month, s.tonnes]));
    const months = Object.keys(o.tonnes_by_month).sort();
    const cancelled = o.status === "cancelled";
    const strip = h("div", { class: "months" }, months.map((m) => {
      const ordered = o.tonnes_by_month[m], planned = delivered[m] || 0;
      const kind = cancelled ? "none" : shortBy[m] ? "gap" : planned + 0.05 >= ordered ? "" : "none";
      const pct = ordered ? Math.min(100, (100 * planned) / ordered) : 0;
      return h("div", { class: "mcell", title: `${monthYear(m)}: ${fmt(planned)} of ${fmt(ordered)} t planned${shortBy[m] ? `, ${fmt(shortBy[m])} t short` : ""}` },
        h("div", { class: `b ${kind}` }, h("i", { style: `height:${kind === "none" ? 0 : pct}%` })), month(m));
    }));
    const actions = h("div", { class: "confirm-row" });
    if (!cancelled) {
      const cancel = h("button", { type: "button", class: "btn quiet small" }, "Cancel order");
      cancel.addEventListener("click", () => {
        const yes = h("button", { type: "button", class: "btn small" }, "Yes, cancel it");
        const no = h("button", { type: "button", class: "btn quiet small" }, "Keep it");
        actions.replaceChildren(h("span", {}, `Cancel ${o.order_code}? Its stock goes to the next order in line.`), yes, no);
        no.addEventListener("click", () => actions.replaceChildren(cancel));
        yes.addEventListener("click", async () => {
          yes.disabled = true;
          try { await postJson(`/customers/${encodeURIComponent(state.customerId)}/orders/${encodeURIComponent(o.id)}/cancel`, {}); toast(`${o.order_code} cancelled.`); await loadOrders(); }
          catch (err) { toast(err.message); yes.disabled = false; }
        });
      });
      actions.append(cancel);
    }
    const shortTotal = Object.values(shortBy).reduce((n, v) => n + v, 0);
    const unplanned = months.filter((m) => !shortBy[m] && (delivered[m] || 0) + 0.05 < o.tonnes_by_month[m]).length;
    return h("article", { class: `order${cancelled ? " cancelled" : ""}` },
      h("header", {}, h("strong", {}, o.order_code),
        cancelled ? h("span", { class: "pill" }, "cancelled") : shortTotal ? h("span", { class: "pill warn" }, `${fmt(shortTotal)} t short`)
          : unplanned ? h("span", { class: "pill brand" }, `${unplanned} month${unplanned === 1 ? "" : "s"} not planned yet`) : h("span", { class: "pill ok" }, "fully planned")),
      h("span", { class: "meta" }, `${fmt(o.total_t)} t at ${rs(o.quote.price_per_t)} a tonne, from ${o.quote.depot_name}`),
      strip, actions);
  }

  async function init() {
    const { customers } = await api("/customers");
    state.customers = customers;
    const select = $("customer");
    select.replaceChildren(...customers.map((c) => h("option", { value: c.id }, c.name)));
    const remembered = saved.get("company_id");
    state.customerId = customers.some((c) => c.id === remembered) ? remembered : customers[0]?.id;
    select.value = state.customerId;
    const site = () => { const c = customers.find((x) => x.id === state.customerId); $("q-site").textContent = c ? `${c.name.replace(" (demo)", "")}, ${c.district}` : "our plant"; };
    site();
    select.addEventListener("change", () => {
      state.customerId = select.value;
      saved.set("company_id", state.customerId);
      site();
      $("quote").replaceChildren(h("p", { class: "hint" }, "Change the numbers above and press \"Price it\"."));
      loadOrders();
    });
    const next = new Date();
    next.setMonth(next.getMonth() + 1);
    $("q-start").value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
    $("quote-form").addEventListener("submit", quote);
    await loadOrders();
    $("quote-form").requestSubmit();     // open on a priced example, not an empty form
  }
  init().catch((err) => toast(err.message));
})();
