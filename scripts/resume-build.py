#!/usr/bin/env python3
"""Build an ATS-safe resume PDF from structured JSON.

    python scripts/resume-build.py resume.json jobs/3-acme/resume.pdf [--keywords a,b,c] [--engine NAME]

The design lives here, not in the model's head: one left-aligned column, a
standard font, real text, standard section headings, dates on the same line as
the company, plain hyphens, no tables, icons, images, headers or footers. That
is what applicant tracking systems parse reliably. The JSON only supplies the
words (see hermes-skills/resume-pdf-designer/SKILL.md for the schema).

Prints one JSON object: {"pdf", "engine", "pages", "font_pt", "ats": {...}} and
exits 0 when the ATS check passes, 1 when it does not, 2 when the input JSON is
unusable (the errors are listed so they can be fixed and the build re-run).
"""
import argparse
import html
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF_TOOLS = ROOT / "scripts" / "pdf-tools.py"

DEFAULT_ACCENT = "#1F3A5F"
DEFAULT_ORDER = ["summary", "skills", "experience", "projects", "education", "certifications"]
HEADINGS = {
    "summary": "Professional Summary", "skills": "Skills", "experience": "Experience",
    "projects": "Projects", "education": "Education", "certifications": "Certifications",
}
# (body font pt, page margin inches). Tried in order; the first that fits one page wins.
FIT_STEPS = [(10.5, 0.70), (10.0, 0.65), (9.5, 0.60)]
MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_ABBR = [m.capitalize() for m in MONTH_NAMES]
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def load_pdf_tools():
    spec = importlib.util.spec_from_file_location("pdf_tools", PDF_TOOLS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Text and dates
# ---------------------------------------------------------------------------

_REPLACE = {
    "—": " - ", "–": "-", "−": "-", "‐": "-", "‑": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    " ": " ", " ": " ", " ": " ", "…": "...",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "•": "", "●": "", "▪": "", "◦": "",
}
_STRIP = re.compile("[​-‍﻿�-]")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")


def clean_text(value):
    """Normalise text so it reads back cleanly: plain hyphens and quotes, no
    ligatures, invisible characters or emoji."""
    if not isinstance(value, str):
        return value
    s = value
    for bad, good in _REPLACE.items():
        s = s.replace(bad, good)
    s = _STRIP.sub("", s)
    s = _EMOJI.sub("", s)
    s = s.replace("--", "-")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" +- +", " - ", s)
    return s.strip()


def clean_tree(obj):
    if isinstance(obj, dict):
        return {k: clean_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_tree(v) for v in obj]
    return clean_text(obj)


def norm_date(value):
    """'July 2024', 'Sept 2024', '07/2024', '2024-07' -> 'Jul 2024'; '2024' stays;
    'present/current/now' -> 'Present'. Returns (text, has_month) or (None, False)."""
    if value is None:
        return None, False
    v = clean_text(str(value)).strip().rstrip(".")
    if not v:
        return None, False
    if v.lower() in ("present", "current", "now", "ongoing", "to date"):
        return "Present", True
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?,? +((?:19|20)\d{2})", v)
    if m and m.group(1)[:3].lower() in MONTH_NAMES:
        return f"{MONTH_ABBR[MONTH_NAMES.index(m.group(1)[:3].lower())]} {m.group(2)}", True
    m = re.fullmatch(r"(0?[1-9]|1[0-2])[/.-]((?:19|20)\d{2})", v)
    if m:
        return f"{MONTH_ABBR[int(m.group(1)) - 1]} {m.group(2)}", True
    m = re.fullmatch(r"((?:19|20)\d{2})[/.-](0?[1-9]|1[0-2])", v)
    if m:
        return f"{MONTH_ABBR[int(m.group(2)) - 1]} {m.group(1)}", True
    if re.fullmatch(r"(?:19|20)\d{2}", v):
        return v, False
    return None, False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _need(errors, cond, msg):
    if not cond:
        errors.append(msg)


