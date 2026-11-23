# PneumoLens AI — Developer Guide

Where things live and what to edit for common changes. Search for the **ids and function names**
given here (Ctrl+Shift+F in VS Code); line numbers change too often to be worth listing.

---

## 1. How the app is put together

```
┌──────────────────────── one window (pywebview + Edge WebView2) ────────────────────────┐
│  ui/index.html  ── all pages and dialogs (HTML only, no logic)                         │
│  ui/style.css   ── app look, both themes          ui/report.css ── the report "paper"  │
│  ui/app.js      ── navigation, step 1 (X-ray), settings, exit, keyboard, start-up      │
│  ui/patient.js  ── patient page + case actions (New Patient, Open Saved Case)          │
│  ui/clinical.js ── step 2 (symptoms & labs form, results, weighting table)             │
│  ui/report.js   ── step 3 (report preview, review/sign, save PDF/DOCX)                 │
│          │                                                                             │
│          │  await window.pywebview.api.<method>(...)   → returns {ok: true, ...}       │
│          ▼                                             or {ok: false, error: "..."}    │
│  app.py  class Api ── every public method is callable from JavaScript                  │
└──────────┬─────────────────┬─────────────────┬─────────────────┬───────────────────────┘
           ▼                 ▼                 ▼                 ▼
   xray_engine.py    clinical_engine.py   case_store.py     report_docx.py
   read image, ONNX  weight.json scoring  dataset JSON      Word report
   models/*.onnx     models/weight.json   (atomic, no dup)  (python-docx)
```

* **Python never touches the page directly**, except `evaluate_js("openExitModal()")` when the
  window's ✕ is clicked. The JavaScript asks, and Python answers.
* Every `Api` method returns `_ok(...)` or `_error(e)`. In JavaScript, wrap calls in
  `call(() => api().method(...), "Busy text…")` (in `app.js`). It disables the buttons while the call
  runs, shows a toast on error, and returns `null` on failure.
* Methods and attributes whose names start with `_` are private, so JavaScript cannot call them.

## 2. File map

| File | Responsibility | Key names |
|---|---|---|
| `app.py` | Window, settings, the `Api` bridge, case state, report export | `APP_NAME`, `APP_VERSION`, `WINDOW_SIZE`, `DISCLAIMER`, `REPORT_DEFAULTS`, `DATASET_DEFAULT`, `class Api`, `main()` |
| `xray_engine.py` | Reads PNG/JPG/TIFF/DICOM, preprocesses, runs the ONNX model | `BANDS`, `SHOWN_LABELS`, `read_image`, `XRayModel.analyze` |
| `clinical_engine.py` | Loads/validates `weight.json`, scores the 7 diseases, severity, alerts | `ClinicalModel.score`, `.severity`, `.normalize`, `.alerts`, `NEUTRAL_EVIDENCE` |
| `case_store.py` | One JSON per case in the dataset folder: atomic write, skip if unchanged, fallback folder | `CaseStore.save`, `atomic_write_json`, `content_hash`, `SCHEMA` |
| `report_docx.py` | Builds the DOCX report | `build_docx` |
| `models/weight.json` | All disease knowledge: features, A/B/C/D weights, patterns, severity signs, lab groups | — |
| `ui/index.html` | Markup for the landing page, header, stepper, 4 pages, status bar, 3 dialogs | element ids, see §3 |
| `ui/app.js` | Global state, `showStep`, `renderStepper`, `updateButtons`, step 1 viewer/results, Settings, Exit, keyboard, `start()` | — |
| `ui/patient.js` | `Patient` (form get/set/summary) and `Case` (push to Python, New Patient, Open Saved Case) | — |
| `ui/clinical.js` | `Clinical` module: form built from `weight.json`, run/import/clear, results, weighting table | — |
| `ui/report.js` | `Report` module: `paperHTML()` (the report), side panel, sign, `save()` | — |
| `ui/style.css` | Design tokens (colors) for dark + light, then components, then responsive rules | sections are marked `/* ... */` |
| `ui/report.css` | The white report page, used in the preview and in the PDF | — |
| `tests/` | `test_engine`, `test_clinical`, `test_dataset`, `test_ui` (+ 70 example cases) | §6 |
| `tools/` | `build_standalone.py`, `make_test_cases.py`, `weights_pdf.py` | — |
| `run_windows.bat` / `build_windows*.bat` | Run (creates `.venv`), build `.exe`, standalone build | — |

