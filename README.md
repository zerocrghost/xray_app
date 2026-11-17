# PneumoLens AI – desktop app (landing page + step 1)

<img src="ui/logo.svg" width="64" align="right" alt="PneumoLens AI logo">

**PneumoLens AI** is an AI-assisted pneumonia and lung-disease screening tool for chest
X-rays. It is a Windows desktop app built with **pywebview**, and it runs the chest
X-ray model **on the PC**: no server, no PyTorch, no internet.

The app opens on a landing page. **Start New Analysis** (or Enter) goes to step 1,
X-ray analysis, and **Open X-ray Image…** (Ctrl+O) goes straight there with an image
loaded. Click the logo in the header to return to the landing page.

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
| `ui/` | The page from the design. `app.js` holds the button logic, the viewer (zoom, pan, invert) and the result rendering. |
| `models/` | The fp32 ONNX model (29 MB), the most exact version. A PC doesn't need fp16. |
| `tests/test_engine.py` | Checks the app's scores against the PyTorch/server pipeline (tolerance 1e-4). |
| `tests/test_ui.py` | Opens the real window and clicks Upload → Analyze → Export → Clear. |

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
  * Ctrl+O upload
  * Ctrl+R analyze
  * Ctrl+S export
  * `+` / `−` / `0` zoom
  * `I` invert
  * Ctrl+T dark / light theme
  * mouse wheel zooms, drag pans, double-click fits the image
* **Not built yet:** "Next: Symptoms & Labs" (step 2), a heatmap, Settings,
  drag-and-drop of files, and compressed DICOM. JPEG-compressed DICOM needs
  `pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg`.

## Tests

```bash
python tests/test_engine.py     # scores vs reference
python tests/test_ui.py         # full click-through (window flashes on Windows)
```

`tests/reference_scores.json` was produced with the original PyTorch model
(see `~/Documents/xray_onnx`). If someone changes the reader, the
preprocessing or the model file, `test_engine.py` fails instead of the app
silently showing different numbers.
