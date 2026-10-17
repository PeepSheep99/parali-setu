// Kisan: the farmer's app, in two views of one booking.
// Phone: a conversation with the talking agent (/agent/turn).
// Laptop: the same booking as a step-by-step page (/listings/draft, /confirm).
// Display only: every price, weight, payout and slot shown comes from the API.
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
    lang: null, view: null, farmerId: null,
    conversationId: null, talkPhoto: null, busy: false,
    draft: null, edits: {}, location: null, deskPhoto: null, offer: null,
  };

  // ---- storage: per-device conveniences only; tolerate blocked storage
  const saved = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  // ---- text
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
    for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
    return el;
  }
  function labelNodes(key, vars) {
    const nodes = [t(key, vars)];
    if (state.lang !== "en") nodes.push(h("span", { class: "sub", lang: "en" }, en(key, vars)));
    return nodes;
  }
  const setLabel = (el, key, vars) => el.replaceChildren(...labelNodes(key, vars));
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
    audio.play().catch(() => { /* autoplay blocked: the replay button works */ });
  }

  // ---- API
  async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try { body = await resp.json(); } catch { /* empty body */ }
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : t("error_generic"));
    return body;
  }
  const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  // ---- formatting (display only). Explicit names: browser locale data for
  // pa-IN is often missing and renders months as "M10".
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
    const [y, m, d] = String(iso || "").slice(0, 10).split("-").map(Number);
    return y && m && d ? new Date(y, m - 1, d) : null;
  }
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  function formatSlot(slot) {
    const d = slot && parseDay(slot.date);
    if (!d) return t("not_given");
    return `${WEEKDAYS[state.lang][d.getDay()]}, ${d.getDate()} ${MONTHS[state.lang][d.getMonth()]}, ${hm(slot.window_start_min)}–${hm(slot.window_end_min)}`;
  }
  function formatLabel(label) {   // "2026-10-19 09:00-12:00" from the API
    const m = /^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})-(\d{2}):(\d{2})$/.exec(label || "");
    return m ? formatSlot({ date: m[1], window_start_min: +m[2] * 60 + +m[3], window_end_min: +m[4] * 60 + +m[5] }) : (label || t("not_given"));
  }
  function formatDate(iso) {
    const d = parseDay(iso);
    return d ? `${d.getDate()} ${MONTHS[state.lang][d.getMonth()]}` : null;
  }
  const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString(LOCALE[state.lang], { hour: "numeric", minute: "2-digit" }); };
  const rupees = (n) => `₹${Number(n).toLocaleString(LOCALE[state.lang], { maximumFractionDigits: 2 })}`;
  const perKg = (n) => `₹${Number(n).toLocaleString(LOCALE[state.lang], { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${t("per_kg")}`;
  const kg = (n) => `${Number(n).toLocaleString(LOCALE[state.lang], { maximumFractionDigits: 0 })} kg`;

  // ---- recording: tap to start, tap to stop (or hold and release), sent as
  // 16 kHz mono WAV, which Gemini and Cloud Speech-to-Text both accept.
  async function toWav(blob) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const decoded = await new Ctx().decodeAudioData(await blob.arrayBuffer());
    const rate = 16000;
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const pcm = (await offline.startRendering()).getChannelData(0);
    const view = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const str = (o, s) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
    str(0, "RIFF"); view.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    str(36, "data"); view.setUint32(40, pcm.length * 2, true);
    pcm.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
    return new Blob([view], { type: "audio/wav" });
  }

  function makeRecorder(button, labelEl, idleKey, onAudio, isDisabled = () => false) {
    let recorder = null, pressedAt = 0, tapMode = false;
    async function start() {
      if (!navigator.mediaDevices || !window.MediaRecorder) { toast(t("mic_unavailable")); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = async () => {
          stream.getTracks().forEach((tr) => tr.stop());
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          recorder = null;
          button.classList.remove("recording");
          setLabel(labelEl, idleKey);
          if (blob.size < 2000) return;
          try { onAudio(await toWav(blob)); } catch { toast(t("mic_unavailable")); }
        };
        recorder.start();
        button.classList.add("recording");
        setLabel(labelEl, "listening");
      } catch {
        toast(t("mic_unavailable"));
      }
    }
    const stop = () => { if (recorder && recorder.state === "recording") recorder.stop(); };
    button.addEventListener("pointerdown", (e) => {
      if (isDisabled()) return;
      e.preventDefault();
      if (recorder) { stop(); tapMode = false; return; }
      pressedAt = Date.now();
      tapMode = false;
      start();
    });
    button.addEventListener("pointerup", () => {
      if (isDisabled() || !recorder) return;
      if (Date.now() - pressedAt > 450) stop(); else tapMode = true;
    });
    button.addEventListener("keydown", (e) => {
      if (isDisabled() || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      if (recorder) stop(); else start();
    });
  }

  // ---- view and language
  function setView(view) {
    state.view = view;
    saved.set("parali_view", view);
    document.body.classList.toggle("view-phone", view === "phone");
    document.body.classList.toggle("view-laptop", view === "laptop");
    document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    if (view === "laptop") { loadPrices(); loadPickups(); }
  }

  function setLanguage(lang) {
    const changed = state.lang && state.lang !== lang;
    state.lang = lang;
    saved.set("parali_lang", lang);
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach((el) => setLabel(el, el.dataset.t));
    document.querySelectorAll(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    $("typed").placeholder = t("type_placeholder");
    $("kbd-input").placeholder = t("type_placeholder");
    $("lang-gate").hidden = true;
    $("app").hidden = false;
    if (changed || !$("log").children.length) {
      const keep = saved.get("parali_conv");      // resetTalk forgets it; a reload should bring the chat back
      resetTalk();
      if (!changed && keep) { saved.set("parali_conv", keep); restoreTalk(); }
    }
    if (state.draft) renderConfirm();
    if (state.offer) renderOffer();
    renderDistrictSelect();
    loadPrices();
    loadPickups();
  }

  // =========================================================================
  // Phone view: talking to the agent
  // =========================================================================
  function scrollLog() { const log = $("log"); log.scrollTop = log.scrollHeight; }

  function resetTalk() {
    state.conversationId = null;
    saved.set("parali_conv", "");
    $("log").replaceChildren(h("div", { class: "bubble agent" }, t("greeting")));
  }

  // After a reload the chat comes back: the saved conversation's words are shown again.
  async function restoreTalk() {
    const id = saved.get("parali_conv");
    if (!id || state.conversationId) return;
    try {
      const conv = await api(`/agent/conversations/${encodeURIComponent(id)}`);
      if (conv.farmer_id !== state.farmerId || !(conv.turns || []).length || state.conversationId) return;
      state.conversationId = id;
      $("log").replaceChildren(...conv.turns.map((turn) => turn.role === "user"
        ? h("div", { class: "bubble farmer" }, turn.text,
            turn.english && state.lang !== "en" ? h("span", { class: "en", lang: "en" }, turn.english) : null)
        : h("div", { class: "bubble agent" }, turn.text)));
      scrollLog();
    } catch { /* an old conversation that is gone just starts fresh */ }
  }

  function farmerBubble(text, english) {
    $("log").append(h("div", { class: "bubble farmer" }, text,
      english && state.lang !== "en" ? h("span", { class: "en", lang: "en" }, english) : null));
    scrollLog();
  }

  function agentBubble(reply) {
    const bubble = h("div", { class: "bubble agent" }, reply.text,
      reply.audio_base64 ? h("button", { type: "button", class: "replay", onclick: () => playAudio(reply) }, `▶ ${t("replay")}`) : null);
    $("log").append(bubble);
    scrollLog();
  }

  function thinking(on) {
    document.querySelector(".log .dots")?.remove();
    if (on) { $("log").append(h("div", { class: "dots", "aria-label": t("thinking") }, h("i"), h("i"), h("i"))); scrollLog(); }
    $("talk-mic").classList.toggle("busy", on);
  }

  function cropName(c) { return c === "wheat_stubble" ? t("wheat") : c === "rice_stubble" ? t("rice") : null; }

  function draftCard(card) {
    const f = card.fields || {};
    const items = [
      f.acres ? `${f.acres} ${t("f_acres")}` : null, cropName(f.crop_type),
      f.village_or_district || null, f.sowing_deadline ? `${t("f_sowing")}: ${formatDate(f.sowing_deadline)}` : null,
    ].filter(Boolean);
    const missing = (card.missing_fields || []).map((m) => ({ quantity: "f_acres", crop_type: "f_crop", location: "f_place", sowing_deadline: "f_sowing" }[m]));
    return h("div", { class: "tcard" },
      h("div", { class: "mini-chips" }, items.map((i) => h("span", { class: "mini-chip" }, i)),
        missing.filter(Boolean).map((k) => h("span", { class: "mini-chip missing" }, `${t(k)}?`))));
  }

  function priceCard(card) {
    return h("div", { class: "tcard" },
      h("span", { class: "hint" }, `${t("price_today")} · ${card.district}`),
      h("span", { class: "big-price" }, perKg(card.price_per_kg)),
      h("div", { class: "badges" }, h("span", { class: "badge" }, t("field_free")), h("span", { class: "badge" }, t("paid_same_day"))));
  }

  function offerCard(card) {
    const book = h("button", { type: "button", class: "primary wide" }, labelNodes("book_this"));
    book.addEventListener("click", () => acceptBooking(card.booking_id, book, (result) => {
      box.replaceWith(bookedCard({ pickup_window: result.pickup_window, payout_inr: result.booking.payout_estimate_inr,
                                   pickup_window_spoken: card.pickup_window_spoken, booking_code: result.booking.booking_code }));
    }));
    const box = h("div", { class: "tcard offer" },
      h("div", { class: "kv" }, h("span", { class: "k" }, t("price_today")), h("span", { class: "v" }, perKg(card.price_per_kg))),
      h("div", { class: "kv" }, h("span", { class: "k" }, t("straw")), h("span", { class: "v" }, kg(card.kg))),
      h("div", { class: "kv" }, h("span", { class: "k" }, t("pickup")), h("span", { class: "v" }, card.pickup_window_spoken || formatLabel(card.pickup_window))),
      h("span", { class: "hint" }, t("you_get")),
      h("span", { class: "money" }, rupees(card.payout_inr)),
      h("div", { class: "badges" }, h("span", { class: "badge" }, t("field_free")), h("span", { class: "badge" }, t("paid_same_day"))),
      card.partner_crew ? h("p", { class: "note" }, t("partner_crew")) : null,
      card.farm ? h("p", { class: "readback" }, `${t("check_details")}: ` + [card.farm.name, card.farm.phone, card.farm.village,
        card.farm.acres ? `${card.farm.acres} acres` : null, card.farm.location].filter(Boolean).join(" · ")) : null,
      card.offer_valid_until ? h("p", { class: "hint" }, t("held_until", { t: clock(card.offer_valid_until) })) : null,
      h("p", { class: "demo-note" }, t("demo_note")),
      book);
    return box;
  }

  function bookedCard(card) {
    return h("div", { class: "tcard done" }, h("strong", {}, labelNodes("booked")),
      h("span", {}, t("booked_line", { w: card.pickup_window_spoken || formatLabel(card.pickup_window), p: rupees(card.payout_inr) })),
      card.booking_code ? h("p", { class: "booking-code" }, `${t("booking_id")}: `, h("strong", {}, card.booking_code)) : null,
      card.booking_code ? h("p", { class: "demo-note" }, t("sms_sent")) : null,
      h("p", { class: "demo-note" }, t("demo_note")));
  }

  function renderCards(cards) {
    // Show only the latest card of each kind from this turn, in a sensible order.
    const latest = {};
    for (const c of cards || []) latest[c.type] = c;
    const order = latest.booked ? ["booked"] : latest.offer ? ["offer"] : ["price", "draft", "bookings"];
    for (const type of order) {
      const c = latest[type];
      if (!c) continue;
      if (type === "draft") $("log").append(draftCard(c));
      else if (type === "price") $("log").append(priceCard(c));
      else if (type === "offer") $("log").append(offerCard(c));
      else if (type === "booked") $("log").append(bookedCard(c));
      else if (type === "bookings") openSheet();
    }
    scrollLog();
  }

  async function sendTurn({ audio, text }) {
    if (state.busy) {
      if (text) {      // queue it: shown greyed now, sent as soon as the reply arrives
        state.queued = text;
        $("log").append(h("div", { class: "bubble farmer queued", "data-queued": "1" }, text));
        scrollLog();
      } else toast(t("wait_reply"));
      return;
    }
    state.busy = true;
    if (text) {
      const waiting = $("log").querySelector("[data-queued]");
      if (waiting && waiting.textContent === text) { waiting.classList.remove("queued"); waiting.removeAttribute("data-queued"); }
      else farmerBubble(text);
    }
    thinking(true);
    const form = new FormData();
    form.append("farmer_id", state.farmerId);
    form.append("language", LANG_API[state.lang]);
    if (state.conversationId) form.append("conversation_id", state.conversationId);
    if (text) form.append("text", text);
    if (audio) form.append("audio", audio, "speech.wav");
    if (state.talkPhoto) form.append("photo", state.talkPhoto);
    try {
      const body = await api("/agent/turn", { method: "POST", body: form });
      thinking(false);
      state.conversationId = body.conversation_id;
      saved.set("parali_conv", state.conversationId);
      state.talkPhoto = null;
      document.querySelector("label[for=talk-photo]").classList.remove("done");
      if (audio) farmerBubble(body.heard.text, body.heard.english);
      agentBubble(body.reply);
      renderCards(body.cards);
      playAudio(body.reply);
      if ((body.cards || []).some((c) => c.type === "offer" || c.type === "booked")) loadPickups();
    } catch (err) {
      thinking(false);
      toast(err.message);
    } finally {
      state.busy = false;
      if (state.queued) { const next = state.queued; state.queued = null; sendTurn({ text: next }); }
    }
  }

  function openSheet() { loadPickups(); $("sheet").hidden = false; }

  // ---- live listening: stream 16 kHz PCM over a WebSocket; captions come
  // back while the farmer speaks; the final words are one guarded agent turn.
  const WORKLET = `class Tap extends AudioWorkletProcessor {
    process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
  }
  registerProcessor("tap", Tap);`;
  const live = { ws: null, ctx: null, stream: null, bubble: null };

  function liveUrl() { return `${API_BASE.replace(/^http/, "ws")}/agent/live`; }

  async function startLive() {
    if (state.busy) return;
    if (!navigator.mediaDevices || !window.AudioWorkletNode || !window.WebSocket) { toast(t("live_failed")); return; }
    state.busy = true;
    try {
      live.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      live.ctx = new AudioContext({ sampleRate: 16000 });
      await live.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));
      const source = live.ctx.createMediaStreamSource(live.stream);
      const tap = new AudioWorkletNode(live.ctx, "tap");
      live.ws = new WebSocket(liveUrl());
      live.ws.binaryType = "arraybuffer";
      let pending = [];
      tap.port.onmessage = (e) => {
        pending.push(e.data);
        const total = pending.reduce((n, a) => n + a.length, 0);
        if (total >= 1600 && live.ws && live.ws.readyState === 1) {   // about 100 ms per frame
          const pcm = new Int16Array(total);
          let o = 0;
          for (const a of pending) for (let k = 0; k < a.length; k++) pcm[o++] = Math.max(-1, Math.min(1, a[k])) * 0x7fff;
          live.ws.send(pcm.buffer);
          pending = [];
        }
      };
      live.ws.onopen = () => {
        live.ws.send(JSON.stringify({ farmer_id: state.farmerId, language: LANG_API[state.lang], conversation_id: state.conversationId }));
        source.connect(tap);
      };
      live.ws.onmessage = (e) => onLiveEvent(JSON.parse(e.data));
      live.ws.onerror = () => { toast(t("live_failed")); stopLive(true); };
      live.ws.onclose = () => {
        stopAudio();
        thinking(false);
        state.busy = false;
        $("talk-mic").classList.remove("streaming");
        setLabel($("talk-label"), "speak");
      };
      live.bubble = h("div", { class: "bubble farmer live" }, "…");
      $("log").append(live.bubble);
      scrollLog();
      $("talk-mic").classList.add("streaming");
      setLabel($("talk-label"), "live_listening");
    } catch {
      toast(t("live_failed"));
      stopLive(true);
    }
  }

  function stopAudio() {
    if (live.stream) live.stream.getTracks().forEach((tr) => tr.stop());
    if (live.ctx) live.ctx.close().catch(() => {});
    live.stream = null;
    live.ctx = null;
  }

  function stopLive(abort) {
    stopAudio();
    if (live.ws && live.ws.readyState === 1 && !abort) {
      live.ws.send(JSON.stringify({ type: "end" }));
      thinking(true);
    } else if (live.ws) {
      live.ws.close();
    }
    $("talk-mic").classList.remove("streaming");
    setLabel($("talk-label"), "speak");
    if (abort) state.busy = false;
  }

  function onLiveEvent(event) {
    if (event.type === "caption" && live.bubble) {
      live.bubble.textContent = event.text;
      live.bubble.classList.toggle("live", !event.final);
      scrollLog();
    } else if (event.type === "reply") {
      thinking(false);
      state.conversationId = event.conversation_id;
      if (live.bubble && event.heard.english && state.lang !== "en") live.bubble.append(h("span", { class: "en", lang: "en" }, event.heard.english));
      agentBubble(event.reply);
      renderCards(event.cards);
      playAudio(event.reply);
      if ((event.cards || []).some((c) => c.type === "offer" || c.type === "booked")) loadPickups();
    } else if (event.type === "error") {
      thinking(false);
      if (live.bubble && live.bubble.textContent === "…") live.bubble.remove();
      toast(event.detail);
    }
  }

  // =========================================================================
  // Laptop view: the step-by-step booking
  // =========================================================================
  function setStep(step) {
    const order = ["tell", "check", "book"];
    order.forEach((s, i) => {
      const li = $(`step-${s}`);
      li.classList.toggle("on", s === step);
      li.classList.toggle("done", i < order.indexOf(step));
    });
  }
  function working(key) {
    if (key) { setLabel($("working-text"), key); $("working").hidden = false; } else { $("working").hidden = true; }
  }

  async function sendDraft({ audio, text }) {
    const form = new FormData();
    form.append("farmer_id", state.farmerId);
    form.append("language", LANG_API[state.lang]);
    if (state.draft) form.append("draft_id", state.draft.draft_id);
    if (text) form.append("text", text);
    if (audio) form.append("audio", audio, "speech.wav");
    if (state.location) { form.append("lat", state.location.lat); form.append("lon", state.location.lon); }
    if (state.deskPhoto) form.append("photo", state.deskPhoto);
    working("understanding");
    try {
      const body = await api("/listings/draft", { method: "POST", body: form });
      state.deskPhoto = null;
      state.draft = body;
      state.edits = {};
      state.offer = null;
      $("offer").hidden = true;
      renderConfirm();
      setStep("check");
      playAudio(body.follow_up || body.confirm_summary);
      $("confirm").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message);
    } finally {
      working(null);
    }
  }

  const currentFields = () => ({ ...(state.draft ? state.draft.fields : {}), ...state.edits });

  function renderConfirm() {
    const d = state.draft;
    $("confirm").hidden = !d;
    if (!d) return;
    $("question").hidden = !d.follow_up;
    if (d.follow_up) $("question-text").textContent = d.follow_up.text;
    $("transcript").textContent = d.transcript ? `“${d.transcript}”` : "";
    const f = currentFields();
    const chips = [
      { field: "acres", key: "f_acres", value: f.acres ? String(f.acres) : null },
      { field: "crop_type", key: "f_crop", value: cropName(f.crop_type) },
      { field: "village_or_district", key: "f_place", value: f.village_or_district || (state.location ? t("location_added") : null) },
      { field: "sowing_deadline", key: "f_sowing", value: formatDate(f.sowing_deadline) },
      { field: "contact", key: "f_phone", value: f.contact || null, optional: true },
    ];
    const nodes = chips.map((c) => h("button", { type: "button", class: `chip${c.value || c.optional ? "" : " missing"}`, "data-field": c.field, onclick: () => editChip(c.field) },
      h("span", { class: "k" }, labelNodes(c.key)), h("span", { class: "v" }, c.value || (c.optional ? "—" : t("not_given"))),
      h("span", { class: "edit", "aria-hidden": "true" }, "✎")));
    if (d.quality && d.quality.grade && d.quality.grade !== "unknown") {
      nodes.push(h("div", { class: "chip" }, h("span", { class: "k" }, labelNodes("f_quality")), h("span", { class: "v" }, d.quality.grade)));
    }
    if (d.location_approximate) nodes.push(h("p", { class: "note" }, labelNodes("approx_location")));
    $("chips").replaceChildren(...nodes);
    $("confirm-btn").disabled = !(f.acres || f.quantity_kg) || !f.crop_type || !(f.village_or_district || state.location);
  }

  function editChip(field) {
    const f = currentFields();
    let input;
    if (field === "acres") input = h("input", { type: "number", min: "0.5", max: "1000", step: "0.5", inputmode: "decimal", value: f.acres || "" });
    else if (field === "crop_type") {
      input = h("select", {}, h("option", { value: "rice_stubble", selected: f.crop_type !== "wheat_stubble" }, t("rice")),
        h("option", { value: "wheat_stubble", selected: f.crop_type === "wheat_stubble" }, t("wheat")));
    } else if (field === "sowing_deadline") input = h("input", { type: "date", value: f.sowing_deadline ? String(f.sowing_deadline).slice(0, 10) : "" });
    else if (field === "contact") input = h("input", { type: "tel", inputmode: "tel", maxlength: "15", value: f.contact || "" });
    else input = h("input", { type: "text", maxlength: "120", value: f.village_or_district || "" });
    const save = h("button", { type: "button", class: "primary" }, "✓");
    $("chips").querySelector(`[data-field="${field}"]`).replaceWith(h("div", { class: "chip-editor" }, input, save));
    input.focus();
    const commit = () => {
      const raw = input.value.trim();
      if (raw) state.edits[field] = field === "acres" ? Number(raw) : raw;
      renderConfirm();
    };
    save.addEventListener("click", commit);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") commit(); });
  }

  async function confirmListing() {
    const edits = Object.fromEntries(Object.entries(state.edits).filter(([, v]) => v !== "" && v !== null));
    working("finding");
    $("confirm-btn").disabled = true;
    try {
      const body = await postJson(`/listings/${state.draft.draft_id}/confirm`, { farmer_id: state.farmerId, edits: Object.keys(edits).length ? edits : null });
      state.draft = null;
      state.edits = {};
      $("confirm").hidden = true;
      state.offer = body;
      renderOffer();
      setStep("book");
      playAudio(body.explanation);
      $("offer").scrollIntoView({ behavior: "smooth", block: "start" });
      loadPickups();
    } catch (err) {
      toast(err.message);
      $("confirm-btn").disabled = false;
    } finally {
      working(null);
    }
  }

  const REASONS = ["booked", "no_capacity", "deadline_passed", "too_far", "beyond_horizon", "expired"];
  const reasonText = (code) => (REASONS.includes(code) ? t(`r_${code}`) : t("error_generic"));

  function renderOffer() {
    const body = state.offer;
    const box = $("offer");
    if (!body) { box.hidden = true; return; }
    box.hidden = false;
    if (body.status === "out_of_area") { box.replaceChildren(h("p", { class: "result warn" }, t("out_of_area"))); return; }
    const b = body.booking;
    if (b.status === "unschedulable") {
      box.replaceChildren(h("p", { class: "result warn" }, t("unschedulable", { r: reasonText(b.status_reason_code) })));
      return;
    }
    const booked = b.status === "booked";
    const accept = h("button", { type: "button", class: "primary wide", disabled: booked }, labelNodes(booked ? "booked" : "accept_slot"));
    accept.addEventListener("click", () => acceptBooking(b.id, accept, () => { b.status = "booked"; renderOffer(); }));
    const whyOut = h("p", { class: "result", "aria-live": "polite" });
    const why = h("button", { type: "button", class: "ghost", onclick: () => whyPrice(b.id, whyOut) }, labelNodes("why_price"));
    const impact = body.impact_if_collected;
    box.replaceChildren(...[
      h("h2", {}, labelNodes("offer_title")),
      h("div", { class: "offer-grid" },
        h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("price_today")), h("span", { class: "v" }, `${perKg(b.price_per_kg)} · ${b.district}`)),
        h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("straw")), h("span", { class: "v" }, kg(b.kg))),
        h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("pickup")), h("span", { class: "v" }, formatSlot(b.slots[0]))),
        h("div", { class: "kv" }, h("span", { class: "k" }, labelNodes("depot")), h("span", { class: "v" }, b.depot_name))),
      h("span", { class: "hint" }, labelNodes("you_get")),
      h("span", { class: "money" }, rupees(b.payout_estimate_inr)),
      h("div", { class: "badges" }, h("span", { class: "badge" }, t("field_free")), h("span", { class: "badge" }, t("paid_same_day"))),
      b.partner_crew ? h("p", { class: "note" }, t("partner_crew")) : null,
      impact ? h("div", { class: "impact" }, h("strong", {}, labelNodes("instead_of_burning")),
        h("p", {}, t("impact_line", { ghg: impact.ghg_avoided_t_co2e, pm: Math.round(impact.pm25_avoided_kg) }))) : null,
      !booked && b.offer_expires_at ? h("p", { class: "hint" }, t("held_until", { t: clock(b.offer_expires_at) })) : null,
      h("div", { class: "row" }, accept, why), whyOut].filter(Boolean));
  }

  async function whyPrice(bookingId, out) {
    out.textContent = "…";
    try {
      const body = await api(`/bookings/${encodeURIComponent(bookingId)}/price-explanation?language=${encodeURIComponent(LANG_API[state.lang])}`);
      out.textContent = body.explanation;
    } catch (err) {
      out.textContent = err.message;
    }
  }

  // ---- shared: accept, prices, my pickups, proof
  async function acceptBooking(bookingId, button, onDone) {
    button.disabled = true;
    try {
      const body = await postJson(`/bookings/${encodeURIComponent(bookingId)}/accept`, { farmer_id: state.farmerId });
      toast(`${t("booked")} · ${formatLabel(body.pickup_window)}`);
      onDone(body);
      loadPickups();
    } catch (err) {
      toast(err.message);
      button.disabled = false;
    }
  }

  async function loadPrices() {
    if (state.view !== "laptop") return;
    try {
      const { prices } = await api("/prices/today");
      $("prices").replaceChildren(...prices.map((p) => {
        const local = DISTRICTS[p.district] ? (state.lang === "pa" ? DISTRICTS[p.district][0] : state.lang === "hi" ? DISTRICTS[p.district][1] : p.district) : p.district;
        return h("div", { class: `price-row ${p.reason_code}`, title: p.reason }, h("span", {}, local), h("span", { class: "v" }, perKg(p.price_per_kg)));
      }));
    } catch {
      $("prices").replaceChildren(h("p", { class: "empty" }, t("error_generic")));
    }
  }

  const STEP_ORDER = ["offered", "booked", "collected", "paid"];
  async function loadPickups() {
    let bookings = [];
    try { ({ bookings } = await api(`/farmers/${encodeURIComponent(state.farmerId)}/bookings`)); } catch { /* shown as empty */ }
    const rows = bookings.length ? bookings.map((b) => {
      const reached = STEP_ORDER.indexOf(b.status);
      const cancel = ["offered", "booked"].includes(b.status)
        ? h("button", { type: "button", class: "ghost", onclick: (e) => cancelBooking(b.id, e.currentTarget) }, t("cancel")) : null;
      const book = b.status === "offered" && b.slots && b.slots.length
        ? h("button", { type: "button", class: "primary", "data-book": b.id }, t("book_this")) : null;
      return h("div", { class: "pickup" },
        h("div", { class: "top-line" }, h("strong", {}, `${b.district} · ${kg(b.kg)}`), h("span", { class: `pill ${b.status}` }, t(`s_${b.status}`))),
        h("span", { class: "hint" }, `${perKg(b.price_per_kg)} · ${b.depot_name}`),
        b.slots && b.slots.length ? h("span", {}, formatSlot(b.slots[0])) : null,
        b.status === "paid" && b.payout_inr ? h("span", { class: "result ok" }, t("paid_line", { p: rupees(b.payout_inr) })) : null,
        b.status === "unschedulable" ? h("span", { class: "note" }, reasonText(b.status_reason_code)) : null,
        b.booking_code ? h("span", { class: "hint" }, `${t("booking_id")}: ${b.booking_code}`) : null,
        reached >= 0 ? h("div", { class: "steps" }, STEP_ORDER.map((step, i) =>
          h("span", { class: i <= reached ? "on" : "" }, h("i", {}), h("small", {}, t(`s_${step}_short`))))) : null,
        h("div", { class: "row-actions" }, book, cancel));
    }) : [h("p", { class: "empty" }, t("no_pickups"))];
    $("desk-pickups").replaceChildren(...rows.map((r) => r.cloneNode(true)));
    $("sheet-list").replaceChildren(...rows);
    // cloneNode drops listeners; rebind the buttons in the desk copy
    $("desk-pickups").querySelectorAll(".pickup").forEach((el, i) => {
      const b = bookings[i];
      const bookBtn = el.querySelector("[data-book]");
      if (bookBtn) bookBtn.addEventListener("click", () => acceptBooking(b.id, bookBtn, () => {}));
      const cancelBtn = el.querySelector(".ghost");
      if (cancelBtn && b) cancelBtn.addEventListener("click", () => cancelBooking(b.id, cancelBtn));
    });
    $("sheet-list").querySelectorAll("[data-book]").forEach((btn) =>
      btn.addEventListener("click", () => acceptBooking(btn.dataset.book, btn, () => {})));
    state.latestDistrict = (bookings.find((b) => ["offered", "booked", "collected", "paid"].includes(b.status)) || {}).district || null;
  }

  async function cancelBooking(bookingId, button) {
    if (!window.confirm(t("cancel_sure"))) return;
    if (button) button.disabled = true;
    try {
      await postJson(`/bookings/${encodeURIComponent(bookingId)}/cancel`, { farmer_id: state.farmerId });
      toast(t("cancelled"));
      document.querySelectorAll(".pickup").forEach((el) => {      // gone at once, in both lists
        if (el.contains(button) || el.querySelector(`[data-book="${bookingId}"]`)) el.remove();
      });
      await loadPickups();
    } catch (err) {
      toast(err.message);
      if (button) button.disabled = false;
    }
  }

  // Phone view: a field photo from the sheet goes to the no-burn proof, for the district of the latest pickup.
  async function sendPhoneProof(file) {
    if (!state.latestDistrict) { toast(t("proof_needs_booking")); return; }
    const form = new FormData();
    form.append("photo", file);
    try {
      const body = await api(`/farmers/${encodeURIComponent(state.farmerId)}/no-burn-proof?district=${encodeURIComponent(state.latestDistrict)}`, { method: "POST", body: form });
      toast(body.disputed ? t("proof_disputed") : t("proof_ok", { sat: t(`sat_${body.satellite_corroboration}`) }));
    } catch (err) { toast(err.message); }
  }

  function renderDistrictSelect() {
    const select = $("proof-district");
    const current = select.value;
    const idx = state.lang === "pa" ? 0 : 1;
    select.replaceChildren(...Object.entries(DISTRICTS).map(([name, local]) =>
      h("option", { value: name }, state.lang === "en" ? name : `${local[idx]} (${name})`)));
    if (current) select.value = current;
  }

  async function sendProof() {
    const file = $("proof-photo").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("photo", file);
    $("proof-send").disabled = true;
    $("proof-result").textContent = "…";
    try {
      const body = await api(`/farmers/${encodeURIComponent(state.farmerId)}/no-burn-proof?district=${encodeURIComponent($("proof-district").value)}`, { method: "POST", body: form });
      const out = $("proof-result");
      out.className = `result ${body.disputed ? "warn" : "ok"}`;
      out.textContent = body.disputed ? t("proof_disputed") : t("proof_ok", { sat: t(`sat_${body.satellite_corroboration}`) });
    } catch (err) {
      $("proof-result").textContent = err.message;
    } finally {
      $("proof-send").disabled = false;
    }
  }

  // ---- wiring
  function init() {
    let id = saved.get("parali_farmer_id");
    if (!id) { id = `farmer_${Math.random().toString(36).slice(2, 10)}`; saved.set("parali_farmer_id", id); }
    state.farmerId = id;

    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));
    document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

    // phone view
    makeRecorder($("talk-mic"), $("talk-label"), "speak", (wav) => sendTurn({ audio: wav }), () => $("live-toggle").checked);
    // Live mode takes over the mic button: tap to start streaming, tap to send.
    $("talk-mic").addEventListener("click", () => {
      if (!$("live-toggle").checked) return;
      if (live.ws && live.ws.readyState <= 1 && live.stream) stopLive(false); else startLive();
    });
    $("live-toggle").checked = saved.get("parali_live") === "1";
    $("live-toggle").addEventListener("change", () => saved.set("parali_live", $("live-toggle").checked ? "1" : "0"));
    $("talk-locate").addEventListener("click", async () => {
      try {
        const body = await postJson("/demo/locate", { farmer_id: state.farmerId, conversation_id: state.conversationId });
        agentBubble(t("located", { d: body.district }));
        toast(body.label);
      } catch (err) { toast(err.message); }
    });
    $("sheet-proof").addEventListener("change", () => {
      const file = $("sheet-proof").files[0];
      $("sheet-proof").value = "";
      if (file) sendPhoneProof(file);
    });
    $("kbd-toggle").addEventListener("click", () => { $("kbd").hidden = !$("kbd").hidden; if (!$("kbd").hidden) $("kbd-input").focus(); });
    $("kbd").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("kbd-input").value.trim();
      if (text) { $("kbd-input").value = ""; sendTurn({ text }); }
    });
    $("talk-photo").addEventListener("change", () => {
      state.talkPhoto = $("talk-photo").files[0] || null;
      if (state.talkPhoto) {
        const img = h("img", { class: "thumb", alt: "", src: URL.createObjectURL(state.talkPhoto) });
        $("log").append(h("div", { class: "bubble farmer" }, img, h("span", { class: "en" }, t("photo_sent_with_next"))));
        scrollLog();
      }
      document.querySelector("label[for=talk-photo]").classList.toggle("done", !!state.talkPhoto);
      if (state.talkPhoto) toast(t("photo_added"));
    });
    $("talk-pickups").addEventListener("click", openSheet);
    $("sheet-close").addEventListener("click", () => { $("sheet").hidden = true; });

    // laptop view
    makeRecorder($("desk-mic"), $("desk-mic-label"), "hold_to_speak", (wav) => sendDraft({ audio: wav }));
    $("send-typed").addEventListener("click", () => {
      const text = $("typed").value.trim();
      if (text) { $("typed").value = ""; sendDraft({ text }); }
    });
    $("desk-photo").addEventListener("change", () => {
      state.deskPhoto = $("desk-photo").files[0] || null;
      $("desk-photo").closest(".tool").classList.toggle("done", !!state.deskPhoto);
      setLabel($("desk-photo-label"), state.deskPhoto ? "photo_added" : "add_photo");
    });
    $("locate").addEventListener("click", async () => {
      // Prototype: a demo farm in Punjab, never the device location (a visitor outside Punjab would be out of area).
      try {
        const body = await postJson("/demo/locate", { farmer_id: state.farmerId });
        state.location = { lat: String(body.lat), lon: String(body.lon) };
        $("locate").classList.add("done");
        setLabel($("locate-label"), "location_added");
        toast(body.label);
      } catch { toast(t("location_failed")); }
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

    const params = new URLSearchParams(location.search);
    const view = ["phone", "laptop"].includes(params.get("view")) ? params.get("view")
      : saved.get("parali_view") || (window.matchMedia("(min-width: 900px)").matches ? "laptop" : "phone");
    setView(view);
    const lang = params.get("lang") || saved.get("parali_lang");
    if (lang && STR[lang]) setLanguage(lang);
    else {
      state.lang = "pa";
      document.querySelectorAll("[data-t]").forEach((el) => setLabel(el, el.dataset.t));
      $("lang-gate").hidden = false;
    }
  }

  init();
})();
