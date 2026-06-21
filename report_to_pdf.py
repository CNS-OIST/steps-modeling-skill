#!/usr/bin/env python3
"""Render a validation report (Markdown) to PDF — best artifact the environment allows.

You write ONE Markdown report; this picks the renderer by what's installed:

  1. a browser (Chrome/Chromium/Edge) + the `markdown` module  → styled HTML → PDF
     (best looking: colored tier badges, callout boxes, CSS tables)
  2. else fpdf2                                                 → pure-Python PDF
     (no browser; same colored badges/callouts approximated in fpdf2)
  3. else nothing installable                                  → the .md IS the report
     (Markdown reads fine as-is; render later when a tool is available)

Supported Markdown subset: `#`/`##`/`###`, paragraphs, `-`/`*` bullets, pipe tables,
`---`, `**bold**`/`_italic_`/`` `code` ``, Unicode (µ, M⁻¹s⁻¹, Ca²⁺, →, ✓, ×).
Two automatic touches need no special syntax: verdict words in table cells get colored
(HARD/ADVISORY/CONFIRMED→badges; exact/match/✓→green; low/tuned/cited→orange;
high/100×→red), and a paragraph beginning **HARD …**/**ADVISORY …**/**CONFIRMED …**
(plus its bullets) becomes a tinted callout box with a colored left bar.

    python report_to_pdf.py report.md [out.pdf]      # auto-cascade
    python report_to_pdf.py --selftest

Install the nicer paths with:  pip install fpdf2   (and have a browser for tier 1).
See SKILL.md → "Generate a report".
"""
import pathlib
import re
import subprocess
import sys
import tempfile

NAVY = (42, 77, 105)
GREY = (60, 60, 60)
RED, ORANGE, GREEN = (192, 40, 45), (176, 84, 10), (26, 127, 55)
HEAD_FILL = (238, 242, 246)
TINT = {"HARD": (252, 246, 246), "ADVISORY": (253, 249, 243),
        "SOFT": (253, 249, 243), "CONFIRMED": (244, 250, 245)}
ACCENT = {"HARD": RED, "ADVISORY": ORANGE, "SOFT": ORANGE, "CONFIRMED": GREEN}

_SANI = {"⁻": "-", "¹": "1", "²": "2", "³": "3", "⁺": "+", "₂": "2", "·": ".",
         "≈": "~", "×": "x", "→": "->", "✓": "[ok]", "µ": "u", "–": "-", "—": "-",
         "’": "'", "“": '"', "”": '"', "≥": ">=", "≤": "<="}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "chrome",
]


def _find_chrome():
    import shutil
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists() or shutil.which(c):
            return c
    return None


# ── tier 1: Markdown → styled HTML → PDF (browser) ───────────────────────────────
CSS = """
@page { size: A4; margin: 15mm 14mm; }
body { font: 10.5px/1.5 -apple-system,"Helvetica Neue",Arial,sans-serif; color:#1a1a1a; }
h1 { font-size:20px; color:#2a4d69; border-bottom:2px solid #2a4d69; padding-bottom:3px; margin:0 0 8px; }
h2 { font-size:13.5px; color:#2a4d69; border-bottom:1px solid #2a4d69; padding-bottom:2px; margin:18px 0 6px; }
h3 { font-size:11.5px; color:#333; margin:12px 0 4px; }
table { border-collapse:collapse; width:100%; margin:6px 0; font-size:9.6px; }
th,td { border:1px solid #ccc; padding:3px 5px; text-align:left; vertical-align:top; }
th { background:#eef2f6; font-weight:600; }
code { font-family:"SF Mono",Menlo,Consolas,monospace; font-size:9.2px; background:#f4f4f4; padding:0 2px; border-radius:2px; }
ul { margin:3px 0 6px 16px; padding:0; } li { margin:1px 0; }
.c-red{color:#c0282d;font-weight:600;} .c-green{color:#1a7f37;font-weight:600;} .c-orange{color:#b3540a;}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:8.5px;font-weight:700;color:#fff;}
.p-hard{background:#c0282d;} .p-soft{background:#b3540a;} .p-ok{background:#1a7f37;}
.box{border-left:4px solid #ccc;padding:6px 10px;margin:7px 0;border-radius:0 4px 4px 0;}
.box.hard{border-color:#c0282d;background:#fcf6f6;} .box.advisory,.box.soft{border-color:#b3540a;background:#fdf9f3;}
.box.confirmed{border-color:#1a7f37;background:#f4faf5;}
.box p{margin:0 0 3px;} .box ul{margin:2px 0 0 16px;}
"""


