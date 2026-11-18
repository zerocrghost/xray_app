"""
Checks models/weight.json and clinical_engine.py:
  1. the table is complete and valid (every disease places every input in A-D, weights in range)
  2. a textbook case of each of the 7 diseases ranks that disease first
  3. edge cases: empty input, partial input, computed FEV1/FVC, alerts, invalid values

Run:  python tests/test_clinical.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import clinical_engine as ce  # noqa: E402

WEIGHTS = ROOT / "models" / "weight.json"
NO = False
YES = True

# Low X-ray scores everywhere unless a case sets them (typical background output of the model)
XR_BASE = {k: 0.15 for k in ["Pneumonia", "Consolidation", "Lung Opacity", "Infiltration", "Atelectasis", "Effusion",
                             "Pleural_Thickening", "Emphysema", "Fibrosis", "Mass", "Lung Lesion", "Nodule",
                             "Cardiomegaly", "Edema", "Pneumothorax"]}

CASES = {
    "asthma": (
        dict(fever=NO, dyspnea=YES, wheezing=YES, cough=YES, sputum=NO, chest_pain=YES, auscultation=["wheeze"],
             sbp=128, dbp=78, pr=108, bt=36.7, rr=24, gcs=15, spo2=94,
             wbc=7.8, esr=8, stab=3, seg=55, eos=11, bas=1.2, lym=28, mon=5, alt=22, ast=24, tp=7.2, ztt=8, glu=96,
             fev1=1.9, fvc=3.4, pfev1=62),
        {}),
    "copd": (
        dict(fever=NO, dyspnea=YES, wheezing=YES, cough=YES, sputum=YES, chest_pain=NO, auscultation=["diminished", "rhonchi"],
             sbp=138, dbp=82, pr=96, bt=36.6, rr=22, gcs=15, spo2=91,
             wbc=8.2, esr=14, stab=4, seg=66, eos=3, bas=0.6, lym=24, mon=7, alt=20, ast=25, tp=6.9, ztt=10, glu=104,
             fev1=1.1, fvc=2.6, pfev1=42),
        {"Emphysema": 0.78}),
    "pneumonia": (
        dict(fever=YES, dyspnea=YES, wheezing=NO, cough=YES, sputum=YES, chest_pain=YES, auscultation=["coarse_crackles", "bronchial"],
             sbp=112, dbp=68, pr=112, bt=38.9, rr=26, gcs=15, spo2=92,
             wbc=16.4, esr=48, stab=14, seg=80, eos=0.5, bas=0.2, lym=9, mon=6, alt=48, ast=52, tp=6.4, ztt=9, glu=142),
        {"Pneumonia": 0.74, "Consolidation": 0.71, "Lung Opacity": 0.68, "Infiltration": 0.6}),
    "pleurisy": (
        dict(fever=YES, dyspnea=YES, wheezing=NO, cough=YES, sputum=NO, chest_pain=YES, auscultation=["friction_rub", "diminished"],
             sbp=124, dbp=76, pr=98, bt=37.8, rr=23, gcs=15, spo2=95,
             wbc=9.6, esr=55, stab=5, seg=68, eos=2, bas=0.5, lym=22, mon=10, alt=24, ast=26, tp=7.1, ztt=11, glu=98),
        {"Effusion": 0.82, "Pleural_Thickening": 0.66}),
    "chronic_bronchitis": (
        dict(fever=NO, dyspnea=NO, wheezing=YES, cough=YES, sputum=YES, chest_pain=NO, auscultation=["rhonchi"],
             sbp=132, dbp=84, pr=82, bt=36.5, rr=18, gcs=15, spo2=96,
             wbc=7.4, esr=12, stab=3, seg=60, eos=2, bas=0.5, lym=30, mon=6, alt=21, ast=23, tp=7.3, ztt=9, glu=101,
             fev1=2.6, fvc=3.6, pfev1=82),
        {}),
    "lung_abscess": (
        dict(fever=YES, dyspnea=NO, wheezing=NO, cough=YES, sputum=YES, chest_pain=YES, auscultation=["coarse_crackles"],
             sbp=104, dbp=62, pr=108, bt=39.2, rr=22, gcs=14, spo2=95,
             wbc=19.5, esr=95, stab=12, seg=82, eos=0.5, bas=0.2, lym=10, mon=11, alt=46, ast=88, tp=5.6, ztt=18, glu=230),
        {"Mass": 0.72, "Lung Lesion": 0.55, "Consolidation": 0.45, "Lung Opacity": 0.55}),
    "bronchiectasis": (
        dict(fever=NO, dyspnea=YES, wheezing=YES, cough=YES, sputum=YES, chest_pain=NO, auscultation=["coarse_crackles", "rhonchi"],
             sbp=122, dbp=74, pr=88, bt=37.0, rr=19, gcs=15, spo2=94,
             wbc=9.8, esr=42, stab=4, seg=72, eos=2, bas=0.4, lym=21, mon=8, alt=19, ast=22, tp=7.6, ztt=19, glu=99,
             fev1=1.8, fvc=2.9, pfev1=64),
        {"Atelectasis": 0.58, "Infiltration": 0.55, "Fibrosis": 0.5}),
}

results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def ranking(r):
    return ", ".join(f"{d['name']} {d['match'] * 100:.0f}%" for d in r["diseases"])


def main():
    m = ce.ClinicalModel(WEIGHTS)
    table = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    n_feat = len(table["features"])
    check("weight.json: 7 diseases", len(m.diseases) == 7, ", ".join(d["name"] for d in m.diseases.values()))
    check(f"weight.json: every disease places all {n_feat} inputs in A-D",
          all(len(d["items"]) == n_feat for d in m.diseases.values()))
    for dk, d in m.diseases.items():
        groups = {g: sum(1 for it in d["items"].values() if it["group"] == g) for g in "ABCD"}
        check(f"{d['name']}: has A items and a reason for every item",
              groups["A"] >= 2 and all(it.get("why") for it in d["items"].values()), str(groups))

    # step-1 X-ray outputs: every model label is either used (and is a feature) or excluded with a reason
    sel = table["xray_selection"]
    model_labels = [k for k in json.loads((ROOT / "tests" / "reference_scores.json").read_text())["01_nih_sample.jpg"]]
    xr_feats = {f["field"].split(":", 1)[1] for f in table["features"].values() if f["category"] == "xray"}
    check("X-ray selection covers all 18 model outputs",
          sorted(set(sel["used"]) | set(sel["not_used"])) == sorted(model_labels) and not set(sel["used"]) & set(sel["not_used"]),
          f"{len(sel['used'])} used, {len(sel['not_used'])} not used: {', '.join(sel['not_used'])}")
    check("every used X-ray finding is weighted for every disease", xr_feats == set(sel["used"]))

    # a broken table is rejected
    bad = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    bad["diseases"]["asthma"]["items"]["wheezing"]["weight"] = 9
    del bad["diseases"]["copd"]["items"]["glu"]
    tmp = ROOT / "build" / "bad_weight.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(bad), encoding="utf-8")
    try:
        ce.ClinicalModel(tmp)
        check("invalid table is rejected", False)
    except ValueError as e:
        check("invalid table is rejected", "outside group A" in str(e) and "copd" in str(e))

    # textbook cases
    for expected, (inputs, xr) in CASES.items():
        r = m.score(inputs, {**XR_BASE, **xr})
        top = r["diseases"][0]
        check(f"case {expected}: ranked first", top["id"] == expected, ranking(r))
        check(f"case {expected}: full coverage, confident", not top["low_confidence"], f"coverage {top['coverage']:.0%}")

    # a severe acute-infection picture with the REAL step-1 model output of every test image: the X-ray model
    # scores 'Pneumonia' low on these images, but the clinical picture must still put pneumonia first
    severe = dict(fever=YES, dyspnea=YES, cough=YES, sputum=YES, chest_pain=YES, wheezing=NO,
                  auscultation=["coarse_crackles", "bronchial"], sbp=104, dbp=62, pr=112, bt=38.9, rr=31, gcs=15,
                  spo2=89, wbc=16.4, esr=48, stab=14, seg=80, lym=9, alt=48, ast=52, glu=142)
    ref = json.loads((ROOT / "tests" / "reference_scores.json").read_text(encoding="utf-8"))
    for img, xr in ref.items():
        if img.startswith("_"):
            continue
        r = m.score(severe, xr)
        check(f"severe infection + real X-ray of {img}: pneumonia first", r["diseases"][0]["id"] == "pneumonia", ranking(r))

    # same pneumonia case without the X-ray still points to pneumonia
    r = m.score(CASES["pneumonia"][0], None)
    check("pneumonia without X-ray: still first", r["diseases"][0]["id"] == "pneumonia", ranking(r))

    # empty input: every disease sits at the prior and is low confidence
    r = m.score({}, None)
    check("empty input: all at prior, low confidence",
          all(abs(d["match"] - m.prior) < 1e-9 and d["low_confidence"] for d in r["diseases"]))

    # one finding only: low confidence, but the right direction
    r = m.score({"wheezing": True}, None)
    top = r["diseases"][0]
    check("wheezing only: asthma first but low confidence", top["id"] == "asthma" and top["low_confidence"], ranking(r))

    # FEV1/FVC computed from FEV1 and FVC
    r = m.score({"fev1": 1.4, "fvc": 2.8}, None)
    check("FEV1/FVC computed (50 %)", r["values"].get("fev1_fvc") == 50.0 and r["fev1_fvc_computed"])

    # invalid / out-of-range values are ignored
    r = m.score({"bt": "abc", "spo2": 140, "pr": "", "wbc": "12,5"}, None)
    check("invalid values ignored, decimal comma accepted", r["entered"] == ["wbc"] and r["values"]["wbc"] == 12.5,
          str(r["entered"]))

    # alerts
    r = m.score({"spo2": 88, "rr": 32, "sbp": 85, "dbp": 55, "gcs": 13, "bt": 39.4}, None)
    check("severity alerts", len(r["alerts"]) == 6, " | ".join(r["alerts"]))

    # factors: the top factor for the pneumonia case raises the score
    r = m.score(CASES["pneumonia"][0], {**XR_BASE, **CASES["pneumonia"][1]})
    f0 = r["diseases"][0]["factors"][0]
    check("pneumonia: strongest factor raises the score", f0["effect"] > 0, f"{f0['label']} {f0['effect']:+.3f}")

    # step-1 / step-2 parts and reasons
    r = m.score(CASES["pneumonia"][0], {**XR_BASE, **CASES["pneumonia"][1]})
    top = r["diseases"][0]
    check("parts: X-ray and clinical sub-scores are both computed",
          top["parts"]["xray"]["used"] and top["parts"]["clinical"]["used"] and
          top["parts"]["xray"]["match"] > 0.5 and top["parts"]["clinical"]["match"] > 0.5,
          f"X-ray {top['parts']['xray']['match']:.0%}, clinical {top['parts']['clinical']['match']:.0%}")
    check("reasons: supporting X-ray and clinical findings are listed",
          top["reasons"]["xray"]["for"] and top["reasons"]["clinical"]["for"] and
          all(f["part"] == "xray" for f in top["reasons"]["xray"]["for"]),
          f"X-ray: {', '.join(f['label'] for f in top['reasons']['xray']['for'][:3])}")
    r = m.score(CASES["pneumonia"][0], None)
    check("without an X-ray the X-ray part is marked unused", not r["diseases"][0]["parts"]["xray"]["used"])
    supports = [f for d in m.score(CASES["asthma"][0], XR_BASE)["diseases"] for f in d["factors"] if f["exclusion"] and f["effect"] > 0]
    check("a fulfilled exclusion never counts FOR a disease", not supports)

    # history & exposure (GOLD): exposure and a chronic course support COPD; an acute, unexposed course argues against it
    copd_in, copd_xr = CASES["copd"]
    base = m.score(copd_in, {**XR_BASE, **copd_xr})
    hist = m.score({**copd_in, "exposure": ["smoking_current", "occupational"], "pack_years": 40, "duration": "years"},
                   {**XR_BASE, **copd_xr})
    get = lambda r, k: next(d for d in r["diseases"] if d["id"] == k)["match"]
    check("COPD: exposure + pack-years + years-long course raise COPD and widen its lead over asthma",
          hist["diseases"][0]["id"] == "copd" and get(hist, "copd") > get(base, "copd") and
          get(hist, "copd") - get(hist, "asthma") > get(base, "copd") - get(base, "asthma"),
          f"COPD {get(base, 'copd'):.0%} → {get(hist, 'copd'):.0%}, vs asthma "
          f"{get(base, 'copd') - get(base, 'asthma'):+.0%} → {get(hist, 'copd') - get(hist, 'asthma'):+.0%}")
    acute = m.score({**copd_in, "exposure": ["none"], "pack_years": 0, "duration": "acute"}, {**XR_BASE, **copd_xr})
    c_acute = next(d for d in acute["diseases"] if d["id"] == "copd")["match"]
    c_base = next(d for d in base["diseases"] if d["id"] == "copd")["match"]
    check("COPD: no exposure and an acute 2-week course lower COPD", c_acute < c_base - 0.05, f"{c_base:.0%} → {c_acute:.0%}")
    r = m.score({**CASES["chronic_bronchitis"][0], "duration": "years", "exposure": ["smoking_current"]}, None)
    check("chronic bronchitis with a years-long course and smoking stays first", r["diseases"][0]["id"] == "chronic_bronchitis",
          ranking(r))
    r = m.score({**CASES["lung_abscess"][0], "duration": "subacute"}, {**XR_BASE, **CASES["lung_abscess"][1]})
    check("lung abscess with a subacute course stays first", r["diseases"][0]["id"] == "lung_abscess", ranking(r))
    r = m.score({"duration": ["acute", "years"], "exposure": ["none", "biomass"]}, None)
    check("single-choice duration keeps one answer; 'none' is dropped when an exposure is chosen",
          r["values"]["duration"] == ["acute"] and r["values"]["exposure"] == ["biomass"], str(r["values"]))

    # a step without real evidence is "neutral" (its own % is only the prior) and barely moves the final score
    from app import _map_lab_names as _m
    cb_in, _ = _m(json.loads((ROOT / "tests" / "cases" / "chronic_bronchitis_01.json").read_text(encoding="utf-8")), m)
    xr02 = json.loads((ROOT / "tests" / "reference_scores.json").read_text(encoding="utf-8"))["02_pneumonia_case.jpg"]
    cb = next(d for d in m.score(cb_in, xr02)["diseases"] if d["id"] == "chronic_bronchitis")
    check("X-ray part without clear evidence is marked neutral; final ≈ clinical part",
          cb["parts"]["xray"]["neutral"] and abs(cb["match"] - cb["parts"]["clinical"]["match"]) < 0.03,
          f"X-ray {cb['parts']['xray']['match']:.0%} (neutral), clinical {cb['parts']['clinical']['match']:.0%}, final {cb['match']:.0%}")

    # blank lab fields are skipped (not required, not treated as normal)
    r = m.score({"wbc": "", "esr": "  ", "stab": None, "alt": "", "glu": "", "fever": True}, None)
    check("blank lab fields are skipped", r["entered"] == ["fever"], str(r["entered"]))

    # Import Lab File name matching: "%FEV1" (percent predicted) must not land in "FEV1" (litres) and vice versa
    from app import _map_lab_names
    mapped, unknown = _map_lab_names({"FEV1": "1.2", "%FEV1": "45", "FVC": "2.7", "FEV1/FVC": "44", "SpO2": "91",
                                      "BP": "120/80", "Pack-years": "30", "Duration": "Years · slowly progressive"}, m)
    check("import keeps FEV1, %FEV1, FVC and FEV1/FVC apart",
          mapped.get("fev1") == "1.2" and mapped.get("pfev1") == "45" and mapped.get("fvc") == "2.7"
          and mapped.get("fev1_fvc") == "44" and mapped.get("duration") == ["years"] and not unknown, str(mapped))

    # the 70 example patients in tests/cases (10 per disease, clinical data only)
    case_dir = ROOT / "tests" / "cases"
    files = sorted(case_dir.glob("*.json"))
    if files:
        t1 = t3 = 0
        for fp in files:
            doc = json.loads(fp.read_text(encoding="utf-8"))
            inputs, _ = _map_lab_names(doc, m)
            names = [d["name"] for d in m.score(inputs, None)["diseases"]]
            t1 += names[0] == doc["_expected"]
            t3 += doc["_expected"] in names[:3]
        check(f"{len(files)} example cases: expected disease 1st in ≥ 85 %, top 3 in ≥ 95 %",
              t1 >= 0.85 * len(files) and t3 >= 0.95 * len(files), f"1st {t1}/{len(files)}, top 3 {t3}/{len(files)}")

    # severity: guideline signs graded none / moderate / severe
    sev = m.score(severe, None)
    pn = next(d for d in sev["diseases"] if d["id"] == "pneumonia")["severity"]
    check("severity: clear abnormal vital signs → Severe", pn["grade"] == "Severe",
          ", ".join(f"{s['label']} {s['value']} {s['level']}" for s in pn["signs"] if s["level"] != "none"))
    mild = dict(severe, sbp=128, dbp=78, pr=92, bt=37.8, rr=20, spo2=96, wbc=10.5, stab=5, lym=22)
    pn = next(d for d in m.score(mild, None)["diseases"] if d["id"] == "pneumonia")["severity"]
    check("severity: weak signals (just outside the reference range) → Mild", pn["grade"] == "Mild", f"{pn['assessed']} signs, 0 points")
    mid = dict(mild, spo2=93, bt=38.4)
    pn = next(d for d in m.score(mid, None)["diseases"] if d["id"] == "pneumonia")["severity"]
    check("severity: some clear signals → Moderate", pn["grade"] == "Moderate", f"{pn['points']} points")
    pn = next(d for d in m.score({"fever": True, "cough": True}, None)["diseases"] if d["id"] == "pneumonia")["severity"]
    check("severity: no vital signs entered → Not assessable", pn["grade"] == "Not assessable")
    cp = next(d for d in m.score(CASES["copd"][0], None)["diseases"] if d["id"] == "copd")["severity"]
    check("severity: COPD with %FEV1 42 and SpO2 91 is graded by GOLD signs",
          any(s["label"] == "%FEV1" and s["level"] == "severe" for s in cp["signs"]) and cp["grade"] in ("Moderate", "Severe"),
          f"{cp['grade']}, {cp['points']} points")
    check("every disease has guideline severity signs", all(d.get("severity", {}).get("signs") for d in m.diseases.values()))

    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
