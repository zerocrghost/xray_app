// X-Ray Analyzer UI. Talks to Python through `pywebview.api` (see app.py).
"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

const state = {
  ready: false,      // model loaded
  busy: false,       // a Python call is running
  image: null,       // {info, preview}
  result: null,      // {scores, preprocess_ms, inference_ms, ...}
  labels: [],
  bands: { high: 0.5, moderate: 0.3 },
  sort: "score",
};

// ------------------------------------------------------------------ helpers
const pct = (s) => (s * 100).toFixed(1) + "%";
const band = (s) => (s >= state.bands.high ? "high" : s >= state.bands.moderate ? "moderate" : "low");

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast" + (isError ? " err" : "")), isError ? 6000 : 3000);
}

function setStatus(kind, text) {
  const s = $("stState");
  s.className = kind;
  s.textContent = "● " + text;
}

function setChip(kind, text) {
  $("modelChip").className = "chip " + kind;
  $("modelChip").querySelector("span").textContent = text;
}

function updateButtons() {
  const idle = state.ready && !state.busy;
  $("btnUpload").disabled = !idle;
  $("btnAnalyze").disabled = !idle || !state.image;
  $("btnClear").disabled = !idle || !state.image;
  $("btnExport").disabled = !idle || !state.result;
  $("device").disabled = !idle;
  for (const id of ["zoomIn", "zoomOut", "fit", "invert"]) $(id).disabled = !state.image;
}

// Wraps every Python call: busy flag, buttons, error toast.
async function call(fn, busyText) {
  state.busy = true;
  updateButtons();
  if (busyText) setStatus("busy", busyText);
  try {
    const r = await fn();
    if (r && r.ok === false) throw new Error(r.error);
    return r;
  } catch (e) {
    toast(e.message || String(e), true);
    setStatus("err", "Error");
    return null;
  } finally {
    state.busy = false;
    updateButtons();
  }
}

