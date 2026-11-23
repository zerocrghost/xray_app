"""
Case data storage: the data must be saved without fail and without repeat.

  * nothing to save -> no file
  * first save -> one file <dataset>/<case_id>.json, revision 1
  * saving unchanged data again -> not rewritten (same revision, still one file)
  * changed data -> same file, revision + 1 (never a second record for the same case)
  * no temporary files left behind (atomic write)
  * dataset folder not writable -> saved to the fallback folder, caller is told
  * dataset AND fallback not writable -> error; New Patient / Exit refuse to discard the case
  * a saved case can be opened again for review; opening + saving without changes writes nothing
  * Save Report (DOCX) writes the report where the doctor chose AND saves the case data once

Run:  python tests/test_dataset.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import app  # noqa: E402
import case_store as cs  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class FakeWindow:
    """Stands in for the pywebview window: answers file dialogs, records destroy()."""
    def __init__(self):
        self.answers, self.destroyed = [], False

    def create_file_dialog(self, *a, **k):
        return self.answers.pop(0) if self.answers else None

    def destroy(self):
        self.destroyed = True


def files(folder: Path):
    return sorted(p.name for p in folder.glob("*")) if folder.exists() else []


def main():
    tmp = Path(tempfile.mkdtemp())
    app.SETTINGS_PATH = tmp / "settings" / "settings.json"
    app.FALLBACK_DATASET = tmp / "fallback"
    ds = tmp / "dataset"
    app.save_settings(dataset_dir=str(ds))

    api = app.Api()
    api._window = FakeWindow()
    api._store = cs.CaseStore(app.dataset_dir(), app.FALLBACK_DATASET)
    assert api.init()["ok"]

    r = api.save_case("test")
    check("empty case: nothing is saved", r["ok"] and r.get("empty") and not files(ds))

    api.update_case({"patient": {"patient_id": "P-001", "name": "Test Patient", "age": 72, "sex": "Male",
                                 "hospital": "General Hospital"}})
    r1 = api.save_case("test")
    case_file = ds / f"{api._report_id}.json"
    check("first save: one file named after the case id, revision 1",
          r1["ok"] and r1["saved"] and files(ds) == [case_file.name] and r1["revision"] == 1, files(ds))
    rec = json.loads(case_file.read_text(encoding="utf-8"))
    check("record contains the patient and the schema", rec["schema"] == cs.SCHEMA and rec["patient"]["name"] == "Test Patient")

    r2 = api.save_case("test")
    mtime = case_file.stat().st_mtime_ns
    check("saving unchanged data again does not rewrite (no repeat)",
          r2["ok"] and r2["unchanged"] and not r2["saved"] and r2["revision"] == 1 and len(files(ds)) == 1)

    # image + analysis + clinical data
    img = ROOT / "tests" / "images" / "02_pneumonia_case.jpg"
    assert api.load_image(str(img))["ok"] and api.analyze()["ok"]
    inputs = {"fever": True, "cough": True, "sputum": True, "bt": "38.9", "rr": "31", "spo2": "89", "wbc": "16.4",
              "duration": ["acute"], "auscultation": ["coarse_crackles"]}
    api.update_case({"clinical_inputs": inputs, "review": {"notes": "Start antibiotics.", "reviewer": "Dr. Test"}})
    r3 = api.save_case("test")
    rec = json.loads(case_file.read_text(encoding="utf-8"))
    check("changed data: same file, revision 2, still one record",
          r3["saved"] and r3["revision"] == 2 and files(ds) == [case_file.name] and rec["revision"] == 2)
    check("record holds X-ray (path, sha256, 18 scores), clinical inputs, analysis and review",
          rec["xray"]["sha256"] == cs.file_sha256(img) and len(rec["xray"]["analysis"]["scores"]) == 18
          and rec["clinical"]["inputs"]["wbc"] == "16.4" and len(rec["analysis"]["diseases"]) == 7
          and rec["review"]["reviewer"] == "Dr. Test")
    pn = next(d for d in rec["analysis"]["diseases"] if d["id"] == "pneumonia")
    check("patient age reaches the CURB-65 severity sign", any(s["label"] == "Age" for s in pn["severity"]["signs"]),
          ", ".join(s["label"] for s in pn["severity"]["signs"]))
    check("no temporary files are left (atomic write)", not list(ds.glob("*.tmp")))

    # Save Report as DOCX: report where the doctor chose + case data saved once
    rep_path = tmp / "reports" / "report.docx"
    api.final_report(inputs, {"notes": "Start antibiotics.", "reviewer": "Dr. Test"})
    api._window.answers.append(str(rep_path))
    r = api.save_report("docx", None, {"notes": "Start antibiotics.", "reviewer": "Dr. Test", "agreed": True})
    rec = json.loads(case_file.read_text(encoding="utf-8"))
    check("Save Report (DOCX) writes the report and saves the case data once",
          r["ok"] and rep_path.exists() and rep_path.stat().st_size > 20000 and r["data"]["saved"]
          and rec["reports"][-1]["path"] == str(rep_path) and files(ds) == [case_file.name],
          f"{rep_path.stat().st_size // 1024} KB, revision {rec['revision']}")
    from docx import Document
    text = "\n".join(p.text for p in Document(str(rep_path)).paragraphs)
    check("DOCX contains the patient and the assessment", "Integrated assessment".upper() in text and "Test Patient" in
          "\n".join(c.text for t in Document(str(rep_path)).tables for row in t.rows for c in row.cells))
    r = api.save_report("html")
    check("only PDF and DOCX are accepted as report formats", not r["ok"])

    # New Patient: saves (nothing changed -> no rewrite), then starts an empty case
    case_id = api._report_id
    rev_before = json.loads(case_file.read_text(encoding="utf-8"))["revision"]
    r = api.new_patient()
    check("New Patient: data already saved -> not written again, then the case is reset",
          r["ok"] and r["data"]["unchanged"] and api._report_id is None and api._image is None and not api._patient
          and json.loads(case_file.read_text(encoding="utf-8"))["revision"] == rev_before)

    # open the saved case for review
    r = api.load_case(str(case_file))
    check("open saved case: patient, inputs, review, X-ray image and scores are restored",
          r["ok"] and r["case_id"] == case_id and r["patient"]["name"] == "Test Patient"
          and r["clinical_inputs"]["wbc"] == "16.4" and r["review"]["reviewer"] == "Dr. Test"
          and r["xray"]["preview"] and len(r["xray"]["result"]["scores"]) == 18, r.get("error", ""))
    r = api.save_case("test")
    check("opened case saved again without changes: nothing is written (no repeat)",
          r["ok"] and r["unchanged"] and files(ds) == [case_file.name])
    api.update_case({"review": {"notes": "Reviewed again.", "reviewer": "Dr. Test"}})
    r = api.save_case("test")
    check("editing the opened case updates the same file (revision + 1)",
          r["saved"] and r["revision"] == rev_before + 1 and files(ds) == [case_file.name])

    # missing image: stored scores are still shown
    api.new_patient()
    moved = tmp / "img_copy.jpg"
    shutil.copy(img, moved)
    api.update_case({"patient": {"name": "Image Gone"}})
    api.load_image(str(moved))
    api.analyze()
    api.save_case("test")
    gone_file = Path(api._store.last_path)
    api.new_patient()
    moved.unlink()
    r = api.load_case(str(gone_file))
    check("opened case whose X-ray file is gone: stored scores shown, user is warned",
          r["ok"] and r["xray"]["preview"] is None and len(r["xray"]["result"]["scores"]) == 18 and r["warnings"])
    api.new_patient()

    # dataset folder not writable -> fallback folder
    blocker = tmp / "not_a_folder"
    blocker.write_text("x")
    api._store.dataset_dir = blocker / "dataset"          # cannot be created: parent is a file
    api.update_case({"patient": {"name": "Fallback Case"}})
    r = api.save_case("test")
    check("dataset folder not writable: data goes to the fallback folder (not lost)",
          r["ok"] and r["saved"] and r["fallback"] and (app.FALLBACK_DATASET / f"{api._report_id}.json").exists(), r["path"])

    # both not writable -> error, and New Patient / Exit refuse to discard the case
    api._store.fallback_dir = blocker / "fallback"
    api.update_case({"patient": {"name": "Fallback Case 2"}})
    r = api.save_case("test")
    check("nothing writable: an error is returned", not r["ok"] and "could not be saved" in r["error"])
    r = api.new_patient()
    check("New Patient refuses to clear an unsaved case", not r["ok"] and api._patient.get("name") == "Fallback Case 2")
    r = api.exit()
    check("Exit refuses to close with unsaved case data", not r["ok"] and not api._window.destroyed)
    r = api.exit(force=True)
    check("Exit anyway (user's explicit choice) closes", r["ok"] and api._window.destroyed)

    # settings: dataset folder must be writable
    r = api.set_settings({"dataset_dir": str(blocker / "x")})
    check("Settings refuse a dataset folder that cannot be written", not r["ok"])
    r = api.set_settings({"dataset_dir": str(tmp / "other_dataset")})
    check("Settings accept a writable dataset folder", r["ok"] and Path(r["dataset_path"]) == (tmp / "other_dataset").resolve())
    app.save_settings(dataset_dir="./dataset")
    check("default dataset folder is ./dataset next to the app", app.dataset_dir() == (app.APP_DIR / "dataset").resolve())

    # weight edits from the app settings: saved, used for scoring, recorded in the case, survive a restart
    edit = {"pneumonia": {"fever": {"group": "D", "weight": 0}}}
    r = api.set_weights(edit)
    check("set_weights saves the edits to settings.json",
          r["ok"] and app.load_settings()["weight_overrides"] == {"pneumonia": {"fever": {"group": "D", "weight": 0.0}}}
          and r["weights"]["edits"] == 1 and "1 local edit" in r["clinical"]["label"])
    check("Settings report the weights in use", api.get_settings()["weights"]["label"] == api._clinical_model.label())
    api.update_case({"patient": {"patient_id": "P-W", "name": "Weights Case"}})
    api.analyze_clinical({"fever": True, "cough": True})
    rec = api._build_record()
    check("a saved case records the weights label and the exact edits",
          "1 local edit" in rec["analysis"]["weights"] and rec["analysis"]["weight_overrides"] == api._clinical_model.overrides)
    r = api.set_weights({"pneumonia": {"fever": {"weight": 99}}})
    check("an invalid edit is refused and changes nothing", not r["ok"] and api._clinical_model.edit_count == 1
          and app.load_settings()["weight_overrides"]["pneumonia"]["fever"]["group"] == "D", r.get("error", "").splitlines()[-1])
    model, warn = app.load_clinical_model()
    check("after a restart the saved edits are used", warn is None and model.overrides == api._clinical_model.overrides)
    app.save_settings(weight_overrides={"asthma": {"wheezing": {"weight": 99}}})     # e.g. weight.json changed under it
    model, warn = app.load_clinical_model()
    check("edits that no longer fit weight.json: the app still starts with weight.json and warns",
          model.overrides == {} and warn and "not applied" in warn)
    r = api.reset_weights()
    check("Reset goes back to weight.json", r["ok"] and app.load_settings()["weight_overrides"] == {}
          and api._clinical_model.label() == f"weight.json v{api._clinical_model.table['version']}")

    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    print("RESULT:", "PASS" if ok else "FAIL")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
