"""
End-to-end UI test: opens the real app window and clicks through it like a user.

  Upload (file dialog answered by the test) -> Start Analysis -> check the 11 rows
  against reference_scores.json -> Export (JSON + CSV) -> Clear -> Exit

On Windows a window flashes up for a few seconds. On a Linux machine with no
display it runs offscreen through Qt (pip install PyQt6 PyQt6-WebEngine qtpy).

Run:  python tests/test_ui.py
"""
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

GUI = None
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
    GUI = "qt"

import webview  # noqa: E402

import app  # noqa: E402

IMAGE = "03_siim_sample.dcm"
results = {"failures": []}


def check(cond, msg, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + msg + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        results["failures"].append(msg)


def _wait_file(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _diff(a, b, path=""):
    """Differences between two JSON values (for test messages)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k in ("saved_at", "revision", "save_reason", "saved_to"):
                continue
            out += _diff(a.get(k), b.get(k), f"{path}.{k}")
        return out
    return [] if a == b else [f"{path}: {str(a)[:60]} → {str(b)[:60]}"]


def _read_json(path: Path, timeout=10):
    """Read a JSON file the app is still writing: retry until it parses."""
    end = time.time() + timeout
    while True:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if time.time() > end:
                raise
            time.sleep(0.1)


def drive(window, api):
    js = window.evaluate_js

    def wait_for(expr, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if js(expr):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return False

    tmp = Path(tempfile.mkdtemp())
    answers = [[str(HERE / "images" / IMAGE)], str(tmp / "report.json"), str(tmp / "report.csv")]
    window.create_file_dialog = lambda *a, **k: answers.pop(0)   # stand-in for the user

    try:
        check(wait_for("document.querySelector('#modelChip').textContent.includes('Model loaded')"),
              "model loads at start-up")
        check(js("document.body.classList.contains('landing-on')") is True, "app opens on the landing page")
        check(wait_for("!document.querySelector('#btnLandOpen').disabled"), "landing 'Open X-ray Image' is enabled")
        js("document.querySelector('#btnStart').click()")
        check(js("!document.body.classList.contains('landing-on') && !document.querySelector('#page0').hidden") is True,
              "Start New Analysis opens the patient page")
        check(js("document.querySelector('[data-p=exam_date]').value") == time.strftime("%Y-%m-%d"),
              "exam date defaults to today")
        for k, v in {"patient_id": "MRN-0042", "name": "Kim Test", "dob": "1950-03-14", "location": "Seoul",
                     "referring": "Dr. Lee"}.items():
            js(f"(() => {{ const i = document.querySelector('[data-p={k}]'); i.value = '{v}';"
               f" i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")
        js("document.querySelector('[data-p=sex] [data-v=Male]').click()")
        age = js("document.querySelector('[data-p=age]').value")
        check(age.isdigit() and int(age) >= 75, f"age is calculated from the date of birth ({age})")
        check("Kim Test" in js("document.querySelector('#step0Sub').textContent"), "stepper shows the patient")
        js("document.querySelector('#btnNext0').click()")
        check(js("!document.querySelector('#page1').hidden") is True, "Next: X-Ray Analysis opens step 2 (X-ray)")
        check(js("document.querySelector('#btnAnalyze').disabled") is True,
              "Start Analysis is disabled before an image is loaded")
        js("document.querySelector('#btnHome').click()")
        check(js("document.body.classList.contains('landing-on')") is True, "logo button goes back to the landing page")

        # theme switch: toggles <html data-theme>, is saved to settings.json, Ctrl+T toggles back
        start_theme = js("document.documentElement.dataset.theme")
        check(start_theme in ("dark", "light"), f"a theme is applied at start-up ({start_theme})")
        js("document.querySelector('.theme-btn').click()")
        flipped = "light" if start_theme == "dark" else "dark"
        check(js("document.documentElement.dataset.theme") == flipped, "the theme button switches the theme")
        check(wait_for(f"true") and _wait_file(lambda: app.load_settings().get("theme") == flipped),
              "the chosen theme is saved for the next start")
        js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 't', ctrlKey: true}))")
        check(js("document.documentElement.dataset.theme") == start_theme, "Ctrl+T switches it back")

        js("document.querySelector('#btnLandOpen').click()")     # open from the landing page
        check(wait_for("!document.querySelector('#btnAnalyze').disabled"), "upload enables Start Analysis")
        check(js("!document.body.classList.contains('landing-on')") is True, "opening an image switches to step 1")
        check(wait_for("document.querySelector('#img').naturalWidth > 0"), "image preview is shown")
        check(IMAGE in js("document.querySelector('#metabar').textContent"), "metabar shows the file name")

        js("document.querySelector('#btnAnalyze').click()")
        check(wait_for("document.querySelectorAll('#rows .row:not(.pending)').length === 11"),
              "analysis fills 11 rows")
        rows = js("""[...document.querySelectorAll('#rows .row')].map(r =>
                      [r.querySelector('.n').textContent, r.querySelector('.p').textContent,
                       r.querySelector('.tag').textContent])""")
        ref = json.loads((HERE / "reference_scores.json").read_text())[IMAGE]
        shown_ok = all(abs(float(p.rstrip('%')) - ref[n.replace(' ', '_')] * 100) <= 0.051 for n, p, _ in rows)
        check(shown_ok, "displayed percentages match the reference scores")
        values = [float(p.rstrip('%')) for _, p, _ in rows]
        check(values == sorted(values, reverse=True), "rows are sorted highest first")
        for n, p, t in rows[:3]:
            print(f"        {n:<14}{p:>7}  {t}")

        check(wait_for("!document.querySelector('#btnExport').disabled"), "Export is enabled after analysis")
        js("document.querySelector('#btnExport').click()")
        check(wait_for(f"document.querySelector('#toast').textContent.includes('report.json')"), "JSON export toast")
        report = _read_json(tmp / "report.json")
        check(len(report["xray"]["all_scores"]) == 18 and len(report["xray"]["findings"]) == 11,
              "JSON report has 18 scores / 11 findings")
        js("document.querySelector('#btnExport').click()")
        check(wait_for(f"document.querySelector('#toast').textContent.includes('report.csv')"), "CSV export toast")
        check(len((tmp / "report.csv").read_text().splitlines()) == 19, "CSV has header + 18 rows")

        js("document.querySelector('[data-sort=name]').click()")
        names = js("[...document.querySelectorAll('#rows .n')].map(e => e.textContent)")
        check(names == sorted(names), "A–Z sort")

        step2(window, api, js, wait_for, tmp, answers)
        step3(window, api, js, wait_for, tmp, answers)

        js("document.querySelector('#btnClear').click()")
        check(wait_for("document.querySelector('#btnAnalyze').disabled && document.querySelectorAll('#rows .pending').length === 11"),
              "Clear resets the screen")

        # clicking the empty image panel opens the file dialog too
        answers.append([str(HERE / "images" / IMAGE)])
        js("document.querySelector('#empty').click()")
        check(wait_for("document.querySelector('#img').naturalWidth > 0 && !document.querySelector('#img').hidden"),
              "clicking the empty image panel opens the upload dialog")
        check(js("getComputedStyle(document.querySelector('#empty')).display") == "none",
              "the empty-panel layer is really hidden once an image is shown")

        # with an image shown, zoom + drag + clicks on the viewer must NOT open the upload dialog
        calls = []
        window.create_file_dialog = lambda *a, **k: calls.append(1)
        js("""(() => {
          const v = document.querySelector('#viewer'), r = v.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + r.height / 2;
          const at = (el, type, dx = 0) => el.dispatchEvent(new MouseEvent(type, {bubbles: true, clientX: x + dx, clientY: y, button: 0}));
          document.querySelector('#zoomIn').click();
          v.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: -100, clientX: x, clientY: y}));
          const top = document.elementFromPoint(x, y);
          at(top, 'mousedown'); at(window, 'mousemove', 60); at(top, 'mouseup', 60); at(top, 'click', 60);
          at(top, 'click');
        })()""")
        time.sleep(1)
        check(calls == [] and js("document.querySelector('#stState').textContent").endswith("Image loaded"),
              "zooming, dragging and clicking the shown image does not open the upload dialog")
        window.create_file_dialog = lambda *a, **k: answers.pop(0)

        # Exit asks for confirmation
        modal = "!document.querySelector('#exitModal').hidden"
        js("document.querySelector('#btnExit').click()")
        check(wait_for(modal, 5), "Exit opens the confirmation dialog")
        check(js("document.activeElement.id") == "exitConfirm", "the Exit button has focus")
        js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        check(js(modal) is False, "Esc closes the dialog without exiting")
        js("document.querySelector('#btnAnalyze').click()")
        wait_for("document.querySelectorAll('#rows .row:not(.pending)').length === 11")
        js("document.querySelector('#btnExit').click()")
        wait_for(modal, 5)
        text = js("document.querySelector('#exitText').textContent")
        check("report has not been saved" in text and "saved to the dataset folder automatically" in text,
              "Exit warns that the report is not saved and that the data is saved automatically")
        js("document.querySelector('#exitCancel').click()")
        check(js(modal) is False, "Cancel closes the dialog")
        exited = []
        real_exit = api.exit
        def fake_exit(force=False):                    # save like the real exit, but don't close the window mid-test
            r = api.save_case("exit")
            exited.append(r)
            return r
        api.exit = fake_exit
        js("document.querySelector('#btnExit').click()")
        wait_for(modal, 5)
        js("document.querySelector('#exitConfirm').click()")
        check(wait_for("true") and (time.sleep(0.8) or (len(exited) == 1 and exited[0]["ok"] and exited[0].get("saved"))),
              "confirming Exit saves the case data (then the window would close)")
        api.exit = real_exit
    except Exception:
        traceback.print_exc()
        results["failures"].append("exception")
    finally:
        window.destroy()


PNEUMONIA = {"fever": True, "cough": True, "sputum": True, "chest_pain": True, "wheezing": False,
             "sbp": "112", "dbp": "68", "pr": "112", "bt": "38.9", "rr": "26", "spo2": "92",
             "wbc": "16.4", "esr": "48", "stab": "14", "seg": "80", "lym": "9"}


def step2(window, api, js, wait_for, tmp, answers):
    """Step 2 (symptoms & labs): navigation, form, scoring, weighting table, import, export."""
    js("document.querySelector('#btnNext').click()")
    check(js("document.querySelector('#page1').hidden && !document.querySelector('#page2').hidden") is True,
          "Next: Symptoms & Labs opens step 2")
    check(js("document.querySelector('#step2').classList.contains('active') && "
             "document.querySelector('#step1').classList.contains('done')") is True,
          "stepper: step 1 done, step 2 active")
    check(js("!document.querySelector('#cThumbImg').hidden && document.querySelectorAll('#cMini .r').length === 4") is True,
          "left panel shows the X-ray and its top 4 findings")
    counts = js("[document.querySelectorAll('#cForm [data-sym]').length, document.querySelectorAll('#cForm [data-snd]').length,"
                " document.querySelectorAll('#cForm .cf').length]")
    check(counts == [6, 8, 24], f"form built from weight.json: 6 symptoms, 8 sounds, 24 value fields ({counts})")
    # history & exposure: multi-select exposure ("none" exclusive), pack-years, single-choice duration
    check(js("document.querySelectorAll('[data-pick^=\"exposure:\"]').length") == 7 and
          js("document.querySelectorAll('[data-pick^=\"duration:\"]').length") == 5 and
          js("!!document.querySelector('.cf[data-f=pack_years]')"), "History & exposure section: exposure, pack-years, duration")
    js("document.querySelector('[data-pick=\"exposure:smoking_current\"]').click();"
       "document.querySelector('[data-pick=\"exposure:occupational\"]').click();"
       "document.querySelector('[data-pick=\"duration:acute\"]').click();"
       "document.querySelector('[data-pick=\"duration:years\"]').click()")
    picked = js("[...document.querySelectorAll('[data-pick].yes')].map(c => c.dataset.pick)")
    check(picked == ["exposure:smoking_current", "exposure:occupational", "duration:years"],
          f"exposure is multi-select, duration single-choice ({picked})")
    js("document.querySelector('[data-pick=\"exposure:none\"]').click()")
    check(js("[...document.querySelectorAll('[data-pick^=\"exposure:\"].yes')].map(c => c.dataset.pick)") == ["exposure:none"],
          "'No relevant exposure' clears the other exposures")
    js("document.querySelector('[data-pick=\"exposure:none\"]').click(); document.querySelector('[data-pick=\"duration:years\"]').click()")
    check(js("document.querySelectorAll('[data-pick].yes').length") == 0, "clicking a chosen option again clears it")
    check(js("document.querySelector('#btnRun').disabled") is True, "Run AI Analysis is disabled while the form is empty")
    groups = js("[...document.querySelectorAll('#cForm .cs-sub[data-group]')].map(g => "
                "g.firstChild.textContent + ':' + g.nextElementSibling.querySelectorAll('.cf').length)")
    check(groups == ["Inflammation markers:2", "WBC differential:6", "Liver function & chemistry:5"],
          f"lab data is split into 3 groups ({groups})")
    for k, v in {"stab": "5", "seg": "60", "eos": "3", "bas": "1", "lym": "25", "mon": "6"}.items():
        js(f"(() => {{ const i = document.querySelector('input[data-k={k}]'); i.value = '{v}'; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")
    check(js("document.querySelector('.cs-sub[data-group=differential] .sum').textContent") == "Σ 100 %" and
          not js("document.querySelector('.cs-sub[data-group=differential] .sum').classList.contains('off')"),
          "WBC differential shows its total (Σ 100 %)")
    js("(() => { const i = document.querySelector('input[data-k=seg]'); i.value = '80'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
    check(js("document.querySelector('.cs-sub[data-group=differential] .sum').classList.contains('off')") is True,
          "a differential far from 100 % is flagged (Σ 120 %)")
    for k in ("stab", "seg", "eos", "bas", "lym", "mon"):
        js(f"(() => {{ const i = document.querySelector('input[data-k={k}]'); i.value = ''; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")

    # fill a pneumonia case like a user: chips are clicked (once = yes, twice = no), numbers typed
    for k, v in PNEUMONIA.items():
        if isinstance(v, bool):
            js(f"document.querySelector('[data-sym={k}]').click()" + ("" if v else ";document.querySelector('[data-sym=" + k + "]').click()"))
        else:
            js(f"(() => {{ const i = document.querySelector('input[data-k={k}]'); i.value = '{v}';"
               f" i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")
    js("document.querySelector('[data-snd=coarse_crackles]').click()")
    check(js("document.querySelector('[data-sym=wheezing]').classList.contains('no') && "
             "document.querySelector('[data-sym=fever]').classList.contains('yes')") is True, "symptom chips: yes / no states")
    check(js("document.querySelector('.cf[data-f=wbc]').classList.contains('h') && "
             "document.querySelector('.cf[data-f=wbc] .st').textContent === 'HIGH'") is True, "WBC 16.4 is flagged HIGH")
    check(js("document.querySelector('.cf[data-f=spo2]').classList.contains('h')") is True,
          "SpO2 92 is flagged in red (low is the dangerous direction)")
    js("(() => { const i = document.querySelector('input[data-k=fev1]'); i.value = '1.4'; i.dispatchEvent(new Event('input', {bubbles: true}));"
       " const j = document.querySelector('input[data-k=fvc]'); j.value = '2.8'; j.dispatchEvent(new Event('input', {bubbles: true})); })()")
    check(js("document.querySelector('input[data-k=fev1_fvc]').placeholder") == "auto 50", "FEV1/FVC is calculated (auto 50)")
    for k in ("fev1", "fvc"):
        js(f"(() => {{ const i = document.querySelector('input[data-k={k}]'); i.value = ''; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")

    js("document.querySelector('#btnRun').click()")
    check(wait_for("document.querySelectorAll('#cOut .dx .r').length === 7"), "Run AI Analysis scores 7 diseases")
    top_ui = js("document.querySelector('#cOut .hero b').textContent")
    inputs = {k: v for k, v in PNEUMONIA.items()}
    inputs["auscultation"] = ["coarse_crackles"]
    ref = api._clinical_model.score(inputs, api._result["scores"])
    check(top_ui == ref["diseases"][0]["name"], f"top assessment matches the engine ({top_ui})")
    pcts = js("[...document.querySelectorAll('#cOut .dx .p')].map(e => parseFloat(e.textContent))")
    check(len(pcts) == 7 and all(abs(p - d["match"] * 100) <= 0.51 for p, d in zip(pcts, ref["diseases"])),
          "all 7 match scores match the engine")
    no_xray = api._clinical_model.score(inputs, None)
    top2 = {d["name"] for d in no_xray["diseases"][:2]}
    check(top2 == {"Pneumonia", "Lung Abscess"},
          f"without the X-ray this picture points to the acute infections ({', '.join(sorted(top2))}); imaging separates them")
    check(js("document.querySelector('#cSrc').textContent").endswith("X-ray + clinical"), "uses the X-ray result too")
    check(js("document.querySelectorAll('#cOut .fx .r').length") > 0, "key factors are listed")

    # a change re-scores automatically
    js("(() => { const i = document.querySelector('input[data-k=spo2]'); i.value = '88'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
    check(wait_for("[...document.querySelectorAll('#cOut .alerts div')].some(d => d.textContent.includes('SpO₂ < 90'))", 5),
          "editing a value re-scores automatically (SpO2 88 → hypoxemia alert)")

    # pick another disease in the differential
    js("document.querySelectorAll('#cOut .dx .r')[2].click()")
    name3 = js("document.querySelectorAll('#cOut .dx .r .n')[2].firstChild.textContent")
    check(name3 in js("document.querySelectorAll('#cOut .sec')[1].textContent"), f"clicking a disease shows its factors ({name3})")

    # weighting table
    js("document.querySelector('#btnWeights').click()")
    check(js("!document.querySelector('#wModal').hidden") is True, "Weights opens the weighting table")
    check(js("document.querySelectorAll('#wTabs button').length") == 8, "7 disease tabs + Method")
    n_feat = len(api._clinical_model.features)
    check(js("document.querySelectorAll('#wBody tbody tr:not(.gh)').length") == n_feat and
          js("document.querySelectorAll('#wBody tbody tr.gh').length") == 4, f"table lists all {n_feat} items in groups A–D")
    js("[...document.querySelectorAll('#wTabs button')].pop().click()")
    check("Spirometry" in js("document.querySelector('#wBody').textContent"), "Method tab explains the weighting and spirometry")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    check(js("document.querySelector('#wModal').hidden") is True, "Esc closes the weighting table")

    # import a lab file (CSV name,value)
    lab = tmp / "labs.csv"
    lab.write_text("WBC,5.1\nfever,no\nBP,120/80\nFoo,1\n", encoding="utf-8")
    answers.append([str(lab)])
    js("document.querySelector('#btnImport').click()")
    check(wait_for("document.querySelector('#toast').textContent.includes('Imported 3 items')"), "Import Lab File reads 3 known items")
    check(js("document.querySelector('input[data-k=wbc]').value") == "5.1" and
          js("document.querySelector('input[data-k=sbp]').value") == "120" and
          js("document.querySelector('[data-sym=fever]').classList.contains('no')") is True, "imported values fill the form")
    check("Foo" in js("document.querySelector('#toast').textContent"), "unknown names are reported")

    # export the combined report from step 2
    answers.append(str(tmp / "full.json"))
    wait_for("!document.querySelector('#btnCExport').disabled", 5)
    time.sleep(0.6)                                           # let the debounced re-score finish
    js("document.querySelector('#btnCExport').click()")
    check(_wait_file(lambda: (tmp / "full.json").exists()), "Export from step 2 writes the report")
    full = _read_json(tmp / "full.json")
    check("xray" in full and len(full["clinical"]["diseases"]) == 7 and full["clinical"]["inputs"]["wbc"] == 5.1,
          "the report holds the X-ray and the clinical result")

    # Ctrl+R / typing digits in a field must not trigger step-1 shortcuts
    js("document.querySelector('input[data-k=pr]').focus()")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '0', bubbles: true}))")
    check(js("document.querySelector('#page2').hidden") is False, "typing in a field stays on step 2")

    js("document.querySelector('#btnBack').click()")
    check(js("!document.querySelector('#page1').hidden") is True and
          js("document.querySelector('#step2 .num').textContent") == "✓", "Back to X-Ray; step 2 shows as done")
    js("document.querySelector('#step2').click()")
    js("document.querySelector('#btnCClear').click()")
    check(wait_for("!document.querySelector('#cOut .hero') && document.querySelector('input[data-k=wbc]').value === ''"),
          "Clear Data empties the form and the result")
    js("document.querySelector('#step1').click()")
    check(js("!document.querySelector('#page1').hidden") is True, "stepper button goes back to step 1")


def step3(window, api, js, wait_for, tmp, answers):
    """Step 3 (final report): combined assessment with reasons from steps 1 and 2, sign-off, save, new patient."""
    js("document.querySelector('#step2').click()")
    js(f"Clinical.setValues({json.dumps({**PNEUMONIA, 'auscultation': ['coarse_crackles']})})")
    check(wait_for("!document.querySelector('#btnNext2').disabled", 5), "Next: Final Report is enabled with data")
    js("document.querySelector('#btnNext2').click()")
    check(wait_for("!document.querySelector('#page3').hidden && document.querySelector('#rPaper .p-assess')"),
          "Next: Final Report opens step 3 with the report")
    rep = api._report
    top = rep["diseases"][0]
    check(js("document.querySelector('#rVerdict .cand .nm').firstChild.textContent") == top["name"],
          f"most likely disease shown ({top['name']} {top['match']:.0%})")
    # candidates: diseases scoring >= ratio x the top score, at most N (defaults 50 %, 3)
    exp = [d["name"] for d in rep["diseases"][:3] if d["match"] >= rep["diseases"][0]["match"] * 0.5]
    shown = js("[...document.querySelectorAll('#rVerdict .cand .nm')].map(e => e.firstChild.textContent)")
    check(shown == exp and rep["candidates"]["ids"] == [d["id"] for d in rep["diseases"][:len(exp)]],
          f"candidates within 50 % of the top are listed ({', '.join(shown)})")
    check(js("document.querySelectorAll('#rPaper .p-cands .p-assess').length") == (len(exp) if len(exp) > 1 else 0),
          "the report lists each candidate")
    grade = top["severity"]["grade"]
    check(js("document.querySelector('#rSev .sev').textContent") == grade and
          f"Severity: {grade}" in js("document.querySelector('#rPaper').textContent"), f"severity shown ({grade})")
    if len(shown) > 1:
        js("document.querySelectorAll('#rVerdict .cand')[1].click()")
        check(rep["diseases"][1]["name"] in js("document.querySelector('#rSev').textContent"),
              "clicking a candidate shows its severity and reasons")

    # Settings: a stricter rule shows only the first candidate
    js("document.querySelector('#btnSettings').click()")
    check(wait_for("!document.querySelector('#setModal').hidden && document.querySelector('#setRatio').value === '50'", 5),
          "Settings opens with the default 50 %")
    js("(() => { const r = document.querySelector('#setRatio'); r.value = '100'; r.dispatchEvent(new Event('input')); })()")
    check("cut-off" in js("document.querySelector('#setExample').textContent"), "Settings previews the rule on the current report")
    js("document.querySelector('#setSave').click()")
    check(_wait_file(lambda: app.load_settings().get("candidate_ratio") == 1.0), "the candidate percentage is saved to settings.json")
    check(wait_for("document.querySelectorAll('#rVerdict .cand').length === 1 && "
                   "document.querySelector('#rVerdict .ch').textContent.includes('clearly most likely')"),
          "at 100 % only the first candidate is shown, as clearly most likely")
    js("document.querySelector('#btnSettings').click()")
    wait_for("!document.querySelector('#setModal').hidden", 5)
    js("document.querySelector('#setReset').click(); document.querySelector('#setSave').click()")
    wait_for(f"document.querySelectorAll('#rVerdict .cand').length === {len(exp)}")
    rep = api._report
    top = rep["diseases"][0]

    check(js("document.querySelectorAll('#rWhy .wcard').length") == 2 and
          js("document.querySelectorAll('#rWhy .wcard li').length") > 0,
          "reasons from step 1 (X-ray) and step 2 (clinical) are shown")
    paper = js("document.querySelector('#rPaper').textContent")
    check("Step 1 · X-ray findings" in paper and "Step 2 · Symptoms" in paper and top["name"] in paper,
          "the report explains the assessment with both steps")
    parts = js("document.querySelector('#rPaper .p-parts').textContent")
    shown_part = lambda p: "neutral" if p["neutral"] else f"{round(p['match'] * 100)}%"
    check(f"X-ray: {shown_part(top['parts']['xray'])}" in parts and
          f"labs: {shown_part(top['parts']['clinical'])}" in parts, f"step-1 / step-2 part scores ({parts})")
    check(js("document.querySelectorAll('#rPaper table')[2].querySelectorAll('tr').length") == 8,
          "differential table lists the 7 diseases")
    js("document.querySelector('[data-opt=raw]').click()")
    check(js("[...document.querySelectorAll('#rPaper tr.dim')].filter(r => r.textContent.includes('not used')).length") == 4,
          "'All 18 X-ray outputs' adds the 4 non-lung outputs as not used")
    check(js("document.querySelector('#printRoot .paper') !== null"), "the print copy of the report is ready")

    # sign-off
    js("document.querySelector('#rSign').click()")
    check(js("document.querySelector('#rSignChip').textContent") == "Not signed", "signing needs a reviewer name")
    js("(() => { const i = document.querySelector('#rReviewer'); i.value = 'Dr. Test'; i.dispatchEvent(new Event('input')); })()")
    js("document.querySelector('#rAgree').click()")
    js("(() => { const i = document.querySelector('#rNotes'); i.value = 'Start antibiotics.'; i.dispatchEvent(new Event('input')); })()")
    time.sleep(0.4)
    check("Kim Test" in js("document.querySelector('#rPatient').textContent") and
          "MRN-0042" in js("document.querySelector('#rPaper .p-meta').textContent"),
          "the report shows the patient from the patient page")
    js("document.querySelector('#rSign').click()")
    check(js("document.querySelector('#rSignChip').textContent") == "Signed" and
          "Dr. Test" in js("document.querySelector('#rPaper .p-sign').textContent"), "Sign report signs it")
    check(_wait_file(lambda: app.load_settings().get("reviewer") == "Dr. Test"), "the reviewer name is remembered")

    check(js("[...document.querySelectorAll('#rFmt button')].map(b => b.dataset.fmt).join()") == "pdf,docx" and
          js("!document.querySelector('#btnPrint')"), "export formats are PDF and DOCX; there is no Print button")

    # save as PDF and DOCX: each report goes where the doctor chose; the case data goes to the dataset ONCE
    ds = Path(app.dataset_dir())
    for fmt in ("pdf", "docx"):
        target = tmp / f"final.{fmt}"
        answers.append(str(target))
        js(f"Report.setFormat('{fmt}')")
        js("document.querySelector('#btnSave').click()")
        check(_wait_file(lambda: target.exists() and target.stat().st_size > 0, 30), f"Save Report writes {fmt.upper()}")
        wait_for("!document.querySelector('#btnSave').disabled", 10)
    pdf = (tmp / "final.pdf").read_bytes()
    check(pdf[:5] == b"%PDF-" and len(pdf) > 20000, f"PDF report printed by WebView2 ({len(pdf) // 1024} KB)")
    from docx import Document
    doc = Document(str(tmp / "final.docx"))
    cells = " ".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    check("Kim Test" in cells and top["name"] in " ".join(p.text for p in doc.paragraphs),
          "DOCX report holds the patient and the assessment")
    cases = sorted(ds.glob("*.json"))
    check(len(cases) == 1 and cases[0].stem == api._report_id, f"one dataset file for this case ({[c.name for c in cases]})")
    rec = _read_json(cases[0])
    check(rec["patient"]["name"] == "Kim Test" and rec["patient"]["age"] >= 75 and len(rec["reports"]) == 2
          and rec["review"]["reviewer"] == "Dr. Test" and len(rec["xray"]["analysis"]["scores"]) == 18
          and rec["clinical"]["inputs"]["wbc"] and rec["analysis"]["diseases"][0]["name"] == top["name"],
          f"dataset record: patient, X-ray, clinical, analysis, review, 2 reports (revision {rec['revision']})")
    check("Case data saved" in js("document.querySelector('#rData').textContent"), "the page confirms where the data went")
    case_file, rev = cases[0], rec["revision"]

    # editing after signing removes the signature
    js("(() => { const i = document.querySelector('#rNotes'); i.value += ' Recheck in 48 h.'; i.dispatchEvent(new Event('input')); })()")
    check(js("document.querySelector('#rSignChip').textContent") == "Not signed", "editing after signing removes the signature")

    # new patient: the changed notes are saved into the SAME file (revision + 1), then everything is cleared
    case_id = api._report_id
    js("document.querySelector('#btnNewPatient').click()")
    check(wait_for("document.querySelector('#exitTitle').textContent === 'Start a new patient?'", 5),
          "New Patient asks for confirmation")
    js("document.querySelector('#exitConfirm').click()")
    check(wait_for("!document.querySelector('#page0').hidden && document.querySelector('#img').hidden && "
                   "!Clinical.hasInput() && document.querySelector('[data-p=name]').value === '' && "
                   "document.querySelector('#step3').disabled"),
          "New Patient clears everything and returns to the patient page")
    check(api._image is None and api._report is None and api._report_id is None, "the Python side is cleared too")
    rec = _read_json(case_file)
    check(sorted(ds.glob("*.json")) == [case_file] and rec["revision"] == rev + 1 and "Recheck in 48 h." in rec["review"]["notes"],
          f"New Patient saved the edited case into the same file (revision {rev} → {rec['revision']}, still 1 file)")

    # open the saved case again to review it
    answers.append([str(case_file)])
    js("document.querySelector('#btnOpenCase0').click()")
    check(wait_for("!document.querySelector('#page3').hidden && document.querySelector('#rPaper .p-assess')", 20),
          "Open Saved Case loads the case and shows the report")
    check(js("document.querySelector('[data-p=name]').value") == "Kim Test" and
          "Recheck in 48 h." in js("document.querySelector('#rNotes').value") and
          js("!document.querySelector('#img').hidden") and js("Clinical.hasInput()") and api._report_id == case_id,
          "patient, notes, X-ray image and clinical data are restored (same case id)")
    check(js("document.querySelector('#rVerdict .cand .nm').firstChild.textContent") == top["name"],
          "the reopened case gives the same assessment")
    after = _read_json(case_file)
    diff = _diff(rec, after)
    check(sorted(ds.glob("*.json")) == [case_file] and after["revision"] == rev + 1,
          "opening a case writes nothing new (no repeat)", "; ".join(diff[:8]))
    js("Case.newPatient()")                            # unchanged since opening: nothing is written
    wait_for("document.querySelector('#exitTitle').textContent === 'Start a new patient?'", 5)
    js("document.querySelector('#exitConfirm').click()")
    wait_for("!document.querySelector('#page0').hidden && document.querySelector('[data-p=name]').value === ''")
    check(_read_json(case_file)["revision"] == rev + 1 and len(list(ds.glob("*.json"))) == 1,
          "closing an unchanged reopened case does not save it again")
    # reload the image for the rest of the step-1 checks
    js("showStep(1)")
    answers.append([str(HERE / "images" / IMAGE)])
    js("document.querySelector('#btnUpload').click()")
    wait_for("document.querySelector('#img').naturalWidth > 0 && !document.querySelector('#img').hidden")


def main():
    tmp = Path(tempfile.mkdtemp())
    app.SETTINGS_PATH = tmp / "settings.json"               # never touch the user's real settings
    app.FALLBACK_DATASET = tmp / "fallback"
    app.save_settings(dataset_dir=str(tmp / "dataset"))       # nor the real dataset folder
    api = app.Api()
    window = webview.create_window(f"{app.APP_NAME} (test)", url=str(app.UI_INDEX), js_api=api,
                                   width=1440, height=900, min_size=app.MIN_WINDOW_SIZE)
    api._window = window
    real = app.APP_DIR / "dataset"
    before = sorted(real.glob("*.json")) if real.exists() else []
    webview.start(drive, (window, api), gui=GUI)
    after = sorted(real.glob("*.json")) if real.exists() else []
    check(after == before, "the test never writes into the real ./dataset folder")
    print("RESULT:", "FAIL" if results["failures"] else "PASS")
    return int(bool(results["failures"]))


if __name__ == "__main__":
    sys.exit(main())
