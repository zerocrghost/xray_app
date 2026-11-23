// PneumoLens AI UI. Talks to Python through `pywebview.api` (see app.py).
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
  exported: false,   // current result has been saved with Export Report
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
  for (const id of ["modelChip", "landChip"]) {
    $(id).className = "chip " + kind;
    $(id).querySelector("span").textContent = text;
  }
}

// ------------------------------------------------------------------ pages (landing <-> workspace)
const onLanding = () => document.body.classList.contains("landing-on");

function showWorkspace() {
  if (!onLanding()) return;
  document.body.classList.remove("landing-on");
  fitView();                    // the viewer had no size while hidden
}

function showLanding() {
  if (state.busy) return;
  document.body.classList.add("landing-on");
}

// workspace pages: 0 = patient, 1 = X-ray analysis, 2 = symptoms & labs, 3 = final report
let step = 1;

const canReport = () => !!state.result || Clinical.hasInput();

function showStep(n) {
  if (state.busy || (n > 1 && !state.ready) || (n === 3 && !canReport())) return;
  showWorkspace();
  step = n;
  for (const k of [0, 1, 2, 3]) $("page" + k).hidden = n !== k;
  if (n === 1) fitView();
  else if (n === 2) Clinical.renderLeft();
  else if (n === 3) Patient.summary();
  renderStepper();
  updateButtons();
  if (n === 3) Report.open();       // recomputed from the current step-1 and step-2 data
}

function renderStepper() {
  const s0 = $("step0"), s1 = $("step1"), s2 = $("step2"), s3 = $("step3");
  const done0 = Patient.hasIdentity();
  const done1 = !!state.result, done2 = Clinical.hasResult(), done3 = Report.ready() && !Report.unsaved();
  s0.className = "step" + (step === 0 ? " active" : done0 ? " done" : "");
  s0.querySelector(".num").textContent = step !== 0 && done0 ? "✓" : "1";
  $("stepLine0").classList.toggle("done", done0);
  s0.title = step === 0 ? "" : "Patient information";
  s1.className = "step" + (step === 1 ? " active" : done1 ? " done" : "");
  s2.className = "step" + (step === 2 ? " active" : done2 ? " done" : "");
  s3.className = "step" + (step === 3 ? " active" : done3 ? " done" : "");
  s1.querySelector(".num").textContent = step !== 1 && done1 ? "✓" : "2";
  s2.querySelector(".num").textContent = step !== 2 && done2 ? "✓" : "3";
  s3.querySelector(".num").textContent = step !== 3 && done3 ? "✓" : "4";
  $("stepLine1").classList.toggle("done", done1);
  $("stepLine2").classList.toggle("done", done2);
  s3.title = canReport() ? (step === 3 ? "" : "Final report") : "Analyze an X-ray or enter clinical data first";
  if (state.result) {
    const n = state.labels.filter((l) => band(state.result.scores[l]) === "high").length;
    $("step1Sub").textContent = n ? `${n} finding${n > 1 ? "s" : ""} flagged` : "No high findings";
  } else {
    $("step1Sub").textContent = "Image · 11 pathologies";
  }
  s1.title = step === 1 ? "" : "Back to the X-ray analysis";
  s2.title = step === 2 ? "" : "Symptoms, vital signs and lab data";
}

