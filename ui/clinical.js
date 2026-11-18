// PneumoLens AI - step 2: symptoms, history & exposure, auscultation, vital signs, labs, spirometry.
// The form and the weighting table are built from models/weight.json (sent by app.py in init()),
// so changing the JSON changes the page. Scoring runs in Python (clinical_engine.py).
// Uses the helpers of app.js: $, el, api, call, state, toast, setStatus, updateButtons.
"use strict";

const Clinical = (() => {
  let T = null;              // weight table (features, diseases, groups, method)
  let result = null;         // last analyze_clinical() result
  let selected = null;       // disease id whose factors are shown
  let running = false;
  let rerunTimer = null;
  const yesNo = {};          // symptom id -> true / false (missing = not asked)
  const picks = {};          // option inputs (auscultation, exposure, duration): id -> Set of chosen keys

  const ORDER = ["symptom", "history", "auscultation", "vital", "lab", "spirometry"];
  const SRC = { symptom: "SYMPTOM", history: "HISTORY", auscultation: "AUSC", vital: "VITAL", lab: "LAB", spirometry: "SPIRO", xray: "X-RAY" };
  const pctTxt = (x) => Math.round(x * 100) + "%";
  const level = (m) => (m >= 0.65 ? "high" : m >= 0.45 ? "moderate" : "low");
  const fmt = (x) => (x === null || x === undefined ? "" : String(+(+x).toFixed(2)));

  // ---------------------------------------------------------------- form
  function featuresOf(cat) {
    return Object.entries(T.features).filter(([, f]) => f.category === cat);
  }

  function section(title, cat, extra) {
    const s = el("div", "cs");
    s.dataset.cat = cat;
    const h = el("div", "cs-h");
    h.append(el("span", null, title), el("span", "cnt"));
    if (extra) h.append(el("div", "spacer"), extra);
    s.append(h);
    return s;
  }

  // chips for an option input (auscultation, exposure, duration). f.single = one choice only;
  // f.exclusive = an option such as "normal" / "none" that clears the others.
  function optionChips(id, f) {
    if (!picks[id]) picks[id] = new Set();
    const chips = el("div", "chips");
    for (const [k, label] of Object.entries(f.sounds)) {
      const c = el("button", "c", label);
      c.dataset.pick = `${id}:${k}`;
      if (id === "auscultation") c.dataset.snd = k;
      c.onclick = () => {
        const set = picks[id];
        if (set.has(k)) set.delete(k);
        else {
          if (f.single || k === f.exclusive) set.clear();
          else if (f.exclusive) set.delete(f.exclusive);
          set.add(k);
        }
        syncChips(); changed();
      };
      chips.append(c);
    }
    return chips;
  }

  function buildForm() {
    const form = $("cForm");
    form.replaceChildren();
    for (const cat of ORDER) {
      const feats = featuresOf(cat);
      if (!feats.length) continue;
      if (cat === "symptom") {
        const rest = el("button", "lnk", "Unmarked → No");
        rest.title = "Mark every symptom that is not ticked as absent";
        rest.onclick = () => { for (const [id] of feats) if (yesNo[id] === undefined) yesNo[id] = false; syncChips(); changed(); };
        const s = section("Symptoms", cat, rest);
        const chips = el("div", "chips");
        for (const [id, f] of feats) {
          const c = el("button", "c", f.label);
          c.dataset.sym = id;
          c.title = `${f.hint}\nClick: yes → no → not asked`;
          c.onclick = () => {
            yesNo[id] = yesNo[id] === undefined ? true : yesNo[id] === true ? false : undefined;
            if (yesNo[id] === undefined) delete yesNo[id];
            syncChips(); changed();
          };
          chips.append(c);
        }
        s.append(chips, el("div", "cs-note", "Click once for present (✓), twice for absent (✕), three times to clear. Symptoms left blank are skipped."));
        form.append(s);
      } else if (cat === "auscultation") {
        const [id, f] = feats[0];
        const s = section("Auscultation", cat);
        s.append(optionChips(id, f));
        form.append(s);
      } else if (cat === "history") {
        // history & exposure: option chips (exposure, duration) and number cards (pack-years)
        const s = section(T.categories[cat] || "History & exposure", cat);
        for (const [id, f] of feats) {
          const sub = el("div", "cs-sub");
          const how = f.input !== "sounds" ? "optional · leave blank if unknown" : f.single ? "choose one" : "select all that apply";
          sub.append(el("span", null, f.label), el("span", "cnt", how));
          sub.title = f.hint || "";
          if (f.input === "sounds") s.append(sub, optionChips(id, f));
          else { const grid = el("div", "cgrid"); grid.append(fieldCard(id, f)); s.append(sub, grid); }
        }
        s.append(el("div", "cs-note", "GOLD: COPD is caused by exposure to noxious particles or gases and causes persistent, " +
          "progressive symptoms. Duration classes follow the cough guidelines (acute < 3, subacute 3–8, chronic > 8 weeks)."));
        form.append(s);
      } else {
        const title = T.categories[cat] || cat;
        const s = section(title, cat);
        if (cat === "lab" && T.lab_groups && T.lab_groups.length) {
          // subdivided: inflammation markers / WBC differential / liver function & chemistry
          const placed = new Set();
          for (const g of T.lab_groups) {
            const sub = el("div", "cs-sub");
            sub.dataset.group = g.id;
            sub.title = g.why;
            sub.append(el("span", null, g.title), el("span", "cnt"));
            if (g.sum_to_100) sub.append(el("span", "sum"));
            const grid = el("div", "cgrid");
            for (const id of g.items) if (T.features[id]) { grid.append(fieldCard(id, T.features[id])); placed.add(id); }
            s.append(sub, grid);
          }
          const rest = feats.filter(([id]) => !placed.has(id));
          if (rest.length) {
            const grid = el("div", "cgrid");
            for (const [id, f] of rest) grid.append(fieldCard(id, f));
            s.append(el("div", "cs-sub", "Other"), grid);
          }
        } else {
          const grid = el("div", "cgrid");
          for (const [id, f] of feats) grid.append(fieldCard(id, f));
          s.append(grid);
        }
        if (cat === "lab") {
          s.append(el("div", "cs-note", "All lab values are optional. Leave a field blank if it was not measured: " +
            "blank fields are skipped, never treated as normal or abnormal."));
        }
        if (cat === "spirometry") {
          s.append(el("div", "cs-note", "Optional. FEV1/FVC is calculated from FEV1 and FVC when left empty. " +
            "It is the key test that separates COPD and asthma from the acute infections (see Weights → Method)."));
        }
        form.append(s);
      }
    }
    form.addEventListener("input", (e) => { if (e.target.matches("input")) { validate(e.target.closest(".cf")); changed(); } });
    form.addEventListener("keydown", (e) => {        // Enter moves to the next field
      if (e.key === "Enter" && e.target.matches("input")) {
        e.preventDefault();
        e.stopPropagation();
        const all = [...form.querySelectorAll("input")];
        const next = all[all.indexOf(e.target) + 1];
        if (next) next.focus(); else run();
      }
    });
    syncChips();
    updateCount();
  }

  function refText(f) {
    if (f.ref_text) return "Ref " + f.ref_text;
    if (!f.ref) return "";
    const [lo, hi] = f.ref;
    if (lo === hi) return `Ref ${lo}`;
    return `Ref ${lo}–${hi}`;
  }

  function fieldCard(id, f) {
    const card = el("div", "cf");
    card.dataset.f = id;
    card.title = `${f.label}${f.unit ? " (" + f.unit + ")" : ""}`;
    const top = el("div", "cf-top");
    top.append(el("b", null, f.short || f.label));
    if (f.short && f.short !== f.label) top.append(el("span", "full", f.label));
    top.append(el("span", "st"));
    const box = el("div", "cin");
    const mk = (key) => {
      const i = el("input");
      i.dataset.k = key;
      i.inputMode = "decimal";
      i.autocomplete = "off";
      i.spellcheck = false;
      return i;
    };
    if (f.input === "bp") {
      const a = mk("sbp"), b = mk("dbp");
      a.placeholder = "sys"; b.placeholder = "dia";
      box.append(a, el("span", "sl", "/"), b);
    } else {
      box.append(mk(id));
    }
    box.append(el("span", "u", f.unit || ""));
    card.append(top, box, el("div", "cf-ref", refText(f)));
    return card;
  }

  function num(v) {
    if (v === undefined || v === null) return null;
    const s = String(v).trim().replace(",", ".");
    if (!s) return null;
    const x = Number(s);
    return Number.isFinite(x) ? x : NaN;
  }

  // status of one value: "h" / "l" (out of range, red = the direction that matters for the diseases), "n", "bad"
  function status(f, key, x) {
    const lim = Array.isArray(f.limits) ? f.limits : f.limits && f.limits[key];
    if (Number.isNaN(x) || (lim && (x < lim[0] || x > lim[1]))) return ["bad", "?"];
    const ref = Array.isArray(f.ref) ? f.ref : f.ref && f.ref[key];
    if (!ref) return ["", ""];
    const def = f.patterns[f.default];
    const badLow = def && (def.type === "below" || (def.type === "any"));
    if (x < ref[0]) return [badLow ? "h" : "l", "LOW"];
    if (x > ref[1]) return [badLow ? "l" : "h", "HIGH"];
    return ["n", "NORMAL"];
  }

  function validate(card) {
    if (!card) return;
    const f = T.features[card.dataset.f];
    let cls = "", txt = "", why = "";
    for (const inp of card.querySelectorAll("input")) {
      const x = num(inp.value);
      if (x === null) continue;
      const [c, t] = status(f, inp.dataset.k, x);
      const rank = { bad: 3, h: 2, l: 1, n: 0, "": -1 };
      if (rank[c] > (rank[cls] ?? -1)) { cls = c; txt = t; }
      if (c === "bad") {
        const lim = Array.isArray(f.limits) ? f.limits : f.limits[inp.dataset.k];
        why = `Not a valid value (allowed ${lim[0]}–${lim[1]}) — it will be skipped`;
      }
    }
    card.className = "cf" + (cls ? " " + cls : "");
    const st = card.querySelector(".st");
    st.className = "st" + (cls ? " " + cls : "");
    st.textContent = txt;
    st.title = why;
    if (["fev1", "fvc", "fev1_fvc"].includes(card.dataset.f)) autoRatio();
  }

  function autoRatio() {
    const r = document.querySelector('input[data-k="fev1_fvc"]');
    if (!r) return;
    const a = num(document.querySelector('input[data-k="fev1"]').value);
    const b = num(document.querySelector('input[data-k="fvc"]').value);
    r.placeholder = a > 0 && b > 0 ? `auto ${Math.round((a / b) * 100)}` : "";
  }

  function syncChips() {
    for (const c of document.querySelectorAll("#cForm [data-sym]")) {
      const v = yesNo[c.dataset.sym];
      c.className = "c" + (v === true ? " yes" : v === false ? " no" : "");
      c.setAttribute("aria-pressed", v === true ? "true" : v === false ? "mixed" : "false");
    }
    for (const c of document.querySelectorAll("#cForm [data-pick]")) {
      const [id, k] = c.dataset.pick.split(":");
      c.classList.toggle("yes", !!picks[id] && picks[id].has(k));
    }
  }

  function collect() {
    const out = {};
    for (const [k, v] of Object.entries(yesNo)) out[k] = v;
    for (const [id, set] of Object.entries(picks)) if (set.size) out[id] = [...set];
    for (const i of document.querySelectorAll("#cForm input")) if (i.value.trim()) out[i.dataset.k] = i.value.trim();
    return out;
  }

  function counts() {
    let entered = 0, total = 0, out = 0;
    const per = {};
    for (const [id, f] of Object.entries(T.features)) {
      if (f.category === "xray") continue;
      total++;
      let has = false;
      if (f.input === "bool") has = yesNo[id] !== undefined;
      else if (f.input === "sounds") has = !!picks[id] && picks[id].size > 0;
      else {
        const card = document.querySelector(`#cForm .cf[data-f="${id}"]`);
        has = [...card.querySelectorAll("input")].some((i) => num(i.value) !== null && !Number.isNaN(num(i.value)));
        if (card.classList.contains("h") || card.classList.contains("l")) out++;
      }
      if (has) { entered++; per[f.category] = (per[f.category] || 0) + 1; }
      per["_" + f.category] = (per["_" + f.category] || 0) + 1;
    }
    return { entered, total, out, per };
  }

  function updateCount() {
    const c = counts();
    $("cCount").textContent = `· ${c.entered} of ${c.total} entered` + (c.out ? ` · ${c.out} out of range` : "");
    for (const s of document.querySelectorAll("#cForm .cs")) {
      const cat = s.dataset.cat;
      s.querySelector(".cnt").textContent = `${c.per[cat] || 0} / ${c.per["_" + cat]}`;
    }
    $("step2Sub").textContent = c.entered ? `${c.entered} clinical inputs` : "Clinical data · 7 diseases";
    // lab subgroups: entered count, and the running total of the WBC differential (should be ~100 %)
    for (const sub of document.querySelectorAll("#cForm .cs-sub[data-group]")) {
      const g = T.lab_groups.find((x) => x.id === sub.dataset.group);
      const vals = g.items.map((id) => num(document.querySelector(`#cForm input[data-k="${id}"]`).value))
        .filter((x) => x !== null && !Number.isNaN(x));
      sub.querySelector(".cnt").textContent = `${vals.length} / ${g.items.length}`;
      const sum = sub.querySelector(".sum");
      if (sum) {
        const total = vals.reduce((a, b) => a + b, 0);
        const off = vals.length === g.items.length ? Math.abs(total - 100) > 5 : total > 105;
        sum.textContent = vals.length ? `Σ ${+total.toFixed(1)} %` : "";
        sum.className = "sum" + (off ? " off" : "");
        sum.title = off ? "The differential should add up to about 100 % — check the values" : "Sum of the differential (should be about 100 %)";
      }
    }
    return c;
  }

  function changed() {
    updateCount();
    updateButtons();
    if (typeof Case !== "undefined") Case.touch();      // keep Python's copy of the case current
    if (result) {                                   // keep the result in sync once it exists
      clearTimeout(rerunTimer);
      rerunTimer = setTimeout(() => run(true), 450);
    }
  }

  function setValues(inputs) {
    for (const [k, v] of Object.entries(inputs)) {
      const f = T.features[k];
      if (f && f.input === "bool") { yesNo[k] = !!v; continue; }
      if (f && f.input === "sounds") {
        picks[k] = new Set((Array.isArray(v) ? v : [v]).filter((s) => s in f.sounds));
        if (f.single && picks[k].size > 1) picks[k] = new Set([[...picks[k]][0]]);
        continue;
      }
      const i = document.querySelector(`#cForm input[data-k="${k}"]`);
      if (i) i.value = Array.isArray(v) ? v.join(", ") : v;
    }
    syncChips();
    for (const card of document.querySelectorAll("#cForm .cf")) validate(card);
    changed();
  }

  function hasInput() { return counts().entered > 0; }

  // ---------------------------------------------------------------- actions
  async function run(quiet = false) {
    if (!T || running || (state.busy && !quiet)) return;
    if (!hasInput()) {
      if (!quiet) toast("Enter at least one symptom, vital sign or lab value first.", true);
      if (quiet) { result = null; renderOut(); updateButtons(); }
      return;
    }
    running = true;
    let r;
    try {
      r = quiet ? await api().analyze_clinical(collect())
                : await call(() => api().analyze_clinical(collect()), "Analyzing clinical data…");
    } finally { running = false; }
    if (!r || r.ok === false) { if (quiet && r) toast(r.error, true); return; }
    result = r;
    if (!selected || !r.diseases.some((d) => d.id === selected) || !quiet) selected = r.diseases[0].id;
    state.exported = false;
    renderOut();
    setStatus("ok", "Integrated analysis complete");
    renderStepper();
    updateButtons();
  }

  async function importFile() {
    if (!state.ready || state.busy) return;
    const r = await call(() => api().import_clinical(), "Importing lab file…");
    if (!r || r.cancelled) { setStatus("ok", result ? "Integrated analysis complete" : "Ready"); return; }
    setValues(r.inputs);
    const n = r.count;
    toast(`Imported ${n} item${n === 1 ? "" : "s"} from ${r.file}` + (r.unknown.length ? ` · skipped: ${r.unknown.slice(0, 6).join(", ")}` : ""));
    setStatus("ok", "Lab file imported");
  }

  async function clear() {
    if (state.busy) return;
    for (const k of Object.keys(yesNo)) delete yesNo[k];
    for (const set of Object.values(picks)) set.clear();
    for (const i of document.querySelectorAll("#cForm input")) i.value = "";
    for (const card of document.querySelectorAll("#cForm .cf")) validate(card);
    syncChips();
    result = null;
    selected = null;
    clearTimeout(rerunTimer);
    await api().clear_clinical();
    renderOut();
    updateCount();
    renderStepper();
    setStatus("ok", "Ready");
    updateButtons();
  }

  // the X-ray result changed in step 1: refresh the integrated result
  function xrayChanged() {
    renderLeft();
    if (result) run(true);
  }

  // ---------------------------------------------------------------- left: step-1 summary
  function renderLeft() {
    const img = $("cThumbImg");
    if (state.image) {
      img.src = state.image.preview;
      img.hidden = false;
      $("cThumbTxt").hidden = true;
      $("cThumbFile").textContent = state.image.info.file;
    } else {
      img.hidden = true;
      img.removeAttribute("src");
      $("cThumbTxt").hidden = false;
      $("cThumbFile").textContent = "";
    }
    const mini = $("cMini");
    mini.replaceChildren();
    const scores = state.result && state.result.scores;
    if (scores) {
      const top = state.labels.map((l) => [l, scores[l]]).sort((a, b) => b[1] - a[1]).slice(0, 4);
      for (const [l, s] of top) {
        const r = el("div", "r " + band(s));
        const bar = el("div", "bar"), fill = el("i");
        fill.style.width = (s * 100).toFixed(1) + "%";
        bar.append(fill);
        r.append(el("span", null, l.replace("_", " ")), bar, el("span", "p", pctTxt(s)));
        mini.append(r);
      }
    } else {
      mini.append(el("div", "note", state.image
        ? "Image loaded but not analyzed. Run the analysis in step 1 to include the X-ray."
        : "No X-ray analyzed. The X-ray items are skipped; the result uses the clinical data only."));
    }
    $("cBack").textContent = scores ? `View all ${state.labels.length} X-ray results →` : "Go to the X-ray step →";
    const info = $("cInfo");
    info.replaceChildren();
    const i = state.image && state.image.info;
    const rows = i ? [["File", i.file], ["Format", i.format], ["Study", i.study_date || "—"], ["View", i.view || "—"]]
                   : [["File", "—"], ["Study", "—"], ["View", "—"]];
    for (const [k, v] of rows) { const b = el("b", null, v); b.title = v; info.append(el("span", null, k), b); }
    $("cSrc").textContent = scores ? "· X-ray + clinical" : "· clinical only";
  }

  // ---------------------------------------------------------------- right: result
  function ring(m, lvl) {
    const C = 2 * Math.PI * 32, col = { high: "#ef5350", moderate: "#f0a83a", low: "#34b27b" }[lvl];
    return `<svg width="78" height="78" viewBox="0 0 80 80"><circle class="ring-t" cx="40" cy="40" r="32" fill="none" stroke-width="8"/>` +
      `<circle cx="40" cy="40" r="32" fill="none" stroke="${col}" stroke-width="8" stroke-linecap="round" stroke-dasharray="${(m * C).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 40 40)"/>` +
      `<text x="40" y="45.5" text-anchor="middle" font-size="18" font-weight="700">${Math.round(m * 100)}%</text></svg>`;
  }

  function renderOut() {
    const out = $("cOut");
    out.replaceChildren();
    if (!result) {
      const p = el("div", "placeholder");
      p.append(el("span", null, hasInput()
        ? "Press Run AI Analysis to score the 7 diseases. Items left empty are skipped."
        : "Enter symptoms, auscultation, vital signs or lab data, then press Run AI Analysis."));
      out.append(p);
      const legend = el("div", "rec");
      legend.innerHTML = "<b>How it works:</b> every input is weighted per disease in groups " +
        "<span class='gA'>A</span> critical, <span class='gB'>B</span> important, <span class='gC'>C</span> slightly related, " +
        "<span class='gD'>D</span> not related. The match score is the weighted share of the expected findings that the patient shows. " +
        "<span class='dim'>Open <b>Weights</b> to see the table and the reasons.</span>";
      out.append(legend);
      return;
    }
    const top = result.diseases[0];
    const lvl = level(top.match);
    const hero = el("div", "hero " + lvl);
    hero.innerHTML = ring(top.match, lvl);
    const txt = el("div");
    const n = counts().entered;
    const detail = el("span");
    detail.textContent = `${n} input${n === 1 ? "" : "s"}${result.used_xray ? " + X-ray" : ""} · ${pctTxt(top.coverage)} of its weighted items entered`;
    if (top.low_confidence) detail.append(" · ", el("b", "lowc", "low confidence — add more data"));
    txt.append(el("div", "k", "Most likely assessment"), el("b", null, top.name), detail);
    hero.append(txt);
    out.append(hero);

    if (result.alerts.length) {
      const a = el("div", "alerts");
      for (const t of result.alerts) a.append(el("div", null, "⚠ " + t));
      out.append(a);
    }

    const sec = el("div", "sec", "Differential · match score");
    out.append(sec);
    const dx = el("div", "dx");
    for (const d of result.diseases) {
      const r = el("button", "r " + level(d.match) + (d.id === selected ? " sel" : ""));
      const name = el("span", "n", d.name);
      if (d.low_confidence) { const s = el("small", null, "low data"); s.title = `Only ${pctTxt(d.coverage)} of the weighted items entered`; name.append(s); }
      const bar = el("div", "bar"), fill = el("i");
      bar.append(fill);
      r.append(name, bar, el("span", "p", pctTxt(d.match)));
      r.title = `${d.name}: match ${pctTxt(d.match)}, coverage ${pctTxt(d.coverage)}. Click to see its factors.`;
      r.onclick = () => { selected = d.id; renderOut(); };
      dx.append(r);
      requestAnimationFrame(() => (fill.style.width = (d.match * 100).toFixed(1) + "%"));
    }
    out.append(dx);

    const d = result.diseases.find((x) => x.id === selected) || top;
    const fsec = el("div", "sec");
    fsec.append(el("span", null, "Key factors · " + d.name), el("div", "spacer"));
    const lg = el("span", "lg");
    lg.innerHTML = `<i style="background:var(--neg)"></i>lowers<i style="background:var(--pos)"></i>raises`;
    fsec.append(lg);
    out.append(fsec);
    const fx = el("div", "fx");
    const factors = d.factors.filter((f) => Math.abs(f.effect) >= 0.001).slice(0, 6);
    const maxE = Math.max(0.05, ...factors.map((f) => Math.abs(f.effect)));
    if (!factors.length) fx.append(el("div", "none", "No entered item is weighted for this disease."));
    for (const f of factors) {
      const r = el("div", "r");
      const n = el("span", "n");
      n.append(f.short || f.label, " ", el("em", null, f.value));
      const src = el("span", "src", SRC[f.category] || f.category);
      n.append(src, el("span", "g" + f.group, f.group));
      n.title = `${f.label}: ${f.value} — group ${f.group}, weight ${f.weight}, evidence ${Math.round(f.evidence * 100)}%`;
      const ax = el("div", "ax"), i = el("i", f.effect >= 0 ? "pos" : "neg");
      i.style.width = (Math.abs(f.effect) / maxE * 50).toFixed(1) + "%";
      ax.append(i);
      r.append(n, ax, el("span", "p", (f.effect >= 0 ? "+" : "−") + Math.abs(f.effect).toFixed(2)));
      fx.append(r);
    }
    out.append(fx);

    const rec = el("div", "rec");
    const p1 = el("p");
    p1.append(el("b", null, "Suggested follow-up: "), d.follow_up);
    rec.append(p1);
    const miss = d.missing.filter((m) => m.group === "A" || m.group === "B").slice(0, 5);
    if (miss.length) {
      const p2 = el("p");
      p2.append(el("b", null, "Not entered: "));
      miss.forEach((m, k) => { p2.append((k ? ", " : "") + m.label.replace("X-ray: ", "X-ray "), el("span", "g" + m.group, m.group)); });
      rec.append(p2);
    }
    rec.append(el("p", "dim", "AI decision support only — confirm with a clinician."));
    out.append(rec);
  }

  // ---------------------------------------------------------------- weighting table
  let wTab = null;
  const modalOpen = () => !$("wModal").hidden;

  function patText(p, f) {
    if (p.type === "present") return "Present";
    if (p.type === "absent") return "Absent";
    if (p.type === "any") return p.of.map((q) => patText(q, f)).join(" or ");
    const who = p.field ? p.field.toUpperCase() + " " : "";
    const unit = f.input === "xray" ? "" : " " + (f.unit || "");
    return `${who}${p.full > p.from ? "↑" : "↓"} ${p.from} → ${p.full}${unit}`;
  }

  function expected(fid, it) {
    const f = T.features[fid];
    if (it.group === "D") return ["—", ""];
    if (f.input === "sounds") {
      return [Object.entries(it.sounds).sort((a, b) => b[1] - a[1])
        .map(([k, v]) => f.sounds[k] + (v < 1 ? ` (${Math.round(v * 100)}%)` : "")).join(", "), ""];
    }
    const key = it.expect || (f.input === "bool" ? "present" : f.default);
    const p = f.patterns[key];
    const txt = patText(p, f);
    const sub = [txt.toLowerCase() === key ? "" : key.replace("_", " "), p.exclusion ? "exclusion" : ""].filter(Boolean).join(" · ");
    return [txt, sub];
  }

  function openWeights(id) {
    wTab = id || selected || Object.keys(T.diseases)[0];
    const tabs = $("wTabs");
    tabs.replaceChildren();
    for (const [k, d] of [...Object.entries(T.diseases), ["method", { name: "Method" }]]) {
      const b = el("button", k === wTab ? "on" : "", d.name);
      b.onclick = () => openWeights(k);
      tabs.append(b);
    }
    $("wTitle").textContent = "Weighting table";
    $("wSub").textContent = `models/weight.json · v${T.version} · ${Object.keys(T.features).length} inputs × ${Object.keys(T.diseases).length} diseases`;
    const body = $("wBody");
    body.replaceChildren();
    body.scrollTop = 0;
    if (wTab === "method") body.append(methodDoc());
    else body.append(...diseaseTable(wTab));
    $("wModal").hidden = false;
  }

  function diseaseTable(id) {
    const d = T.diseases[id];
    const sum = el("div", "w-sum");
    sum.append(el("b", null, `${d.name}${d.icd10 ? " (ICD-10 " + d.icd10 + ")" : ""}: `), d.summary);
    sum.append(el("div", "refs", "Sources: " + d.references.join(" · ")));
    sum.append(el("div", "refs", "Expected finding “↑ a → b”: the evidence rises from 0 at a to full at b (↓: falling). " +
      "Exclusion: an abnormal value counts fully against the disease, whatever its group."));
    const t = el("table", "wt");
    t.innerHTML = "<thead><tr><th>Item</th><th style='text-align:right'>Weight</th><th>Expected finding</th><th>Theory / assumption</th></tr></thead>";
    const tb = el("tbody");
    for (const g of ["A", "B", "C", "D"]) {
      const items = Object.entries(d.items).filter(([, it]) => it.group === g).sort((a, b) => b[1].weight - a[1].weight);
      const gh = el("tr", "gh");
      const td = el("td");
      td.colSpan = 4;
      const gi = T.groups[g];
      td.append(el("b", null, `Group ${g} · ${items.length} item${items.length === 1 ? "" : "s"}`), gi.meaning,
        gi.range[1] ? ` Weight ${gi.range[0]}–${gi.range[1]}.` : "");
      gh.append(td);
      tb.append(gh);
      for (const [fid, it] of items) {
        const f = T.features[fid];
        const tr = el("tr", g === "D" ? "d" : "");
        const c1 = el("td", "it");
        c1.append(f.short && f.input !== "xray" ? f.short : f.label.replace("X-ray: ", ""), el("span", "g" + g, g),
          el("small", null, (T.categories[f.category] || f.category) + (f.short && f.input !== "xray" && f.short !== f.label ? " · " + f.label : "")));
        const [ex, sub] = expected(fid, it);
        const c3 = el("td", "ex", ex);
        if (sub) c3.append(el("small", null, sub));
        tr.append(c1, el("td", "w", it.weight ? it.weight.toFixed(1) : "0"), c3, el("td", "why", it.why));
        tb.append(tr);
      }
    }
    t.append(tb);
    return [sum, t];
  }

  function methodDoc() {
    const m = T.method, s = T.spirometry_assessment;
    const doc = el("div", "w-doc");
    const h = (t) => doc.append(el("h4", null, t));
    const p = (t) => doc.append(el("p", null, t));
    h("Groups");
    const ul = el("ul");
    for (const [g, v] of Object.entries(m.groups)) {
      const li = el("li");
      li.append(el("span", "g" + g, g), ` ${v.meaning} Weight ${v.range[0]}–${v.range[1]}, ` +
        `presence factor ${v.presence_factor}, absence factor ${v.absence_factor}.`);
      ul.append(li);
    }
    doc.append(ul);
    h("Evidence"); p(m.evidence);
    h("Match score"); p(m.score); p(m.exclusion);
    p(`Prior ${m.prior}, prior strength K = ${m.prior_strength_K}. ` + m.coverage.replace("'low_coverage'", m.low_coverage));
    for (const n of m.notes) p("• " + n);
    if (s) {
      h("Spirometry (FEV1, FVC, %FEV1, FEV1/FVC) — " + s.verdict);
      for (const k of ["FEV1/FVC", "%FEV1", "FEV1", "FVC", "acute_diseases"]) if (s[k]) p(`${k === "acute_diseases" ? "Acute diseases" : k}: ${s[k]}`);
    }
    h("Disclaimer"); p(T.disclaimer);
    return doc;
  }

  function closeWeights() { $("wModal").hidden = true; }

  // ---------------------------------------------------------------- wiring
  function init(table) {
    T = table;
    buildForm();
    renderLeft();
    renderOut();
  }

  $("btnRun").onclick = () => run();
  $("btnImport").onclick = importFile;
  $("btnCClear").onclick = clear;
  $("btnBack").onclick = () => showStep(1);
  $("cBack").onclick = () => showStep(1);
  $("btnWeights").onclick = () => T && openWeights();
  $("wClose").onclick = closeWeights;
  $("wModal").addEventListener("mousedown", (e) => { if (e.target === e.currentTarget) closeWeights(); });

  return {
    init, run, clear, importFile, renderLeft, xrayChanged, openWeights, closeWeights, modalOpen,
    hasResult: () => !!result,
    inputs: () => (T ? collect() : {}),
    // an opened case: fill the form and score it (quietly)
    restore: async (inputs) => {
      await clear();
      if (inputs && Object.keys(inputs).length) {
        setValues(inputs);
        if (hasInput()) await run(true);
      }
    },
    hasInput: () => !!T && hasInput(),
    ready: () => !!T,
    result: () => result,
    entered: () => (T ? counts().entered : 0),
    setValues,
  };
})();
