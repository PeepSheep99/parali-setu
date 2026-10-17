// The pickup page: one conversation with the talking agent, for every screen.
// No language step: the farmer speaks or types in Punjabi, Hindi or English
// and the agent answers in the same language (the API detects it). Display
// only: every price, weight, payout and slot shown comes from the API.
(() => {
  const STR = window.KISAN_STRINGS;
  const LANG_API = { hi: "Hindi", pa: "Punjabi", en: "English" };
  const API_LANG = { Hindi: "hi", Punjabi: "pa", English: "en" };
  const LOCALE = { hi: "hi-IN", pa: "pa-IN", en: "en-IN" };
  const $ = (id) => document.getElementById(id);
  const state = { lang: "pa", picked: null, farmerId: null, conversationId: null, talkPhoto: null, busy: false,
                  queued: null, latestDistrict: null };

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

  // ---- API
  async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try { body = await resp.json(); } catch { /* empty body */ }
    if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : t("error_generic"));
    return body;
  }
  const postJson = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  // ---- formatting (display only). Explicit month and day names: browser
  // locale data for pa-IN is often missing.
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
  const DISTRICTS = {
    Sangrur: ["ਸੰਗਰੂਰ", "संगरूर"], Patiala: ["ਪਟਿਆਲਾ", "पटियाला"], Bathinda: ["ਬਠਿੰਡਾ", "बठिंडा"],
    Ludhiana: ["ਲੁਧਿਆਣਾ", "लुधियाना"], Moga: ["ਮੋਗਾ", "मोगा"], Karnal: ["ਕਰਨਾਲ", "करनाल"],
    Kaithal: ["ਕੈਥਲ", "कैथल"], Kurukshetra: ["ਕੁਰੂਕਸ਼ੇਤਰ", "कुरुक्षेत्र"],
  };
  const district = (name) => (DISTRICTS[name] ? (state.lang === "pa" ? DISTRICTS[name][0] : state.lang === "hi" ? DISTRICTS[name][1] : name) : name);
  function parseDay(iso) {
    const [y, m, d] = String(iso || "").slice(0, 10).split("-").map(Number);
    return y && m && d ? new Date(y, m - 1, d) : null;
  }
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  function formatSlot(slot) {
    const d = slot && parseDay(slot.date);
    if (!d) return "";
    return `${WEEKDAYS[state.lang][d.getDay()]}, ${d.getDate()} ${MONTHS[state.lang][d.getMonth()]}, ${hm(slot.window_start_min)}–${hm(slot.window_end_min)}`;
  }
  function formatLabel(label) {   // "2026-10-19 09:00-12:00" from the API
    const m = /^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})-(\d{2}):(\d{2})$/.exec(label || "");
    return m ? formatSlot({ date: m[1], window_start_min: +m[2] * 60 + +m[3], window_end_min: +m[4] * 60 + +m[5] }) : (label || "");
  }
  const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString(LOCALE[state.lang], { hour: "numeric", minute: "2-digit" }); };
  const rupees = (n) => `₹${Number(n).toLocaleString(LOCALE[state.lang], { maximumFractionDigits: 0 })}`;
  const perKg = (n) => `₹${Number(n).toLocaleString(LOCALE[state.lang], { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${t("per_kg")}`;
  const kg = (n) => `${Number(n).toLocaleString(LOCALE[state.lang], { maximumFractionDigits: 0 })} kg`;

  // ---- language: the page follows the farmer. It starts from the device's
  // language (Punjabi if unsure) and switches when the agent hears another one.
  function setUILang(lang) {
    if (!STR[lang]) return;
    state.lang = lang;
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-t]").forEach((el) => setLabel(el, el.dataset.t));
    document.querySelectorAll(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    $("kbd-input").placeholder = t("type_placeholder");
    const hello = document.querySelector(".hello p");
    if (hello) hello.textContent = t("greeting_sub");
    loadPrices();
    loadPickups();
  }
  function startLang() {
    const param = new URLSearchParams(location.search).get("lang");
    if (STR[param]) return param;
    const picked = saved.get("parali_lang_pick");
    if (STR[picked]) { state.picked = picked; return picked; }
    const nav = (navigator.language || "").toLowerCase();
    return nav.startsWith("hi") ? "hi" : nav.startsWith("en-us") || nav.startsWith("en-gb") ? "en" : "pa";
  }

  // ---- speech: the reply text shows at once; its audio is fetched alongside
  async function speak(text, lang, button) {
    try {
      const body = await postJson("/speech", { text, language: LANG_API[lang] || "Punjabi" });
      const audio = $("voice");
      audio.src = `data:audio/mp3;base64,${body.audio_base64}`;
      if (button) button.dataset.audio = body.audio_base64;
      await audio.play();
    } catch { /* autoplay blocked or speech down: the Play button stays */ }
  }

  // ---- recording: tap to start, tap to stop (or hold and release), sent as 16 kHz WAV
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

  function makeRecorder(button, labelEl, onAudio, isDisabled) {
    let recorder = null, pressedAt = 0;
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
          setLabel(labelEl, "speak");
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
      if (recorder) { stop(); return; }
      pressedAt = Date.now();
      start();
    });
    button.addEventListener("pointerup", () => {
      if (isDisabled() || !recorder) return;
      if (Date.now() - pressedAt > 450) stop();
    });
    button.addEventListener("keydown", (e) => {
      if (isDisabled() || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      if (recorder) stop(); else start();
    });
  }

  // ---- conversation
  function scrollLog() { const log = $("log"); log.scrollTop = log.scrollHeight; }

  function hello() {
    return h("div", { class: "hello" },
      h("h1", {}, h("span", { lang: "pa" }, "ਬੋਲੋ"), " ", h("span", { lang: "hi" }, "बोलिए"), " ", h("span", { lang: "en" }, "Speak")),
      h("p", {}, t("greeting_sub")));
  }
  function resetTalk() {
    state.conversationId = null;
    saved.set("parali_conv", "");
    $("log").replaceChildren(hello());
  }
  async function restoreTalk(id) {
    try {
      const conv = await api(`/agent/conversations/${encodeURIComponent(id)}`);
      if (conv.farmer_id !== state.farmerId || !(conv.turns || []).length || state.conversationId) return;
      state.conversationId = id;
      if (!state.picked && API_LANG[conv.language]) setUILang(API_LANG[conv.language]);
      $("log").replaceChildren(hello(), ...conv.turns.map((turn) => turn.role === "user"
        ? h("div", { class: "bubble farmer" }, turn.text,
            turn.english && turn.english !== turn.text && state.lang !== "en" ? h("span", { class: "en", lang: "en" }, turn.english) : null)
        : h("div", { class: "bubble agent" }, turn.text)));
      scrollLog();
    } catch { /* an old conversation that is gone just starts fresh */ }
  }

  function farmerBubble(text, english) {
    $("log").append(h("div", { class: "bubble farmer" }, text,
      english && english !== text && state.lang !== "en" ? h("span", { class: "en", lang: "en" }, english) : null));
    scrollLog();
  }
  function agentBubble(text, lang) {
    const play = h("button", { type: "button", class: "replay", "aria-label": t("replay") }, `▶ ${t("replay")}`);
    play.addEventListener("click", () => {
      if (play.dataset.audio) { const a = $("voice"); a.src = `data:audio/mp3;base64,${play.dataset.audio}`; a.play().catch(() => {}); }
      else speak(text, lang, play);
    });
    $("log").append(h("div", { class: "bubble agent" }, text, play));
    scrollLog();
    return play;
  }
  function thinking(on) {
    document.querySelector(".log .dots")?.remove();
    if (on) { $("log").append(h("div", { class: "dots", "aria-label": t("thinking") }, h("i"), h("i"), h("i"))); scrollLog(); }
    $("talk-mic").classList.toggle("busy", on);
  }

  // What the agent has noted, and what it still needs (asked for in the reply too).
  function draftCard(card) {
    const f = card.fields || {};
    const have = [f.farmer_name, f.acres ? `${f.acres} ${t("f_acres")}` : null, f.village_or_district,
      f.sowing_deadline ? `${t("f_sowing")}: ${formatSlot({ date: f.sowing_deadline, window_start_min: 0, window_end_min: 0 }).split(",").slice(0, 2).join(",")}` : null].filter(Boolean);
    const keys = { quantity: "f_quantity", crop_type: "f_crop", location: "f_place", sowing_deadline: "f_sowing", name: "f_name", phone: "f_phone" };
    const missing = (card.missing_fields || []).map((m) => keys[m]).filter(Boolean);
    if (!have.length && !missing.length) return null;
    return h("div", { class: "tcard" }, h("div", { class: "need" },
      have.map((x) => h("span", {}, x)), missing.map((k) => h("span", { class: "missing" }, `${t(k)}?`))));
  }

  function offerCard(card) {
    const book = h("button", { type: "button", class: "btn" }, labelNodes("book_this"));
    const farm = card.farm || {};
    const box = h("div", { class: "tcard offer" },
      h("span", { class: "lead" }, t("you_get")),
      h("span", { class: "money" }, rupees(card.payout_inr)),
      h("div", { class: "row" }, h("span", { class: "k" }, t("price_today")), h("span", { class: "v" }, perKg(card.price_per_kg))),
      h("div", { class: "row" }, h("span", { class: "k" }, t("straw")), h("span", { class: "v" }, kg(card.kg))),
      h("div", { class: "row" }, h("span", { class: "k" }, t("pickup")), h("span", { class: "v" }, when(card))),
      h("div", { class: "skips" }, ["skip_1", "skip_2", "skip_3", "skip_5"].map((k) => h("span", {}, t(k)))),
      card.partner_crew ? h("p", { class: "fine" }, t("partner_crew")) : null,
      farm.name || farm.village ? h("p", { class: "readback" }, `${t("check_details")}: ${[farm.name, farm.phone, farm.village, farm.location].filter(Boolean).join(", ")}`) : null,
      card.offer_valid_until ? h("p", { class: "fine" }, t("held_until", { t: clock(card.offer_valid_until) })) : null,
      book,
      h("p", { class: "fine" }, t("demo_note")));
    book.addEventListener("click", () => acceptBooking(card.booking_id, book, (result) => {
      box.replaceWith(bookedCard({ pickup_window: result.pickup_window, payout_inr: result.booking.payout_estimate_inr,
                                   pickup_window_spoken: card.pickup_window_spoken, lang: card.lang, booking_code: result.booking.booking_code }));
    }));
    return box;
  }

  // The agent's spoken time ("Sunday 18 October, 7 to 10 am") when it is in the
  // page's language; otherwise the slot formatted here.
  const when = (card) => (card.pickup_window_spoken && card.lang === state.lang ? card.pickup_window_spoken : formatLabel(card.pickup_window));

  function bookedCard(card) {
    return h("div", { class: "tcard booked" },
      h("h3", {}, labelNodes("booked")),
      h("span", {}, t("booked_line", { w: when(card), p: rupees(card.payout_inr) })),
      card.booking_code ? h("div", { class: "row" }, h("span", { class: "k" }, t("booking_id")), h("span", { class: "code" }, card.booking_code)) : null,
      h("p", { class: "call-next" }, t("call_next")),
      h("p", { class: "fine" }, `${t("sms_sent")} · ${t("demo_note")}`));
  }

  function renderCards(cards) {
    const latest = {};
    for (const c of cards || []) latest[c.type] = c;
    const order = latest.booked ? ["booked"] : latest.offer ? ["offer"] : ["draft", "bookings"];
    for (const type of order) {
      const c = latest[type];
      if (!c) continue;
      const node = type === "draft" ? draftCard(c) : type === "offer" ? offerCard(c) : type === "booked" ? bookedCard(c) : null;
      if (node) $("log").append(node);
      if (type === "bookings") openRail();
    }
    scrollLog();
  }

  // One reply from the agent, typed, recorded or live: text and cards at once, speech after.
  function showReply(body, heardBubble) {
    const unsupported = body.guardrails && body.guardrails.unsupported_language;
    const lang = unsupported ? state.lang : API_LANG[body.language] || state.lang;
    if (!state.picked && lang !== state.lang) setUILang(lang);
    (body.cards || []).forEach((c) => { c.lang = lang; });   // spoken phrases on cards are in this language
    state.conversationId = body.conversation_id || state.conversationId;
    if (state.conversationId) saved.set("parali_conv", state.conversationId);
    if (heardBubble === true) farmerBubble(body.heard.text, body.heard.english);
    else if (heardBubble && body.heard.english && body.heard.english !== body.heard.text && lang !== "en") {
      heardBubble.append(h("span", { class: "en", lang: "en" }, body.heard.english));
    }
    const text = typeof body.reply === "string" ? body.reply : body.reply.text;
    const play = agentBubble(text, lang);
    renderCards(body.cards);
    if (body.reply && body.reply.audio_base64) {
      play.dataset.audio = body.reply.audio_base64;
      const a = $("voice"); a.src = `data:audio/mp3;base64,${body.reply.audio_base64}`; a.play().catch(() => {});
    } else {
      speak((body.reply && body.reply.speak_text) || text, lang, play);
    }
    if ((body.cards || []).some((c) => c.type === "offer" || c.type === "booked")) loadPickups();
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
    form.append("speak", "false");
    if (state.picked) form.append("language", LANG_API[state.picked]);
    if (state.conversationId) form.append("conversation_id", state.conversationId);
    if (text) form.append("text", text);
    if (audio) form.append("audio", audio, "speech.wav");
    if (state.talkPhoto) form.append("photo", state.talkPhoto);
    try {
      const body = await api("/agent/turn", { method: "POST", body: form });
      thinking(false);
      state.talkPhoto = null;
      document.querySelector("label[for=talk-photo]").classList.remove("done");
      showReply(body, audio ? true : null);
    } catch (err) {
      thinking(false);
      toast(err.message);
    } finally {
      state.busy = false;
      if (state.queued) { const next = state.queued; state.queued = null; sendTurn({ text: next }); }
    }
  }

  // ---- live words: stream 16 kHz PCM over a WebSocket; the words appear while
  // the farmer speaks, in whichever language; the final words are one guarded turn.
  const WORKLET = `class Tap extends AudioWorkletProcessor {
    process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
  }
  registerProcessor("tap", Tap);`;
  const live = { ws: null, ctx: null, stream: null, bubble: null };
  const liveUrl = () => `${API_BASE.replace(/^http/, "ws")}/agent/live`;

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
        live.ws.send(JSON.stringify({ farmer_id: state.farmerId, conversation_id: state.conversationId,
                                      language: state.picked ? LANG_API[state.picked] : null }));
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
      showReply(event, live.bubble);
    } else if (event.type === "error") {
      thinking(false);
      if (live.bubble && live.bubble.textContent === "…") live.bubble.remove();
      toast(event.detail);
    }
  }

  // ---- pickups, prices, proof
  async function acceptBooking(bookingId, button, onDone) {
    button.disabled = true;
    try {
      const body = await postJson(`/bookings/${encodeURIComponent(bookingId)}/accept`, { farmer_id: state.farmerId });
      toast(t("booked"));
      onDone(body);
      loadPickups();
    } catch (err) {
      toast(err.message);
      button.disabled = false;
    }
  }

  async function loadPrices() {
    try {
      const { prices } = await api("/prices/today");
      $("prices").replaceChildren(...prices.map((p) =>
        h("div", { class: `price-row ${p.reason_code}`, title: p.reason }, h("span", {}, district(p.district)), h("span", { class: "v" }, perKg(p.price_per_kg)))));
    } catch {
      $("prices").replaceChildren(h("p", { class: "empty" }, t("error_generic")));
    }
  }

  const STEP_ORDER = ["booked", "verified", "collected", "paid"];
  const REASONS = ["booked", "no_capacity", "deadline_passed", "too_far", "beyond_horizon", "expired"];
  function statusKey(b) {
    if (b.status === "booked" && b.verification && b.verification.status === "needs_change") return "needs_change";
    return b.status;
  }
  const PILL = { offered: "silk", unschedulable: "warn", booked: "brand", needs_change: "warn", verified: "ok", collected: "ok", paid: "ok", expired: "" };

  async function loadPickups() {
    let bookings = [];
    try { ({ bookings } = await api(`/farmers/${encodeURIComponent(state.farmerId)}/bookings`)); } catch { /* shown as empty */ }
    const active = bookings.filter((b) => ["offered", "booked", "verified"].includes(b.status));
    $("pickup-count").hidden = !active.length;
    $("pickup-count").textContent = active.length;
    state.latestDistrict = (bookings.find((b) => ["offered", "booked", "verified", "collected", "paid"].includes(b.status)) || {}).district || null;
    $("pickups").replaceChildren(...(bookings.length ? bookings.map(pickupRow) : [h("p", { class: "empty" }, t("no_pickups"))]));
  }

  function pickupRow(b) {
    const key = statusKey(b);
    const reached = STEP_ORDER.indexOf(b.status);
    const actions = h("div", { class: "row-actions" });
    if (b.status === "offered" && b.slots && b.slots.length) {
      const book = h("button", { type: "button", class: "btn small" }, t("book_this"));
      book.addEventListener("click", () => acceptBooking(b.id, book, () => {}));
      actions.append(book);
    }
    if (["offered", "booked", "verified"].includes(b.status)) {
      const cancel = h("button", { type: "button", class: "btn quiet small" }, t("cancel"));
      cancel.addEventListener("click", () => askCancel(b.id, actions));
      actions.append(cancel);
    }
    return h("div", { class: "pickup" },
      h("div", { class: "top" }, h("strong", {}, `${district(b.district)} · ${kg(b.kg)}`), h("span", { class: `pill ${PILL[key] || ""}` }, t(`s_${key}`))),
      b.slots && b.slots.length ? h("span", {}, formatSlot(b.slots[0])) : null,
      h("span", { class: "hint" }, `${perKg(b.price_per_kg)}${b.booking_code ? ` · ${t("booking_id")} ${b.booking_code}` : ""}`),
      b.status === "paid" && b.payout_inr ? h("span", { class: "result" }, t("paid_line", { p: rupees(b.payout_inr) })) : null,
      b.status === "unschedulable" ? h("span", { class: "hint" }, REASONS.includes(b.status_reason_code) ? t(`r_${b.status_reason_code}`) : "") : null,
      reached >= 0 ? h("div", { class: "steps", "aria-label": t(`s_${key}`) }, STEP_ORDER.map((step, i) =>
        h("span", { class: i <= reached ? "on" : "" }, h("i", {}), h("small", {}, t(`s_${step}_short`))))) : null,
      actions.childNodes.length ? actions : null);
  }

  // An in-page "are you sure?", in the farmer's language.
  function askCancel(bookingId, actions) {
    const yes = h("button", { type: "button", class: "btn small" }, t("cancel_yes"));
    const no = h("button", { type: "button", class: "btn quiet small" }, t("keep"));
    const before = [...actions.childNodes];
    actions.replaceChildren(h("span", {}, t("cancel_sure")), yes, no);
    no.addEventListener("click", () => actions.replaceChildren(...before));
    yes.addEventListener("click", async () => {
      yes.disabled = true;
      try {
        await postJson(`/bookings/${encodeURIComponent(bookingId)}/cancel`, { farmer_id: state.farmerId });
        toast(t("cancelled"));
        actions.closest(".pickup")?.remove();
        await loadPickups();
      } catch (err) {
        toast(err.message);
        yes.disabled = false;
      }
    });
  }

  async function sendProof(file) {
    if (!state.latestDistrict) { toast(t("proof_needs_booking")); return; }
    const form = new FormData();
    form.append("photo", file);
    const out = $("proof-result");
    out.textContent = "…";
    try {
      const body = await api(`/farmers/${encodeURIComponent(state.farmerId)}/no-burn-proof?district=${encodeURIComponent(state.latestDistrict)}`, { method: "POST", body: form });
      out.textContent = body.disputed ? t("proof_disputed") : t("proof_ok", { sat: t(`sat_${body.satellite_corroboration}`) });
    } catch (err) { out.textContent = err.message; }
  }

  function openRail() { loadPickups(); $("rail").classList.add("open"); }

  // ---- wiring
  function init() {
    let id = saved.get("parali_farmer_id");
    if (!id) { id = `farmer_${Math.random().toString(36).slice(2, 10)}`; saved.set("parali_farmer_id", id); }
    state.farmerId = id;

    const keep = saved.get("parali_conv");      // read before resetTalk forgets it
    setUILang(startLang());
    resetTalk();
    if (keep) { saved.set("parali_conv", keep); restoreTalk(keep); }

    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => {
      state.picked = b.dataset.lang;
      saved.set("parali_lang_pick", b.dataset.lang);
      setUILang(b.dataset.lang);
    }));

    makeRecorder($("talk-mic"), $("talk-label"), (wav) => sendTurn({ audio: wav }), () => $("live-toggle").checked);
    $("talk-mic").addEventListener("click", () => {
      if (!$("live-toggle").checked) return;
      if (live.ws && live.ws.readyState <= 1 && live.stream) stopLive(false); else startLive();
    });
    $("live-toggle").checked = saved.get("parali_live") === "1";
    $("live-toggle").addEventListener("change", () => saved.set("parali_live", $("live-toggle").checked ? "1" : "0"));
    $("talk-locate").addEventListener("click", async () => {
      // Prototype: a demo farm in Punjab, never the device location (a visitor
      // outside Punjab would be out of every depot's reach).
      try {
        const body = await postJson("/demo/locate", { farmer_id: state.farmerId, conversation_id: state.conversationId });
        $("talk-locate").classList.add("done");
        agentBubble(t("located", { d: district(body.district) }), state.lang);
      } catch (err) { toast(err.message); }
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
        $("log").append(h("div", { class: "bubble farmer" }, h("img", { class: "thumb", alt: "", src: URL.createObjectURL(state.talkPhoto) }),
          h("span", { class: "en" }, t("photo_sent_with_next"))));
        scrollLog();
      }
      document.querySelector("label[for=talk-photo]").classList.toggle("done", !!state.talkPhoto);
    });
    $("proof-photo").addEventListener("change", () => {
      const file = $("proof-photo").files[0];
      $("proof-photo").value = "";
      if (file) sendProof(file);
    });
    $("open-pickups").addEventListener("click", openRail);
    $("close-rail").addEventListener("click", () => $("rail").classList.remove("open"));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("rail").classList.remove("open"); });
  }

  init();
})();
