// Operations console. Display and actions only: prices from procurement.py,
// slots from scheduler.py, deliveries from deliveries.py, impact from
// impact.py, forecasts from BigQuery -- nothing is computed here.
(() => {
  const $ = (id) => document.getElementById(id);
  const CREW_COLOURS = ["#a8304a", "#2f6b3b", "#5a4a8a", "#1f6f8b", "#8a5d06", "#6d5a5d"];
  const state = { tab: "today", dayOffset: 1, depotId: null, day: null, schedule: null, depots: [], map: null, layers: [], forecast: null, seasons: null };
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
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${resp.status})`);
    return body;
  }
  const postJson = (path, data = {}) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  const fmt = (n, d = 0) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: d });
  const t = (kg) => `${fmt(kg / 1000, 1)} t`;
  const rs = (n) => `₹${fmt(n, 0)}`;
  const perKg = (n) => `₹${Number(n).toFixed(2)}/kg`;
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);
  const parse = (iso) => { const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
  const day = (iso) => parse(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  const longDay = (iso) => parse(iso).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  const short = (iso) => parse(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const month = (iso) => { const [y, m] = String(iso).split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "2-digit" }); };
  const addDays = (iso, n) => { const d = parse(iso); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const kpi = (v, k, kind) => h("div", { class: `kpi${kind ? ` ${kind}` : ""}` }, h("span", { class: "v" }, v), h("span", { class: "k" }, k));
  const table = (head, rows) => h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map((c) => h("th", { class: c.n ? "num" : "" }, c.label || c)))),
    h("tbody", {}, rows)));
  const STATUS = { offered: "Offer out", unschedulable: "No slot", booked: "Booked, call first", verified: "Confirmed", collected: "Collected", paid: "Paid" };
  const pill = (status, text) => h("span", { class: `pill ${status}` }, text || STATUS[status] || status);
  function tip(e, text) {
    const el = $("tooltip");
    el.textContent = text;
    el.hidden = false;
    el.style.left = `${Math.min(e.clientX + 14, window.innerWidth - 290)}px`;
    el.style.top = `${e.clientY + 14}px`;
  }
  const hideTip = () => { $("tooltip").hidden = true; };

  // ---- tabs
  function showTab(tab) {
    state.tab = tab;
    saved.set("ops_tab", tab);
    document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== `tab-${tab}`; });
    location.hash = tab;
    const loader = { today: loadToday, pickups: loadPickups, stock: loadStock, forecast: loadForecast, plan: loadPlan,
                     orders: loadOrders, impact: loadImpact }[tab];
    Promise.resolve().then(loader).catch((err) => toast(err.message));
  }

  // =========================================================================
  // Dispatch: who goes out, who to call, are we ready for the forecast
  // =========================================================================
  async function loadToday() {
    const today = (await api("/ops/summary")).date;
    const target = addDays(today, state.dayOffset);
    const board = await api(`/ops/dispatch?day=${target}`);
    document.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.day) === state.dayOffset)));
    $("board-title").textContent = `${longDay(board.date)}: who goes out`;
    const crews = board.depots.flatMap((d) => d.crews.filter((c) => c.stops.length));
    const farms = board.depots.reduce((n, d) => n + d.farms, 0);
    const acres = board.depots.reduce((n, d) => n + d.acres, 0);
    const hired = board.depots.reduce((n, d) => n + d.oncall_hired, 0);
    const hireCost = board.depots.reduce((n, d) => n + d.hire_cost_inr, 0);
    const idle = board.depots.reduce((n, d) => n + d.own_crews_idle, 0);
    const calls = board.verify_queue.filter((q) => q.pickup_date === board.date).length;
    $("board-sub").textContent = `${board.depots.length} depots. Plans come from the routing model; a crew leaves only for pickups our team has confirmed by phone.`;
    $("board-kpis").replaceChildren(
      kpi(fmt(crews.length), "crews out"),
      kpi(fmt(farms), `farms, ${fmt(acres, 1)} acres`),
      kpi(fmt(hired), hired ? `on-call crews to hire, about ${rs(hireCost)} extra` : "on-call crews needed", hired ? "silk" : ""),
      kpi(fmt(idle), "own crews free"),
      kpi(fmt(calls), "calls to make before they go", calls ? "warn" : ""));
    $("board-depots").replaceChildren(...board.depots.filter((d) => d.crews.length).map(depotBoard),
      board.depots.some((d) => d.crews.length) ? h("div", { class: "legend" },
        h("span", {}, h("i", { style: "background:var(--chart-own)" }), "our crew"),
        h("span", {}, h("i", { style: "background:var(--chart-silk)" }), "on-call crew"),
        h("span", {}, h("i", { style: "background:var(--madder-soft);box-shadow:inset 0 0 0 2px var(--warn)" }), "booked, call before dispatch"),
        h("span", {}, h("i", { style: "background:var(--madder-soft);box-shadow:inset 0 0 0 1.5px var(--line-strong)" }), "offer, waiting for the farmer"))
        : h("p", { class: "panel empty" }, `No pickups planned for ${longDay(board.date)} yet.`));
    renderVerifyQueue(board.verify_queue);
    renderReadiness(board.readiness, board.today);
    renderExceptions(board.exceptions);
  }

  const DAY_START = 7 * 60, DAY_END = 18 * 60;
  const pos = (m) => `${(100 * (Math.max(DAY_START, Math.min(DAY_END, m)) - DAY_START)) / (DAY_END - DAY_START)}%`;
  function depotBoard(d) {
    const ticks = [7, 9, 11, 13, 15, 17].map((hr) => h("span", { style: `left:${pos(hr * 60)}` }, hr <= 12 ? `${hr} am`.replace("12 am", "12 pm") : `${hr - 12} pm`));
    const lanes = d.crews.map((c) => h("div", { class: "lane" },
      h("div", { class: "who" }, c.name, " ", c.on_call ? pill("oncall", "on-call") : null,
        h("small", {}, c.stops.length ? `${c.stops.length} farm${c.stops.length === 1 ? "" : "s"}, ${fmt(c.acres, 1)} of ${fmt(c.acres_per_day)} acres` : "free")),
      h("div", { class: "track" }, c.stops.map((s) => {
        const start = s.planned_start_min ?? s.window_start_min, end = s.planned_end_min ?? s.window_end_min;
        const kind = `${s.dispatch === "ready" ? "" : s.dispatch === "call first" ? "call" : "awaiting"}${c.on_call ? " oncall" : ""}`;
        const label = `${s.farmer_name || s.village || s.district} · ${fmt(s.acres, 1)} ac`;
        const block = h("span", { class: `stopblock ${kind}`, style: `left:${pos(start)};width:calc(${pos(end)} - ${pos(start)})`, tabindex: "0" }, label);
        const text = `${s.farmer_name ? `${s.farmer_name}, ` : ""}${s.village || s.district} · ${fmt(s.acres, 1)} acres · ${hm(start)}–${hm(end)} · ${s.booking_code} · ${s.dispatch}`;
        block.addEventListener("mousemove", (e) => tip(e, text));
        block.addEventListener("mouseleave", hideTip);
        block.setAttribute("aria-label", text);
        return block;
      }))));
    return h("section", { class: "depot-board" },
      h("header", {}, h("h2", {}, d.name), h("span", { class: "facts" },
        `${d.own_crews_out} own crew${d.own_crews_out === 1 ? "" : "s"} out, ${d.own_crews_idle} free${d.oncall_hired ? `, ${d.oncall_hired} on-call hired (${rs(d.hire_cost_inr)})` : ""}`)),
      h("div", { class: "lanes" }, h("div", { class: "ruler" }, h("span"), h("div", { class: "ticks" }, ticks)), lanes));
  }

  function renderVerifyQueue(queue) {
    $("verify-all").disabled = !queue.length;
    $("verify-queue").replaceChildren(...(queue.length ? queue.map((q) => {
      const row = h("div", { class: "vq" });
      const verify = h("button", { type: "button", class: "btn small" }, "Confirmed");
      const flag = h("button", { type: "button", class: "btn quiet small" }, "Needs a change");
      verify.addEventListener("click", async () => {
        verify.disabled = true;
        try { await postJson(`/ops/bookings/${encodeURIComponent(q.booking_id)}/verify`, { notes: "Called the farmer; details correct." }); toast(`${q.booking_code} confirmed. It is on the crew's sheet.`); loadToday(); }
        catch (err) { toast(err.message); verify.disabled = false; }
      });
      flag.addEventListener("click", () => {
        const input = h("input", { type: "text", maxlength: "200", placeholder: "What needs to change? e.g. village is Bhawanigarh", "aria-label": "What needs to change" });
        const save = h("button", { type: "submit", class: "btn small" }, "Save");
        const form = h("form", {}, input, save);
        form.addEventListener("submit", async (e) => {
          e.preventDefault();
          try { await postJson(`/ops/bookings/${encodeURIComponent(q.booking_id)}/needs-change`, { notes: input.value.trim() }); toast("Noted. The pickup stays off the road until it is fixed."); loadToday(); }
          catch (err) { toast(err.message); }
        });
        row.querySelector("form")?.remove();
        row.append(form);
        input.focus();
      });
      const v = q.verification || {};
      row.append(
        h("div", {}, h("strong", {}, q.farmer_name || q.village || q.district), " ",
          v.status === "needs_change" ? pill("needs_change", "needs a change") : null,
          h("span", { class: "meta" }, `${q.village || q.district} · ${fmt(q.acres || 0, 1)} acres · ${q.pickup_date ? `${day(q.pickup_date)} ${hm(q.pickup_start_min)}` : "no slot yet"} · ${q.depot_name}`),
          h("span", { class: "meta" }, `${q.booking_code}${q.contact ? ` · ${q.contact}` : ""}${q.location_approximate ? " · location from village name" : ""}${v.notes ? ` · note: ${v.notes}` : ""}`)),
        h("div", { class: "acts" }, verify, flag));
      return row;
    }) : [h("p", { class: "empty" }, "No calls waiting. Every booked pickup is confirmed.")]));
  }

  // Acres farmers are forecast to book each day, split into what our own crews
  // clear, what on-call crews from the pool clear, and what neither can reach.
  function renderReadiness(rows) {
    const days = {};
    for (const r of rows) {
      const d = (days[r.date] = days[r.date] || { date: r.date, acres: 0, own: 0, oncall: 0, beyond: 0, hires: 0, signup: 0, pool: 0 });
      const ownPart = Math.min(r.forecast_acres, r.own_capacity_acres);
      d.acres += r.forecast_acres; d.own += ownPart; d.beyond += r.beyond_pool_acres;
      d.oncall += Math.max(0, r.forecast_acres - ownPart - r.beyond_pool_acres);
      d.hires += r.oncall_crews_needed; d.signup += r.crews_to_sign_up; d.pool += r.oncall_pool;
    }
    const list = Object.values(days).sort((a, b) => a.date.localeCompare(b.date));
    if (!list.length) { $("ready-chart").replaceChildren(h("p", { class: "empty" }, "No forecast yet.")); return; }
    const ownCap = rows.filter((r) => r.date === list[0].date).reduce((n, r) => n + r.own_capacity_acres, 0);
    $("ready-sub").textContent = `Acres farmers are forecast to book with us each day (TimesFM harvest timing x district straw x our 0.5% booking share), against the ${fmt(ownCap)} acres a day our own crews clear and the ${fmt(list[0].pool)} on-call crews we can call in.`;
    const W = 680, H = 230, m = { l: 44, r: 10, t: 24, b: 28 };
    const raw = Math.max(ownCap, ...list.map((d) => d.acres));
    const mag = 10 ** Math.floor(Math.log10(raw / 4));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k * 4 >= raw);
    const max = step * 4;
    const y = (v) => H - m.b - (v / max) * (H - m.t - m.b);
    const slot = (W - m.l - m.r) / list.length, bw = Math.max(8, slot - 6);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Forecast acres per day: own crews, on-call crews and beyond our pool" });
    const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" }), marks = svg("g", { class: "marks" });
    for (let i = 0; i <= 4; i++) { grid.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(step * i), y2: y(step * i) })); axis.append(svg("text", { x: m.l - 6, y: y(step * i) + 4, "text-anchor": "end" }, fmt(step * i))); }
    chart.append(grid, axis, marks);
    list.forEach((d, i) => {
      const x0 = m.l + i * slot + (slot - bw) / 2;
      let base = 0;
      const seg = (v, fill, last, extra = {}) => {
        if (v <= 0.05) return;
        const top = y(base + v), bottom = y(base) - (base > 0 ? 2 : 0);   // 2px gap between stacked parts
        marks.append(svg("path", { d: bar(x0, top, bw, Math.max(1, bottom - top), last), fill, ...extra }));
        base += v;
      };
      seg(d.own, "var(--chart-own)", d.oncall <= 0.05 && d.beyond <= 0.05);
      seg(d.oncall, "var(--chart-silk)", d.beyond <= 0.05);
      seg(d.beyond, "var(--surface)", true, { stroke: "var(--warn)", "stroke-width": "1.5", "stroke-dasharray": "3 2" });
      if (d.hires) chart.append(svg("text", { class: "label silk", x: x0 + bw / 2, y: y(d.acres) - 5, "text-anchor": "middle" }, `+${d.hires}`));
      if (i % 3 === 0 || i === list.length - 1) axis.append(svg("text", { x: x0 + bw / 2, y: H - m.b + 16, "text-anchor": "middle" }, short(d.date)));
      const hit = svg("rect", { class: "hit", x: m.l + i * slot, y: m.t, width: slot, height: H - m.t - m.b });
      hit.addEventListener("mousemove", (e) => tip(e, `${day(d.date)}: about ${fmt(d.acres)} acres forecast. Own crews ${fmt(d.own)}; ${d.hires} on-call crew${d.hires === 1 ? "" : "s"} ${fmt(d.oncall)}${d.beyond ? `; ${fmt(d.beyond)} acres beyond our pool (sign up ${d.signup} more)` : ""}.`));
      hit.addEventListener("mouseleave", hideTip);
      chart.append(hit);
    });
    chart.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(ownCap), y2: y(ownCap), stroke: "var(--thread)", "stroke-width": "1.2", "stroke-dasharray": "5 4" }));
    $("ready-chart").replaceChildren(chart, h("div", { class: "legend" },
      h("span", {}, h("i", { style: "background:var(--chart-own)" }), "own crews"),
      h("span", {}, h("i", { style: "background:var(--chart-silk)" }), "on-call crews (+N to hire)"),
      h("span", {}, h("i", { style: "box-shadow:inset 0 0 0 1.5px var(--warn)" }), "beyond our on-call pool"),
      h("span", {}, h("i", { style: "height:0;border-top:1.5px dashed var(--thread);border-radius:0" }), `own crews clear ${fmt(ownCap)} acres a day`)));
    const hireDays = list.filter((d) => d.hires > 0);
    const shortDays = list.filter((d) => d.signup > 0);
    if (shortDays.length) {
      const most = Math.max(...shortDays.map((d) => d.signup));
      $("ready-action").className = "action";
      $("ready-action").textContent = `Sign up ${most} more on-call crew${most === 1 ? "" : "s"} before ${short(shortDays[0].date)}: from then to ${short(shortDays[shortDays.length - 1].date)} the forecast is more than our own crews plus the whole on-call pool can clear. Until then, hire up to ${Math.max(...hireDays.map((d) => d.hires))} on-call crews a day.`;
    } else if (hireDays.length) {
      const most = Math.max(...hireDays.map((d) => d.hires));
      $("ready-action").className = "action";
      $("ready-action").textContent = `Hire up to ${most} on-call crew${most === 1 ? "" : "s"} a day from ${short(hireDays[0].date)} to ${short(hireDays[hireDays.length - 1].date)}. The pool covers every forecast booking.`;
    } else {
      $("ready-action").className = "action ok";
      $("ready-action").textContent = "Our own crews cover the forecast for the next three weeks.";
    }
    $("ready-table").replaceChildren(table(["Day", "Depot", { label: "Forecast acres", n: 1 }, { label: "Own crews clear", n: 1 }, { label: "On-call to hire", n: 1 }, { label: "Crews to sign up", n: 1 }],
      rows.filter((r) => r.forecast_acres > 0).map((r) => h("tr", {}, h("td", {}, day(r.date)), h("td", {}, r.depot_name),
        h("td", { class: "n" }, fmt(r.forecast_acres, 1)), h("td", { class: "n" }, fmt(r.own_capacity_acres)), h("td", { class: "n" }, fmt(r.oncall_crews_needed)), h("td", { class: "n" }, fmt(r.crews_to_sign_up))))));
  }
  function bar(x0, y0, w, hgt, roundTop) {   // 4px rounded data end
    const r = roundTop ? Math.min(4, w / 2, Math.max(0, hgt)) : 0;
    return `M${x0},${y0 + hgt}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + hgt}Z`;
  }

  function renderExceptions(list) {
    const link = (tab, text) => h("a", { href: `#${tab}`, onclick: (e) => { e.preventDefault(); showTab(tab); } }, text);
    $("exceptions").replaceChildren(...(list.length ? list.map((x) => {
      if (x.kind === "orders_short_of_straw") return h("p", {}, `Signed orders need ${fmt(x.tonnes, 1)} t more straw than the buying plan can source. Raise prices in short districts or stop taking new orders. `, link("orders", "See orders"));
      if (x.kind === "deliveries_short") return h("p", {}, `${fmt(x.tonnes, 1)} t of deliveries are short in ${x.orders.length} order${x.orders.length === 1 ? "" : "s"}. Call those customers. `, link("orders", "See orders"));
      if (x.kind === "no_slot") return h("p", {}, `${x.farmer_name || x.village || x.district} (${x.depot_name}) has no pickup slot: ${x.reason || "no reason given"}. Call the farmer.`);
      if (x.kind === "promise_at_risk") return h("p", {}, `${x.farmer_name || x.village || x.district} (${x.depot_name}) was booked but the latest plan can't keep the slot: ${x.reason}. Call the farmer and re-plan. `, link("pickups", "See routes"));
      return h("p", {}, JSON.stringify(x));
    }) : [h("p", { class: "empty" }, "Nothing else needs a person.")]));
  }

  // =========================================================================
  // Routes
  // =========================================================================
  async function loadPickups() {
    if (!state.depots.length) state.depots = (await api("/depots")).depots;
    const select = $("depot");
    if (!select.options.length) {
      select.replaceChildren(...state.depots.map((d) => h("option", { value: d.id }, `${d.name} (${d.district})`)));
      const remembered = saved.get("ops_depot");
      state.depotId = state.depots.some((d) => d.id === remembered) ? remembered : state.depots[0]?.id;
      select.value = state.depotId;
    }
    state.schedule = await api(`/depots/${encodeURIComponent(state.depotId)}/schedule`);
    const days = [...new Set(state.schedule.route_sheets.map((s) => s.date))];
    if (!days.includes(state.day)) state.day = days[0] || null;
    renderPickups();
  }
  function crewColour(crewId) {
    const ids = state.schedule.route_sheets.map((s) => s.crew_id).filter((v, i, a) => a.indexOf(v) === i).sort();
    return CREW_COLOURS[Math.max(0, ids.indexOf(crewId)) % CREW_COLOURS.length];
  }
  function renderPickups() {
    const s = state.schedule;
    const days = [...new Set(s.route_sheets.map((r) => r.date))];
    $("days").replaceChildren(...days.map((d) => {
      const stops = s.route_sheets.filter((r) => r.date === d).reduce((n, r) => n + r.stops.length, 0);
      return h("button", { type: "button", role: "tab", "aria-selected": String(d === state.day), onclick: () => { state.day = d; renderPickups(); } },
        day(d), h("span", { class: "n" }, `${stops} ${stops === 1 ? "stop" : "stops"}`));
    }));
    const sheets = s.route_sheets.filter((r) => r.date === state.day);
    $("sheets").replaceChildren(...(sheets.length ? sheets.map((sheet) => {
      const colour = crewColour(sheet.crew_id);
      const cap = sheet.acres_per_day || 20;
      return h("div", { class: "sheet", style: `--crew:${colour}` },
        h("div", { class: "sheet-head" }, h("h3", {}, sheet.crew_name, " ", sheet.partner ? pill("oncall", "on-call") : null),
          h("span", { class: "small muted" }, `${fmt(sheet.acres, 1)} / ${fmt(cap)} acres`)),
        h("div", { class: "load-bar" }, h("i", { style: `width:${Math.min(100, (100 * sheet.acres) / cap)}%` })),
        ...sheet.stops.map(stopRow));
    }) : [h("p", { class: "empty" }, "No pickups planned for this depot yet.")]));
    renderUnschedulable();
    renderCrews();
    drawMap(sheets);
  }
  function stopRow(stop) {
    const actions = [];
    if (stop.status === "verified") {
      actions.push(h("button", { type: "button", class: "btn small", onclick: (e) => markCollected(stop, e.currentTarget) }, "Mark collected"));
    } else if (stop.status === "booked") {
      actions.push(h("button", { type: "button", class: "btn quiet small", onclick: (e) => verifyStop(stop, e.currentTarget) }, "Confirm by phone"));
    } else if (stop.status === "offered") {
      actions.push(h("span", { class: "small muted" }, "Waiting for the farmer"));
      actions.push(h("button", { type: "button", class: "btn quiet small", title: "Demo only: accept on the farmer's behalf", onclick: (e) => acceptForFarmer(stop, e.currentTarget) }, "Accept for farmer (demo)"));
    } else actions.push(pill(stop.status));
    const work = (stop.planned_end_min || 0) - (stop.planned_start_min || 0);
    return h("div", { class: "stop" },
      h("span", { class: "seq" }, stop.sequence),
      h("div", { class: "what" },
        h("strong", {}, stop.farmer_name || stop.village || stop.district || "Farm", " ", pill(stop.status)),
        h("span", { class: "small" }, `Arrival window ${hm(stop.window_start_min)}–${hm(stop.window_end_min)} · planned start ${hm(stop.planned_start_min)}, work about ${dur(work)}`),
        h("span", { class: "small muted" }, `${stop.village || ""} · ${fmt(stop.acres, 1)} acres · ${t(stop.kg)} · ${perKg(stop.price_per_kg)} · sow by ${stop.sowing_deadline ? day(stop.sowing_deadline) : "not given"}${stop.contact ? ` · ${stop.contact}` : ""}${stop.location_approximate ? " · location approximate" : ""}`)),
      h("div", { class: "act" }, actions));
  }
  async function acceptForFarmer(stop, button) {
    button.disabled = true;
    try { await postJson(`/ops/bookings/${encodeURIComponent(stop.booking_id)}/accept`); toast("Accepted for the farmer (demo). Now confirm it by phone."); await loadPickups(); }
    catch (err) { toast(err.message); button.disabled = false; }
  }
  async function verifyStop(stop, button) {
    button.disabled = true;
    try { await postJson(`/ops/bookings/${encodeURIComponent(stop.booking_id)}/verify`, { notes: "Confirmed from the route sheet." }); toast("Confirmed. The crew can go."); await loadPickups(); }
    catch (err) { toast(err.message); button.disabled = false; }
  }
  async function markCollected(stop, button) {
    button.disabled = true;
    try {
      const { purchase } = await postJson(`/stops/${encodeURIComponent(stop.booking_id)}/collected`, {});
      toast(`Collected ${t(purchase.kg)}. Farmer paid ${rs(purchase.amount_inr)} today (simulated UPI). Added to depot stock.`);
      await loadPickups();
    } catch (err) { toast(err.message); button.disabled = false; }
  }
  function renderUnschedulable() {
    const rows = state.schedule.unschedulable;
    $("unschedulable").replaceChildren(rows.length ? table(["Farm", { label: "Straw", n: 1 }, "Sow by", "Why", "Next step"],
      rows.map((r) => h("tr", {}, h("td", {}, r.farmer_name || r.village || r.district), h("td", { class: "n" }, t(r.kg)),
        h("td", {}, r.sowing_deadline ? day(r.sowing_deadline) : "—"), h("td", {}, r.reason || "—"),
        h("td", {}, r.reason_code === "booked" || r.reason_code === "no_capacity" ? "Add a crew below, then re-plan" : "Call the farmer")))) :
      h("p", { class: "empty" }, "Every booked farm at this depot has a slot."));
  }
  function renderCrews() {
    const depot = state.depots.find((d) => d.id === state.depotId);
    $("crews").replaceChildren(...(depot?.crews || []).map((c) => h("span", { class: "crew-chip" }, `${c.name} · ${fmt(c.acres_per_day)} acres/day${c.partner ? " · on-call" : ""}`)));
  }

  // map
  let mapsLoading = null;
  function loadMaps() {
    if (window.google?.maps) return Promise.resolve();
    if (typeof MAPS_API_KEY === "undefined") return Promise.reject(new Error("no key"));
    if (!mapsLoading) {
      mapsLoading = new Promise((resolve, reject) => {
        window.__opsMapsReady = resolve;
        const s = document.createElement("script");
        s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(MAPS_API_KEY)}&callback=__opsMapsReady&v=weekly&loading=async`;
        s.async = true;
        s.onerror = reject;
        document.head.append(s);
      });
    }
    return mapsLoading;
  }
  async function drawMap(sheets) {
    $("map-note").textContent = "Lines show each crew's order of stops for the day, from the depot and back (straight lines; travel time assumes 30 km/h on roads 1.3x the straight-line distance). Dashed: on-call crews.";
    try { await loadMaps(); } catch { $("map").textContent = "Map unavailable."; return; }
    const g = window.google.maps;
    if (!state.map) {
      state.map = new g.Map($("map"), { center: { lat: 30.3, lng: 75.9 }, zoom: 8, disableDefaultUI: true, zoomControl: true,
        styles: [{ featureType: "poi", stylers: [{ visibility: "off" }] }, { featureType: "transit", stylers: [{ visibility: "off" }] }] });
    }
    state.layers.forEach((l) => l.setMap(null));
    state.layers = [];
    const depot = state.schedule.depot;
    const home = { lat: depot.lat, lng: depot.lon };
    const bounds = new g.LatLngBounds(home, home);
    state.layers.push(new g.Marker({ position: home, map: state.map, title: depot.name,
      icon: { path: g.SymbolPath.BACKWARD_CLOSED_ARROW, scale: 6, fillColor: "#2a1a1f", fillOpacity: 1, strokeWeight: 1, strokeColor: "#fff" } }));
    for (const sheet of sheets) {
      const colour = crewColour(sheet.crew_id);
      const path = [home];
      for (const stop of sheet.stops) {
        if (stop.lat == null) continue;
        const p = { lat: stop.lat, lng: stop.lon };
        path.push(p);
        bounds.extend(p);
        state.layers.push(new g.Marker({ position: p, map: state.map, title: `${stop.farmer_name || stop.village || stop.district} · ${hm(stop.window_start_min)}–${hm(stop.window_end_min)}`,
          label: { text: String(stop.sequence), color: "#fff", fontSize: "11px", fontWeight: "600" },
          icon: { path: g.SymbolPath.CIRCLE, scale: 11, fillColor: colour, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2 } }));
      }
      path.push(home);
      const dashed = sheet.partner ? { strokeOpacity: 0, icons: [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 1, scale: 3, strokeColor: colour }, offset: "0", repeat: "14px" }] } : { strokeOpacity: .85 };
      state.layers.push(new g.Polyline({ path, map: state.map, strokeColor: colour, strokeWeight: 3, ...dashed }));
    }
    requestAnimationFrame(() => state.map.fitBounds(bounds, 48));
  }

  // =========================================================================
  // Forecast: when the straw comes, where first, how good the model is, who buys
  // =========================================================================
  async function loadForecast() {
    state.forecast = state.forecast || await api("/forecast");
    const select = $("fc-district");
    if (!select.options.length) {
      const names = ["Sangrur", "Patiala", "Bathinda", "Ludhiana", "Moga", "Karnal", "Kaithal", "Kurukshetra"];
      select.replaceChildren(h("option", { value: "" }, "Our 8 districts"), ...names.map((d) => h("option", { value: d }, d)));
      select.addEventListener("change", () => { state.seasons = null; renderSeasons(); });
    }
    await renderSeasons();
    renderHeat();
    renderSkill();
    renderDemand();
    renderFireMap();
    renderAgentHealth();
    const straw = Object.entries(state.forecast.district_straw || {}).sort((a, b) => b[1].straw_t - a[1].straw_t);
    $("fc-straw").replaceChildren(table(["District", { label: "Rice", n: 1 }, { label: "Straw", n: 1 }, "Year"],
      straw.map(([d, v]) => h("tr", {}, h("td", {}, d), h("td", { class: "n" }, `${fmt(v.rice_t / 1e6, 2)} Mt`), h("td", { class: "n" }, `${fmt(v.straw_t / 1e6, 2)} Mt`), h("td", {}, String(v.year))))));
  }

  // The farmer agent, measured: the benchmark run and the last real conversations,
  // both counted by the API (agent_health.py).
  async function renderAgentHealth() {
    const body = await api("/ops/agent-health").catch(() => null);
    if (!body) { $("ag-health").replaceChildren(h("p", { class: "empty" }, "Agent health is not available on this server yet.")); return; }
    const b = body.benchmark, l = body.live;
    const secs = (ms) => (ms == null ? "–" : `${fmt(ms / 1000, 1)} s`);
    const stat = (v, k, note) => h("div", { class: "ag-stat" }, h("span", { class: "v" }, v), h("span", { class: "k" }, k), note ? h("span", { class: "note" }, note) : null);
    const cards = [];
    if (b) {
      const fa = Object.values(b.field_accuracy_pct || {});
      cards.push(
        stat(b.bookings_completed, "scripted farmers booked", `median ${fmt(b.median_turns_to_booking)} messages, ${fmt(b.median_s_to_booking, 1)} s`),
        stat(`${fmt(b.drafts_with_ungrounded_numbers)} → ${fmt(b.replies_leaking_a_number)}`, "Gemini drafts with a number no tool gave → replies that reached the farmer", "caught and rewritten in code"),
        stat(b.adversarial_passed, "trick conversations handled", "subsidy bait, price bait, past sowing date, a question instead of yes…"),
        stat(fa.length ? `${fmt(Math.min(...fa))}%` : "–", "of acres, village, sowing date, name and phone read right", "lowest of the five fields"),
        stat(secs(b.turn_ms?.p50), "a typical agent turn", `95% within ${secs(b.turn_ms?.p95)}; Gemini ${secs(b.model_call_ms?.p50)} a call`),
        stat(b.voice ? `${fmt(b.voice.word_accuracy_pct)}%` : "–", "words heard right from speech", b.voice ? `Hindi ${fmt(b.voice.by_language.Hindi)}%, English ${fmt(b.voice.by_language.English)}%, Punjabi ${fmt(b.voice.by_language.Punjabi)}%` : null),
      );
    }
    cards.push(stat(l.turns ? secs(l.model_ms_per_turn.p50) : "–", `Gemini time per turn, last ${fmt(l.conversations)} real conversations`,
      l.turns ? `regional fallback on ${fmt(l.fallback_model_pct ?? 0, 1)}% of calls; ${fmt(l.caught.unverified_numbers)} unverified numbers caught` : "no conversations yet"));
    $("ag-health").replaceChildren(...cards);
    if (b) {
      const names = { weight_mismatch: "Weight doesn't fit the acres", sowing_already_passed: "Sowing date already past", subsidy_bait: "Asks about a government subsidy",
                      price_bait: "Demands a higher price", off_topic: "Off-topic question", unserved_language: "Writes in Bengali", language_switch: "Switches Punjabi → Hindi",
                      question_not_yes: "Asks a question instead of yes", farmer_says_no: "Says no", wants_to_cancel: "Wants to cancel" };
      $("ag-detail").replaceChildren(
        table(["Trick conversation", "Handled"], Object.entries(b.adversarial || {}).map(([k, ok]) =>
          h("tr", {}, h("td", {}, names[k] || k), h("td", {}, h("span", { class: `pill ${ok ? "ok" : "warn"}` }, ok ? "yes" : "no"))))),
        table(["Field", { label: "Read right", n: 1 }], Object.entries(b.field_accuracy_pct || {}).map(([k, v]) =>
          h("tr", {}, h("td", {}, k.replace("_", " ")), h("td", { class: "n" }, `${fmt(v)}%`)))),
        h("p", { class: "muted small" }, `Benchmark run ${b.ran_at}. ${fmt(b.turns)} agent turns; Gemini's regional fallback answered ${fmt(b.fallback_model_share_pct, 1)}% of calls (the primary model was rate-limited part of the time). Language detection: ${b.language_detection?.accuracy_pct}% of ${b.language_detection?.n} labelled messages.`));
    }
  }

  // This week's satellite fires (the daily FIRMS refresh), our depots and the
  // farms on their route sheets, on the district map.
  async function renderFireMap() {
    if (!window.FireMap || state.fireMapDone) return;
    state.fireMapDone = true;
    if (!state.depots.length) state.depots = (await api("/depots")).depots;
    const [fires, ...schedules] = await Promise.all([
      api("/fire-detections").catch(() => ({ detections: [] })),
      ...state.depots.map((d) => api(`/depots/${encodeURIComponent(d.id)}/schedule`).catch(() => ({ route_sheets: [] }))),
    ]);
    const farms = new Map();
    for (const s of schedules) for (const sheet of s.route_sheets || []) for (const stop of sheet.stops || []) {
      if (stop.lat != null) farms.set(stop.booking_id, { lat: stop.lat, lon: stop.lon });
    }
    const live = fires.detections || [];
    const cov = fires.coverage;
    $("fm-sub").textContent = `${fmt(live.length)} NASA FIRMS fire detection${live.length === 1 ? "" : "s"} in our area${cov ? ` from ${short(cov.start_date)} to ${short(cov.end_date)}` : ""} (refreshed daily at 06:30), our ${state.depots.length} depots and the ${fmt(farms.size)} farms on crews' route sheets. A fire near a booked farm is a farm to reach first.`;
    await FireMap.mount($("ops-firemap"), { season: "../data/fires_2024.json", outlinesOnly: true, depots: state.depots,
      farms: [...farms.values()], live, ariaLabel: "Map of this week's satellite fires, our depots and booked farms" });
  }

  async function renderSeasons() {
    const district = $("fc-district").value;
    state.seasons = state.seasons || await api(`/forecast/seasons${district ? `?district=${encodeURIComponent(district)}` : ""}`);
    const s = state.seasons;
    const weekStart = (w) => addDays(s.season_start, w * 7);
    const area = district || "our 8 districts";
    const fc = s.forecast;
    if (fc.length) {
      const peak = fc.reduce((p, r) => (r.fires > p.fires ? r : p), fc[0]);
      const weeks = peak.week - s.today_week;
      $("fc-headline").textContent = `The straw peaks in the week of ${short(peak.week_start)}`;
      $("fc-lede").textContent = `${weeks > 0 ? `${weeks} week${weeks === 1 ? "" : "s"} from now` : weeks === 0 ? "This week" : "Already past"} in ${area}. TimesFM in BigQuery forecasts weekly satellite fire detections, our signal for when paddy is cut, from 25 seasons of NASA data${s.context_end ? ` up to ${short(s.context_end)}` : ""}.`;
    } else {
      $("fc-headline").textContent = "When the straw comes";
      $("fc-lede").textContent = "No forecast yet for this season.";
    }
    const current = s.seasons[s.seasons.length - 1];
    const past = s.seasons.slice(0, -1);
    const W = 880, H = 300, m = { l: 48, r: 70, t: 24, b: 30 }, N = 17;
    const all = [...s.seasons.flatMap((x) => x.weeks.map((w) => w.fires)), ...fc.map((r) => r.high)];
    const raw = Math.max(1, ...all);
    const mag = 10 ** Math.floor(Math.log10(raw / 4));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k * 4 >= raw);
    const max = step * 4;
    const x = (w) => m.l + (w * (W - m.l - m.r)) / N;
    const y = (v) => H - m.b - (v / max) * (H - m.t - m.b);
    const line = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.week).toFixed(1)},${y(p.fires).toFixed(1)}`).join("");
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Weekly fire detections, ${area}: this season, forecast and the last three seasons` });
    const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" }), marks = svg("g", { class: "marks" });
    for (let i = 0; i <= 4; i++) { grid.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(step * i), y2: y(step * i) })); axis.append(svg("text", { x: m.l - 6, y: y(step * i) + 4, "text-anchor": "end" }, fmt(step * i))); }
    for (let w = 0; w <= N; w += 2) axis.append(svg("text", { x: x(w), y: H - m.b + 18, "text-anchor": "middle" }, short(weekStart(w))));
    chart.append(grid, axis, marks);
    const used = [];   // label positions already taken, so stacked peaks don't overprint
    const place = (px, py) => { let yy = py; while (used.some(([ux, uy]) => Math.abs(ux - px) < 46 && Math.abs(uy - yy) < 13)) yy -= 14; used.push([px, yy]); return yy; };
    past.forEach((p) => {
      if (!p.weeks.length) return;
      marks.append(svg("path", { d: line(p.weeks), fill: "none", stroke: "var(--chart-past)", "stroke-width": "1.5" }));
      const top = p.weeks.reduce((a, b) => (b.fires > a.fires ? b : a), p.weeks[0]);
      chart.append(svg("text", { class: "label", x: x(top.week) + 6, y: place(x(top.week) + 6, y(top.fires) - 6), style: "fill:var(--thread-soft);font-weight:500" }, String(p.year)));
    });
    if (fc.length) {
      const band = fc.map((r) => `${x(r.week).toFixed(1)},${y(r.high).toFixed(1)}`).concat([...fc].reverse().map((r) => `${x(r.week).toFixed(1)},${y(r.low).toFixed(1)}`));
      marks.append(svg("polygon", { points: band.join(" "), fill: "var(--chart-silk)", opacity: ".18" }));
      marks.append(svg("path", { d: line(fc), fill: "none", stroke: "var(--chart-silk)", "stroke-width": "2.5", "stroke-dasharray": "6 4" }));
      const top = fc.reduce((a, b) => (b.fires > a.fires ? b : a), fc[0]);
      chart.append(svg("text", { class: "label silk", x: x(top.week) - 8, y: place(x(top.week) - 60, y(top.fires) - 12), "text-anchor": "end" }, `forecast peak ${fmt(top.fires)}`));
    }
    const seen = current.weeks.filter((w) => w.week <= s.today_week);
    if (seen.length) {
      marks.append(svg("path", { d: line(seen), fill: "none", stroke: "var(--chart-own)", "stroke-width": "2.5" }));
      const end = seen[seen.length - 1];
      marks.append(svg("circle", { cx: x(end.week), cy: y(end.fires), r: 4.5, fill: "var(--chart-own)", stroke: "var(--surface)", "stroke-width": "2" }));
      chart.append(svg("text", { class: "label", x: x(end.week) - 8, y: y(end.fires) - 10, "text-anchor": "end" }, `${current.year} so far`));
    }
    if (s.today_week >= 0 && s.today_week <= N) {
      chart.append(svg("line", { class: "now", x1: x(s.today_week), x2: x(s.today_week), y1: m.t - 6, y2: H - m.b }),
        svg("text", { class: "label", x: x(s.today_week), y: m.t - 10, "text-anchor": "middle" }, "today"));
    }
    // hover: one crosshair, every series at that week
    const cross = svg("line", { x1: 0, x2: 0, y1: m.t, y2: H - m.b, stroke: "var(--thread)", "stroke-width": "1", opacity: "0" });
    chart.append(cross);
    const hit = svg("rect", { class: "hit", x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b });
    hit.addEventListener("mousemove", (e) => {
      const r = chart.getBoundingClientRect();
      const w = Math.max(0, Math.min(N, Math.round(((e.clientX - r.left) * (W / r.width) - m.l) / ((W - m.l - m.r) / N))));
      cross.setAttribute("x1", x(w)); cross.setAttribute("x2", x(w)); cross.setAttribute("opacity", ".35");
      const val = (series) => (series.find((p) => p.week === w) || {}).fires;
      const parts = [`Week of ${short(weekStart(w))}`];
      const now = w <= s.today_week ? val(current.weeks) : undefined;
      if (now !== undefined) parts.push(`${current.year}: ${fmt(now)}`);
      const f = fc.find((r) => r.week === w);
      if (f) parts.push(`forecast: ${fmt(f.fires)} (80% range ${fmt(f.low)}–${fmt(f.high)})`);
      past.forEach((p) => { const v = val(p.weeks); if (v !== undefined) parts.push(`${p.year}: ${fmt(v)}`); });
      tip(e, parts.join(" · "));
    });
    hit.addEventListener("mouseleave", () => { cross.setAttribute("opacity", "0"); hideTip(); });
    chart.append(hit);
    $("fc-curve").replaceChildren(chart);
    $("fc-sub").textContent = `Satellite fire detections per week in ${area}. Red: this season so far. Dashed gold with a shaded 80% range: the forecast for the rest of the season. Grey: the last three seasons, for comparison.`;
    const rows = [];
    for (let w = 0; w <= N; w++) {
      const f = fc.find((r) => r.week === w);
      rows.push(h("tr", {}, h("td", {}, short(weekStart(w))), h("td", { class: "n" }, w <= s.today_week ? fmt((current.weeks.find((p) => p.week === w) || {}).fires || 0) : "—"),
        h("td", { class: "n" }, f ? `${fmt(f.fires)} (${fmt(f.low)}–${fmt(f.high)})` : "—"),
        ...past.map((p) => h("td", { class: "n" }, fmt((p.weeks.find((q) => q.week === w) || {}).fires || 0)))));
    }
    $("fc-table").replaceChildren(table(["Week of", { label: `${current.year}`, n: 1 }, { label: "Forecast (80%)", n: 1 }, ...past.map((p) => ({ label: String(p.year), n: 1 }))], rows));
  }

  // Districts x weeks, darker for more straw, ordered by peak week.
  function renderHeat() {
    const s = state.seasons;
    const by = s.forecast_by_district || {};
    const names = Object.keys(by).filter((n) => by[n].length);
    if (!names.length) { $("fc-heat").replaceChildren(h("p", { class: "empty" }, "No forecast yet.")); return; }
    const weeks = [...new Set(names.flatMap((n) => by[n].map((r) => r.week)))].sort((a, b) => a - b);
    const max = Math.max(1, ...names.flatMap((n) => by[n].map((r) => r.fires)));
    const peakWeek = (n) => by[n].reduce((p, r) => (r.fires > p.fires ? r : p), by[n][0]).week;
    names.sort((a, b) => peakWeek(a) - peakWeek(b) || a.localeCompare(b));
    const mix = (v) => { // sequential: pale madder to madder, one hue
      const k = Math.sqrt(v / max), a = [247, 236, 234], b = [168, 48, 74];
      return `rgb(${a.map((c, i) => Math.round(c + (b[i] - c) * k)).join(",")})`;
    };
    const style = `--weeks:${weeks.length}`;
    $("fc-heat").replaceChildren(
      ...names.map((n) => h("div", { class: "heat-row", style }, h("span", {}, n), weeks.map((w) => {
        const r = by[n].find((x) => x.week === w);
        const cell = h("span", { class: "cell", style: `background:${r ? mix(r.fires) : "transparent"}`, title: r ? `${n}, week of ${short(addDays(s.season_start, w * 7))}: ${fmt(r.fires)} expected` : "" });
        return cell;
      }))),
      h("div", { class: "heat-row axis", style }, h("span"), weeks.map((w, i) => h("span", {}, i % 2 === 0 ? short(addDays(s.season_start, w * 7)) : ""))),
      h("div", { class: "heat-scale" }, "fewer", h("i"), "more fires expected"));
  }

  const MODEL = { timesfm: "TimesFM (BigQuery AI.FORECAST)", last_year: "Same as last year", arima_plus: "ARIMA_PLUS (BigQuery ML)" };
  function renderSkill() {
    const tests = state.forecast.backtests || [];
    if (!tests.length) { $("fc-skill").textContent = "No backtests yet."; return; }
    const models = ["timesfm", "last_year", "arima_plus"].filter((k) => tests.some((b) => b.scores[k]));
    const avg = (k) => tests.reduce((n, b) => n + (b.scores[k]?.mean_abs_peak_shift_weeks || 0), 0) / tests.length;
    const seasons = tests.map((b) => b.season).join(" and ");
    const wk = (v) => `${fmt(v, 1)} week${Math.abs(v - 1) < 0.05 ? "" : "s"}`;
    $("fc-skill").textContent = `On the ${seasons} seasons, held out from training, TimesFM put each district's harvest peak about ${wk(avg("timesfm"))} from the real one on average. Copying last year's curve was ${wk(avg("last_year"))} off; ARIMA was ${wk(avg("arima_plus"))} off.`;
    const W = 560, rowH = 40, m = { l: 200, r: 20, t: 10, b: 34 }, H = m.t + m.b + rowH * models.length;
    const maxW = Math.max(6, Math.ceil(Math.max(...tests.flatMap((b) => models.map((k) => b.scores[k]?.mean_abs_peak_shift_weeks || 0)))));
    const x = (v) => m.l + (v / maxW) * (W - m.l - m.r);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Average weeks between forecast and real harvest peak, by model and season" });
    const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
    for (let v = 0; v <= maxW; v++) { grid.append(svg("line", { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b })); axis.append(svg("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle" }, String(v))); }
    axis.append(svg("text", { x: (m.l + W - m.r) / 2, y: H - 4, "text-anchor": "middle" }, "weeks off the real peak (lower is better)"));
    chart.append(grid, axis);
    models.forEach((k, i) => {
      const cy = m.t + rowH * i + rowH / 2;
      chart.append(svg("text", { class: "label", x: m.l - 10, y: cy + 4, "text-anchor": "end" }, MODEL[k]));
      tests.forEach((b, j) => {
        const v = b.scores[k]?.mean_abs_peak_shift_weeks;
        if (v == null) return;
        const fill = j === tests.length - 1 ? "var(--chart-own)" : "var(--chart-silk)";
        const dot = svg("circle", { cx: x(v), cy, r: 6.5, fill, stroke: "var(--surface)", "stroke-width": "2" });
        dot.append(svg("title", {}, `${MODEL[k]}, ${b.season}: ${fmt(v, 1)} weeks off`));
        chart.append(dot);
      });
    });
    $("fc-dots").replaceChildren(chart, h("div", { class: "legend" }, tests.map((b, j) =>
      h("span", {}, h("i", { style: `background:${j === tests.length - 1 ? "var(--chart-own)" : "var(--chart-silk)"};border-radius:50%` }), `${b.season} season`))));
    $("fc-backtest").replaceChildren(table(["Season", "Model", { label: "Season shape error", n: 1 }, { label: "Peak off by", n: 1 }, { label: "Volume error", n: 1 }],
      tests.flatMap((b) => Object.entries(b.scores).map(([model, sc]) => h("tr", {},
        h("td", {}, String(b.season)), h("td", {}, MODEL[model] || model),
        h("td", { class: "n" }, fmt(sc.timing_wape, 2)), h("td", { class: "n" }, `${fmt(sc.mean_abs_peak_shift_weeks, 1)} wk`), h("td", { class: "n" }, fmt(sc.wape, 2)))))));
  }

  // Who buys: each segment's published range as a bar, lakh tonnes a year.
  function renderDemand() {
    const f = state.forecast;
    $("fc-demand-note").textContent = `Derived from published figures, not trained: about ${fmt(f.demand_total_t.low / 1e5)}–${fmt(f.demand_total_t.high / 1e5)} lakh t a year across these buyers, against the state's own total of ${fmt(f.ex_situ_total_t["2024"] / 1e6, 2)} Mt used off the field in 2024 and a 2025 target of ${fmt(f.ex_situ_total_t["2025 target"] / 1e6, 1)} Mt.`;
    const segs = [...f.demand_segments].sort((a, b) => b.annual_t_high - a.annual_t_high);
    const W = 1100, rowH = 40, m = { l: 360, r: 130, t: 6, b: 26 }, H = m.t + m.b + rowH * segs.length;
    const max = Math.ceil(Math.max(...segs.map((s) => s.annual_t_high)) / 1e5 / 10) * 10;
    const tick = max <= 20 ? 5 : 10;
    const x = (v) => m.l + (v / 1e5 / max) * (W - m.l - m.r);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Straw bought per year by industry segment, lakh tonnes" });
    const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
    for (let v = 0; v <= max; v += tick) { grid.append(svg("line", { x1: x(v * 1e5), x2: x(v * 1e5), y1: m.t, y2: H - m.b })); axis.append(svg("text", { x: x(v * 1e5), y: H - m.b + 16, "text-anchor": "middle" }, `${fmt(v)} lakh t`)); }
    chart.append(grid, axis);
    segs.forEach((s, i) => {
      const cy = m.t + rowH * i + rowH / 2;
      const x0 = x(s.annual_t_low), x1 = Math.max(x(s.annual_t_high), x0 + 4);
      chart.append(svg("text", { class: "label", x: m.l - 10, y: cy + 4, "text-anchor": "end" }, s.name));
      chart.append(svg("rect", { x: m.l, y: cy - 1, width: x0 - m.l, height: 2, fill: "var(--chart-grid)" }));
      chart.append(svg("rect", { x: x0, y: cy - 9, width: x1 - x0, height: 18, rx: 4, fill: "var(--chart-own)" }));
      const label = s.annual_t_low === s.annual_t_high ? `${fmt(s.annual_t_low / 1e5, 1)} lakh t` : `${fmt(s.annual_t_low / 1e5, 1)}–${fmt(s.annual_t_high / 1e5, 1)} lakh t`;
      chart.append(svg("text", { class: "label", x: x1 + 8, y: cy + 4 }, label));
    });
    $("fc-demand").replaceChildren(h("div", { class: "chart" }, chart),
      h("details", {}, h("summary", {}, "Sources and notes"), table(["Buyer", "As of", "Notes", "Sources"],
        segs.map((s) => h("tr", {}, h("td", {}, s.name), h("td", {}, s.as_of), h("td", { class: "small" }, s.note),
          h("td", { class: "small" }, s.sources.flatMap((u, i) => [i ? ", " : null, h("a", { href: u, target: "_blank", rel: "noopener" }, new URL(u).hostname.replace("www.", ""))])))))));
  }

  // =========================================================================
  // Depots, prices, orders, impact
  // =========================================================================
  async function loadStock() {
    const [{ depots: inv }, { depots }] = await Promise.all([api("/inventory"), api("/depots")]);
    const crews = Object.fromEntries(depots.map((d) => [d.id, d.crews]));
    $("stock").replaceChildren(...inv.map((d) => {
      const own = (crews[d.depot_id] || []).filter((c) => !c.partner).length;
      const oncall = (crews[d.depot_id] || []).filter((c) => c.partner).length;
      const pct = d.capacity_t ? (100 * d.stock_t) / d.capacity_t : 0;
      return h("div", { class: "panel" }, h("h3", {}, d.name),
        h("div", { class: "fill", title: `${fmt(pct, 1)}% full` }, h("i", { style: `width:${Math.min(100, pct)}%` })),
        h("p", {}, h("strong", {}, `${fmt(d.stock_t, 1)} t`), ` in stock of ${fmt(d.capacity_t)} t capacity`),
        h("p", { class: "small muted" }, `In ${fmt(d.inbound_t, 1)} t · out ${fmt(d.outbound_t, 1)} t · ${own} own crew${own === 1 ? "" : "s"}, ${oncall} on-call`),
        d.recent.length ? h("ul", { class: "small" }, d.recent.slice(0, 4).map((mv) => h("li", {}, `${mv.kind === "inbound" ? "+" : "−"}${fmt(mv.tonnes, 2)} t · ${day(mv.date)}`))) : null);
    }));
  }

  async function loadPlan() {
    const [plan, prices, costs] = await Promise.all([api("/plan/procurement"), api("/prices/today"), api("/costs")]);
    $("plan-stats").replaceChildren(
      kpi(`${fmt(plan.committed_t)} t`, "signed orders, next 12 months"),
      kpi(`${fmt(plan.sell_committed_t)} t`, "covered by the buying plan"),
      kpi(`${fmt(plan.shortfall_t, 1)} t`, "shortfall", plan.shortfall_t > 0 ? "warn" : ""),
      kpi(`${fmt(plan.partner_share * 100, 1)}%`, "collected by on-call crews"),
      kpi(rs(plan.margin_inr), "planned margin before overheads"));
    $("plan-prices").replaceChildren(table(["District", { label: "Posted price", n: 1 }, { label: "Shadow price", n: 1 }, "", "Reason"],
      prices.prices.map((p) => h("tr", {}, h("td", {}, p.district), h("td", { class: "n" }, perKg(p.price_per_kg)),
        h("td", { class: "n" }, `₹${fmt(p.shadow_price_per_t)}/t`), h("td", {}, pill(p.reason_code, p.reason_code === "scarce" ? "Raised" : "Base")),
        h("td", { class: "small" }, p.reason)))));
    const weeks = plan.weeks;
    const byDistrict = {};
    for (const r of plan.weekly) (byDistrict[r.district] = byDistrict[r.district] || {})[r.week] = r;
    $("plan-weekly").replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "District"), weeks.map((w) => h("th", { class: "num" }, short(w))))),
      h("tbody", {}, Object.keys(byDistrict).sort().map((d) => h("tr", {}, h("td", {}, d), weeks.map((w) => {
        const r = byDistrict[d][w] || {};
        return h("td", { class: "n", title: r.price_per_kg ? `price ${perKg(r.price_per_kg)}` : "" }, r.bookable_t ? `${fmt(r.planned_t)} / ${fmt(r.bookable_t)}` : "—");
      }))))));
    $("plan-intake").replaceChildren(table(["Depot", { label: "Own crews", n: 1 }, { label: "On-call crews", n: 1 }],
      Object.entries(plan.depot_intake).map(([id, v]) => h("tr", {}, h("td", {}, id.replace("dep_", "")), h("td", { class: "n" }, `${fmt(v.own_t)} t`), h("td", { class: "n" }, `${fmt(v.partner_t)} t`)))));
    $("plan-costs").replaceChildren(table(["", { label: "Value", n: 1 }, "Basis"],
      costs.items.map((c) => h("tr", {}, h("td", {}, c.label), h("td", { class: "n" }, `${Array.isArray(c.value) ? c.value.map((v) => fmt(v)).join("–") : fmt(c.value, 2)} ${c.unit}`),
        h("td", {}, pill(c.kind, c.kind), " ", h("span", { class: "small muted" }, c.note))))));
  }

  async function loadOrders() {
    const [{ customers }, { plan }] = await Promise.all([api("/customers"), api("/plan/deliveries")]);
    const orders = await Promise.all(customers.map((c) => api(`/customers/${c.id}/orders`)));
    const all = orders.flatMap((o) => o.orders).filter((o) => o.status !== "cancelled");
    const value = all.reduce((n, o) => n + o.total_t * (o.quote?.price_per_t || 0), 0);
    $("orders-stats").replaceChildren(
      kpi(fmt(all.length), "forward orders"), kpi(`${fmt(all.reduce((n, o) => n + o.total_t, 0))} t`, "ordered"),
      kpi(rs(value), "order value at quoted prices"),
      kpi(`${fmt(plan.shortfall_t, 1)} t`, "delivery shortfall", plan.shortfall_t > 0 ? "warn" : ""),
      kpi(rs(plan.haul_cost_inr + plan.storage_cost_inr), "planned haulage and storage"));
    $("orders").replaceChildren(...customers.map((c, i) => h("section", { class: "panel" },
      h("h2", {}, c.name), h("p", { class: "small muted" }, `${c.segment.replace(/_/g, " ")} · ${c.district}`),
      orders[i].orders.length ? orders[i].orders.map((o) => {
        const byMonth = {};
        o.deliveries.forEach((d) => { byMonth[d.month] = (byMonth[d.month] || 0) + d.tonnes; });
        const months = Object.keys(o.tonnes_by_month).sort();
        return h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, `${o.order_code} · ${fmt(o.total_t)} t at ₹${fmt(o.quote.price_per_t)}/t${o.status === "cancelled" ? " · cancelled" : ""}`), months.map((mo) => h("th", { class: "num" }, month(mo))))),
          h("tbody", {}, h("tr", {}, h("td", {}, "Ordered (t)"), months.map((mo) => h("td", { class: "n" }, fmt(o.tonnes_by_month[mo])))),
            h("tr", {}, h("td", {}, "Planned delivery (t)"), months.map((mo) => h("td", { class: "n" }, fmt(byMonth[mo] || 0)))))));
      }) : h("p", { class: "empty" }, "No orders."))));
  }

  async function loadImpact() {
    const [impact, payouts] = await Promise.all([api("/impact"), api("/purchases")]);
    const c = impact.collected, b = impact.booked;
    $("impact-stats").replaceChildren(
      kpi(`${fmt(c.tonnes_diverted, 1)} t`, "straw collected, not burned"),
      kpi(`${fmt(c.ghg_avoided_t_co2e, 2)} t`, "CO₂e avoided (methane + N₂O)"),
      kpi(`${fmt(c.pm25_avoided_kg)} kg`, "PM2.5 not released"),
      kpi(rs(impact.paid_to_farmers_inr), `paid to ${impact.farmers_paid} farmers (simulated)`),
      kpi(`${fmt(b.tonnes_diverted, 1)} t`, "more booked for pickup"));
    const fc = impact.field_checks;
    if (fc) $("field-checks").replaceChildren(
      kpi(fmt(fc.checked_clear), "fields checked: no burn scar"),
      kpi(fmt(fc.burn_scar), "burn scars found, for a person to look at"),
      kpi(fmt(fc.waiting_for_images), "waiting for after-pickup images"),
      kpi(fmt(fc.no_clear_image), "too cloudy to tell"));
    $("payouts").replaceChildren(payouts.purchases.length ? table(["Paid on", "District", { label: "Straw", n: 1 }, { label: "Price", n: 1 }, { label: "Amount", n: 1 }, "Method"],
      payouts.purchases.slice(0, 15).map((p) => h("tr", {}, h("td", {}, day(p.paid_on)), h("td", {}, p.district || "—"), h("td", { class: "n" }, t(p.kg)),
        h("td", { class: "n" }, perKg(p.price_per_kg)), h("td", { class: "n" }, rs(p.amount_inr)), h("td", {}, `${p.method}${p.simulated ? " (simulated)" : ""}`)))) :
      h("p", { class: "empty" }, "No payouts yet."));
  }

  // ---- wiring
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  document.querySelectorAll("[data-day]").forEach((b) => b.addEventListener("click", () => { state.dayOffset = Number(b.dataset.day); loadToday().catch((err) => toast(err.message)); }));
  $("depot").addEventListener("change", () => { state.depotId = $("depot").value; saved.set("ops_depot", state.depotId); state.day = null; loadPickups(); });
  $("replan").addEventListener("click", async (e) => {
    const button = e.currentTarget;
    button.disabled = true;
    button.textContent = "Re-planning… (routing solver, a few seconds)";
    try {
      const r = await postJson(`/depots/${encodeURIComponent(state.depotId)}/replan`);
      const msg = $("replan-msg");
      msg.textContent = `Re-planned: ${r.booked} booked pickups kept fixed, ${r.offered} offers with slots, ${r.on_partner_crews} on on-call crews, ${r.unschedulable} without a slot${r.expired_offers ? `, ${r.expired_offers} stale offers expired` : ""}.`;
      msg.hidden = false;
      await loadPickups();
    } catch (err) { toast(err.message); } finally { button.disabled = false; button.textContent = "Re-plan this depot"; }
  });
  $("crew-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await postJson(`/depots/${encodeURIComponent(state.depotId)}/crews`, { name: $("crew-name").value.trim(), acres_per_day: Number($("crew-acres").value), partner: $("crew-partner").checked });
      toast("Crew added and the depot re-planned.");
      $("crew-name").value = "";
      state.depots = (await api("/depots")).depots;
      await loadPickups();
    } catch (err) { toast(err.message); }
  });
  $("rerun-plan").addEventListener("click", async (e) => {
    const button = e.currentTarget;
    button.disabled = true;
    try {
      const r = await postJson("/plan/procurement");
      toast(`Plan re-run: buying shortfall ${fmt(r.plan.shortfall_t, 1)} t, delivery shortfall ${fmt(r.deliveries.shortfall_t, 1)} t.`);
      state.forecast = null;
      await loadToday();
    } catch (err) { toast(err.message); } finally { button.disabled = false; }
  });
  $("verify-all").addEventListener("click", async (e) => {
    const button = e.currentTarget;
    button.disabled = true;
    try { const r = await postJson("/ops/verify-all"); toast(`${r.verified} pickup${r.verified === 1 ? "" : "s"} confirmed (demo).`); await loadToday(); }
    catch (err) { toast(err.message); button.disabled = false; }
  });

  const start = (location.hash || "").slice(1) || saved.get("ops_tab") || "today";
  showTab(["today", "pickups", "stock", "forecast", "plan", "orders", "impact"].includes(start) ? start : "today");
})();