def _color_cells(html):
    def repl(m):
        inner = m.group(1)
        t = re.sub("<[^>]+>", "", inner).strip().lower()
        if len(t) <= 24:
            for k, p in (("hard", "p-hard"), ("advisory", "p-soft"),
                         ("confirmed", "p-ok"), ("soft", "p-soft")):
                if k in t:
                    return f'<td><span class="pill {p}">{inner}</span></td>'
            if "exact" in t or "match" in t or "✓" in t:
                return f'<td class="c-green">{inner}</td>'
            if "100×" in t or "100x" in t or t == "high":
                return f'<td class="c-red">{inner}</td>'
            if any(k in t for k in ("low", "tuned", "cited", "+5%", "×0.2", "x0.2", "2×", "code")):
                return f'<td class="c-orange">{inner}</td>'
        return m.group(0)
    return re.sub(r"<td>(.*?)</td>", repl, html, flags=re.S)


def _wrap_callouts(html):
    pat = re.compile(r"(<p><strong>(HARD|ADVISORY|SOFT|CONFIRMED)\b.*?</p>\s*(?:<ul>.*?</ul>)?)",
                     re.S | re.I)
    return pat.sub(lambda m: f'<div class="box {m.group(2).lower()}">{m.group(1)}</div>', html)


def _md_to_html(md):
    import markdown as md_lib
    body = md_lib.markdown(md, extensions=["tables", "sane_lists"])
    body = _wrap_callouts(_color_cells(body))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def _html_pdf(md, out):
    chrome = _find_chrome()
    if not chrome:
        return None
    try:
        html = _md_to_html(md)
    except ImportError:
        return None        # no `markdown` module → let tier 2 handle it
    with tempfile.TemporaryDirectory() as d:
        page = pathlib.Path(d) / "report.html"
        page.write_text(html)
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pathlib.Path(out).resolve()}", page.as_uri()],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "browser (HTML)" if pathlib.Path(out).exists() else None


# ── tier 2: Markdown → PDF (fpdf2, pure Python) ──────────────────────────────────
def _cells(row):
    return [c.strip().strip("`") for c in row.strip().strip("|").split("|")]


def _is_sep(cells):
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c != "")


def _dejavu():
    """(regular, bold, italic, bold-italic) TTF paths for a Unicode font, or None."""
    try:
        from matplotlib import font_manager as fm
        fp = fm.FontProperties
        return (fm.findfont(fp(family="DejaVu Sans")),
                fm.findfont(fp(family="DejaVu Sans", weight="bold")),
                fm.findfont(fp(family="DejaVu Sans", style="italic")),
                fm.findfont(fp(family="DejaVu Sans", weight="bold", style="italic")))
    except Exception:
        pass
    for base in ("/usr/share/fonts/truetype/dejavu", "/Library/Fonts",
                 "/System/Library/Fonts/Supplemental", "/usr/share/fonts/dejavu"):
        reg = pathlib.Path(base) / "DejaVuSans.ttf"
        if reg.exists():
            def pick(name):
                p = reg.with_name(name)
                return str(p if p.exists() else reg)
            return (str(reg), pick("DejaVuSans-Bold.ttf"),
                    pick("DejaVuSans-Oblique.ttf"), pick("DejaVuSans-BoldOblique.ttf"))
    return None


# single-`_x_`/`*x*` emphasis → fpdf2's `__x__`; leaves **bold** and word_internal_ alone
_EMPH = re.compile(r"(?<![\w*_`])([*_])(?!\1)(\S(?:.*?\S)?)\1(?![\w*_`])")


def _md_inline(s):
    return _EMPH.sub(r"__\2__", s.replace("`", ""))


def _cell_style(text):
    from fpdf.fonts import FontFace
    t = text.strip().lower()
    if len(t) > 24:
        return None
    for key, col in (("hard", RED), ("advisory", ORANGE), ("confirmed", GREEN), ("soft", ORANGE)):
        if key in t:
            return FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=col)
    if "exact" in t or "match" in t or "✓" in t:
        return FontFace(color=GREEN, emphasis="BOLD")
    if "100×" in t or "100x" in t or t == "high":
        return FontFace(color=RED, emphasis="BOLD")
    if any(k in t for k in ("low", "tuned", "cited", "+5%", "×0.2", "x0.2", "≈2×", "2×", "code")):
        return FontFace(color=ORANGE)
    return None


