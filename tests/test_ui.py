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


def _wait_file(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


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
        check(js("!document.body.classList.contains('landing-on')") is True, "Start New Analysis opens step 1")
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
        check(js(modal) is True, "Exit opens the confirmation dialog")
        check(js("document.activeElement.id") == "exitConfirm", "the Exit button has focus")
        js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        check(js(modal) is False, "Esc closes the dialog without exiting")
        js("document.querySelector('#btnAnalyze').click()")
        wait_for("document.querySelectorAll('#rows .row:not(.pending)').length === 11")
        js("document.querySelector('#btnExit').click()")
        check("not been exported" in js("document.querySelector('#exitText').textContent"),
              "the dialog warns when the analysis was not exported")
        js("document.querySelector('#exitCancel').click()")
        check(js(modal) is False, "Cancel closes the dialog")
        exited = []
        api.exit = lambda: exited.append(True)         # don't really close the window mid-test
        js("document.querySelector('#btnExit').click()")
        js("document.querySelector('#exitConfirm').click()")
        check(wait_for("true") and (time.sleep(0.5) or exited == [True]), "confirming calls exit")
    except Exception:
        traceback.print_exc()
        results["failures"].append("exception")
    finally:
        window.destroy()


def main():
    app.SETTINGS_PATH = Path(tempfile.mkdtemp()) / "settings.json"   # never touch the user's real settings
    api = app.Api()
    window = webview.create_window(f"{app.APP_NAME} (test)", url=str(app.UI_INDEX), js_api=api,
                                   width=1440, height=900, min_size=app.MIN_WINDOW_SIZE)
    api._window = window
    webview.start(drive, (window, api), gui=GUI)
    print("RESULT:", "FAIL" if results["failures"] else "PASS")
    return int(bool(results["failures"]))


if __name__ == "__main__":
    sys.exit(main())
