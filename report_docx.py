"""Final report as a Word document (.docx), built from the same report data as the preview / PDF."""
from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BLUE = RGBColor(0x2F, 0x6F, 0xED)
GREY = RGBColor(0x6B, 0x74, 0x89)
LEVEL_RGB = {"HIGH": "C62F2A", "MODERATE": "A8650F", "LOW": "1C7C53"}
SEV_RGB = {"Severe": "C62F2A", "Moderate": "A8650F", "Mild": "1C7C53", "Not assessable": "6B7489"}


def _shade(cell, hex_fill: str):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc.append(shd)


def _run(par, text, bold=False, size=None, color=None, italic=False):
    r = par.add_run(text)
    r.bold, r.italic = bold, italic
    if size:
        r.font.size = Pt(size)
    if color is not None:
        r.font.color.rgb = color if isinstance(color, RGBColor) else RGBColor.from_string(color)
    return r


def _section(doc, title):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    _run(p, title.upper(), bold=True, size=10.5, color=BLUE)
    return p


def _table(doc, header, rows, widths=None, shade_header=True):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        _run(c.paragraphs[0], h, bold=True, size=8.5, color=GREY)
        if shade_header:
            _shade(c, "F3F5F9")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            if isinstance(v, tuple):                         # (text, bold, color)
                _run(cells[i].paragraphs[0], v[0], bold=v[1], size=9, color=v[2])
            else:
                _run(cells[i].paragraphs[0], str(v), size=9)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    return t


