# PneumoLens AI – desktop app (landing page, step 1 X-ray, step 2 symptoms & labs, step 3 final report)

<img src="ui/logo.svg" width="64" align="right" alt="PneumoLens AI logo">

**PneumoLens AI** is an AI-assisted pneumonia and lung-disease screening tool for chest
X-rays. It is a Windows desktop app built with **pywebview**, and it runs the chest
X-ray model **on the PC**: no server, no PyTorch, no internet.

The app opens on a landing page. **Start New Analysis** (or Enter) goes to step 1,
X-ray analysis, and **Open X-ray Image…** (Ctrl+O) goes straight there with an image
loaded. Click the logo in the header to return to the landing page.

**Step 2, Symptoms & Labs** (Next: Symptoms & Labs, or click step 2 in the stepper) scores
7 lung diseases: asthma, COPD, pneumonia, pleurisy, chronic bronchitis, lung abscess and
bronchiectasis. It uses symptoms (fever, dyspnea, wheezing, cough, sputum, chest pain),
auscultation, vital signs (BP, PR, BT, RR, GCS, SpO₂), lab data (WBC, ESR, STAB, SEG, Eos,
Bas, Lym, Mon, ALT, AST, TP, ZTT, Glu), optional spirometry (FEV1, FVC, %FEV1, FEV1/FVC) and
the step-1 X-ray scores. Leave anything that was not measured empty: it is skipped, not
treated as normal. This applies to every lab field: none is required.

**History & exposure:** these are core GOLD criteria for COPD.

* **Noxious exposure:** select all that apply: current or former smoker, occupational dust/chemicals/fumes, biomass/indoor smoke, outdoor pollution, passive smoking, or none.
* **Pack-years:** cumulative smoking.
* **Illness duration:** choose one: acute < 3 weeks, subacute 3–8 weeks, chronic > 8 weeks, years (slowly progressive), or recurrent episodes.

These are weighted per disease. Exposure and a chronic course are A for COPD and chronic bronchitis. An acute course is A for pneumonia. A subacute course supports lung abscess, and recurrent episodes support asthma. **Import Lab File** reads a JSON object or a two-column CSV
(`WBC,12.1` / `fever,yes` / `BP,128/78`). **Export** writes the X-ray and clinical result
together.

**Step 3, Final Report** (Next: Final Report, or step 3 in the stepper) combines both steps.

* **Assessment:** shows the most likely disease with its combined match. Next to it are the X-ray part (step 1) and the clinical part (step 2), each with its reasons:
  * ✓ findings that support the disease
  * ✗ missing key findings or violated exclusions
* **Candidates:** the first disease is always shown. Other diseases are listed next to it when their score is at least a set share of the first one's score, up to a set maximum. With a large gap only the first disease is shown, marked "clearly most likely".
  * Set both in **Settings** (gear button in the header). The defaults are 50 % and 3 diseases.
  * The values are saved in `%APPDATA%\PneumoLens AI\settings.json`.
* **Severity:** each candidate gets **Mild / Moderate / Severe** from its guideline severity signs, not from the match score:
  * Pneumonia: CURB-65, A-DROP and the ATS/IDSA minor criteria
  * Asthma: GINA exacerbation severity
  * COPD: GOLD airflow grade and exacerbation signs
  * The other four diseases have equivalent signs, defined in weight.json under `severity`.
* **How severity is graded:** each sign is none / moderate / severe by its thresholds.
  * Weak signals, just outside the normal range, give Mild.
  * Clearly abnormal values give Severe: 2 severe signs, or 4 points.
  * Too few signs measured gives Not assessable.
  * The report lists the signs behind each grade.
* **Report preview:** a printable report with:
  * the assessment and the reasons from both steps
  * any alerts
  * the lung-related X-ray findings with the image
  * the clinical data with reference ranges and flags
  * the 7-disease differential (combined, step 1, step 2, coverage)
  * the follow-up and the clinician review
