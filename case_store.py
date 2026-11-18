"""
Case data storage ("dataset"): every patient case is stored as ONE JSON file, <dataset>/<case_id>.json.

Rules (the data must be saved without fail and without repeat):
  * one case = one file. The case id never changes, so saving again updates the same file - there are never
    two records for one case.
  * unchanged data is not written again (content hash); changed data is written as revision + 1.
  * every write is atomic: write a temporary file, flush + fsync, rename over the target, read it back and
    verify it. A crash can leave the old version or the new one, never a half-written file.
  * if the dataset folder cannot be written (missing drive, no permission ...), the record goes to a fallback
    folder in %APPDATA% and the caller is told where it went. Only if that fails too is an error returned.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

SCHEMA = "pneumolens.case/1"
VOLATILE = {"saved_at", "revision", "saved_to"}          # not part of the content hash


def new_case_id() -> str:
    """RPT-YYYYMMDD-HHMMSS-xxxx: sortable by time, unique even for two cases in the same second."""
    return f"RPT-{dt.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def content_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def atomic_write_json(target: Path, data: dict) -> None:
    """Write JSON so that the target is either the old or the complete new file, then verify it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    fd, tmp = tempfile.mkstemp(prefix=target.stem + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    back = json.loads(target.read_text(encoding="utf-8"))          # verify what is on disk
    if back.get("case_id") != data.get("case_id") or back.get("revision") != data.get("revision"):
        raise OSError(f"verification failed for {target}")


class CaseStore:
    def __init__(self, dataset_dir: Path, fallback_dir: Path):
        self.dataset_dir = Path(dataset_dir)
        self.fallback_dir = Path(fallback_dir)
        self.last_hash: str | None = None      # hash of the last record written for the current case
        self.last_path: Path | None = None
        self.revision = 0

    def reset(self, revision: int = 0, last_hash: str | None = None, last_path: Path | None = None):
        """Start tracking a new case (or a case loaded from disk)."""
        self.revision, self.last_hash, self.last_path = revision, last_hash, last_path

    def save(self, record: dict, reason: str) -> dict:
        """Save the case record once. Returns {saved, unchanged, path, fallback, revision, error}."""
        h = content_hash(record)
        if h == self.last_hash and self.last_path and self.last_path.exists():
            return {"saved": False, "unchanged": True, "path": str(self.last_path), "fallback": False,
                    "revision": self.revision}
        rec = dict(record)
        rec["revision"] = self.revision + 1
        rec["saved_at"] = dt.datetime.now().isoformat(timespec="seconds")
        rec["save_reason"] = reason
        name = f"{rec['case_id']}.json"
        errors = []
        for folder, is_fallback in ((self.dataset_dir, False), (self.fallback_dir, True)):
            target = folder / name
            try:
                rec["saved_to"] = str(target)
                atomic_write_json(target, rec)
                # the case now lives here; if it moved to the fallback, the old copy (if any) stays as it was
                self.revision, self.last_hash, self.last_path = rec["revision"], h, target
                return {"saved": True, "unchanged": False, "path": str(target), "fallback": is_fallback,
                        "revision": rec["revision"], "error": "; ".join(errors) or None}
            except Exception as e:                                   # noqa: BLE001 - try the fallback
                errors.append(f"{folder}: {e}")
        return {"saved": False, "unchanged": False, "path": None, "fallback": False, "revision": self.revision,
                "error": "; ".join(errors)}


def load_record(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Not a PneumoLens case file.")
    return data