def validate(data):
    """Returns (errors, warnings, normalised data). Errors stop the build."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["The JSON must be an object."], [], data
    data = clean_tree(data)
    contact = data.get("contact") or {}
    _need(errors, data.get("name"), 'Missing "name" (the full name, exactly as the candidate writes it).')
    _need(errors, contact.get("email") and RE_EMAIL.match(contact["email"]), 'Missing or invalid "contact.email".')
    phone = contact.get("phone") or ""
    _need(errors, len(re.sub(r"\D", "", phone)) >= 9, 'Missing "contact.phone". Ask the candidate for it, with the country code.')
    if phone and not phone.startswith("+"):
        warnings.append('"contact.phone" has no country code (for example +234 ...). Ask the candidate for the international format.')
    _need(errors, contact.get("location"), 'Missing "contact.location" as "City, Country". ATS filters search by location.')
    if not contact.get("linkedin"):
        warnings.append('No "contact.linkedin". Ask the candidate for it if they have one.')

    exp, proj = data.get("experience") or [], data.get("projects") or []
    _need(errors, exp or proj, 'Provide at least one entry in "experience" or "projects".')
    _need(errors, data.get("skills"), 'Missing "skills" (a list of {"label": ..., "items": [...]}).')
    _need(errors, data.get("education"), 'Missing "education".')

    order = data.get("section_order") or DEFAULT_ORDER
    bad = [s for s in order if s not in HEADINGS]
    _need(errors, not bad, f'Unknown section(s) in "section_order": {bad}. Allowed: {list(HEADINGS)}.')

    for i, e in enumerate(exp):
        tag = f"experience[{i}]"
        _need(errors, e.get("title"), f'{tag} needs "title" (the exact job title).')
        _need(errors, e.get("company"), f'{tag} needs "company".')
        start, start_m = norm_date(e.get("start"))
        end, end_m = norm_date(e.get("end"))
        _need(errors, start, f'{tag} needs "start" as Month YYYY (for example "Jul 2024"). Ask the candidate for the month if it is missing; never guess.')
        _need(errors, end, f'{tag} needs "end" as Month YYYY, or "Present".')
        if start and not start_m:
            warnings.append(f"{tag}.start has no month. ATS tools calculate experience from months; ask the candidate.")
        if end and not end_m:
            warnings.append(f"{tag}.end has no month. ATS tools calculate experience from months; ask the candidate.")
        e["start"], e["end"] = start, end
        _need(errors, e.get("bullets"), f'{tag} needs at least one bullet.')
    for i, p in enumerate(proj):
        _need(errors, p.get("name"), f'projects[{i}] needs "name".')
        _need(errors, p.get("bullets"), f'projects[{i}] needs at least one bullet.')
    for i, ed in enumerate(data.get("education") or []):
        _need(errors, ed.get("degree"), f'education[{i}] needs "degree", spelled out.')
        _need(errors, ed.get("school"), f'education[{i}] needs "school".')
        end, _ = norm_date(ed.get("end"))
        _need(errors, end, f'education[{i}] needs "end" (graduation month and year, or year).')
        ed["end"] = end
    for i, s in enumerate(data.get("skills") or []):
        _need(errors, s.get("items"), f'skills[{i}] needs "items".')
    for i, c in enumerate(data.get("certifications") or []):
        _need(errors, c.get("name"), f'certifications[{i}] needs "name".')
        if c.get("year"):
            c["year"] = norm_date(c["year"])[0] or c["year"]

    accent = data.get("accent") or DEFAULT_ACCENT
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
        errors.append('"accent" must be a hex colour like "#1F3A5F".')
    elif _luminance(accent) > 0.35:
        warnings.append('"accent" is quite light; it may be hard to read when printed. Pick a darker colour.')
    if data.get("page", "A4") not in ("A4", "Letter"):
        errors.append('"page" must be "A4" or "Letter".')
    return errors, warnings, data


def _luminance(hex_color):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def e(s):
    return html.escape(s or "", quote=True)


def _link(url):
    """A visible, plain-text URL that is also clickable."""
    shown = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    href = url if re.match(r"^https?://", url) else "https://" + url
    return f'<a href="{e(href)}">{e(shown)}</a>'


def _bullets(items):
    return "<ul>" + "".join(f"<li>{e(b)}</li>" for b in items if b) + "</ul>"


def build_html(data, font_pt, margin_in):
    accent = data.get("accent") or DEFAULT_ACCENT
    page = data.get("page", "A4")
    c = data.get("contact") or {}
    basics = [e(c[k]) for k in ("email", "phone", "location") if c.get(k)]
    links = [_link(c[k]) for k in ("linkedin", "github", "website") if c.get(k)]
    header = f"<h1>{e(data['name'])}</h1>"
    if data.get("headline"):
        header += f'<p class="headline">{e(data["headline"])}</p>'
    header += '<p class="contact">' + " | ".join(basics) + "</p>"
    if links:
        header += '<p class="contact">' + " | ".join(links) + "</p>"

    sections = {}
    if data.get("summary"):
        sections["summary"] = f"<p>{e(data['summary'])}</p>"
    if data.get("skills"):
        sections["skills"] = "".join(
            f'<p class="skill"><strong>{e(s["label"])}:</strong> {e(", ".join(s["items"]))}</p>' if s.get("label")
            else f'<p class="skill">{e(", ".join(s["items"]))}</p>'
            for s in data["skills"])
    if data.get("experience"):
        out = []
        for x in data["experience"]:
            meta = " | ".join(v for v in (x["company"], x.get("location"), f'{x["start"]} - {x["end"]}') if v)
            out.append(f'<div class="entry"><h3>{e(x["title"])}</h3><p class="meta">{e(meta)}</p>{_bullets(x["bullets"])}</div>')
        sections["experience"] = "".join(out)
    if data.get("projects"):
        out = []
        for p in data["projects"]:
            meta = " | ".join(v for v in ((f'Tools: {p["stack"]}' if p.get("stack") else ""), p.get("dates", "")) if v)
            link = f' | {_link(p["url"])}' if p.get("url") else ""
            metaline = f'<p class="meta">{e(meta)}{link}</p>' if (meta or link) else ""
            out.append(f'<div class="entry"><h3>{e(p["name"])}</h3>{metaline}{_bullets(p["bullets"])}</div>')
        sections["projects"] = "".join(out)
    if data.get("education"):
        out = []
        for ed in data["education"]:
            meta = " | ".join(v for v in (ed["school"], ed.get("location"), ed["end"]) if v)
            extra = _bullets(ed["details"]) if ed.get("details") else ""
            out.append(f'<div class="entry"><h3>{e(ed["degree"])}</h3><p class="meta">{e(meta)}</p>{extra}</div>')
        sections["education"] = "".join(out)
    if data.get("certifications"):
        items = []
        for ct in data["certifications"]:
            tail = ", ".join(v for v in (ct.get("issuer"), ct.get("year")) if v)
            items.append(ct["name"] + (f" - {tail}" if tail else ""))
        sections["certifications"] = _bullets(items)

    body = "".join(
        f"<h2>{HEADINGS[k]}</h2>{sections[k]}"
        for k in (data.get("section_order") or DEFAULT_ORDER) if k in sections)

    css = f"""