def render_markdown(md, out):
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    class _Report(FPDF):
        bfam = "Helvetica"

        def footer(self):
            self.set_y(-11)
            self.set_font(self.bfam, "", 7.5)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, str(self.page_no()), align="C")
            self.set_text_color(0, 0, 0)

    pdf = _Report(format="A4")
    pdf.set_margins(14, 13, 14)
    pdf.set_auto_page_break(True, margin=14)
    files = _dejavu()
    if files:
        for style, f in zip(("", "B", "I", "BI"), files):
            pdf.add_font("Body", style, f)
        fam, uni = "Body", True
    else:
        fam, uni = "Helvetica", False
    pdf.bfam = fam
    pdf.add_page()

    def txt(s):
        s = _md_inline(s)
        return s if uni else "".join(_SANI.get(c, c if ord(c) < 256 else "?") for c in s)

    def para(text, w, lh, size, x=None, style=""):
        pdf.set_font(fam, style, size)
        if x is not None:
            pdf.set_x(x)
        pdf.multi_cell(w, lh, txt(text), markdown=True)

    def height(text, w, lh, size):
        pdf.set_font(fam, size=size)
        return pdf.multi_cell(w, lh, txt(text), markdown=True, dry_run=True, output="HEIGHT")

    def callout(kind, lead, bullets):
        x0, w = 14, pdf.w - 28
        bar, pad, tw = 1.8, 2.6, (pdf.w - 28) - 1.8 - 5.2
        tx = x0 + bar + 2.6
        total = pad + height(lead, tw, 4.7, 9.5) \
            + sum(height("•  " + b, tw - 3, 4.5, 9) for b in bullets) + pad
        if pdf.get_y() + total > pdf.h - pdf.b_margin:
            pdf.add_page()
        y0 = pdf.get_y()
        pdf.set_fill_color(*TINT[kind]); pdf.rect(x0, y0, w, total, "F")
        pdf.set_fill_color(*ACCENT[kind]); pdf.rect(x0, y0, bar, total, "F")
        pdf.set_xy(tx, y0 + pad)
        para(lead, tw, 4.7, 9.5, x=tx)
        for b in bullets:
            para("•  " + b, tw - 3, 4.5, 9, x=tx + 3)
        pdf.set_y(y0 + total + 2.2)
        pdf.set_fill_color(255, 255, 255); pdf.set_text_color(0, 0, 0)   # don't leak accent

    lines = md.splitlines()
    i, n = 0, len(lines)
    subtitle_next = False
    pdf.set_font(fam, size=9.7)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if (m := re.match(r"(#{1,3})\s+(.*)", s)):
            lvl, body = len(m.group(1)), m.group(2).strip()
            pdf.ln(2 if lvl > 1 else 0.5)
            pdf.set_text_color(*(NAVY if lvl <= 2 else GREY))
            pdf.set_font(fam, "B", {1: 16, 2: 12.5, 3: 10.5}[lvl])
            pdf.multi_cell(0, {1: 7.5, 2: 6, 3: 5}[lvl], txt(body), markdown=True)
            if lvl <= 2:
                y = pdf.get_y() + 0.3
                pdf.set_draw_color(*NAVY); pdf.set_line_width(0.5 if lvl == 1 else 0.3)
                pdf.line(14, y, pdf.w - 14, y); pdf.ln(1.6)
            pdf.set_text_color(0, 0, 0); pdf.set_font(fam, size=9.7)
            subtitle_next = (lvl == 1)
            i += 1
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            pdf.ln(0.8); pdf.set_draw_color(205, 205, 205); pdf.set_line_width(0.2)
            pdf.line(14, pdf.get_y(), pdf.w - 14, pdf.get_y()); pdf.ln(1.8)
            i += 1
            continue
        kind = next((k for k in ACCENT if re.match(rf"\*\*{k}\b", s, re.I)), None)
        if kind:
            lead = []
            while i < n and lines[i].strip() and not re.match(r"[-*]\s", lines[i].strip()):
                lead.append(lines[i].strip()); i += 1
            bullets = []
            while i < n and re.match(r"[-*]\s", lines[i].strip()):
                bullets.append(lines[i].strip()[2:].strip()); i += 1
            callout(kind.upper(), " ".join(lead), bullets)
            subtitle_next = False
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i])); i += 1
            rows = [r for r in rows if not _is_sep(r)]
            if rows:
                pdf.set_font(fam, size=8.4)
                pdf.set_text_color(0, 0, 0)
                pdf.set_fill_color(247, 249, 251)        # zebra; also guards against any leaked fill
                with pdf.table(markdown=True, first_row_as_headings=True, line_height=4.6,
                               padding=1.2, cell_fill_color=(247, 249, 251),
                               cell_fill_mode="EVEN_ROWS",
                               headings_style=FontFace(emphasis="BOLD", fill_color=HEAD_FILL)) as table:
                    for ri, r in enumerate(rows):
                        tr = table.row()
                        for c in r:
                            st = _cell_style(c) if ri else None
                            tr.cell(txt(c), style=st) if st else tr.cell(txt(c))
                pdf.set_font(fam, size=9.7); pdf.ln(0.8)
            subtitle_next = False
            continue
        if re.match(r"[-*]\s", s):
            while i < n and re.match(r"[-*]\s", lines[i].strip()):
                para("•  " + lines[i].strip()[2:].strip(), pdf.w - 18 - 14, 4.8, 9.7, x=18)
                i += 1
            pdf.ln(0.8)
            subtitle_next = False
            continue
        block = []
        while i < n and lines[i].strip() and not re.match(r"(#{1,3}\s|[-*]\s|\|)", lines[i].strip()) \
                and not re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", lines[i].strip()):
            block.append(lines[i].strip()); i += 1
        if subtitle_next:
            pdf.set_text_color(*GREY)
            para(" ".join(block), 0, 4.6, 8.6, style="I")
            pdf.set_text_color(0, 0, 0); pdf.ln(1.4); subtitle_next = False
        else:
            para(" ".join(block), 0, 4.9, 9.7); pdf.ln(1)

    pdf.output(str(out))
    return "fpdf2 (Markdown)"


