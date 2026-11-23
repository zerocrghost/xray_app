"""
PneumoLens AI - desktop app for AI-assisted pneumonia / lung disease analysis
(landing page, step 1: X-ray analysis, step 2: symptoms & labs weighted by models/weight.json).

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

import case_store as cs
import clinical_engine as ce
import xray_engine as xe

APP_NAME = "PneumoLens AI"
APP_VERSION = "0.4.0"
# PyInstaller unpacks bundled files into sys._MEIPASS
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MODEL_PATH = BASE_DIR / "models" / "xray_densenet121.onnx"
WEIGHTS_PATH = BASE_DIR / "models" / "weight.json"         # step 2: A/B/C/D weighting table
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


REPORT_DEFAULTS = {"candidate_ratio": 0.5, "max_candidates": 3}     # final report: which diseases to list
DATASET_DEFAULT = "./dataset"                 # case data folder; relative paths are relative to the app folder
FALLBACK_DATASET = SETTINGS_PATH.parent / "dataset_fallback"     # used only if the dataset folder is not writable


def dataset_dir() -> Path:
    raw = str(load_settings().get("dataset_dir") or DATASET_DEFAULT)
    p = Path(os.path.expandvars(raw)).expanduser()
    return (p if p.is_absolute() else APP_DIR / p).resolve()


def _check_writable(folder: Path):
    """Create the folder if needed and prove that a file can be written there."""
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / f".write_test_{os.getpid()}"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def report_settings() -> dict:
    """Final-report candidate rule: list every disease whose match is at least candidate_ratio x the top
    match (e.g. 0.5 = 50 % of the first candidate's score), at most max_candidates of them."""
    s = load_settings()
    out = dict(REPORT_DEFAULTS)
    try:
        out["candidate_ratio"] = min(1.0, max(0.05, float(s.get("candidate_ratio", out["candidate_ratio"]))))
        out["max_candidates"] = min(7, max(1, int(s.get("max_candidates", out["max_candidates"]))))
    except (TypeError, ValueError):
        pass
    return out


def load_clinical_model() -> tuple[ce.ClinicalModel, str | None]:
    """weight.json plus the user's weight edits from settings.json ("weight_overrides").
    If the edits no longer fit weight.json (e.g. after an update of the table), the app still starts with the
    plain table and returns a warning; the stored edits are kept until the user saves or resets them."""
    overrides = load_settings().get("weight_overrides") or {}
    try:
        return ce.ClinicalModel(WEIGHTS_PATH, overrides), None
    except ValueError as e:
        if not overrides:
            raise                                   # weight.json itself is broken: refuse to start
        return ce.ClinicalModel(WEIGHTS_PATH), f"Your weight edits were not applied, weight.json is used as is. {e}"


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
        self._clinical_model: ce.ClinicalModel | None = None
        self._weights_warning: str | None = None    # stored weight edits that could not be applied
        self._clinical: dict | None = None          # last step-2 result (+ the inputs it used)
        self._report: dict | None = None            # last step-3 report
        self._report_id: str | None = None          # = case id; stays the same for one patient
        self._lock = threading.Lock()      # one analysis / model change at a time
        # ---- the current case (patient page + steps 1-3); saved once per change to the dataset folder
        self._case_created: str | None = None
        self._patient: dict = {}
        self._review: dict = {}
        self._clinical_inputs: dict = {}
        self._reports: list[dict] = []              # report files the doctor saved (PDF / DOCX)
        self._image_sha: str | None = None
        self._loaded_from: str | None = None        # dataset file this case was opened from (review)
        self._store = cs.CaseStore(dataset_dir(), FALLBACK_DATASET)
        self._case_lock = threading.RLock()         # state updates and saves never interleave
        self._close_ok = False                      # True once the case is safely saved and the window may close
        self._close_asked = 0.0

    # ------------------------------------------------------------------ startup
    def init(self):
        try:
            with self._lock:
                if self._model is None:
                    self._model = xe.XRayModel(MODEL_PATH)
                if self._clinical_model is None:
                    self._clinical_model, self._weights_warning = load_clinical_model()
            m = self._model
            return _ok(
                clinical=self._clinical_model.for_ui(),
                weights_warning=self._weights_warning,
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

    def get_settings(self):
        s = load_settings()
        return _ok(**report_settings(), dataset_dir=s.get("dataset_dir") or DATASET_DEFAULT,
                   dataset_path=str(dataset_dir()), dataset_default=DATASET_DEFAULT, hospital=s.get("hospital", ""),
                   weights=self._weights_info())

    def _weights_info(self) -> dict | None:
        cm = self._clinical_model
        if cm is None:
            return None
        return {"label": cm.label(), "edits": cm.edit_count, "diseases": len(cm.overrides),
                "warning": self._weights_warning, "ignored": cm.ignored_overrides}

    def set_weights(self, overrides: dict):
        """Weight edits from the weighting-table editor: {disease: {input: {group, weight}}} (only the changed
        items; an empty object = back to weight.json). Checked like weight.json, then saved to settings.json and
        used for every analysis from now on. A rejected edit changes nothing."""
        try:
            model = ce.ClinicalModel(WEIGHTS_PATH, overrides or {})     # raises ValueError with every problem
            save_settings(weight_overrides=model.overrides)
            with self._lock:
                self._clinical_model, self._weights_warning = model, None
            return _ok(clinical=model.for_ui(), weights=self._weights_info())
        except Exception as e:
            return _error(e)

    def reset_weights(self):
        return self.set_weights({})

    def set_settings(self, changes: dict):
        """Application settings from the Settings dialog (only known keys are accepted)."""
        try:
            clean = {}
            if "candidate_ratio" in changes:
                clean["candidate_ratio"] = min(1.0, max(0.05, float(changes["candidate_ratio"])))
            if "max_candidates" in changes:
                clean["max_candidates"] = min(7, max(1, int(changes["max_candidates"])))
            if "hospital" in changes:
                clean["hospital"] = str(changes["hospital"]).strip()[:120]
            if "dataset_dir" in changes:
                raw = str(changes["dataset_dir"]).strip() or DATASET_DEFAULT
                p = Path(os.path.expandvars(raw)).expanduser()
                p = (p if p.is_absolute() else APP_DIR / p).resolve()
                try:
                    _check_writable(p)                # refuse a folder that cannot store the data
                except OSError as e:
                    raise ValueError(f"The dataset folder cannot be used: {p} ({e.strerror or e})") from e
                clean["dataset_dir"] = raw
            save_settings(**clean)
            with self._case_lock:
                self._store.dataset_dir = dataset_dir()
            return self.get_settings()
        except Exception as e:
            return _error(e)

    def browse_folder(self):
        paths = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(dataset_dir()))
        if not paths:
            return _ok(cancelled=True)
        return _ok(path=paths[0] if isinstance(paths, (list, tuple)) else paths)

    def open_dataset_folder(self):
        try:
            p = dataset_dir()
            _check_writable(p)
            os.startfile(str(p))                      # noqa: S606 - opens Explorer
            return _ok(path=str(p))
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
            sha = cs.file_sha256(image.path)
            with self._lock:
                self._image, self._result = image, None
                self._image_sha = sha                  # the image belongs to the current patient case
            return _ok(info=image.info, preview=preview)
        except Exception as e:
            return _error(e)

    def clear(self):
        with self._lock:
            self._image, self._result, self._image_sha = None, None, None
        return _ok()

    # ------------------------------------------------------------------ step 2: clinical data
    def analyze_clinical(self, inputs: dict):
        """Score the 7 diseases from the step-2 inputs (+ the step-1 X-ray scores, if analyzed)."""
        try:
            xray = self._result["scores"] if self._result else None
            with self._case_lock:
                self._clinical_inputs = dict(inputs or {})
            r = self._clinical_model.score(self._scoring_inputs(inputs), xray)
            r["time"] = dt.datetime.now().isoformat(timespec="seconds")
            self._clinical = {"inputs": inputs or {}, "result": r}
            return _ok(**r)
        except Exception as e:
            return _error(e)

    def clear_clinical(self):
        self._clinical = None
        return _ok()

    # ------------------------------------------------------------------ step 3: final report
    def _scoring_inputs(self, inputs: dict | None) -> dict:
        """Step-2 inputs plus the patient's age from the patient page (CURB-65 severity sign)."""
        out = dict(inputs or {})
        age = self._patient.get("age")
        if age not in (None, ""):
            out["age"] = age
        return out

    def _compute_report(self, inputs: dict, review: dict) -> dict:
        """Everything the final report shows (preview, PDF, DOCX and the dataset record use it): the combined
        ranking of the 7 diseases, the X-ray (step 1) and clinical (step 2) part of each, the reasons from both
        steps, severity, candidates, the lung-related X-ray findings and the entered clinical data."""
        cm = self._clinical_model
        r, img = self._result, self._image
        score = cm.score(self._scoring_inputs(inputs), r["scores"] if r else None)
        sel = cm.table.get("xray_selection", {"used": {}, "not_used": {}})
        xray = None
        if r:
            lung = sorted(({"label": l.replace("_", " "), "score": round(s, 4), "level": xe.band(s).upper(),
                            "reason": sel["used"][l]} for l, s in r["scores"].items() if l in sel["used"]),
                          key=lambda x: -x["score"])
            other = [{"label": l.replace("_", " "), "score": round(r["scores"][l], 4), "reason": why}
                     for l, why in sel["not_used"].items() if l in r["scores"]]
            xray = {"model": r["model"], "device": r["device"], "time": r["time"], "lung": lung, "not_used": other,
                    "flagged": sum(1 for x in lung if x["level"] == "HIGH"), "operating_point": 0.5}
        data = cm.value_rows(inputs)
        n_rows = len(data["rows"])
        # section titles for the report table: history / vital signs / lab subgroups / spirometry
        titles = {**cm.table.get("categories", {}), **{g["id"]: g["title"] for g in cm.table.get("lab_groups", [])}}
        clinical = {**data, "titles": titles,
                    "entered": len(data["present"]) + len(data["absent"]) + bool(data["sounds"]) + n_rows,
                    "abnormal": sum(1 for x in data["rows"] if x["flag"] in ("HIGH", "LOW"))}

        def slim(f):
            return {k: f[k] for k in ("label", "value", "group", "effect", "why", "exclusion")}

        diseases = []
        for d in score["diseases"]:
            diseases.append({
                "id": d["id"], "name": d["name"], "match": d["match"], "coverage": d["coverage"],
                "low_confidence": d["low_confidence"], "level": _level(d["match"]), "parts": d["parts"],
                "severity": d["severity"],
                "reasons": {k: {side: [slim(f) for f in v[side]] for side in ("for", "against")}
                            for k, v in d["reasons"].items()},
                "summary": d["summary"], "follow_up": d["follow_up"],
                "missing": [m for m in d["missing"] if m["group"] in ("A", "B")][:6],
            })
        # candidates: the first disease, plus every other one scoring at least ratio x the first (max N)
        rs = report_settings()
        cut = diseases[0]["match"] * rs["candidate_ratio"]
        n_cand = 1 + sum(1 for d in diseases[1:rs["max_candidates"]] if d["match"] >= cut)
        candidates = {"ids": [d["id"] for d in diseases[:n_cand]], "ratio": rs["candidate_ratio"],
                      "max": rs["max_candidates"], "cutoff": round(cut, 4), "clear": n_cand == 1}
        info = img.info if img else (self._result or {}).get("image_info", {})
        return {
            "id": self._ensure_case(),
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "app": f"{APP_NAME} {APP_VERSION}",
            "patient": {**self._patient, "file": info.get("file"), "study_date": info.get("study_date"),
                        "view": info.get("view"), "format": info.get("format"),
                        "size": f"{info['width']} × {info['height']} px" if info.get("width") else None},
            "xray": xray,
            "clinical": clinical if clinical["entered"] else None,
            "diseases": diseases,
            "candidates": candidates,
            "alerts": score["alerts"],
            "weights": score["weights_label"],
            "weight_overrides": cm.overrides,
            "review": review or {},
            "disclaimer": DISCLAIMER,
        }

    def final_report(self, inputs: dict | None = None, review: dict | None = None):
        try:
            with self._case_lock:
                if inputs is not None:
                    self._clinical_inputs = dict(inputs)
                if review is not None:
                    self._review = dict(review)
                self._report = self._compute_report(self._clinical_inputs, self._review)
            return _ok(**self._report, reviewer_default=load_settings().get("reviewer", ""),
                       saved_reports=self._reports)
        except Exception as e:
            return _error(e)

    def remember_reviewer(self, name: str):
        try:
            save_settings(reviewer=str(name)[:80])
            return _ok()
        except Exception as e:
            return _error(e)

    def save_report(self, fmt: str, html: str | None = None, review: dict | None = None, options: dict | None = None):
        """Save the final report where the doctor chooses (PDF printed by WebView2 from the preview, or DOCX),
        then save the case data to the dataset folder (once per change)."""
        try:
            if self._report is None:
                raise RuntimeError("Open the final report first.")
            fmt = fmt.lower()
            kinds = {"pdf": "PDF report (*.pdf)", "docx": "Word report (*.docx)"}
            if fmt not in kinds:
                raise ValueError(f"Unknown format: {fmt}")
            with self._case_lock:
                if review is not None:
                    self._review = dict(review)
                self._report = self._compute_report(self._clinical_inputs, self._review)
            rep = self._report
            pid = self._patient.get("patient_id") or self._patient.get("name") or ""
            stem = rep["id"] + (f"_{_safe(pid)}" if pid else "")
            target = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{stem}.{fmt}",
                                                     file_types=(kinds[fmt],))
            if not target:
                return _ok(cancelled=True)
            target = Path(target if isinstance(target, str) else target[0])
            if target.suffix.lower() != "." + fmt:
                target = target.with_suffix("." + fmt)
            if fmt == "pdf":
                _print_to_pdf(self._window, target)
            else:
                from report_docx import build_docx
                jpeg = _image_jpeg(self._image) if (options or {}).get("image", True) and self._image else None
                build_docx(rep, self._patient, self._review, jpeg, BASE_DIR / "ui" / "logo.png", target, DISCLAIMER)
            with self._case_lock:
                self._reports.append({"format": fmt, "path": str(target),
                                      "saved_at": dt.datetime.now().isoformat(timespec="seconds")})
                data = self.save_case("report")
            return _ok(path=str(target), data=data)
        except Exception as e:
            return _error(e)

    # ------------------------------------------------------------------ case data (dataset folder)
    def _ensure_case(self) -> str:
        with self._case_lock:
            if not self._report_id:
                self._report_id = cs.new_case_id()
                self._case_created = dt.datetime.now().isoformat(timespec="seconds")
            return self._report_id

    def _has_data(self) -> bool:
        """Is there anything worth saving? (Defaults such as the hospital name or today's exam date are not.)"""
        prefilled = {"hospital", "exam_date", "visit"}
        patient = any(str(v).strip() for k, v in self._patient.items() if k not in prefilled and v not in (None, ""))
        clinical = any(v not in (None, "", []) for v in self._clinical_inputs.values())   # "no" answers count
        # the reviewer name alone is not case data: it is remembered from the last report
        return bool(patient or clinical or self._image is not None or self._result or self._reports
                    or any(self._review.get(k) for k in ("notes", "signed_at")))

    def update_case(self, data: dict):
        """The page sends its current state (patient page, step-2 inputs, review fields) after every edit, so
        Python always holds the latest data - even if the window is closed with the X button."""
        try:
            with self._case_lock:
                if isinstance(data.get("patient"), dict):
                    self._patient = {k: v for k, v in data["patient"].items() if v not in (None, "")}
                if isinstance(data.get("clinical_inputs"), dict):
                    self._clinical_inputs = dict(data["clinical_inputs"])
                if isinstance(data.get("review"), dict):
                    self._review = dict(data["review"])
                if self._has_data():
                    self._ensure_case()
            return _ok(case_id=self._report_id)
        except Exception as e:
            return _error(e)

    def _build_record(self) -> dict:
        """The dataset record of the current case. Contains no save time, so unchanged data gives the same hash."""
        cm = self._clinical_model
        r = self._result
        xray = None
        if self._image is not None or r:
            info = self._image.info if self._image is not None else (r or {}).get("image_info", {})
            xray = {"file": info.get("file"), "path": str(self._image.path) if self._image is not None else
                    (r or {}).get("image_path"), "sha256": self._image_sha, "info": info,
                    "analysis": None if not r else {
                        "model": r.get("model"), "device": r.get("device"), "analyzed_at": r.get("time"),
                        "scores": {k: round(v, 6) for k, v in r["scores"].items()},
                        "preprocess_ms": r.get("preprocess_ms"), "inference_ms": r.get("inference_ms")}}
        values = cm.normalize(self._scoring_inputs(self._clinical_inputs))
        analysis = None
        if r or any(not k.startswith("_") for k in values):
            rep = self._compute_report(self._clinical_inputs, self._review)
            analysis = {
                "weights": rep["weights"], "weight_overrides": rep["weight_overrides"],
                "alerts": rep["alerts"], "candidates": rep["candidates"],
                "diseases": [{"id": d["id"], "name": d["name"], "match": d["match"], "coverage": d["coverage"],
                              "level": d["level"], "parts": {k: {x: d["parts"][k][x] for x in ("match", "used", "neutral")}
                                                             for k in ("xray", "clinical")},
                              "severity": {"grade": d["severity"]["grade"], "points": d["severity"]["points"],
                                           "signs": [s for s in d["severity"]["signs"] if s["level"] != "none"]}}
                             for d in rep["diseases"]],
            }
        return {
            "schema": cs.SCHEMA,
            "case_id": self._ensure_case(),
            "created": self._case_created,
            "app": f"{APP_NAME} {APP_VERSION}",
            "patient": self._patient,
            "xray": xray,
            "clinical": {"inputs": self._clinical_inputs,
                         "values": {k: v for k, v in values.items() if not k.startswith("_")}} if self._clinical_inputs else None,
            "analysis": analysis,
            "review": self._review,
            "reports": self._reports,
            "opened_from": self._loaded_from,
        }

    def save_case(self, reason: str = "manual"):
        """Save the current case to the dataset folder: one file per case, rewritten only when the data changed.
        Returns ok=False only if the data could not be stored anywhere (dataset folder and fallback both failed)."""
        try:
            with self._case_lock:
                if not self._has_data():
                    return _ok(saved=False, empty=True)
                res = self._store.save(self._build_record(), reason)
            if res["saved"] or res["unchanged"]:
                return _ok(**res)
            return {**res, "ok": False, "error": f"The case data could not be saved: {res['error']}"}
        except Exception as e:
            return _error(e)

    def _reset_case(self):
        with self._case_lock, self._lock:
            self._image = self._result = self._clinical = self._report = None
            self._report_id = self._case_created = self._image_sha = self._loaded_from = None
            self._patient, self._review, self._clinical_inputs, self._reports = {}, {}, {}, []
            self._store.reset()

    def new_patient(self, force: bool = False):
        """Save the current case (unless force after a failed save), then start an empty one."""
        res = self.save_case("new_patient")
        if not res["ok"] and not force:
            return res
        self._reset_case()
        return _ok(data=res)

    def case_status(self):
        with self._case_lock:
            return _ok(case_id=self._report_id, has_data=self._has_data(), revision=self._store.revision,
                       saved_path=str(self._store.last_path) if self._store.last_path else None,
                       reports=self._reports, dataset=str(dataset_dir()))

    # ------------------------------------------------------------------ open a saved case (review)
    def open_case(self):
        """Load a case from the dataset folder (or an older exported JSON report) for review."""
        try:
            folder = dataset_dir()
            folder.mkdir(parents=True, exist_ok=True)
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=str(folder),
                                                    file_types=("Case data (*.json)", "All files (*.*)"))
            if not paths:
                return _ok(cancelled=True)
            return self.load_case(paths[0])
        except Exception as e:
            return _error(e)

    def load_case(self, path: str):
        try:
            path = Path(path)
            rec = cs.load_record(path)
            if not (rec.get("schema", "").startswith("pneumolens.case") or "xray" in rec or "clinical" in rec):
                raise ValueError(f"{path.name} is not a PneumoLens case file.")
            # the current case is saved first, so opening another case never loses data
            res = self.save_case("open_other_case")
            if not res["ok"]:
                return res
            self._reset_case()
            warn = []
            with self._case_lock:
                legacy = not rec.get("schema")
                self._report_id = rec.get("case_id") or (rec.get("report_id") if legacy else None) or cs.new_case_id()
                self._case_created = rec.get("created") or dt.datetime.now().isoformat(timespec="seconds")
                self._patient = dict(rec.get("patient") or {})
                self._review = dict(rec.get("review") or {})
                self._reports = list(rec.get("reports") or [])
                clin = rec.get("clinical") or {}
                self._clinical_inputs = dict(clin.get("inputs") or {})
                self._loaded_from = str(path)
                x = rec.get("xray") or {}
                preview, info, scores = None, x.get("info") or x.get("image") or {}, None
                an = x.get("analysis") or ({"scores": x["all_scores"], "model": x.get("model"), "device": x.get("device"),
                                            "analyzed_at": x.get("time")} if x.get("all_scores") else None)
                img_path = x.get("path") or info.get("path")
                if img_path and Path(img_path).is_file():
                    sha = cs.file_sha256(img_path)
                    if x.get("sha256") and sha != x["sha256"]:
                        warn.append("The X-ray file has changed since this case was saved; the stored scores are shown.")
                    image = xe.read_image(img_path)
                    with self._lock:
                        self._image, self._image_sha = image, sha
                    preview, info = xe.preview_data_url(image), image.info
                elif x:
                    warn.append("The X-ray image file was not found; the stored X-ray scores are shown without the image.")
                    self._image_sha = x.get("sha256")
                if an and an.get("scores"):
                    scores = an["scores"]
                    self._result = {"scores": scores, "model": an.get("model") or self._model.name,
                                    "device": an.get("device") or "", "time": an.get("analyzed_at") or "",
                                    "preprocess_ms": an.get("preprocess_ms") or 0, "inference_ms": an.get("inference_ms") or 0,
                                    "file": info.get("file") or "", "image_info": info, "image_path": img_path}
                # this case already exists on disk: an unchanged case is not written again
                if not legacy and path.parent.resolve() in (dataset_dir(), FALLBACK_DATASET.resolve()):
                    self._store.reset(int(rec.get("revision") or 0), cs.content_hash(self._build_record()), path)
            return _ok(case_id=self._report_id, patient=self._patient, review=self._review,
                       clinical_inputs=self._clinical_inputs, reports=self._reports,
                       xray={"info": info, "preview": preview, "result": self._result} if (preview or self._result) else None,
                       warnings=warn, file=path.name, previous=res)
        except Exception as e:
            return _error(e)

    def import_clinical(self):
        """Read step-2 inputs from a file: JSON ({"wbc": 12.1, "fever": true, ...} or an exported report)
        or CSV with two columns  name,value  (e.g. "WBC,12.1"). Names may be ids or the short labels."""
        try:
            types = ("Lab data (*.json;*.csv;*.txt)", "All files (*.*)")
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
            if not paths:
                return _ok(cancelled=True)
            path = Path(paths[0])
            raw = _read_lab_file(path)
            inputs, unknown = _map_lab_names(raw, self._clinical_model)
            if not inputs:
                raise ValueError(f"No known items in {path.name}. Use names like WBC, ESR, SpO2, BT, fever ...")
            return _ok(inputs=inputs, unknown=unknown, file=path.name, count=len(raw) - len(unknown))
        except Exception as e:
            return _error(e)

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
        """Save the X-ray result and/or the step-2 clinical result as JSON or CSV."""
        try:
            r, c = self._result, self._clinical
            if r is None and c is None:
                raise RuntimeError("Run an analysis before exporting.")
            stem = Path(r["file"]).stem if r else "clinical"
            default = stem + ("_report.json" if c else "_xray_report.json")
            types = ("JSON report (*.json)", "CSV table (*.csv)")
            target = self._window.create_file_dialog(webview.FileDialog.SAVE,
                                                     save_filename=default, file_types=types)
            if not target:
                return _ok(cancelled=True)
            target = Path(target if isinstance(target, str) else target[0])
            if target.suffix.lower() not in (".json", ".csv"):
                target = target.with_suffix(".json")

            rows = sorted(r["scores"].items(), key=lambda kv: -kv[1]) if r else []
            if target.suffix.lower() == ".csv":
                with open(target, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if r:
                        w.writerow(["label", "score", "level", "shown_in_app"])
                        for label, s in rows:
                            w.writerow([label, f"{s:.4f}", xe.band(s).upper(), label in xe.SHOWN_LABELS])
                    if c:
                        if r:
                            w.writerow([])
                        w.writerow(["disease", "match", "coverage", "low_confidence"])
                        for d in c["result"]["diseases"]:
                            w.writerow([d["name"], f"{d['match']:.4f}", f"{d['coverage']:.4f}", d["low_confidence"]])
                        w.writerow([])
                        w.writerow(["input", "value"])
                        for k, v in c["result"]["values"].items():
                            w.writerow([k, ";".join(v) if isinstance(v, list) else v])
            else:
                report = {"app": f"{APP_NAME} {APP_VERSION}", "disclaimer": DISCLAIMER}
                if r:
                    report["xray"] = {
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
                    }
                if c:
                    cr = c["result"]
                    report["clinical"] = {
                        "time": cr["time"],
                        "weights": cr.get("weights_label") or f"{WEIGHTS_PATH.name} v{cr['table_version']}",
                        "weight_overrides": self._clinical_model.overrides,
                        "used_xray": cr["used_xray"],
                        "inputs": cr["values"],
                        "alerts": cr["alerts"],
                        "diseases": [{"name": d["name"], "match": d["match"], "coverage": d["coverage"],
                                      "low_confidence": d["low_confidence"],
                                      "factors": [{k: f[k] for k in ("label", "group", "weight", "evidence", "effect", "value")}
                                                  for f in d["factors"]]}
                                     for d in cr["diseases"]],
                    }
                target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            return _ok(path=str(target))
        except Exception as e:
            return _error(e)

    # ------------------------------------------------------------------ window
    def exit(self, force: bool = False):
        """Save the case data, then close. If the data cannot be stored anywhere, the window stays open
        (unless the user explicitly chose to exit anyway: force=True)."""
        res = self.save_case("exit")
        if not res["ok"] and not force:
            return res
        self._close_ok = True
        self._window.destroy()
        return _ok(data=res)

    def close_cancelled(self):
        """The user cancelled the exit dialog: a later X click asks again instead of closing."""
        self._close_asked = 0.0
        return _ok()

    def _on_closing(self):
        """Window X button. The case data is saved before the window closes; if a report is not saved yet the
        page asks first (same dialog as Exit). A second X click while the dialog is open saves and closes."""
        import time
        if self._close_ok:
            return True
        with self._case_lock:
            has_data = self._has_data()
        if not has_data:
            return True
        now = time.time()
        if now - self._close_asked < 20:                  # asked already: save, and close if that worked
            res = self.save_case("window_closed")
            self._close_ok = bool(res.get("ok"))
            return self._close_ok
        self._close_asked = now

        def ask():
            try:
                self._window.evaluate_js("openExitModal()")
            except Exception:                              # the page cannot ask: save and close anyway
                if self.save_case("window_closed").get("ok"):
                    self._close_ok = True
                    self._window.destroy()
        threading.Thread(target=ask, daemon=True).start()
        return False                                       # cancel this close; the dialog decides


def _level(m: float) -> str:
    """Display level of a match score (same thresholds as the page)."""
    return "HIGH" if m >= 0.65 else "MODERATE" if m >= 0.45 else "LOW"


def _image_jpeg(image) -> bytes | None:
    """The preview JPEG of the X-ray (same image as in the PDF) for the DOCX report."""
    import base64
    try:
        url = xe.preview_data_url(image)
        return base64.b64decode(url.split(",", 1)[1])
    except Exception:                                    # noqa: BLE001 - the report is still useful without it
        return None


def _safe(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(s))[:40]


def _print_to_pdf(window, target: Path, timeout: float = 60):
    """Print the page to PDF with WebView2's own PrintToPdfAsync. The page's @media print CSS shows only the
    report (#printRoot), so the PDF looks exactly like the preview. No extra PDF library is needed."""
    browser = getattr(getattr(window, "native", None), "browser", None)
    wv = getattr(browser, "webview", None)
    if wv is None:
        raise RuntimeError("PDF export needs the Edge WebView2 window. Save as HTML and print that instead.")
    from System import Action, Boolean, Func, Object
    from System.Threading.Tasks import Task
    done, out = threading.Event(), {}
    if target.exists():
        target.unlink()

    def finished(task):
        try:
            out["ok"] = bool(task.Result)
        except Exception as e:                       # noqa: BLE001 - reported below
            out["error"] = e
        done.set()

    def start():
        core = wv.CoreWebView2
        s = core.Environment.CreatePrintSettings()
        s.PageWidth, s.PageHeight = 8.27, 11.69                    # A4 in inches
        s.MarginTop = s.MarginBottom = 0                           # margins come from report.css (white)
        s.MarginLeft = s.MarginRight = 0
        s.ShouldPrintBackgrounds = True
        s.ShouldPrintHeaderAndFooter = False
        core.PrintToPdfAsync(str(target), s).ContinueWith(Action[Task[Boolean]](finished))
        return None

    wv.Invoke(Func[Object](start))
    if not done.wait(timeout):
        raise RuntimeError("PDF export timed out.")
    if "error" in out or not out.get("ok") or not target.exists():
        raise RuntimeError(f"PDF export failed: {out.get('error', 'WebView2 returned false')}")


def _standalone_report_html(body: str, report: dict) -> str:
    """The report preview as one self-contained HTML file (CSS and logo inlined)."""
    import base64
    css = (BASE_DIR / "ui" / "report.css").read_text(encoding="utf-8")
    logo = "data:image/svg+xml;base64," + base64.b64encode((BASE_DIR / "ui" / "logo.svg").read_bytes()).decode()
    body = body.replace('src="logo.svg"', f'src="{logo}"')
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{report['id']} · {APP_NAME} report</title><style>{css}\n"
            "body{margin:0;background:#e9edf3;padding:24px}.paper{margin:0 auto}"
            "@media print{body{background:#fff;padding:0}.paper{box-shadow:none}}</style></head>"
            f"<body>{body}</body></html>")


