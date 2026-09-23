#!/usr/bin/env python3
"""PDF helpers for the resume workflow. Resumes in this project are PDF only.

    python scripts/pdf-tools.py check
    python scripts/pdf-tools.py extract resume-library/resume.pdf
    python scripts/pdf-tools.py render page.html jobs/3-acme/resume.pdf [--engine NAME]
    python scripts/pdf-tools.py ats-check jobs/3-acme/resume.pdf [--name "Full Name"] [--keywords a,b,c]
    python scripts/pdf-tools.py ats-check resume-library/resume.pdf --base

`extract` prints the text of a PDF (tries pypdf, then PyMuPDF, then the
pdftotext program). `render` turns an HTML file into a PDF (tries WeasyPrint,
then headless Chrome/Edge, then wkhtmltopdf). `ats-check` reads a resume PDF
back the way an applicant tracking system does and reports what would trip a
parser: a JSON report with `pass`, `failures`, `warnings` and `info` (exit 1
when there are failures). With `--base` it only checks the content of a
resume you were given (contact details, headings, dates), not its layout.
Nothing here is required by the dashboard or db.py; only the skills call it.
Each engine is optional -- the first one that works on this machine is used.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


def _extract_pypdf(path):
    from pypdf import PdfReader
    return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def _import_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def _extract_pymupdf(path):
    with _import_pymupdf().open(str(path)) as doc:
        return "\n\n".join(page.get_text() for page in doc)


def _extract_pdftotext(path):
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext not installed")
    r = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout


EXTRACTORS = [("pypdf", _extract_pypdf), ("pymupdf", _extract_pymupdf), ("pdftotext", _extract_pdftotext)]


def _browser_exe():
    env = os.environ
    candidates = []
    if os.name == "nt":
        for base in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")):
            if base:
                candidates += [
                    Path(base) / "Microsoft/Edge/Application/msedge.exe",
                    Path(base) / "Google/Chrome/Application/chrome.exe",
                ]
    elif sys.platform == "darwin":
        candidates += [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    for c in candidates:
        if c.is_file():
            return str(c)
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _render_weasyprint(html, pdf):
    import weasyprint
    weasyprint.HTML(filename=str(html)).write_pdf(str(pdf))


def _render_browser(html, pdf):
    exe = _browser_exe()
    if not exe:
        raise RuntimeError("no Chrome or Edge found")
    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, "--headless", "--disable-gpu", f"--user-data-dir={profile}",
               "--no-pdf-header-footer", "--print-to-pdf-no-header",
               f"--print-to-pdf={Path(pdf).resolve()}", Path(html).resolve().as_uri()]
        subprocess.run(cmd, capture_output=True, timeout=90)


def _render_wkhtmltopdf(html, pdf):
    exe = shutil.which("wkhtmltopdf")
    if not exe:
        raise RuntimeError("wkhtmltopdf not installed")
    r = subprocess.run([exe, "--quiet", str(html), str(pdf)], capture_output=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip())


RENDERERS = [("weasyprint", _render_weasyprint), ("browser", _render_browser), ("wkhtmltopdf", _render_wkhtmltopdf)]


def _available():
    extract, render = [], []
    try:
        __import__("pypdf")
        extract.append("pypdf")
    except Exception:
        pass
    try:
        _import_pymupdf()
        extract.append("pymupdf")
    except Exception:
        pass
    if shutil.which("pdftotext"):
        extract.append("pdftotext")
    try:
        __import__("weasyprint")
        render.append("weasyprint")
    except Exception:
        pass
    if _browser_exe():
        render.append("browser")
    if shutil.which("wkhtmltopdf"):
        render.append("wkhtmltopdf")
    return extract, render


# ---------------------------------------------------------------------------
# ATS check
# ---------------------------------------------------------------------------

SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "profile", "professional profile", "career summary", "objective"},
    "experience": {"experience", "work experience", "professional experience", "employment history", "work history", "employment"},
    "education": {"education", "education and training", "academic background"},
    "skills": {"skills", "technical skills", "core skills", "skills and tools", "core competencies", "key skills"},
    "projects": {"projects", "selected projects", "personal projects"},
    "certifications": {"certifications", "certificates", "licenses and certifications", "certifications and training"},
}
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_PHONE = re.compile(r"(?<![\w/])(\+?\d[\d\s().-]{7,}\d)(?![\w/])")
RE_LOCATION = re.compile(r"\b[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+)*, [A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+)*\b")
RE_MONTH_YEAR = re.compile(rf"\b(?:{MONTHS})\.?,? (?:19|20)\d{{2}}\b", re.I)
RE_NUM_DATE = re.compile(r"\b(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}\b")
RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RE_BAD_GLYPHS = re.compile("[-�ﬀ-ﬆ​-‍﻿]")
# Tab, newline, carriage return, vertical tab and form feed are layout (readers
# use form feed between pages); everything else in this range is a decoding failure.
RE_CONTROL = re.compile("[\x00-\x08\x0e-\x1f\x7f]")
RE_SPACED = re.compile(r"(?:(?<=\s)|^)(?:[A-Za-z] ){6,}[A-Za-z](?=\s|$)")


def _read_text(path):
    """Text as an ATS would get it, plus which reader produced it."""
    for name, fn in EXTRACTORS:
        try:
            text = fn(path)
        except Exception:
            continue
        if text and text.strip():
            return name, text
    return None, ""


def _norm_line(s):
    return re.sub(r"[^a-z& ]", "", s.lower().replace("&", " and ")).strip()


def _find_sections(lines):
    found = {}
    for ln in lines:
        key = re.sub(r"\s+", " ", _norm_line(ln))
        if not key or len(key) > 40:
            continue
        for canon, aliases in SECTION_ALIASES.items():
            if key in aliases and canon not in found:
                found[canon] = ln.strip()
    return found


def _layout_checks(path, add_fail, add_warn, info):
    """Checks that need the PDF's structure, not just its text (PyMuPDF)."""
    try:
        mu = _import_pymupdf()
        doc = mu.open(str(path))
    except Exception:
        info["layout_checked"] = False
        return
    info["layout_checked"] = True
    pages = len(doc)
    info["pages"] = pages
    if pages > 2:
        add_fail("too_long", f"The resume is {pages} pages. Applicant tracking systems and recruiters expect one page, two at most. Cut the least relevant content.")
    elif pages == 2:
        p2 = doc[1]
        blocks = p2.get_text("blocks")
        bottom = max((b[3] for b in blocks), default=0)
        fill = bottom / p2.rect.height if p2.rect.height else 0
        info["last_page_fill"] = round(fill, 2)
        if fill < 0.30:
            add_warn("thin_second_page", "The second page is almost empty. Tighten the content so it fits on one page.")

    images = sum(len(pg.get_images()) for pg in doc)
    info["images"] = images
    if images:
        add_fail("has_images", f"The PDF contains {images} image(s). Parsers skip images, so anything inside them (logos, photos, text as pictures) is lost. Remove them.")

    fonts = set()
    type3 = set()
    for pg in doc:
        for f in pg.get_fonts():
            name = f[3] or f[4] or "unknown"
            fonts.add(name.split("+")[-1])
            if f[2] == "Type3":
                type3.add(name)
    info["fonts"] = sorted(fonts)
    if type3:
        add_fail("type3_fonts", f"Text is drawn with Type 3 fonts ({', '.join(sorted(type3))}), which many parsers cannot read. Use a standard font such as Arial.")

    # Text sitting side by side on one line (columns, right-aligned dates, tabs).
    wide_lines = 0
    for pg in doc:
        width = pg.rect.width
        # Group by vertical position, not by the PDF's own block and line
        # numbers: a table cell or a right-aligned span is its own block, so
        # grouping by block would never see the gap between it and its neighbour.
        lines = {}
        for x0, y0, x1, y1, word, _block, _line, _n in pg.get_text("words"):
            lines.setdefault(round((y0 + y1) / 2 / 3), []).append((x0, x1))
        for spans in lines.values():
            spans.sort()
            if any(b[0] - a[1] > width * 0.12 for a, b in zip(spans, spans[1:])):
                wide_lines += 1
    info["wide_gap_lines"] = wide_lines
    if wide_lines >= 6:
        add_fail("columns", "The layout looks multi-column or uses tabbed/right-aligned text on many lines. Parsers read it in the wrong order and mix up dates and titles. Use a single left-aligned column.")
    elif wide_lines >= 2:
        add_warn("side_by_side_text", f"{wide_lines} lines have text far apart (for example right-aligned dates). Some parsers attach the date to the wrong job. Put dates on the same left-aligned line, separated by ' | '.")

    if not (doc.metadata or {}).get("title"):
        add_warn("no_pdf_title", "The PDF has no title in its metadata. Set the HTML <title> to 'Full Name - Resume'.")