# ── cascade ──────────────────────────────────────────────────────────────────────
def to_pdf(src, out):
    """Render src→out by the best available tier. Returns (engine, path):
    engine None + path=src means no renderer — the Markdown itself is the deliverable."""
    src = pathlib.Path(src)
    if src.suffix.lower() not in (".md", ".markdown", ".txt"):
        sys.exit(f"write the report as Markdown (.md); got {src.suffix or 'no extension'}")
    md = src.read_text()
    used = _html_pdf(md, out)                       # tier 1
    if used:
        return used, out
    try:
        return render_markdown(md, out), out        # tier 2
    except ImportError:
        return None, str(src)                        # tier 3


def _selftest():
    md = ("# Report self-test\n\nUnits like 5.5×10⁶ M⁻¹s⁻¹, Ca²⁺, 38 µM, →, ✓ and "
          "**bold**.\n\n## Tiers\n\n| Tier | Note |\n|---|---|\n| HARD — verify | one |\n"
          "| ADVISORY | five |\n| CONFIRMED | rest |\n\n## Findings\n\n"
          "**HARD — verify: beta 100× low.**\n\n- bullet one with detail\n- bullet two\n\n"
          "**ADVISORY — tuning.**\n\n- factor 0.2 scaling\n")
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "r.pdf"
        # tier 2 directly (needs fpdf2)
        try:
            render_markdown(md, out)
            assert out.read_bytes()[:4] == b"%PDF" and out.stat().st_size > 1500
            print("selftest OK — fpdf2 path")
        except ImportError:
            print("selftest: fpdf2 not installed (tier 2 unavailable)")
        # cascade
        src = pathlib.Path(d) / "r.md"; src.write_text(md)
        out2 = pathlib.Path(d) / "c.pdf"
        engine, path = to_pdf(src, out2)
        if engine:
            assert pathlib.Path(path).read_bytes()[:4] == b"%PDF"
            print(f"selftest OK — cascade chose: {engine}")
        else:
            print("selftest OK — cascade fell back to the Markdown file (no renderer)")


def main(argv):
    if argv == ["--selftest"]:
        return _selftest()
    if not argv:
        sys.exit("usage: python report_to_pdf.py report.md [out.pdf]   (or --selftest)")
    out = argv[1] if len(argv) > 1 else str(pathlib.Path(argv[0]).with_suffix(".pdf"))
    engine, path = to_pdf(argv[0], out)
    if engine:
        print(f"wrote {path} (via {engine})")
    else:
        print(f"no PDF renderer available (need a browser+markdown, or fpdf2) — "
              f"{path} is the report; Markdown reads fine as-is.")


if __name__ == "__main__":
    main(sys.argv[1:])