* **Review:** enter a patient ID, notes and the reviewer, then **Sign report**. Signing needs the reviewer's name and the confirmation tick. Any later edit removes the signature, and the reviewer's name is remembered.
* **Save Report** (Ctrl+S) saves as:
  * **PDF**: printed by WebView2 from the preview, so no extra library is needed.
  * **HTML**: a single self-contained file.
  * **JSON**: all the data.
  * **CSV**: the values.
* **Print** (Ctrl+P) prints the report only.
* **New Patient** clears everything after a confirmation.
* **Example:** `design/screenshots/example_report.pdf`.

**X-ray outputs used:**
* The model gives 18 outputs. The 14 lung-related ones are weighted per disease in weight.json:
  * Pneumonia, Consolidation, Lung Opacity, Infiltration
  * Atelectasis, Effusion, Pleural Thickening, Emphysema
  * Fibrosis, Mass, Lung Lesion, Nodule
  * Pneumothorax, Edema
* Cardiomegaly, Enlarged Cardiomediastinum, Hernia and Fracture are not lung findings, so they are not used. The reasons are in `xray_selection` in weight.json.

### The weighting table: `models/weight.json`

All clinical knowledge is in `models/weight.json`, and the page is built from it. Change a
weight, save, and restart the app. The app refuses to start with a broken table and lists
every problem.

* **Groups:** for every disease, every one of the 44 inputs (30 clinical + 14 X-ray) is in a group.
  * **A** (2.5–3.5): critical, a defining feature.
  * **B** (1.5–2.4): important.
  * **C** (0.3–1.4): slightly related.
  * **D** (0): not related.
  Each entry has a weight within its group's range, the expected finding (e.g. *WBC ↑ 9 → 15*) and `why`, the theory or
  assumption behind it with its source (GINA, GOLD, ATS/IDSA, CURB-65, BTS, ...).
* **Score:** `match = (Σ w·s·p + 0.2·K) / (Σ w·(s + (1−s)·a) + K)` over the entered items.
  * `s` is how strongly the patient shows the expected finding, from 0 to 1.
  * `p` is the presence factor (specificity): A 1, B 0.8, C 0.5.
  * `a` is the absence factor (sensitivity): A 1, B 0.6, C 0.3.
  * Findings that expect a *normal* value are exclusions. A normal value adds nothing, and an abnormal value counts fully against the disease.
  * The same formula also runs on the X-ray items alone and on the clinical items alone. These are the step-1 and step-2 parts shown in the report.
* **Independent scores:** the 7 scores are independent, because diseases can coexist, so they don't add up to 100 %.
* **Coverage:** shows how much of a disease's weighted data was entered. Below 35 % the result is marked *low confidence*.
* **In the app:** the **Weights** button on step 2 shows the full table for each disease, plus a Method tab.

**Spirometry: include it as optional.** FEV1/FVC is the deciding test for COPD (< 0.70 is
required by GOLD) and documents the airflow limitation of asthma, so it is group A for both.
It is B for chronic bronchitis and bronchiectasis, and D for the acute infections, where it isn't measured.

* %FEV1 grades severity (GOLD 1–4).
* FEV1 and FVC on their own depend on age, sex and height, so they are weak (B/C). Their main use is to compute FEV1/FVC, which the app does automatically.

The weights are expert-style assumptions taken from the guidelines, not fitted to patient data. Validate them before any clinical use.

**Theory document:** `docs/PneumoLens_weight_theory.pdf` explains every rule, group and weight with its source.
It is generated from weight.json, so rebuild it after editing the weights:
`.venv\Scripts\python tools\weights_pdf.py`. This script needs `pip install reportlab`, which is only for the documentation, not the app.

**Themes:** dark and light. Switch with the sun/moon button in the header or with
Ctrl+T. The choice is saved in `%APPDATA%\PneumoLens AI\settings.json`; on first
start the app follows the Windows app theme. Every color is a token in
`ui/style.css`, so a component never hard-codes a theme color. The X-ray itself
always shows on black.

**Design:** `design/` holds the mock-ups for all three steps
(`step1_xray.html`, `step2_clinical.html`, `step3_report.html`). Open one as is
for dark, or add `#light` to the URL for light. They share the app's stylesheet
through `design/style.css`. Screenshots of the app and the mock-ups in both
themes are in `design/screenshots/`.

