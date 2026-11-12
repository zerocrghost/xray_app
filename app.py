"""
X-Ray Analyzer - desktop app (step 1: X-ray analysis).

pywebview opens a native window (Edge WebView2 on Windows) that shows ui/index.html.
The page calls the methods of `Api` below as  `await pywebview.api.<method>(...)`.
Every call runs on its own Python thread, so analysis does not freeze the UI.

Run:   python app.py            (add --debug to open the browser dev tools)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import threading
import traceback
from pathlib import Path

import onnxruntime as ort
import webview

import xray_engine as xe

APP_NAME = "X-Ray Analyzer"
APP_VERSION = "0.1.0"
# PyInstaller unpacks bundled files into sys._MEIPASS
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MODEL_PATH = BASE_DIR / "models" / "xray_densenet121.onnx"
UI_INDEX = BASE_DIR / "ui" / "index.html"
DISCLAIMER = "For research use only. Not intended for clinical diagnosis."


def _ok(**data):
    return {"ok": True, **data}


def _error(exc: Exception):
    traceback.print_exc()
    return {"ok": False, "error": str(exc) or exc.__class__.__name__}


class Api:
    """Public methods are callable from JavaScript. Attributes start with '_'
    so pywebview does not try to expose (and walk through) them."""

    def __init__(self):
        self._window: webview.Window | None = None
        self._model: xe.XRayModel | None = None
        self._image: xe.XRayImage | None = None
        self._result: dict | None = None
        self._lock = threading.Lock()      # one analysis / model change at a time

    # ------------------------------------------------------------------ startup
    def init(self):
        try:
            with self._lock:
                if self._model is None:
                    self._model = xe.XRayModel(MODEL_PATH)
            m = self._model
            return _ok(
                model=m.name,
                device=m.provider,
                devices=[{"id": p, "name": xe.PROVIDER_NAMES[p]} for p in m.available_providers()],
                shown_labels=xe.SHOWN_LABELS,
                bands=xe.BANDS,
                versions=f"{APP_NAME} {APP_VERSION} · ONNX Runtime {ort.__version__}",
                disclaimer=DISCLAIMER,
            )
        except Exception as e:
            return _error(e)

    def set_device(self, provider: str):
        try:
            with self._lock:
                self._model.set_provider(provider)
            return _ok(device=provider)
        except Exception as e:
            return _error(e)

    # ------------------------------------------------------------------ image
    def open_image(self):
        types = ("X-ray images (*.png;*.jpg;*.jpeg;*.dcm;*.dicom;*.tif;*.tiff;*.bmp)", "All files (*.*)")
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
        if not paths:
            return _ok(cancelled=True)
        return self.load_image(paths[0])

    def load_image(self, path: str):
        try:
            image = xe.read_image(path)
            preview = xe.preview_data_url(image)
            with self._lock:
                self._image, self._result = image, None
            return _ok(info=image.info, preview=preview)
        except Exception as e:
            return _error(e)

    def clear(self):
        with self._lock:
            self._image, self._result = None, None
        return _ok()

    # ------------------------------------------------------------------ analysis
    def analyze(self):
        try:
            with self._lock:
                if self._image is None:
                    raise RuntimeError("Upload an X-ray image first.")
                result = self._model.analyze(self._image)
                result.update(
                    file=self._image.info["file"],
                    model=self._model.name,
                    device=self._model.provider,
                    time=dt.datetime.now().isoformat(timespec="seconds"),
                )
                self._result = result
            return _ok(**result)
        except Exception as e:
            return _error(e)

    # ------------------------------------------------------------------ export
    def export_report(self):
        try:
            if self._result is None:
                raise RuntimeError("Run the analysis before exporting.")
            r = self._result
            default = Path(r["file"]).stem + "_xray_report.json"
            types = ("JSON report (*.json)", "CSV table (*.csv)")
            target = self._window.create_file_dialog(webview.FileDialog.SAVE,
                                                     save_filename=default, file_types=types)
            if not target:
                return _ok(cancelled=True)
            target = Path(target if isinstance(target, str) else target[0])
            if target.suffix.lower() not in (".json", ".csv"):
                target = target.with_suffix(".json")

            rows = sorted(r["scores"].items(), key=lambda kv: -kv[1])
            if target.suffix.lower() == ".csv":
                with open(target, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["label", "score", "level", "shown_in_app"])
                    for label, s in rows:
                        w.writerow([label, f"{s:.4f}", xe.band(s).upper(), label in xe.SHOWN_LABELS])
            else:
                report = {
                    "app": f"{APP_NAME} {APP_VERSION}",
                    "time": r["time"],
                    "image": self._image.info if self._image else {"file": r["file"]},
                    "model": r["model"],
                    "device": r["device"],
                    "operating_point": 0.5,
                    "bands": xe.BANDS,
                    "findings": [{"label": l, "score": round(s, 4), "level": xe.band(s).upper()}
                                 for l, s in rows if l in xe.SHOWN_LABELS],
                    "all_scores": {l: round(s, 6) for l, s in rows},
                    "timing_ms": {"preprocess": r["preprocess_ms"], "inference": r["inference_ms"]},
                    "disclaimer": DISCLAIMER,
                }
                target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            return _ok(path=str(target))
        except Exception as e:
            return _error(e)

    # ------------------------------------------------------------------ window
    def exit(self):
        self._window.destroy()


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--debug", action="store_true", help="open the browser dev tools")
    args = parser.parse_args()

    api = Api()
    api._window = webview.create_window(
        APP_NAME, url=str(UI_INDEX), js_api=api,
        width=1440, height=900, min_size=(1180, 760), background_color="#0c111c",
    )
    webview.start(debug=args.debug)


if __name__ == "__main__":
    main()