## 3. Screen → file map

| What you see | HTML (`ui/index.html`) | Logic |
|---|---|---|
| Landing page | `<section id="landing">`, buttons `btnStart`, `btnLandCase`, `btnLandOpen` | `app.js` (wiring block near the end) |
| Header (logo, title, Model, Device, ⚙, theme) | `<div class="header">`, `btnHome`, `btnSettings`, `.theme-btn` | `app.js` |
| Stepper (1 Patient → 4 Final Report) | `step0`…`step3`, subtitles `step0Sub`…`step3Sub` | `renderStepper()` in `app.js` |
| Page 1 · Patient | `id="page0"`, fields with `data-p="..."`, `btnOpenCase0`, `btnNewPatient0`, `btnNext0` | `patient.js` |
| Page 2 · X-ray | `id="page1"`, `btnUpload`, `btnAnalyze`, `btnClear`, `btnExport`, `btnNext` | `app.js` (`analyze`, `renderResults`, viewer) |
| Page 3 · Symptoms & Labs | `id="page2"`, `btnBack`, `btnImport`, `btnRun`, `btnCClear`, `btnCExport`, `btnNext2` | `clinical.js` (form is **generated** from `weight.json`) |
| Page 4 · Final Report | `id="page3"`, `btnBack3`, `btnSave`, `btnOpenCase3`, `btnNewPatient` | `report.js` |
| Exit button (every page) | any button with `data-exit` | `openExitModal()` in `app.js` |
| Exit dialog | `id="exitModal"` | `openExitModal`, `exitNow` in `app.js` |
| Settings dialog | `id="setModal"`, inputs `setRatio`, `setMax`, `setDataset`, `setHospital` | `openSettings`, `saveSettings` in `app.js`; `get_settings`/`set_settings` in `app.py` |
| Weighting table dialog | `id="wModal"` | `openWeights` in `clinical.js` |
| Status bar / toast | `.status`, `#toast` | `setStatus()`, `toast()` in `app.js` |

> The pages are numbered `page0..page3` in code but shown as steps 1–4 on screen.

## 4. Recipes

### Change the app name, window title or version
* **Window title bar and settings folder:** `APP_NAME` in `app.py`. The settings folder
  `%APPDATA%\<APP_NAME>` changes with it, so existing users lose their settings.
* **Version:** `APP_VERSION` in `app.py`. It is shown in the app and written into every case file.
* **Browser `<title>`:** `<title>` in `ui/index.html`. The window title comes from `APP_NAME`.
* **Header title / subtitle:** `ui/index.html` → `<div class="htitle"><b>…</b><span>…</span>`.
* **Landing page text:** `ui/index.html` → `.l-hero` (`<h1>`, `.lead`, `.desc`).
* **Report title:** `paperHTML()` in `ui/report.js` (`<h1>Chest X-Ray &amp; Clinical AI Report`)
  **and** `build_docx()` in `report_docx.py`. Keep both in sync.
* **Disclaimer:** `DISCLAIMER` in `app.py`. It is used by the UI, the PDF and the DOCX.
* **Logo / icon:** `ui/logo.svg` (page), `ui/logo.ico` (window + exe), `ui/logo.png` (DOCX).

