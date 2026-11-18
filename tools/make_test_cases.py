"""
Writes tests/cases/: 10 example patients for each of the 7 diseases (70 JSON files) plus index.csv.

Each file can be loaded on step 2 with "Import Lab File". Keys starting with "_" are case notes and are
ignored by the import. The variants per disease cover: typical, mild, severe, atypical / subtype
presentations and incomplete data (no labs, no spirometry, minimal data), so the weighting is tested
on more than textbook cases.

    .venv\\Scripts\\python tools\\make_test_cases.py          (writes the files and prints how each case ranks)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tests" / "cases"

DIFF = ["stab", "seg", "eos", "bas", "lym", "mon"]
LABS = ["wbc", "esr", *DIFF, "alt", "ast", "tp", "ztt", "glu"]
SPIRO = ["fev1", "fvc", "pfev1"]
NO = "__drop__"

# ------------------------------------------------------------------ base profiles (typical presentation)
BASE = {
    "asthma": dict(
        fever="no", dyspnea="yes", wheezing="yes", cough="yes", sputum="no", chest_pain="yes",
        exposure=[], duration="episodic", auscultation=["wheeze"],
        BP="124/76", pr=96, bt=36.7, rr=22, gcs=15, spo2=95,
        wbc=7.6, esr=8, stab=2, seg=52, eos=9, bas=1, lym=30, mon=6, alt=20, ast=22, tp=7.2, ztt=8, glu=95,
        fev1=2.1, fvc=3.6, pfev1=68),
    "copd": dict(
        fever="no", dyspnea="yes", wheezing="yes", cough="yes", sputum="yes", chest_pain="no",
        exposure=["smoking_current"], pack_years=45, duration="years", auscultation=["diminished", "rhonchi"],
        BP="138/84", pr=94, bt=36.6, rr=22, gcs=15, spo2=91,
        wbc=8.4, esr=15, stab=3, seg=66, eos=2, bas=0.5, lym=22, mon=6.5, alt=22, ast=24, tp=6.9, ztt=10, glu=108,
        fev1=1.2, fvc=2.7, pfev1=45),
    "pneumonia": dict(
        fever="yes", dyspnea="yes", wheezing="no", cough="yes", sputum="yes", chest_pain="yes",
        exposure=[], duration="acute", auscultation=["coarse_crackles", "bronchial"],
        BP="118/72", pr=108, bt=38.8, rr=24, gcs=15, spo2=93,
        wbc=15.2, esr=45, stab=12, seg=74, eos=0.5, bas=0.3, lym=9, mon=4.2, alt=38, ast=41, tp=6.6, ztt=9, glu=128),
    "pleurisy": dict(
        fever="yes", dyspnea="yes", wheezing="no", cough="yes", sputum="no", chest_pain="yes",
        exposure=[], duration="acute", auscultation=["friction_rub", "diminished"],
        BP="122/76", pr=98, bt=37.9, rr=22, gcs=15, spo2=95,
        wbc=10.4, esr=52, stab=5, seg=70, eos=1, bas=0.5, lym=19, mon=4.5, alt=24, ast=26, tp=7.1, ztt=11, glu=98,
        fev1=2.4, fvc=2.9, pfev1=78),
    "chronic_bronchitis": dict(
        fever="no", dyspnea="no", wheezing="yes", cough="yes", sputum="yes", chest_pain="no",
        exposure=["smoking_current"], pack_years=25, duration="years", auscultation=["rhonchi"],
        BP="132/84", pr=82, bt=36.5, rr=17, gcs=15, spo2=96,
        wbc=7.4, esr=12, stab=3, seg=60, eos=2, bas=0.5, lym=28, mon=6.5, alt=21, ast=23, tp=7.3, ztt=9, glu=101,
        fev1=2.8, fvc=3.7, pfev1=84),
    "lung_abscess": dict(
        fever="yes", dyspnea="no", wheezing="no", cough="yes", sputum="yes", chest_pain="yes",
        exposure=[], duration="subacute", auscultation=["coarse_crackles", "bronchial"],
        BP="112/70", pr=106, bt=38.9, rr=21, gcs=15, spo2=95,
        wbc=18.6, esr=88, stab=11, seg=78, eos=0.5, bas=0.2, lym=7, mon=3.3, alt=42, ast=70, tp=5.9, ztt=17, glu=168),
    "bronchiectasis": dict(
        fever="no", dyspnea="yes", wheezing="yes", cough="yes", sputum="yes", chest_pain="no",
        exposure=["none"], duration="years", auscultation=["coarse_crackles", "rhonchi"],
        BP="122/74", pr=88, bt=37.0, rr=19, gcs=15, spo2=94,
        wbc=9.6, esr=44, stab=4, seg=70, eos=2, bas=0.4, lym=18, mon=5.6, alt=19, ast=22, tp=7.7, ztt=19, glu=99,
        fev1=1.9, fvc=2.9, pfev1=66),
}

# ------------------------------------------------------------------ 10 variants per disease: (title, overrides)
# NO removes a field; "only" keeps just the listed fields (minimal data)
V = {
    "asthma": [
        ("Typical allergic asthma attack", {}),
        ("Mild intermittent asthma", dict(spo2=98, rr=16, pr=78, eos=6, fev1=2.9, fvc=3.8, pfev1=84, chest_pain="no")),
        ("Severe exacerbation", dict(rr=32, pr=128, spo2=88, fev1=1.2, fvc=2.9, pfev1=38, eos=7)),
        ("Cough-variant asthma (no wheeze)", dict(wheezing="no", dyspnea="no", chest_pain="no", auscultation=["normal"],
                                                  eos=8, fev1=2.8, fvc=3.7, pfev1=82, duration="chronic")),
        ("Occupational asthma", dict(exposure=["occupational"])),
        ("Viral-triggered attack (low fever)", dict(fever="yes", bt=37.8, wbc=9.5, lym=34, eos=4, sputum="yes")),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("No spirometry", {**{k: NO for k in SPIRO}}),
        ("Young patient, marked eosinophilia", dict(eos=14, bas=2, pr=88, spo2=96)),
        ("Minimal data", dict(only=["wheezing", "dyspnea", "auscultation", "duration"])),
    ],
    "copd": [
        ("Typical COPD, current smoker (GOLD 3)", {}),
        ("Mild COPD (GOLD 1)", dict(pfev1=82, fev1=2.4, fvc=3.6, spo2=95, rr=18, pr=80, wheezing="no")),
        ("Severe hypercapnic exacerbation", dict(spo2=84, rr=30, pr=118, gcs=13, pfev1=28, fev1=0.7, fvc=1.9)),
        ("Former smoker", dict(exposure=["smoking_former"], pack_years=30)),
        ("Never-smoker, biomass smoke", dict(exposure=["biomass"], pack_years=0)),
        ("Occupational dust + former smoker", dict(exposure=["occupational", "smoking_former"], pack_years=15)),
        ("Eosinophilic phenotype", dict(eos=6)),
        ("Infective exacerbation", dict(fever="yes", bt=38.2, wbc=12.8, stab=6, lym=13, esr=32)),
        ("No spirometry", {**{k: NO for k in SPIRO}}),
        ("Minimal data", dict(only=["dyspnea", "cough", "exposure", "pack_years", "duration", "fev1", "fvc"],
                              fev1=1.4, fvc=2.6)),
    ],
    "pneumonia": [
        ("Typical bacterial pneumonia", {}),
        ("Mild outpatient pneumonia", dict(bt=38.1, pr=92, rr=19, spo2=96, wbc=11.8, stab=6, lym=18, esr=30,
                                          chest_pain="no", auscultation=["fine_crackles"])),
        ("Severe pneumonia (CURB-65 high)", dict(BP="86/54", rr=33, gcs=13, spo2=86, pr=124, bt=39.6, wbc=22,
                                                stab=20, lym=6, glu=190)),
        ("Elderly, afebrile presentation", dict(fever="no", bt=36.9, gcs=14, rr=26, spo2=90, wbc=13.5, chest_pain="no")),
        ("Atypical (Mycoplasma-like)", dict(sputum="no", wbc=8.9, stab=3, lym=28, alt=62, ast=58, bt=38.4,
                                           auscultation=["fine_crackles"])),
        ("Severe with leukopenia", dict(wbc=3.2, stab=18, lym=8, bt=39.1, spo2=89, rr=28, pr=118)),
        ("Pneumonia in a smoker", dict(exposure=["smoking_current"], pack_years=25)),
        ("Diabetic (Klebsiella-like)", dict(glu=260, wbc=18, bt=39.0)),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("Minimal data", dict(only=["fever", "cough", "sputum", "bt", "wbc"], bt=38.6, wbc=14)),
    ],
    "pleurisy": [
        ("Typical acute pleurisy with effusion", {}),
        ("Dry viral pleurisy", dict(fever="no", bt=37.3, auscultation=["friction_rub"], wbc=7.8, esr=22, lym=30)),
        ("Tuberculous pleurisy (subacute)", dict(duration="subacute", bt=37.8, esr=78, mon=10, lym=32)),
        ("Large effusion", dict(spo2=91, rr=26, auscultation=["diminished"], fvc=2.2, fev1=1.9, pfev1=62)),
        ("Bacterial pleurisy / empyema", dict(bt=39.2, wbc=19, stab=14, pr=116, esr=90)),
        ("Asbestos-related effusion", dict(exposure=["occupational"], duration="subacute", fever="no", bt=36.8)),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("No spirometry", {**{k: NO for k in SPIRO}}),
        ("Pleurisy with productive cough", dict(sputum="yes", auscultation=["friction_rub", "bronchial"])),
        ("Minimal data", dict(only=["chest_pain", "auscultation", "dyspnea"], auscultation=["friction_rub"])),
    ],
    "chronic_bronchitis": [
        ("Typical simple chronic bronchitis", {}),
        ("No wheeze", dict(wheezing="no")),
        ("Industrial bronchitis (dust, non-smoker)", dict(exposure=["occupational"], pack_years=0)),
        ("Former smoker", dict(exposure=["smoking_former"], pack_years=20)),
        ("Mild infective exacerbation", dict(bt=37.9, wbc=10.8, lym=20)),
        ("No spirometry", {**{k: NO for k in SPIRO}}),
        ("Passive smoke + biomass", dict(exposure=["passive", "biomass"], pack_years=0)),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("Heavy smoker, borderline spirometry", dict(pack_years=40, fev1=2.4, fvc=3.3, pfev1=76)),
        ("Minimal data", dict(only=["cough", "sputum", "duration", "exposure"])),
    ],
    "lung_abscess": [
        ("Typical lung abscess (aspiration)", {}),
        ("Alcohol-related aspiration", dict(gcs=14, ast=96, alt=48, tp=5.6)),
        ("Diabetic patient", dict(glu=285)),
        ("Septic presentation", dict(BP="88/56", pr=124, rr=28, spo2=91, bt=39.8, wbc=24)),
        ("Chronic indolent abscess", dict(duration="chronic", bt=37.8, wbc=13.2, esr=102, ztt=22, tp=5.8, mon=9)),
        ("Extension to the pleura", dict(auscultation=["diminished", "coarse_crackles"], dyspnea="yes")),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("No relevant exposure recorded", dict(exposure=["none"])),
        ("Milder course", dict(bt=38.0, wbc=12.5, esr=55, pr=92)),
        ("Minimal data", dict(only=["fever", "sputum", "cough", "bt", "wbc", "duration"], bt=39.0, wbc=17)),
    ],
    "bronchiectasis": [
        ("Typical stable bronchiectasis", {}),
        ("Infective exacerbation", dict(fever="yes", bt=38.4, wbc=13.6, stab=8, lym=12, duration="episodic")),
        ("ABPA-related (eosinophilia)", dict(eos=12)),
        ("Mild disease", dict(dyspnea="no", pfev1=84, fev1=2.8, fvc=3.5, esr=25, ztt=13, spo2=97)),
        ("Severe disease", dict(spo2=89, rr=26, pfev1=38, fev1=1.0, fvc=2.2)),
        ("Post-infectious, no wheeze", dict(wheezing="no")),
        ("No spirometry", {**{k: NO for k in SPIRO}}),
        ("No lab data", {**{k: NO for k in LABS}}),
        ("Chronic Pseudomonas colonisation", dict(esr=70, ztt=24, tp=8.4)),
        ("Minimal data", dict(only=["cough", "sputum", "auscultation", "duration"], auscultation=["coarse_crackles"])),
    ],
}

NAMES = {"asthma": "Asthma", "copd": "COPD", "pneumonia": "Pneumonia", "pleurisy": "Pleurisy",
         "chronic_bronchitis": "Chronic Bronchitis", "lung_abscess": "Lung Abscess", "bronchiectasis": "Bronchiectasis"}


def build(disease: str, title: str, ov: dict) -> dict:
    case = dict(BASE[disease])
    only = ov.pop("only", None)
    for k, v in ov.items():
        if v == NO:
            case.pop(k, None)
        else:
            case[k] = v
    if only:
        case = {k: case[k] for k in only if k in case}
    if all(k in case for k in DIFF):                      # keep the WBC differential at 100 % (adjust SEG)
        case["seg"] = round(100 - sum(case[k] for k in DIFF if k != "seg"), 1)
    if "exposure" in case and not case["exposure"]:
        del case["exposure"]
    return case


def main():
    import clinical_engine as ce
    from app import _map_lab_names
    model = ce.ClinicalModel(ROOT / "models" / "weight.json")
    OUT.mkdir(parents=True, exist_ok=True)
    rows, top1, top3 = [], 0, 0
    for disease, variants in V.items():
        assert len(variants) == 10, disease
        for i, (title, ov) in enumerate(variants, 1):
            case = build(disease, title, dict(ov))
            fname = f"{disease}_{i:02d}.json"
            doc = {"_case": f"{NAMES[disease]} {i:02d}: {title}", "_expected": NAMES[disease],
                   "_note": "Example data for testing only (fictional patient). Load it on step 2 with Import Lab File.",
                   **case}
            (OUT / fname).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            inputs, unknown = _map_lab_names(doc, model)       # exactly what Import Lab File does
            assert not unknown, (fname, unknown)
            for k, v in case.items():                          # every field must arrive under its own id
                if k == "BP":
                    assert inputs.get("sbp") and inputs.get("dbp"), (fname, k)
                else:
                    assert k in inputs, (fname, k, "was mapped to another field")
            r = model.score(inputs, None)
            ranked = [d["name"] for d in r["diseases"]]
            rank = ranked.index(NAMES[disease]) + 1
            top1 += rank == 1
            top3 += rank <= 3
            d0 = r["diseases"][0]
            rows.append([fname, NAMES[disease], title, len(case), rank, d0["name"], f"{d0['match']:.0%}",
                         ranked[1], d0["severity"]["grade"]])
    with open(OUT / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "expected", "case", "fields", "rank_of_expected", "top_disease", "top_match", "second",
                    "severity_of_top"])
        w.writerows(rows)
    for r in rows:
        print(f"{r[0]:<26} rank {r[4]}  top: {r[5]:<19}{r[6]:>4}  {r[2]}")
    n = len(rows)
    print(f"\n{n} cases · expected disease ranked 1st: {top1}/{n} · in top 3: {top3}/{n}  (clinical data only, no X-ray)")


if __name__ == "__main__":
    main()
