const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async (path, opts = {}) => {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  return r.json();
};
const toast = (msg, cls = "ok") => {
  const t = $("toast");
  t.textContent = msg; t.className = cls; t.hidden = false;
  setTimeout(() => (t.hidden = true), 2600);
};

let SESSION = null, SEGS = [], CARD = null, PAD = { b: 0, a: 0 };
let STATUS = {};              // lemma -> learning|known|ignored|tracking (ausente = desconocida)
let CUR = -1;
let DUAL = false, AUTOPAUSE = false, HIDE_CA = false, HIDE_ES = false;
let OFFSET = 0;               // desfase subtítulo↔media (s); + = subs más tarde
let CONDENSED = false;        // saltar huecos sin diálogo al reproducir
let POP = null, HOVER = null;
let PINNED = false, RESUME = false, HOVER_TIMER = null, CLOSE_TIMER = null;
const ES_CACHE = {};
const LOOKUP_CACHE = {};
let SETTINGS = null, KEY2ACTION = {}, CAPTURING = null, RECS = [];
const DEFAULT_KEYMAP = { prev: "a", next: "d", replay: "s", mine: "q",
  subs: "w", browser: "g", copy: "c", dual: "e", autopause: "p",
  fullscreen: "f", recommended: "r" };
const SPEEDS = [1, 1.25, 1.5, 0.75];
let SPEED_IX = 0;

// ---------- badge de Anki ----------
async function refreshAnki() {
  const s = await api("/api/anki/status");
  const b = $("anki-badge");
  const q = s.pending > 0 ? `${s.pending} en cola · ` : "";
  if (s.up) { b.textContent = s.pending > 0 ? `Anki: enviando ${s.pending}…` : `Anki ✓ (:${s.port})`; b.className = "badge up"; }
  else if (s.reason === "squatted") { b.textContent = `${q}puerto ocupado — clic`; b.className = "badge err"; }
  else { b.textContent = q + "Anki cerrado"; b.className = s.pending > 0 ? "badge pending" : "badge"; }
  b.dataset.reason = s.reason || "";
}
$("anki-badge").onclick = () => {
  const reason = $("anki-badge").dataset.reason;
  $("port-msg").textContent = reason === "squatted"
    ? "Otro servicio ocupa los puertos 8765/8766. En Anki → Herramientas → Complementos → AnkiConnect → Configuración pon \"webBindPort\": 8767 y reinicia Anki (o escribe 8767 aquí)."
    : "Déjalo vacío para detectarlo automáticamente.";
  $("port-input").value = "";
  $("port-dlg").showModal();
};
$("port-dlg").addEventListener("close", async () => {
  if ($("port-dlg").returnValue !== "ok") return;
  const v = $("port-input").value.trim();
  const port = v === "" ? null : parseInt(v, 10);
  const r = await api("/api/anki/port", { method: "POST", body: JSON.stringify({ port }) });
  toast(r.port ? `AnkiConnect encontrado en el puerto ${r.port}` : "Aún no encuentro AnkiConnect", r.port ? "ok" : "err");
  refreshAnki();
});
setInterval(async () => {
  await api("/api/anki/flush", { method: "POST" }).catch(() => {});
  refreshAnki();
}, 15000);

// estilo Migaku: los estados siguen tu progreso real en Anki (intervalo >= 21d -> conocida)
async function syncStatuses() {
  const r = await api("/api/anki/sync-statuses", { method: "POST" }).catch(() => null);
  if (r && r.synced > 0 && SESSION) {
    const s = await api("/api/sessions/" + SESSION.id);
    STATUS = s.word_statuses || {};
    renderSegs(); renderOverlay(); updateComp();
    toast(`${r.synced} palabras actualizadas desde Anki`);
  }
}
// cada 10 min y al volver a la ventana: pedir cardsInfo de TODAS las tarjetas
// cada minuto era un martilleo innecesario a Anki (y peor con invitados).
setInterval(syncStatuses, 600000);
window.addEventListener("focus", () => syncStatuses());

// ---------- biblioteca ----------
const SRC_LABEL = () => ({ whisper: "Whisper", srt: "SRT", youtube_subs: t("src.yt"), youtube_auto: t("src.yt_auto"), none: t("src.none"), "-": "—" });

// badge de origen (arriba a la izquierda de la miniatura)
function sourceBadge(s) {
  const p = (s.page_url || "").toLowerCase();
  if (s.source_type === "stream" && p.includes("youtube")) return { t: "▶ YouTube", c: "yt" };
  if (s.source_type === "stream" && (p.includes("3cat") || p.includes("ccma"))) return { t: "3cat", c: "tv" };
  if (s.source_type === "stream") return { t: "Streaming", c: "st" };
  if (s.source_type === "youtube") return { t: "▶ YouTube", c: "yt" };
  if (s.source_type === "url") return { t: "Enlace", c: "st" };
  return { t: "Local", c: "loc" };
}

