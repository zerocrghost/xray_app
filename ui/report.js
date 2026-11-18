// PneumoLens AI - step 3: final report.
// Python (app.py final_report) computes everything; this file renders the report "paper" (also printed to
// PDF and saved as HTML) and the review & export panel. Uses the helpers of app.js and clinical.js.
"use strict";

const Report = (() => {
  let R = null;            // last final_report() result
  let lastId = null;       // report id the review fields belong to
  let signed = "";         // ISO time of the sign-off ("" = not signed)
  let fmt = "pdf";
  let zoom = null;         // null = fit to width
  let saved = false;
  let reports = [];        // report files saved for this case (PDF / DOCX)
  let selId = null;        // candidate whose reasons / severity the side panel shows

  const sevCls = (g) => ({ Severe: "severe", Moderate: "moderate", Mild: "mild" }[g] || "na");
  const candidates = () => R.diseases.filter((d) => R.candidates.ids.includes(d.id));

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (x) => Math.round(x * 100) + "%";
  // a step's own score; "neutral" when it carries no real evidence (its % would only be the 20 % prior)
  const partTxt = (part, none) => (!part.used ? none : part.neutral ? "neutral" : pct(part.match));
  const NEUTRAL_TIP = "No finding clearly for or against this disease in this step, so it does not move the final score.";
  const when = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "—");
  const opts = () => Object.fromEntries([...document.querySelectorAll("[data-opt]")].map((i) => [i.dataset.opt, i.checked]));

  function review() {
    return {
      notes: $("rNotes").value.trim(),
      reviewer: $("rReviewer").value.trim(),
      agreed: $("rAgree").checked,
      signed_at: signed,
    };
  }

  // ---------------------------------------------------------------- open / refresh
  async function open() {
    await Case.push();                          // the latest patient / clinical edits first
    const r = await call(() => api().final_report(Clinical.inputs(), review()), "Preparing the report…");
    if (!r) return;
    R = r;
    if (R.id !== lastId) {                     // a new patient / new image: fresh review fields
      lastId = R.id;
      signed = "";
      saved = false;
      reports = [];
      $("rNotes").value = "";
      $("rAgree").checked = false;
      showData(null);
    }
    if (!$("rReviewer").value && r.reviewer_default) $("rReviewer").value = r.reviewer_default;
    if (!R.candidates.ids.includes(selId)) selId = R.candidates.ids[0];
    render();
    status();
    updateButtons();
  }

  function status() {
    setStatus(signed ? "ok" : "busy", signed ? `Report signed by ${review().reviewer}` : "Report ready · awaiting clinician sign-off");
  }

  // ---------------------------------------------------------------- the paper
  function reasonList(items, mark, cls) {
    return items.map((f) => `<li class="${cls}"><i>${mark}</i><span>${esc(f.label.replace("X-ray: ", ""))}` +
      `${f.value ? " · " + esc(f.value) : ""}<span class="g ${f.group}">${f.group}</span></span>` +
      `<small>${f.effect >= 0 ? "+" : "−"}${Math.abs(f.effect).toFixed(2)}</small></li>`).join("");
  }

  function whyCol(title, part, reasons, emptyText) {
    if (!part.used) return `<div class="col"><h3>${title}</h3><div class="none">${emptyText}</div></div>`;
    const list = reasonList(reasons.for, "✓", "y") + reasonList(reasons.against, "✗", "n");
    return `<div class="col"><h3>${title}<em title="${part.neutral ? NEUTRAL_TIP : ""}">${partTxt(part, "")}</em></h3>` +
      (list ? `<ul>${list}</ul>` : `<div class="none">No finding clearly for or against this disease.</div>`) + `</div>`;
  }

  function sevLine(d) {
    const s = d.severity, ab = s.signs.filter((x) => x.level !== "none");
    let t = `<b>Severity: ${esc(s.grade)}</b>`;
    if (s.assessed) t += ` · ${s.assessed} of ${s.total} severity signs measured`;
    if (ab.length) {
      t += " — " + ab.map((x) => `${esc(x.label)} ${esc(x.value)} <span class="${x.level === "severe" ? "sv" : "md"}">${x.level}</span>`).join(" · ");
    } else if (s.grade === "Mild") {
      t += " — no sign crosses a moderate threshold (weak signals)";
    } else {
      t += " — too few severity signs entered (e.g. SpO₂, respiratory rate, blood pressure, temperature)";
    }
    return `<div class="p-sevline">${t}<div style="color:#8a92a6;font-size:9.5px;margin-top:2px">Criteria: ${esc(s.source)}</div></div>`;
  }

  function paperHTML() {
    const o = opts(), top = R.diseases[0], p = R.patient, rv = review();
    const parts = top.parts;
    let h = "";
    h += `<div class="p-head"><img src="logo.svg" alt=""><div><h1>Chest X-Ray &amp; Clinical AI Report</h1>` +
      `<div class="s">PneumoLens AI · AI-assisted decision support for 7 lung diseases</div></div>` +
      `<div class="id"><b>${esc(R.id)}</b>Generated ${esc(when(R.generated))}</div></div>`;
    const ageSex = [p.age !== undefined && p.age !== null ? `${p.age} y` : "", p.sex || ""].filter(Boolean).join(" · ");
    const hw = [p.height ? `${p.height} cm` : "", p.weight ? `${p.weight} kg` : ""].filter(Boolean).join(" · ");
    const meta = [["Patient ID", p.patient_id || "—"], ["Name", p.name || "—"], ["Age · sex", ageSex || "—"],
      ["Date of birth", p.dob || "—"], ["Location", p.location || "—"], ["Phone", p.phone || "—"],
      ["Hospital", [p.hospital, p.department].filter(Boolean).join(" · ") || "—"], ["Referring physician", p.referring || "—"],
      ["Exam date", [p.exam_date, p.visit].filter(Boolean).join(" · ") || "—"], ["Height · weight", hw || "—"],
      ["X-ray", p.file ? `${p.file}${p.view ? " · " + p.view : ""}` : "not analyzed"], ["Models", (R.xray ? "densenet121 · " : "") + R.weights],
      ["Reviewed by", rv.reviewer || "—"], ["Status", signed ? "Signed " + when(signed) : "Not signed"],
      ["Data", `${R.xray ? "X-ray" : "no X-ray"} · ${R.clinical ? R.clinical.entered + " clinical inputs" : "no clinical data"}`]];
    h += `<div class="p-meta">${meta.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join("")}</div>`;
    const hist = [["Chief complaint", p.complaint], ["History", p.history], ["Allergies", p.allergies]].filter(([, v]) => v);
    if (hist.length) h += `<div class="p-text" style="margin:2px 0 4px">${hist.map(([k, v]) => `<b>${k}:</b> ${esc(v)}`).join(" &nbsp;·&nbsp; ")}</div>`;

    // integrated assessment: one clear candidate, or 2-3 close ones (rule from Settings)
    const C = R.candidates, cands = candidates();
    const others = R.diseases.filter((d) => !C.ids.includes(d.id));
    const assess = (d, i) => `<div class="p-assess ${d.level}"><div>` +
      (cands.length > 1 ? `<span class="rank">Candidate ${i + 1}</span>` : "") +
      `<b>${esc(d.name)} — ${pct(d.match)}</b>` +
      (i === 0 && cands.length === 1 ? `<div class="sub">Clearly ahead: the next disease, ${others[0] ? esc(others[0].name) + " " + pct(others[0].match) : "—"}, ` +
        `scores below ${Math.round(C.ratio * 100)} % of this score (cut-off ${pct(C.cutoff)}).</div>` : "") +
      `<div class="p-parts"><span>Step 1 · X-ray: ${partTxt(d.parts.xray, "not analyzed")}</span>` +
      `<span>Step 2 · Symptoms &amp; labs: ${partTxt(d.parts.clinical, "no data")}</span>` +
      `<span>Data coverage: ${pct(d.coverage)}</span></div>` +
      (d.low_confidence ? `<div class="p-note">Low confidence: less than 35 % of the weighted data for this disease was available.</div>` : "") +
      `</div><div class="p-badges"><div class="badge ${d.level}">${d.level === "MODERATE" ? "MOD" : d.level} MATCH</div>` +
      `<div class="p-sevb ${sevCls(d.severity.grade)}">${esc(d.severity.grade.toUpperCase())}</div></div></div>`;
    if (cands.length === 1) {
      h += `<div class="p-sec">Integrated assessment</div>` + assess(top, 0);
    } else {
      h += `<div class="p-sec">Integrated assessment — ${cands.length} candidate diagnoses</div>` +
        `<div class="p-cands">${cands.map(assess).join("")}</div>`;
    }
    h += `<div class="p-rule">Candidates: every disease scoring at least ${Math.round(C.ratio * 100)} % of the first candidate ` +
      `(≥ ${pct(C.cutoff)}), at most ${C.max}. ` +
      (others.length ? `Not listed: ${others.map((d) => `${esc(d.name)} ${pct(d.match)}`).join(", ")}.` : "") + `</div>`;

    // why + severity, per candidate
    h += `<div class="p-sec">${cands.length === 1 ? "Why " + esc(top.name) + " — reasons and severity" : "Reasons and severity per candidate"}</div>`;
    cands.forEach((d, i) => {
      h += `<div class="p-cblock">` +
        (cands.length > 1 ? `<h4>${i + 1}. ${esc(d.name)} — ${pct(d.match)}<span class="p-sevb ${sevCls(d.severity.grade)}">${esc(d.severity.grade.toUpperCase())}</span></h4>` : "") +
        (o.factors ? `<div class="p-why">` +
          whyCol("Step 1 · X-ray findings", d.parts.xray, d.reasons.xray, "No X-ray was analyzed.") +
          whyCol("Step 2 · Symptoms, vital signs &amp; labs", d.parts.clinical, d.reasons.clinical, "No clinical data was entered.") +
          `</div>` : "") + sevLine(d) + `</div>`;
    });
    if (R.alerts.length) h += `<div class="p-alert"><b>Alerts:</b> ${R.alerts.map(esc).join(" · ")}</div>`;

    // 1 imaging
    h += `<div class="p-sec">1 · Imaging findings (lung-related X-ray outputs)</div>`;
    if (R.xray) {
      const lung = R.xray.lung;
      const shown = o.raw ? lung : lung.filter((x, i) => i < 5 || x.score >= 0.3);
      const rows = shown.map((x) => {
        const col = { HIGH: "#e0453f", MODERATE: "#e59a2c", LOW: "#2fa36f" }[x.level];
        return `<tr><td>${esc(x.label)}</td><td><span class="pb" style="width:${Math.round(x.score * 80)}px;background:${col}"></span></td>` +
          `<td class="r">${(x.score * 100).toFixed(1)}%</td><td><span class="f ${x.level}">${x.level === "MODERATE" ? "MOD" : x.level}</span></td></tr>`;
      }).join("");
      const rest = lung.length - shown.length;
      const other = o.raw ? R.xray.not_used.map((x) => `<tr class="dim"><td>${esc(x.label)}</td><td>not used (non-lung)</td>` +
        `<td class="r">${(x.score * 100).toFixed(1)}%</td><td></td></tr>`).join("") : "";
      const table = `<table><tr><th>Finding</th><th></th><th class="r">Score</th><th>Flag</th></tr>${rows}` +
        (rest > 0 ? `<tr class="dim"><td colspan="4">${rest} other lung findings below 30 %</td></tr>` : "") + other + `</table>`;
      const img = o.image && state.image ? `<div class="p-img"><img src="${state.image.preview}" alt=""></div>` : "";
      h += img ? `<div class="p-two">${img}${table}</div>` : table;
      h += `<div class="p-text" style="margin-top:5px;font-size:10px;color:#6b7489">${lung.length} of 18 model outputs are lung-related and ` +
        `weighted per disease; ${R.xray.not_used.map((x) => esc(x.label)).join(", ")} are not used. ` +
        `HIGH ≥ 50 % (model operating point), MOD 30–50 %.</div>`;
    } else {
      h += `<div class="p-text">No X-ray was analyzed for this report.</div>`;
    }

    // 2 clinical
    h += `<div class="p-sec">2 · Symptoms, vital signs &amp; laboratory data</div>`;
    const c = R.clinical;
    if (c) {
      const lines = [];
      if (c.present.length) lines.push(`<b>Symptoms present:</b> ${c.present.map(esc).join(", ")}`);
      if (c.absent.length) lines.push(`<b>Absent:</b> ${c.absent.map(esc).join(", ")}`);
      if (c.sounds.length) lines.push(`<b>Auscultation:</b> ${c.sounds.map(esc).join(", ")}`);
      if (lines.length) h += `<div class="p-text" style="margin-bottom:6px">${lines.join(" &nbsp;·&nbsp; ")}</div>`;
      if (c.rows.length) {
        let last = null;
        const head = (x) => {                     // a sub-heading row whenever the section changes
          const key = x.subgroup || x.category;
          if (key === last) return "";
          last = key;
          return `<tr class="sg"><td colspan="4">${esc((c.titles || {})[key] || key)}</td></tr>`;
        };
        h += `<table><tr><th>Item</th><th class="r">Value</th><th>Reference</th><th>Flag</th></tr>` +
          c.rows.map((x) => head(x) + `<tr><td>${esc(x.label)}${x.short && x.short !== x.label ? ` <span style="color:#8a92a6">(${esc(x.short)})</span>` : ""}</td>` +
            `<td class="r">${esc(x.value)}</td><td>${esc(x.ref)}</td>` +
            `<td>${x.flag ? `<span class="f ${x.flag === "NORMAL" ? "n" : "h"}">${x.flag}</span>` : ""}</td></tr>`).join("") + `</table>`;
      }
    } else {
      h += `<div class="p-text">No clinical data was entered.</div>`;
    }

    // 3 differential
    h += `<div class="p-sec">3 · Differential diagnosis (7 lung diseases)</div>` +
      `<table><tr><th>Disease</th><th class="r">Combined</th><th class="r">Step 1 · X-ray</th><th class="r">Step 2 · Clinical</th><th class="r">Coverage</th><th>Match</th><th>Severity</th></tr>` +
      R.diseases.map((d) => `<tr class="${R.candidates.ids.includes(d.id) ? "top" : ""}"><td>${esc(d.name)}${d.low_confidence ? ' <span style="color:#a8650f">(low data)</span>' : ""}</td>` +
        `<td class="r">${pct(d.match)}</td><td class="r">${partTxt(d.parts.xray, "—")}</td>` +
        `<td class="r">${partTxt(d.parts.clinical, "—")}</td><td class="r">${pct(d.coverage)}</td>` +
        `<td><span class="f ${d.level}">${d.level === "MODERATE" ? "MOD" : d.level}</span></td>` +
        `<td>${esc(d.severity.grade)}</td></tr>`).join("") + `</table>` +
      `<div class="p-text" style="margin-top:5px;font-size:10px;color:#6b7489">Match scores are independent (diseases can coexist) and ` +
      `do not add up to 100 %. Weights and theory: ${esc(R.weights)}.</div>`;

    // 4 follow-up
    h += `<div class="p-sec">4 · Recommended follow-up</div>`;
    cands.forEach((d) => {
      h += `<div class="p-text" style="margin-bottom:4px"><b>${esc(d.name)}:</b> ${esc(d.follow_up)}`;
      if (d.missing.length) {
        h += `<br><span style="color:#6b7489">Important data not available: ` +
          d.missing.map((m) => `${esc(m.label.replace("X-ray: ", "X-ray "))}<span class="g ${m.group}">${m.group}</span>`).join(", ") + `</span>`;
      }
      h += `</div>`;
    });

    // 5 review
    if (o.notes) {
      h += `<div class="p-sec">5 · Clinician review</div><div class="p-notes">${esc(rv.notes) || '<span style="color:#8a92a6">No notes.</span>'}</div>` +
        `<div class="p-sign"><div><b>${esc(rv.reviewer)}</b>Reviewed by</div><div><b>${signed ? esc(when(signed)) : ""}</b>Signed</div>` +
        `<div><b>${rv.agreed ? "Agrees with the AI assessment" : ""}</b>Agreement</div></div>`;
    }
    h += `<div class="p-foot"><span>${esc(R.disclaimer)}</span><span>${esc(R.app)} · ${esc(R.weights)}</span></div>`;
    return h;
  }

  // ---------------------------------------------------------------- right panel
  function renderSide() {
    const top = R.diseases[0], C = R.candidates, cands = candidates();
    const sel = cands.find((d) => d.id === selId) || top, parts = sel.parts;
    const next = R.diseases[cands.length];
    const v = $("rVerdict");
    v.className = "cands";
    v.innerHTML = `<div class="ch">${cands.length === 1 ? "Final AI assessment · clearly most likely"
                                                       : `${cands.length} candidate diagnoses`}` +
      `<span class="cr" title="Change in Settings (gear button)">≥ ${Math.round(C.ratio * 100)} % of the top score</span></div>` +
      cands.map((d, i) => `<button class="cand ${d.level.toLowerCase()}${i === 0 ? " first" : ""}${d.id === sel.id ? " sel" : ""}" data-id="${d.id}">` +
        `<span class="rk">${i + 1}</span><b class="nm">${esc(d.name)}<small>${d.low_confidence ? "low confidence · " : ""}` +
        `coverage ${pct(d.coverage)}${i === 0 && cands.length === 1 && next ? ` · next: ${esc(next.name)} ${pct(next.match)}` : ""}</small></b>` +
        `<span class="sev ${sevCls(d.severity.grade)}">${esc(d.severity.grade)}</span><span class="pc">${pct(d.match)}</span></button>`).join("");
    for (const b of v.querySelectorAll(".cand")) b.onclick = () => { selId = b.dataset.id; renderSide(); };

    const s = sel.severity, ab = s.signs.filter((x) => x.level !== "none");
    $("rSev").innerHTML = `<div class="sevbox"><div class="st2">Severity · ${esc(sel.name)}<span class="sev ${sevCls(s.grade)}">${esc(s.grade)}</span></div>` +
      (ab.length ? `<ul>${ab.map((x) => `<li class="${x.level}" title="${esc(x.why)}"><i>${x.level === "severe" ? "●●" : "●"}</i>${esc(x.label)} ${esc(x.value)}</li>`).join("")}</ul>`
        : `<div class="none">${s.grade === "Mild" ? `${s.assessed} severity signs measured, none clearly abnormal — weak signals.`
                                                  : "Too few severity signs entered (SpO₂, respiratory rate, blood pressure, temperature…)."}</div>`) +
      `</div>`;
    const card = (title, part, reasons, emptyText) => {
      if (!part.used) return `<div class="wcard"><div class="wt">${title}</div><div class="none">${emptyText}</div></div>`;
      const li = (f, mark, cls) => `<li class="${cls}"><i>${mark}</i><span title="${esc(f.why)}">${esc(f.label.replace("X-ray: ", ""))}` +
        `${f.value ? " · " + esc(f.value) : ""}</span></li>`;
      const items = reasons.for.slice(0, 3).map((f) => li(f, "✓", "y")).join("") + reasons.against.slice(0, 2).map((f) => li(f, "✗", "n")).join("");
      return `<div class="wcard"><div class="wt">${title}<b title="${part.neutral ? NEUTRAL_TIP : ""}">${partTxt(part, "")}</b></div>` +
        (items ? `<ul>${items}</ul>` : `<div class="none">No finding clearly for or against.</div>`) + `</div>`;
    };
    $("rWhy").innerHTML = card("Step 1 · X-ray", parts.xray, sel.reasons.xray, "No X-ray analyzed — go to step 1 to add it.") +
      card("Step 2 · Clinical", parts.clinical, sel.reasons.clinical, "No symptoms or labs entered — add them in step 2.");
    const c = R.clinical;
    const stats = [
      ["X-ray ≥ 50 %", R.xray ? R.xray.flagged : "—", R.xray ? `/ ${R.xray.lung.length}` : ""],
      ["Values abnormal", c ? c.abnormal : "—", c ? `/ ${c.rows.filter((x) => x.flag).length}` : ""],
      ["Symptoms", c ? c.present.length : "—", c ? "present" : ""],
    ];
    const tips = {"X-ray ≥ 50 %": "Lung-related X-ray outputs at or above the model threshold (50 %). Values just above 50 % are often the model's background level, so this is not the same as clearly abnormal.",
                  "Values abnormal": "Vital signs and lab values outside their reference range / values that have a range.",
                  "Symptoms": "Symptoms marked as present in step 2."};
    $("rStats").innerHTML = stats.map(([k, b, s]) => `<div class="stat" title="${tips[k] || ""}"><span>${k}</span><b>${b}</b><small>${s}</small></div>`).join("");
    const chip = $("rSignChip");
    chip.className = "chip " + (signed ? "ok" : "busy");
    chip.querySelector("span").textContent = signed ? "Signed" : "Not signed";
    $("rSign").classList.toggle("done", !!signed);
    $("rSign").lastChild.textContent = signed ? "Signed" : "Sign report";
    $("rSub").textContent = `· ${R.id}`;
    $("step3Sub").textContent = signed ? "Signed" : cands.length > 1 ? `${cands.length} candidates · ${top.name} first`
                                                                      : `${top.name} · ${top.severity.grade}`;
  }

  function render() {
    if (!R) return;
    const paper = $("rPaper");
    paper.innerHTML = paperHTML();
    const copy = paper.cloneNode(true);
    copy.removeAttribute("id");
    copy.style.zoom = "";
    $("printRoot").replaceChildren(copy);
    renderSide();
    applyZoom();
  }

  function applyZoom() {
    const paper = $("rPaper"), canvas = $("rCanvas");
    const fit = Math.min(1.2, Math.max(0.3, (canvas.clientWidth - 44) / 794));
    const z = zoom ?? fit;
    paper.style.zoom = z.toFixed(3);
    $("rZoomFit").textContent = zoom === null ? "Fit" : Math.round(z * 100) + "%";
  }

  // ---------------------------------------------------------------- actions
  function sign() {
    const rv = review();
    if (signed) { signed = ""; render(); status(); toast("Signature removed."); return; }
    if (!rv.reviewer) { toast("Enter the reviewer's name first.", true); $("rReviewer").focus(); return; }
    if (!rv.agreed) { toast("Tick “I have reviewed the AI findings” to sign.", true); return; }
    const d = new Date();                       // local time, like "Generated"
    signed = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    api().remember_reviewer(rv.reviewer);
    render();
    status();
    toast(`Report signed by ${rv.reviewer}.`);
  }

  function edited() {
    if (signed) { signed = ""; renderSide(); toast("The report changed after signing — sign it again.", true); status(); }
    clearTimeout(edited.t);
    edited.t = setTimeout(render, 250);
    if (typeof Case !== "undefined") Case.touch();
  }

  async function save() {
    if (!R || state.busy) return;
    render();                                   // the PDF prints #printRoot, so it must be current
    await Case.push();                          // Python saves the latest case data with the report
    const r = await call(() => api().save_report(fmt, null, review(), opts()), `Saving ${fmt.toUpperCase()} report…`);
    if (r && !r.cancelled) {
      saved = true;
      state.exported = true;
      reports.push({ format: fmt, path: r.path });
      const d = r.data || {};
      showData(d);
      if (d.ok === false) toast(`Report saved: ${r.path} — but the CASE DATA could not be saved: ${d.error}`, true);
      else toast(`Report saved: ${r.path} · ${Case.savedText(d)}`);
      renderStepper();
    }
    status();
  }

  function showData(d) {
    const box = $("rData");
    box.className = "dsnote" + (d && d.ok === false ? " err" : "");
    box.replaceChildren();
    if (!d) return;
    if (d.ok === false) { box.append(el("b", null, "Case data NOT saved: "), d.error || ""); return; }
    const t = Case.savedText(d);
    if (t) box.append(el("b", null, "✓ "), t);
  }

  // New Patient: forget this case's report state
  function reset() {
    R = null; lastId = null; signed = ""; saved = false; reports = []; selId = null;
    $("rNotes").value = "";
    $("rAgree").checked = false;
    $("rPaper").replaceChildren();
    $("printRoot").replaceChildren();
    showData(null);
  }

  // Open Saved Case: restore the review of that case (it keeps its id, so open() does not clear it)
  function load(rv, caseId, savedReports) {
    reset();
    lastId = caseId;
    $("rNotes").value = rv.notes || "";
    $("rReviewer").value = rv.reviewer || "";
    $("rAgree").checked = !!rv.agreed;
    signed = rv.signed_at || "";
    reports = savedReports.slice();
    saved = reports.length > 0;
  }

  // ---------------------------------------------------------------- wiring
  for (const id of ["rNotes", "rReviewer"]) $(id).addEventListener("input", edited);
  $("rAgree").addEventListener("change", edited);
  for (const i of document.querySelectorAll("[data-opt]")) i.addEventListener("change", render);
  $("rFmt").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    fmt = b.dataset.fmt;
    for (const x of $("rFmt").children) x.classList.toggle("on", x === b);
  });
  $("rSign").onclick = sign;
  $("btnSave").onclick = save;
  $("btnNewPatient").onclick = () => Case.newPatient();
  $("btnOpenCase3").onclick = () => Case.open();
  $("btnBack3").onclick = () => showStep(2);
  $("rZoomIn").onclick = () => { zoom = Math.min(2, (zoom ?? parseFloat($("rPaper").style.zoom || 1)) * 1.15); applyZoom(); };
  $("rZoomOut").onclick = () => { zoom = Math.max(0.3, (zoom ?? parseFloat($("rPaper").style.zoom || 1)) / 1.15); applyZoom(); };
  $("rZoomFit").onclick = () => { zoom = null; applyZoom(); };
  window.addEventListener("resize", () => { if (R && !$("page3").hidden) applyZoom(); });

  return {
    open, save, reset, load, review,
    ready: () => !!R,
    savedReports: () => reports.slice(),
    scores: () => R.diseases.map((d) => [d.name, d.match]),
    unsaved: () => !!R && !saved,
    setFormat: (f) => { const b = document.querySelector(`#rFmt [data-fmt="${f}"]`); if (b) b.click(); },
  };
})();