def _write_report_csv(target: Path, rep: dict):
    with open(target, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["report", rep["id"], rep["generated"], rep["app"], rep["weights"]])
        w.writerow(["patient_id", rep["patient"]["id"]])
        w.writerow([])
        w.writerow(["disease", "combined_match", "xray_part", "clinical_part", "coverage", "level", "low_confidence",
                    "severity", "candidate"])
        cand = set(rep["candidates"]["ids"])
        for d in rep["diseases"]:
            p = d["parts"]
            w.writerow([d["name"], f"{d['match']:.4f}",
                        f"{p['xray']['match']:.4f}" if p["xray"]["used"] else "",
                        f"{p['clinical']['match']:.4f}" if p["clinical"]["used"] else "",
                        f"{d['coverage']:.4f}", d["level"], d["low_confidence"], d["severity"]["grade"], d["id"] in cand])
        w.writerow(["candidate_rule", f"match >= {rep['candidates']['ratio']:.0%} of the top score",
                    f"max {rep['candidates']['max']}"])
        if rep["xray"]:
            w.writerow([])
            w.writerow(["xray_finding", "score", "level", "used_for_diseases"])
            for x in rep["xray"]["lung"]:
                w.writerow([x["label"], f"{x['score']:.4f}", x["level"], True])
            for x in rep["xray"]["not_used"]:
                w.writerow([x["label"], f"{x['score']:.4f}", "", False])
        if rep["clinical"]:
            c = rep["clinical"]
            w.writerow([])
            w.writerow(["clinical_item", "value", "reference", "flag"])
            for s in c["present"]:
                w.writerow([s, "present", "", ""])
            for s in c["absent"]:
                w.writerow([s, "absent", "", ""])
            if c["sounds"]:
                w.writerow(["Auscultation", "; ".join(c["sounds"]), "", ""])
            for x in c["rows"]:
                w.writerow([x["label"], x["value"], x["ref"], x["flag"]])
        rv = rep.get("review") or {}
        if rv:
            w.writerow([])
            w.writerow(["reviewed_by", rv.get("reviewer", "")])
            w.writerow(["signed", rv.get("signed_at", "")])
            w.writerow(["notes", rv.get("notes", "")])


