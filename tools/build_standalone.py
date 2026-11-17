"""
Standalone ("static") Windows build of PneumoLens AI.

The normal build (build_windows.bat) relies on two things being installed on the target PC:
  * the Microsoft Edge WebView2 Runtime  (draws the window)
  * the Visual C++ 2015-2022 runtime     (msvcp140*.dll, needed by onnxruntime / scikit-image)
Plain Windows Server and older Windows 10 installs often have neither.

This build puts both inside the app folder, so nothing has to be installed:
  dist\\standalone\\PneumoLensAI\\
      PneumoLensAI.exe
      _internal\\            Python, packages, model, UI  + msvcp140.dll, msvcp140_1.dll, ...
      webview2\\             private WebView2 "Fixed Version" runtime (msedgewebview2.exe ...)

Usage (from the project folder, after run_windows.bat has created .venv):
  .venv\\Scripts\\python tools\\build_standalone.py [--webview2 PATH] [--trim-locales] [--zip]

  --webview2 PATH   WebView2 Fixed Version runtime: the .cab from
                    https://developer.microsoft.com/microsoft-edge/webview2/  (Fixed Version, x64)
                    or a folder that contains msedgewebview2.exe.
                    Default: copy the WebView2 runtime installed on this build PC.
  --trim-locales    keep only the en-US language pack of WebView2 (about 130 MB smaller).
  --zip             also write dist\\PneumoLensAI-standalone-<version>.zip

Still required on the target PC: Windows 10 / Server 2016 or newer (x64) and .NET Framework 4.7.2+
(built into Windows 10 1803+ and Server 2019+; Server 2016 needs the .NET 4.8 installer).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "PneumoLensAI"
DIST = ROOT / "dist" / "standalone"
APP_DIR = DIST / NAME
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

# VC++ runtime DLLs imported by onnxruntime / scikit-image / numpy (see README). Python ships
# vcruntime140*.dll itself, but the msvcp140* (C++ standard library) files come only with the
# Visual C++ Redistributable, so they are taken from this build PC (install it once here).
VC_RUNTIME = ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"]
VC_REQUIRED = {"msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"}

# parts of an installed (Evergreen) WebView2 that a private copy does not need
WEBVIEW2_SKIP = {"resiliencylinks", "installer", "setupmetrics", "widevinecdm"}


def step(msg):
    print(f"\n=== {msg}", flush=True)


def fail(msg):
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def folder_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**20


def app_version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0"


# ---------------------------------------------------------------------- WebView2
def installed_webview2() -> Path | None:
    base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "EdgeWebView" / "Application"
    versions = [d for d in base.glob("*") if d.is_dir() and re.match(r"^\d+(\.\d+){3}$", d.name)
                and (d / "msedgewebview2.exe").exists()]
    return max(versions, key=lambda d: tuple(map(int, d.name.split(".")))) if versions else None


def find_runtime_dir(folder: Path) -> Path | None:
    hits = sorted(folder.rglob("msedgewebview2.exe"), key=lambda p: len(p.parts))
    return hits[0].parent if hits else None


def get_webview2(source: str | None, tmp: Path) -> tuple[Path, str]:
    if source:
        src = Path(source)
        if src.suffix.lower() == ".cab":
            out = tmp / "webview2_cab"
            out.mkdir()
            print(f"extracting {src.name} ...")
            subprocess.run(["expand.exe", str(src), "-F:*", str(out)], check=True, stdout=subprocess.DEVNULL)
            src = out
        runtime = find_runtime_dir(src)
        if runtime is None:
            fail(f"No msedgewebview2.exe found in {source}")
        return runtime, "Fixed Version package"
    runtime = installed_webview2()
    if runtime is None:
        fail("No WebView2 runtime installed on this PC. Pass --webview2 <Fixed Version .cab or folder>.")
    return runtime, f"installed runtime {runtime.name} (for releases prefer the official Fixed Version .cab)"


def copy_webview2(runtime: Path, dest: Path, trim_locales: bool):
    def ignore(dirpath, names):
        skip = {n for n in names if n.lower() in WEBVIEW2_SKIP}
        if trim_locales and Path(dirpath).name.lower() == "locales":
            skip |= {n for n in names if not n.lower().startswith("en-us")}
        return skip
    shutil.copytree(runtime, dest, ignore=ignore)


def grant_appcontainer_read(folder: Path):
    """WebView2 renderers run in an AppContainer sandbox; outside Program Files they need explicit
    read access ("ALL APPLICATION PACKAGES" + "ALL RESTRICTED APPLICATION PACKAGES"), otherwise the
    page stays blank. The app repeats this at start-up in case the folder was copied elsewhere."""
    for sid in ("*S-1-15-2-1", "*S-1-15-2-2"):
        subprocess.run(["icacls", str(folder), "/grant", f"{sid}:(OI)(CI)(RX)", "/Q"],
                       check=False, stdout=subprocess.DEVNULL)


# ---------------------------------------------------------------------- build
def main():
    ap = argparse.ArgumentParser(description="Standalone Windows build of PneumoLens AI")
    ap.add_argument("--webview2", help="WebView2 Fixed Version .cab or folder (default: installed runtime)")
    ap.add_argument("--trim-locales", action="store_true", help="keep only en-US WebView2 language files")
    ap.add_argument("--zip", action="store_true", help="also create a .zip of the result")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    if sys.platform != "win32":
        fail("Build on Windows.")

    step("1/5 engine test")
    if not args.skip_tests:
        subprocess.run([sys.executable, str(ROOT / "tests" / "test_engine.py")], check=True)

    step("2/5 Visual C++ runtime DLLs")
    vc = [SYSTEM32 / d for d in VC_RUNTIME if (SYSTEM32 / d).exists()]
    missing = VC_REQUIRED - {p.name.lower() for p in vc}
    if missing:
        fail(f"{', '.join(sorted(missing))} not found in {SYSTEM32}. Install the Visual C++ Redistributable "
             "(x64) on this build PC: https://aka.ms/vs/17/release/vc_redist.x64.exe")
    for p in vc:
        print(f"  {p.name}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        step("3/5 WebView2 runtime")
        runtime, origin = get_webview2(args.webview2, tmp)
        print(f"  source: {runtime}  ({origin})")

        step("4/5 PyInstaller")
        if APP_DIR.exists():
            shutil.rmtree(APP_DIR)
        import PyInstaller.__main__
        sep = os.pathsep
        pyi = ["--noconfirm", "--clean", "--windowed", "--name", NAME,
               "--icon", str(ROOT / "ui" / "logo.ico"),
               "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "standalone"),
               "--specpath", str(ROOT / "build" / "standalone"),
               "--add-data", f"{ROOT / 'ui'}{sep}ui", "--add-data", f"{ROOT / 'models'}{sep}models"]
        for p in vc:
            pyi += ["--add-binary", f"{p}{sep}."]          # -> _internal\ (app.py adds it to the DLL search path)
        PyInstaller.__main__.run(pyi + [str(ROOT / "app.py")])

        step("5/5 bundle WebView2")
        dest = APP_DIR / "webview2"
        copy_webview2(runtime, dest, args.trim_locales)
        grant_appcontainer_read(dest)
        (APP_DIR / "webview2" / "VERSION.txt").write_text(f"{runtime.name}\n{origin}\n", encoding="utf-8")

    internal = APP_DIR / "_internal"
    bundled_vc = sorted(p.name for p in internal.glob("*.dll") if p.name.lower() in {v.lower() for v in VC_RUNTIME})
    if not VC_REQUIRED <= {n.lower() for n in bundled_vc}:
        fail(f"VC++ DLLs missing from the build: {VC_REQUIRED - {n.lower() for n in bundled_vc}}")
    (APP_DIR / "README.txt").write_text(README.format(version=app_version(), webview2=runtime.name), encoding="utf-8")

    print(f"\nDone in {time.time() - t0:.0f} s: {APP_DIR}")
    print(f"  app + Python + model : {folder_mb(internal):6.0f} MB   (VC++ runtime: {', '.join(bundled_vc)})")
    print(f"  WebView2 runtime     : {folder_mb(dest):6.0f} MB")
    if args.zip:
        z = shutil.make_archive(str(ROOT / "dist" / f"{NAME}-standalone-{app_version()}"), "zip", DIST, NAME)
        print(f"  zip                  : {Path(z).stat().st_size / 2**20:6.0f} MB   {z}")
    print("Ship the whole folder (or the zip). Nothing has to be installed on the target PC except "
          ".NET Framework 4.7.2+ where it is missing (Windows Server 2016 / Windows 10 before 1803).")


README = """PneumoLens AI {version} - standalone build
==========================================

Run PneumoLensAI.exe. Nothing needs to be installed: this folder contains Python, the AI model,
the Visual C++ runtime and its own Microsoft Edge WebView2 runtime ({webview2}, in .\\webview2).

Requirements
  * Windows 10 / Windows Server 2016 or newer, 64-bit
  * .NET Framework 4.7.2 or newer. Built into Windows 10 version 1803+ and Windows Server 2019+.
    On Windows Server 2016 or older Windows 10, install .NET Framework 4.8 (offline installer):
    https://dotnet.microsoft.com/download/dotnet-framework/net48
    The app tells you on start-up if it is missing.

Keep the folder together: PneumoLensAI.exe needs _internal\\ and webview2\\ next to it.
It can live anywhere (Program Files, a network share copy, a USB stick, Documents ...).

For research use only. Not intended for clinical diagnosis.
"""

if __name__ == "__main__":
    main()