### Change the text of a button, a step or a heading
Edit the text in `ui/index.html`. A few texts are set from JavaScript and override the HTML:
* Stepper subtitles: `renderStepper()` in `app.js` (`step1Sub`), and `Patient.summary()` (`step0Sub`).
* Exit dialog text: `openExitModal()` in `app.js`.
* New Patient confirm text: `Case.newPatient()` in `patient.js`.
* Status bar and toast messages: the `setStatus(...)` / `toast(...)` calls next to each action.

### Add a button
1. **HTML:** copy an existing button in the right `<div class="actions">` of `ui/index.html` and give it a
   unique `id`. Use the classes `btn`, `btn primary` (blue), `btn next` (right-hand "next"), `btn exit` or `btn sm`.
   Icons are inline 24×24 SVGs; copy one from a neighbouring button.
2. **Click handler:** in `app.js`, in the wiring block next to `$("btnStart").onclick = …`, add
   `$("btnMyThing").onclick = myThing;`. Put the handler in the module that owns that page
   (`clinical.js` / `report.js` / `patient.js`) and export it from the module's `return { … }`.
3. **Enabled / disabled:** add a line to `updateButtons()` in `app.js`. It runs after every Python call
   and every step change. Use `idle` so the button is disabled while something is running.
4. **If it needs Python:** see the next recipe.
5. **Keyboard shortcut (optional):** the `document.addEventListener("keydown", …)` block in `app.js`.
   It is ordered by context (dialogs, landing, then step 0 / 3 / 2 / 1), and some Ctrl keys are blocked on purpose.
6. **Test:** add a click to `tests/test_ui.py`.

### Add a Python function the UI can call
```python
# app.py, inside class Api
def my_action(self, value: str):
    try:
        ...                                   # heavy work is fine: each JS call runs on its own thread
        return _ok(result=...)
    except Exception as e:
        return _error(e)
```
```js
// any ui/*.js
const r = await call(() => api().my_action("x"), "Working…");
if (r) toast("Done: " + r.result);
```
* Arguments and return values must be JSON-serializable (dict, list, str, number, bool, None).
* Shared state: when you touch case state (`_patient`, `_result`, `_review`, …), take `self._case_lock`.
* File dialogs: copy `open_image()` / `open_case()` / `browse_folder()`, which use
  `self._window.create_file_dialog`.

### Add a field to the Patient page
1. `ui/index.html`, `#page0`: add `<label class="fl"><span>Label</span><input data-p="my_field"></label>`.
   A choice field uses `<div class="seg pseg" data-p="…"><button data-v="A">A</button>…</div>`.
   **That's all for saving:** `Patient.get()/set()` read every `[data-p]`, and the field is stored in the
   case JSON automatically.
2. To show it in the report, add it to the `meta` list in `paperHTML()` (`report.js`) **and** to `pairs`
   in `build_docx()` (`report_docx.py`).
3. To make it count for the Patient step's ✓, edit `Patient.hasIdentity()`.

### Add or change a symptom / lab / disease / weight
**Edit `models/weight.json` only.** The step 2 form, lab groups, scoring, severity, weighting table and
report all read it. `ClinicalModel.validate()` checks the file at start-up and `tests/test_clinical.py`
checks it in depth. Run that test after every edit. The theory is in `docs/PneumoLens_weight_theory.pdf`
(regenerate with `tools/weights_pdf.py`).
If the new input needs special handling (unit conversion, derived values), add it to
`ClinicalModel.normalize()` in `clinical_engine.py`.

### Change which X-ray findings are shown or the HIGH/MODERATE thresholds
`SHOWN_LABELS` and `BANDS` in `xray_engine.py`. Which X-ray outputs feed each disease is set in
`weight.json` (`xray_selection` and the `xray_*` features).

### Change the final report
* **Preview + PDF:** `paperHTML()` in `ui/report.js` (content) and `ui/report.css` (look). The PDF is the
  same HTML, printed by WebView2 (`_print_to_pdf` in `app.py`).