Logo files: `ui/logo.svg` (source), `ui/logo.png` (256 px) and `ui/logo.ico`
(window and .exe icon). The window can't be made smaller than 1040 × 800 because
that is the smallest size at which the whole design fits without being cut off.

```
┌─────────── native window (Edge WebView2) ───────────┐
│  ui/index.html + style.css + app.js  (the design)   │
│              │  await pywebview.api.analyze()       │
│              ▼                                      │
│  app.py  (Api class: dialogs, export, exit)         │
│  xray_engine.py  read → preprocess → ONNX Runtime   │
│  models/xray_densenet121.onnx  (from xray_onnx/)    │
└─────────────────────────────────────────────────────┘
```

## Run on Windows

1. Install **Python 3.14** (3.12 and 3.13 also work) from python.org and tick "Add python.exe to PATH".
2. Copy this `desktop` folder to the Windows PC, but leave out `.venv`.
3. Double-click **`run_windows.bat`**. The first run creates `.venv` and
   installs the packages, which takes a few minutes. After that the app starts
   in seconds.

The app needs two Microsoft runtimes. Windows 10 and 11 usually have both, but
**Windows Server** (2019/2022/2025) and old Windows 10 builds often have neither:

- **Edge WebView2 Runtime** draws the window. Without it, Windows falls back to
  Internet Explorer and the layout is broken, so the app stops and says so.
  Install the Evergreen Runtime: https://go.microsoft.com/fwlink/p/?LinkId=2124703
- **Visual C++ Redistributable (x64)** is needed by onnxruntime. Without it you get
  `DLL load failed while importing onnxruntime_pybind11_state`.
  Install it: https://aka.ms/vs/17/release/vc_redist.x64.exe

With winget: `winget install Microsoft.EdgeWebView2Runtime Microsoft.VCRedist.2015+.x64`.
Windows Server has no winget, so download and run the two installers from the links
above (silent options: `/silent /install` for WebView2 and `/install /quiet /norestart`
for the Visual C++ runtime).

### Build an .exe

```bat
build_windows.bat
```