function fmtTime(t) {
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  const h = Math.floor(m / 60);
  return h ? `${h}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

async function loadSessions() {
  const list = await api("/api/sessions");
  $("session-list").innerHTML = list.map((s) => `
    <article class="scard" data-id="${s.id}">
      <div class="thumb" style="${s.thumb ? `background-image:url('${s.thumb}')` : ""}">
        ${s.thumb ? "" : `<svg class="ic thumb-ph"><use href="#i-folder"/></svg>`}
        <span class="src-badge src-${sourceBadge(s).c}">${sourceBadge(s).t}</span>
        <button class="scard-del" title="${esc(t("lib.delete"))}" aria-label="${esc(t("lib.delete"))}"><svg class="ic"><use href="#i-trash"/></svg></button>
        ${s.duration_secs ? `<span class="dur">${fmtTime(s.duration_secs)}</span>` : ""}
        ${s.resume_pos && s.duration_secs ? `<span class="resume-bar" style="width:${Math.min(100, s.resume_pos / s.duration_secs * 100).toFixed(1)}%"></span>` : ""}
      </div>
      <div class="scard-body">
        <div class="scard-title" title="${esc(s.title)}">${esc(s.title)}</div>
        <div class="pills">
          ${s.comp_pct !== null && s.comp_pct !== undefined ? `<span class="pill comp"><svg class="ic ic-xs"><use href="#i-chart"/></svg>${t("pill.known", s.comp_pct)}</span>` : ""}
          ${s.new_words ? `<span class="pill new">${t("pill.new", s.new_words)}</span>` : ""}
          <span class="pill">${SRC_LABEL()[s.srt_source] ?? s.srt_source}</span>
        </div>
      </div>
    </article>`).join("");
  for (const card of $("session-list").children) {
    card.onclick = () => openSession(card.dataset.id);
    const del = card.querySelector(".scard-del");
    del.onclick = (e) => {
      e.stopPropagation();                 // no abrir la sesión al borrar
      deleteSession(card.dataset.id, card.querySelector(".scard-title").textContent);
    };
  }
  $("library-empty").hidden = list.length > 0;
  $("lib-search-sec").hidden = list.length === 0;
  refreshOnboarding();
}

async function deleteSession(sid, title) {
  if (!confirm(t("lib.delete_confirm", title))) return;
  const r = await api("/api/sessions/" + sid, { method: "DELETE" }).catch(() => null);
  if (r && r.ok) { toast(t("lib.deleted")); loadSessions(); }
  else toast(t("lib.delete_err"), "err");
}

// ---------- búsqueda en subtítulos ----------
let SEARCH_TIMER = null;
$("lib-search").oninput = () => {
  clearTimeout(SEARCH_TIMER);
  SEARCH_TIMER = setTimeout(runSearch, 250);
};
$("lib-search").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("lib-search").value = ""; runSearch(); }
});

async function runSearch() {
  const q = $("lib-search").value.trim();
  const box = $("search-results");
  if (q.length < 2) {
    box.hidden = true; box.innerHTML = "";
    $("session-list").hidden = false;
    return;
  }
  const r = await api("/api/search?q=" + encodeURIComponent(q)).catch(() => null);
  const results = (r && r.results) || [];
  $("session-list").hidden = true;
  box.hidden = false;
  if (!results.length) {
    box.innerHTML = `<p class="dim search-none">Sin resultados para «${esc(q)}»</p>`;
    return;
  }
  const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
  const total = results.reduce((n, g) => n + g.hits.length, 0);
  box.innerHTML =
    `<p class="dim search-count">${total} líneas en ${results.length} videos</p>` +
    results.map((g) => `
      <div class="search-group">
        <div class="search-gt">${sourceBadge(g).t} · ${esc(g.title)}</div>
        ${g.hits.map((h) => `
          <button class="search-hit" data-sid="${g.session_id}" data-seg="${h.index}">
            <span class="search-ts">${fmtTime(h.start)}</span>
            <span class="search-tx">${esc(h.text).replace(re, "<mark>$1</mark>")}</span>
          </button>`).join("")}
      </div>`).join("");
  for (const b of box.querySelectorAll(".search-hit"))
    b.onclick = () => openSession(b.dataset.sid, { seg: +b.dataset.seg });
}

// ---------- asistente de primer arranque ----------
const ONB_LABEL = {
  ffmpeg: ["ffmpeg (recorte de audio/imagen)", "Instala con: brew install ffmpeg"],
  translator: ["Traductor catalán→español", "Se descarga (~1.5 GB) — pulsa el botón"],
  dictionary: ["Diccionario de acepciones", "Se descarga con el traductor"],
  forms: ["Diccionario de formas (lemas)", "Se descarga con el traductor"],
  spacy: ["Modelo lingüístico spaCy", "Ejecuta install.sh de nuevo si falta"],
  anki: ["Anki + AnkiConnect (para las tarjetas)", "Abre Anki con el complemento 2055492159; sin él, las tarjetas quedan en cola"],
  espeak: ["espeak-ng (pronunciación IPA, opcional)", "Opcional: brew install espeak-ng"],
  tts: ["Voz neural Piper (pronunciación, opcional)", "Se descarga (~20 MB) con el botón"],
};
const ONB_ORDER = ["ffmpeg", "translator", "dictionary", "forms", "spacy", "anki", "tts", "espeak"];
const ONB_OPTIONAL = new Set(["espeak", "tts"]);
let ONB_DISMISSED = false;

async function refreshOnboarding() {
  const s = await api("/api/setup-status").catch(() => null);
  if (!s) return;
  const allReady = ONB_ORDER.every((k) => s.checks[k] || ONB_OPTIONAL.has(k));
  // mostrar mientras no esté todo listo, o si la biblioteca está vacía
  const show = !ONB_DISMISSED && (!allReady || !s.has_sessions);
  $("onboarding").hidden = !show;
  if (!show) return;
  $("onb-checks").innerHTML = ONB_ORDER.map((k) => {
    const ok = s.checks[k];
    const [label, hint] = ONB_LABEL[k];
    const dot = ok ? "ok" : (ONB_OPTIONAL.has(k) ? "opt" : "warn");
    return `<li class="${ok ? "ok" : ""}"><span><span class="onb-dot ${dot}"></span>${label}</span>${ok ? "" : `<small>${hint}</small>`}</li>`;
  }).join("");
  // botón de descarga si falta el traductor o los diccionarios
  const needsDl = !s.checks.translator || !s.checks.dictionary || !s.checks.forms;
  $("onb-download").hidden = !needsDl;
}

$("onb-download").onclick = async () => {
  const r = await api("/api/setup/download", { method: "POST" });
  const res = await pollJob(r.job_id, "Descargando…");
  if (res) { toast("Todo descargado", "ok"); refreshOnboarding(); }
};
$("onb-recheck").onclick = () => { refreshAnki(); refreshOnboarding(); };
$("onb-dismiss").onclick = () => { ONB_DISMISSED = true; $("onboarding").hidden = true; };

$("file-input").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await uploadWithProgress("/api/sessions/upload", fd).catch(() => null);
  e.target.value = "";
  if (!r || r.error) { showProgress(1, r?.error || "Error subiendo el archivo", true); return; }
  const res = await pollJob(r.job_id, "Procesando el video…");
  if (res) openSession(res.session_id);
};

$("yt-btn").onclick = async () => {
  const url = $("yt-url").value.trim();
  if (!url) return;
  const { job_id } = await api("/api/sessions/youtube", { method: "POST", body: JSON.stringify({ url }) });
  const res = await pollJob(job_id, "Descargando de YouTube…");
  if (res) openSession(res.session_id);
};

$("url-btn").onclick = async () => {
  const url = $("yt-url").value.trim();
  if (!url) return;
  const r = await api("/api/sessions/stream", { method: "POST", body: JSON.stringify({ url }) });
  if (r.error) { showProgress(1, r.error, true); return; }
  const res = await pollJob(r.job_id, "Resolviendo el enlace…");
  if (res) openSession(res.session_id);
};

// ---------- jobs (progreso global, visible también en la home) ----------
function showProgress(v, msg, isError = false) {
  const pill = $("progress-pill");
  pill.hidden = false;
  pill.classList.toggle("err", isError);
  $("gp-bar").hidden = isError;
  $("gp-bar").value = v || 0;
  $("gp-msg").textContent = msg || "";
  $("gp-close").hidden = !isError;   // solo se puede cerrar en estado de error
}
function hideProgress() {
  $("progress-pill").hidden = true;
  $("progress-pill").classList.remove("err");
}
$("gp-close").onclick = hideProgress;

async function pollJob(jid, label) {
  showProgress(0, label);
  while (true) {
    const j = await api("/api/jobs/" + jid).catch(() => null);
    if (!j || j.error) {                 // server reiniciado: el job ya no existe
      showProgress(1, "trabajo perdido (¿se reinició la app?)", true);
      return null;
    }
    showProgress(j.progress || 0, j.message || label);
    if (j.status === "done") { hideProgress(); return j.result; }
    if (j.status === "error") {
      // error persistente en la píldora (no un toast que se esfuma)
      showProgress(1, j.message || "algo falló", true);
      return null;
    }
    await new Promise((r) => setTimeout(r, 800));
  }
}

// subida con porcentaje real (fetch no expone progreso de subida)
function uploadWithProgress(url, fd) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.upload.onprogress = (e) => {
      if (e.lengthComputable)
        showProgress(e.loaded / e.total,
          `Subiendo… ${Math.round((100 * e.loaded) / e.total)}%`);
    };
    x.onload = () => { try { resolve(JSON.parse(x.responseText)); } catch (err) { reject(err); } };
    x.onerror = () => reject(new Error("fallo de red"));
    x.send(fd);
  });
}

// ---------- sesión ----------
let PENDING_SEEK = 0;                    // reanudar / saltar desde búsqueda
async function openSession(sid, opts = {}) {
  const s = await api("/api/sessions/" + sid);
  SESSION = s; SEGS = s.transcript; STATUS = s.word_statuses || {};
  CUR = -1; POP = null; HOVER = null; PINNED = false; $("word-pop").hidden = true;
  setOffset(0);                         // el desfase es por sesión
  // a dónde saltar al cargar: línea buscada > reanudar donde se dejó > inicio
  PENDING_SEEK = 0;
  if (opts.seg != null && SEGS[opts.seg]) PENDING_SEEK = SEGS[opts.seg].start;
  else {
    const rp = s.resume_pos || 0;
    if (rp > 5 && rp < (s.duration_secs || 0) - 15) PENDING_SEEK = rp;
  }
  for (const k in ES_CACHE) delete ES_CACHE[k];
  for (const k in LOOKUP_CACHE) delete LOOKUP_CACHE[k];
  // solo sirve el cache de traducción del idioma base activo (es histórico si
  // no está marcado); otra base lo re-traduce bajo demanda
  const base = SETTINGS?.base_language_effective || "es";
  SEGS.forEach((seg, i) => {
    if (seg.text_es && (seg.es_b || "es") === base) ES_CACHE[i] = seg.text_es;
  });
  $("home").hidden = true; $("player").hidden = false;
  STALLS = [];
  if (s.source_type === "stream") {
    await loadStreamUrl(sid, 0);        // URL fresca (las de yt-dlp caducan)
  } else {
    $("quality-btn").hidden = true;
    await setVideoSrc(s.media_url, s.is_hls);   // enlace directo (mp4 o HLS)
  }
  // preferencias por defecto de la configuración
  setDual(SETTINGS?.dual_default ?? DUAL);
  setAutopause(SETTINGS?.autopause_default ?? AUTOPAUSE);
  const sp = SETTINGS?.speed_default ?? 1;
  $("video").playbackRate = sp;
  SPEED_IX = Math.max(0, SPEEDS.indexOf(sp));
  $("speed-btn").textContent = sp + "×";
  renderSegs();
  renderOverlay();
  renderSeekMarks();
  updateComp();
  syncStatuses();
}

// marcadores de subtítulo en la barra (estilo Language Reactor)
function renderSeekMarks() {
  const el = $("seek-marks");
  const dur = SESSION?.duration_secs || 0;
  if (!SEGS.length || dur <= 0) { el.innerHTML = ""; return; }
  // muestrear hasta ~400 marcas para no saturar el DOM en videos largos
  const step = Math.ceil(SEGS.length / 400);
  let html = "";
  for (let i = 0; i < SEGS.length; i += step) {
    const left = Math.min(100, (SEGS[i].start / dur) * 100);
    html += `<i style="left:${left.toFixed(3)}%"></i>`;
  }
  el.innerHTML = html;
}
// ---------- streaming (URL fresca + calidad + auto-bajada) ----------
let STREAM_HEIGHTS = [], STREAM_H = 0, STALLS = [];

// Reproducir HLS (.m3u8) en cualquier plataforma: Safari/WKWebView lo hace
// nativo; Chrome/Firefox/Android necesitan hls.js (se carga solo si hace falta,
// vendido en /vendor para funcionar offline y bajo la CSP de la PWA).
let HLS = null, _hlsLib = null;
function ensureHls() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (!_hlsLib) _hlsLib = new Promise((res, rej) => {
    const sc = document.createElement("script");
    sc.src = "/vendor/hls.min.js";
    sc.onload = () => res(window.Hls); sc.onerror = rej;
    document.head.appendChild(sc);
  });
  return _hlsLib;
}
async function setVideoSrc(url, isHls) {
  if (HLS) { HLS.destroy(); HLS = null; }
  const wantHls = isHls || /\.m3u8(\?|$)/i.test(url || "");
  if (wantHls && !V.canPlayType("application/vnd.apple.mpegurl")) {
    const Hls = await ensureHls().catch(() => null);
    if (Hls && Hls.isSupported()) {
      HLS = new Hls({ enableWorker: true, backBufferLength: 30 });
      HLS.on(Hls.Events.ERROR, (_e, d) => {
        if (d.fatal) showProgress(1, "error de reproducción HLS", true);
      });
      HLS.loadSource(url); HLS.attachMedia(V);
      return;
    }
  }
  V.src = url;                            // nativo (Safari/WKWebView) o fallback
}

async function loadStreamUrl(sid, height) {
  showProgress(0.5, "Cargando el video…");
  const r = await api(`/api/sessions/${sid}/stream-url?height=${height || 0}`);
  hideProgress();
  if (r.error) { showProgress(1, r.error, true); return; }
  const t = V.currentTime || 0, playing = !V.paused;
  STREAM_HEIGHTS = r.is_hls ? [] : (r.heights || []);   // HLS: ABR automático
  STREAM_H = r.height || 0;
  await setVideoSrc(r.url, r.is_hls);
  if (height) {   // cambio de calidad: preservar el punto
    V.addEventListener("loadedmetadata", () => {
      V.currentTime = t; if (playing) V.play();
    }, { once: true });
  }
  renderQualityMenu();
}

function renderQualityMenu() {
  const btn = $("quality-btn");
  if (STREAM_HEIGHTS.length < 2) { btn.hidden = true; return; }
  btn.hidden = false;
  btn.textContent = STREAM_H ? STREAM_H + "p" : "Auto";
  $("quality-menu").innerHTML = STREAM_HEIGHTS
    .slice().sort((a, b) => b.height - a.height)
    .map((h) => `<button data-h="${h.height}" class="${h.height === STREAM_H ? "on" : ""}">${esc(h.label)}</button>`).join("");
  for (const b of $("quality-menu").querySelectorAll("button"))
    b.onclick = () => { $("quality-menu").hidden = true; loadStreamUrl(SESSION.id, +b.dataset.h); };
}
$("quality-btn").onclick = () => { $("quality-menu").hidden = !$("quality-menu").hidden; };

// auto-bajada: si se atasca repetidamente, baja un escalón de calidad
$("video").addEventListener("waiting", () => {
  if (SESSION?.source_type !== "stream" || STREAM_HEIGHTS.length < 2) return;
  const now = Date.now();
  STALLS = STALLS.filter((t) => now - t < 12000);
  STALLS.push(now);
  if (STALLS.length >= 3) {
    STALLS = [];
    const lower = STREAM_HEIGHTS.filter((h) => h.height < STREAM_H)
      .sort((a, b) => b.height - a.height)[0];
    if (lower) { toast(`Bajando a ${lower.label} por conexión lenta`); loadStreamUrl(SESSION.id, lower.height); }
  }
});

$("back").onclick = () => {
  saveResume(true);                     // recordar dónde lo dejamos
  if (document.fullscreenElement) document.exitFullscreen();
  $("quality-menu").hidden = true;
  $("video-col").classList.remove("fake-fs");
  $("player").hidden = true; $("home").hidden = false;
  $("card-panel").hidden = true; $("word-pop").hidden = true;
  $("comp-chip").hidden = true; $("rec-chip").hidden = true;
  $("lib-search").value = ""; $("search-results").hidden = true;
  $("session-list").hidden = false;     // volver a la biblioteca limpia
  loadSessions();
};

$("transcribe-btn").onclick = async () => {
  const model = $("model-select").value;
  const { job_id } = await api(`/api/sessions/${SESSION.id}/transcribe`,
    { method: "POST", body: JSON.stringify({ model }) });
  const res = await pollJob(job_id, "Transcribiendo… (la primera vez descarga el modelo)");
  if (res) openSession(SESSION.id);
};

$("subs-input").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch(`/api/sessions/${SESSION.id}/subtitles`, { method: "POST", body: fd }).then((x) => x.json());
  if (r.error) { toast(r.error, "err"); return; }
  toast(`${r.segments} subtítulos cargados`, "ok");
  openSession(SESSION.id);
};

// ---------- estados de palabra ----------
function stOf(lemma) { return STATUS[lemma] || "unknown"; }

const ST_LABEL = { unknown: "nueva", learning: "aprendiendo", known: "conocida", ignored: "ignorada", tracking: "seguimiento" };

async function setStatus(lemma, status) {
  if (!lemma) return;
  const r = await api("/api/words/status", {
    method: "POST", body: JSON.stringify({ lemma, status }),
  });
  if (r.error) { toast(r.error, "err"); return; }
  if (status === "unknown") delete STATUS[r.lemma];
  else STATUS[r.lemma] = status;
  renderSegs(); renderOverlay(); updateComp();
  if (POP && POP.lemma === r.lemma) markStatusButtons(status);
  toast(`"${r.lemma}" → ${ST_LABEL[status]}`);
}

// score de comprensión estilo Migaku: % de palabras del contenido que ya conoces
function updateComp() {
  const chip = $("comp-chip");
  if (!SEGS.length) { chip.hidden = true; return; }
  let total = 0, known = 0;
  const newLemmas = new Set();
  for (const seg of SEGS)
    for (const t of (seg.tokens || []))
      if (t.is_word && t.lemma) {
        const st = stOf(t.lemma);
        if (st === "ignored") continue;
        total++;
        if (st === "known") known++;
        else if (st === "unknown") newLemmas.add(t.lemma);
      }
  if (!total) { chip.hidden = true; return; }
  const pct = Math.round((known / total) * 100);
  chip.innerHTML = `<svg class="ic ic-xs"><use href="#i-chart"/></svg>` + esc(t("chip.comp", pct, newLemmas.size));
  chip.hidden = false;
  chip.className = "badge " + (pct >= 90 ? "up" : pct >= 60 ? "pending" : "");
  updateRecs();
  if (!$("side-panel").hidden && PANEL_TAB === "words") renderWords();
}

// ---------- toggles ----------
$("dual-btn").onclick = () => setDual(!DUAL);
$("autopause-btn").onclick = () => setAutopause(!AUTOPAUSE);
$("condensed-btn").onclick = () => setCondensed(!CONDENSED);
$("offset-minus").onclick = () => bumpOffset(-0.1);
$("offset-plus").onclick = () => bumpOffset(0.1);
$("browser-btn").onclick = () => toggleBrowser();
$("fs-btn").onclick = () => toggleFullscreen();
$("speed-btn").onclick = () => {
  SPEED_IX = (SPEED_IX + 1) % SPEEDS.length;
  $("video").playbackRate = SPEEDS[SPEED_IX];
  $("speed-btn").textContent = SPEEDS[SPEED_IX] + "×";
};

function setDual(v) {
  DUAL = v;
  $("dual-btn").classList.toggle("on", v);
  $("overlay-es").hidden = !v || HIDE_ES;
  if (v) fillDual(CUR);
}
function setAutopause(v) {
  AUTOPAUSE = v;
  $("autopause-btn").classList.toggle("on", v);
}
function setCondensed(v) {
  CONDENSED = v;
  $("condensed-btn").classList.toggle("on", v);
  if (v) toast("Condensado: se saltan los silencios entre frases");
}
function setOffset(v) {
  OFFSET = Math.round(v * 10) / 10;      // pasos de 0.1 s
  $("offset-val").textContent = (OFFSET > 0 ? "+" : "") + OFFSET.toFixed(1) + "s";
  $("offset-ctl").classList.toggle("on", OFFSET !== 0);
}
function bumpOffset(d) { setOffset(OFFSET + d); }
function toggleBrowser() {
  const p = $("side-panel");
  p.hidden = !p.hidden;
  $("browser-btn").classList.toggle("on", !p.hidden);
  if (!p.hidden) scrollBrowserTo(CUR);
}
function toggleFullscreen() {
  const col = $("video-col");
  if (document.fullscreenElement) { document.exitFullscreen(); return; }
  if (col.classList.contains("fake-fs")) { col.classList.remove("fake-fs"); $("fs-btn").classList.remove("alt"); return; }
  const p = col.requestFullscreen ? col.requestFullscreen() : Promise.reject();
  Promise.resolve(p).catch(() => {
    col.classList.add("fake-fs");
    $("fs-btn").classList.add("alt");
  });
}
document.addEventListener("fullscreenchange", () => {
  $("fs-btn").classList.toggle("alt", !!document.fullscreenElement);
});

// ---------- render ----------
// etiqueta amigable de un lema para mostrar: contracciones Apertium
// («de+el» → «del») y homógrafos numerados del diccionario («nit1» → «nit»)
const CONTR_LABEL = { "de+el": "del", "de+els": "dels", "a+el": "al",
                      "a+els": "als", "per+el": "pel", "per+els": "pels" };
function lemmaLabel(l) {
  return CONTR_LABEL[l] || String(l || "").replace(/(\D)\d+$/, "$1");
}

// transcripciones antiguas sin «ws»: reconstruirlo localizando cada token en
// el texto original (así «dels» no se muestra partido en «d els»)
function reconstructWs(seg) {
  if (seg._ws !== undefined) return seg._ws;
  const txt = seg.text || "";
  let cur = 0;
  for (const t of seg.tokens) {
    const idx = txt.indexOf(t.t, cur);
    if (idx < 0) return (seg._ws = false);        // no mapea → join legado
    cur = idx + t.t.length;
    t.ws = /\s/.test(txt[cur] || "") ? " " : "";
  }
  return (seg._ws = true);
}

function tokenHtml(seg) {
  if (!(seg.tokens && seg.tokens.length)) return esc(seg.text);
  const hasWs = seg.tokens[0].ws !== undefined || reconstructWs(seg);
  let prevJoined = false;                    // el token anterior va pegado a este
  return seg.tokens.map((t, k) => {
    // nsr/nsl: sin padding en la juntura, para que «d»+«els» se lea «dels»
    const joined = hasWs && t.ws === "" && k < seg.tokens.length - 1;
    const cls = (joined ? " nsr" : "") + (prevJoined ? " nsl" : "");
    const html = t.is_word
      ? `<span class="t st-${stOf(t.lemma)}${cls}" data-l="${esc(t.lemma)}">${esc(t.t)}</span>`
      : `<span>${esc(t.t)}</span>`;
    prevJoined = joined;
    // «ws» = espaciado original; sin él, espacio antes de cada palabra (legado)
    if (hasWs) return html + (t.ws ? " " : "");
    return (k > 0 && t.is_word ? " " : "") + html;
  }).join("");
}

function bindTokenEvents(container, segIndex) {
  for (const tok of container.querySelectorAll(".t")) {
    tok.onclick = (ev) => {
      ev.stopPropagation();
      const sel = window.getSelection().toString().trim();
      openPopup(segIndex, sel || tok.textContent, tok, true);
    };
    tok.onmouseenter = () => {
      HOVER = { segIndex, text: tok.textContent, lemma: tok.dataset.l, el: tok };
      clearTimeout(CLOSE_TIMER);
      if (PINNED) return;
      clearTimeout(HOVER_TIMER);
      HOVER_TIMER = setTimeout(
        () => openPopup(segIndex, tok.textContent, tok, false), 180);
    };
    tok.onmouseleave = () => {
      if (HOVER && HOVER.el === tok) HOVER = null;
      clearTimeout(HOVER_TIMER);
      if (!PINNED && !$("word-pop").hidden) scheduleClose();
    };
  }
}

function scheduleClose() {
  clearTimeout(CLOSE_TIMER);
  CLOSE_TIMER = setTimeout(() => { if (!PINNED) closePopup(); }, 250);
}

function renderSegs() {
  const el = $("subs");
  if (!SEGS.length) { el.innerHTML = `<p class="dim">${esc(t("pl.no_transcript"))}</p>`; return; }
  el.innerHTML = SEGS.map((seg, i) => {
    const low = seg.logprob < -1.0 ? " lowconf" : "";
    return `<div class="seg${low}${i === CUR ? " active" : ""}" id="seg-${i}" data-i="${i}">
      <span class="time">${fmtTime(seg.start)}</span>${tokenHtml(seg)}</div>`;
  }).join("");
  for (const div of el.querySelectorAll(".seg")) {
    const i = +div.dataset.i;
    div.querySelector(".time").onclick = () => { $("video").currentTime = SEGS[i].start + OFFSET; $("video").play(); };
    bindTokenEvents(div, i);
  }
}

function renderOverlay() {
  const ca = $("overlay-ca");
  if (CUR < 0 || !SEGS[CUR]) {
    ca.innerHTML = ""; ca.classList.remove("rec-1", "rec-2");
    $("overlay-es").textContent = ""; return;
  }
  const long = SEGS[CUR].text.length > 140;
  ca.classList.toggle("longtext", long);
  $("overlay-es").classList.toggle("longtext", long);
  ca.style.display = HIDE_CA ? "none" : "";
  ca.innerHTML = tokenHtml(SEGS[CUR]);
  // recomendación estilo Migaku: verde (i+1) / azul (i+2) en la línea en vivo
  const tier = segRecTier(SEGS[CUR]);
  ca.classList.toggle("rec-1", tier === 1);
  ca.classList.toggle("rec-2", tier === 2);
  bindTokenEvents(ca, CUR);
  // el popup abierto sigue a su palabra tras el re-render (su span murió)
  if (POP && POP.anchor && !POP.anchor.isConnected) positionPopup(POP.anchor);
  if (DUAL && !HIDE_ES) fillDual(CUR);
}

async function fillDual(i) {
  const es = $("overlay-es");
  if (i < 0 || !SEGS[i]) { es.textContent = ""; return; }
  if (ES_CACHE[i] === undefined) {
    ES_CACHE[i] = "";
    const r = await api(`/api/sessions/${SESSION.id}/segments/${i}/translate`, { method: "POST" });
    ES_CACHE[i] = r.text_es || "";
  }
  if (i === CUR) es.textContent = ES_CACHE[i];
  for (const j of [i + 1, i + 2])
    if (j < SEGS.length && ES_CACHE[j] === undefined) {
      ES_CACHE[j] = "";
      api(`/api/sessions/${SESSION.id}/segments/${j}/translate`, { method: "POST" })
        .then((r) => { ES_CACHE[j] = r.text_es || ""; if (j === CUR) es.textContent = ES_CACHE[j]; });
    }
}

function scrollBrowserTo(i) {
  const panel = $("side-panel");
  if (panel.hidden || i < 0) return;
  const row = $("seg-" + i);
  if (!row) return;
  panel.scrollTop = row.offsetTop - panel.clientHeight / 2 + row.offsetHeight / 2;
}

// ---------- video ----------
const V = $("video");
V.addEventListener("click", () => { V.paused ? V.play() : V.pause(); });
V.addEventListener("play", () => { $("play-btn").classList.add("alt"); RESUME = false; });
V.addEventListener("pause", () => { $("play-btn").classList.remove("alt"); });

// controles auto-ocultables (estilo reproductor): visibles con el ratón o en
// pausa; se desvanecen tras 2.6 s reproduciendo, y al salir del video.
let CTL_TIMER = null;
// altura real de la barra (cambia con flex-wrap) → var CSS para que el
// subtítulo suba por encima de los controles cuando están visibles
function syncCtlH() {
  $("video-wrap").style.setProperty("--ctl-h", ($("controls").offsetHeight + 10) + "px");
}
function wakeControls() {
  syncCtlH();
  $("video-wrap").classList.remove("hide-ctl");
  clearTimeout(CTL_TIMER);
  if (!V.paused)
    CTL_TIMER = setTimeout(() => $("video-wrap").classList.add("hide-ctl"), 2600);
}
$("video-wrap").addEventListener("mousemove", wakeControls);
$("video-wrap").addEventListener("touchstart", wakeControls, { passive: true });
window.addEventListener("resize", syncCtlH);
// al abrir el popup se pausa el video → aparecen los controles → el subtítulo
// sube (lift): re-pegar el popup a la palabra cuando la transición termina
$("overlay-sub").addEventListener("transitionend", (e) => {
  if (e.propertyName === "bottom" && POP && POP.anchor) positionPopup(POP.anchor);
});
$("video-wrap").addEventListener("mouseleave", () => {
  if (!V.paused) { clearTimeout(CTL_TIMER); $("video-wrap").classList.add("hide-ctl"); }
});
V.addEventListener("play", wakeControls);
V.addEventListener("pause", wakeControls);
V.addEventListener("seeked", wakeControls);   // saltos con A/D también los muestran
V.addEventListener("loadedmetadata", () => { $("time-dur").textContent = fmtTime(V.duration || 0); });

// reanudar / saltar: aplicar el punto pendiente cuando el video ya tiene duración
V.addEventListener("loadedmetadata", () => {
  if (PENDING_SEEK > 0) {
    const target = PENDING_SEEK; PENDING_SEEK = 0;
    V.currentTime = target;
    const te = target - OFFSET;
    setCur(SEGS.findIndex((s) => te >= s.start && te <= s.end));
    if (target > 5) toast(`Reanudado en ${fmtTime(target)}`);
  }
});

// guardar la posición para reanudar (limitado a 1 vez / 5 s, y en pausa/salir)
let LAST_SAVE = 0;
function saveResume(force) {
  if (!SESSION || !V.duration || V.currentTime < 1) return;
  const now = Date.now();
  if (!force && now - LAST_SAVE < 5000) return;
  LAST_SAVE = now;
  const body = JSON.stringify({ pos: V.currentTime });
  const url = "/api/sessions/" + SESSION.id + "/position";
  if (force && navigator.sendBeacon)
    navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
  else
    api(url, { method: "POST", body }).catch(() => {});
}
V.addEventListener("timeupdate", () => saveResume(false));
V.addEventListener("pause", () => saveResume(true));
window.addEventListener("pagehide", () => saveResume(true));
$("play-btn").onclick = () => { V.paused ? V.play() : V.pause(); };
$("prev-btn").onclick = () => prevSeg();
$("next-btn").onclick = () => nextSeg();
$("replay-btn").onclick = () => replaySeg();

function setCur(i) {
  if (i === CUR) return;
  CUR = i;
  document.querySelectorAll(".seg.active").forEach((d) => d.classList.remove("active"));
  if (i >= 0) $("seg-" + i)?.classList.add("active");
  scrollBrowserTo(i);
  renderOverlay();
}

function gotoSeg(i) {
  if (!SEGS.length) return;
  const j = Math.min(SEGS.length - 1, Math.max(0, i));
  V.currentTime = SEGS[j].start + OFFSET + 0.01;
  // actualizar CUR ya: si no, el timeupdate con auto-pausa cree que nos
  // "escapamos" del segmento viejo y rebota al final de este.
  setCur(j);
  V.play();
}
// En huecos entre subtítulos CUR = -1: navegar por tiempo, nunca al segmento 0.
function nextSeg() {
  if (!SEGS.length) return;
  if (CUR >= 0) { gotoSeg(CUR + 1); return; }
  const t = V.currentTime - OFFSET;
  for (let i = 0; i < SEGS.length; i++)
    if (SEGS[i].start > t + 0.05) { gotoSeg(i); return; }
}
function prevSeg() {
  if (!SEGS.length) return;
  if (CUR >= 0) { gotoSeg(CUR - 1); return; }
  const t = V.currentTime - OFFSET;
  for (let i = SEGS.length - 1; i >= 0; i--)
    if (SEGS[i].end < t) { gotoSeg(i); return; }
  gotoSeg(0);
}
function replaySeg() {
  if (CUR < 0) return;
  V.currentTime = SEGS[CUR].start + OFFSET + 0.01;
  V.play();
}

let seeking = false;
$("seek").oninput = () => { seeking = true; };
$("seek").onchange = () => {
  V.currentTime = ($("seek").value / 1000) * (V.duration || 0);
  seeking = false;
  // actualizar CUR ya: si no, la auto-pausa cree que "escapamos" del segmento
  // antiguo y devuelve la reproducción al punto de partida.
  const te = V.currentTime - OFFSET;
  setCur(SEGS.findIndex((s) => te >= s.start && te <= s.end));
};

// Auto-pausa sin rebote: al reanudar aparcados en el final del segmento (ahí
// nos deja la auto-pausa), soltamos CUR para que el guard no vuelva a pausar
// y la reproducción siga hasta el final de la SIGUIENTE frase.
V.addEventListener("play", () => {
  if (CUR >= 0 && SEGS[CUR] && (V.currentTime - OFFSET) >= SEGS[CUR].end - 0.05)
    setCur(-1);
});

V.addEventListener("timeupdate", () => {
  const t = V.currentTime;
  if (!seeking && V.duration) $("seek").value = Math.round((t / V.duration) * 1000);
  $("time-cur").textContent = fmtTime(t);
  const te = t - OFFSET;                 // tiempo en el reloj de los subtítulos
  const i = SEGS.findIndex((s) => te >= s.start && te <= s.end);
  if (AUTOPAUSE && !V.paused && CUR >= 0 && i !== CUR) {
    V.pause();
    V.currentTime = Math.max(SEGS[CUR].end + OFFSET - 0.02, SEGS[CUR].start + OFFSET);
    return;
  }
  // condensado: en un hueco sin diálogo, saltar al inicio del próximo segmento
  if (CONDENSED && !V.paused && !AUTOPAUSE && i < 0) {
    const nxt = SEGS.find((s) => s.start > te);
    if (nxt) { V.currentTime = nxt.start + OFFSET; }
    else if (te > SEGS[SEGS.length - 1].end) { V.pause(); }
  }
  setCur(i);
});

// ---------- popup de palabra ----------
function markStatusButtons(st) {
  for (const b of $("wp-status").querySelectorAll("button"))
    b.classList.toggle("on", b.dataset.st === st);
}

async function openPopup(segIndex, selection, anchorEl, pin) {
  if (pin && POP && !$("word-pop").hidden &&
      POP.selection === selection && POP.segIndex === segIndex) {
    closePopup();
    return;
  }
  if (!V.paused) { V.pause(); RESUME = !pin; }
  PINNED = !!pin;
  POP = { segIndex, selection, anchor: anchorEl,
          lemma: (anchorEl.dataset?.l || selection).toLowerCase() };
  $("wp-word").textContent = selection;
  $("wp-ipa").textContent = "";
  $("wp-meta").textContent = "…";
  $("wp-level").textContent = "";
  $("wp-senses").innerHTML = "";
  $("wp-examples").innerHTML = "";
  $("wp-gloss").hidden = true; $("wp-gloss").innerHTML = "";
  $("wp-def").hidden = true; $("wp-def").textContent = "";
  $("wp-word-es").textContent = "";
  $("wp-sentence-es").textContent = "";
  $("wp-sentence-ca").textContent = SEGS[segIndex].text;
  markStatusButtons(stOf(POP.lemma));
  positionPopup(anchorEl);
  $("word-pop").classList.add("loading");   // oculta el pie hasta tener datos
  $("word-pop").hidden = false;

  const key = segIndex + ":" + selection;
  let r = LOOKUP_CACHE[key];
  if (!r) {
    r = await api("/api/lookup", {
      method: "POST",
      body: JSON.stringify({ selection, sentence: SEGS[segIndex].text,
        session_id: SESSION.id, segment_index: segIndex }),
    });
    LOOKUP_CACHE[key] = r;
  }
  if (!POP || POP.selection !== selection || POP.segIndex !== segIndex) return;
  POP.lookup = r;
  POP.lemma = r.lemma;
  markStatusButtons(stOf(r.lemma));
  renderPopupLookup(r);
  if (POP.anchor) positionPopup(POP.anchor);   // recolocar con la altura final
}

const LEVEL_LABEL = { 5: "muy frecuente", 4: "frecuente", 3: "media", 2: "poco común", 1: "rara" };
function zipfLevel(z) { return z >= 5.5 ? 5 : z >= 5 ? 4 : z >= 4.3 ? 3 : z >= 3.3 ? 2 : 1; }

function renderPopupLookup(r) {
  $("word-pop").classList.remove("loading");
  $("wp-ipa").textContent = (SETTINGS?.ipa_enabled ?? true) ? (r.ipa || "") : "";
  const lvl = zipfLevel(r.zipf);
  $("wp-level").textContent = `${LEVEL_LABEL[lvl]} ★${lvl}`;
  $("wp-meta").textContent = `${lemmaLabel(r.lemma)}${r.pos ? " · " + r.pos : ""}`;
  $("wp-sentence-es").textContent = r.sentence_es || "";
  // con base ≠ español no hay acepciones (fuentes en español); no es un fallo
  const noSenseMsg = (SETTINGS?.base_language_effective || "es") === "es"
    ? '<span class="dim" style="font-size:13px">— sin entrada en el diccionario —</span>' : "";
  $("wp-senses").innerHTML = (r.senses.length ? r.senses : [])
    .map((s, i) => `<span class="sense${i === r.active ? " active" : ""}" data-es="${esc(s.es)}">${esc(s.es)} <small>${esc(s.pos)}</small></span>`).join("")
    || noSenseMsg;
  for (const sp of $("wp-senses").querySelectorAll(".sense"))
    sp.onclick = () => { POP.chosen = sp.dataset.es; mineFromPopup(); };
  if (r.senses.length && r.active >= 0) POP.active_es = r.senses[r.active].es;
  const gl = (r.glosses || []).slice(0, 3);
  $("wp-gloss").hidden = !gl.length;
  $("wp-gloss").innerHTML = gl.map((g) => `<div class="wp-gl"><svg class="ic ic-xs"><use href="#i-book"/></svg>${esc(g.es)}</div>`).join("");
  const uds = (r.userdefs || []).slice(0, 4);
  $("wp-userdefs").hidden = !uds.length;
  $("wp-userdefs").innerHTML = uds.map((u) =>
    `<div class="wp-gl"><svg class="ic ic-xs"><use href="#i-book"/></svg>${esc(u.text)} <small class="dim">${esc(u.source)}</small></div>`).join("");
  $("wp-word-es").textContent = r.word_es || "";
  $("wp-say").hidden = !(r.ipa || r.tts);            // voz Piper o espeak
  $("wp-dict").hidden = !(SETTINGS?.online_enabled);
  // conjugación: solo verbos y solo con diccionario de formas (catalán)
  $("wp-conj-btn").hidden = !(r.pos === "VERB" && (SETTINGS?.language ?? "ca") === "ca");
  renderExamples(r);
}

async function openConj(lemma) {
  if (!lemma) return;
  // estudiar la conjugación: el vídeo se queda quieto y el popup no se
  // auto-cierra por detrás (si no, al salir el ratón se reanudaba el vídeo).
  V.pause(); RESUME = false;
  PINNED = true; clearTimeout(CLOSE_TIMER);
  $("conj-title").textContent = "Conjugació — " + lemma;
  $("conj-body").innerHTML = '<p class="dim">…</p>';
  $("conj-view").hidden = false;
  const t = await api("/api/conjugation?lemma=" + encodeURIComponent(lemma));
  $("conj-body").innerHTML = renderConjTable(t);
}

function renderConjTable(t) {
  if (!t || !t.moods || !t.moods.length)
    return '<p class="dim">— sense conjugació disponible —</p>';
  const nf = t.nonfinite || {};
  const nfHtml = ["Infinitiu", "Gerundi", "Participi"].filter((k) => nf[k])
    .map((k) => `${k}: <b>${nf[k]}</b>`).join(" · ");
  const head = `<tr><th></th>${t.pronouns.map((p) => `<th>${p}</th>`).join("")}</tr>`;
  const body = t.moods.map((m) =>
    `<tr class="conj-mrow"><td colspan="7">${m.mood}</td></tr>` +
    m.tenses.map((te) => `<tr><td class="conj-t">${te.tense}</td>${te.forms.map((f) => `<td>${f || "—"}</td>`).join("")}</tr>`).join("")
  ).join("");
  return (nfHtml ? `<p class="conj-nf">${nfHtml}</p>` : "") +
    `<div class="conj-scroll"><table class="conj-tbl">${head}${body}</table></div>`;
}
$("wp-conj-btn").onclick = () => openConj(POP?.lemma);
function closeConj() { $("conj-view").hidden = true; closePopup(); }
$("conj-close").onclick = closeConj;
$("conj-view").onclick = (e) => { if (e.target === $("conj-view")) closeConj(); };

// frases del propio contenido donde aparece el mismo lema (carga perezosa)
async function renderExamples(r) {
  if (!r._examples) {
    const ex = await api(`/api/examples?lemma=${encodeURIComponent(r.lemma)}` +
      `&session_id=${SESSION.id}&index=${POP ? POP.segIndex : -1}`);
    r._examples = ex.examples || [];
  }
  if (!POP || POP.lookup !== r) return;
  $("wp-examples").innerHTML = r._examples.slice(0, 3).map((e) =>
    `<div class="wp-ex" title="${esc(e.session_title)}">${esc(e.text)}</div>`).join("");
}

for (const b of $("wp-status").querySelectorAll("button"))
  b.onclick = () => { if (POP) setStatus(POP.lemma, b.dataset.st); };

// si el overlay se re-renderizó (cambio de estado, sync…), el span ancla
// muere: se relocaliza el token equivalente en el DOM nuevo
function refindAnchor() {
  if (!POP || POP.segIndex !== CUR) return null;   // otra frase: no re-pegar
  return [...document.querySelectorAll("#overlay-ca .t")]
    .find((e) => e.textContent === POP.selection) || null;
}

function positionPopup(anchorEl) {
  if (!anchorEl || !anchorEl.isConnected) {
    anchorEl = refindAnchor();
    if (!anchorEl) return;               // sin ancla: conservar posición actual
    POP.anchor = anchorEl;
  }
  const pop = $("word-pop");
  const rect = anchorEl.getBoundingClientRect();
  pop.hidden = false;
  const w = pop.offsetWidth || 324, gap = 12;
  const x = Math.min(Math.max(8, rect.left + rect.width / 2 - w / 2),
                     window.innerWidth - w - 8);
  pop.style.left = x + "px";
  // estilo Migaku: nunca tapa la palabra. Con sitio arriba, se ancla por el
  // borde INFERIOR (crece hacia arriba al llegar el contenido async); si no,
  // va debajo anclado por arriba. Así el popup jamás se expande sobre la palabra.
  const roomAbove = rect.top, roomBelow = window.innerHeight - rect.bottom;
  const above = roomAbove >= roomBelow;
  if (above) {
    pop.style.top = "auto";
    pop.style.bottom = Math.max(8, window.innerHeight - rect.top + gap) + "px";
  } else {
    pop.style.bottom = "auto";
    pop.style.top = Math.max(8, rect.bottom + gap) + "px";
  }
  // flecha estilo Migaku apuntando a la palabra: horizontal en el centro de la
  // palabra (recortada al ancho del popup), arriba o abajo según el lado.
  const arrow = $("wp-arrow");
  if (arrow) {
    const cx = rect.left + rect.width / 2 - x;      // centro de la palabra rel. al popup
    arrow.style.left = Math.min(Math.max(16, cx), w - 16) + "px";
    arrow.classList.toggle("down", above);          // popup arriba → flecha abajo
    arrow.classList.toggle("up", !above);
  }
}

function closePopup() {
  $("word-pop").hidden = true;
  POP = null; PINNED = false;
  clearTimeout(HOVER_TIMER); clearTimeout(CLOSE_TIMER);
  if (RESUME) { RESUME = false; V.play(); }
}
$("wp-close").onclick = closePopup;
const WP = $("word-pop");
WP.onmouseenter = () => clearTimeout(CLOSE_TIMER);
WP.onmouseleave = () => { if (!PINNED) scheduleClose(); };
document.addEventListener("click", (e) => {
  if (!$("word-pop").hidden && !$("word-pop").contains(e.target) && !e.target.classList?.contains("t"))
    closePopup();
});
$("wp-replay").onclick = () => { if (POP) { V.currentTime = SEGS[POP.segIndex].start + OFFSET; V.play(); } };
$("wp-card").onclick = () => mineFromPopup();
$("wp-edit").onclick = () => editFromPopup();
$("wp-say").onclick = async () => {
  if (!POP) return;
  const r = await api("/api/tts?text=" + encodeURIComponent(POP.selection));
  if (r.file) new Audio("/media/" + r.file).play().catch(() => {});
};
$("wp-dict").onclick = async () => {
  if (!POP) return;
  $("wp-def").hidden = false; $("wp-def").textContent = "…";
  const r = await api("/api/define?word=" + encodeURIComponent(POP.lemma || POP.selection));
  $("wp-def").textContent = r.text || "— sin entrada en el Viccionari —";
};
// traducción editable: lo escrito pasa a ser el paraula_es de la tarjeta
$("wp-word-es").addEventListener("input", () => {
  if (POP) POP.chosen = $("wp-word-es").textContent.trim();
});

function mineFromPopup() {
  if (!POP) return;
  const { segIndex, selection, chosen } = POP;
  closePopup();
  mineQuick(segIndex, selection, chosen || "");
}

function editFromPopup() {
  if (!POP) return;
  const { segIndex, selection } = POP;
  closePopup();
  mine(segIndex, selection);
}

// minado en segundo plano: crea + envía a Anki sin panel ni pausa
async function mineQuick(segIndex, selection, paraula_es = "") {
  toast("Creando tarjeta…");
  const r = await api("/api/cards/mine", {
    method: "POST",
    body: JSON.stringify({ session_id: SESSION.id, segment_index: segIndex,
      selection, paraula_es, offset: OFFSET }),
  });
  if (r.error) { toast(r.error, "err"); return; }
  if (r.word_status) STATUS[r.lema] = r.word_status;
  renderSegs(); renderOverlay(); updateComp(); refreshAnki();
  toast(r.sent_now ? `«${r.paraula}» → Anki` : `«${r.paraula}» en cola`,
        r.sent_now ? "ok" : "err");
}

// ---------- minado ----------
async function mine(segIndex, selection, padB = 0, padA = 0, extra = {}) {
  V.pause();
  PAD = { b: padB, a: padA };
  toast("Creando tarjeta…");
  const p = await api("/api/cards/preview", {
    method: "POST",
    body: JSON.stringify({ session_id: SESSION.id, segment_index: segIndex,
      selection, pad_before: padB, pad_after: padA, offset: OFFSET }),
  });
  CARD = { ...p, session_id: SESSION.id, segment_index: segIndex };
  // el clip animado (WebP) sustituye a la captura estática cuando existe
  CARD.image_file = p.clip_file || p.image_file;
  $("c-paraula").value = p.paraula;
  $("c-paraula-es").value = extra.chosen || p.paraula_es;
  $("c-frase").value = p.frase;
  $("c-frase-es").value = p.frase_es;
  $("c-meta").textContent = `${p.lema} · ${p.pos} · ${p.freq_rank} (zipf ${p.freq_zipf.toFixed(1)}) · ${p.font}`;
  $("senses").innerHTML = p.senses.map((s) =>
    `<span class="sense" data-es="${esc(s.es)}">${esc(s.es)} <small>${esc(s.pos)}</small></span>`).join("");
  for (const sp of $("senses").children)
    sp.onclick = () => { $("c-paraula-es").value = sp.dataset.es; };
  $("c-audio").src = p.audio_file ? "/media/" + p.audio_file : "";
  $("c-image").src = CARD.image_file ? "/media/" + CARD.image_file : "";
  $("card-panel").hidden = false;
  if (p.audio_file) $("c-audio").play().catch(() => {});
}

$("pad-before").onclick = () => CARD && mine(CARD.segment_index, $("c-paraula").value, PAD.b + 1, PAD.a);
$("pad-after").onclick = () => CARD && mine(CARD.segment_index, $("c-paraula").value, PAD.b, PAD.a + 1);
$("c-cancel").onclick = () => { $("card-panel").hidden = true; };

async function sendCard() {
  if (!CARD) return;
  const body = {
    session_id: CARD.session_id, segment_index: CARD.segment_index,
    paraula: $("c-paraula").value, lema: CARD.lema, pos: CARD.pos,
    paraula_es: $("c-paraula-es").value,
    frase: $("c-frase").value, frase_es: $("c-frase-es").value,
    freq_rank: CARD.freq_rank, audio_file: CARD.audio_file,
    image_file: CARD.image_file, font: CARD.font,
  };
  const r = await api("/api/cards", { method: "POST", body: JSON.stringify(body) });
  $("card-panel").hidden = true;
  if (r.word_status) STATUS[CARD.lema] = r.word_status;
  renderSegs();
  renderOverlay();
  updateComp();
  refreshAnki();
  toast(r.sent_now ? "Tarjeta añadida a Anki" : "Tarjeta en cola", r.sent_now ? "ok" : "err");
}
$("c-send").onclick = sendCard;

// ---------- teclado (mapa Migaku + estados) ----------
// A/← anterior · D/→ siguiente · S/↓ repetir · W/↑ ocultar subs · shift+W ocultar ES ·
// G navegador · C copiar · Q minar · 1-4 estado · E dual · P auto-pausa · F pantalla completa
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT" || e.target.isContentEditable) {
    if (e.key === "Enter" && !e.shiftKey && !$("card-panel").hidden) { e.preventDefault(); sendCard(); }
    return;
  }
  if (e.key === "Escape") {
    closePopup(); $("card-panel").hidden = true;
    $("stats-view").hidden = true; $("settings-view").hidden = true; $("help-view").hidden = true; $("conj-view").hidden = true;
    if ($("video-col").classList.contains("fake-fs")) { $("video-col").classList.remove("fake-fs"); $("fs-btn").classList.remove("alt"); }
    return;
  }
  if (e.key === "?") { e.preventDefault(); toggleHelp(); return; }
  if ($("player").hidden || !$("settings-view").hidden || CAPTURING) return;
  const k = e.key.toLowerCase();
  const statusKeys = { "1": "unknown", "2": "learning", "3": "known", "4": "ignored", "5": "tracking" };
  if (e.key === " ") { e.preventDefault(); V.paused ? V.play() : V.pause(); return; }
  if (statusKeys[e.key]) {
    const lemma = (POP && !$("word-pop").hidden) ? POP.lemma : HOVER?.lemma;
    if (lemma) setStatus(lemma, statusKeys[e.key]);
    else toast("Pasa el ratón por una palabra y pulsa " + e.key, "err");
    return;
  }
  if (e.key === "[") { e.preventDefault(); bumpOffset(-0.1); return; }
  if (e.key === "]") { e.preventDefault(); bumpOffset(0.1); return; }
  if (k === "k") { setCondensed(!CONDENSED); return; }
  // teclas de letra remapeables (⚙️) + flechas fijas
  const act = KEY2ACTION[k] ||
    ({ ArrowLeft: "prev", ArrowRight: "next", ArrowDown: "replay", ArrowUp: "subs" })[e.key];
  if (act === "prev") { e.preventDefault(); prevSeg(); }
  else if (act === "next") { e.preventDefault(); nextSeg(); }
  else if (act === "replay") { e.preventDefault(); replaySeg(); }
  else if (act === "subs") {
    e.preventDefault();
    if (e.shiftKey) { HIDE_ES = !HIDE_ES; $("overlay-es").hidden = !DUAL || HIDE_ES; }
    else { HIDE_CA = !HIDE_CA; renderOverlay(); }
  }
  else if (act === "browser") toggleBrowser();
  else if (act === "copy" && CUR >= 0) { navigator.clipboard.writeText(SEGS[CUR].text).then(() => toast("Copiado", "ok")); }
  else if (act === "mine") {
    const inPop = POP && !$("word-pop").hidden;
    const seg = inPop ? POP.segIndex : HOVER?.segIndex;
    const sel = inPop ? POP.selection : HOVER?.text;
    if (sel === undefined) { toast("Pasa el ratón por una palabra y pulsa " + (SETTINGS?.keymap?.mine || "Q").toUpperCase(), "err"); return; }
    const chosen = inPop ? (POP.chosen || "") : "";
    if (inPop) closePopup();
    if (e.shiftKey) mine(seg, sel);
    else mineQuick(seg, sel, chosen);
  }
  else if (act === "dual") setDual(!DUAL);
  else if (act === "autopause") setAutopause(!AUTOPAUSE);
  else if (act === "fullscreen") toggleFullscreen();
  else if (act === "recommended") nextRec();
  else if (e.key === "Enter" && !$("card-panel").hidden) sendCard();
});

// ---------- estadísticas ----------
const ST_COLORS = { learning: "#e5a04c", known: "#4fc383", ignored: "#6b6b7c", tracking: "#8b7cf8" };

function svgBars(data, color = "#8b7cf8") {  // data: [[label, value], ...]
  const max = Math.max(1, ...data.map((d) => d[1]));
  const bw = 34, gap = 12, h = 120;
  const w = data.length * (bw + gap) + gap;
  const bars = data.map(([lab, v], i) => {
    const bh = Math.round((v / max) * (h - 34));
    const x = gap + i * (bw + gap), y = h - 18 - bh;
    return `<rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="4" fill="${color}"><title>${lab}: ${v}</title></rect>
      <text x="${x + bw / 2}" y="${y - 4}" text-anchor="middle" class="sv">${v}</text>
      <text x="${x + bw / 2}" y="${h - 4}" text-anchor="middle" class="sl">${lab}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w * 1.4}px">${bars}</svg>`;
}

