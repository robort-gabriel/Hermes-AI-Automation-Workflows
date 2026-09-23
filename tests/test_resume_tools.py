"""Tests for scripts/resume-build.py and the `ats-check` command in
scripts/pdf-tools.py. Build and layout tests need a PDF maker and reader on the
machine and are skipped when there isn't one."""
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parent.parent
BUILD = REAL_ROOT / "scripts" / "resume-build.py"
TOOLS = REAL_ROOT / "scripts" / "pdf-tools.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = load(BUILD, "resume_build_under_test")
tools = load(TOOLS, "pdf_tools_under_test")
_extract, _render = tools._available()
HAVE_PDF = bool(_extract and _render)

SAMPLE = {
    "name": "Sam Doe",
    "headline": "Data Analyst",
    "contact": {"email": "sam@example.com", "phone": "+234 801 234 5678", "location": "Lagos, Nigeria",
                "linkedin": "linkedin.com/in/samdoe"},
    "summary": "Data analyst who turns messy operational data into clear weekly reports for decision makers.",
    "skills": [{"label": "Data", "items": ["SQL", "Python", "Power BI", "Excel"]},
               {"label": "Tools", "items": ["Git", "Airflow"]}],
    "experience": [
        {"title": "Data Analyst", "company": "Acme Ltd", "location": "Lagos, Nigeria", "start": "March 2023",
         "end": "Present", "bullets": ["Built a weekly sales dashboard used by 40 managers.",
                                        "Cut report preparation time from 6 hours to 30 minutes."]},
        {"title": "Junior Analyst", "company": "Beta Co", "start": "07/2021", "end": "Feb 2023",
         "bullets": ["Cleaned and merged five data sources in Python."]},
    ],
    "education": [{"degree": "Bachelor of Science in Statistics", "school": "University of Lagos", "end": "Jul 2021"}],
    "certifications": [{"name": "Google Data Analytics Certificate", "issuer": "Google", "year": "2022"}],
}


def sample(**changes):
    d = copy.deepcopy(SAMPLE)
    d.update(changes)
    return d


class TestCleaning(unittest.TestCase):
    def test_dashes_quotes_and_invisible_characters_are_normalised(self):
        self.assertEqual(build.clean_text("Led “team” — grew 2020–2022"), 'Led "team" - grew 2020-2022')
        self.assertEqual(build.clean_text("ofﬁce​"), "office")
        self.assertEqual(build.clean_text("Ready \U0001F680 now"), "Ready now")

    def test_dates(self):
        cases = {"July 2024": ("Jul 2024", True), "Sept 2024": ("Sep 2024", True), "07/2024": ("Jul 2024", True),
                 "2024-07": ("Jul 2024", True), "2024": ("2024", False), "current": ("Present", True),
                 "Present": ("Present", True)}
        for raw, expected in cases.items():
            self.assertEqual(build.norm_date(raw), expected, raw)
        self.assertEqual(build.norm_date("last spring"), (None, False))
        self.assertEqual(build.norm_date(""), (None, False))