def ats_check(path, base=False, name=None, keywords=None):
    path = Path(path)
    failures, warnings, info = [], [], {}

    def add_fail(code, message):
        failures.append({"code": code, "message": message})

    def add_warn(code, message):
        warnings.append({"code": code, "message": message})

    if not path.is_file():
        add_fail("missing_pdf", f"No file at {path}")
        return {"mode": "base" if base else "tailored", "pass": False, "failures": failures, "warnings": warnings, "info": info}

    reader, text = _read_text(path)
    words = re.findall(r"\S+", text)
    info["reader"] = reader
    info["words"] = len(words)
    if len(words) < 30:
        add_fail("no_text_layer", "No readable text was found. This PDF is a scan or picture, so an ATS would see a blank page. Use a text-based PDF.")
        return {"mode": "base" if base else "tailored", "pass": False, "failures": failures, "warnings": warnings, "info": info}

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    info["first_line"] = lines[0][:80]
    if name:
        if _norm_line(name) not in _norm_line(" ".join(lines[:3])):
            add_fail("name_not_first", f"The name '{name}' is not at the top of the text. An ATS takes the first line as the candidate's name.")

    # Garbled text and glyphs that break parsing.
    bad = sorted(set(RE_BAD_GLYPHS.findall(text)))
    if bad or "(cid:" in text:
        add_fail("garbled_text", "Some characters read back as garbage (ligatures, private-use or unmapped glyphs). Re-render with ligatures off and a standard font.")
    # Bullets and separators that some readers decode as control characters.
    controls = set()
    for _name, fn in EXTRACTORS:
        try:
            controls |= set(RE_CONTROL.findall(fn(path)))
        except Exception:
            continue
    if controls:
        shown = ", ".join(f"U+{ord(c):04X}" for c in sorted(controls))
        if base:
            add_warn("control_characters", f"Some bullet or separator symbols read back as control characters ({shown}) in at least one PDF reader. The ATS-safe copies made for each job avoid this, so no action is needed on this file.")
        else:
            add_fail("control_characters", f"Some symbols read back as control characters ({shown}) in at least one PDF reader, which a parser may show as garbage. Use plain text bullets and separators.")
    if RE_SPACED.search(text):
        add_fail("letter_spaced", "Some words read back with spaces between letters (letter-spacing). Remove letter-spacing from the styling.")
    odd = sorted({c for c in text if unicodedata.category(c) == "So"})
    if odd:
        add_warn("decorative_glyphs", f"Decorative symbols or icons found ({' '.join(odd[:8])}). Parsers drop or garble them. Use plain text.")
    dashes = text.count("—") + text.count("–")
    if dashes:
        add_warn("special_dashes", f"{dashes} em or en dash(es) found. Use a plain hyphen, especially in date ranges.")

    # Contact details.
    head = "\n".join(lines[:14])
    emails = RE_EMAIL.findall(text)
    info["email"] = bool(emails)
    if not emails:
        add_fail("no_email", "No email address found in the text. It is the one thing a recruiter and an ATS must both have.")
    elif not RE_EMAIL.search(head):
        add_warn("contact_not_at_top", "The email is not near the top. Keep contact details in the body at the top of page 1, not in a header or footer.")
    phones = [m for m in RE_PHONE.findall(text) if len(re.sub(r"\D", "", m)) >= 9]
    info["phone"] = bool(phones)
    if not phones:
        add_fail("no_phone", "No phone number found. Add one, with the country code (for example +234 ...).")
    elif not any(p.strip().startswith("+") for p in phones):
        add_warn("phone_no_country_code", "The phone number has no country code. Add it (for example +234 ...) so it works for employers abroad.")
    if not RE_LOCATION.search(head):
        add_warn("no_location", "No 'City, Country' line found near the top. ATS filters often search by location.")
    if "linkedin.com" not in text.lower():
        add_warn("no_linkedin", "No LinkedIn address found. Many recruiters look for it.")

    # Standard section headings.
    sections = _find_sections(lines)
    info["sections"] = sorted(sections)
    if "skills" not in sections:
        add_fail("no_skills_heading", "No 'Skills' heading found. ATS keyword matching depends on a clearly labelled skills section.")
    if "education" not in sections:
        add_fail("no_education_heading", "No 'Education' heading found.")
    if "experience" not in sections and "projects" not in sections:
        add_fail("no_experience_heading", "No 'Experience' (or 'Projects') heading found. Use the standard word 'Experience'.")

    # Dates.
    mon_year = RE_MONTH_YEAR.findall(text)
    num_dates = RE_NUM_DATE.findall(text)
    info["dates"] = {"month_year": len(mon_year), "numeric": len(num_dates)}
    if ("experience" in sections) and len(mon_year) + len(num_dates) < 2:
        add_warn("dates_missing_months", "Few 'Month YYYY' dates found. ATS tools calculate experience from start and end months, so give a month for each role.")
    if mon_year and num_dates:
        add_warn("mixed_date_formats", "Dates mix 'Jan 2024' and '01/2024' styles. Use one format throughout.")

    if len(words) < 150:
        add_warn("very_short", f"Only {len(words)} words. A resume this short gives an ATS little to match.")
    if len(words) > 1000:
        add_warn("very_long", f"{len(words)} words is long. Trim to the most relevant content.")

    if not base:
        _layout_checks(path, add_fail, add_warn, info)
        # Two different readers should agree; if they don't, a parser may stumble too.
        try:
            a = set(re.findall(r"[a-z0-9]+", _extract_pypdf(path).lower()))
            b = set(re.findall(r"[a-z0-9]+", _extract_pymupdf(path).lower()))
            if a and b:
                overlap = len(a & b) / len(a | b)
                info["reader_agreement"] = round(overlap, 2)
                if overlap < 0.85:
                    add_warn("readers_disagree", "Two PDF readers extract noticeably different text from this file, which suggests a parser could also misread it.")
        except Exception:
            pass

    if keywords:
        low = text.lower()
        found, missing = [], []
        for kw in keywords:
            k = kw.strip().lower()
            if not k:
                continue
            (found if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low) else missing).append(kw.strip())
        info["keywords"] = {"found": found, "missing": missing}
        if missing:
            add_warn("keywords_missing", f"Not in the resume: {', '.join(missing)}. Add a keyword only where it truthfully describes the candidate's real experience.")

    return {"mode": "base" if base else "tailored", "pass": not failures, "failures": failures, "warnings": warnings, "info": info}