function svgDonut(counts) {  // {status: n}
  const entries = Object.entries(counts).filter(([, v]) => v > 0);
  const total = entries.reduce((a, [, v]) => a + v, 0);
  if (!total) return '<p class="dim">Sin palabras marcadas aún.</p>';
  // hueco angular entre segmentos: codificación secundaria además del color
  // (ámbar↔verde quedan a ΔE 7 en visión protán; el gap + etiquetas resuelven)
  const GAP = entries.length > 1 ? 0.06 : 0;
  let a0 = -Math.PI / 2, paths = "";
  for (const [st, v] of entries) {
    const a1 = a0 + (v / total) * Math.PI * 2;
    const g = Math.min(GAP, (a1 - a0) / 3);
    const large = (a1 - g) - (a0 + g) > Math.PI ? 1 : 0;
    const p = (a) => `${60 + 46 * Math.cos(a)},${60 + 46 * Math.sin(a)}`;
    const pct = Math.round((v / total) * 100);
    paths += `<path d="M ${p(a0 + g)} A 46 46 0 ${large} 1 ${p(a1 - g)}" stroke="${ST_COLORS[st] || "#888"}"
      stroke-width="16" fill="none" stroke-linecap="round"><title>${ST_LABEL[st] || st}: ${v} (${pct}%)</title></path>`;
    a0 = a1;
  }
  const legend = entries.map(([st, v]) =>
    `<span class="leg"><i style="background:${ST_COLORS[st] || "#888"}"></i>${ST_LABEL[st] || st}: ${v} · ${Math.round((v / total) * 100)}%</span>`).join("");
  return `<div class="donut-row"><svg viewBox="0 0 120 120" width="120" role="img">${paths}
    <text x="60" y="66" text-anchor="middle" class="sv">${total}</text></svg>
    <div class="legend">${legend}</div></div>`;
}

