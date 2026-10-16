// Buyer console. Display and actions only: every number comes from the API
// (planning from scheduler.py, prices from solver.py, impact from impact.py).
(() => {
  const $ = (id) => document.getElementById(id);
  const CREW_COLOURS = ["#2f6b3b", "#1f5f8b", "#9a6a08", "#7a3b8f"];
  const state = { companyId: null, tab: "ops", day: null, data: null, map: null, mapLayers: [] };

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
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.hidden = true; }, 5000);
  }
  async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try { body = await resp.json(); } catch { /* no body */ }
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${resp.status})`);
    return body;
  }
  const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  const kg = (n) => `${Math.round(n).toLocaleString("en-IN")} kg`;
  const tonnes = (n) => `${(n / 1000).toLocaleString("en-IN", { maximumFractionDigits: 1 })} t`;
  const rupees = (n) => `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const dayLabel = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  };
  const cropName = (c) => (c === "wheat_stubble" ? "Wheat" : c === "rice_stubble" ? "Paddy" : "—");
  const STATUS_TEXT = { proposed: "Offered", waitlisted: "Waitlisted", scheduled: "Booked", collected: "Collected", paid: "Paid", rejected: "Rejected" };
  const pill = (status) => h("span", { class: `pill ${status}` }, STATUS_TEXT[status] || status);

  // ---- loading
  async function loadCompanies() {
    const { companies } = await api("/companies");
    const select = $("company");
    select.replaceChildren(...companies.map((c) => h("option", { value: c.id },
      `${c.name}${c.depot_district ? ` · ${c.depot_district} depot` : ""}`)));
    const remembered = saved.get("parali_buyer");
    state.companyId = companies.some((c) => c.id === remembered) ? remembered : companies[0]?.id;
    select.value = state.companyId;
  }

  async function loadAll() {
    const id = encodeURIComponent(state.companyId);
    const [schedule, dashboard, demand, impact, fleet] = await Promise.all([
      api(`/buyers/${id}/schedule`), api(`/companies/${id}/dashboard`), api(`/companies/${id}/demand`),
      api(`/buyers/${id}/impact`), api(`/buyers/${id}/fleet`),
    ]);
    state.data = { schedule, dashboard, demand, impact, fleet };
    const days = [...new Set(schedule.route_sheets.map((s) => s.date))];
    if (!days.includes(state.day)) state.day = days[0] || null;
    renderSummary();
    renderOps();
    renderSupply();
    renderDemand();
    renderImpact();
  }

  // ---- summary strip
  function renderSummary() {
    const { dashboard, schedule, impact } = state.data;
    const matches = dashboard.active_matches.filter((m) => m.status !== "rejected");
    const count = (s) => matches.filter((m) => m.status === s).length;
    const stats = [
      [matches.length, "farms matched"],
      [count("scheduled"), "pickups booked"],
      [count("proposed"), "offers awaiting farmer"],
      [schedule.waitlist.length, "on the waitlist"],
      [tonnes(impact.collected.tonnes_diverted * 1000), "collected so far"],
      [rupees(impact.payouts_inr), "paid to farmers"],
    ];
    $("summary").replaceChildren(...stats.map(([v, k]) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "k" }, k))));
  }

  // ---- Pickup Ops
  function crewColour(crewId) {
    const crews = state.data.fleet.crews.map((c) => c.id).sort();
    return CREW_COLOURS[Math.max(0, crews.indexOf(crewId)) % CREW_COLOURS.length];
  }
  function crewName(crewId) {
    const crew = state.data.fleet.crews.find((c) => c.id === crewId);
    return crew?.name || crewId;
  }

  function renderOps() {
    const { schedule, fleet } = state.data;
    $("attention").replaceChildren(...schedule.needs_attention.map((a) =>
      h("p", { class: "alert" }, `Booked pickup needs attention (${a.place || a.match_id}): ${a.note}`)));

    const days = [...new Set(schedule.route_sheets.map((s) => s.date))];
    $("days").replaceChildren(...days.map((d) => {
      const stops = schedule.route_sheets.filter((s) => s.date === d).reduce((n, s) => n + s.stops.length, 0);
      return h("button", { type: "button", role: "tab", "aria-selected": String(d === state.day),
        onclick: () => { state.day = d; renderOps(); } }, dayLabel(d), h("span", { class: "n" }, `${stops} stops`));
    }));

    const sheets = schedule.route_sheets.filter((s) => s.date === state.day);
    if (!sheets.length) {
      $("sheets").replaceChildren(h("p", { class: "card empty" }, "No pickups planned yet. New matches are planned automatically; use Re-plan after adding demand."));
    } else {
      const crewById = Object.fromEntries(fleet.crews.map((c) => [c.id, c]));
      $("sheets").replaceChildren(...sheets.map((sheet) => {
        const colour = crewColour(sheet.crew_id);
        const capacity = crewById[sheet.crew_id]?.acres_per_day || 20;
        return h("div", { class: "card sheet", style: `--crew:${colour}` },
          h("div", { class: "sheet-head" }, h("h3", {}, crewName(sheet.crew_id)),
            h("span", { class: "load" }, `${sheet.acres} / ${capacity} acres`)),
          h("div", { class: "load-bar" }, h("i", { style: `width:${Math.min(100, (100 * sheet.acres) / capacity)}%` })),
          ...sheet.stops.map((stop) => stopRow(stop)));
      }));
    }

    if (!schedule.waitlist.length) {
      $("waitlist").replaceChildren(h("p", { class: "card empty" }, "Nobody is waiting: every matched farm has a slot."));
    } else {
      $("waitlist").replaceChildren(h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Farm", "Crop", "Quantity", "Why waiting", ""].map((c) => h("th", {}, c)))),
        h("tbody", {}, schedule.waitlist.map((w) => h("tr", {},
          h("td", {}, w.place || "—", w.location_approximate ? [" ", h("span", { class: "pill approx" }, "approx.")] : null),
          h("td", {}, cropName(w.crop_type)), h("td", { class: "num" }, kg(w.matched_kg)),
          h("td", {}, w.reason || "—"),
          h("td", {}, h("button", { type: "button", class: "ghost danger", onclick: () => reject(w.match_id) }, "Release"))))))));
    }
    drawMap(sheets);
  }

  function stopRow(stop) {
    const action = stop.status === "scheduled"
      ? h("button", { type: "button", class: "ghost", onclick: (e) => markCollected(stop, e.currentTarget) }, "Mark collected")
      : stop.status === "proposed" ? h("span", { class: "small muted" }, "Awaiting farmer") : pill(stop.status);
    return h("div", { class: "stop" },
      h("span", { class: "seq" }, stop.sequence),
      h("div", { class: "what" },
        h("span", { class: "when" }, `${hm(stop.window_start_min)}–${hm(stop.window_end_min)}`, stop.locked ? "  · promised" : ""),
        h("span", {}, stop.place || "—", " ", stop.location_approximate ? h("span", { class: "pill approx" }, "approx.") : null),
        h("span", { class: "meta" }, `${cropName(stop.crop_type)} · ${stop.acres} acres · ${kg(stop.matched_kg)} · ${rupees(stop.price_agreed_per_kg)}/kg`)),
      action);
  }

  async function markCollected(stop, button) {
    button.disabled = true;
    try {
      const { payout } = await postJson(`/stops/${encodeURIComponent(stop.match_id)}/collected`, {});
      toast(`Collected ${kg(payout.kg)} from ${stop.place || "farm"} · ${rupees(payout.amount_inr)} paid to the farmer (simulated)`);
      await loadAll();
    } catch (err) {
      toast(err.message);
      button.disabled = false;
    }
  }

  async function reject(matchId) {
    try {
      await postJson(`/matches/${encodeURIComponent(matchId)}/status`, { status: "rejected", reason: "Released by buyer" });
      toast("Released. The farm's quantity is back in the market.");
      await loadAll();
    } catch (err) {
      toast(err.message);
    }
  }

  // ---- map
  let mapsLoading = null;
  function loadMaps() {
    if (window.google?.maps) return Promise.resolve();
    if (typeof MAPS_API_KEY === "undefined") return Promise.reject(new Error("no key"));
    if (!mapsLoading) {
      mapsLoading = new Promise((resolve, reject) => {
        window.__paraliMapsReady = resolve;
        const s = document.createElement("script");
        s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(MAPS_API_KEY)}&callback=__paraliMapsReady&v=weekly`;
        s.async = true;
        s.onerror = reject;
        document.head.append(s);
      });
    }
    return mapsLoading;
  }

  async function drawMap(sheets) {
    const company = state.data.fleet.company || {};
    $("map-note").textContent = "Lines show each crew's planned order for the day, from the depot and back. Straight lines; travel time is estimated at 30 km/h on roads 1.3x the straight-line distance.";
    try { await loadMaps(); } catch { $("map").textContent = "Map unavailable."; return; }
    const g = window.google.maps;
    if (!state.map) {
      state.map = new g.Map($("map"), { center: { lat: 30.3, lng: 75.9 }, zoom: 8, disableDefaultUI: true, zoomControl: true,
        styles: [{ featureType: "poi", stylers: [{ visibility: "off" }] }, { featureType: "transit", stylers: [{ visibility: "off" }] }] });
    }
    state.mapLayers.forEach((l) => l.setMap(null));
    state.mapLayers = [];
    const bounds = new g.LatLngBounds();
    const depot = company.depot_lat ? { lat: company.depot_lat, lng: company.depot_lon } : null;
    if (depot) {
      state.mapLayers.push(new g.Marker({ position: depot, map: state.map, title: `${company.name} depot`,
        icon: { path: g.SymbolPath.BACKWARD_CLOSED_ARROW, scale: 6, fillColor: "#1b2117", fillOpacity: 1, strokeWeight: 1, strokeColor: "#fff" } }));
      bounds.extend(depot);
    }
    for (const sheet of sheets) {
      const colour = crewColour(sheet.crew_id);
      const path = depot ? [depot] : [];
      for (const stop of sheet.stops) {
        if (stop.lat == null) continue;
        const pos = { lat: stop.lat, lng: stop.lon };
        path.push(pos);
        bounds.extend(pos);
        state.mapLayers.push(new g.Marker({ position: pos, map: state.map, label: { text: String(stop.sequence), color: "#fff", fontSize: "11px", fontWeight: "600" },
          title: `${stop.place} · ${hm(stop.window_start_min)}–${hm(stop.window_end_min)}`,
          icon: { path: g.SymbolPath.CIRCLE, scale: 11, fillColor: colour, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2 } }));
      }
      if (depot) path.push(depot);
      state.mapLayers.push(new g.Polyline({ path, map: state.map, strokeColor: colour, strokeOpacity: .85, strokeWeight: 3 }));
    }
    if (!bounds.isEmpty()) state.map.fitBounds(bounds, 48);
  }

  // ---- Supply
  function renderSupply() {
    const { dashboard, schedule } = state.data;
    const farms = {};
    schedule.route_sheets.forEach((s) => s.stops.forEach((st) => { farms[st.match_id] = { ...st, window: `${dayLabel(s.date)} ${hm(st.window_start_min)}–${hm(st.window_end_min)}` }; }));
    schedule.waitlist.forEach((w) => { farms[w.match_id] = w; });
    const rows = [...dashboard.active_matches].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    if (!rows.length) {
      $("supply").replaceChildren(h("p", { class: "card empty" }, "No farms matched yet. Matches appear as soon as farmers list stubble your demand fits."));
      return;
    }
    $("supply").replaceChildren(h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Farm", "Crop", "Quality", "Quantity", "Price", "Pickup", "Status", ""].map((c) => h("th", {}, c)))),
      h("tbody", {}, rows.map((m) => {
        const f = farms[m.id] || {};
        const canRelease = ["proposed", "waitlisted"].includes(m.status);
        return h("tr", {},
          h("td", {}, f.place || "—"), h("td", {}, cropName(f.crop_type)), h("td", {}, f.quality_grade || "—"),
          h("td", { class: "num" }, kg(m.matched_kg)), h("td", { class: "num" }, `${rupees(m.price_agreed_per_kg)}/kg`),
          h("td", {}, f.window || (m.status === "waitlisted" ? "—" : "")), h("td", {}, pill(m.status)),
          h("td", {}, canRelease ? h("button", { type: "button", class: "ghost danger", onclick: () => reject(m.id) }, "Release") : null));
      })))));
  }

  // ---- Demand
  function renderDemand() {
    const { dashboard, demand } = state.data;
    const rec = dashboard.recommendation;
    $("forecast").replaceChildren(rec ? h("div", { class: "card forecast" },
      h("h3", {}, `Forecast: plan for ${String(rec.product).replace(/_/g, " ")} demand in ${rec.region}`),
      h("p", { class: "small" }, `Peak week starting ${dayLabel(String(rec.period).slice(0, 10))}: about ${Math.round(rec.predicted_demand).toLocaleString("en-IN")} units. BigQuery ML (ARIMA_PLUS), trained on a synthetic history; a planning signal, it does not change prices.`))
      : h("p", { class: "card empty" }, "Forecast not yet available for this buyer."));

    const progress = Object.fromEntries((dashboard.constraint_progress || []).map((p) => [p.demand_id, p]));
    $("demand-list").replaceChildren(...(demand.demand.length ? demand.demand.map((d) => {
      const filled = d.quantity_needed_kg - d.quantity_remaining_kg;
      const rule = progress[d.id];
      return h("div", { class: "card demand" },
        h("div", { class: "sheet-head" }, h("h3", {}, `${String(d.product).replace(/_/g, " ")} · ${cropName(d.crop_type)}`),
          h("span", { class: "mono small" }, `${rupees(d.price_offer_per_kg)}/kg offer · up to ${rupees(d.ceiling_per_kg)}/kg`)),
        h("div", { class: "bar-track" }, h("i", { style: `width:${Math.min(100, (100 * filled) / d.quantity_needed_kg)}%` })),
        h("div", { class: "kv-row" }, h("span", {}, "Matched ", h("b", {}, tonnes(filled))),
          h("span", {}, "Still open ", h("b", {}, tonnes(d.quantity_remaining_kg))),
          h("span", {}, "Needed ", h("b", {}, tonnes(d.quantity_needed_kg)))),
        rule ? h("p", { class: "small muted" }, `Sourcing rule: at least ${rule.target_pct}% ${rule.quality_grade} · ${rule.met_pct}% met (${rule.achieved_kg} of ${rule.target_kg} kg)`) : null);
    }) : [h("p", { class: "card empty" }, "No standing demand yet. Post one to start receiving matched farms.")]));
  }

  async function postDemand(e) {
    e.preventDefault();
    const out = $("d-result");
    const qty = Number($("d-qty").value), price = Number($("d-price").value), max = Number($("d-max").value);
    if (!$("d-product").value.trim() || !qty || !price) { out.textContent = "Fill in product, quantity and offer."; return; }
    out.textContent = "Posting and matching…";
    try {
      const body = await postJson(`/companies/${encodeURIComponent(state.companyId)}/demand`, {
        product: $("d-product").value.trim(), crop_type: $("d-crop").value,
        quantity_needed_kg: qty * 1000, price_offer_per_kg: price,
        max_price_per_kg: max || null, custom_constraint_text: $("d-rule").value.trim() || null,
      });
      const ruleNote = $("d-rule").value.trim() && !(body.custom_constraints || []).length ? " The sourcing rule wasn't recognised, so it wasn't applied." : "";
      out.textContent = `Posted. ${body.new_matches_count} new farm match${body.new_matches_count === 1 ? "" : "es"}; pickups re-planned.${ruleNote}`;
      e.target.reset();
      await loadAll();
    } catch (err) {
      out.textContent = err.message;
    }
  }

  // ---- Impact
  function renderImpact() {
    const { impact } = state.data;
    const c = impact.collected, s = impact.scheduled;
    const cards = [
      [tonnes(c.tonnes_diverted * 1000), "straw collected instead of burned"],
      [`${c.acres_cleared}`, "acres cleared"],
      [`${c.ghg_avoided_t_co2e} t`, "CO₂e avoided (methane + nitrous oxide)"],
      [`${Math.round(c.pm25_avoided_kg)} kg`, `PM2.5 avoided (range ${c.pm25_avoided_kg_range[0]}–${c.pm25_avoided_kg_range[1]} kg)`],
      [rupees(impact.payouts_inr), `paid to ${impact.farmers_paid} farmer${impact.farmers_paid === 1 ? "" : "s"} (simulated)`],
      [`₹${c.farmer_clearing_cost_avoided_inr_range[0].toLocaleString("en-IN")}–${c.farmer_clearing_cost_avoided_inr_range[1].toLocaleString("en-IN")}`, "clearing cost farmers didn't pay"],
    ];
    $("impact").replaceChildren(
      h("div", { class: "impact-grid" }, cards.map(([v, k]) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "k" }, k)))),
      h("p", { class: "card" }, `Already booked and not yet collected: ${tonnes(s.tonnes_diverted * 1000)} from ${s.acres_cleared} acres, a further ${s.ghg_avoided_t_co2e} t CO₂e once collected.`),
      h("p", { class: "method" }, c.method));
  }

  // ---- tabs & wiring
  function showTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== `tab-${tab}`; });
    saved.set("parali_buyer_tab", tab);
  }

  async function init() {
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
    const tab = (location.hash || "").replace("#", "") || saved.get("parali_buyer_tab");
    showTab(["ops", "supply", "demand", "impact"].includes(tab) ? tab : "ops");
    $("company").addEventListener("change", async () => {
      state.companyId = $("company").value;
      saved.set("parali_buyer", state.companyId);
      state.day = null;
      await loadAll().catch((err) => toast(err.message));
    });
    $("replan").addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try {
        const { plans } = await postJson("/schedule/solve", { company_id: state.companyId });
        const p = plans[0];
        toast(`Re-planned: ${p.proposed_with_slot} offers with slots, ${p.scheduled} booked kept in place, ${p.waitlisted} waitlisted.`);
        await loadAll();
      } catch (err) {
        toast(err.message);
      } finally {
        e.currentTarget.disabled = false;
      }
    });
    $("demand-form").addEventListener("submit", postDemand);
    try {
      await loadCompanies();
      await loadAll();
    } catch (err) {
      toast(err.message);
    }
  }

  init();
})();
