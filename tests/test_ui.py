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


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        results["failures"].append(msg)


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
        check(js("document.querySelector('#btnAnalyze').disabled") is True,
              "Start Analysis is disabled before an image is loaded")

        js("document.querySelector('#btnUpload').click()")
        check(wait_for("!document.querySelector('#btnAnalyze').disabled"), "upload enables Start Analysis")
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
        report = json.loads((tmp / "report.json").read_text())
        check(len(report["all_scores"]) == 18 and len(report["findings"]) == 11, "JSON report has 18 scores / 11 findings")
        js("document.querySelector('#btnExport').click()")
        check(wait_for(f"document.querySelector('#toast').textContent.includes('report.csv')"), "CSV export toast")
        check(len((tmp / "report.csv").read_text().splitlines()) == 19, "CSV has header + 18 rows")

        js("document.querySelector('[data-sort=name]').click()")
        names = js("[...document.querySelectorAll('#rows .n')].map(e => e.textContent)")
        check(names == sorted(names), "A–Z sort")

        js("document.querySelector('#btnClear').click()")
        check(wait_for("document.querySelector('#btnAnalyze').disabled && document.querySelectorAll('#rows .pending').length === 11"),
              "Clear resets the screen")
    except Exception:
        traceback.print_exc()
        results["failures"].append("exception")
    finally:
        window.destroy()


def main():
    api = app.Api()
    window = webview.create_window("X-Ray Analyzer (test)", url=str(app.UI_INDEX), js_api=api,
                                   width=1440, height=900)
    api._window = window
    webview.start(drive, (window, api), gui=GUI)
    print("RESULT:", "FAIL" if results["failures"] else "PASS")
    return int(bool(results["failures"]))


if __name__ == "__main__":
    sys.exit(main())