// gráfico de área: crecimiento de conocidas en el tiempo
function svgArea(points, color = "#4fc383") {  // [{date,total}]
  if (points.length < 2) return '<p class="dim">Marca más palabras como conocidas para ver tu progreso.</p>';
  const w = 520, h = 150, pad = 8;
  const max = Math.max(...points.map((p) => p.total));
  const x = (i) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const y = (v) => h - 18 - (v / max) * (h - 30);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.total).toFixed(1)}`).join(" ");
  const area = `${pad},${h - 18} ${line} ${w - pad},${h - 18}`;
  // capa hover: un punto invisible con tooltip nativo por cada dato
  const hover = points.map((p, i) =>
    `<circle cx="${x(i).toFixed(1)}" cy="${y(p.total).toFixed(1)}" r="9" fill="transparent">
      <title>${p.date}: ${p.total}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%" role="img">
    <defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${color}" stop-opacity=".35"/>
      <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <line x1="${pad}" y1="${h - 18}" x2="${w - pad}" y2="${h - 18}" stroke="#262b42" stroke-width="1"/>
    <polygon points="${area}" fill="url(#ga)"/>
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${x(points.length - 1)}" cy="${y(points[points.length - 1].total)}" r="4" fill="${color}" stroke="#151827" stroke-width="2"/>
    <text x="${w - pad}" y="14" text-anchor="end" class="sv">${max}</text>
    ${hover}
  </svg>`;
}

// tira de actividad de minado (últimos días)
function svgActivity(days, color = "#8b7cf8") {  // [{date,n}]
  if (!days.length) return "";
  const max = Math.max(1, ...days.map((d) => d.n));
  const bw = 100 / days.length;
  const bars = days.map((d, i) => {
    const bh = (d.n / max) * 100;
    return `<rect x="${(i * bw + bw * 0.12).toFixed(2)}" y="${(100 - bh).toFixed(2)}"
      width="${(bw * 0.76).toFixed(2)}" height="${bh.toFixed(2)}" rx="1.2" fill="${color}">
      <title>${d.date}: ${d.n}</title></rect>`;
  }).join("");
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:56px">${bars}</svg>`;
}