function updateButtons() {
  const idle = state.ready && !state.busy;
  $("btnUpload").disabled = !idle;
  $("btnLandOpen").disabled = !idle;
  $("empty").classList.toggle("disabled", !idle);
  $("btnAnalyze").disabled = !idle || !state.image;
  $("btnClear").disabled = !idle || !state.image;
  const canExport = idle && (!!state.result || Clinical.hasResult());
  $("btnExport").disabled = !canExport;
  $("device").disabled = !idle;
  for (const id of ["zoomIn", "zoomOut", "fit", "invert"]) $(id).disabled = !state.image;
  // step 2
  $("btnNext").disabled = !idle;
  $("step2").disabled = !idle;
  $("step1").disabled = state.busy;
  $("btnImport").disabled = !idle;
  $("btnRun").disabled = !idle || !Clinical.hasInput();
  $("btnCClear").disabled = !idle || !(Clinical.hasInput() || Clinical.hasResult());
  $("btnCExport").disabled = !canExport;
  // step 3
  $("btnNext2").disabled = !idle || !canReport();
  $("step3").disabled = !idle || !canReport();
  $("btnSave").disabled = !idle || !Report.ready();
  $("btnNewPatient").disabled = state.busy;
  $("btnBack3").disabled = state.busy;
  // patient page / saved cases
  for (const id of ["btnLandCase", "btnOpenCase0", "btnOpenCase3"]) $(id).disabled = !idle;
  $("btnNewPatient0").disabled = state.busy;
  $("step0").disabled = state.busy;
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
    const icons = {
      high: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
      moderate: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
      low: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    };
    const s = el("div", "summary " + level);
    const ic = el("div", "ic");
    ic.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${icons[level]}</svg>`;
    const txt = el("div");
    const d = el("span", null, detail);
    d.title = detail;
    txt.append(el("b", null, title), d);
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
  if (!state.image || onLanding() || $("page1").hidden) return;
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
    $("viewer").classList.add("has-img");
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
    s.title = v;                // full value on hover when it is cut off
    meta.append(s);
  }
  $("stFile").textContent = info.file;
  setStatus("ok", "Image loaded");
  renderResults();
  renderStepper();
  Clinical.xrayChanged();       // the old X-ray scores no longer apply
  updateButtons();
}

function restoreXray(x) {
  if (x.preview) showImage({ info: x.info, preview: x.preview });
  if (x.result) {
    state.result = x.result;
    state.exported = true;
    $("stFile").textContent = (x.info && x.info.file) || x.result.file || "";
    setStatus("ok", "Saved case opened");
    renderResults();
    renderStepper();
    Clinical.xrayChanged();
    updateButtons();
  }
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
  $("viewer").classList.remove("has-img");
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
  renderStepper();
  Clinical.xrayChanged();
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
  if (r && !r.cancelled) { showWorkspace(); showImage(r); }
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
    state.exported = false;
    setStatus("ok", "Analysis complete");
  }
  renderResults();
  renderStepper();
  if (r) Clinical.xrayChanged();
  updateButtons();
}

async function exportReport() {
  if (!(state.result || Clinical.hasResult()) || state.busy) return;
  const r = await call(() => api().export_report(), "Exporting…");
  if (r && !r.cancelled) { state.exported = true; toast("Report saved: " + r.path); }
  setStatus(r ? "ok" : "err", r ? "Report ready" : "Export failed");
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

// ------------------------------------------------------------------ theme (dark / light)
const theme = () => document.documentElement.dataset.theme;

function setTheme(t, save = true) {
  document.documentElement.dataset.theme = t;
  const next = t === "light" ? "dark" : "light";
  for (const b of document.querySelectorAll(".theme-btn")) b.title = `Switch to ${next} theme (Ctrl+T)`;
  if (save && window.pywebview && window.pywebview.api) api().set_theme(t);   // remembered for the next start
}

function toggleTheme() { setTheme(theme() === "light" ? "dark" : "light"); }

for (const b of document.querySelectorAll(".theme-btn")) b.onclick = toggleTheme;
setTheme(theme(), false);

// ------------------------------------------------------------------ exit confirmation
// ------------------------------------------------------------------ settings dialog
const settingsOpen = () => !$("setModal").hidden;
const SET_DEFAULTS = { candidate_ratio: 0.5, max_candidates: 3 };

function settingsExample() {
  const ratio = +$("setRatio").value / 100, max = Math.min(7, Math.max(1, parseInt($("setMax").value, 10) || 1));
  $("setRatioVal").textContent = Math.round(ratio * 100) + "%";
  // the current report's scores if there is one, else an illustration
  const list = Report.ready() ? Report.scores() : [["Pneumonia", 0.72], ["Lung Abscess", 0.66], ["Bronchiectasis", 0.41], ["COPD", 0.30]];
  const cut = list[0][1] * ratio;
  const parts = list.map(([n, m], i) => {
    const shown = i === 0 || (i < max && m >= cut && list.slice(1, i).every(([, x]) => x >= cut));
    return `<span class="${shown ? "in" : "out"}">${n} ${Math.round(m * 100)}%</span>`;
  });
  $("setExample").innerHTML = `${Report.ready() ? "Current report" : "Example"}: cut-off ${Math.round(cut * 100)}% → ` + parts.join(" · ");
}

function showDatasetPath(r) {
  const el2 = $("setDatasetPath");
  el2.className = "s-path";
  el2.textContent = r && r.dataset_path ? "→ " + r.dataset_path : "";
}

function showWeightsInfo(w) {
  const box = $("setWeights");
  box.className = "s-weights" + (w && w.warning ? " err" : "");
  if (!w) { box.textContent = "not loaded"; $("setEditWeights").disabled = true; return; }
  $("setEditWeights").disabled = !Clinical.ready();
  box.textContent = w.warning ? w.warning
    : w.edits ? `${w.label} · ${w.edits} item${w.edits === 1 ? "" : "s"} in ${w.diseases} disease${w.diseases === 1 ? "" : "s"} changed`
    : `${w.label} as shipped (no edits)`;
  box.title = box.textContent;
}

async function openSettings() {
  const r = await api().get_settings();
  $("setRatio").value = Math.round((r.candidate_ratio ?? 0.5) * 100);
  $("setMax").value = r.max_candidates ?? 3;
  $("setDataset").value = r.dataset_dir || r.dataset_default || "./dataset";
  $("setHospital").value = r.hospital || "";
  showWeightsInfo(r.weights);
  showDatasetPath(r);
  settingsExample();
  $("setModal").hidden = false;
  $("setRatio").focus();
}

function closeSettings() { $("setModal").hidden = true; }

async function saveSettings() {
  const r = await api().set_settings({ candidate_ratio: +$("setRatio").value / 100, max_candidates: +$("setMax").value,
                                      dataset_dir: $("setDataset").value.trim(), hospital: $("setHospital").value.trim() });
  if (!r.ok) {                                         // e.g. a dataset folder that cannot be written
    $("setDatasetPath").className = "s-path err";
    $("setDatasetPath").textContent = r.error;
    toast(r.error, true);
    return;
  }
  closeSettings();
  Patient.setHospitalDefault(r.hospital);
  toast(`Settings saved · candidates ≥ ${Math.round(r.candidate_ratio * 100)}% of the top, at most ${r.max_candidates} · ` +
        `case data → ${r.dataset_path}`);
  if (step === 3) Report.open();                     // apply to the open report right away
}

$("btnSettings").onclick = openSettings;
$("setClose").onclick = closeSettings;
$("setCancel").onclick = closeSettings;
$("setSave").onclick = saveSettings;
$("setReset").onclick = () => {
  $("setRatio").value = SET_DEFAULTS.candidate_ratio * 100;
  $("setMax").value = SET_DEFAULTS.max_candidates;
  // the dataset folder and the hospital are NOT reset here: the storage location only changes when set explicitly
  settingsExample();
};
$("setBrowse").onclick = async () => {
  const r = await api().browse_folder();
  if (r && r.ok && !r.cancelled) { $("setDataset").value = r.path; showDatasetPath({ dataset_path: r.path }); }
};
$("setOpenDs").onclick = async () => {
  const r = await api().open_dataset_folder();
  if (r && !r.ok) toast(r.error, true);
};
$("setEditWeights").onclick = () => {
  // the other settings in this dialog are not saved by this button: Save them first if they were changed
  closeSettings();
  Clinical.openWeights(null, true);
};
$("setRatio").addEventListener("input", settingsExample);
$("setMax").addEventListener("input", settingsExample);
$("setModal").addEventListener("mousedown", (e) => { if (e.target === e.currentTarget) closeSettings(); });

// one confirmation dialog for Exit and New Patient
const exitOpen = () => !$("exitModal").hidden;
let modalAction = null;

function confirmBox({ title, text, ok, onOk }) {
  $("exitTitle").textContent = title;
  $("exitText").textContent = text;
  $("exitConfirm").firstChild.textContent = ok;
  modalAction = onOk;
  $("exitModal").hidden = false;
  $("exitConfirm").focus();
}

async function openExitModal() {
  if (!$("exitModal").hidden) return;
  const st = await Case.status();
  const exitNow = async (force) => {
    const r = await api().exit(!!force);
    if (r && r.ok === false) {
      confirmBox({ title: "Could not save the case data", ok: "Exit anyway",
        text: `${r.error} The app did NOT close. Exit anyway? The data of this case will be lost.`,
        onOk: () => exitNow(true) });
    }
  };
  if (st.has_data) {
    confirmBox({
      title: "Exit PneumoLens AI?",
      text: st.reports.length
        ? "The case data is saved to the dataset folder automatically."
        : "The report has not been saved. Exit without saving the report? The case data is saved to the dataset folder automatically.",
      ok: "Exit",
      onOk: () => exitNow(false),
    });
    return;
  }
  confirmBox({ title: "Exit PneumoLens AI?", text: "Are you sure you want to close the application?", ok: "Exit",
               onOk: () => exitNow(false) });
}


function closeExitModal() {
  $("exitModal").hidden = true;
}

for (const b of document.querySelectorAll("[data-exit]")) b.onclick = openExitModal;
$("exitCancel").onclick = () => { closeExitModal(); api().close_cancelled(); };
$("exitConfirm").onclick = () => { const f = modalAction; closeExitModal(); if (f) f(); };
$("exitModal").addEventListener("mousedown", (e) => { if (e.target === e.currentTarget) closeExitModal(); });

// empty image panel: click (or Enter / Space when focused) opens the file dialog
$("empty").addEventListener("click", () => {
  if (!state.image && !$("empty").classList.contains("disabled")) uploadImage();   // only while no image is shown
});
$("empty").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); $("empty").click(); }
});

$("btnStart").onclick = () => showStep(0);
$("btnNext0").onclick = () => showStep(1);
$("step0").onclick = () => showStep(0);
$("btnLandCase").onclick = () => Case.open();
$("btnOpenCase0").onclick = () => Case.open();
$("btnNewPatient0").onclick = () => Case.newPatient();
$("btnLandOpen").onclick = uploadImage;
$("btnHome").onclick = showLanding;
$("btnUpload").onclick = uploadImage;
$("btnAnalyze").onclick = analyze;
$("btnExport").onclick = exportReport;
$("btnCExport").onclick = exportReport;
$("btnNext").onclick = () => showStep(2);
$("step1").onclick = () => showStep(1);
$("step2").onclick = () => showStep(2);
$("step3").onclick = () => showStep(3);
$("btnNext2").onclick = () => showStep(3);
$("btnClear").onclick = clearAll;
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
  if (exitOpen()) {             // modal: Esc cancels, Enter exits, everything else is blocked
    if (e.key === "Escape") closeExitModal();
    else if (e.key === "Enter") {  // Enter presses the focused button (Exit by default)
      document.activeElement === $("exitCancel") ? closeExitModal() : $("exitConfirm").click();
    }
    else if (e.key === "Tab") {  // keep focus inside the dialog
      e.preventDefault();
      ($("exitConfirm") === document.activeElement ? $("exitCancel") : $("exitConfirm")).focus();
      return;
    }
    e.preventDefault();
    return;
  }
  if (settingsOpen()) {         // settings: Esc cancels, Enter saves
    if (e.key === "Escape") closeSettings();
    else if (e.key === "Enter") { e.preventDefault(); saveSettings(); }
    if ((e.ctrlKey && "rsop".includes(k)) || e.key === "F5") e.preventDefault();
    return;
  }
  if (Clinical.modalOpen()) {   // weighting table: Esc closes it (not with unsaved edits), Ctrl+S saves edits
    if (e.key === "Escape") Clinical.closeWeights();
    else if (e.ctrlKey && k === "s" && Clinical.editingWeights()) Clinical.saveWeights();
    else if (e.key === "Enter" && e.target.matches && e.target.matches("input.w-n")) e.target.blur();
    if ((e.ctrlKey && "rso".includes(k)) || e.key === "F5") e.preventDefault();
    return;
  }
  if (e.ctrlKey && k === "t") { e.preventDefault(); toggleTheme(); return; }
  if (onLanding()) {            // landing page: only Enter (start) and Ctrl+O (open) do something
    if (e.key === "Enter" && !e.ctrlKey) { e.preventDefault(); showStep(0); }
    else if (e.ctrlKey && k === "o") { e.preventDefault(); uploadImage(); }
    else if ((e.ctrlKey && (k === "r" || k === "s")) || e.key === "F5") e.preventDefault();
    return;
  }
  if (e.ctrlKey && k === "p") { e.preventDefault(); return; }                  // no printing of the app window
  if (step === 0) {             // patient page: typing stays normal
    if ((e.ctrlKey && "rso".includes(k)) || e.key === "F5") e.preventDefault();
    return;
  }
  if (step === 3) {             // final report: typing in the fields stays normal
    if (e.ctrlKey && k === "s") { e.preventDefault(); Report.save(); }
    else if ((e.ctrlKey && (k === "r" || k === "o")) || e.key === "F5") e.preventDefault();
    return;
  }
  if (step === 2) {             // symptoms & labs
    if (e.ctrlKey && k === "o") { e.preventDefault(); Clinical.importFile(); }
    else if (e.ctrlKey && k === "r") { e.preventDefault(); Clinical.run(); }
    else if (e.ctrlKey && k === "s") { e.preventDefault(); exportReport(); }
    else if (e.key === "F5") e.preventDefault();
    return;
  }
  if (e.target.matches && e.target.matches("input, select")) {
    if (e.ctrlKey && "ors".includes(k)) e.preventDefault(); else return;
  }
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
    $("btnLandOpen").disabled = true;
    setChip("err", "Model failed to load");
    setStatus("err", "Model failed to load");
    toast(r.error, true);
    return;
  }
  state.ready = true;
  Clinical.init(r.clinical);
  if (r.weights_warning) toast(r.weights_warning, true);    // stored weight edits no longer fit weight.json
  try { Patient.init(await api().get_settings()); } catch (e) { Patient.init({}); }
  state.labels = r.shown_labels;
  state.bands = r.bands;
  state.device = r.device;
  $("modelName").textContent = r.model;
  $("landModel").textContent = r.model;
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
  renderStepper();
  updateButtons();
}

// start once every script (clinical.js too) has run and the Python bridge exists
function boot() {
  if (window.pywebview && window.pywebview.api) start();
  else window.addEventListener("pywebviewready", start, { once: true });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