def _read_lab_file(path: Path) -> dict:
    """{name: value} from a JSON object (or an exported report's clinical.inputs) or a 2-column CSV."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("clinical"), dict):
            data = data["clinical"].get("inputs", {})
        if not isinstance(data, dict):
            raise ValueError("The JSON file must contain an object like {\"WBC\": 12.1, \"fever\": true}.")
        return data
    out = {}
    dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
    for row in csv.reader(text.splitlines(), dialect):
        if len(row) >= 2 and row[0].strip():
            out[row[0].strip()] = row[1].strip()
    return out


def _map_lab_names(raw: dict, model: ce.ClinicalModel) -> tuple[dict, list[str]]:
    """Map file names (ids, short labels like 'WBC' / 'SpO2', or labels) to the input ids of weight.json."""
    def key(s):
        # "%" is kept as a token: "%FEV1" (percent predicted) must not collapse into "FEV1" (litres)
        return "".join(ch for ch in str(s).lower().replace("₂", "2").replace("%", "pct") if ch.isalnum())
    names = {}
    for fid, f in model.features.items():
        if f["input"] == "xray":
            continue
        for n in (fid, f.get("short"), f["label"]):
            if n:
                names[key(n)] = fid
    names.update({key("sbp"): "sbp", key("dbp"): "dbp", key("systolic"): "sbp", key("diastolic"): "dbp",
                  key("temperature"): "bt", key("pulse"): "pr", key("hr"): "pr", key("sat"): "spo2",
                  key("fev1/fvc%"): "fev1_fvc", key("%pred"): "pfev1"})
    # "FEV1%" is deliberately not an alias: in Japanese usage it means FEV1/FVC, elsewhere % predicted
    truthy = {"1", "true", "yes", "y", "+", "present", "positive"}
    falsy = {"0", "false", "no", "n", "-", "absent", "negative"}
    inputs, unknown = {}, []
    for name, value in raw.items():
        if str(name).startswith("_"):                 # metadata such as "_case" / "_note" in example files
            continue
        fid = names.get(key(name))
        if fid is None:
            unknown.append(str(name))
            continue
        f = model.features.get(fid, {})
        if fid == "bp" and isinstance(value, str) and "/" in value:            # "128/78"
            sbp, dbp = value.split("/", 1)
            inputs["sbp"], inputs["dbp"] = sbp.strip(), dbp.strip()
        elif f.get("input") == "bool":
            v = str(value).strip().lower()
            if v in truthy or value is True:
                inputs[fid] = True
            elif v in falsy or value is False:
                inputs[fid] = False
        elif f.get("input") == "sounds":
            items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
            lookup = {key(k): k for k in f["sounds"]} | {key(v): k for k, v in f["sounds"].items()}
            inputs[fid] = [lookup[key(i)] for i in items if key(i) in lookup]
        else:
            inputs[fid] = value
    return inputs, unknown


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
    api._window.events.closing += api._on_closing      # X button: never close with unsaved case data
    webview.start(gui="edgechromium", debug=args.debug, icon=str(ICON_PATH))


if __name__ == "__main__":
    main()
