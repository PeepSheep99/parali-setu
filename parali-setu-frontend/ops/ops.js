// Operations console. Display and actions only: prices from procurement.py,
// slots from scheduler.py, deliveries from deliveries.py, impact from
// impact.py, forecasts from BigQuery -- nothing is computed here.
(() => {
  const $ = (id) => document.getElementById(id);
  const CREW_COLOURS = ["#2b7d3a", "#2f6db5", "#8a5d06", "#7a3b8f", "#a23a1f", "#4b6b2f"];
  const OPERATING = ["Sangrur", "Patiala", "Bathinda", "Ludhiana", "Moga", "Karnal", "Kaithal", "Kurukshetra"];
  const state = { tab: "today", depotId: null, day: null, schedule: null, depots: [], map: null, layers: [], forecast: null };
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
  const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);
  const day = (iso) => {
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  };
  const month = (iso) => {
    const [y, m] = String(iso).split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
  };
  const stat = (v, k, warn) => h("div", { class: `stat${warn ? " warn" : ""}` }, h("span", { class: "v" }, v), h("span", { class: "k" }, k));
  const table = (head, rows) => h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map((c) => h("th", { class: c.n ? "num" : "" }, c.label || c)))),
    h("tbody", {}, rows)));
  const STATUS = { offered: "Offer out", unschedulable: "No slot", booked: "Booked", collected: "Collected", paid: "Paid" };
  const pill = (status) => h("span", { class: `pill ${status}` }, STATUS[status] || status);

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

  // ---- Today
  async function loadToday() {
    const [summary, depots] = await Promise.all([api("/ops/summary"), api("/depots")]);
    state.depots = depots.depots;
    const by = summary.bookings_by_status || {};
    $("today-date").textContent = day(summary.date);
    $("today-stats").replaceChildren(
      stat(fmt(summary.pickups_today), "booked pickups today"),
      stat(fmt(summary.tentative_today), "offered slots today, awaiting farmers"),
      stat(fmt(by.offered || 0), "offers out"),
      stat(fmt(by.booked || 0), "pickups booked"),
      stat(fmt(summary.on_partner_crews), "farms on partner crews today"),
      stat(`${fmt(summary.stock_t, 1)} t`, "straw in our depots"),
      stat(`${fmt(summary.procurement_shortfall_t || 0, 1)} t`, "order shortfall in the buying plan", summary.procurement_shortfall_t > 0),
      stat(`${fmt(summary.delivery_shortfall_t || 0, 1)} t`, "shortfall in the delivery plan", summary.delivery_shortfall_t > 0));
    const attention = [];
    if (by.unschedulable) attention.push(h("p", {}, `${by.unschedulable} farm(s) have no slot yet. `, h("a", { href: "#pickups", onclick: (e) => { e.preventDefault(); showTab("pickups"); } }, "See Pickups")));
    if (summary.procurement_shortfall_t > 0) attention.push(h("p", {}, `Signed orders need ${fmt(summary.procurement_shortfall_t, 1)} t more straw than the buying plan can source. `, h("a", { href: "#orders", onclick: (e) => { e.preventDefault(); showTab("orders"); } }, "See Orders")));
    if (summary.delivery_shortfall_t > 0) attention.push(h("p", {}, `${fmt(summary.delivery_shortfall_t, 1)} t of customer orders are short in the delivery plan; call the affected customers.`));
    if (summary.needs_attention.length) attention.push(h("p", {}, `${summary.needs_attention.length} booked pickup(s) could not be kept in the latest re-plan.`));
    $("today-attention").replaceChildren(...(attention.length ? attention : [h("p", { class: "empty" }, "Nothing needs a person right now.")]));
    const schedules = await Promise.all(state.depots.map((d) => api(`/depots/${d.id}/schedule`)));
    const today = summary.date;
    $("today-depots").replaceChildren(table(["Depot", { label: "Stops today", n: 1 }, { label: "Acres", n: 1 }, "Crews out"],
      schedules.map((s) => {
        const sheets = s.route_sheets.filter((r) => r.date === today);
        return h("tr", {}, h("td", {}, s.depot.name),
          h("td", { class: "n" }, fmt(sheets.reduce((n, r) => n + r.stops.length, 0))),
          h("td", { class: "n" }, fmt(sheets.reduce((n, r) => n + r.acres, 0), 1)),
          h("td", {}, sheets.map((r) => `${r.crew_name}${r.partner ? " (partner)" : ""}`).join(", ") || "—"));
      })));
  }

  // ---- Pickups
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
        h("div", { class: "sheet-head" }, h("h3", {}, sheet.crew_name, " ", sheet.partner ? h("span", { class: "pill partner" }, "Partner crew") : null),
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
    if (stop.status === "booked") {
      actions.push(h("button", { type: "button", class: "primary", onclick: (e) => markCollected(stop, e.currentTarget) }, "Mark collected"));
    } else if (stop.status === "offered") {
      actions.push(h("span", { class: "small muted" }, "Waiting for the farmer"));
      actions.push(h("button", { type: "button", class: "ghost small-btn", title: "Demo only: accept on the farmer's behalf", onclick: (e) => acceptForFarmer(stop, e.currentTarget) }, "Accept for farmer (demo)"));
    } else actions.push(pill(stop.status));
    const work = (stop.planned_end_min || 0) - (stop.planned_start_min || 0);
    return h("div", { class: "stop" },
      h("span", { class: "seq" }, stop.sequence),
      h("div", { class: "what" },
        h("strong", {}, stop.village || stop.district || "Farm", " ", pill(stop.status)),
        h("span", { class: "small" }, `Arrival window ${hm(stop.window_start_min)}–${hm(stop.window_end_min)} · planned start ${hm(stop.planned_start_min)}, work about ${dur(work)}`),
        h("span", { class: "small muted" }, `${fmt(stop.acres, 1)} acres · ${t(stop.kg)} · ${perKg(stop.price_per_kg)} · sow by ${stop.sowing_deadline ? day(stop.sowing_deadline) : "not given"}${stop.contact ? ` · ${stop.contact}` : ""}${stop.location_approximate ? " · location approximate" : ""}`)),
      h("div", { class: "act" }, actions));
  }

  async function acceptForFarmer(stop, button) {
    button.disabled = true;
    try {
      await postJson(`/ops/bookings/${encodeURIComponent(stop.booking_id)}/accept`);
      toast("Accepted for the farmer (demo). The slot is now locked.");
      await loadPickups();
    } catch (err) { toast(err.message); button.disabled = false; }
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
      rows.map((r) => h("tr", {}, h("td", {}, r.village || r.district), h("td", { class: "n" }, t(r.kg)),
        h("td", {}, r.sowing_deadline ? day(r.sowing_deadline) : "—"), h("td", {}, r.reason || "—"),
        h("td", {}, r.reason_code === "booked" || r.reason_code === "no_capacity" ? "Add a crew below, then re-plan" : "Call the farmer")))) :
      h("p", { class: "empty" }, "Every booked farm at this depot has a slot."));
  }

  function renderCrews() {
    const depot = state.depots.find((d) => d.id === state.depotId);
    $("crews").replaceChildren(...(depot?.crews || []).map((c) => h("span", { class: "crew-chip" }, `${c.name} · ${fmt(c.acres_per_day)} acres/day${c.partner ? " · partner" : ""}`)));
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
    $("map-note").textContent = "Lines show each crew's order of stops for the day, from the depot and back (straight lines; travel time assumes 30 km/h on roads 1.3x the straight-line distance). Dashed: partner crews.";
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
      icon: { path: g.SymbolPath.BACKWARD_CLOSED_ARROW, scale: 6, fillColor: "#1b2117", fillOpacity: 1, strokeWeight: 1, strokeColor: "#fff" } }));
    for (const sheet of sheets) {
      const colour = crewColour(sheet.crew_id);
      const path = [home];
      for (const stop of sheet.stops) {
        if (stop.lat == null) continue;
        const pos = { lat: stop.lat, lng: stop.lon };
        path.push(pos);
        bounds.extend(pos);
        state.layers.push(new g.Marker({ position: pos, map: state.map, title: `${stop.village || stop.district} · ${hm(stop.window_start_min)}–${hm(stop.window_end_min)}`,
          label: { text: String(stop.sequence), color: "#fff", fontSize: "11px", fontWeight: "600" },
          icon: { path: g.SymbolPath.CIRCLE, scale: 11, fillColor: colour, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2 } }));
      }
      path.push(home);
      const dashed = sheet.partner ? { strokeOpacity: 0, icons: [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 1, scale: 3, strokeColor: colour }, offset: "0", repeat: "14px" }] } : { strokeOpacity: .85 };
      state.layers.push(new g.Polyline({ path, map: state.map, strokeColor: colour, strokeWeight: 3, ...dashed }));
    }
    // Fit once the map has a size (the tab may have just become visible).
    requestAnimationFrame(() => state.map.fitBounds(bounds, 48));
  }

  // ---- Depots & stock
  async function loadStock() {
    const [{ depots: inv }, { depots }] = await Promise.all([api("/inventory"), api("/depots")]);
    const crews = Object.fromEntries(depots.map((d) => [d.id, d.crews]));
    $("stock").replaceChildren(...inv.map((d) => {
      const own = (crews[d.depot_id] || []).filter((c) => !c.partner).length;
      const partner = (crews[d.depot_id] || []).filter((c) => c.partner).length;
      const pct = d.capacity_t ? (100 * d.stock_t) / d.capacity_t : 0;
      return h("div", { class: "panel" }, h("h3", {}, d.name),
        h("div", { class: "fill", title: `${fmt(pct, 1)}% full` }, h("i", { style: `width:${Math.min(100, pct)}%` })),
        h("p", {}, h("strong", {}, `${fmt(d.stock_t, 1)} t`), ` in stock of ${fmt(d.capacity_t)} t capacity`),
        h("p", { class: "small muted" }, `In ${fmt(d.inbound_t, 1)} t · out ${fmt(d.outbound_t, 1)} t · ${own} own crew${own === 1 ? "" : "s"}, ${partner} partner`),
        d.recent.length ? h("ul", { class: "small" }, d.recent.slice(0, 4).map((m) => h("li", {}, `${m.kind === "inbound" ? "+" : "−"}${fmt(m.tonnes, 2)} t · ${day(m.date)}`))) : null);
    }));
  }

  // ---- Forecast
  async function loadForecast() {
    state.forecast = state.forecast || await api("/forecast");
    const f = state.forecast;
    const select = $("fc-district");
    if (!select.options.length) {
      const districts = Object.keys(f.supply_live?.districts || {}).sort();
      select.replaceChildren(h("option", { value: "__ops" }, "Our 8 districts"), h("option", { value: "__all" }, "All Punjab & Haryana"),
        ...districts.map((d) => h("option", { value: d }, d)));
      select.addEventListener("change", renderForecastChart);
    }
    renderForecastChart();
    const scores = (b) => b.scores;
    $("fc-backtest").replaceChildren(table(["Season", "Model", { label: "Season shape error", n: 1 }, { label: "Peak off by", n: 1 }, { label: "Volume error", n: 1 }],
      (f.backtests || []).flatMap((b) => Object.entries(scores(b)).map(([model, s]) => h("tr", {},
        h("td", {}, String(b.season)), h("td", {}, { timesfm: "TimesFM (BigQuery AI.FORECAST)", arima_plus: "ARIMA_PLUS (BigQuery ML)", last_year: "Same as last year" }[model] || model),
        h("td", { class: "n" }, fmt(s.timing_wape, 2)), h("td", { class: "n" }, `${fmt(s.mean_abs_peak_shift_weeks, 1)} wk`), h("td", { class: "n" }, fmt(s.wape, 2)))))));
    const straw = Object.entries(f.district_straw || {}).sort((a, b) => b[1].straw_t - a[1].straw_t);
    $("fc-straw").replaceChildren(table(["District", { label: "Rice", n: 1 }, { label: "Straw", n: 1 }, "Year"],
      straw.map(([d, v]) => h("tr", {}, h("td", {}, d), h("td", { class: "n" }, `${fmt(v.rice_t / 1e6, 2)} Mt`), h("td", { class: "n" }, `${fmt(v.straw_t / 1e6, 2)} Mt`), h("td", {}, String(v.year))))));
    $("fc-demand-note").textContent = `Derived from published figures, not trained: about ${fmt(f.demand_total_t.low / 1e5)}–${fmt(f.demand_total_t.high / 1e5)} lakh t a year across these segments, against the state's own ex-situ total of ${fmt(f.ex_situ_total_t["2024"] / 1e6, 2)} Mt in 2024 and a 2025 target of ${fmt(f.ex_situ_total_t["2025 target"] / 1e6, 1)} Mt.`;
    $("fc-demand").replaceChildren(table(["Segment", { label: "Straw a year", n: 1 }, "As of", "Notes", "Sources"],
      f.demand_segments.map((s) => h("tr", {}, h("td", {}, s.name),
        h("td", { class: "n" }, s.annual_t_low === s.annual_t_high ? `${fmt(s.annual_t_low / 1e5, 1)} lakh t` : `${fmt(s.annual_t_low / 1e5, 1)}–${fmt(s.annual_t_high / 1e5, 1)} lakh t`),
        h("td", {}, s.as_of), h("td", { class: "small" }, s.note),
        h("td", { class: "small" }, s.sources.flatMap((u, i) => [i ? ", " : null, h("a", { href: u, target: "_blank", rel: "noopener" }, new URL(u).hostname.replace("www.", ""))]))))));
  }

  function forecastSeries() {
    const live = state.forecast.supply_live;
    const pick = $("fc-district").value;
    const names = pick === "__all" ? Object.keys(live.districts) : pick === "__ops" ? OPERATING.filter((d) => live.districts[d]) : [pick];
    const weeks = {};
    for (const d of names) for (const w of live.districts[d] || []) {
      const row = (weeks[w.week] = weeks[w.week] || { week: w.week, value: 0, low: 0, high: 0 });
      row.value += w.fire_pixels; row.low += w.low; row.high += w.high;
    }
    const observed = names.reduce((n, d) => n + (live.observed_to_date[d] || 0), 0);
    return { rows: Object.values(weeks).sort((a, b) => a.week.localeCompare(b.week)), observed, label: pick.startsWith("__") ? $("fc-district").selectedOptions[0].textContent : pick };
  }

  function renderForecastChart() {
    const live = state.forecast.supply_live;
    if (!live) { $("fc-chart").replaceChildren(h("p", { class: "empty" }, "No forecast yet: run forecast.pipeline live.")); return; }
    const { rows, observed, label } = forecastSeries();
    const total = rows.reduce((n, r) => n + r.value, 0);
    $("fc-sub").textContent = `${label}: weekly satellite fire detections expected (a proxy for straw coming off the fields), forecast by TimesFM in BigQuery from data up to ${day(live.context_end)}. ${fmt(observed)} detections observed so far this season; ${fmt(total)} expected in the remaining weeks. Bars: forecast; whiskers: 80% interval.`;
    const W = 860, H = 280, m = { l: 48, r: 12, t: 22, b: 34 };
    const raw = Math.max(1, ...rows.map((r) => r.high));
    const mag = 10 ** Math.floor(Math.log10(raw / 4));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k * 4 >= raw);
    const max = step * 4;   // four round gridlines that cover the highest whisker
    const x = (i) => m.l + (i * (W - m.l - m.r)) / rows.length;
    const bw = Math.max(6, (W - m.l - m.r) / rows.length - 8);
    const y = (v) => H - m.b - (v / max) * (H - m.t - m.b);
    const ticks = 4;
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Weekly forecast for ${label}` });
    const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
    for (let i = 0; i <= ticks; i++) {
      const v = step * i;
      grid.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
      axis.append(svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    }
    chart.append(grid, axis);
    const peak = rows.reduce((p, r, i) => (r.value > rows[p].value ? i : p), 0);
    rows.forEach((r, i) => {
      const cx = x(i) + bw / 2 + 4;
      const g = svg("g", {});
      const bar = svg("path", { class: "bar-f", d: barPath(cx - bw / 2, y(r.value), bw, y(0) - y(r.value)) });
      const whisker = svg("line", { class: "band", x1: cx, x2: cx, y1: y(r.low), y2: y(r.high) });
      const hit = svg("rect", { class: "hit", x: x(i), y: m.t, width: (W - m.l - m.r) / rows.length, height: H - m.t - m.b });
      hit.addEventListener("mousemove", (e) => { bar.classList.add("on"); tip(e, `${day(r.week)} week: ${fmt(r.value)} expected (80% range ${fmt(r.low)}–${fmt(r.high)})`); });
      hit.addEventListener("mouseleave", () => { bar.classList.remove("on"); $("tooltip").hidden = true; });
      g.append(bar, whisker, hit);
      if (i % Math.ceil(rows.length / 8) === 0 || i === rows.length - 1) axis.append(svg("text", { x: cx, y: H - m.b + 16, "text-anchor": "middle" }, day(r.week).replace(/^\w+, /, "")));
      if (i === peak) chart.append(svg("text", { class: "label", x: cx, y: y(r.high) - 6, "text-anchor": "middle" }, `peak ${fmt(r.value)}`));
      chart.append(g);
    });
    $("fc-chart").replaceChildren(chart);
    $("fc-table").replaceChildren(table(["Week starting", { label: "Expected", n: 1 }, { label: "80% low", n: 1 }, { label: "80% high", n: 1 }],
      rows.map((r) => h("tr", {}, h("td", {}, day(r.week)), h("td", { class: "n" }, fmt(r.value)), h("td", { class: "n" }, fmt(r.low)), h("td", { class: "n" }, fmt(r.high))))));
  }
  function barPath(x0, y0, w, hgt) {   // 4px rounded data-end, square at the baseline
    const r = Math.min(4, w / 2, Math.max(0, hgt));
    return `M${x0},${y0 + hgt}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + hgt}Z`;
  }
  function tip(e, text) {
    const el = $("tooltip");
    el.textContent = text;
    el.hidden = false;
    el.style.left = `${Math.min(e.clientX + 12, window.innerWidth - 270)}px`;
    el.style.top = `${e.clientY + 12}px`;
  }

  // ---- Prices & plan
  async function loadPlan() {
    const [plan, prices, costs] = await Promise.all([api("/plan/procurement"), api("/prices/today"), api("/costs")]);
    $("plan-stats").replaceChildren(
      stat(`${fmt(plan.committed_t)} t`, "signed orders, next 12 months"),
      stat(`${fmt(plan.sell_committed_t)} t`, "of that covered by the buying plan"),
      stat(`${fmt(plan.shortfall_t, 1)} t`, "shortfall", plan.shortfall_t > 0),
      stat(`${fmt(plan.partner_share * 100, 1)}%`, "collected by partner crews"),
      stat(rs(plan.margin_inr), "planned margin (before overheads)"));
    $("plan-prices").replaceChildren(table(["District", { label: "Posted price", n: 1 }, { label: "Shadow price", n: 1 }, "", "Reason"],
      prices.prices.map((p) => h("tr", {}, h("td", {}, p.district), h("td", { class: "n" }, perKg(p.price_per_kg)),
        h("td", { class: "n" }, `₹${fmt(p.shadow_price_per_t)}/t`), h("td", {}, h("span", { class: `pill ${p.reason_code}` }, p.reason_code === "scarce" ? "Raised" : "Base")),
        h("td", { class: "small" }, p.reason)))));
    const weeks = plan.weeks;
    const byDistrict = {};
    for (const r of plan.weekly) (byDistrict[r.district] = byDistrict[r.district] || {})[r.week] = r;
    $("plan-weekly").replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "District"), weeks.map((w) => h("th", { class: "num" }, day(w).replace(/^\w+, /, ""))))),
      h("tbody", {}, Object.keys(byDistrict).sort().map((d) => h("tr", {}, h("td", {}, d), weeks.map((w) => {
        const r = byDistrict[d][w] || {};
        return h("td", { class: "n", title: r.price_per_kg ? `price ${perKg(r.price_per_kg)}` : "" }, r.bookable_t ? `${fmt(r.planned_t)} / ${fmt(r.bookable_t)}` : "—");
      }))))));
    $("plan-intake").replaceChildren(table(["Depot", { label: "Own crews", n: 1 }, { label: "Partner crews", n: 1 }],
      Object.entries(plan.depot_intake).map(([id, v]) => h("tr", {}, h("td", {}, id.replace("dep_", "")), h("td", { class: "n" }, `${fmt(v.own_t)} t`), h("td", { class: "n" }, `${fmt(v.partner_t)} t`)))));
    $("plan-costs").replaceChildren(table(["", { label: "Value", n: 1 }, "Basis"],
      costs.items.map((c) => h("tr", {}, h("td", {}, c.label), h("td", { class: "n" }, `${Array.isArray(c.value) ? c.value.map((v) => fmt(v)).join("–") : fmt(c.value, 2)} ${c.unit}`),
        h("td", {}, h("span", { class: `pill ${c.kind}` }, c.kind), " ", h("span", { class: "small muted" }, c.note))))));
  }

  // ---- Orders
  async function loadOrders() {
    const [{ customers }, { plan }] = await Promise.all([api("/customers"), api("/plan/deliveries")]);
    const orders = await Promise.all(customers.map((c) => api(`/customers/${c.id}/orders`)));
    const all = orders.flatMap((o) => o.orders);
    const value = all.reduce((n, o) => n + o.total_t * (o.quote?.price_per_t || 0), 0);
    $("orders-stats").replaceChildren(
      stat(fmt(all.length), "forward orders"), stat(`${fmt(all.reduce((n, o) => n + o.total_t, 0))} t`, "ordered"),
      stat(rs(value), "order value at quoted prices"),
      stat(`${fmt(plan.shortfall_t, 1)} t`, "delivery shortfall", plan.shortfall_t > 0),
      stat(rs(plan.haul_cost_inr + plan.storage_cost_inr), "planned haulage + storage"));
    $("orders").replaceChildren(...customers.map((c, i) => h("section", { class: "panel" },
      h("h2", {}, c.name), h("p", { class: "small muted" }, `${c.segment.replace(/_/g, " ")} · ${c.district}`),
      orders[i].orders.length ? orders[i].orders.map((o) => {
        const byMonth = {};
        o.deliveries.forEach((d) => { byMonth[d.month] = (byMonth[d.month] || 0) + d.tonnes; });
        const months = Object.keys(o.tonnes_by_month).sort();
        return h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, `Order · ${fmt(o.total_t)} t at ₹${fmt(o.quote.price_per_t)}/t`), months.map((m) => h("th", { class: "num" }, month(m))))),
          h("tbody", {}, h("tr", {}, h("td", {}, "Ordered (t)"), months.map((m) => h("td", { class: "n" }, fmt(o.tonnes_by_month[m])))),
            h("tr", {}, h("td", {}, "Planned delivery (t)"), months.map((m) => h("td", { class: "n" }, fmt(byMonth[m] || 0)))))));
      }) : h("p", { class: "empty" }, "No orders."))));
  }

  // ---- Impact
  async function loadImpact() {
    const [impact, payouts] = await Promise.all([api("/impact"), api("/purchases")]);
    const c = impact.collected, b = impact.booked;
    $("impact-stats").replaceChildren(
      stat(`${fmt(c.tonnes_diverted, 1)} t`, "straw collected, not burned"),
      stat(`${fmt(c.ghg_avoided_t_co2e, 2)} t`, "CO₂e avoided (methane + N₂O)"),
      stat(`${fmt(c.pm25_avoided_kg)} kg`, "PM2.5 not released"),
      stat(rs(impact.paid_to_farmers_inr), `paid to ${impact.farmers_paid} farmers (simulated)`),
      stat(`${fmt(b.tonnes_diverted, 1)} t`, "more booked for pickup"));
    $("payouts").replaceChildren(payouts.purchases.length ? table(["Paid on", "District", { label: "Straw", n: 1 }, { label: "Price", n: 1 }, { label: "Amount", n: 1 }, "Method"],
      payouts.purchases.slice(0, 15).map((p) => h("tr", {}, h("td", {}, day(p.paid_on)), h("td", {}, p.district || "—"), h("td", { class: "n" }, t(p.kg)),
        h("td", { class: "n" }, perKg(p.price_per_kg)), h("td", { class: "n" }, rs(p.amount_inr)), h("td", {}, `${p.method}${p.simulated ? " (simulated)" : ""}`)))) :
      h("p", { class: "empty" }, "No payouts yet."));
  }

  // ---- wiring
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("depot").addEventListener("change", () => { state.depotId = $("depot").value; saved.set("ops_depot", state.depotId); state.day = null; loadPickups(); });
  $("replan").addEventListener("click", async (e) => {
    const button = e.currentTarget;
    button.disabled = true;
    button.textContent = "Re-planning… (routing solver, a few seconds)";
    try {
      const r = await postJson(`/depots/${encodeURIComponent(state.depotId)}/replan`);
      const msg = $("replan-msg");
      msg.textContent = `Re-planned: ${r.booked} booked pickups kept fixed, ${r.offered} offers with slots, ${r.on_partner_crews} on partner crews, ${r.unschedulable} without a slot${r.expired_offers ? `, ${r.expired_offers} stale offers expired` : ""}.`;
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
      toast(`Plan re-run: shortfall ${fmt(r.plan.shortfall_t, 1)} t, delivery shortfall ${fmt(r.deliveries.shortfall_t, 1)} t. Today's prices updated.`);
      state.forecast = null;
      await loadToday();
    } catch (err) { toast(err.message); } finally { button.disabled = false; }
  });

  const start = (location.hash || "").slice(1) || saved.get("ops_tab") || "today";
  showTab(["today", "pickups", "stock", "forecast", "plan", "orders", "impact"].includes(start) ? start : "today");
})();
