#!/usr/bin/env python3
"""Render a validation report (Markdown) to PDF — pure Python, no browser/binaries.

Uses fpdf2.  A restricted-but-common Markdown subset is supported, enough for the
skill's reports: `#`/`##`/`###` headings, paragraphs, `-`/`*` bullet lists, pipe
tables, `---` rules, and inline `**bold**` / `_italic_` / `` `code` ``.  Unicode
(µ, M⁻¹s⁻¹, Ca²⁺, →, ✓, ×) renders via DejaVu Sans (borrowed from matplotlib if
present, else a system copy; falls back to a core font with ASCII transliteration).

    python report_to_pdf.py report.md [out.pdf]
    python report_to_pdf.py --selftest

Write the report as Markdown (it doubles as a readable .md). See SKILL.md →
"Generate a report".  Install once with:  pip install fpdf2
"""
import pathlib
import re
import sys
import tempfile

NAVY = (42, 77, 105)
GREY = (60, 60, 60)
HEAD_FILL = (238, 242, 246)

# ASCII transliteration used only when no Unicode font is available
_SANI = {"⁻": "-", "¹": "1", "²": "2", "³": "3", "⁺": "+", "₂": "2", "·": ".",
         "≈": "~", "×": "x", "→": "->", "✓": "[ok]", "µ": "u", "–": "-", "—": "-",
         "’": "'", "“": '"', "”": '"', "≥": ">=", "≤": "<="}


def _dejavu():
    """(regular, bold, italic) TTF paths for a Unicode font, or None."""
    try:
        from matplotlib import font_manager as fm
        fp = fm.FontProperties
        return (fm.findfont(fp(family="DejaVu Sans")),
                fm.findfont(fp(family="DejaVu Sans", weight="bold")),
                fm.findfont(fp(family="DejaVu Sans", style="italic")))
    except Exception:
        pass
    for base in ("/usr/share/fonts/truetype/dejavu", "/Library/Fonts",
                 "/System/Library/Fonts/Supplemental", "/usr/share/fonts/dejavu"):
        reg = pathlib.Path(base) / "DejaVuSans.ttf"
        if reg.exists():
            b, i = reg.with_name("DejaVuSans-Bold.ttf"), reg.with_name("DejaVuSans-Oblique.ttf")
            return (str(reg), str(b if b.exists() else reg), str(i if i.exists() else reg))
    return None


def _cells(row):
    return [c.strip().strip("`") for c in row.strip().strip("|").split("|")]


def _is_sep(cells):
    return all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c != "") and cells


def render_markdown(md, out):
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_margins(14, 14, 14)
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    files = _dejavu()
    if files:
        reg, bold, ital = files
        pdf.add_font("Body", "", reg)
        pdf.add_font("Body", "B", bold)
        pdf.add_font("Body", "I", ital)
        fam, uni = "Body", True
    else:
        fam, uni = "Helvetica", False

    def txt(s):
        return s if uni else "".join(_SANI.get(c, c if ord(c) < 256 else "?") for c in s)

    pdf.set_font(fam, size=10)
    lines, i, n = md.splitlines(), 0, len(md.splitlines())
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if (m := re.match(r"(#{1,3})\s+(.*)", s)):
            lvl, body = len(m.group(1)), m.group(2).strip()
            pdf.ln(3 if lvl > 1 else 1)
            pdf.set_text_color(*(NAVY if lvl <= 2 else GREY))
            pdf.set_font(fam, "B", {1: 17, 2: 13, 3: 11}[lvl])
            pdf.multi_cell(0, {1: 8, 2: 6.5, 3: 5.5}[lvl], txt(body), markdown=True)
            if lvl <= 2:
                y = pdf.get_y() + 0.5
                pdf.set_draw_color(*NAVY)
                pdf.set_line_width(0.5 if lvl == 1 else 0.3)
                pdf.line(14, y, pdf.w - 14, y)
                pdf.ln(2)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(fam, size=10)
            i += 1
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            pdf.ln(1); pdf.set_draw_color(200, 200, 200); pdf.set_line_width(0.2)
            pdf.line(14, pdf.get_y(), pdf.w - 14, pdf.get_y()); pdf.ln(2)
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i])); i += 1
            rows = [r for r in rows if not _is_sep(r)]
            if rows:
                pdf.set_font(fam, size=8.5)
                with pdf.table(markdown=True, first_row_as_headings=True,
                               headings_style=__import__("fpdf").fonts.FontFace(
                                   emphasis="BOLD", fill_color=HEAD_FILL),
                               line_height=5, padding=1.3) as table:
                    for r in rows:
                        tr = table.row()
                        for c in r:
                            tr.cell(txt(c))
                pdf.set_font(fam, size=10); pdf.ln(1)
            continue
        if re.match(r"[-*]\s", s):
            while i < n and re.match(r"[-*]\s", lines[i].strip()):
                item = lines[i].strip()[2:].strip()
                pdf.set_x(18)
                pdf.multi_cell(pdf.w - 18 - 14, 5, txt("•  " + item), markdown=True)
                i += 1
            pdf.ln(1)
            continue
        para = []
        while i < n and lines[i].strip() and not re.match(r"(#{1,3}\s|[-*]\s|\|)", lines[i].strip()) \
                and not re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", lines[i].strip()):
            para.append(lines[i].strip()); i += 1
        pdf.multi_cell(0, 5.2, txt(" ".join(para)), markdown=True); pdf.ln(1.5)

    pdf.output(str(out))
    return "fpdf2"


def to_pdf(src, out):
    src = pathlib.Path(src)
    if src.suffix.lower() not in (".md", ".markdown", ".txt"):
        sys.exit(f"write the report as Markdown (.md); got {src.suffix or 'no extension'}")
    return render_markdown(src.read_text(), out)


def _selftest():
    md = ("# Report self-test\n\nA paragraph with **bold** and units like 5.5×10⁶ M⁻¹s⁻¹, "
          "Ca²⁺, 38 µM, →, ✓.\n\n## Section\n\n- first bullet\n- second **bold** bullet\n\n"
          "| param | model | published | match |\n|---|---|---|---|\n"
          "| β | 58 | 5800 | 100× low |\n| b | 0.25 | 0.25 | exact |\n")
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "r.pdf"
        render_markdown(md, out)
        assert out.exists() and out.stat().st_size > 1500, "PDF not written / too small"
        assert out.read_bytes()[:4] == b"%PDF", "output is not a PDF"
    print("selftest OK (via fpdf2)")


def main(argv):
    if argv == ["--selftest"]:
        return _selftest()
    if not argv:
        sys.exit("usage: python report_to_pdf.py report.md [out.pdf]   (or --selftest)")
    out = argv[1] if len(argv) > 1 else str(pathlib.Path(argv[0]).with_suffix(".pdf"))
    try:
        used = to_pdf(argv[0], out)
    except ImportError:
        sys.exit(f"fpdf2 not installed — `pip install fpdf2` to render a PDF. "
                 f"If you can't install it, {argv[0]} is the report (Markdown reads fine as-is).")
    print(f"wrote {out} (via {used})")


if __name__ == "__main__":
    main(sys.argv[1:])