* **DOCX:** `build_docx()` in `report_docx.py`. It is built separately, so mirror any change from the PDF.
* **Which diseases are listed (candidates):** the Settings ratio/max, `REPORT_DEFAULTS` in `app.py`,
  logic in `_compute_report()`.
* **Side panel (review, reviewer, sign, format):** `#page3` in `index.html`, `renderSide()` / `review()` in `report.js`.

### Add a setting
1. `index.html` `#setModal`: add the input.
2. `app.js`: fill it in `openSettings()` and send it in `saveSettings()`.
3. `app.py`: return it from `get_settings()`, then validate and accept it in `set_settings()`, which only
   accepts known keys. Read it anywhere with `load_settings().get("key", default)`.
   Settings live in `%APPDATA%\PneumoLens AI\settings.json`.

### Change what is saved in the dataset JSON
`_build_record()` in `app.py`. If you change the structure, also:
* Update `load_case()` so older files still open.
* Bump `SCHEMA` in `case_store.py` if old readers would misread the new layout.
* Add volatile fields (timestamps that change on every save) to `VOLATILE` in `case_store.py`.
  Otherwise every save looks like a change and writes a new revision.

### Change colors / theme
Only change the **tokens** at the top of `ui/style.css`: `:root` is dark and `:root[data-theme="light"]`
is light. Components use `var(--token)`, never hard-coded colors. If you change `--bg`, also change
`THEME_BACKGROUND` in `app.py`, which is the window color before the page paints.
The report (`report.css`) is always white on purpose.

### Add a new page / step
1. `index.html`: a new `<div class="page" id="pageN" hidden>` plus a stepper `<button class="step" id="stepN" data-go="N">`.
2. `app.js`: add N to the loop in `showStep()`, number and state in `renderStepper()`, wiring, and `updateButtons()`.
3. Keyboard rules for the page in the keydown block.

## 5. Case data rules (do not break these)

The doctor decides whether to save a **report**. The **case data** must always be saved, without fail
and without repeats.

* **One file per case:** `dataset/<case_id>.json`. A new revision overwrites the same file.
* `CaseStore.save()` skips the write when the content hash is unchanged, writes atomically
  (temp → fsync → replace → read back), and falls back to `%APPDATA%\PneumoLens AI\dataset_fallback`.
* **Triggers:** Save Report, Exit, New Patient, Open Saved Case and window ✕ (`_on_closing`).
  Each refuses to drop the case if saving fails, unless the user forces it.
* **JS → Python sync:** every edit calls `Case.touch()`, which sends after 400 ms. Before anything that
  saves or reads the case, `await Case.push()`. **If you add a new input anywhere, call `Case.touch()` on
  change**, or that edit can be missing from the saved file.
* `dataset/` is in `.gitignore`. Never commit patient data.

## 6. Run, test, build

```bat
run_windows.bat                       :: first run creates .venv; later runs install new requirements
.venv\Scripts\python app.py --debug   :: with browser dev tools (F12) for UI work
```
| Test | Covers |
|---|---|
| `tests/test_engine.py` | X-ray scores vs the reference PyTorch pipeline |
| `tests/test_clinical.py` | weight.json validity, textbook case per disease, severity, edge cases |
| `tests/test_dataset.py` | case saving: one file, no repeats, atomic, fallback, reopen, refuse on failure |
| `tests/test_ui.py` | opens the real window and clicks through everything (uses a temp dataset folder) |

Run all four before committing. When you add a button or field, add it to `test_ui.py`.

* **Builds:** `build_windows.bat` (PyInstaller folder build) and `build_windows_standalone.bat`
  (bundles the WebView2 runtime, via `tools/build_standalone.py`). A new **Python package** goes into
  `requirements.txt`. If PyInstaller misses it, add `--hidden-import` / `--collect-data` in the build
  scripts. A new **folder the app reads** needs an `--add-data` entry.
* Paths: read bundled files through `BASE_DIR` and user-side files (dataset, reports) through
  `APP_DIR` in `app.py`, so both the source run and the `.exe` work.
