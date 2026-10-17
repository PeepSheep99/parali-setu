// Landing page. Display only: the demo counters (/impact), the satellite
// record (/fires/history) and the what-if slider (/impact/scenario) all show
// numbers computed by the API.
(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n, digits = 0) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits });
  const tonnesLabel = (t) => (t >= 1e6 ? `${fmt(t / 1e6, 2)} Mt` : t >= 1000 ? `${fmt(t / 1000, 1)} kt` : `${fmt(t, 1)} t`);
  const ghgLabel = (t) => (t >= 1e6 ? `${fmt(t / 1e6, 2)} Mt` : t >= 1000 ? `${fmt(t / 1000, 1)} kt` : `${fmt(t, 2)} t`);
  const pmLabel = (kg) => (kg >= 1e6 ? `${fmt(kg / 1e6, 1)} kt` : kg >= 1000 ? `${fmt(kg / 1000, 1)} t` : `${fmt(kg)} kg`);
  const rupeesLabel = (n) => (n >= 1e7 ? `₹${fmt(n / 1e7, 1)} crore` : n >= 1e5 ? `₹${fmt(n / 1e5, 1)} lakh` : `₹${fmt(n)}`);
  const svg = (tag, attrs = {}, text) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text !== undefined) el.textContent = text;
    return el;
  };

  async function getJson(path) {
    const resp = await fetch(`${API_BASE}${path}`);
    if (!resp.ok) throw new Error(String(resp.status));
    return resp.json();
  }

  // The satellite record only changes with the season, so show the last copy at once
  // and refresh it for the next visit.
  async function getJsonCached(path) {
    const key = `ps_cache_${path}`;
    let cached = null;
    try { cached = JSON.parse(localStorage.getItem(key)); } catch { /* blocked or corrupt storage */ }
    const fresh = getJson(path).then((body) => { try { localStorage.setItem(key, JSON.stringify(body)); } catch { /* ignore */ } return body; });
    if (cached) { fresh.catch(() => {}); return cached; }
    return fresh;
  }

  const PLACEHOLDERS = ["live-tonnes", "live-paid", "live-ghg", "sc-tonnes", "sc-ghg", "sc-pm", "sc-cost"];
  PLACEHOLDERS.forEach((id) => { const el = $(id); if (el) el.classList.add("loading"); });
  const loaded = (...ids) => ids.forEach((id) => $(id) && $(id).classList.remove("loading"));

  async function loadLive() {
    try {
      const { collected, paid_to_farmers_inr } = await getJson("/impact");
      $("live-tonnes").textContent = tonnesLabel(collected.tonnes_diverted);
      $("live-paid").textContent = rupeesLabel(paid_to_farmers_inr);
      $("live-ghg").textContent = ghgLabel(collected.ghg_avoided_t_co2e);
      loaded("live-tonnes", "live-paid", "live-ghg");
    } catch {
      $("live").replaceChildren(Object.assign(document.createElement("p"), { className: "small muted", textContent: "Live figures are unavailable right now." }));
    }
  }

  function tip(e, text) {
    const el = $("tooltip");
    el.textContent = text;
    el.hidden = false;
    el.style.left = `${Math.min(e.clientX + 12, window.innerWidth - 270)}px`;
    el.style.top = `${e.clientY + 12}px`;
  }

  async function loadRecord() {
    try {
      const { seasons } = await getJsonCached("/fires/history");
      const W = 980, H = 300, m = { l: 56, r: 12, t: 26, b: 30 };
      const raw = Math.max(...seasons.map((s) => s.total));
      const mag = 10 ** Math.floor(Math.log10(raw / 4));
      const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k * 4 >= raw);
      const max = step * 4;
      const slot = (W - m.l - m.r) / seasons.length;
      const bw = Math.max(6, slot - 6);
      const y = (v) => H - m.b - (v / max) * (H - m.t - m.b);
      const chart = svg("svg", { viewBox: `0 0 ${W} ${H}` });
      const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
      for (let i = 0; i <= 4; i++) {
        grid.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(step * i), y2: y(step * i) }));
        axis.append(svg("text", { x: m.l - 6, y: y(step * i) + 4, "text-anchor": "end" }, fmt(step * i)));
      }
      chart.append(grid, axis);
      const peak = seasons.reduce((p, s, i) => (s.total > seasons[p].total ? i : p), 0);
      seasons.forEach((s, i) => {
        const x0 = m.l + i * slot + (slot - bw) / 2;
        const top = y(s.total), base = y(0), r = Math.min(4, bw / 2, base - top);
        const bar = svg("path", { class: `bar${s.partial ? " partial" : ""}`,
          d: `M${x0},${base}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${base}Z` });
        const hit = svg("rect", { class: "hit", x: m.l + i * slot, y: m.t, width: slot, height: H - m.t - m.b });
        const label = `${s.year}${s.partial ? " (so far)" : ""}: ${fmt(s.total)} detections · Punjab ${fmt(s.Punjab)}, Haryana ${fmt(s.Haryana)}`;
        hit.addEventListener("mousemove", (e) => { bar.classList.add("on"); tip(e, label); });
        hit.addEventListener("mouseleave", () => { bar.classList.remove("on"); $("tooltip").hidden = true; });
        chart.append(bar, hit);
        if (i % 3 === 0 || i === seasons.length - 1) axis.append(svg("text", { x: x0 + bw / 2, y: H - m.b + 16, "text-anchor": "middle" }, String(s.year)));
        if (i === peak) chart.append(svg("text", { class: "label", x: x0 + bw / 2, y: top - 6, "text-anchor": "middle" }, `${s.year}: ${fmt(s.total)}`));
        if (i === seasons.length - 2) chart.append(svg("text", { class: "label", x: x0 + bw / 2, y: top - 6, "text-anchor": "middle" }, fmt(s.total)));
      });
      $("record-chart").replaceChildren(chart);
      $("record-chart").scrollLeft = $("record-chart").scrollWidth;   // phones open on the latest seasons
      const last = seasons[seasons.length - 1];
      $("record-note").textContent = `Bars: satellite fire pixels per season (Sep–Dec). ${last.partial ? `${last.year} so far, to ${last.last_date}: ${fmt(last.total)}. ` : ""}Source: NASA FIRMS via Google Earth Engine, counted per district with FAO GAUL 2025 boundaries.`;
    } catch {
      $("record-chart").textContent = "The satellite record is unavailable right now.";
    }
  }

  let scenarioTimer = null;
  async function loadScenario() {
    const share = $("share").value;
    $("share-out").textContent = share;
    try {
      const s = await getJson(`/impact/scenario?share_pct=${encodeURIComponent(share)}`);
      $("sc-tonnes").textContent = tonnesLabel(s.tonnes_diverted);
      $("sc-ghg").textContent = ghgLabel(s.ghg_avoided_t_co2e);
      $("sc-pm").textContent = `${pmLabel(s.pm25_avoided_kg_range[0])}–${pmLabel(s.pm25_avoided_kg_range[1])}`;
      const [lo, hi] = s.farmer_clearing_cost_avoided_inr_range;
      $("sc-cost").textContent = `${rupeesLabel(lo)}–${rupeesLabel(hi)}`;
      loaded("sc-tonnes", "sc-ghg", "sc-pm", "sc-cost");
      $("sc-method").textContent = `A scenario, not a measurement. ${s.basis} ${s.method} PM2.5 is shown as a range because field studies report 4.7–20 kg per tonne burned.`;
    } catch {
      $("sc-method").textContent = "The scenario model is unavailable right now.";
    }
  }

  $("share").addEventListener("input", () => {
    $("share-out").textContent = $("share").value;
    clearTimeout(scenarioTimer);
    scenarioTimer = setTimeout(loadScenario, 250);
  });
  loadLive();
  loadRecord();
  loadScenario();
})();
