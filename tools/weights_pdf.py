"""
Builds docs/PneumoLens_weight_theory.pdf - the theory behind models/weight.json - directly from the JSON,
so the document always matches the weights the app uses. Re-run it after editing weight.json.

    .venv\\Scripts\\python -m pip install reportlab      (documentation only, not needed by the app)
    .venv\\Scripts\\python tools\\weights_pdf.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import clinical_engine as ce  # noqa: E402

WEIGHTS = ROOT / "models" / "weight.json"
OUT = ROOT / "docs" / "PneumoLens_weight_theory.pdf"

# ---------------------------------------------------------------- fonts (Segoe UI has ↑ ≥ Σ ₂ etc.)
FONTS = Path(r"C:\Windows\Fonts")
pdfmetrics.registerFont(TTFont("UI", str(FONTS / "segoeui.ttf")))
pdfmetrics.registerFont(TTFont("UI-B", str(FONTS / "segoeuib.ttf")))
pdfmetrics.registerFont(TTFont("UI-I", str(FONTS / "segoeuii.ttf")))
pdfmetrics.registerFont(TTFont("UI-BI", str(FONTS / "segoeuiz.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONTS / "consola.ttf")))
pdfmetrics.registerFontFamily("UI", normal="UI", bold="UI-B", italic="UI-I", boldItalic="UI-BI")

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#5d6880")
LINE = colors.HexColor("#dde3ee")
SOFT = colors.HexColor("#f3f6fb")
ACCENT = colors.HexColor("#2563eb")
GROUP_BG = {"A": colors.HexColor("#fde8e8"), "B": colors.HexColor("#fdf1dc"),
            "C": colors.HexColor("#e6eefe"), "D": colors.HexColor("#eef0f4")}
GROUP_FG = {"A": colors.HexColor("#b42318"), "B": colors.HexColor("#93540a"),
            "C": colors.HexColor("#1d4ed8"), "D": colors.HexColor("#5d6880")}

S = {
    "title": ParagraphStyle("title", fontName="UI-B", fontSize=24, leading=30, textColor=INK, spaceAfter=6),
    "subtitle": ParagraphStyle("subtitle", fontName="UI", fontSize=12.5, leading=17, textColor=MUTED, spaceAfter=18),
    "h1": ParagraphStyle("h1", fontName="UI-B", fontSize=16, leading=21, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="UI-B", fontSize=12, leading=16, textColor=INK, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="UI", fontSize=9.5, leading=13.6, textColor=INK, spaceAfter=6, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="UI", fontSize=8.3, leading=11.2, textColor=MUTED, spaceAfter=4),
    "bullet": ParagraphStyle("bullet", fontName="UI", fontSize=9.5, leading=13.6, textColor=INK, leftIndent=12,
                             bulletIndent=2, spaceAfter=3),
    "formula": ParagraphStyle("formula", fontName="Mono", fontSize=9.5, leading=14, textColor=INK, backColor=SOFT,
                              borderColor=LINE, borderWidth=0.6, borderPadding=7, leftIndent=7, rightIndent=7,
                              spaceBefore=4, spaceAfter=12),
    "cell": ParagraphStyle("cell", fontName="UI", fontSize=8, leading=10.4, textColor=INK),
    "cellm": ParagraphStyle("cellm", fontName="UI", fontSize=8, leading=10.4, textColor=MUTED),
    "cellb": ParagraphStyle("cellb", fontName="UI-B", fontSize=8, leading=10.4, textColor=INK),
    "head": ParagraphStyle("head", fontName="UI-B", fontSize=7.6, leading=10, textColor=MUTED),
    "note": ParagraphStyle("note", fontName="UI", fontSize=9, leading=13, textColor=INK, backColor=colors.HexColor("#fff7e8"),
                           borderColor=colors.HexColor("#f0c27a"), borderWidth=0.6, borderPadding=7, leftIndent=7,
                           rightIndent=7, spaceBefore=6, spaceAfter=12),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def esc(t) -> str:
    return escape(str(t))


def bullets(items, style="bullet"):
    return [Paragraph(t, S[style], bulletText="•") for t in items]


def table(rows, widths, header=True, zebra=True, extra=()):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE)]
    if zebra:
        for r in range(2 if header else 1, len(rows), 2):
            st.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fafbfd")))
    t.setStyle(TableStyle(st + list(extra)))
    return t


def pattern_text(p: dict, f: dict) -> str:
    t = p["type"]
    if t == "present":
        return "Present"
    if t == "absent":
        return "Absent"
    if t == "any":
        return " or ".join(pattern_text(q, f) for q in p["of"])
    who = p["field"].upper() + " " if "field" in p else ""
    unit = "" if f["input"] == "xray" or "–" in f.get("unit", "") else " " + f.get("unit", "")
    return f"{who}{'↑' if p['full'] > p['from'] else '↓'} {p['from']} → {p['full']}{unit}".rstrip()


def expected(f: dict, it: dict) -> str:
    if it["group"] == "D":
        return "—"
    if f["input"] == "sounds":
        return ", ".join(f["sounds"][k] + ("" if v >= 1 else f" ({v:.0%})")
                         for k, v in sorted(it["sounds"].items(), key=lambda kv: -kv[1]))
    key = it.get("expect") or ("present" if f["input"] == "bool" else f["default"])
    p = f["patterns"][key]
    txt = esc(pattern_text(p, f))
    tags = [key.replace("_", " ")] if key not in ("present",) and key != pattern_text(p, f).lower() else []
    if p.get("exclusion"):
        tags.append("<b>exclusion</b>")
    return txt + (f"<br/><font color='#5d6880' size='7'>{' · '.join(tags)}</font>" if tags else "")


def item_name(f: dict) -> str:
    if f["input"] == "xray":
        return "X-ray: " + esc(f["short"])
    return esc(f.get("short") or f["label"])


def group_badge(g):
    return f"<font name='UI-B' color='{GROUP_FG[g].hexval().replace('0x', '#')}'>{g}</font>"


# ---------------------------------------------------------------- page decoration
def on_page(c, doc):
    c.saveState()
    w, h = A4
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(18 * mm, h - 14 * mm, w - 18 * mm, h - 14 * mm)
    c.setFont("UI", 7.8)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, h - 11.5 * mm, "PneumoLens AI · Theory of the clinical weighting table (models/weight.json)")
    c.drawRightString(w - 18 * mm, h - 11.5 * mm, f"weight.json v{doc.version}")
    c.line(18 * mm, 13 * mm, w - 18 * mm, 13 * mm)
    c.drawString(18 * mm, 9 * mm, "Research use only · not validated for clinical diagnosis")
    c.drawRightString(w - 18 * mm, 9 * mm, f"Page {doc.page}")
    c.restoreState()


# ---------------------------------------------------------------- content
def build():
    T = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    model = ce.ClinicalModel(WEIGHTS)            # also validates the table
    F, D, M = T["features"], T["diseases"], T["method"]
    story = []

    # ---------- title + summary
    story += [Spacer(1, 18 * mm),
              P("Clinical weighting table", "title"),
              P(f"Theory, assumptions and sources behind <b>models/weight.json</b> (v{esc(T['version'])}, "
                f"updated {esc(T['updated'])}) — step 2 “Symptoms &amp; Labs” of PneumoLens AI", "subtitle")]
    n_in = sum(1 for f in F.values() if f["category"] != "xray")
    n_xr = len(F) - n_in
    story += [P("Summary", "h1"),
              P(f"Step 2 of PneumoLens AI scores <b>{len(D)} lung diseases</b> "
                f"({esc(', '.join(d['name'] for d in D.values()))}) from <b>{n_in} clinical inputs</b> "
                f"(symptoms, auscultation, vital signs, laboratory data, optional spirometry) and <b>{n_xr} X-ray findings</b> "
                "from the step-1 AI model. For every disease, every input is placed in one of four groups — "
                "<b>A</b> critical, <b>B</b> important, <b>C</b> slightly related, <b>D</b> not related — and gets a weight "
                "inside its group's range, the finding that supports the disease, and the reason for that choice."),
              P("The weights are <b>expert-style assumptions</b> derived from international guidelines and standard textbook "
                "descriptions of each disease (GINA, GOLD, ATS/IDSA, BTS, ERS, JRS, CURB-65, A-DROP, Light's criteria). They are "
                "<b>not fitted to patient data</b>. This document explains every assumption so that a clinician can review it, "
                "and it is generated from the JSON file itself, so it always shows the weights the app actually uses."),
              P(esc(T["disclaimer"]), "note")]

    contents = ["1. Inputs and reference ranges", "2. The four groups (A / B / C / D)", "3. How a finding becomes evidence",
                "4. The match score", "5. Design decisions and why they were made", "6. Spirometry: is it important?",
                "7. Severity alerts", "8. Disease tables (one per disease)", "9. Validation with textbook cases",
                "10. Limitations", "11. References"]
    story += [P("Contents", "h2")] + bullets(contents) + [PageBreak()]

    # ---------- 1 inputs
    story += [P("1. Inputs and reference ranges", "h1"),
              P("Every input is optional. An input that is left empty is <b>skipped</b> — it is never treated as normal. "
                "Units follow common hospital laboratory practice (WBC in ×10³/µL, glucose in mg/dL, total protein in g/dL, "
                "ZTT in Kunkel units). The reference ranges are used to flag values on screen; the scoring itself uses the "
                "evidence ramps of section 3.")]
    rows = [[P("Category", "head"), P("Input", "head"), P("Unit", "head"), P("Reference", "head"), P("Valid range", "head")]]
    for fid, f in F.items():
        if f["category"] == "xray":
            continue
        ref = f.get("ref_text") or (f"{f['ref'][0]}–{f['ref'][1]}" if isinstance(f.get("ref"), list) else "")
        if f["input"] == "bool":
            ref, unit, lim = "—", "yes / no", "—"
        elif f["input"] == "sounds":
            ref, unit, lim = "—", "multi-select", ", ".join(f["sounds"].values())
        else:
            unit = f.get("unit", "")
            l = f.get("limits")
            lim = " / ".join(f"{a}–{b}" for a, b in l.values()) if isinstance(l, dict) else (f"{l[0]}–{l[1]}" if l else "")
        name = esc(f.get("short") or f["label"])
        if f.get("short") and f["short"] != f["label"]:
            name += f" <font color='#5d6880'>({esc(f['label'])})</font>"
        cat = T["categories"][f["category"]]
        sub = next((g["title"] for g in T.get("lab_groups", []) if fid in g["items"]), None)
        if sub:
            cat += " · " + sub
        rows.append([P(esc(cat), "cellm"), P(name, "cell"), P(esc(unit), "cell"),
                     P(esc(ref), "cell"), P(esc(lim), "cellm")])
    story.append(table(rows, [27 * mm, 58 * mm, 22 * mm, 31 * mm, 36 * mm]))
    story += [Spacer(1, 6),
              P(f"<b>X-ray findings ({n_xr}).</b> The step-1 model (TorchXRayVision DenseNet-121) outputs a score from 0 to 1 per "
                "finding. The table uses " + esc(", ".join(f["short"] for f in F.values() if f["category"] == "xray")) +
                ". If no X-ray was analyzed, these items are skipped like any other empty input."),
              ]
    sel = T.get("xray_selection")
    if sel:
        story += [P("Which step-1 X-ray outputs are used", "h2"),
                  P(f"The X-ray model outputs 18 findings. The {len(sel['used'])} lung-related ones are weighted for every "
                    f"disease like any other input; the {len(sel['not_used'])} others describe the heart, mediastinum, "
                    "bones or abdomen and are not used for the 7 lung diseases.")]
        rows = [[P("X-ray output", "head"), P("Used", "head"), P("Why", "head")]]
        rows += [[P(esc(k.replace("_", " ")), "cell"), P("<b>yes</b>", "cell"), P(esc(v), "cell")] for k, v in sel["used"].items()]
        rows += [[P(esc(k), "cellm"), P("no", "cellm"), P(esc(v), "cellm")] for k, v in sel["not_used"].items()]
        story.append(table(rows, [40 * mm, 14 * mm, 120 * mm]))
        story.append(Spacer(1, 6))
    story += [
              P("<b>Auscultation</b> is one input with several possible sounds; the disease tables say how much each sound counts "
                "(e.g. wheezes 100 %, rhonchi 50 % for asthma), and the strongest sound that was heard is used."),
              PageBreak()]

    # ---------- 2 groups
    story += [P("2. The four groups (A / B / C / D)", "h1"),
              P("Each disease places every input in exactly one group. The group sets the allowed weight range and two factors "
                "that describe how the finding behaves as evidence:")]
    rows = [[P("Group", "head"), P("Meaning", "head"), P("Weight", "head"), P("Presence factor p", "head"),
             P("Absence factor a", "head")]]
    for g, v in M["groups"].items():
        rows.append([P(group_badge(g), "cell"), P(esc(v["meaning"]), "cell"), P(f"{v['range'][0]}–{v['range'][1]}", "cell"),
                     P(str(v.get("presence_factor", 1)), "cell"), P(str(v.get("absence_factor", 1)), "cell")])
    story.append(table(rows, [14 * mm, 88 * mm, 20 * mm, 26 * mm, 26 * mm],
                       extra=[("BACKGROUND", (0, i + 1), (0, i + 1), GROUP_BG[g]) for i, g in enumerate("ABCD")]))
    story += [Spacer(1, 6),
              P("<b>Weight</b> — how important the item is for this disease. Within a group, a slightly different weight expresses "
                "that one item is more established than another (e.g. for COPD, FEV1/FVC 3.5 is the defining criterion, "
                "emphysema on X-ray 2.5 supports it)."),
              P("<b>Presence factor p (specificity)</b> — how much a finding that <i>is</i> present speaks for the disease. "
                "A present A finding is characteristic of the disease and counts fully; a present C finding is shared by many "
                "diseases (fever, raised WBC, low SpO₂) and counts only half."),
              P("<b>Absence factor a (sensitivity)</b> — how much a finding that is <i>missing</i> speaks against the disease. "
                "A defining (A) feature that is absent argues strongly against it; an occasional (C) finding is often absent "
                "even when the disease is there, so its absence counts only a little."),
              P("<b>Exclusions.</b> " + esc(M["exclusion"])),
              CondPageBreak(70 * mm)]

    # ---------- 3 evidence
    story += [P("3. How a finding becomes evidence", "h1"),
              P(esc(M["evidence"])),
              P("Linear ramps avoid hard cut-offs: a temperature of 37.9 °C is partial evidence of fever, 38.5 °C is full "
                "evidence. The ramps start at the upper (or lower) limit of the reference range and reach full evidence at a "
                "value that is clearly abnormal, usually the threshold used by the cited guideline or severity score."),
              P("Patterns used in the table", "h2")]
    rows = [[P("Input", "head"), P("Pattern", "head"), P("Evidence ramp (0 → full)", "head"), P("Note", "head")]]
    for fid, f in F.items():
        if f["input"] in ("bool", "sounds"):
            continue
        if f["category"] == "xray" and fid != "xr_pneumonia":
            continue
        for key, p in f["patterns"].items():
            name = "Every X-ray finding" if f["category"] == "xray" else (f.get("short") or f["label"])
            note = "exclusion" if p.get("exclusion") else ("default" if key == f["default"] else "")
            rows.append([P(esc(name), "cell"), P(esc(key.replace("_", " ")), "cell"),
                         P(esc(pattern_text(p, f)), "cell"), P(note, "cellm")])
    rows.append([P("Symptoms", "cell"), P("present / absent", "cell"), P("yes = 1, no = 0 (absent: inverted)", "cell"),
                 P("absent = exclusion", "cellm")])
    story.append(table(rows, [34 * mm, 26 * mm, 74 * mm, 40 * mm]))
    story += [Spacer(1, 4),
              P("<b>X-ray scores.</b> The model is calibrated so that 0.5 is its decision threshold (operating point), and many "
                "labels sit near 0.5 on almost any image. Evidence therefore starts at 0.5 and is full at 0.75; a finding counts "
                "as absent below 0.45. Treating 0.5 as half evidence would turn background noise into findings.", "body"),
              CondPageBreak(70 * mm)]

    # ---------- 4 score
    story += [P("4. The match score", "h1"),
              P("For each disease, over the items that were entered (w = weight, s = evidence, p = presence factor, "
                "a = absence factor):"),
              P("match = ( Σ w·s·p + prior·K ) / ( Σ w·(s + (1 − s)·a) + K )", "formula"),
              P(esc(M["score"])),
              P(f"<b>Prior.</b> prior = {M['prior']}, K = {M['prior_strength_K']}. The prior keeps a disease near "
                f"{M['prior']:.0%} when little data is entered, so that one matching symptom cannot produce a 100 % match. "
                "With full data its influence is small."),
              P("<b>Coverage.</b> " + esc(M["coverage"].replace("'low_coverage'", f"{M['low_coverage']:.0%}")) +
                " Coverage tells the user how much of the evidence the disease's table asks for was actually available."),
              P("<b>Step 1 and step 2 parts.</b> " + esc(M.get("parts", "")) +
                " The final report (step 3) lists, for the most likely disease, the findings from each step that raise "
                "the match (✓) and the missing A/B findings or violated exclusions that lower it (✗)."),
              P("<b>Factors shown in the app.</b> For the selected disease each entered item is listed with its signed share of the "
                "match: (w·s·p − match·w·(s + (1 − s)·a)) / (Σ w·(s + (1 − s)·a) + K). Positive values raise the match, negative "
                "values lower it. The app also lists important (A/B) items that were not entered."),
              P("Notes", "h2")] + bullets([esc(n) for n in M["notes"]]) + [
              P("Worked example", "h2"),
              P("A patient with fever (yes) and a WBC of 12 ×10³/µL, nothing else entered. For pneumonia, fever is A 3.0 "
                "(s = 1, p = 1) and WBC is A 2.5 (s = (12 − 9)/(15 − 9) = 0.5). Numerator: 3.0·1·1 + 2.5·0.5·1 + 0.2·4 = 5.05. "
                "Denominator: 3.0·1 + 2.5·(0.5 + 0.5·1) + 4 = 9.5. Match = 53 %, coverage low (only two items), so the "
                "result is shown as low confidence."),
              CondPageBreak(70 * mm)]
    # verify the worked example against the engine so the document can't drift from the code
    ex = model.score({"fever": True, "wbc": 12}, None)
    pn = next(d for d in ex["diseases"] if d["id"] == "pneumonia")
    assert abs(pn["match"] - 5.05 / 9.5) < 1e-3, ("worked example out of date", pn["match"])

    # ---------- 5 design decisions
    story += [P("5. Design decisions and why they were made", "h1"),
              P("The scoring rules were checked against a textbook case of every disease and against the real step-1 output "
                "of the test images. Five problems appeared; each was fixed with a rule that follows from what the groups mean, "
                "not by tuning individual weights to the test cases.")]
    decisions = [
        ("Missing findings counted equally for every group",
         "Absence of an occasional (C) finding lowered a disease as much as absence of a defining (A) finding, so diseases "
         "with many C items (bronchiectasis) were marked down in stable patients without fever.",
         "Absence factor per group (A 1.0, B 0.6, C 0.3) — sensitivity."),
        ("Diagnoses of exclusion matched almost everything",
         "Simple chronic bronchitis is defined by cough and sputum “with other causes excluded”. Without exclusion items it "
         "matched every patient with a productive cough, including COPD and bronchiectasis.",
         "Exclusion patterns (normal FEV1/FVC and %FEV1, no emphysema, normal ESR/ZTT, no fever) that always count fully: "
         "persistent obstruction makes the patient COPD (GOLD; Fletcher &amp; Peto 1977)."),
        ("Present C findings counted as fully consistent",
         "A disease whose matching evidence was mostly C items (fever, WBC, SpO₂ for bronchiectasis) reached the same score as "
         "one whose evidence was A items, so a classic pneumonia picture ranked as bronchiectasis.",
         "Presence factor per group (A 1.0, B 0.8, C 0.5) — specificity."),
        ("Correlated X-ray labels were counted several times",
         "Pneumonia, Consolidation, Lung Opacity and Infiltration are four readings of one criterion (“new infiltrate”). "
         "With all four in group A, one label the model missed vetoed the diagnosis.",
         "Only the Pneumonia label is A (2.5); Consolidation B 2.0, Lung Opacity B 1.5, Infiltration C 1.2. X-ray evidence "
         "starts at the model's operating point 0.5."),
        ("Fulfilled exclusions diluted the match",
         "A normal value of an exclusion item (e.g. no edema on the X-ray for pneumonia) counted as a weak C finding for the "
         "disease and pulled a high match down, although a normal value is common to almost every disease.",
         "A fulfilled exclusion adds nothing; a violated one counts fully against the disease."),
    ]
    rows = [[P("Problem", "head"), P("What happened", "head"), P("Rule adopted", "head")]]
    rows += [[P(f"<b>{a}</b>", "cell"), P(b, "cell"), P(c, "cell")] for a, b, c in decisions]
    story.append(table(rows, [40 * mm, 72 * mm, 62 * mm]))
    story += [Spacer(1, 6),
              P("<b>Base rates are not modelled.</b> The match score says how well the patient fits each disease's typical "
                "picture; it does not include how common each disease is. Pneumonia is far more common than lung abscess, "
                "and the two share most findings — without imaging they score close together, which is clinically honest: "
                "chest imaging separates them (infiltrate vs. cavity)."),
              CondPageBreak(70 * mm)]

    # ---------- 6 spirometry
    sa = T["spirometry_assessment"]
    story += [P("6. Spirometry: is it important?", "h1"),
              P(f"<b>Verdict: {esc(sa['verdict'])}</b>")]
    rows = [[P("Value", "head"), P("Assessment", "head")]]
    for k in ("FEV1/FVC", "%FEV1", "FEV1", "FVC", "acute_diseases"):
        if k in sa:
            rows.append([P("<b>" + esc("Acute diseases" if k == "acute_diseases" else k) + "</b>", "cell"), P(esc(sa[k]), "cell")])
    story.append(table(rows, [32 * mm, 142 * mm]))
    rows = [[P("Disease", "head")] + [P(esc(F[k]["short"]), "head") for k in ("fev1_fvc", "pfev1", "fev1", "fvc")]]
    for d in D.values():
        r = [P(esc(d["name"]), "cell")]
        for k in ("fev1_fvc", "pfev1", "fev1", "fvc"):
            it = d["items"][k]
            exp = it.get("expect")
            r.append(P(f"{group_badge(it['group'])} {it['weight']:g}" + (f" <font color='#5d6880'>({esc(exp)})</font>" if exp else ""),
                       "cell"))
        rows.append(r)
    story += [Spacer(1, 8), P("Spirometry weights per disease", "h2"),
              table(rows, [42 * mm, 33 * mm, 33 * mm, 33 * mm, 33 * mm]),
              Spacer(1, 6),
              P("Spirometry is the test that separates the obstructive diseases (asthma, COPD, chronic bronchitis with obstruction, "
                "bronchiectasis) from the acute infections and from pleural disease. It is optional in the app because it is "
                "often not available in acute care, and an empty value is simply skipped. FEV1/FVC is calculated from FEV1 and "
                "FVC when both are entered. Reversibility after a bronchodilator (≥ 12 % and ≥ 200 mL), which distinguishes "
                "asthma from COPD, is not an input yet and is listed as a follow-up test instead."),
              CondPageBreak(70 * mm)]

    # ---------- 7 alerts
    story += [P("7. Severity alerts", "h1"),
              P("Independently of the match score, the app shows an alert when a vital sign crosses a severity threshold. "
                "Most thresholds come from CURB-65 (confusion, respiratory rate ≥ 30, systolic BP &lt; 90 or diastolic ≤ 60) "
                "and A-DROP (SpO₂ ≤ 90 %). Age and urea/BUN are not inputs, so CURB-65 and A-DROP cannot be scored completely; "
                "the follow-up text for pneumonia asks for them. The disease-specific severity grade is described in the next "
                "section.")]
    rows = [[P("Input", "head"), P("Condition", "head"), P("Alert text", "head")]]
    ops = {"below": "<", "at_most": "≤", "at_least": "≥", "above": ">"}
    for a in T["alerts"]:
        op = next(k for k in ops if k in a)
        rows.append([P(esc(a["field"].upper()), "cell"), P(f"{ops[op]} {a[op]}", "cell"), P(esc(a["text"]), "cell")])
    story += [table(rows, [24 * mm, 26 * mm, 124 * mm]), Spacer(1, 8)]

    # ---------- 7b severity
    sv = M.get("severity")
    if sv:
        ops = {"below": "<", "at_most": "≤", "at_least": "≥", "above": ">"}

        def cond_text(conds, field):
            out = []
            for c in conds:
                op = next(k for k in ops if k in c)
                fld = c.get("field", field)
                name = fld.split(":", 1)[1] + " score" if fld.startswith("xray:") else fld.upper()
                out.append(f"{name} {ops[op]} {c[op]}")
            return " or ".join(out) or "—"

        story += [CondPageBreak(80 * mm), P("Severity grading (final report)", "h1"),
                  P(esc(sv["meaning"]) + " " + esc(sv["note"]))]
        rows = [[P("Grade", "head"), P("Rule", "head")]]
        rows += [[P(f"<b>{esc(g['grade'])}</b>", "cell"), P(esc(g["rule"]), "cell")] for g in sv["grades"]]
        story += [table(rows, [36 * mm, 138 * mm]), Spacer(1, 4),
                  P(f"A moderate sign counts {sv['points']['moderate']} point, a severe sign {sv['points']['severe']} points.", "small")]
        for dk, d in D.items():
            spec = d.get("severity")
            if not spec:
                continue
            rows = [[P("Sign", "head"), P("Moderate", "head"), P("Severe", "head"), P("Why", "head")]]
            for sg in spec["signs"]:
                rows.append([P(esc(sg["label"]), "cellb"), P(esc(cond_text(sg["moderate"], sg["field"])), "cell"),
                             P(esc(cond_text(sg["severe"], sg["field"])), "cell"), P(esc(sg["why"]), "cell")])
            story += [CondPageBreak(40 * mm), P(f"{esc(d['name'])} <font color='#5d6880' size='9'>· {esc(spec['source'])}</font>", "h2"),
                      table(rows, [34 * mm, 30 * mm, 38 * mm, 72 * mm])]
        story.append(P("<b>Final report candidates.</b> The report always shows the first disease. Others are listed next to "
                       "it when their match is at least a set share of the first one (application setting, default 50 %, "
                       "at most 3 diseases). With a large gap only the first disease is shown, as clearly most likely.", "body"))
        story.append(PageBreak())

    # ---------- 8 diseases
    story += [P("8. Disease tables", "h1"),
              P("One table per disease. Items are grouped A → D and sorted by weight. “Expected finding” is the evidence ramp of "
                "section 3 (↑ a → b: evidence rises from 0 at a to full at b; ↓: falling). <b>exclusion</b> marks items that "
                "expect a normal value and always count fully. Group D items are listed with the reason they are ignored.")]
    for i, (dk, d) in enumerate(D.items()):
        if i:
            story.append(PageBreak())
        counts = {g: sum(1 for it in d["items"].values() if it["group"] == g) for g in "ABCD"}
        story += [P(f"8.{i + 1} {esc(d['name'])} <font color='#5d6880' size='10'>· ICD-10 {esc(d.get('icd10', ''))}</font>", "h1"),
                  P(esc(d["summary"])),
                  P("<b>Sources:</b> " + esc("; ".join(d["references"])), "small"),
                  P("<b>Suggested follow-up in the app:</b> " + esc(d["follow_up"]), "small"),
                  P(f"Groups: A {counts['A']} · B {counts['B']} · C {counts['C']} · D {counts['D']} items "
                    f"(total weight {sum(it['weight'] for it in d['items'].values()):.1f})", "small"),
                  Spacer(1, 4)]
        rows = [[P("Grp", "head"), P("Item", "head"), P("W", "head"), P("Expected finding", "head"),
                 P("Theory / assumption", "head")]]
        style = []
        for g in "ABC":
            for fid, it in sorted(((k, v) for k, v in d["items"].items() if v["group"] == g), key=lambda kv: -kv[1]["weight"]):
                f = F[fid]
                rows.append([P(group_badge(g), "cell"), P("<b>" + item_name(f) + "</b>", "cell"), P(f"{it['weight']:.1f}", "cell"),
                             P(expected(f, it), "cell"), P(esc(it["why"]), "cell")])
                style.append(("BACKGROUND", (0, len(rows) - 1), (0, len(rows) - 1), GROUP_BG[g]))
        story.append(table(rows, [10 * mm, 30 * mm, 10 * mm, 38 * mm, 86 * mm], zebra=False, extra=style))
        dl = sorted(((k, v) for k, v in d["items"].items() if v["group"] == "D"), key=lambda kv: list(F).index(kv[0]))
        if dl:
            story += [Spacer(1, 6), CondPageBreak(30 * mm),
                      P(f"Group D — not related ({len(dl)} items)", "h2")]
            # merge items that share the same reason
            by_reason = {}
            for fid, it in dl:
                by_reason.setdefault(it["why"], []).append(item_name(F[fid]))
            rows = [[P("Items", "head"), P("Why they are ignored", "head")]]
            for why, names in by_reason.items():
                rows.append([P(", ".join(names), "cellm"), P(esc(why), "cellm")])
            story.append(table(rows, [64 * mm, 110 * mm]))

    # ---------- 9 validation
    story += [PageBreak(), P("9. Validation with textbook cases", "h1"),
              P("<i>tests/test_clinical.py</i> enters a textbook presentation of each disease (all inputs filled, typical X-ray "
                "findings) and checks that the disease ranks first. The table below is computed live from the current "
                "weight.json when this document is generated.")]
    try:
        import test_clinical as tc
        rows = [[P("Textbook case", "head"), P("Rank 1", "head"), P("Rank 2", "head"), P("Rank 3", "head"), P("Result", "head")]]
        for key, (inp, xr) in tc.CASES.items():
            r = model.score(inp, {**tc.XR_BASE, **xr})
            top = r["diseases"]
            ok = top[0]["id"] == key
            rows.append([P(esc(D[key]["name"]), "cellb")] +
                        [P(f"{esc(x['name'])} {x['match']:.0%}", "cell") for x in top[:3]] +
                        [P("<font color='#13804f'><b>correct</b></font>" if ok else "<font color='#b42318'><b>wrong</b></font>",
                           "cell")])
        story.append(table(rows, [36 * mm, 38 * mm, 38 * mm, 38 * mm, 24 * mm]))
        ref = json.loads((ROOT / "tests" / "reference_scores.json").read_text(encoding="utf-8"))
        severe = dict(fever=True, dyspnea=True, cough=True, sputum=True, chest_pain=True, wheezing=False,
                      auscultation=["coarse_crackles", "bronchial"], sbp=104, dbp=62, pr=112, bt=38.9, rr=31, gcs=15,
                      spo2=89, wbc=16.4, esr=48, stab=14, seg=80, lym=9, alt=48, ast=52, glu=142)
        rows = [[P("X-ray used", "head"), P("Rank 1", "head"), P("Rank 2", "head"), P("Rank 3", "head")]]
        for img, xr in [("none", None)] + [(k, v) for k, v in ref.items() if not k.startswith("_")]:
            r = model.score(severe, xr)
            rows.append([P(esc(img), "cell")] + [P(f"{esc(x['name'])} {x['match']:.0%}", "cell") for x in r["diseases"][:3]])
        story += [Spacer(1, 8), P("Real X-ray output with a severe acute-infection picture", "h2"),
                  P("A febrile patient with productive cough, coarse crackles and bronchial breathing, RR 31, SpO₂ 89 %, "
                    "WBC 16.4 with a left shift — scored without an X-ray and with the real step-1 output of each test image. "
                    "The model rates the “Pneumonia” label low on these images, which pulls pneumonia down; the clinical "
                    "picture still keeps it first, but by a narrow margin. Without imaging, pneumonia and lung abscess "
                    "cannot be separated well (see section 5)."),
                  table(rows, [44 * mm, 43 * mm, 43 * mm, 44 * mm])]
    except Exception as e:                              # the document still builds without the tests folder
        story.append(P(f"(Validation table not available: {esc(e)})", "small"))
    story += [Spacer(1, 6),
              P("These checks show that the table behaves as the theory intends on typical presentations. They are not a clinical "
                "validation: the cases were written from the same textbook descriptions as the weights.", "note")]

    # ---------- 10 limitations
    story += [P("10. Limitations", "h1")] + bullets([
        "The weights are assumptions from guidelines and textbooks, not estimated from patient data. Sensitivity, specificity "
        "and prevalence of each finding in a real population should replace them once data are available (e.g. by logistic "
        "regression or a naive-Bayes model using likelihood ratios).",
        "Base rates (prevalence) are not included. Common diseases are not favoured over rare ones.",
        "History is entered in coarse classes: illness duration as acute / subacute / chronic / years / recurrent and exposure "
        "as categories plus pack-years. The chronic-bronchitis rule (≥ 3 months in 2 consecutive years), age, alcohol use and "
        "aspiration risk (important for lung abscess) are not separate inputs.",
        "Important tests are missing: CRP / procalcitonin, bronchodilator reversibility, FeNO, sputum culture, arterial "
        "blood gas, age and urea (needed for CURB-65 / A-DROP), chest CT.",
        "The X-ray model has no labels for cavities, bronchial wall thickening or hyperinflation; Mass / Lung Lesion and "
        "Emphysema are used as proxies.",
        "The seven match scores are independent; diseases can coexist (COPD with pneumonia, bronchiectasis with an "
        "infective exacerbation). They are not probabilities and do not add up to 100 %.",
        "Laboratory reference ranges differ between laboratories and populations; check them against the local laboratory.",
    ]) + [Spacer(1, 6)]

    # ---------- 11 references
    refs = []
    for d in D.values():
        for r in d["references"]:
            if r not in refs:
                refs.append(r)
    refs += ["Fletcher C, Peto R. The natural history of chronic airflow obstruction. BMJ 1977;1:1645-8",
             "Hill AT et al. Pulmonary exacerbation in adults with bronchiectasis: a consensus definition for clinical "
             "research. Eur Respir J 2017;49:1700051",
             "Cohen JP et al. TorchXRayVision: A library of chest X-ray datasets and models. MIDL 2022"]
    story += [CondPageBreak(50 * mm), P("11. References", "h1")] + bullets([esc(r) for r in refs])

    # ---------- build
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm,
                          bottomMargin=18 * mm, title="PneumoLens AI – Theory of the clinical weighting table",
                          author="PneumoLens AI", subject=f"models/weight.json v{T['version']}")
    doc.version = T["version"]
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=on_page)])
    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)  generated {dt.date.today()}")


if __name__ == "__main__":
    build()
