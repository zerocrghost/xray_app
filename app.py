"""
PneumoLens AI - desktop app for AI-assisted pneumonia / lung disease analysis
(landing page + step 1: X-ray analysis).

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
import os
import sys
import threading
import traceback
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# Standalone build (tools/build_standalone.py): the Visual C++ runtime (msvcp140*.dll) is bundled
# in _internal\. Put that folder on the DLL search path *before* onnxruntime / scikit-image load,
# so they never depend on the runtime being installed in Windows.
if sys.platform == "win32" and FROZEN:
    os.add_dll_directory(sys._MEIPASS)

import onnxruntime as ort
import webview

import xray_engine as xe

APP_NAME = "PneumoLens AI"
APP_VERSION = "0.1.0"
# PyInstaller unpacks bundled files into sys._MEIPASS
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MODEL_PATH = BASE_DIR / "models" / "xray_densenet121.onnx"
UI_INDEX = BASE_DIR / "ui" / "index.html"
ICON_PATH = BASE_DIR / "ui" / "logo.ico"
# folder of PneumoLensAI.exe (or of app.py); a standalone build ships its own WebView2 runtime here
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLED_WEBVIEW2 = APP_DIR / "webview2"
# Outer window size (title bar + borders included; pywebview scales it for DPI).
# The minimum keeps a 1024 x 761 page area (frame = 16 x 39 px): the smallest size at which
# every part of the design (all 11 result rows, header, action bar, landing page) is shown
# without being cut off. Measured with the overflow check in headless Edge and in WebView2.
WINDOW_SIZE = (1440, 900)
MIN_WINDOW_SIZE = (1040, 800)
DISCLAIMER = "For research use only. Not intended for clinical diagnosis."


# ---------------------------------------------------------------------- user settings
# %APPDATA%\PneumoLens AI\settings.json  (e.g. {"theme": "light"})
SETTINGS_PATH = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME / "settings.json"
THEME_BACKGROUND = {"dark": "#0c111c", "light": "#f2f5fa"}     # = --bg in ui/style.css


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**changes):
    data = {**load_settings(), **changes}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def saved_theme() -> str:
    """'light' / 'dark' from the settings, else the Windows app theme (default: dark)."""
    t = load_settings().get("theme")
    if t in THEME_BACKGROUND:
        return t
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            pass
    return "dark"


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

    def set_theme(self, theme: str):
        try:
            if theme not in THEME_BACKGROUND:
                raise ValueError(f"Unknown theme: {theme}")
            save_settings(theme=theme)
            return _ok(theme=theme)
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
        # pywebview only accepts letters, digits, '_' and spaces in the description (no '-')
        types = ("Xray images (*.png;*.jpg;*.jpeg;*.dcm;*.dicom;*.tif;*.tiff;*.bmp)", "All files (*.*)")
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


WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"   # Evergreen bootstrapper


def _has_webview2() -> bool:
    """True if the Edge WebView2 runtime is installed (same registry check pywebview uses).
    Without it pywebview silently falls back to MSHTML (Internet Explorer 11), which
    cannot render this UI (CSS variables, flex gap, modern JS) - the layout looks broken."""
    if sys.platform != "win32":
        return True
    import winreg
    guid = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{guid}"),
                      (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{guid}"),
                      (winreg.HKEY_CURRENT_USER, rf"Software\{guid}")):
        try:
            with winreg.OpenKey(hive, key) as k:
                version = winreg.QueryValueEx(k, "pv")[0]
            if version and version != "0.0.0.0":
                return True
        except OSError:
            pass
    return False


def _fatal(msg: str, url: str):
    """Explain a missing prerequisite, offer to open its download page, and quit."""
    print(msg.replace("\n\n", "\n"), file=sys.stderr)
    import ctypes
    MB_YESNO, MB_ICONERROR, IDYES = 0x4, 0x10, 6
    if ctypes.windll.user32.MessageBoxW(None, f"{msg}\n\n{url}\n\nOpen the download page now?",
                                        APP_NAME, MB_YESNO | MB_ICONERROR) == IDYES:
        import webbrowser
        webbrowser.open(url)
    sys.exit(1)


def _use_bundled_webview2() -> bool:
    """Standalone build: use the private WebView2 runtime in .\\webview2 instead of an installed one."""
    if not (BUNDLED_WEBVIEW2 / "msedgewebview2.exe").is_file():
        return False
    # WebView2 renderers run in an AppContainer sandbox. Outside Program Files the folder needs read
    # access for "ALL (RESTRICTED) APPLICATION PACKAGES", or the window stays blank. Grant it once per
    # location (no admin rights needed for the user's own folders; Program Files already has it).
    done = load_settings().get("webview2_acl")
    if done != str(BUNDLED_WEBVIEW2):
        import subprocess
        ok = True
        for sid in ("*S-1-15-2-1", "*S-1-15-2-2"):
            r = subprocess.run(["icacls", str(BUNDLED_WEBVIEW2), "/grant", f"{sid}:(OI)(CI)(RX)", "/Q"],
                               capture_output=True, creationflags=0x08000000)     # CREATE_NO_WINDOW
            ok &= r.returncode == 0
        if ok:
            try:
                save_settings(webview2_acl=str(BUNDLED_WEBVIEW2))
            except OSError:
                pass
    webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(BUNDLED_WEBVIEW2)
    return True


def _require_webview2():
    if sys.platform != "win32" or _use_bundled_webview2() or _has_webview2():
        return
    _fatal("The Microsoft Edge WebView2 Runtime is not installed.\n\n"
           f"{APP_NAME} needs it to display its window (without it Windows falls back to "
           "Internet Explorer and the layout is broken).\n\n"
           "Install it, or use the standalone build of the app, which includes it.", WEBVIEW2_URL)


DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet-framework/net48"


def _require_dotnet():
    """pythonnet (which drives the WinForms window) needs .NET Framework 4.7.2+. It is part of
    Windows 10 1803+ / Server 2019+, but not of Server 2016 or older Windows 10 - and it cannot be
    bundled, so check for it instead of failing with a cryptic error."""
    if sys.platform != "win32":
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
            release = winreg.QueryValueEx(k, "Release")[0]
    except OSError:
        release = 0
    if release < 461808:            # 461808 = .NET Framework 4.7.2
        _fatal(".NET Framework 4.7.2 or newer is not installed.\n\n"
               f"{APP_NAME} needs it to open its window. Install .NET Framework 4.8 "
               "(the offline installer works without internet access on the target PC).", DOTNET_URL)


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--debug", action="store_true", help="open the browser dev tools")
    args = parser.parse_args()
    _require_dotnet()
    _require_webview2()

    api = Api()
    theme = saved_theme()
    api._window = webview.create_window(
        APP_NAME, url=f"{UI_INDEX}#theme={theme}", js_api=api,     # the page applies it before painting
        width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=MIN_WINDOW_SIZE,
        background_color=THEME_BACKGROUND[theme],
    )
    webview.start(gui="edgechromium", debug=args.debug, icon=str(ICON_PATH))


if __name__ == "__main__":
    main()