// ------------------------------------------------------------------ results panel
function renderResults() {
  const box = $("summaryBox");
  box.replaceChildren();
  const scores = state.result && state.result.scores;

  if (state.busy && state.image && !scores) {
    const p = el("div", "placeholder");
    p.append(el("div", "spinner"), el("span", null, "Analyzing image…"));
    box.append(p);
  } else if (!scores) {
    const p = el("div", "placeholder");
    p.append(el("span", null, state.image
      ? "Image loaded. Press Start Analysis to compute the probabilities."
      : "Upload a chest X-ray to begin."));
    box.append(p);
  } else {
    const shown = state.labels.map((l) => [l, scores[l]]).sort((a, b) => b[1] - a[1]);
    const highs = shown.filter(([, s]) => band(s) === "high");
    const mods = shown.filter(([, s]) => band(s) === "moderate");
    const level = highs.length ? "high" : mods.length ? "moderate" : "low";
    const list = (arr) => arr.map(([l, s]) => `${l} (${pct(s)})`).join(" · ");
    const hp = Math.round(state.bands.high * 100), mp = Math.round(state.bands.moderate * 100);
    const [title, detail] = highs.length
      ? [`${highs.length} finding${highs.length > 1 ? "s" : ""} at or above ${hp}%`, list(highs) + " — review recommended"]
      : mods.length
        ? [`No high findings · ${mods.length} moderate`, list(mods)]
        : [`No findings above ${mp}%`, "All 11 pathologies are in the low range"];
    const colors = { high: "#ff7b78", moderate: "#ffc066", low: "#5fd3a0" };
    const icons = {
      high: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
      moderate: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
      low: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    };
    const s = el("div", "summary " + level);
    const ic = el("div", "ic");
    ic.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${colors[level]}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${icons[level]}</svg>`;
    const txt = el("div");
    txt.append(el("b", null, title), el("span", null, detail));
    s.append(ic, txt);
    box.append(s);
  }

  // rows
  const rows = $("rows");
  rows.replaceChildren();
  let order = [...state.labels];
  if (scores && state.sort === "score") order.sort((a, b) => scores[b] - scores[a]);
  else order.sort((a, b) => a.localeCompare(b));
  const bars = [];
  for (const label of order) {
    const s = scores ? scores[label] : null;
    const r = el("div", "row " + (s === null ? "pending" : band(s)));
    const bar = el("div", "bar");
    const fill = el("i");
    bar.append(fill);
    r.append(el("span", "n", label.replace("_", " ")), bar,
             el("span", "p", s === null ? "—" : pct(s)),
             el("span", "tag", s === null ? "—" : band(s).toUpperCase()));
    rows.append(r);
    if (s !== null) bars.push([fill, s]);
  }
  requestAnimationFrame(() => bars.forEach(([f, s]) => (f.style.width = (s * 100).toFixed(1) + "%")));

  $("timing").textContent = state.result
    ? `Preprocess ${Math.round(state.result.preprocess_ms)} ms · Inference ${Math.round(state.result.inference_ms)} ms`
    : "";
}

// ------------------------------------------------------------------ image viewer
const view = { scale: 1, fit: 1, x: 0, y: 0, w: 0, h: 0, inverted: false };

function applyView() {
  const img = $("img");
  img.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  $("ovTR").textContent = state.image
    ? `ZOOM ${Math.round(view.scale / view.fit * 100)}%` + (view.inverted ? "\nINVERTED" : "")
    : "";
}

function fitView() {
  if (!state.image) return;
  const v = $("viewer").getBoundingClientRect();
  view.fit = Math.min(v.width / view.w, v.height / view.h);
  view.scale = view.fit;
  view.x = (v.width - view.w * view.scale) / 2;
  view.y = (v.height - view.h * view.scale) / 2;
  applyView();
}

function zoomAt(factor, cx, cy) {
  if (!state.image) return;
  const v = $("viewer").getBoundingClientRect();
  if (cx === undefined) { cx = v.width / 2; cy = v.height / 2; }
  const next = Math.min(Math.max(view.scale * factor, view.fit * 0.5), view.fit * 10);
  const k = next / view.scale;
  view.x = cx - (cx - view.x) * k;
  view.y = cy - (cy - view.y) * k;
  view.scale = next;
  applyView();
}

function showImage(data) {
  state.image = data;
  state.result = null;
  const info = data.info;
  const img = $("img");
  img.onload = () => {
    view.w = img.naturalWidth;
    view.h = img.naturalHeight;
    img.hidden = false;
    $("empty").hidden = true;
    fitView();
  };
  img.src = data.preview;

  const tl = [`FILE   ${info.file}`];
  if (info.study_date) tl.push(`STUDY  ${info.study_date}`);
  if (info.view) tl.push(`VIEW   ${info.view}`);
  $("ovTL").textContent = tl.join("\n");
  $("ovBL").textContent = `${info.width} × ${info.height} px`;
  $("viewSub").textContent = info.view ? `· ${info.view} view` : "";

  const meta = $("metabar");
  meta.replaceChildren();
  for (const [k, v] of [["File", info.file], ["Size", info.size_mb + " MB"], ["Format", info.format],
                        ["Input", "224 × 224 (center-crop)"]]) {
    const s = el("span", null, k);
    s.append(el("b", null, v));
    meta.append(s);
  }
  $("stFile").textContent = info.file;
  setStatus("ok", "Image loaded");
  renderResults();
  updateButtons();
}

function clearImage() {
  state.image = null;
  state.result = null;
  view.inverted = false;
  const img = $("img");
  img.hidden = true;
  img.removeAttribute("src");
  img.classList.remove("inverted");
  $("invert").classList.remove("on");
  $("empty").hidden = false;
  for (const id of ["ovTL", "ovTR", "ovBL", "viewSub", "stFile"]) $(id).textContent = "";
  const meta = $("metabar");
  meta.replaceChildren();
  for (const k of ["File", "Size", "Format"]) {
    const s = el("span", null, k);
    s.append(el("b", null, "—"));
    meta.append(s);
  }
  const s = el("span", null, "Input");
  s.append(el("b", null, "224 × 224 (center-crop)"));
  meta.append(s);
  setStatus("ok", "Ready");
  renderResults();
  updateButtons();
}

// pan with the mouse, zoom with the wheel
(function setupViewer() {
  const v = $("viewer");
  let drag = null;
  v.addEventListener("mousedown", (e) => {
    if (!state.image || e.button !== 0) return;
    drag = { x: e.clientX - view.x, y: e.clientY - view.y };
    v.classList.add("dragging");
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    view.x = e.clientX - drag.x;
    view.y = e.clientY - drag.y;
    applyView();
  });
  window.addEventListener("mouseup", () => { drag = null; v.classList.remove("dragging"); });
  v.addEventListener("wheel", (e) => {
    if (!state.image) return;
    e.preventDefault();
    const r = v.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  v.addEventListener("dblclick", fitView);
  window.addEventListener("resize", fitView);
})();

// ------------------------------------------------------------------ actions
async function uploadImage() {
  if (!state.ready || state.busy) return;
  const r = await call(() => api().open_image(), "Opening image…");
  if (r && !r.cancelled) showImage(r);
  else if (r && r.cancelled) setStatus("ok", state.image ? "Image loaded" : "Ready");
}

async function analyze() {
  if (!state.ready || state.busy || !state.image) return;
  state.result = null;
  state.busy = true;           // so renderResults shows the spinner
  renderResults();
  const r = await call(() => api().analyze(), "Analyzing…");
  if (r) {
    state.result = r;
    setStatus("ok", "Analysis complete");
  }
  renderResults();
  updateButtons();
}

async function exportReport() {
  if (!state.result || state.busy) return;
  const r = await call(() => api().export_report(), "Exporting…");
  if (r && !r.cancelled) toast("Report saved: " + r.path);
  setStatus(r ? "ok" : "err", r ? "Analysis complete" : "Export failed");
}

async function clearAll() {
  if (state.busy) return;
  await api().clear();
  clearImage();
}

async function changeDevice(e) {
  const prev = state.device;
  const r = await call(() => api().set_device(e.target.value), "Switching device…");
  if (r) {
    state.device = r.device;
    toast("Device: " + e.target.selectedOptions[0].textContent + (state.result ? " — run the analysis again to use it" : ""));
  } else {
    e.target.value = prev;
  }
  setStatus("ok", state.result ? "Analysis complete" : state.image ? "Image loaded" : "Ready");
}

$("btnUpload").onclick = uploadImage;
$("btnAnalyze").onclick = analyze;
$("btnExport").onclick = exportReport;
$("btnClear").onclick = clearAll;
$("btnExit").onclick = () => api().exit();
$("zoomIn").onclick = () => zoomAt(1.25);
$("zoomOut").onclick = () => zoomAt(1 / 1.25);
$("fit").onclick = fitView;
$("invert").onclick = () => {
  view.inverted = !view.inverted;
  $("img").classList.toggle("inverted", view.inverted);
  $("invert").classList.toggle("on", view.inverted);
  applyView();
};
$("device").onchange = changeDevice;
$("sortSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.sort = b.dataset.sort;
  for (const x of $("sortSeg").children) x.classList.toggle("on", x === b);
  renderResults();
});

document.addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase();
  if (e.ctrlKey && k === "o") { e.preventDefault(); uploadImage(); }
  else if (e.ctrlKey && k === "r") { e.preventDefault(); analyze(); }      // also blocks page reload
  else if (e.ctrlKey && k === "s") { e.preventDefault(); exportReport(); }
  else if (e.key === "F5") e.preventDefault();
  else if (!e.ctrlKey && (k === "+" || k === "=")) zoomAt(1.25);
  else if (!e.ctrlKey && k === "-") zoomAt(1 / 1.25);
  else if (!e.ctrlKey && k === "0") fitView();
  else if (!e.ctrlKey && k === "i" && state.image) $("invert").click();
});
document.addEventListener("contextmenu", (e) => e.preventDefault());

// ------------------------------------------------------------------ start-up
async function start() {
  renderResults();
  setStatus("busy", "Loading model…");
  const r = await api().init();
  if (!r.ok) {
    setChip("err", "Model failed to load");
    setStatus("err", "Model failed to load");
    toast(r.error, true);
    return;
  }
  state.ready = true;
  state.labels = r.shown_labels;
  state.bands = r.bands;
  state.device = r.device;
  $("modelName").textContent = r.model;
  $("stModel").textContent = r.model;
  $("stVersion").textContent = r.versions;
  $("disclaimer").textContent = r.disclaimer;
  $("lgHigh").textContent = Math.round(r.bands.high * 100);
  $("lgMod").textContent = Math.round(r.bands.moderate * 100);
  const sel = $("device");
  sel.replaceChildren(...r.devices.map((d) => {
    const o = el("option", null, d.name);
    o.value = d.id;
    o.selected = d.id === r.device;
    return o;
  }));
  setChip("ok", "Model loaded");
  setStatus("ok", "Ready");
  renderResults();
  updateButtons();
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start);