function kpiTile(value, label, color) {
  // el valor viste tinta de texto; la identidad la lleva la marca de color
  return `<div class="kpi" style="--kpi-c:${color}"><div class="kpi-v">${value}</div>
    <div class="kpi-l"><i class="kpi-dot"></i>${label}</div></div>`;
}

async function openStats() {
  $("stats-view").hidden = false;
  $("stats-body").innerHTML = '<p class="dim">Cargando…</p>';
  const s = await api("/api/stats");
  const sc = s.status_counts || {};
  const growth = s.known_over_time || [];
  const kpis = `<div class="kpi-row">
    ${kpiTile(sc.known || 0, t("stats.known"), "#4fc383")}
    ${kpiTile(sc.learning || 0, t("stats.learning"), "#e5a04c")}
    ${kpiTile(s.total_cards, t("stats.mined"), "#8b7cf8")}
    ${kpiTile(s.streak_days || 0, t("stats.streak"), "#c678dd")}
    ${kpiTile(s.anki && s.anki.retention !== null ? s.anki.retention + "%" : "—", t("stats.retention"), "#6fb3ff")}
  </div>`;
  let html = kpis + `
    <section><h3>Palabras conocidas · progreso</h3>
      ${svgArea(growth)}
    </section>
    <section><h3>Actividad de minado</h3>
      ${svgActivity(s.mined_by_day || [])}
      <p class="dim" style="margin-top:4px">${s.total_cards} tarjetas en ${s.sessions} sesiones</p>
    </section>
    <section><h3>Palabras por estado</h3>
      ${svgDonut(sc)}
    </section>`;
  if (s.anki) {
    html += `
    <section><h3>Repasos en Anki (mazo de minado)</h3>
      <p class="dim" title="retención = 1 − fallos/repasos, sobre todas las tarjetas del mazo">${s.anki.total} tarjetas · ${s.anki.mature} maduras (≥ 21 días)</p>
      ${svgBars([["hoy", s.anki.due_today], ["7 días", s.anki.due_7d], ["30 días", s.anki.due_30d]], "#e5a04c")}
      <p class="dim">Carga futura de repasos.</p>
    </section>`;
  } else {
    html += '<section><h3>En Anki</h3><p class="dim">Abre Anki para ver retención y pronóstico de repasos.</p></section>';
  }
  $("stats-body").innerHTML = html;
}
$("stats-btn").onclick = openStats;
$("stats-close").onclick = () => { $("stats-view").hidden = true; };
$("stats-view").onclick = (e) => { if (e.target === $("stats-view")) $("stats-view").hidden = true; };

