// Fire map: real NASA FIRMS fire pixels over Punjab and Haryana's districts,
// with our depots and how far their crews reach. Shared by the landing page
// (the 2024 season, day by day) and the ops console (this week's fires and
// our booked farms). Drawn on a canvas: 27,000 points are too many for SVG.
//
//   FireMap.mount(el, { season: "data/fires_2024.json", depots, farms, live, liveLabel })
//
// Every point comes from the data file (forecast/fire_map_data.py) or the API;
// nothing is interpolated. Counts shown are counts of those points.
(function () {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmt = (n) => Math.round(n).toLocaleString("en-IN");

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v; else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return node;
  }

  function dayLabel(start, d) {
    const t = new Date(`${start}T00:00:00`);
    t.setDate(t.getDate() + d);
    return `${t.getDate()} ${MONTHS[t.getMonth()]} ${t.getFullYear()}`;
  }

  // Point-in-polygon (ray casting), [lon, lat] rings.
  function inRing(lon, lat, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  async function mount(root, opts) {
    const data = opts.season ? await fetch(opts.season).then((r) => r.json()) : null;
    const districts = (data && data.districts) || opts.districts || [];
    // outlinesOnly: the district map without the season's fires (ops shows this week's instead)
    const season = data && !opts.outlinesOnly ? data : null;
    const points = (season && season.points) || [];
    const days = (data && data.days) || 1;
    const live = (opts.live || []).map((p) => [p.lat, p.lon]);
    const depots = opts.depots || [];
    const farms = opts.farms || [];

    // Bounds and a projection that keeps distances honest at this latitude.
    let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
    const grow = (x, y) => { minLon = Math.min(minLon, x); maxLon = Math.max(maxLon, x); minLat = Math.min(minLat, y); maxLat = Math.max(maxLat, y); };
    for (const d of districts) for (const ring of d.rings) for (const [x, y] of ring) grow(x, y);
    for (const p of points) grow(p[1], p[0]);
    for (const [lat, lon] of live) grow(lon, lat);
    const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const aspect = ((maxLat - minLat) / ((maxLon - minLon) * kx)) || 1;

    const canvas = el("canvas", { class: "fm-canvas", role: "img", "aria-label": opts.ariaLabel || "Map of satellite fire detections in Punjab and Haryana" });
    const tip = el("div", { class: "fm-tip", hidden: true });
    const stage = el("div", { class: "fm-stage" }, canvas, tip);
    const legend = el("div", { class: "fm-legend" },
      el("span", {}, el("i", { class: "fm-key fire" }), season ? "Satellite fire pixel (about 1 km)" : "Satellite fire, last 7 days"),
      depots.length ? el("span", {}, el("i", { class: "fm-key depot" }), "Our depot and its crews' reach") : null,
      farms.length ? el("span", {}, el("i", { class: "fm-key farm" }), "Booked farm") : null);
    root.replaceChildren(stage, legend);
    root.classList.add("firemap");

    let day = days - 1, playing = false, timer = null;
    const byDay = new Array(days).fill(0);
    for (const p of points) byDay[p[2]]++;
    const cumulative = byDay.reduce((acc, n, i) => (acc.push((acc[i - 1] || 0) + n), acc), []);

    // Controls (season mode): play, slider, date, and the daily bars as a scrubber.
    let slider, out, bars;
    if (season) {
      const play = el("button", { class: "btn small quiet fm-play", type: "button", "aria-label": "Play the season" }, "▶ Play");
      slider = el("input", { type: "range", min: 0, max: days - 1, value: day, "aria-label": "Day of the season" });
      out = el("output", { class: "fm-out", "aria-live": "polite" });
      bars = el("canvas", { class: "fm-bars", "aria-hidden": "true" });
      root.prepend(el("div", { class: "fm-controls" }, play, el("div", { class: "fm-scrub" }, bars, slider), out));
      slider.addEventListener("input", () => { stop(); day = +slider.value; draw(); });
      play.addEventListener("click", () => (playing ? stop() : start()));
      bars.addEventListener("pointerdown", (e) => scrub(e));
      bars.addEventListener("pointermove", (e) => e.buttons && scrub(e));
      function scrub(e) {
        const r = bars.getBoundingClientRect();
        stop(); day = Math.max(0, Math.min(days - 1, Math.floor(((e.clientX - r.left) / r.width) * days))); slider.value = day; draw();
      }
      function start() {
        if (day >= days - 1) day = 0;
        playing = true; play.textContent = "❚❚ Pause"; play.setAttribute("aria-label", "Pause");
        timer = setInterval(() => { day++; slider.value = day; draw(); if (day >= days - 1) stop(); }, 110);
      }
      function stop() {
        playing = false; clearInterval(timer); play.textContent = "▶ Play"; play.setAttribute("aria-label", "Play the season");
      }
      // Play once when the map first scrolls into view (not for reduced motion), pause when it leaves.
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      let played = false;
      new IntersectionObserver((entries) => {
        for (const e of entries) {
          if (e.isIntersecting && !played && !reduce && opts.autoplay !== false) { played = true; day = 0; start(); }
          if (!e.isIntersecting && playing) stop();
        }
      }, { threshold: 0.4 }).observe(stage);
    }

    let W = 0, H = 0, project;
    function size() {
      const dpr = window.devicePixelRatio || 1;
      W = stage.clientWidth; H = Math.round(Math.min(W * aspect, 640));
      canvas.style.height = `${H}px`;
      canvas.width = W * dpr; canvas.height = H * dpr;
      canvas.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
      const pad = 10, sx = (W - 2 * pad) / ((maxLon - minLon) * kx), sy = (H - 2 * pad) / (maxLat - minLat), s = Math.min(sx, sy);
      const ox = (W - (maxLon - minLon) * kx * s) / 2, oy = (H - (maxLat - minLat) * s) / 2;
      project = (lon, lat) => [ox + (lon - minLon) * kx * s, oy + (maxLat - lat) * s];
      project.kmPx = s / 111;  // pixels per km (1 degree of latitude is about 111 km)
      if (bars) {
        const dpr2 = window.devicePixelRatio || 1;
        bars.width = bars.clientWidth * dpr2; bars.height = bars.clientHeight * dpr2;
        bars.getContext("2d").setTransform(dpr2, 0, 0, dpr2, 0, 0);
      }
    }

    function draw() {
      const g = canvas.getContext("2d");
      const C = { ground: css("--surface"), field: css("--khaddar"), line: css("--line-strong"), fire: css("--fire"),
                  madder: css("--madder"), silk: css("--silk"), ok: css("--ok"), ink: css("--thread-soft") };
      g.clearRect(0, 0, W, H);
      g.fillStyle = C.ground; g.fillRect(0, 0, W, H);
      g.lineWidth = 0.8; g.strokeStyle = C.line; g.fillStyle = C.field;
      for (const d of districts) for (const ring of d.rings) {
        g.beginPath();
        ring.forEach(([x, y], i) => { const [px, py] = project(x, y); i ? g.lineTo(px, py) : g.moveTo(px, py); });
        g.closePath(); g.fill(); g.stroke();
      }
      // Depot reach first, so fires draw over it.
      for (const d of depots) {
        const [x, y] = project(d.lon, d.lat);
        g.beginPath(); g.arc(x, y, (d.radius_km || 80) * project.kmPx, 0, Math.PI * 2);
        g.setLineDash([4, 4]); g.strokeStyle = C.madder; g.globalAlpha = 0.45; g.lineWidth = 1.2; g.stroke();
        g.setLineDash([]); g.globalAlpha = 1;
      }
      // Fires: older days faint, the last three days bright.
      const fire = C.fire;
      g.fillStyle = fire;
      if (season) {
        g.globalAlpha = 0.28;
        for (const p of points) if (p[2] <= day - 3) { const [x, y] = project(p[1], p[0]); g.fillRect(x - 1, y - 1, 2, 2); }
        g.globalAlpha = 0.95;
        for (const p of points) if (p[2] > day - 3 && p[2] <= day) { const [x, y] = project(p[1], p[0]); g.fillRect(x - 1.5, y - 1.5, 3, 3); }
      }
      g.globalAlpha = 0.95;
      for (const [lat, lon] of live) { const [x, y] = project(lon, lat); g.beginPath(); g.arc(x, y, 3.2, 0, Math.PI * 2); g.fill(); }
      g.globalAlpha = 1;
      for (const f of farms) {
        const [x, y] = project(f.lon, f.lat);
        g.beginPath(); g.arc(x, y, 3.4, 0, Math.PI * 2); g.fillStyle = C.ok; g.fill();
        g.lineWidth = 1.2; g.strokeStyle = C.ground; g.stroke();
      }
      // Depots: the stitched diamond.
      for (const d of depots) {
        const [x, y] = project(d.lon, d.lat), r = 7;
        g.beginPath(); g.moveTo(x, y - r); g.lineTo(x + r, y); g.lineTo(x, y + r); g.lineTo(x - r, y); g.closePath();
        g.fillStyle = C.madder; g.fill();
        g.fillStyle = C.silk; g.fillRect(x - 2, y - 2, 4, 4);
        g.font = `600 12px ${css("--font-body")}`; g.fillStyle = css("--thread"); g.textAlign = "left";
        g.fillText(d.name.replace(/ depot$/, ""), x + r + 4, y + 4);
      }
      if (out) {
        out.textContent = `${dayLabel(season.start, day)} · ${fmt(cumulative[day])} fire pixels so far · ${fmt(byDay[day])} that day`;
      }
      if (bars) drawBars(C);
    }

    function drawBars(C) {
      const g = bars.getContext("2d"), w = bars.clientWidth, h = bars.clientHeight, max = Math.max(...byDay), bw = w / days;
      g.clearRect(0, 0, w, h);
      byDay.forEach((n, i) => {
        const bh = Math.max(1, (n / max) * (h - 2));
        g.fillStyle = i <= day ? C.fire : C.line;
        g.globalAlpha = i === day ? 1 : 0.75;
        g.fillRect(i * bw + 0.5, h - bh, Math.max(1, bw - 1), bh);
      });
      g.globalAlpha = 1;
    }

    // District under the pointer, with its fires so far (counted lazily, once).
    let owner = null;
    function districtOf(lon, lat) {
      return districts.find((d) => d.rings.some((r) => inRing(lon, lat, r)));
    }
    function assignPoints() {
      owner = new Map();
      for (const p of points) {
        const d = districtOf(p[1], p[0]);
        if (!d) continue;
        if (!owner.has(d)) owner.set(d, new Array(days).fill(0));
        owner.get(d)[p[2]]++;
      }
    }
    canvas.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      // invert the projection
      const [x0, y0] = project(minLon, maxLat), [x1, y1] = project(maxLon, minLat);
      const lon = minLon + ((mx - x0) / (x1 - x0)) * (maxLon - minLon), lat = maxLat - ((my - y0) / (y1 - y0)) * (maxLat - minLat);
      const d = districtOf(lon, lat);
      if (!d) { tip.hidden = true; return; }
      let text = `${d.district}, ${d.state}`;
      if (season) {
        if (!owner) assignPoints();
        const counts = owner.get(d) || [];
        const sofar = counts.slice(0, day + 1).reduce((a, b) => a + b, 0);
        text += ` · ${fmt(sofar)} fire pixels by ${dayLabel(season.start, day)}`;
      }
      tip.textContent = text; tip.hidden = false;
      tip.style.left = `${Math.min(mx + 12, W - 220)}px`; tip.style.top = `${my + 12}px`;
    });
    canvas.addEventListener("pointerleave", () => { tip.hidden = true; });

    size(); draw();
    new ResizeObserver(() => { size(); draw(); }).observe(stage);
    return { total: points.length, days, start: season && season.start, peakDay: byDay.indexOf(Math.max(...byDay)), byDay,
             setDay(d) { day = d; if (slider) slider.value = d; draw(); } };
  }

  window.FireMap = { mount, dayLabel };
})();
