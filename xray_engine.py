"""
X-ray analysis engine: image file -> 18 pathology scores, with no PyTorch and no server.

The preprocessing is the server's (TorchXRayVision) pipeline, step for step:
  1. read gray        (DICOM: BitsStored scaling, MONOCHROME1 inverted)
  2. normalize        (2 * x / maxval - 1) * 1024    -> [-1024, 1024]
  3. center crop      to a square (XRayCenterCrop)
  4. resize 224x224   skimage.transform.resize, anti-aliased (XRayResizer)
The model is the ONNX export from ~/Documents/xray_onnx (lesson 2). Its
output already has op_norm applied, so 0.5 is each label's operating point.
tests/test_engine.py checks the scores against the reference pipeline.
"""
from __future__ import annotations

import base64
import io
import json
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

INPUT_SIZE = 224
PREVIEW_MAX_SIDE = 1600          # display copy only; analysis always uses full resolution

# The 11 pathologies shown in the UI (the model outputs 18; exports contain all).
SHOWN_LABELS = ["Atelectasis", "Cardiomegaly", "Consolidation", "Edema", "Effusion",
                "Emphysema", "Fibrosis", "Mass", "Nodule", "Pneumonia", "Pneumothorax"]

# Display bands. HIGH starts at the model's operating point (0.5).
BANDS = {"high": 0.50, "moderate": 0.30}

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".dcm", ".dicom"}


def band(score: float) -> str:
    if score >= BANDS["high"]:
        return "high"
    if score >= BANDS["moderate"]:
        return "moderate"
    return "low"


# --------------------------------------------------------------------------- reading
@dataclass
class XRayImage:
    path: Path
    gray: np.ndarray                 # float32 H x W, original pixel values
    maxval: float                    # full-scale value of the bit depth
    info: dict = field(default_factory=dict)


def _is_dicom(path: Path) -> bool:
    if path.suffix.lower() in {".dcm", ".dicom"}:
        return True
    with open(path, "rb") as f:      # DICOM files without extension: "DICM" at byte 128
        f.seek(128)
        return f.read(4) == b"DICM"


def read_image(path: str | Path) -> XRayImage:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    size_mb = path.stat().st_size / 1e6

    if _is_dicom(path):
        import pydicom
        ds = pydicom.dcmread(path)
        photometric = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
        if photometric not in ("MONOCHROME1", "MONOCHROME2"):
            raise ValueError(f"Unsupported DICOM color type {photometric} (expected grayscale)")
        img = ds.pixel_array.astype(np.float32)
        if img.ndim == 3:            # multi-frame: use the first frame
            img = img[0]
        bits = int(ds.BitsStored)
        maxval = float(2 ** bits - 1)
        if photometric == "MONOCHROME1":
            img = maxval - img
        info = {
            "format": f"DICOM · {bits}-bit · {photometric}",
            "study_date": _dicom_date(getattr(ds, "StudyDate", "")),
            "view": str(getattr(ds, "ViewPosition", "") or ""),
            "modality": str(getattr(ds, "Modality", "") or ""),
        }
    else:
        import skimage.io            # same reader as the server's main.py
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = skimage.io.imread(path)
        if img.dtype == np.uint8:
            maxval, bits = 255.0, 8
        elif np.issubdtype(img.dtype, np.integer):
            bits = max(8, int(np.ceil(np.log2(int(img.max()) + 1))))
            maxval = float(2 ** bits - 1)
        else:
            maxval = 1.0 if img.max() <= 1.0 else float(img.max())
            bits = 32
        if img.ndim == 3 and img.shape[2] == 2:            # gray + alpha
            img, color = img[..., 0], "grayscale"
        elif img.ndim == 3 and img.shape[2] in (3, 4):     # RGB(A): drop alpha, average
            img, color = img[..., :3].mean(2), "color → gray"
        elif img.ndim == 2:
            color = "grayscale"
        else:
            raise ValueError(f"Unsupported image shape {img.shape}")
        img = img.astype(np.float32)
        info = {"format": f"{path.suffix.lstrip('.').upper()} · {bits}-bit {color}"}

    h, w = img.shape
    if min(h, w) < 64:
        raise ValueError(f"Image too small ({w}×{h})")
    info.update(file=path.name, size_mb=round(size_mb, 2), width=w, height=h)
    return XRayImage(path, img, maxval, info)


def _dicom_date(value) -> str:
    s = str(value or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


# --------------------------------------------------------------------------- preprocessing
def preprocess(image: XRayImage) -> np.ndarray:
    """XRayImage -> float32 (1, 1, 224, 224) in [-1024, 1024]. Identical to the server."""
    import skimage.transform
    x = (2.0 * (image.gray / image.maxval) - 1.0) * 1024.0
    h, w = x.shape
    s = min(h, w)
    top, left = h // 2 - s // 2, w // 2 - s // 2
    x = x[top:top + s, left:left + s]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        x = skimage.transform.resize(x[None], (1, INPUT_SIZE, INPUT_SIZE),
                                     mode="constant", preserve_range=True)
    return x[None].astype(np.float32)


def preview_data_url(image: XRayImage) -> str:
    """8-bit JPEG for the viewer (display only)."""
    g = image.gray
    if image.info["format"].startswith("DICOM"):
        # DICOM rarely uses the full bit range: stretch 0.5..99.5 percentile for display
        lo, hi = np.percentile(g, [0.5, 99.5])
    else:
        lo, hi = 0.0, image.maxval
    g8 = np.clip((g - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    im = Image.fromarray(g8)
    im.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- model
PROVIDER_NAMES = {
    "CPUExecutionProvider": "CPU",
    "DmlExecutionProvider": "GPU · DirectML",
    "CUDAExecutionProvider": "GPU · CUDA",
}


class XRayModel:
    def __init__(self, model_path: str | Path, provider: str = "CPUExecutionProvider"):
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        self.provider = provider
        self._session = self._make_session(provider)
        meta = self._session.get_modelmeta().custom_metadata_map
        self.labels: list[str] = json.loads(meta["labels"])
        self.source = meta.get("source", "")
        self.name = self.source.split(",")[-1].strip() or self.model_path.stem

    @staticmethod
    def available_providers() -> list[str]:
        return [p for p in ort.get_available_providers() if p in PROVIDER_NAMES]

    def _make_session(self, provider: str) -> ort.InferenceSession:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        providers = [provider] + (["CPUExecutionProvider"] if provider != "CPUExecutionProvider" else [])
        return ort.InferenceSession(str(self.model_path), so, providers=providers)

    def set_provider(self, provider: str) -> None:
        if provider not in self.available_providers():
            raise ValueError(f"Device not available: {provider}")
        self._session = self._make_session(provider)
        self.provider = provider

    def predict(self, x: np.ndarray) -> dict[str, float]:
        scores = self._session.run(["scores"], {"image": x})[0][0]
        return {label: float(s) for label, s in zip(self.labels, scores)}

    def analyze(self, image: XRayImage) -> dict:
        t0 = time.perf_counter()
        x = preprocess(image)
        t1 = time.perf_counter()
        scores = self.predict(x)
        t2 = time.perf_counter()
        return {
            "scores": scores,
            "preprocess_ms": round((t1 - t0) * 1000, 1),
            "inference_ms": round((t2 - t1) * 1000, 1),
        }