// ---------- configuración ⚙️ ----------
const ACTION_LABEL = {
  prev: "Frase anterior", next: "Frase siguiente", replay: "Repetir frase",
  mine: "Crear tarjeta (⇧ = editar)", subs: "Ocultar subtítulos (⇧ = línea ES)",
  browser: "Navegador de subtítulos", copy: "Copiar frase",
  dual: "Subtítulo dual", autopause: "Auto-pausa",
  fullscreen: "Pantalla completa", recommended: "Siguiente recomendada",
};

function rebuildKeymap() {
  KEY2ACTION = {};
  const km = SETTINGS?.keymap || DEFAULT_KEYMAP;
  for (const [act, key] of Object.entries(km)) KEY2ACTION[key] = act;
}

function renderHelpLine() {
  // la línea de ayuda refleja el keymap real (tras remapear en ⚙️ no miente)
  const km = SETTINGS?.keymap || DEFAULT_KEYMAP;
  const U = (a) => (km[a] || "?").toUpperCase();
  $("help-line").textContent = t("help.line",
    U("prev"), U("next"), U("replay"), U("mine"), U("recommended"),
    U("subs"), U("dual"), U("browser"), U("fullscreen"));
}

function applySettings() {
  document.documentElement.style.setProperty("--sub-scale", SETTINGS.sub_scale);
  setUILang(SETTINGS.ui_lang || "es");           // idioma de la interfaz
  $("set-ui-lang").value = SETTINGS.ui_lang || "es";
  rebuildKeymap();
  renderKeyEditor();
  renderHelpLine();
  $("set-sub-scale").value = Math.round(SETTINGS.sub_scale * 100);
  $("set-sub-val").textContent = Math.round(SETTINGS.sub_scale * 100);
  $("set-dual").checked = SETTINGS.dual_default;
  $("set-autopause").checked = SETTINGS.autopause_default;
  $("set-speed").value = String(SETTINGS.speed_default);
  $("set-ipa").checked = SETTINGS.ipa_enabled;
  $("set-online").checked = SETTINGS.online_enabled;
  $("set-audio-trim").checked = SETTINGS.audio_trim;
  $("set-port").value = SETTINGS.anki_port ?? "";
  // idioma: el selector solo aparece cuando hay más de un perfil activable
  const langs = (SETTINGS.languages || []).filter((l) => l.available);
  $("set-lang-section").hidden = langs.length <= 1;
  $("set-language").innerHTML = langs.map((l) =>
    `<option value="${l.code}"${l.code === SETTINGS.language ? " selected" : ""}>${l.name}</option>`).join("");
  // idioma base (traducir a): solo si el idioma de estudio ofrece alternativas
  const bases = SETTINGS.bases || [{ code: "es", name: "Español" }];
  const activeBase = SETTINGS.base_language_effective || "es";
  $("set-base-section").hidden = bases.length <= 1;
  $("set-base").innerHTML = bases.map((b) =>
    `<option value="${esc(b.code)}"${b.code === activeBase ? " selected" : ""}>${esc(b.name)}</option>`).join("");
  // etiquetas «ES» de la tarjeta y del dual → idioma base activo
  const baseTag = activeBase.toUpperCase();
  $("lbl-word-es").textContent = t("card.word") + " " + baseTag;
  $("lbl-sentence-es").textContent = t("card.sentence") + " " + baseTag;
  $("dual-btn").title = t("dual.title", baseTag);
  // selector de Whisper según el idioma activo (el modelo catalán AINA no
  // debe ofrecerse para transcribir alemán, etc.)
  const wm = SETTINGS.whisper_models || [];
  if (wm.length) {
    const WLBL = {
      "catala-large": "Whisper large-v3 catalán (AINA) — máxima calidad",
      "large-v3": "Whisper large-v3 multilingüe — máxima calidad",
      "small": "Whisper small — rápido",
    };
    $("model-select").innerHTML = wm.map((k) =>
      `<option value="${esc(k)}"${k === SETTINGS.default_whisper ? " selected" : ""}>${esc(WLBL[k] || k)}</option>`).join("");
  }
  // el hero refleja el idioma de estudio activo («Mina inglés desde tus videos…»)
  const lc = SETTINGS.language || "ca";
  let ln = t("lang." + lc);
  if (ln === "lang." + lc)                       // sin clave i18n → nombre del perfil
    ln = (SETTINGS.languages || []).find((l) => l.code === lc)?.name || lc;
  $("hero-sub").textContent = t("hero.sub", ln);
}

