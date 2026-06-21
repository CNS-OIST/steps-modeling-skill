#!/usr/bin/env python3
"""Convert a validation report (self-contained HTML, or Markdown) to PDF using
whichever backend is installed — so the steps-modeling skill can emit a PDF report
without assuming a particular toolchain.

Backends, tried in order:
  HTML  → headless Chrome/Chromium  →  wkhtmltopdf
  MD    → pandoc
If none is found it leaves the source in place and tells you to print it by hand.

    python report_to_pdf.py report.html [out.pdf]     # or report.md
    python report_to_pdf.py --selftest

Write the report as a single self-contained .html (inline CSS, no external assets) —
Chrome is the most widely available HTML→PDF engine. See SKILL.md → "Generate a report".
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "chrome",
]


def _find_chrome():
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists() or shutil.which(c):
            return c
    return None


def to_pdf(src, out):
    """Render src -> out. Returns the backend name used, or None if none available."""
    src, out = pathlib.Path(src).resolve(), pathlib.Path(out).resolve()
    is_md = src.suffix.lower() in (".md", ".markdown")
    if is_md:
        if shutil.which("pandoc"):
            subprocess.run(["pandoc", str(src), "-o", str(out)], check=True)
            return "pandoc"
        return None
    chrome = _find_chrome()
    if chrome:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", src.as_uri()], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "chrome"
    if shutil.which("wkhtmltopdf"):
        subprocess.run(["wkhtmltopdf", str(src), str(out)], check=True)
        return "wkhtmltopdf"
    return None


def _selftest():
    with tempfile.TemporaryDirectory() as d:
        html = pathlib.Path(d) / "r.html"
        html.write_text("<!doctype html><meta charset=utf-8>"
                        "<h1>self-test</h1><p>report_to_pdf works.</p>")
        out = pathlib.Path(d) / "r.pdf"
        used = to_pdf(html, out)
        if used is None:
            print("no HTML→PDF backend (Chrome/wkhtmltopdf) on this machine — "
                  "selftest skipped (the script's logic is fine; install one to render)")
            return
        assert out.exists() and out.stat().st_size > 1000, "PDF not written / too small"
        assert out.read_bytes()[:4] == b"%PDF", "output is not a PDF"
        print(f"selftest OK (via {used})")


def main(argv):
    if argv == ["--selftest"]:
        return _selftest()
    if not argv:
        sys.exit("usage: python report_to_pdf.py report.html|.md [out.pdf]   (or --selftest)")
    src = argv[0]
    out = argv[1] if len(argv) > 1 else str(pathlib.Path(src).with_suffix(".pdf"))
    used = to_pdf(src, out)
    if used:
        print(f"wrote {out} (via {used})")
    else:
        need = "pandoc" if pathlib.Path(src).suffix.lower() in (".md", ".markdown") \
            else "Chrome/Chromium or wkhtmltopdf"
        sys.exit(f"no PDF backend found (need {need}) — open {src} in a browser and Print → PDF")


if __name__ == "__main__":
    main(sys.argv[1:])
