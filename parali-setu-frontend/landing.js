// Landing page. Display only: the live counter, the what-if slider and the
// fire map all show numbers from the API (impact.py, FIRMS batch).
(() => {
  const $ = (id) => document.getElementById(id);
  const DISTRICT_CENTERS = {
    Sangrur: [30.2458, 75.8421], Patiala: [30.3398, 76.3869], Bathinda: [30.2110, 74.9455],
    Ludhiana: [30.9010, 75.8573], Moga: [30.8230, 75.1710], Karnal: [29.6857, 76.9905],
    Kaithal: [29.8014, 76.3996], Kurukshetra: [29.9695, 76.8783],
  };
  const fmt = (n, digits = 0) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits });
  const tonnesLabel = (t) => (t >= 1e6 ? `${fmt(t / 1e6, 2)} Mt` : t >= 1000 ? `${fmt(t / 1000, 1)} kt` : `${fmt(t, 1)} t`);
  const ghgLabel = (t) => (t >= 1e6 ? `${fmt(t / 1e6, 2)} Mt` : t >= 1000 ? `${fmt(t / 1000, 1)} kt` : `${fmt(t, 2)} t`);
  const pmLabel = (kg) => (kg >= 1e6 ? `${fmt(kg / 1e6, 1)} kt` : kg >= 1000 ? `${fmt(kg / 1000, 1)} t` : `${fmt(kg)} kg`);
  const rupeesLabel = (n) => (n >= 1e7 ? `₹${fmt(n / 1e7, 1)} crore` : n >= 1e5 ? `₹${fmt(n / 1e5, 1)} lakh` : `₹${fmt(n)}`);

  async function getJson(path) {
    const resp = await fetch(`${API_BASE}${path}`);
    if (!resp.ok) throw new Error(String(resp.status));
    return resp.json();
  }

  async function loadLive() {
    try {
      const { collected, scheduled } = await getJson("/impact");
      $("live-tonnes").textContent = tonnesLabel(collected.tonnes_diverted);
      $("live-ghg").textContent = `${ghgLabel(collected.ghg_avoided_t_co2e)}`;
      $("live-booked").textContent = tonnesLabel(scheduled.tonnes_diverted);
    } catch {
      $("live").replaceChildren(Object.assign(document.createElement("p"), { className: "small muted", textContent: "Live figures are unavailable right now." }));
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
      $("sc-method").textContent = `${s.basis} ${s.method}`;
    } catch {
      $("sc-method").textContent = "The scenario model is unavailable right now.";
    }
  }

  // ---- fire map (Maps JS with the referrer-restricted key from config.js)
  let fireMap = null;
  let pending = null;
  window.initFireMap = () => {
    fireMap = new google.maps.Map($("fire-map"), {
      center: { lat: 30.4, lng: 75.6 }, zoom: 8, disableDefaultUI: true, zoomControl: true,
      styles: [{ featureType: "poi", stylers: [{ visibility: "off" }] }, { featureType: "transit", stylers: [{ visibility: "off" }] }],
    });
    for (const [name, [lat, lng]] of Object.entries(DISTRICT_CENTERS)) {
      new google.maps.Marker({ position: { lat, lng }, map: fireMap, title: name,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 4, fillColor: "#4d5547", fillOpacity: .6, strokeWeight: 0 } });
    }
    if (pending) drawFires(pending);
  };
  function drawFires(detections) {
    if (!fireMap) { pending = detections; return; }
    for (const d of detections) {
      new google.maps.Marker({ position: { lat: d.lat, lng: d.lon }, map: fireMap,
        title: `${d.district_guess || "unknown district"} · ${d.detected_at}`,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6, fillColor: "#b33a1a", fillOpacity: .8, strokeColor: "#5c3410", strokeWeight: 1 } });
    }
  }
  async function loadFires() {
    const status = $("map-status");
    try {
      const body = await getJson("/fire-detections");
      const detections = body.detections || [];
      if (!detections.length) { status.textContent = "No fire detections in the current refresh window."; return; }
      drawFires(detections);
      status.textContent = body.coverage
        ? `${detections.length} detections between ${body.coverage.start_date} and ${body.coverage.end_date}.`
        : `${detections.length} detections.`;
    } catch {
      status.textContent = "Could not load fire activity right now.";
    }
  }
  function loadMapsScript() {
    if (typeof MAPS_API_KEY === "undefined") return;
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(MAPS_API_KEY)}&callback=initFireMap&v=weekly`;
    s.async = true;
    document.head.append(s);
  }

  $("share").addEventListener("input", () => {
    $("share-out").textContent = $("share").value;
    clearTimeout(scenarioTimer);
    scenarioTimer = setTimeout(loadScenario, 250);
  });
  loadLive();
  loadScenario();
  loadFires();
  loadMapsScript();
})();