class TestValidation(unittest.TestCase):
    def test_valid_sample_has_no_errors_and_normalises_dates(self):
        errors, warnings, data = build.validate(sample())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(data["experience"][0]["start"], "Mar 2023")
        self.assertEqual(data["experience"][1]["start"], "Jul 2021")

    def test_missing_details_are_reported_not_guessed(self):
        d = sample()
        d["contact"] = {"email": "not-an-email"}
        errors, _, _ = build.validate(d)
        text = " ".join(errors)
        for needle in ("contact.email", "contact.phone", "contact.location"):
            self.assertIn(needle, text)

    def test_phone_without_country_code_warns(self):
        d = sample()
        d["contact"]["phone"] = "0801 234 5678"
        errors, warnings, _ = build.validate(d)
        self.assertEqual(errors, [])
        self.assertTrue(any("country code" in w for w in warnings))

    def test_job_without_a_start_month_is_an_error_and_year_only_warns(self):
        d = sample()
        d["experience"][0]["start"] = None
        errors, _, _ = build.validate(d)
        self.assertTrue(any("experience[0]" in e and "start" in e for e in errors))
        d = sample()
        d["experience"][0]["start"] = "2023"
        errors, warnings, _ = build.validate(d)
        self.assertEqual(errors, [])
        self.assertTrue(any("no month" in w for w in warnings))

    def test_bad_section_page_and_accent_are_rejected(self):
        for change, needle in (({"section_order": ["summary", "photo"]}, "section_order"),
                               ({"page": "Legal"}, "page"), ({"accent": "red"}, "accent")):
            errors, _, _ = build.validate(sample(**change))
            self.assertTrue(any(needle in e for e in errors), change)

    def test_pale_accent_warns(self):
        _, warnings, _ = build.validate(sample(accent="#F5E6A0"))
        self.assertTrue(any("light" in w for w in warnings))


class TestHtml(unittest.TestCase):
    def html(self, data):
        errors, _, clean = build.validate(data)
        self.assertEqual(errors, [])
        return build.build_html(clean, 10.5, 0.7)

    def test_html_is_escaped(self):
        d = sample(summary="Uses <script>alert(1)</script> & more")
        out = self.html(d)
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_design_avoids_everything_an_ats_dislikes(self):
        out = self.html(sample())
        for banned in ("<table", "<img", "<svg", "display: flex", "display:flex", "display: grid",
                       "letter-spacing", "@font-face", "<header", "<footer", "position: absolute"):
            self.assertNotIn(banned, out)
        self.assertIn("font-variant-ligatures: none", out)
        self.assertIn("<title>Sam Doe - Resume</title>", out)

    def test_dates_and_company_share_one_left_aligned_line(self):
        out = self.html(sample())
        self.assertIn("Acme Ltd | Lagos, Nigeria | Mar 2023 - Present", out)

    def test_standard_headings_and_order(self):
        out = self.html(sample(section_order=["skills", "experience", "education"]))
        positions = [out.index(f"<h2>{h}</h2>") for h in ("Skills", "Experience", "Education")]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("<h2>Certifications</h2>", out)  # left out of section_order

    def test_contact_links_do_not_wrap_mid_url(self):
        self.assertIn("white-space: nowrap", self.html(sample()))