def cmd_ats_check(args):
    keywords = [k for k in (args.keywords or "").split(",") if k.strip()]
    report = ats_check(args.pdf, base=args.base, name=args.name, keywords=keywords)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


def cmd_check(_args):
    extract, render = _available()
    hints = []
    if not extract:
        hints.append("No PDF text reader found. Install one with: pip install pypdf")
    if not render:
        hints.append("No PDF maker found. Install Google Chrome or Microsoft Edge, or run: pip install weasyprint")
    print(json.dumps({"extract": extract, "render": render, "ok": bool(extract and render), "hints": hints}))
    return 0


def cmd_extract(args):
    path = Path(args.pdf)
    if not path.is_file():
        print(json.dumps({"error": "missing_pdf", "message": f"No file at {path}"}))
        return 2
    errors = []
    for name, fn in EXTRACTORS:
        try:
            text = fn(path)
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue
        if text.strip():
            sys.stdout.write(text)
            return 0
        errors.append(f"{name}: no text found")
    print(json.dumps({
        "error": "no_text",
        "message": "Could not read text from this PDF. If it is a scan or photo, "
                   "export a text-based PDF from your word processor. If no PDF "
                   "reader is installed, run: pip install pypdf",
        "details": errors,
    }))
    return 3


def cmd_render(args):
    html, pdf = Path(args.html), Path(args.pdf)
    if not html.is_file():
        print(json.dumps({"error": "missing_html", "message": f"No file at {html}"}))
        return 2
    pdf.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for name, fn in RENDERERS:
        if args.engine and args.engine != name:
            continue
        try:
            pdf.unlink(missing_ok=True)
            fn(html, pdf)
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue
        try:
            with open(pdf, "rb") as f:
                ok = f.read(5) == b"%PDF-"
        except OSError:
            ok = False
        if ok:
            print(json.dumps({"engine": name, "pdf": str(pdf), "bytes": pdf.stat().st_size}))
            return 0
        errors.append(f"{name}: produced no valid PDF")
    print(json.dumps({
        "error": "render_failed",
        "message": "Could not make a PDF. Install Google Chrome or Microsoft Edge, "
                   "or run: pip install weasyprint",
        "details": errors,
    }))
    return 3


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Report which PDF readers/makers are available").set_defaults(func=cmd_check)
    a = sub.add_parser("extract", help="Print the text of a PDF")
    a.add_argument("pdf")
    a.set_defaults(func=cmd_extract)
    a = sub.add_parser("render", help="Turn an HTML file into a PDF")
    a.add_argument("html")
    a.add_argument("pdf")
    a.add_argument("--engine", choices=[n for n, _ in RENDERERS], default=None)
    a.set_defaults(func=cmd_render)
    a = sub.add_parser("ats-check", help="Read a resume PDF back like an ATS and report anything that would trip a parser")
    a.add_argument("pdf")
    a.add_argument("--base", action="store_true", help="Only check content (contact, headings, dates), not layout. For a resume the user supplied.")
    a.add_argument("--name", default=None, help="The candidate's full name; must be the first thing in the text")
    a.add_argument("--keywords", default=None, help="Comma-separated job keywords to look for")
    a.set_defaults(func=cmd_ats_check)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