@page {{ size: {page}; margin: {margin_in}in; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ font-family: Arial, Helvetica, "Liberation Sans", sans-serif; font-variant-ligatures: none; }}
body {{ font-size: {font_pt}pt; line-height: 1.32; color: #111111; background: #ffffff; }}
h1 {{ font-size: {font_pt + 12}pt; line-height: 1.1; font-weight: 700; color: {accent}; }}
.headline {{ font-size: {font_pt + 1.5}pt; margin-top: 3pt; color: #222222; }}
.contact {{ margin-top: 4pt; color: #222222; }}
.contact + .contact {{ margin-top: 1pt; }}
.contact a {{ color: inherit; text-decoration: none; white-space: nowrap; }}
h2 {{ font-size: {font_pt + 0.5}pt; font-weight: 700; color: {accent}; border-bottom: 0.75pt solid {accent}; padding-bottom: 2pt; margin: {font_pt + 2}pt 0 5pt; break-after: avoid; }}
h3 {{ font-size: {font_pt + 0.5}pt; font-weight: 700; color: #111111; break-after: avoid; }}
p {{ margin: 0; }}
.meta {{ color: #333333; margin-top: 1pt; break-after: avoid; }}
.entry {{ margin-bottom: 6pt; orphans: 3; widows: 3; }}
.skill {{ margin-bottom: 2pt; break-inside: avoid; }}
ul {{ margin: 3pt 0 0 {font_pt * 1.3:.1f}pt; }}
li {{ margin-bottom: 1.5pt; break-inside: avoid; }}
"""
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{e(data["name"])} - Resume</title>'
            f'<meta name="author" content="{e(data["name"])}">'
            f"<style>{css}</style></head><body>{header}{body}</body></html>")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def render(html_text, pdf_path, engine=None):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "resume.html"
        src.write_text(html_text, encoding="utf-8")
        cmd = [sys.executable, str(PDF_TOOLS), "render", str(src), str(pdf_path)]
        if engine:
            cmd += ["--engine", engine]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return r.returncode, {"error": "render_failed", "message": r.stderr.strip() or "no output"}


def page_count(pdf_path):
    tools = load_pdf_tools()
    with tools._import_pymupdf().open(str(pdf_path)) as doc:
        return len(doc)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_file", help="The resume content (see the resume-pdf-designer skill for the schema)")
    ap.add_argument("pdf", help="Where to write the PDF, for example jobs/3-acme/resume.pdf")
    ap.add_argument("--keywords", default=None, help="Comma-separated job keywords to look for in the finished PDF")
    ap.add_argument("--engine", default=None, help="Force a PDF engine: weasyprint, browser or wkhtmltopdf")
    args = ap.parse_args()

    try:
        raw = json.loads(Path(args.json_file).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": "bad_json", "message": f"Could not read {args.json_file}: {exc}"}))
        return 2
    errors, warnings, data = validate(raw)
    if errors:
        print(json.dumps({"error": "invalid_resume_data", "errors": errors, "warnings": warnings}, indent=2))
        return 2

    pdf = Path(args.pdf)
    chosen = None
    result = {}
    # Shrink slightly to fit one page. If even the smallest step needs two pages,
    # go back to the most readable size: a cramped two-pager is worse than a
    # comfortable one.
    for font_pt, margin in FIT_STEPS:
        code, result = render(build_html(data, font_pt, margin), pdf, args.engine)
        if code != 0:
            print(json.dumps({"error": "render_failed", **result}, indent=2))
            return 2
        pages = page_count(pdf)
        chosen = (font_pt, pages)
        if pages <= 1:
            break
    else:
        font_pt, margin = FIT_STEPS[0]
        code, result = render(build_html(data, font_pt, margin), pdf, args.engine)
        if code != 0:
            print(json.dumps({"error": "render_failed", **result}, indent=2))
            return 2
        chosen = (font_pt, page_count(pdf))

    tools = load_pdf_tools()
    keywords = [k for k in (args.keywords or "").split(",") if k.strip()]
    report = tools.ats_check(pdf, base=False, name=data["name"], keywords=keywords)
    out = {"pdf": str(pdf), "engine": result.get("engine"), "pages": chosen[1], "font_pt": chosen[0],
           "input_warnings": warnings, "ats": report}
    print(json.dumps(out, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