@unittest.skipUnless(HAVE_PDF, "needs a PDF reader and maker")
class TestBuildEndToEnd(unittest.TestCase):
    def run_build(self, data, *extra):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, pdf = Path(tmp.name) / "resume.json", Path(tmp.name) / "resume.pdf"
        src.write_text(json.dumps(data), encoding="utf-8")
        r = subprocess.run([sys.executable, str(BUILD), str(src), str(pdf), *extra],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            self.fail(f"no JSON output: {r.stdout!r} {r.stderr[-400:]!r}")
        return r.returncode, out, pdf

    def test_sample_builds_and_passes_the_ats_check(self):
        code, out, pdf = self.run_build(sample(), "--keywords", "SQL,Python,Kubernetes")
        self.assertEqual(code, 0, out.get("ats"))
        self.assertTrue(out["ats"]["pass"])
        self.assertEqual(out["pages"], 1)
        self.assertEqual(out["ats"]["info"]["first_line"], "Sam Doe")
        self.assertEqual(out["ats"]["info"]["images"], 0)
        self.assertEqual(out["ats"]["info"]["wide_gap_lines"], 0)
        self.assertEqual(out["ats"]["info"]["keywords"]["missing"], ["Kubernetes"])
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))

    def test_text_reads_back_in_order_with_plain_characters(self):
        _, _, pdf = self.run_build(sample())
        _, text = tools._read_text(pdf)
        self.assertLess(text.index("Sam Doe"), text.index("Professional Summary"))
        self.assertLess(text.index("Professional Summary"), text.index("Skills"))
        self.assertLess(text.index("Skills"), text.index("Experience"))
        self.assertIn("Acme Ltd | Lagos, Nigeria | Mar 2023 - Present", text)
        self.assertIn("linkedin.com/in/samdoe", text)  # not split across lines
        self.assertNotIn("—", text)
        self.assertNotIn("�", text)

    def test_letter_page_size_is_honoured(self):
        _, out, pdf = self.run_build(sample(page="Letter"))
        with tools._import_pymupdf().open(str(pdf)) as doc:
            self.assertEqual((round(doc[0].rect.width), round(doc[0].rect.height)), (612, 792))

    def test_too_much_content_stays_readable_and_at_most_two_pages(self):
        long_bullets = [f"Delivered improvement number {i} across the reporting process for the finance team." for i in range(9)]
        exp = [{"title": f"Analyst {i}", "company": f"Company {i}", "start": "Jan 2015", "end": "Dec 2016",
                "bullets": long_bullets} for i in range(4)]
        code, out, _ = self.run_build(sample(experience=exp))
        self.assertGreaterEqual(out["font_pt"], 10)  # never shrunk into a cramped two-pager
        self.assertLessEqual(out["pages"], 2)
        self.assertEqual(code, 0, out["ats"])

    def test_invalid_data_exits_2_and_lists_what_is_missing(self):
        d = sample()
        d["contact"].pop("phone")
        code, out, pdf = self.run_build(d)
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "invalid_resume_data")
        self.assertTrue(any("phone" in e for e in out["errors"]))
        self.assertFalse(pdf.exists())

    def test_every_engine_builds_a_two_page_resume_without_false_alarms(self):
        # Regression: page separators (form feed) once tripped the control-character check.
        bullets = [f"Delivered improvement number {i} across the reporting process for the finance team." for i in range(9)]
        exp = [{"title": f"Analyst {i}", "company": f"Company {i}", "start": "Jan 2015", "end": "Dec 2016",
                "bullets": bullets} for i in range(4)]
        for engine in _render:
            code, out, _ = self.run_build(sample(experience=exp), "--engine", engine)
            self.assertEqual(code, 0, (engine, out["ats"]["failures"]))
            self.assertNotIn("control_characters", {f["code"] for f in out["ats"]["failures"]}, engine)

    def test_three_page_resume_fails_the_check(self):
        bullets = [f"Delivered a very detailed improvement number {i} across the reporting and finance process." for i in range(12)]
        exp = [{"title": f"Analyst {i}", "company": f"Company {i}", "start": "Jan 2010", "end": "Dec 2011",
                "bullets": bullets} for i in range(9)]
        code, out, _ = self.run_build(sample(experience=exp))
        self.assertEqual(code, 1)
        self.assertIn("too_long", [f["code"] for f in out["ats"]["failures"]])


