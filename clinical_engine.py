"""
Step 2 of PneumoLens AI: clinical weighting of symptoms, auscultation, vital signs, lab data,
spirometry and the step-1 X-ray scores for 7 lung diseases.

All knowledge lives in models/weight.json:
  features  - every input (unit, reference range, evidence patterns)
  diseases  - per disease, every feature in group A/B/C/D with a weight, the expected finding and the reason
  method    - prior, prior strength, low-coverage limit

Scoring (see weight.json "method"):
  s       = evidence 0..1 that the patient shows the finding the disease expects
  match   = (Σ w·s·p + prior·K) / (Σ w·(s + (1-s)·a) + K)   over the items that were entered
            p = presence factor of the group (specificity), a = absence factor (sensitivity; 1 for exclusions)
  coverage= Σ w(entered) / Σ w(all)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GROUP_ORDER = "ABCD"
# a step (X-ray or clinical part) whose evidence weight is below this is "neutral": its own % would only show the
# 20 % prior (no finding clearly for or against), so the report says "neutral" instead of a misleading number
NEUTRAL_EVIDENCE = 1.0


def _ramp(x: float, frm: float, full: float) -> float:
    """0 at `frm`, 1 at `full`, linear in between (works for rising and falling ramps)."""
    if full == frm:
        return 1.0 if x >= full else 0.0
    return min(1.0, max(0.0, (x - frm) / (full - frm)))


class ClinicalModel:
    def __init__(self, path: str | Path, overrides: dict | None = None):
        """`overrides` = the user's weight edits from the app settings, {disease: {feature: {"group", "weight"}}}.
        They are applied on top of weight.json (the file itself is never changed) and checked like the file."""
        self.path = Path(path)
        self.table = json.loads(self.path.read_text(encoding="utf-8"))
        self.features: dict = self.table["features"]
        self.diseases: dict = self.table["diseases"]
        # group and weight of every item as weight.json defines them (for the editor and for "reset")
        self.defaults = {dk: {fid: {"group": it.get("group"), "weight": it.get("weight")} for fid, it in d["items"].items()}
                         for dk, d in self.diseases.items()}
        m = self.table["method"]
        self.prior = float(m["prior"])
        self.k = float(m["prior_strength_K"])
        self.low_coverage = float(m["low_coverage"])
        self.absence = {g: float(v.get("absence_factor", 1.0)) for g, v in m["groups"].items()}
        self.presence = {g: float(v.get("presence_factor", 1.0)) for g, v in m["groups"].items()}
        self.ignored_overrides: list[str] = []      # edits for diseases / inputs weight.json no longer has
        self.overrides = self._apply_overrides(overrides or {})
        self.validate()

    # ------------------------------------------------------------------ user weight edits
    def _apply_overrides(self, overrides: dict) -> dict:
        """Apply the user's group / weight edits to self.diseases. Returns the cleaned edits: only the items that
        differ from weight.json. Raises ValueError for an edit that cannot be used (unknown group, not a number)."""
        if not isinstance(overrides, dict):
            raise ValueError("Weight edits must be an object {disease: {input: {group, weight}}}.")
        groups = self.table["method"]["groups"]
        clean, errors = {}, []
        for dk, items in overrides.items():
            if dk not in self.diseases:
                self.ignored_overrides.append(str(dk))
                continue
            d = self.diseases[dk]
            for fid, ov in (items or {}).items():
                if fid not in d["items"]:
                    self.ignored_overrides.append(f"{dk}.{fid}")
                    continue
                label = f"{d['name']} · {self.features[fid]['label']}"
                base = self.defaults[dk][fid]
                ov = ov if isinstance(ov, dict) else {"weight": ov}
                g = ov.get("group", base["group"])
                if g not in groups:
                    errors.append(f"{label}: group must be one of {', '.join(groups)}, got {g!r}")
                    continue
                if g == "D":
                    w = 0.0                                  # group D = not related: always weight 0
                else:
                    try:
                        w = round(float(ov.get("weight", base["weight"])), 2)
                    except (TypeError, ValueError):
                        errors.append(f"{label}: weight must be a number, got {ov.get('weight')!r}")
                        continue
                    lo, hi = groups[g]["range"]
                    if not lo <= w <= hi:
                        if "weight" in ov:
                            errors.append(f"{label}: weight {w:g} is outside group {g}'s range {lo}–{hi}")
                            continue
                        w = min(hi, max(lo, w))              # only the group changed: move the weight into its range
                    f, it = self.features[fid], d["items"][fid]
                    if base["group"] == "D" and f["input"] == "sounds" and not it.get("sounds"):
                        errors.append(f"{label}: cannot leave group D, weight.json defines no expected "
                                      f"{f['label'].lower()} for {d['name']}")
                        continue
                if g == base["group"] and w == float(base["weight"]):
                    continue                                 # same as weight.json: not an edit
                d["items"][fid] = {**d["items"][fid], "group": g, "weight": w}
                clean.setdefault(dk, {})[fid] = {"group": g, "weight": w}
        if errors:
            raise ValueError("Weight edits are invalid:\n  " + "\n  ".join(errors))
        return clean

    @property
    def edit_count(self) -> int:
        return sum(len(v) for v in self.overrides.values())

    def label(self) -> str:
        """Which weights scored a case, e.g. 'weight.json v1.6' or 'weight.json v1.6 + 3 local edits #1a2b3c4d'.
        The hash identifies the exact edits, so two reports with the same label used the same weights."""
        base = f"{self.path.name} v{self.table.get('version')}"
        if not self.overrides:
            return base
        n = self.edit_count
        digest = hashlib.sha256(json.dumps(self.overrides, sort_keys=True).encode()).hexdigest()[:8]
        return f"{base} + {n} local edit{'s' if n != 1 else ''} #{digest}"

    # ------------------------------------------------------------------ table checks
    def validate(self):
        """Every disease must place every feature in A-D with a weight inside the group's range,
        and every referenced pattern / sound must exist. Raises ValueError with all problems."""
        ranges = {g: v["range"] for g, v in self.table["method"]["groups"].items()}
        errors = []
        for dk, d in self.diseases.items():
            missing = set(self.features) - set(d["items"])
            extra = set(d["items"]) - set(self.features)
            if missing:
                errors.append(f"{dk}: features without a group: {sorted(missing)}")
            if extra:
                errors.append(f"{dk}: unknown features: {sorted(extra)}")
            for fid, it in d["items"].items():
                if fid not in self.features:
                    continue
                f = self.features[fid]
                g, w = it.get("group"), it.get("weight")
                if g not in ranges:
                    errors.append(f"{dk}.{fid}: group must be A-D, got {g!r}")
                    continue
                lo, hi = ranges[g]
                if not isinstance(w, (int, float)) or not lo <= w <= hi:
                    errors.append(f"{dk}.{fid}: weight {w!r} outside group {g} range {lo}-{hi}")
                if not it.get("why"):
                    errors.append(f"{dk}.{fid}: missing 'why'")
                if g == "D":
                    continue
                if f["input"] == "sounds":
                    snd = it.get("sounds") or {}
                    if not snd or set(snd) - set(f["sounds"]):
                        errors.append(f"{dk}.{fid}: needs 'sounds' from {sorted(f['sounds'])}")
                elif f["input"] != "bool" or it.get("expect"):
                    expect = it.get("expect") or f.get("default")
                    if expect not in f["patterns"]:
                        errors.append(f"{dk}.{fid}: unknown pattern {expect!r}")
        # lab subgroups: every lab input in exactly one group
        groups = self.table.get("lab_groups") or []
        if groups:
            listed = [fid for g in groups for fid in g["items"]]
            labs = [fid for fid, f in self.features.items() if f["category"] == "lab"]
            if sorted(listed) != sorted(labs):
                errors.append(f"lab_groups must list every lab input once (missing {sorted(set(labs) - set(listed))}, "
                              f"extra/duplicate {sorted(set(x for x in listed if listed.count(x) > 1 or x not in labs))})")
        # severity signs must point at known inputs / X-ray outputs
        known = set()
        for fid, f in self.features.items():
            known.update(f.get("fields") or [fid])
            if f["input"] == "xray":
                known.add(f["field"])
        known.update({"xray:Pneumothorax", "age"})
        for dk, d in self.diseases.items():
            for sg in (d.get("severity") or {}).get("signs", []):
                for c in [{"field": sg["field"]}] + sg["moderate"] + sg["severe"]:
                    fld = c.get("field", sg["field"])
                    if fld != "bp" and fld not in known:
                        errors.append(f"{dk}.severity: unknown field {fld!r}")
                if not sg["moderate"] + sg["severe"]:
                    errors.append(f"{dk}.severity.{sg['label']}: no thresholds")
        if errors:
            what = f"{self.path.name} with your weight edits" if self.overrides else self.path.name
            raise ValueError(f"{what} is invalid:\n  " + "\n  ".join(errors))

    # ------------------------------------------------------------------ inputs
    def normalize(self, inputs: dict) -> dict:
        """Clean the raw page inputs: numbers as float within limits, booleans, sound lists.
        Empty / invalid values are dropped (= not entered). FEV1/FVC is computed if possible."""
        out = {}
        for fid, f in self.features.items():
            kind = f["input"]
            if kind == "bool":
                v = inputs.get(fid)
                if isinstance(v, bool):
                    out[fid] = v
            elif kind == "sounds":
                v = inputs.get(fid)
                if isinstance(v, str):
                    v = [v]
                if isinstance(v, (list, tuple)):
                    v = [s for s in v if s in f["sounds"]]
                    if f.get("exclusive") in v and len(v) > 1:      # "none" / "normal" excludes the others
                        v = [s for s in v if s != f["exclusive"]]
                    if f.get("single"):
                        v = v[:1]
                    if v:
                        out[fid] = v
            elif kind == "xray":
                continue                                    # filled from the step-1 result
            else:
                fields = f.get("fields") or [fid]
                limits = f.get("limits")
                for fld in fields:
                    x = _num(inputs.get(fld))
                    lim = limits.get(fld) if isinstance(limits, dict) else limits
                    if x is not None and (not lim or lim[0] <= x <= lim[1]):
                        out[fld] = x
        age = _num(inputs.get("age"))                       # from the patient page; used by severity signs only
        if age is not None and 0 <= age <= 130:
            out["age"] = age
        if "fev1_fvc" not in out and "fev1" in out and "fvc" in out and out["fvc"] > 0:
            r = out["fev1"] / out["fvc"] * 100
            if 10 <= r <= 100:
                out["fev1_fvc"] = round(r, 1)
                out["_fev1_fvc_computed"] = True
        return out

    def _entered(self, fid: str, f: dict, values: dict, xray: dict | None) -> bool:
        if f["input"] == "xray":
            return bool(xray) and f["field"].split(":", 1)[1] in xray
        fields = f.get("fields") or [fid]
        return any(fld in values for fld in fields)

    def _evidence(self, pattern: dict, values: dict, fid: str, xray: dict | None) -> float | None:
        t = pattern["type"]
        if t == "present":
            return 1.0 if values.get(fid) else 0.0
        if t == "absent":
            return 0.0 if values.get(fid) else 1.0
        if t == "any":
            parts = [self._evidence(p, values, fid, xray) for p in pattern["of"]]
            parts = [p for p in parts if p is not None]
            return max(parts) if parts else None
        fld = pattern.get("field", fid)
        if fld.startswith("xray:"):
            x = (xray or {}).get(fld.split(":", 1)[1])
        elif fid.startswith("xr_"):
            x = (xray or {}).get(self.features[fid]["field"].split(":", 1)[1])
        else:
            x = values.get(fld)
        if x is None:
            return None
        return _ramp(float(x), pattern["from"], pattern["full"])

    def evidence(self, fid: str, item: dict, values: dict, xray: dict | None) -> float | None:
        f = self.features[fid]
        if not self._entered(fid, f, values, xray):
            return None
        if f["input"] == "sounds":
            heard = values[fid]
            return max((item["sounds"].get(s, 0.0) for s in heard), default=0.0)
        return self._evidence(self.pattern_of(fid, item), values, fid, xray)

    def pattern_of(self, fid: str, item: dict) -> dict | None:
        f = self.features[fid]
        if f["input"] == "sounds":
            return None
        if f["input"] == "bool":
            return f["patterns"][item.get("expect") or "present"]
        return f["patterns"][item.get("expect") or f["default"]]

    def is_exclusion(self, fid: str, item: dict) -> bool:
        pat = self.pattern_of(fid, item)
        return bool(pat and pat.get("exclusion"))

    def absence_factor(self, fid: str, item: dict) -> float:
        """How much a missing finding counts against the disease: by group, but always fully for
        exclusion patterns (no fever, normal spirometry, ...)."""
        pat = self.pattern_of(fid, item)
        if pat and pat.get("exclusion"):
            return 1.0
        return self.absence[item["group"]]

    # ------------------------------------------------------------------ scoring
    def score(self, inputs: dict, xray_scores: dict | None = None) -> dict:
        values = self.normalize(inputs)
        xray = xray_scores or None
        results = []
        for dk, d in self.diseases.items():
            # sums for the combined score and for each part: "xray" (step 1) and "clinical" (step 2)
            acc = {k: {"num": 0.0, "den": 0.0, "total": 0.0, "seen": 0.0} for k in ("all", "xray", "clinical")}
            factors, missing = [], []
            for fid, it in d["items"].items():
                w = float(it["weight"])
                if w <= 0:
                    continue
                part = "xray" if self.features[fid]["category"] == "xray" else "clinical"
                for k in ("all", part):
                    acc[k]["total"] += w
                s = self.evidence(fid, it, values, xray)
                if s is None:
                    missing.append({"id": fid, "label": self.features[fid]["label"], "group": it["group"], "weight": w})
                    continue
                a = self.absence_factor(fid, it)
                p = self.presence[it["group"]]
                if self.is_exclusion(fid, it):
                    # exclusion criterion: a normal value is common to almost every disease, so a fulfilled
                    # exclusion adds nothing; an abnormal value counts fully against the disease
                    up, down, p = 0.0, w * (1 - s), 0.0
                else:
                    up, down = w * s * p, w * (s + (1 - s) * a)
                for k in ("all", part):
                    acc[k]["num"] += up
                    acc[k]["den"] += down
                    acc[k]["seen"] += w
                factors.append({"id": fid, "label": self.features[fid]["label"], "short": self.features[fid].get("short"),
                                "category": self.features[fid]["category"], "part": part, "group": it["group"],
                                "weight": w, "evidence": round(s, 3), "expect": it.get("expect"), "absence": a,
                                "presence": p, "exclusion": self.is_exclusion(fid, it),
                                "value": self.display_value(fid, values, xray), "why": it["why"]})
            num, den = acc["all"]["num"], acc["all"]["den"]
            match = (num + self.prior * self.k) / (den + self.k)
            coverage = acc["all"]["seen"] / acc["all"]["total"] if acc["all"]["total"] else 0.0
            parts = {}
            for k in ("xray", "clinical"):
                a_ = acc[k]
                parts[k] = {
                    "match": round((a_["num"] + self.prior * self.k) / (a_["den"] + self.k), 4),
                    "coverage": round(a_["seen"] / a_["total"], 4) if a_["total"] else 0.0,
                    "used": a_["seen"] > 0,
                    "weight_share": round(a_["den"] / den, 4) if den else 0.0,   # share of the combined evidence
                    # evidence actually carried by this part; < NEUTRAL_EVIDENCE = its % is just the neutral prior
                    "evidence": round(a_["den"], 3),
                    "neutral": a_["seen"] > 0 and a_["den"] < NEUTRAL_EVIDENCE,
                }
            for fc in factors:
                # signed share of this item in the match: what it adds above, minus what it costs below
                # (> 0: the finding supports the disease more than the overall match does; < 0: it pulls it down)
                w, s, a, p = fc["weight"], fc["evidence"], fc["absence"], fc["presence"]
                if fc["exclusion"]:
                    fc["effect"] = round(-match * w * (1 - s) / (den + self.k), 4)
                else:
                    fc["effect"] = round((w * s * p - match * w * (s + (1 - s) * a)) / (den + self.k), 4)
            factors.sort(key=lambda fc: -abs(fc["effect"]))
            missing.sort(key=lambda m: (GROUP_ORDER.index(m["group"]), -m["weight"]))
            # reasons shown in the report: supporting findings, and against = a missing A/B finding or a violated
            # exclusion (a normal value of an occasional C finding, e.g. a severity marker, is not a reason against)
            reasons = {k: {"for": [f for f in factors if f["part"] == k and f["effect"] >= 0.005][:5],
                           "against": [f for f in factors if f["part"] == k and f["effect"] <= -0.005
                                       and (f["group"] in ("A", "B") or f["exclusion"])][:3]}
                       for k in ("xray", "clinical")}
            results.append({
                "id": dk, "name": d["name"], "match": round(match, 4), "coverage": round(coverage, 4),
                "low_confidence": coverage < self.low_coverage,
                "parts": parts, "reasons": reasons, "severity": self.severity(dk, values, xray),
                "factors": factors, "missing": missing,
                "summary": d["summary"], "follow_up": d["follow_up"],
            })
        results.sort(key=lambda r: -r["match"])
        entered = sorted(k for k in values if not k.startswith("_"))
        return {
            "diseases": results,
            "alerts": self.alerts(values),
            "values": {k: v for k, v in values.items() if not k.startswith("_")},
            "fev1_fvc_computed": bool(values.get("_fev1_fvc_computed")),
            "entered": entered,
            "used_xray": bool(xray),
            "table_version": self.table.get("version"),
            "weights_label": self.label(),
        }

    # ------------------------------------------------------------------ severity
    def _sign_value(self, field: str, values: dict, xray: dict | None):
        if field.startswith("xray:"):
            return (xray or {}).get(field.split(":", 1)[1])
        return values.get(field)

    def _cond(self, cond: dict, default_field: str, values: dict, xray: dict | None) -> bool | None:
        x = self._sign_value(cond.get("field", default_field), values, xray)
        if x is None:
            return None
        return (("below" in cond and x < cond["below"]) or ("at_most" in cond and x <= cond["at_most"]) or
                ("at_least" in cond and x >= cond["at_least"]) or ("above" in cond and x > cond["above"]))

    def severity(self, disease_id: str, values: dict, xray: dict | None) -> dict:
        """Grade how severe the disease is from its guideline severity signs (weight.json diseases.*.severity):
        each entered sign is none / moderate / severe; the grade follows method.severity."""
        spec = self.diseases[disease_id].get("severity")
        rule = self.table["method"].get("severity", {})
        if not spec:
            return {"grade": "Not assessable", "points": 0, "signs": [], "assessed": 0, "total": 0, "source": ""}
        pts = rule.get("points", {"moderate": 1, "severe": 2})
        signs, points, n_severe, assessed = [], 0, 0, 0
        for sg in spec["signs"]:
            sev = [self._cond(c, sg["field"], values, xray) for c in sg["severe"]]
            mod = [self._cond(c, sg["field"], values, xray) for c in sg["moderate"]]
            if all(v is None for v in sev + mod):
                continue                                            # this sign's value was not entered
            assessed += 1
            level = "severe" if any(sev) else "moderate" if any(mod) else "none"
            points += pts.get(level, 0)
            n_severe += level == "severe"
            signs.append({"label": sg["label"], "level": level, "why": sg["why"],
                          "value": self._sign_display(sg["field"], values, xray)})
        if points == 0 and assessed < rule.get("min_signs", 2):
            grade = "Not assessable"                                 # too little measured to call it mild
        elif n_severe >= rule.get("severe_signs", 2) or points >= rule.get("severe_points", 4):
            grade = "Severe"
        elif points >= 1:
            grade = "Moderate"
        else:
            grade = "Mild"
        signs.sort(key=lambda s: {"severe": 0, "moderate": 1, "none": 2}[s["level"]])
        return {"grade": grade, "points": points, "severe_signs": n_severe, "signs": signs,
                "assessed": assessed, "total": len(spec["signs"]), "source": spec.get("source", "")}

    def _sign_display(self, field: str, values: dict, xray: dict | None) -> str:
        if field.startswith("xray:"):
            x = (xray or {}).get(field.split(":", 1)[1])
            return "" if x is None else f"{x * 100:.0f}%"
        if field in self.features:
            return self.display_value(field, values, xray)
        if field == "age":
            return f"{_fmt(values.get('age'))} y"
        return _fmt(values.get(field))

    def value_rows(self, inputs: dict) -> dict:
        """Entered step-2 data in report form: symptoms present / absent, auscultation and one row per
        measured value with its reference range and a HIGH / LOW / NORMAL flag."""
        values = self.normalize(inputs)
        out = {"present": [], "absent": [], "sounds": [], "rows": []}
        for fid, f in self.features.items():
            kind = f["input"]
            if kind == "bool" and fid in values:
                out["present" if values[fid] else "absent"].append(f["label"])
            elif kind == "sounds" and fid in values:
                if fid == "auscultation":
                    out["sounds"] = [f["sounds"][s] for s in values[fid]]
                else:                                               # history: exposure, duration
                    out["rows"].append({"id": fid, "label": f["label"], "short": f.get("short"), "category": f["category"],
                                        "subgroup": None, "value": self.display_value(fid, values, None),
                                        "ref": "", "unit": "", "flag": ""})
            elif kind in ("number", "bp"):
                fields = f.get("fields") or [fid]
                if not any(fld in values for fld in fields):
                    continue
                flag = "NORMAL"
                for fld in fields:
                    x = values.get(fld)
                    ref = f["ref"].get(fld) if isinstance(f.get("ref"), dict) else f.get("ref")
                    if x is None or not ref:
                        if not ref:
                            flag = ""
                        continue
                    if x < ref[0]:
                        flag = "LOW"
                    elif x > ref[1] and flag != "LOW":
                        flag = "HIGH"
                ref_txt = f.get("ref_text") or (f"{f['ref'][0]}–{f['ref'][1]}" if isinstance(f.get("ref"), list) else "")
                if fid == "fev1_fvc" and values.get("_fev1_fvc_computed"):
                    ref_txt += " (calculated)"
                out["rows"].append({"id": fid, "label": f["label"], "short": f.get("short"), "category": f["category"],
                                    "subgroup": f.get("subgroup"),
                                    "value": self.display_value(fid, values, None), "ref": ref_txt,
                                    "unit": f.get("unit", ""), "flag": flag})
        return out

    def alerts(self, values: dict) -> list[str]:
        out = []
        for a in self.table.get("alerts", []):
            x = values.get(a["field"])
            if x is None:
                continue
            if ("below" in a and x < a["below"]) or ("at_most" in a and x <= a["at_most"]) or \
               ("at_least" in a and x >= a["at_least"]) or ("above" in a and x > a["above"]):
                out.append(a["text"])
        return out

    def display_value(self, fid: str, values: dict, xray: dict | None) -> str:
        f = self.features[fid]
        if f["input"] == "bool":
            return "yes" if values[fid] else "no"
        if f["input"] == "sounds":
            return ", ".join(f["sounds"][s] for s in values[fid])
        if f["input"] == "xray":
            return f"{xray[f['field'].split(':', 1)[1]] * 100:.0f}%"
        if f["input"] == "bp":
            return f"{_fmt(values.get('sbp'))}/{_fmt(values.get('dbp'))} {f['unit']}"
        unit = f.get("unit", "")
        return f"{_fmt(values[fid])} {'' if '–' in unit else unit}".strip()     # GCS "3–15" is a scale, not a unit

    def for_ui(self) -> dict:
        """The parts of weight.json the page needs to build the form and the weight table."""
        return {
            "version": self.table.get("version"),
            "label": self.label(),
            "defaults": self.defaults,                  # weight.json's own group / weight of every item
            "overrides": self.overrides,                # the user's edits that are in effect
            "categories": self.table["categories"],
            "groups": self.table["method"]["groups"],
            "features": self.features,
            "diseases": {k: {"name": d["name"], "icd10": d.get("icd10"), "summary": d["summary"],
                             "references": d.get("references", []), "items": d["items"]}
                         for k, d in self.diseases.items()},
            "method": self.table["method"],
            "xray_selection": self.table.get("xray_selection"),
            "lab_groups": self.table.get("lab_groups", []),
            "spirometry_assessment": self.table.get("spirometry_assessment"),
            "disclaimer": self.table.get("disclaimer"),
        }


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace(",", ".").strip())
    except ValueError:
        return None
    return x if x == x else None          # NaN -> None


def _fmt(x):
    if x is None:
        return "—"
    return f"{x:g}"
