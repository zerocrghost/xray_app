# X-Ray Analyzer – desktop app (step 1)

A Windows desktop app built with **pywebview**. It runs the chest X-ray model
**on the PC**: no server, no PyTorch, no internet.

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

1. Install **Python 3.12** from python.org and tick "Add python.exe to PATH".
2. Copy this `desktop` folder to the Windows PC, but leave out `.venv`.
3. Double-click **`run_windows.bat`**. The first run creates `.venv` and
   installs the packages, which takes a few minutes. After that the app starts
   in seconds.

Windows 10 and 11 already include Edge WebView2. On an old Windows 10 PC
without it, install the "Evergreen Runtime" from Microsoft.

### Build an .exe

```bat
build_windows.bat
```

This first runs the score test, then PyInstaller. To give the app to someone
else, ship the **whole** `dist\XRayAnalyzer\` folder. They don't need Python.
The `.exe` must be built on Windows, because PyInstaller can't build a Windows
app from Linux.

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