@unittest.skipUnless(HAVE_PDF, "needs a PDF reader and maker")
class TestAtsCheckCatchesProblems(unittest.TestCase):
    def pdf_from_html(self, body, css=""):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, pdf = Path(tmp.name) / "p.html", Path(tmp.name) / "p.pdf"
        src.write_text(f"<!doctype html><meta charset=utf-8><title>T</title><style>{css}</style>{body}", encoding="utf-8")
        r = subprocess.run([sys.executable, str(TOOLS), "render", str(src), str(pdf), "--engine", "weasyprint"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("weasyprint not available")
        return pdf

    GOOD = ("<h1>Sam Doe</h1><p>sam@example.com | +234 801 234 5678 | Lagos, Nigeria | linkedin.com/in/samdoe</p>"
            "<h2>Skills</h2><p>SQL, Python</p><h2>Experience</h2><p>Analyst | Acme | Jan 2022 - Present</p>"
            "<p>" + "Built reports and dashboards for finance managers every week. " * 14 + "</p>"
            "<h2>Education</h2><p>BSc Statistics | University of Lagos | 2021</p>")

    def codes(self, report):
        return {f["code"] for f in report["failures"]}, {w["code"] for w in report["warnings"]}

    def test_a_clean_document_passes(self):
        report = tools.ats_check(self.pdf_from_html(self.GOOD), name="Sam Doe")
        self.assertTrue(report["pass"], report["failures"])

    def test_an_image_fails(self):
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        report = tools.ats_check(self.pdf_from_html(self.GOOD + f"<img src='{png}' width=40 height=40>"))
        self.assertIn("has_images", self.codes(report)[0])

    def test_columns_and_right_aligned_text_are_flagged(self):
        css = ".row{display:table;width:100%}.l{display:table-cell}.r{display:table-cell;text-align:right}"
        rows = "".join(f"<div class=row><span class=l>Job title number {i}</span><span class=r>Jan 20{i:02d} - Dec 20{i + 1:02d}</span></div>" for i in range(1, 8))
        report = tools.ats_check(self.pdf_from_html(self.GOOD + rows, css))
        failures, warnings = self.codes(report)
        self.assertTrue({"columns"} & failures or {"side_by_side_text"} & warnings, (failures, warnings))

    def test_letter_spacing_and_ligatures_are_flagged(self):
        report = tools.ats_check(self.pdf_from_html(self.GOOD + "<h3>WORK HISTORY</h3>", "h3{letter-spacing:6pt}"))
        self.assertIn("letter_spaced", self.codes(report)[0])

    def test_decorative_symbols_warn(self):
        report = tools.ats_check(self.pdf_from_html(self.GOOD.replace("Skills</h2>", "Skills</h2><p>★ ★ ★ ★</p>")))
        self.assertIn("decorative_glyphs", self.codes(report)[1])

    def test_missing_email_phone_and_headings_fail(self):
        report = tools.ats_check(self.pdf_from_html("<h1>Sam Doe</h1><p>" + "I have worked with many teams and tools over the years. " * 12 + "</p>"))
        failures = self.codes(report)[0]
        for code in ("no_email", "no_phone", "no_skills_heading", "no_education_heading", "no_experience_heading"):
            self.assertIn(code, failures)

    def test_name_must_be_first(self):
        report = tools.ats_check(self.pdf_from_html(self.GOOD), name="Someone Else")
        self.assertIn("name_not_first", self.codes(report)[0])

    def test_phone_without_country_code_and_special_dashes_warn(self):
        body = self.GOOD.replace("+234 801 234 5678", "0801 234 5678").replace("Jan 2022 - Present", "Jan 2022 – Present")
        warnings = self.codes(tools.ats_check(self.pdf_from_html(body)))[1]
        self.assertIn("phone_no_country_code", warnings)
        self.assertIn("special_dashes", warnings)

    def test_control_characters_are_recognised(self):
        # Some readers decode bullets and separators as DEL or other control codes.
        for ch in ("\x7f", "\x01", "\x1b"):
            self.assertTrue(tools.RE_CONTROL.search(f"Enugu {ch} 0806"), repr(ch))
        # Layout characters, including the form feed readers put between pages, are fine.
        for ch in ("\n", "\t", "\r", "\x0b", "\x0c", "•"):
            self.assertIsNone(tools.RE_CONTROL.search(f"Enugu {ch} 0806"), repr(ch))

    def test_a_blank_or_missing_file_fails_clearly(self):
        self.assertIn("missing_pdf", self.codes(tools.ats_check("does-not-exist.pdf"))[0])
        report = tools.ats_check(self.pdf_from_html("<p>hi</p>"))
        self.assertIn("no_text_layer", self.codes(report)[0])

    def test_base_mode_skips_layout_checks(self):
        report = tools.ats_check(self.pdf_from_html(self.GOOD), base=True)
        self.assertEqual(report["mode"], "base")
        self.assertNotIn("layout_checked", report["info"])


if __name__ == "__main__":
    unittest.main()