async function loadSettings() {
  SETTINGS = await api("/api/settings");
  applySettings();
}

async function saveSettings(partial) {
  const r = await api("/api/settings", { method: "POST", body: JSON.stringify(partial) });
  if (r.error) { toast(r.error, "err"); return; }
  SETTINGS = r;
  applySettings();
}

function renderKeyEditor() {
  const km = SETTINGS?.keymap || DEFAULT_KEYMAP;
  $("set-keys").innerHTML = Object.keys(ACTION_LABEL).map((a) =>
    `<div class="set-row"><label>${ACTION_LABEL[a]}</label>
     <button class="keybtn" data-act="${a}">${CAPTURING === a ? "pulsa una tecla…" : (km[a] || "?").toUpperCase()}</button></div>`).join("");
  for (const b of $("set-keys").querySelectorAll(".keybtn"))
    b.onclick = () => { CAPTURING = b.dataset.act; renderKeyEditor(); };
}

// ---------- overlay de ayuda de atajos (tecla ?) ----------
const HELP_FIXED = [
  ["Espacio", "Reproducir / pausar"],
  ["1 – 5", "Estado: nueva · aprendiendo · conocida · ignorar · seguir"],
  ["Q / ⇧Q", "Crear tarjeta / editar y crear"],
  ["[  ]", "Sincronía de subtítulos (−/+ 0,1 s)"],
  ["K", "Reproducción condensada (saltar silencios)"],
  ["⏎", "Enviar la tarjeta a Anki"],
  ["? ", "Esta ayuda · Esc cierra"],
];
function renderHelp() {
  const km = SETTINGS?.keymap || DEFAULT_KEYMAP;
  const row = (k, d) => `<div class="help-row"><kbd>${k}</kbd><span>${d}</span></div>`;
  const remap = Object.keys(ACTION_LABEL)
    .map((a) => row((km[a] || "?").toUpperCase(), ACTION_LABEL[a])).join("");
  const fixed = HELP_FIXED.map(([k, d]) => row(k, d)).join("");
  $("help-body").innerHTML =
    `<div class="help-cols">
       <div><h3>Reproducción y minado</h3>${remap}</div>
       <div><h3>Teclas fijas</h3>${fixed}</div>
     </div>
     <h3>Frases recomendadas para minar</h3>
     <div class="rec-legend">
       <span><i class="rec-sw green"></i>i+1 — 1 palabra nueva (óptima, ${(km.recommended || "r").toUpperCase()} salta a la siguiente)</span>
       <span><i class="rec-sw blue"></i>i+2 — 2 palabras nuevas (también buena)</span>
     </div>
     <p class="dim">El subtítulo se subraya en verde o azul cuando es una buena frase para hacer flashcard.</p>
     <p class="dim">Las letras se cambian en Ajustes → Atajos de teclado.</p>`;
}
function toggleHelp() {
  const v = $("help-view");
  if (v.hidden) renderHelp();
  v.hidden = !v.hidden;
}
$("help-close").onclick = () => { $("help-view").hidden = true; };
$("help-view").onclick = (e) => { if (e.target === $("help-view")) $("help-view").hidden = true; };

// captura de tecla nueva (fase capture: le gana al handler global)
document.addEventListener("keydown", (e) => {
  if (!CAPTURING) return;
  e.preventDefault(); e.stopPropagation();
  const k = e.key.toLowerCase();
  const act = CAPTURING; CAPTURING = null;
  if (!/^[a-z]$/.test(k)) { toast("Solo letras a–z", "err"); renderKeyEditor(); return; }
  saveSettings({ keymap: { [act]: k } });
}, true);

$("set-keys-reset").onclick = () => saveSettings({ keymap: { ...DEFAULT_KEYMAP } });

function renderUserdicts(dicts) {
  $("set-userdict-list").innerHTML = dicts.length
    ? dicts.map((d) => `<div class="set-row"><label>${esc(d.name)} <small class="dim">(${d.entries} entradas)</small></label><button class="small ud-rm" data-slug="${esc(d.slug)}">Quitar</button></div>`).join("")
    : '<p class="dim" style="font-size:13px">— ninguno importado —</p>';
  for (const b of $("set-userdict-list").querySelectorAll(".ud-rm"))
    b.onclick = async () => {
      const r = await api("/api/userdict/remove", { method: "POST", body: JSON.stringify({ slug: b.dataset.slug }) });
      renderUserdicts(r.dicts || []);
    };
}
async function refreshUserdicts() {
  try { renderUserdicts((await api("/api/userdict/list")).dicts || []); } catch { /* noop */ }
}
$("set-userdict-import").onclick = async () => {
  const path = $("set-userdict-path").value.trim();
  if (!path) return;
  $("set-userdict-import").disabled = true;
  toast("Importando diccionario…");
  const r = await api("/api/userdict/import", { method: "POST", body: JSON.stringify({ path }) });
  $("set-userdict-import").disabled = false;
  if (r.error) { toast(r.error, "err"); return; }
  toast(`${r.name}: ${r.entries} entradas`, "ok");
  $("set-userdict-path").value = "";
  renderUserdicts(r.dicts || []);
};

async function openSettings() {
  $("settings-view").hidden = false;
  refreshShare();
  refreshUserdicts();
  const st = await api("/api/anki/status");
  $("set-deck").innerHTML = (st.decks || []).map((d) =>
    `<option${d === st.deck ? " selected" : ""}>${d}</option>`).join("")
    || `<option>${SETTINGS?.deck || ""}</option>`;
}

function renderShare(s) {
  $("set-share").checked = s.running;
  const info = $("share-info");
  info.hidden = !(s.running && s.urls.length);
  $("share-urls").innerHTML = (s.running ? s.urls : []).map((u) => `
    <div class="share-url">
      <img class="share-qr" alt="QR ${u.label}" src="/api/share/qr?url=${encodeURIComponent(u.url)}">
      <div class="share-url-body">
        <div class="share-url-label">${u.label}</div>
        <code>${u.url}</code>
        <button class="small share-copy" data-url="${u.url}">Copiar enlace</button>
      </div>
    </div>`).join("");
  info.querySelectorAll(".share-copy").forEach((b) => {
    b.onclick = () => { navigator.clipboard?.writeText(b.dataset.url); toast("Enlace copiado", "ok"); };
  });
  let note = "";
  if (s.running) note += "⚠️ Quien abra el enlace en tu red o tailnet tiene acceso completo — compártelo solo con amigos de confianza. ";
  if (!s.tailscale) note += "Instala Tailscale para que entren amigos fuera de tu wifi (y para HTTPS + instalación como app).";
  else if (!s.tailscale_up) note += "Tailscale está instalado pero apagado: ábrelo para obtener un enlace 100.x accesible desde cualquier sitio.";
  else note += "Tailscale activo ✓ — usa su enlace para amigos remotos.";
  $("share-note").textContent = note;
}

