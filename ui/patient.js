// PneumoLens AI - patient page (first page) and the case actions that span all pages:
// keeping Python's copy of the case current, New Patient, Open Saved Case.
// The case data itself is saved by Python (app.py save_case): one JSON file per case in the dataset folder.
"use strict";

const Patient = (() => {
  let hospitalDefault = "";
  const fields = () => [...document.querySelectorAll("#page0 [data-p]")];
  const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };

  function get() {
    const o = {};
    for (const el of fields()) {
      if (el.classList.contains("pseg")) {
        const b = el.querySelector("button.on");
        if (b) o[el.dataset.p] = b.dataset.v;
      } else if (el.value.trim()) {
        o[el.dataset.p] = el.value.trim();
      }
    }
    if (o.age !== undefined) {
      const n = parseInt(o.age, 10);
      if (Number.isFinite(n) && n >= 0 && n <= 130) o.age = n; else delete o.age;
    }
    return o;
  }

  function set(p) {
    for (const el of fields()) {
      const v = p[el.dataset.p];
      if (el.classList.contains("pseg")) {
        for (const b of el.children) b.classList.toggle("on", b.dataset.v === v);
      } else {
        el.value = v === undefined || v === null ? "" : String(v);
      }
    }
    summary();
  }

  function clear(defaults = true) {
    set(defaults ? { hospital: hospitalDefault, exam_date: today(), visit: "Outpatient" } : {});
  }

  function ageFromDob() {
    const dob = document.querySelector('#page0 [data-p="dob"]').value;
    if (!dob) return;
    const b = new Date(dob), t = new Date();
    let a = t.getFullYear() - b.getFullYear();
    if (t.getMonth() < b.getMonth() || (t.getMonth() === b.getMonth() && t.getDate() < b.getDate())) a--;
    if (a >= 0 && a <= 130) document.querySelector('#page0 [data-p="age"]').value = a;
  }

  function hasIdentity() { const p = get(); return !!(p.name || p.patient_id); }

  // short summary: stepper, report panel
  function summary() {
    const p = get();
    const who = p.name || p.patient_id || "";
    const bits = [p.age !== undefined ? `${p.age} y` : "", p.sex || ""].filter(Boolean).join(" · ");
    $("step0Sub").textContent = who ? `${who}${bits ? " · " + bits : ""}` : "Information for the report";
    const box = $("rPatient");
    box.replaceChildren();
    if (who) {
      box.append(el("b", null, p.name || "—"), ` · ID ${p.patient_id || "—"}${bits ? " · " + bits : ""}`);
    } else {
      box.append("No patient information entered. ");
    }
    const a = el("a", null, who ? " Edit" : "Enter it on the Patient page");
    a.onclick = () => showStep(0);
    box.append(a);
  }

  function init(settings) {
    hospitalDefault = (settings && settings.hospital) || "";
    clear(true);
  }
  function setHospitalDefault(h) {
    const inp = document.querySelector('#page0 [data-p="hospital"]');
    if (!inp.value || inp.value === hospitalDefault) inp.value = h || "";
    hospitalDefault = h || "";
  }

  // wiring
  for (const el of fields()) {
    if (el.classList.contains("pseg")) {
      el.addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        const on = !b.classList.contains("on");
        for (const x of el.children) x.classList.remove("on");
        b.classList.toggle("on", on);
        summary(); Case.touch(); renderStepper();
      });
    } else {
      el.addEventListener("input", () => {
        if (el.dataset.p === "age") el.value = el.value.replace(/[^0-9]/g, "").slice(0, 3);
        if (el.dataset.p === "dob") ageFromDob();
        summary(); Case.touch(); renderStepper();
      });
    }
  }
  return { get, set, clear, init, summary, hasIdentity, setHospitalDefault };
})();

// ------------------------------------------------------------------ the case (all pages)
const Case = (() => {
  let timer = null;

  function collect() {
    return { patient: Patient.get(), clinical_inputs: Clinical.inputs(), review: Report.review() };
  }
  // send the current state to Python now (before any save, exit or new patient)
  async function push() {
    clearTimeout(timer);
    timer = null;
    try { return await api().update_case(collect()); } catch (e) { return null; }
  }
  // after an edit: send it shortly (Python then always holds the latest data, even for the X button)
  function touch() {
    clearTimeout(timer);
    timer = setTimeout(push, 400);
  }
  async function status() {
    await push();
    return api().case_status();
  }

  function savedText(d) {
    if (!d || d.empty) return "";
    if (d.unchanged) return "Case data already saved (unchanged)";
    if (d.saved) return `Case data saved${d.fallback ? " to the FALLBACK folder (dataset folder not writable)" : ""}: ${d.path}`;
    return "";
  }

  function resetUI() {
    clearImage();
    Clinical.clear();
    Report.reset();
    Patient.clear(true);
    state.exported = false;
    renderStepper();
  }

  // New Patient: ask if the report is not saved; the case data is saved automatically (once)
  async function newPatient() {
    if (state.busy) return;
    const st = await status();
    const go = async (force) => {
      const r = await api().new_patient(!!force);
      if (!r.ok) {
        confirmBox({ title: "Could not save the case data", ok: "Clear anyway",
          text: `${r.error} The case was NOT cleared. Clear it anyway? Its data will be lost.`,
          onOk: () => go(true) });
        return;
      }
      resetUI();
      showStep(0);
      toast(savedText(r.data) || "Ready for a new patient.");
    };
    if (!st.has_data) { go(false); return; }
    confirmBox({
      title: "Start a new patient?",
      text: st.reports.length
        ? "The case data is saved to the dataset folder automatically."
        : "The report has not been saved. Start a new patient without saving the report? " +
          "The case data is saved to the dataset folder automatically.",
      ok: "New Patient",
      onOk: () => go(false),
    });
  }

  // Open a saved case (dataset JSON) for review. Python saves the current case first.
  async function open() {
    if (state.busy || !state.ready) return;
    await push();
    const r = await call(() => api().open_case(), "Opening saved case…");
    if (!r) return;
    if (r.cancelled) { setStatus("ok", "Ready"); return; }
    resetUI();
    Patient.set(r.patient || {});
    if (r.xray) restoreXray(r.xray);
    await Clinical.restore(r.clinical_inputs || {});
    Report.load(r.review || {}, r.case_id, r.reports || []);
    showStep(3);
    const prev = savedText(r.previous);
    toast(`Opened ${r.file}` + (r.warnings.length ? " · " + r.warnings.join(" ") : "") + (prev ? " · previous case: " + prev : ""),
          r.warnings.length > 0);
  }

  return { touch, push, status, newPatient, open, savedText, collect };
})();
