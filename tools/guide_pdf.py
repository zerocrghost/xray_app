"""Render docs/DEVELOPER_GUIDE.md to docs/PneumoLens_developer_guide.pdf.

Converts the Markdown subset used in the guide (headings, tables, lists, code blocks, quotes,
inline code/bold/italic/links) to HTML and prints it with headless Microsoft Edge.

    .venv\\Scripts\\python tools\\guide_pdf.py
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "DEVELOPER_GUIDE.md"
OUT = ROOT / "docs" / "PneumoLens_developer_guide.pdf"
EDGE = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]

CSS = """
@page{size:A4;margin:16mm 15mm 16mm 15mm}
body{font-family:'Segoe UI',system-ui,sans-serif;font-size:10pt;line-height:1.45;color:#1d2433;margin:0}
h1{font-size:21pt;margin:0 0 4pt;color:#0b1220}
h1+p{color:#5d6880;margin-top:0}
h2{font-size:14pt;color:#2f6fed;border-bottom:1.5px solid #dbe3f3;padding-bottom:3pt;margin:20pt 0 8pt;break-after:avoid}
h3{font-size:11pt;margin:14pt 0 5pt;color:#0b1220;break-after:avoid}
h2+*,h3+*{break-before:avoid}
p{margin:5pt 0}
ul,ol{margin:4pt 0;padding-left:18pt} li{margin:2pt 0}
code{font-family:Consolas,'Cascadia Mono',monospace;font-size:8.6pt;background:#eef2f9;border-radius:3px;padding:0 3px;color:#16337a}
pre{background:#f5f7fb;border:1px solid #dde3ee;border-radius:6px;padding:8pt 10pt;font-size:8.2pt;line-height:1.3;
    white-space:pre;overflow:hidden;break-inside:avoid}
pre code{background:none;padding:0;color:#1d2433;font-size:inherit}
table{border-collapse:collapse;width:100%;margin:6pt 0;font-size:8.8pt}
th{background:#2f6fed;color:#fff;text-align:left;font-weight:600}
th code{background:rgba(255,255,255,.18);color:#fff}
th,td{padding:4pt 6pt;border:1px solid #dde3ee;vertical-align:top}
tr:nth-child(even) td{background:#f7f9fc} tr{break-inside:avoid}
blockquote{margin:6pt 0;padding:5pt 10pt;border-left:3px solid #f0a83a;background:#fff8ec}
hr{border:0;border-top:1px solid #dde3ee;margin:10pt 0}
a{color:#2563eb;text-decoration:none}
"""


def inline(t: str) -> str:
    codes: list[str] = []

    def keep(m):                                   # code spans first, so ** and * inside them stay literal
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    p = html.escape(re.sub(r"`([^`]+)`", keep, t), quote=False)
    p = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', p)
    p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
    p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", p)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], p)


def convert(md: str) -> str:
    lines = md.splitlines()
    out, i, para = [], 0, []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        if not s:
            flush(); i += 1; continue
        if re.fullmatch(r"-{3,}", s):
            flush(); out.append("<hr>"); i += 1; continue
        m = re.match(r"(#{1,4})\s+(.*)", s)
        if m:
            flush(); n = len(m.group(1)); out.append(f"<h{n}>{inline(m.group(2))}</h{n}>"); i += 1; continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>" +
                       "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) +
                       "</tbody></table>")
            continue
        if s.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip()[1:].strip()); i += 1
            out.append(f"<blockquote>{inline(' '.join(q))}</blockquote>")
            continue
        if re.match(r"([*-]|\d+\.)\s", s):
            flush()
            ordered = bool(re.match(r"\d+\.", s))
            items: list[list[str]] = []
            while i < len(lines):
                cur = lines[i]
                if re.match(r"\s{0,3}([*-]|\d+\.)\s", cur):
                    items.append([re.sub(r"^\s*([*-]|\d+\.)\s+", "", cur)])
                elif cur.startswith("  ") and cur.strip() and items:
                    items[-1].append(cur)            # continuation or nested item
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(' '.join(t.strip() for t in it))}</li>" for it in items) + f"</{tag}>")
            continue
        para.append(s)
        i += 1
    flush()
    return "\n".join(out)


def main():
    edge = next((p for p in EDGE if p.exists()), None)
    if not edge:
        sys.exit("Microsoft Edge was not found.")
    body = convert(SRC.read_text(encoding="utf-8"))
    page = f"<!doctype html><html><head><meta charset='utf-8'><title>PneumoLens AI Developer Guide</title><style>{CSS}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "guide.html"
        src.write_text(page, encoding="utf-8")
        OUT.unlink(missing_ok=True)
        r = subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--user-data-dir={Path(tmp) / 'profile'}", f"--print-to-pdf={OUT}", src.as_uri()],
                           capture_output=True, text=True, timeout=120)
        end = time.time() + 60                     # Edge may hand the job to a child process and return early
        while time.time() < end and not (OUT.exists() and OUT.stat().st_size > 0):
            time.sleep(0.5)
        if not OUT.exists():
            sys.exit(f"Edge did not write the PDF.\n{r.stdout}\n{r.stderr}")
        time.sleep(1)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