This first runs the score test, then PyInstaller. To give the app to someone
else, ship the **whole** `dist\PneumoLensAI\` folder. They don't need Python.
The `.exe` must be built on Windows, because PyInstaller can't build a Windows
app from Linux. This build still needs WebView2 and the Visual C++ runtime
installed on the target PC (see above).

### Standalone build (nothing to install on the target PC)

For servers and older or locked-down Windows PCs, build the standalone version.
It carries its own copies of everything the normal build takes from Windows:

```bat
build_windows_standalone.bat                     :: uses the WebView2 runtime installed on this PC
build_windows_standalone.bat --webview2 Microsoft.WebView2.FixedVersionRuntime.<ver>.x64.cab
build_windows_standalone.bat --trim-locales --zip
```

Output: `dist\standalone\PneumoLensAI\` (ship the whole folder, or the zip).

| Bundled | Where | Instead of |
|---|---|---|
| Edge WebView2 **Fixed Version** runtime | `webview2\` | the installed WebView2 Runtime |
| Visual C++ runtime (`msvcp140*.dll`, `vcruntime140*.dll`) | `_internal\` | the installed VC++ Redistributable |
| Python, packages, model, UI | `_internal\` | (already bundled by the normal build) |

* **WebView2:** for a release, download the official *Fixed Version* `.cab` (x64) from
  https://developer.microsoft.com/microsoft-edge/webview2/ and pass it with `--webview2`.
  Without it, the script copies the runtime installed on the build PC, skipping the
  parts a private copy doesn't need. `--trim-locales` keeps only English (US) and
  saves about 130 MB. On start-up the app uses `webview2\` if it's there, and also
  grants the WebView2 sandbox read access to that folder, without which the window
  stays blank outside Program Files.
* **Visual C++ runtime:** taken from the build PC's `System32`, so install the VC++
  Redistributable there once. The app adds `_internal\` to the DLL search path
  before onnxruntime loads, so the bundled copies are used even if Windows has
  none.
* **Still required on the target PC:** 64-bit **Windows 10 / Server 2016 or newer**
  (Python 3.14 and onnxruntime need it) and **.NET Framework 4.7.2+**. .NET is built
  into Windows 10 1803+ and Server 2019+, but Server 2016 needs the
  [.NET Framework 4.8 offline installer](https://dotnet.microsoft.com/download/dotnet-framework/net48).
  The window toolkit runs on .NET Framework, which is a part of Windows and can't be
  bundled, so the app checks for it on start-up and says what's missing.
* Windows 7 / 8.1 are not covered: Python 3.14, WebView2 (after version 109) and
  onnxruntime no longer run there.

## Files

| File | What it does |
|---|---|
| `app.py` | Creates the window and holds the `Api` class. Every public method can be called from JavaScript, and each call runs on its own thread, so the UI never freezes. |
| `xray_engine.py` | Reads PNG/JPG/TIFF/DICOM, preprocesses exactly like the server, runs ONNX, and has the band thresholds. |
| `clinical_engine.py` | Step 2: loads and validates `models/weight.json` and computes the 7 match scores, factors and alerts. |
| `models/weight.json` | The A/B/C/D weighting table with the theory for every entry (see above). |
| `ui/` | The page from the design. `app.js` holds step 1 (buttons, viewer, results), `clinical.js` step 2 (form, results, weighting table), `report.js` + `report.css` step 3 (report preview, sign-off, save, print). |
| `models/` | The fp32 ONNX model (29 MB), the most exact version. A PC doesn't need fp16. |
| `tests/test_engine.py` | Checks the app's scores against the PyTorch/server pipeline (tolerance 1e-4). |
| `tests/test_clinical.py` | Checks that weight.json is complete and valid, that a textbook case of each disease ranks first, and the edge cases. |
| `tests/test_ui.py` | Opens the real window and clicks through step 1 and step 2 (Upload → Analyze → Export, symptoms & labs, weighting table, import, Clear). |

## Behaviour

* **Bands:** HIGH ≥ 50%, MODERATE 30–50%, LOW < 30%. HIGH starts at **0.5
  because that is the model's operating point**: the scores are calibrated so
  that 0.5 is the decision threshold for every label. The design mockup used
  60%. To change the bands, edit `BANDS` in `xray_engine.py`.
* **11 pathologies are shown.** The model outputs 18. JSON/CSV exports
  contain all 18; edit `SHOWN_LABELS` to change which ones appear.
* **Preview vs analysis:** the viewer shows a downscaled 8-bit JPEG, and for
  DICOM a 0.5–99.5% contrast stretch. Analysis always uses the
  full-resolution original pixels. *Invert* changes the display only.
* **Device:** the drop-down lists what ONNX Runtime offers. Install
  `onnxruntime-directml` instead of `onnxruntime` to get "GPU · DirectML" on
  Windows. On CPU the analysis takes about 0.1–0.3 s.
* **Shortcuts:**
  * Ctrl+O upload (step 2: import lab file)
  * Ctrl+R analyze (step 2: run AI analysis)
  * Ctrl+S export (step 3: save report)
  * Ctrl+P print the report (step 3)
  * Enter in a step-2 field: next field
  * `+` / `−` / `0` zoom
  * `I` invert
  * Ctrl+T dark / light theme
  * mouse wheel zooms, drag pans, double-click fits the image
* **Not built yet:** a heatmap, Settings, sending to an EHR / DICOM SR,
  drag-and-drop of files, and compressed DICOM. JPEG-compressed DICOM needs
  `pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg`.

## Tests

```bash
python tests/test_engine.py     # scores vs reference
python tests/test_clinical.py   # weight.json + step-2 scoring
python tests/test_ui.py         # full click-through (window flashes on Windows)
```

`tests/reference_scores.json` was produced with the original PyTorch model
(see `~/Documents/xray_onnx`). If someone changes the reader, the
preprocessing or the model file, `test_engine.py` fails instead of the app
silently showing different numbers.