async function refreshShare() {
  try { renderShare(await api("/api/share/status")); }
  catch { $("share-section").hidden = true; }
}

$("set-share").onchange = async () => {
  $("set-share").disabled = true;
  const path = $("set-share").checked ? "/api/share/start" : "/api/share/stop";
  try {
    const s = await api(path, { method: "POST" });
    renderShare(s);
    toast(s.running ? "Modo compartir activado" : "Modo compartir desactivado", s.running ? "ok" : "");
  } catch { toast("No se pudo cambiar el modo compartir", "err"); refreshShare(); }
  $("set-share").disabled = false;
};
$("settings-btn").onclick = openSettings;
$("settings-close").onclick = () => { $("settings-view").hidden = true; };

// ---------- actualizaciones (solo el equipo anfitrión; invitados: 403) ----------
if (["localhost", "127.0.0.1"].includes(location.hostname))
  $("update-section").hidden = false;
$("update-check").onclick = async () => {
  $("update-status").textContent = t("set.upd_checking");
  $("update-apply").hidden = true;
  try {
    const r = await api("/api/update/check");
    if (r.error) { $("update-status").textContent = `${t("set.upd_err")}: ${r.error}`; return; }
    if (!r.git) { $("update-status").textContent = t("set.upd_nogit"); return; }
    if (r.behind > 0) {
      $("update-status").textContent = t("set.upd_avail", r.behind, r.latest);
      $("update-apply").hidden = false;
    } else {
      $("update-status").textContent = t("set.upd_ok", r.current);
    }
  } catch { $("update-status").textContent = t("set.upd_err"); }
};
$("update-apply").onclick = async () => {
  $("update-apply").disabled = true;
  $("update-status").textContent = t("set.upd_updating");
  try {
    const r = await api("/api/update/apply", { method: "POST" });
    if (r.error) { $("update-status").textContent = `${t("set.upd_err")}: ${r.error}`; return; }
    $("update-apply").hidden = true;
    $("update-status").textContent = r.deps_changed
      ? t("set.upd_done_deps", r.installer) : t("set.upd_done");
  } catch { $("update-status").textContent = t("set.upd_err"); }
  finally { $("update-apply").disabled = false; }
};
$("settings-view").onclick = (e) => { if (e.target === $("settings-view")) $("settings-view").hidden = true; };

$("set-deck").onchange = async () => {
  await api("/api/anki/deck", { method: "POST", body: JSON.stringify({ deck: $("set-deck").value }) });
  toast("Mazo: " + $("set-deck").value, "ok");
};
$("set-port").onchange = async () => {
  const v = $("set-port").value.trim();
  const r = await api("/api/anki/port", { method: "POST", body: JSON.stringify({ port: v === "" ? null : parseInt(v, 10) }) });
  toast(r.port ? `AnkiConnect en el puerto ${r.port}` : "Aún no encuentro AnkiConnect", r.port ? "ok" : "err");
  refreshAnki();
};
$("set-sub-scale").oninput = () => {
  const v = $("set-sub-scale").value;
  $("set-sub-val").textContent = v;
  document.documentElement.style.setProperty("--sub-scale", v / 100);
};
$("set-sub-scale").onchange = () => saveSettings({ sub_scale: $("set-sub-scale").value / 100 });
$("set-dual").onchange = () => saveSettings({ dual_default: $("set-dual").checked });
$("set-autopause").onchange = () => saveSettings({ autopause_default: $("set-autopause").checked });
$("set-speed").onchange = () => saveSettings({ speed_default: parseFloat($("set-speed").value) });
$("set-ipa").onchange = () => saveSettings({ ipa_enabled: $("set-ipa").checked });
$("set-online").onchange = () => saveSettings({ online_enabled: $("set-online").checked });
$("set-ui-lang").onchange = () => saveSettings({ ui_lang: $("set-ui-lang").value });
$("set-audio-trim").onchange = () => saveSettings({ audio_trim: $("set-audio-trim").checked });
$("set-language").onchange = async () => {
  await saveSettings({ language: $("set-language").value });
  toast(t("set.lang_changed"));
  loadSessions();
};
$("set-base").onchange = async () => {
  await saveSettings({ base_language: $("set-base").value });
  toast(t("set.base_changed"));
  // re-traducir lo visible al nuevo idioma base
  if (SESSION) openSession(SESSION.id);
};
$("set-import").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    const r = await api("/api/words/import", {
      method: "POST",
      body: JSON.stringify({ statuses: data.statuses || data, overwrite: false }),
    });
    if (r.error) { toast(r.error, "err"); return; }
    toast(`${r.imported} palabras importadas (${r.skipped} ya existían)`, "ok");
    if (SESSION) openSession(SESSION.id);
  } catch { toast("JSON inválido", "err"); }
  e.target.value = "";
};

// ---------- panel de palabras (Language Reactor) ----------
let RANKS = null, PANEL_TAB = "subs";

async function loadRanks() {
  if (!RANKS) RANKS = (await api("/api/vocab/ranks")).ranks || {};
  return RANKS;
}

function setPanelTab(t) {
  PANEL_TAB = t;
  $("tab-subs").classList.toggle("on", t === "subs");
  $("tab-words").classList.toggle("on", t === "words");
  $("subs").hidden = t !== "subs";
  $("words-view").hidden = t !== "words";
  if (t === "words") renderWords();
}
$("tab-subs").onclick = () => setPanelTab("subs");
$("tab-words").onclick = () => setPanelTab("words");

const BANDS = [[1, 100], [101, 300], [301, 1000], [1001, 5000]];

async function renderWords() {
  await loadRanks();
  // lemas del video: primera aparición + zipf máximo
  const first = {}, zmax = {};
  SEGS.forEach((seg, i) => {
    for (const t of (seg.tokens || []))
      if (t.is_word && t.lemma) {
        if (!(t.lemma in first)) first[t.lemma] = i;
        zmax[t.lemma] = Math.max(zmax[t.lemma] || 0, t.zipf || 0);
      }
  });
  const lemmas = Object.keys(first);
  if (!lemmas.length) { $("words-list").innerHTML = `<p class="dim">${esc(t("words.empty"))}</p>`; return; }
  const bandOf = (l) => {
    const r = RANKS[l];
    if (!r) return BANDS.length;
    for (let b = 0; b < BANDS.length; b++) if (r <= BANDS[b][1]) return b;
    return BANDS.length;
  };
  const groups = Array.from({ length: BANDS.length + 1 }, () => []);
  for (const l of lemmas) groups[bandOf(l)].push(l);
  for (const g of groups)
    g.sort((a, b) => (RANKS[a] || 1e9) - (RANKS[b] || 1e9) || (zmax[b] - zmax[a]));
  const label = (b) => b < BANDS.length
    ? `Rank ${BANDS[b][0]} – ${BANDS[b][1]}` : t("words.rest");
  $("words-list").innerHTML = groups.map((g, b) => g.length ? `
    <div class="wband"><div class="wband-h">${label(b)} · ${g.length}</div>
      <div class="wband-words">${g.map((l) =>
        `<span class="w st-${stOf(l)}" data-l="${esc(l)}">${esc(lemmaLabel(l))}</span>`).join("")}</div></div>` : "").join("");
  for (const w of $("words-list").querySelectorAll(".w")) {
    w.onclick = (ev) => {
      ev.stopPropagation();
      openPopup(first[w.dataset.l], w.dataset.l, w, true);
    };
    w.oncontextmenu = (ev) => {
      ev.preventDefault();
      const st = stOf(w.dataset.l);
      setStatus(w.dataset.l, st === "known" ? "unknown" : "known");
    };
  }
}

$("vocab-level-btn").onclick = () => $("level-dlg").showModal();
$("level-n").oninput = () => { $("level-val").textContent = $("level-n").value; };
$("level-dlg").addEventListener("close", async () => {
  if ($("level-dlg").returnValue !== "ok") return;
  toast("⏳ Marcando vocabulario…");
  const r = await api("/api/words/bulk-known", {
    method: "POST",
    body: JSON.stringify({ top_n: parseInt($("level-n").value, 10) }),
  });
  toast(`${r.marked} palabras marcadas como conocidas`, "ok");
  if (SESSION) {
    const s = await api("/api/sessions/" + SESSION.id);
    STATUS = s.word_statuses || {};
    renderSegs(); renderOverlay(); updateComp();
  }
});

// ---------- recomendadas i+1 ----------
// frase óptima para minar = exactamente 1 lema desconocido (estilo Migaku)
function segNewLemmas(seg) {
  const s = new Set();
  for (const t of (seg.tokens || []))
    if (t.is_word && t.lemma && stOf(t.lemma) === "unknown") s.add(t.lemma);
  return s.size;
}

// nivel de recomendación: 1 = i+1 (una palabra nueva, óptima, verde) ·
// 2 = i+2 (dos nuevas, buena, azul) · 0 = no recomendada
function segRecTier(seg) {
  const n = segNewLemmas(seg);
  return n === 1 ? 1 : n === 2 ? 2 : 0;
}

function updateRecs() {
  RECS = [];
  SEGS.forEach((seg, i) => { if (segNewLemmas(seg) === 1) RECS.push(i); });
  const chip = $("rec-chip");
  if (!SEGS.length || !RECS.length) chip.hidden = true;
  else { chip.innerHTML = `<svg class="ic ic-xs"><use href="#i-star"/></svg>${RECS.length} recomendadas`; chip.hidden = false; }
  // filas del navegador de subtítulos: verde (i+1) / azul (i+2)
  document.querySelectorAll(".seg.rec-1, .seg.rec-2")
    .forEach((d) => d.classList.remove("rec-1", "rec-2"));
  SEGS.forEach((seg, i) => {
    const tier = segRecTier(seg);
    if (tier) $("seg-" + i)?.classList.add("rec-" + tier);
  });
  // re-resaltar la línea en vivo por si cambió el estado de una palabra
  if (CUR >= 0 && SEGS[CUR]) {
    const t = segRecTier(SEGS[CUR]);
    $("overlay-ca").classList.toggle("rec-1", t === 1);
    $("overlay-ca").classList.toggle("rec-2", t === 2);
  }
}

function nextRec() {
  if (!RECS.length) { toast("No hay frases i+1 ahora mismo", "err"); return; }
  const t = V.currentTime;
  const nxt = RECS.find((i) => SEGS[i].start > t + 0.05) ?? RECS[0];
  gotoSeg(nxt);
}
$("rec-chip").onclick = () => nextRec();

// ---------- init ----------
loadSettings();
loadSessions();
refreshAnki();