def build_docx(rep: dict, patient: dict, review: dict, image_jpeg: bytes | None, logo_png: Path | None,
               target: Path, disclaimer: str):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(1.6)
    st = doc.styles["Normal"]
    st.font.name = "Segoe UI"
    st.font.size = Pt(9.5)

    # header
    head = doc.add_table(rows=1, cols=3)
    if logo_png and logo_png.exists():
        head.rows[0].cells[0].paragraphs[0].add_run().add_picture(str(logo_png), width=Cm(1.2))
    c = head.rows[0].cells[1].paragraphs[0]
    _run(c, "Chest X-Ray & Clinical AI Report\n", bold=True, size=15)
    _run(c, "PneumoLens AI · AI-assisted decision support for 7 lung diseases", size=8.5, color=GREY)
    r = head.rows[0].cells[2].paragraphs[0]
    r.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(r, rep["id"] + "\n", bold=True, size=10)
    _run(r, "Generated " + rep["generated"].replace("T", " ")[:16], size=8.5, color=GREY)
    head.rows[0].cells[0].width, head.rows[0].cells[1].width, head.rows[0].cells[2].width = Cm(1.6), Cm(10.4), Cm(5.4)

    # patient
    _section(doc, "Patient")
    age_sex = " / ".join(x for x in [f"{patient.get('age')} y" if patient.get("age") not in (None, "") else "",
                                      patient.get("sex", "")] if x) or "—"
    pairs = [("Patient ID", patient.get("patient_id")), ("Name", patient.get("name")), ("Age / sex", age_sex),
             ("Date of birth", patient.get("dob")), ("Location", patient.get("location")), ("Phone", patient.get("phone")),
             ("Hospital", patient.get("hospital")), ("Department / ward", patient.get("department")),
             ("Referring physician", patient.get("referring")), ("Visit", patient.get("visit")),
             ("Exam date", patient.get("exam_date")), ("Height / weight",
              " / ".join(x for x in [f"{patient['height']} cm" if patient.get("height") else "",
                                     f"{patient['weight']} kg" if patient.get("weight") else ""] if x) or None)]
    t = doc.add_table(rows=0, cols=4)
    t.style = "Table Grid"
    for i in range(0, len(pairs), 2):
        cells = t.add_row().cells
        for j, (k, v) in enumerate(pairs[i:i + 2]):
            cells[j * 2].text = ""
            _run(cells[j * 2].paragraphs[0], k, size=8.5, color=GREY)
            _shade(cells[j * 2], "F3F5F9")
            cells[j * 2 + 1].text = ""
            _run(cells[j * 2 + 1].paragraphs[0], str(v) if v not in (None, "") else "—", bold=True, size=9)
    for line, key in (("Chief complaint", "complaint"), ("Medical history", "history"), ("Allergies", "allergies")):
        if patient.get(key):
            p = doc.add_paragraph()
            _run(p, f"{line}: ", bold=True)
            _run(p, patient[key])

    # assessment
    cand_ids = rep["candidates"]["ids"]
    cands = [d for d in rep["diseases"] if d["id"] in cand_ids]
    _section(doc, "Integrated assessment" + (f" — {len(cands)} candidate diagnoses" if len(cands) > 1 else ""))
    for i, d in enumerate(cands, 1):
        p = doc.add_paragraph()
        if len(cands) > 1:
            _run(p, f"Candidate {i}  ", bold=True, size=8.5, color=BLUE)
        _run(p, f"{d['name']} — {round(d['match'] * 100)}%", bold=True, size=12.5)
        _run(p, f"   {d['level']} MATCH", bold=True, size=8.5, color=LEVEL_RGB[d["level"]])
        _run(p, f"   SEVERITY: {d['severity']['grade'].upper()}", bold=True, size=8.5, color=SEV_RGB[d["severity"]["grade"]])
        parts = d["parts"]
        part = lambda x, none: none if not x["used"] else "neutral" if x.get("neutral") else f"{round(x['match'] * 100)}%"
        p2 = doc.add_paragraph()
        _run(p2, f"Step 1 · X-ray: {part(parts['xray'], 'not analyzed')}   ·   Step 2 · Symptoms & labs: "
                 f"{part(parts['clinical'], 'no data')}   ·   Data coverage: {round(d['coverage'] * 100)}%", size=8.5, color=GREY)
        for side, mark, col in (("for", "✓ ", "1C7C53"), ("against", "✗ ", "C62F2A")):
            items = d["reasons"]["xray"][side] + d["reasons"]["clinical"][side]
            if items:
                q = doc.add_paragraph()
                _run(q, ("Supports: " if side == "for" else "Against: "), bold=True, size=9)
                for f in items:
                    _run(q, mark, bold=True, size=9, color=col)
                    _run(q, f"{f['label'].replace('X-ray: ', 'X-ray ')} {f['value']} [{f['group']}]   ", size=9)
        s = d["severity"]
        abn = [x for x in s["signs"] if x["level"] != "none"]
        q = doc.add_paragraph()
        _run(q, f"Severity {s['grade']}: ", bold=True, size=9, color=SEV_RGB[s["grade"]])
        _run(q, (", ".join(f"{x['label']} {x['value']} ({x['level']})" for x in abn) or
                 ("no sign crosses a moderate threshold" if s["grade"] == "Mild" else "too few severity signs entered"))
             + f" — criteria: {s['source']}", size=8.5)
    p = doc.add_paragraph()
    others = [d for d in rep["diseases"] if d["id"] not in cand_ids]
    _run(p, f"Candidates: diseases scoring ≥ {round(rep['candidates']['ratio'] * 100)}% of the first (max "
            f"{rep['candidates']['max']}). Not listed: " + ", ".join(f"{d['name']} {round(d['match'] * 100)}%" for d in others),
         size=8, color=GREY)
    if rep["alerts"]:
        p = doc.add_paragraph()
        _run(p, "Alerts: ", bold=True, color="C62F2A")
        _run(p, " · ".join(rep["alerts"]), color="C62F2A")

    # imaging
    _section(doc, "1 · Imaging findings (lung-related X-ray outputs)")
    if rep["xray"]:
        if image_jpeg:
            doc.add_picture(io.BytesIO(image_jpeg), width=Cm(6.0))
        lung = rep["xray"]["lung"]
        shown = [x for i, x in enumerate(lung) if i < 5 or x["score"] >= 0.3]
        _table(doc, ["Finding", "Score", "Flag"],
               [[x["label"], f"{x['score'] * 100:.1f}%", (x["level"], True, LEVEL_RGB[x["level"]])] for x in shown],
               widths=[8, 3, 3])
        p = doc.add_paragraph()
        _run(p, f"{len(lung) - len(shown)} other lung findings below 30 %. HIGH ≥ 50 % (model operating point).",
             size=8, color=GREY)
    else:
        doc.add_paragraph("No X-ray was analyzed for this report.")

    # clinical
    _section(doc, "2 · Symptoms, vital signs & laboratory data")
    c = rep["clinical"]
    if c:
        for label, items in (("Symptoms present", c["present"]), ("Absent", c["absent"]), ("Auscultation", c["sounds"])):
            if items:
                p = doc.add_paragraph()
                _run(p, f"{label}: ", bold=True)
                _run(p, ", ".join(items))
        if c["rows"]:
            rows, last = [], None
            titles = c.get("titles", {})
            for x in c["rows"]:
                key = x.get("subgroup") or x["category"]
                if key != last:
                    rows.append([(titles.get(key, key).upper(), True, BLUE), "", "", ""])
                    last = key
                flag = x["flag"]
                rows.append([x["label"], x["value"], x["ref"],
                             (flag, True, "1C7C53" if flag == "NORMAL" else "C62F2A") if flag else ""])
            _table(doc, ["Item", "Value", "Reference", "Flag"], rows, widths=[6.5, 3.5, 4.5, 2.5])
    else:
        doc.add_paragraph("No clinical data was entered.")

    # differential
    _section(doc, "3 · Differential diagnosis (7 lung diseases)")
    part = lambda x: "—" if not x["used"] else "neutral" if x.get("neutral") else f"{round(x['match'] * 100)}%"
    _table(doc, ["Disease", "Combined", "Step 1 · X-ray", "Step 2 · Clinical", "Coverage", "Severity"],
           [[(d["name"], d["id"] in cand_ids, None), f"{round(d['match'] * 100)}%", part(d["parts"]["xray"]),
             part(d["parts"]["clinical"]), f"{round(d['coverage'] * 100)}%",
             (d["severity"]["grade"], False, SEV_RGB[d["severity"]["grade"]])] for d in rep["diseases"]],
           widths=[4.2, 2.3, 2.6, 2.8, 2.3, 3])

    # follow-up
    _section(doc, "4 · Recommended follow-up")
    for d in cands:
        p = doc.add_paragraph()
        _run(p, f"{d['name']}: ", bold=True)
        _run(p, d["follow_up"])

    # review
    _section(doc, "5 · Clinician review")
    doc.add_paragraph(review.get("notes") or "No notes.")
    _table(doc, ["Reviewed by", "Signed", "Agreement"],
           [[review.get("reviewer") or "", (review.get("signed_at") or "").replace("T", " ")[:16],
             "Agrees with the AI assessment" if review.get("agreed") else ""]], widths=[6, 5, 6])

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    _run(p, f"{disclaimer}  ·  {rep['app']} · {rep['weights']}", size=8, color=GREY, italic=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
