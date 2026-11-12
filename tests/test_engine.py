"""
Checks that the app's engine gives the same scores as the server's PyTorch pipeline.

reference_scores.json was produced with the original PyTorch model and
TorchXRayVision's own preprocessing (see xray_onnx/common.py). If anyone changes
the reader, preprocessing or model file, this test fails instead of the app
silently showing different numbers.

Run:  python tests/test_engine.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from xray_engine import XRayModel, read_image  # noqa: E402

TOL = 1e-4


def main() -> int:
    refs = json.loads((HERE / "reference_scores.json").read_text())
    model = XRayModel(HERE.parent / "models" / "xray_densenet121.onnx")
    failed = False
    for name, ref in refs.items():
        if name.startswith("_"):
            continue
        result = model.analyze(read_image(HERE / "images" / name))
        diff = max(abs(result["scores"][k] - v) for k, v in ref.items())
        ok = diff < TOL
        failed |= not ok
        print(f"{name:<26} max |diff| = {diff:.2e}  "
              f"({result['preprocess_ms']:.0f} + {result['inference_ms']:.0f} ms)  {'OK' if ok else 'FAIL'}")
    print("RESULT:", "FAIL" if failed else "PASS")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
