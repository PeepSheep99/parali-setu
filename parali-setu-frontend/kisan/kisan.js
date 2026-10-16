// Kisan: speak once, confirm once. Talks only to the deployed API
// (../config.js). Never computes a price, quantity or slot itself -- every
// number shown comes from the API response.
(() => {
  const STR = window.KISAN_STRINGS;
  const LANG_API = { hi: "Hindi", pa: "Punjabi", en: "English" };
  const LOCALE = { hi: "hi-IN", pa: "pa-IN", en: "en-IN" };
  const DISTRICTS = {
    Sangrur: ["ਸੰਗਰੂਰ", "संगरूर"], Patiala: ["ਪਟਿਆਲਾ", "पटियाला"], Bathinda: ["ਬਠਿੰਡਾ", "बठिंडा"],
    Ludhiana: ["ਲੁਧਿਆਣਾ", "लुधियाना"], Moga: ["ਮੋਗਾ", "मोगा"], Karnal: ["ਕਰਨਾਲ", "करनाल"],
    Kaithal: ["ਕੈਥਲ", "कैथल"], Kurukshetra: ["ਕੁਰੂਕਸ਼ੇਤਰ", "कुरुक्षेत्र"],
  };

  const $ = (id) => document.getElementById(id);
  const state = {
    lang: null, farmerId: null, draft: null, edits: {}, location: null,
    photo: null, offerBody: null, lastPlace: null,
  };

  // ---- storage (per-device convenience only; tolerate blocked storage)
  const saved = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  // ---- text helpers
  const fill = (s, vars) => s.replace(/\{(\w+)\}/g, (_, k) => (vars && vars[k] !== undefined ? vars[k] : ""));
  const t = (key, vars) => fill((STR[state.lang] || STR.en)[key] || STR.en[key] || key, vars);
  const en = (key, vars) => fill(STR.en[key] || key, vars);

  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) el.append(c.nodeType ? c : String(c));
    return el;
  }

  // A label in the farmer's language, with the English line underneath
  // for Hindi/Punjabi so others can follow.
  function labelNodes(key, vars) {
    const nodes = [t(key, vars)];
    if (state.lang !== "en") nodes.push(h("span", { class: "sub", lang: "en" }, en(key, vars)));
    return nodes;
  }
  function setLabel(el, key, vars) { el.replaceChildren(...labelNodes(key, vars)); }

  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.hidden = true; }, 4500);
  }

  function playAudio(spoken) {
    if (!spoken || !spoken.audio_base64) return;
    const audio = $("voice");
    audio.src = `data:audio/mp3;base64,${spoken.audio_base64}`;
    audio.play().catch(() => { /* autoplay blocked; the Listen button replays */ });
  }

  // ---- API
  async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try { body = await resp.json(); } catch { /* empty body */ }
    if (!resp.ok) {
      const detail = typeof body.detail === "string" ? body.detail : t("error_generic");
      throw new Error(detail);
    }
    return body;
  }
  const postJson = (path, data) => api(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  });

  // ---- formatting (display only)
  // Explicit names: browser locale data for pa-IN is often missing and
  // renders months as "M10".
  const MONTHS = {
    en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    hi: ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    pa: ["ਜਨਵਰੀ", "ਫ਼ਰਵਰੀ", "ਮਾਰਚ", "ਅਪ੍ਰੈਲ", "ਮਈ", "ਜੂਨ", "ਜੁਲਾਈ", "ਅਗਸਤ", "ਸਤੰਬਰ", "ਅਕਤੂਬਰ", "ਨਵੰਬਰ", "ਦਸੰਬਰ"],
  };
  const WEEKDAYS = {
    en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    hi: ["रविवार", "सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार"],
    pa: ["ਐਤਵਾਰ", "ਸੋਮਵਾਰ", "ਮੰਗਲਵਾਰ", "ਬੁੱਧਵਾਰ", "ਵੀਰਵਾਰ", "ਸ਼ੁੱਕਰਵਾਰ", "ਸ਼ਨੀਵਾਰ"],
  };
  function parseDay(iso) {
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d);
  }
  function formatWindow(slot) {
    if (!slot) return t("not_given");
    const d = parseDay(slot.date);
    if (!d) return t("not_given");
    const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
    const day = `${WEEKDAYS[state.lang][d.getDay()]}, ${d.getDate()} ${MONTHS[state.lang][d.getMonth()]}`;
    return `${day}, ${hm(slot.window_start_min)}–${hm(slot.window_end_min)}`;
  }
  function formatDate(iso) {
    if (!iso) return null;
    const d = parseDay(iso);
    return d ? `${d.getDate()} ${MONTHS[state.lang][d.getMonth()]}` : null;
  }
  const rupees = (n) => `₹${Number(n).toLocaleString(LOCALE[state.lang], { maximumFractionDigits: 2 })}`;

  // ---- language
  function setLanguage(lang) {
    state.lang = lang;
    saved.set("parali_lang", lang);
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach((el) => setLabel(el, el.dataset.t));
    document.querySelectorAll(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    $("typed").placeholder = t("type_placeholder");
    $("lang-gate").hidden = true;
    $("app").hidden = false;
    if (state.photo) setLabel($("photo-label"), "photo_added");
    if (state.location) setLabel($("locate-label"), "location_added");
    if (state.draft) renderConfirm();
    if (state.offerBody) renderOffer();
    renderDistrictSelect();
    loadPickups();
  }

  // ---- voice recording: hold to talk, or tap to start and tap to stop
  function makeRecorder(button, labelEl, idleKey, onAudio) {
    let recorder = null, chunks = [], pressedAt = 0, tapMode = false;

    async function start() {
      if (!navigator.mediaDevices || !window.MediaRecorder) { toast(t("mic_unavailable")); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
        recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
        chunks = [];
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = () => {
          stream.getTracks().forEach((tr) => tr.stop());
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          recorder = null;
          button.classList.remove("recording");
          setLabel(labelEl, idleKey);
          if (blob.size > 2000) onAudio(blob);
        };
        recorder.start();
        button.classList.add("recording");
        setLabel(labelEl, "tap_to_stop");
      } catch {
        toast(t("mic_unavailable"));
      }
    }
    const stop = () => { if (recorder && recorder.state === "recording") recorder.stop(); };

    button.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      if (recorder) { stop(); tapMode = false; return; }
      pressedAt = Date.now();
      tapMode = false;
      start();
    });
    button.addEventListener("pointerup", () => {
      if (!recorder) return;
      if (Date.now() - pressedAt > 450) stop();   // held: release sends
      else tapMode = true;                         // quick tap: keep listening until the next tap
    });
    button.addEventListener("pointerleave", () => { if (recorder && !tapMode && Date.now() - pressedAt > 450) stop(); });
    button.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      if (recorder) stop(); else start();
    });
  }

  // ---- step 1: draft
  function showWorking(key) {
    setLabel($("working-text"), key);
    $("working").hidden = false;
  }
  const hideWorking = () => { $("working").hidden = true; };

  async function sendDraft({ audio, text }) {
    const form = new FormData();
    form.append("farmer_id", state.farmerId);
    form.append("language", LANG_API[state.lang]);
    if (state.draft) form.append("draft_id", state.draft.draft_id);
    if (text) form.append("text", text);
    if (audio) form.append("audio", audio, "speech.webm");
    if (state.location) { form.append("lat", state.location.lat); form.append("lon", state.location.lon); }
    if (state.photo) form.append("photo", state.photo);
    showWorking("understanding");
    try {
      const body = await api("/listings/draft", { method: "POST", body: form });
      state.photo = null;
      state.draft = body;
      state.edits = {};
      state.offerBody = null;
      $("offer").hidden = true;
      renderConfirm();
      playAudio(body.follow_up || body.confirm_summary);
      $("confirm").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message);
    } finally {
      hideWorking();
    }
  }

  function currentFields() {
    return { ...(state.draft ? state.draft.fields : {}), ...state.edits };
  }

  function renderConfirm() {
    const d = state.draft;
    $("confirm").hidden = !d;
    if (!d) return;
    $("question").hidden = !d.follow_up;
    if (d.follow_up) $("question-text").textContent = d.follow_up.text;
    $("transcript").textContent = d.transcript ? `“${d.transcript}”` : "";

    const f = currentFields();
    const cropName = f.crop_type === "wheat_stubble" ? t("wheat") : f.crop_type === "rice_stubble" ? t("rice") : null;
    const chips = [
      { field: "acres", key: "f_acres", value: f.acres ? String(f.acres) : null },
      { field: "crop_type", key: "f_crop", value: cropName },
      { field: "village_or_district", key: "f_place", value: f.village_or_district || (state.location ? t("location_added") : null) },
      { field: "sowing_deadline", key: "f_sowing", value: formatDate(f.sowing_deadline) },
    ];
    const nodes = chips.map((c) => h("button", {
      type: "button", class: `chip${c.value ? "" : " missing"}`, onclick: () => editChip(c.field),
    },
      h("span", { class: "k" }, labelNodes(c.key)),
      h("span", { class: "v" }, c.value || t("not_given")),
      h("span", { class: "edit", "aria-hidden": "true" }, "✎"),
    ));
    if (d.quality && d.quality.grade && d.quality.grade !== "unknown") {
      nodes.push(h("div", { class: "chip" }, h("span", { class: "k" }, labelNodes("f_quality")),
        h("span", { class: "v" }, `${d.quality.grade}${d.quality.note ? " · " + d.quality.note : ""}`)));
    }
    if (d.location_approximate) nodes.push(h("p", { class: "note" }, labelNodes("approx_location")));
    $("chips").replaceChildren(...nodes);
    $("confirm-btn").disabled = !(f.acres || f.quantity_kg) || !f.crop_type;
  }

  function editChip(field) {
    const f = currentFields();
    let input;
    if (field === "acres") {
      input = h("input", { type: "number", min: "0.5", max: "1000", step: "0.5", inputmode: "decimal", value: f.acres || "" });
    } else if (field === "crop_type") {
      input = h("select", {},
        h("option", { value: "rice_stubble", selected: f.crop_type !== "wheat_stubble" }, t("rice")),
        h("option", { value: "wheat_stubble", selected: f.crop_type === "wheat_stubble" }, t("wheat")));
    } else if (field === "sowing_deadline") {
      input = h("input", { type: "date", value: f.sowing_deadline ? String(f.sowing_deadline).slice(0, 10) : "" });
    } else {
      input = h("input", { type: "text", maxlength: "120", value: f.village_or_district || "" });
    }
    const save = h("button", { type: "button", class: "primary" }, "✓");
    const editor = h("div", { class: "chip-editor" }, input, save);
    const chipButtons = [...$("chips").querySelectorAll("button.chip")];
    const order = ["acres", "crop_type", "village_or_district", "sowing_deadline"];
    chipButtons[order.indexOf(field)].replaceWith(editor);
    input.focus();
    const commit = () => {
      const raw = input.value.trim();
      if (raw) state.edits[field] = field === "acres" ? Number(raw) : raw;
      renderConfirm();
    };
    save.addEventListener("click", commit);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") commit(); });
  }

  // ---- step 2: confirm -> offer
  async function confirmListing() {
    const edits = {};
    for (const [k, v] of Object.entries(state.edits)) if (v !== "" && v !== null) edits[k] = v;
    showWorking("finding");
    $("confirm-btn").disabled = true;
    try {
      const body = await postJson(`/listings/${state.draft.draft_id}/confirm`, {
        farmer_id: state.farmerId, edits: Object.keys(edits).length ? edits : null,
      });
      state.lastPlace = body.listing && body.listing.village_or_district;
      state.draft = null;
      state.edits = {};
      $("confirm").hidden = true;
      state.offerBody = body;
      renderOffer();
      playAudio(body.explanation);
      $("offer").scrollIntoView({ behavior: "smooth", block: "start" });
      loadPickups();
    } catch (err) {
      toast(err.message);
      $("confirm-btn").disabled = false;
    } finally {
      hideWorking();
    }
  }

  function renderOffer() {
    const body = state.offerBody;
    const box = $("offer");
    if (!body) { box.hidden = true; return; }
    box.hidden = false;

    if (body.status !== "offered") {
      const titleKey = body.status === "waitlisted" ? "waitlisted_title" : "no_buyer_title";
      const bodyKey = body.status === "waitlisted" ? "waitlisted_body" : "no_buyer_body";
      box.replaceChildren(
        h("div", { class: "state-banner" }, h("h2", {}, labelNodes(titleKey)), h("p", {}, t(bodyKey))),
        h("button", { type: "button", class: "ghost", onclick: resetCompose }, labelNodes("list_more")),
      );
      return;
    }

    const offer = body.offers.find((o) => o.status === "proposed" && o.slots && o.slots.length) || body.offers[0];
    const accepted = offer.status === "scheduled";
    const impact = body.impact_if_collected;
    const grid = h("div", { class: "offer-grid" },
      h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("buyer")), h("span", { class: "v" }, offer.company_name)),
      h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("pickup")), h("span", { class: "v" }, formatWindow(offer.slots[0]))),
      h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("price")),
        h("span", { class: "v", id: "offer-price" }, `${rupees(offer.price_agreed_per_kg)}/kg`)),
      h("div", {}, h("p", { class: "k hint" }, labelNodes("you_get")),
        h("p", { class: "big-money", id: "offer-total" }, rupees(offer.matched_kg * offer.price_agreed_per_kg)),
        h("p", { class: "hint" }, `${Number(offer.matched_kg).toLocaleString(LOCALE[state.lang])} kg`)),
    );
    const extras = [];
    if (impact) {
      extras.push(h("div", { class: "impact" }, h("strong", {}, labelNodes("instead_of_burning")),
        h("p", {}, t("impact_line", { ghg: impact.ghg_avoided_t_co2e, pm: Math.round(impact.pm25_avoided_kg) }))));
    }
    if (body.window_assumed) extras.push(h("p", { class: "note" }, labelNodes("assumed_window")));
    if (body.location_approximate) extras.push(h("p", { class: "note" }, labelNodes("approx_location")));

    const acceptBtn = h("button", {
      type: "button", class: "primary wide", disabled: accepted,
      onclick: () => acceptSlot(offer, acceptBtn),
    }, labelNodes(accepted ? "accepted" : "accept_slot"));
    const whyOut = h("p", { class: "result", "aria-live": "polite" });
    const whyBtn = h("button", { type: "button", class: "ghost", onclick: () => whyPrice(offer, whyOut) }, labelNodes("why_price"));
    const negotiatePanel = buildNegotiation(offer);
    const listenBtn = body.explanation && body.explanation.audio_base64
      ? h("button", { type: "button", class: "ghost", onclick: () => playAudio(body.explanation) }, labelNodes("listen")) : null;

    box.replaceChildren(
      h("h2", {}, labelNodes("offer_title")), grid, ...extras,
      h("div", { class: "row" }, acceptBtn),
      h("div", { class: "row" }, whyBtn, listenBtn), whyOut, negotiatePanel,
    );
  }

  async function acceptSlot(offer, button) {
    button.disabled = true;
    try {
      const body = await postJson(`/matches/${offer.id}/accept-slot`, { farmer_id: state.farmerId });
      offer.status = "scheduled";
      toast(`${t("accepted")} · ${formatWindow(body.slots[0])}`);
      renderOffer();
      loadPickups();
    } catch (err) {
      toast(err.message);
      button.disabled = false;
    }
  }

  async function whyPrice(offer, out) {
    out.textContent = "…";
    try {
      const body = await api(`/matches/${offer.id}/pricing-explanation?language=${encodeURIComponent(LANG_API[state.lang])}`);
      out.textContent = body.explanation;
    } catch (err) {
      out.textContent = err.message;
    }
  }

  function buildNegotiation(offer) {
    const details = h("details", { class: "panel" });
    const floor = h("input", { type: "number", min: "0.1", step: "0.05", inputmode: "decimal", id: "floor", value: offer.price_agreed_per_kg });
    const out = h("div", { class: "turns", "aria-live": "polite" });
    const go = h("button", { type: "button", class: "primary" }, labelNodes("negotiate"));
    go.addEventListener("click", async () => {
      go.disabled = true;
      out.replaceChildren(h("p", { class: "hint" }, "…"));
      try {
        const session = await postJson("/negotiate/agents", {
          match_id: offer.id, farmer_floor: Number(floor.value), language: LANG_API[state.lang],
        });
        const rows = session.turns.map((turn) => h("div", { class: "turn" },
          h("span", {}, `${rupees(turn.farmer_ask_per_kg)} · ${turn.farmer_message || ""}`),
          h("span", {}, `${rupees(turn.buyer_offer_per_kg)} · ${turn.buyer_message || ""}`)));
        const nodes = [...rows];
        if (session.final_price_per_kg && session.final_price_per_kg > offer.price_agreed_per_kg) {
          const accept = h("button", { type: "button", class: "primary" }, labelNodes("accept_price", { p: session.final_price_per_kg }));
          accept.addEventListener("click", async () => {
            accept.disabled = true;
            try {
              const done = await postJson(`/matches/${offer.id}/confirm-price`, { session_id: session.id });
              offer.price_agreed_per_kg = done.new_price_per_kg;
              toast(t("price_updated", { p: done.new_price_per_kg }));
              renderOffer();
            } catch (err) {
              toast(err.message);
              accept.disabled = false;
            }
          });
          nodes.push(accept);
        } else {
          nodes.push(h("p", { class: "result" }, t("no_deal")));
        }
        out.replaceChildren(...nodes);
      } catch (err) {
        out.replaceChildren(h("p", { class: "result warn" }, err.message));
      } finally {
        go.disabled = false;
      }
    });
    details.append(h("summary", {}, labelNodes("better_price")),
      h("label", { for: "floor", class: "hint" }, labelNodes("floor_label")), floor, go, out);
    return details;
  }

  function resetCompose() {
    state.offerBody = null;
    renderOffer();
    $("compose").scrollIntoView({ behavior: "smooth" });
  }

  // ---- my pickups
  const STEP_ORDER = ["proposed", "scheduled", "collected", "paid"];
  async function loadPickups() {
    const box = $("pickups");
    try {
      const body = await api(`/farmers/${encodeURIComponent(state.farmerId)}/pickups`);
      if (!body.pickups.length) { box.replaceChildren(h("p", { class: "empty" }, t("no_pickups"))); return; }
      box.replaceChildren(...body.pickups.map((p) => {
        const reached = STEP_ORDER.indexOf(p.status);
        return h("div", { class: "pickup" },
          h("div", { class: "top-line" }, h("strong", {}, p.company_name),
            h("span", { class: `pill ${p.status}` }, t(`s_${p.status}`) || p.status)),
          h("span", { class: "hint" }, `${Number(p.matched_kg).toLocaleString(LOCALE[state.lang])} kg · ${rupees(p.price_agreed_per_kg)}/kg`),
          p.slots && p.slots.length ? h("span", {}, formatWindow(p.slots[0])) : null,
          p.status === "paid" && p.payout_inr ? h("span", { class: "result ok" }, `${t("s_paid")}: ${rupees(p.payout_inr)}`) : null,
          p.status === "waitlisted" && p.status_reason ? h("span", { class: "hint" }, p.status_reason) : null,
          h("div", { class: "steps", "aria-hidden": "true" }, STEP_ORDER.map((_, i) => h("i", { class: i <= reached ? "on" : "" }))),
        );
      }));
    } catch {
      box.replaceChildren(h("p", { class: "empty" }, t("error_generic")));
    }
  }

  // ---- no-burn proof
  function renderDistrictSelect() {
    let select = $("proof-district");
    if (!select) {
      select = h("select", { id: "proof-district", "aria-label": "District" });
      $("proof-send").before(select);
    }
    const current = select.value;
    const idx = state.lang === "pa" ? 0 : 1;
    select.replaceChildren(...Object.entries(DISTRICTS).map(([name, local]) =>
      h("option", { value: name }, state.lang === "en" ? name : `${local[idx]} (${name})`)));
    const guess = Object.keys(DISTRICTS).find((d) => (state.lastPlace || "").includes(d)
      || DISTRICTS[d].some((n) => (state.lastPlace || "").includes(n)));
    select.value = current || guess || "Sangrur";
  }

  async function sendProof() {
    const file = $("proof-photo").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("photo", file);
    const params = new URLSearchParams({ district: $("proof-district").value });
    $("proof-send").disabled = true;
    $("proof-result").textContent = "…";
    try {
      const body = await api(`/farmers/${encodeURIComponent(state.farmerId)}/no-burn-proof?${params}`, { method: "POST", body: form });
      const out = $("proof-result");
      out.className = `result ${body.disputed ? "warn" : "ok"}`;
      out.textContent = t("trust_result", { s: Number(body.trust_score).toFixed(2), sat: t(`sat_${body.satellite_corroboration}`) })
        + (body.disputed ? ` ${t("disputed")}` : "");
    } catch (err) {
      $("proof-result").textContent = err.message;
    } finally {
      $("proof-send").disabled = false;
    }
  }

  // ---- wiring
  function init() {
    let id = saved.get("parali_farmer_id");
    if (!id) {
      id = `farmer_${Math.random().toString(36).slice(2, 10)}`;
      saved.set("parali_farmer_id", id);
    }
    state.farmerId = id;

    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));

    makeRecorder($("mic"), $("mic-label"), "hold_to_speak", (blob) => sendDraft({ audio: blob }));
    makeRecorder($("answer-mic"), $("answer-label"), "hold_to_answer", (blob) => sendDraft({ audio: blob }));

    $("send-typed").addEventListener("click", () => {
      const text = $("typed").value.trim();
      if (text) { sendDraft({ text }); $("typed").value = ""; }
    });
    $("photo").addEventListener("change", () => {
      state.photo = $("photo").files[0] || null;
      $("photo").closest(".tool").classList.toggle("done", !!state.photo);
      setLabel($("photo-label"), state.photo ? "photo_added" : "add_photo");
    });
    $("locate").addEventListener("click", () => {
      if (!navigator.geolocation) { toast(t("location_failed")); return; }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          state.location = { lat: pos.coords.latitude.toFixed(5), lon: pos.coords.longitude.toFixed(5) };
          $("locate").classList.add("done");
          setLabel($("locate-label"), "location_added");
        },
        () => toast(t("location_failed")),
        { enableHighAccuracy: true, timeout: 10000 },
      );
    });
    $("confirm-btn").addEventListener("click", confirmListing);
    $("listen-confirm").addEventListener("click", () => state.draft && playAudio(state.draft.follow_up || state.draft.confirm_summary));
    $("proof-photo").addEventListener("change", () => {
      const has = !!$("proof-photo").files[0];
      $("proof-send").disabled = !has;
      $("proof-photo").closest(".tool").classList.toggle("done", has);
      setLabel($("proof-label"), has ? "photo_added" : "add_photo");
    });
    $("proof-send").addEventListener("click", sendProof);

    const lang = saved.get("parali_lang");
    if (lang && STR[lang]) {
      setLanguage(lang);
    } else {
      state.lang = "pa";
      document.querySelectorAll("[data-t]").forEach((el) => setLabel(el, el.dataset.t));
      $("lang-gate").hidden = false;
    }
  }

  init();
})();
