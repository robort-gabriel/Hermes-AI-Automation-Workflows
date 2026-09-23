"""Tests for scripts/db.py, run against a throwaway project folder so the real
job-hunter.db, jobs/ and config/ are never touched."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

REAL_ROOT = Path(__file__).resolve().parent.parent
DB_SCRIPT = REAL_ROOT / "scripts" / "db.py"


def load_db(root):
    spec = importlib.util.spec_from_file_location("db_under_test", DB_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.DB_PATH = root / "data" / "job-hunter.db"
    mod.SEARCH_CONFIG_PATH = root / "config" / "search-config.md"
    return mod


def call(fn, **kwargs):
    """Run a cmd_* function, returning (exit_code, parsed_json_output)."""
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            fn(SimpleNamespace(**kwargs))
        except SystemExit as e:
            code = e.code or 0
    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    return code, json.loads(lines[-1]) if lines else None


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "config").mkdir()
        shutil.copy(REAL_ROOT / "data" / "schema.sql", self.root / "data" / "schema.sql")
        self.db = load_db(self.root)
        self.db.SCHEMA_PATH = self.root / "data" / "schema.sql"
        conn = self.db.get_conn()
        conn.executescript(self.db.SCHEMA_PATH.read_text())
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def onboard(self):
        call(self.db.cmd_set_setting, key="onboarded", value="yes")

    def new_run(self):
        self.onboard()
        code, out = call(self.db.cmd_start_run, role="Backend Engineer",
                         seniority="Senior", location="Remote", target_companies=None)
        self.assertEqual(code, 0)
        return out["id"]

    def add_job(self, run_id, posted, **over):
        args = dict(run_id=run_id, company="Acme Co", title="Backend Engineer",
                    url="https://acme.example/careers/1", location="Remote",
                    source="target-list", posted_date=posted, match_score=85,
                    match_notes="Strong overlap")
        args.update(over)
        return call(self.db.cmd_add_job, **args)

    def status_of(self, table, row_id):
        conn = self.db.get_conn()
        row = conn.execute(f"SELECT status FROM {table} WHERE id = ?", (row_id,)).fetchone()
        conn.close()
        return row["status"]


class TestPipeline(DbTestCase):
    def test_full_lifecycle_with_pdf_resume(self):
        run_id = self.new_run()
        self.assertEqual(self.status_of("runs", run_id), "new")
        call(self.db.cmd_mark_researching, run_id=run_id)

        code, job = self.add_job(run_id, date.today().isoformat())
        self.assertEqual(code, 0)
        self.assertFalse(job["date_unknown"])
        call(self.db.cmd_mark_jobs_found, run_id=run_id)

        folder = self.root / "jobs" / f"{job['id']}-acme-co"
        folder.mkdir(parents=True)
        (folder / "resume.pdf").write_bytes(b"%PDF-1.4\n%fake\n")
        code, _ = call(self.db.cmd_save_resume, id=job["id"],
                       job_folder=f"jobs/{job['id']}-acme-co",
                       resume_pdf_path=f"jobs/{job['id']}-acme-co/resume.pdf")
        self.assertEqual(code, 0)
        self.assertEqual(self.status_of("jobs", job["id"]), "resume_ready")

        call(self.db.cmd_mark_resume_ready, run_id=run_id)
        call(self.db.cmd_mark_presented, run_id=run_id)
        self.assertEqual(self.status_of("runs", run_id), "presented")

        conn = self.db.get_conn()
        names = [e["event"] for e in conn.execute("SELECT event FROM events WHERE run_id=?", (run_id,))]
        conn.close()
        for expected in ["run_created", "researching", "job_found", "jobs_found",
                         "resume_tailored", "resume_ready", "presented"]:
            self.assertIn(expected, names)


class TestOnboardingGate(DbTestCase):
    def test_start_run_refused_until_onboarded(self):
        code, out = call(self.db.cmd_start_run, role="X", seniority=None,
                         location=None, target_companies=None)
        self.assertEqual(code, 4)
        self.assertEqual(out["error"], "not_onboarded")
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        conn.close()

    def test_start_run_allowed_after_onboarding(self):
        self.new_run()


class TestFreshness(DbTestCase):
    def test_default_window_is_three_days(self):
        self.assertEqual(self.db.max_job_age_days(), 3)

    def test_window_read_from_search_config(self):
        (self.root / "config" / "search-config.md").write_text("- **Max job age (days):** 7\n")
        self.assertEqual(self.db.max_job_age_days(), 7)

    def test_job_inside_window_is_logged(self):
        run_id = self.new_run()
        posted = (date.today() - timedelta(days=3)).isoformat()
        code, out = self.add_job(run_id, posted)
        self.assertEqual(code, 0)
        self.assertEqual(out["posted_date"], posted)

    def test_job_outside_window_is_refused(self):
        run_id = self.new_run()
        posted = (date.today() - timedelta(days=4)).isoformat()
        code, out = self.add_job(run_id, posted)
        self.assertEqual(code, 3)
        self.assertEqual(out["error"], "stale")
        conn = self.db.get_conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        conn.close()

    def test_wider_window_from_config_is_respected(self):
        (self.root / "config" / "search-config.md").write_text("- **Max job age (days):** 10\n")
        run_id = self.new_run()
        code, _ = self.add_job(run_id, (date.today() - timedelta(days=8)).isoformat())
        self.assertEqual(code, 0)

    def test_undated_job_is_logged_and_flagged(self):
        run_id = self.new_run()
        for token in (None, "", "unknown", "N/A"):
            code, out = self.add_job(run_id, token)
            self.assertEqual(code, 0)
            self.assertTrue(out["date_unknown"])
            self.assertIsNone(out["posted_date"])

    def test_undated_job_records_flag_in_timeline(self):
        run_id = self.new_run()
        self.add_job(run_id, None)
        conn = self.db.get_conn()
        msg = conn.execute("SELECT message FROM events WHERE event='job_found'").fetchone()["message"]
        conn.close()
        self.assertIn("date unknown", msg)

    def test_garbage_date_is_rejected(self):
        run_id = self.new_run()
        code, out = self.add_job(run_id, "last Tuesday")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "invalid_date")

    def test_datetime_string_uses_its_date(self):
        run_id = self.new_run()
        code, out = self.add_job(run_id, date.today().isoformat() + "T09:30:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(out["posted_date"], date.today().isoformat())


class TestPdfOnlyResumes(DbTestCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.new_run()
        _, self.job = self.add_job(self.run_id, date.today().isoformat())
        self.folder = self.root / "jobs" / "1-acme-co"
        self.folder.mkdir(parents=True)

    def save(self, name):
        return call(self.db.cmd_save_resume, id=self.job["id"],
                    job_folder="jobs/1-acme-co", resume_pdf_path=f"jobs/1-acme-co/{name}")

    def test_markdown_resume_is_refused(self):
        (self.folder / "resume.md").write_text("# Resume")
        code, out = self.save("resume.md")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "not_pdf")
        self.assertEqual(self.status_of("jobs", self.job["id"]), "found")

    def test_missing_pdf_is_refused(self):
        code, out = self.save("resume.pdf")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "missing_pdf")

    def test_file_named_pdf_but_not_a_pdf_is_refused(self):
        (self.folder / "resume.pdf").write_text("# actually markdown")
        code, out = self.save("resume.pdf")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "not_pdf")

    def test_real_pdf_is_accepted(self):
        (self.folder / "resume.pdf").write_bytes(b"%PDF-1.7\n")
        code, _ = self.save("resume.pdf")
        self.assertEqual(code, 0)
        self.assertEqual(self.status_of("jobs", self.job["id"]), "resume_ready")


class TestMigrate(DbTestCase):
    def test_migrate_upgrades_an_old_database(self):
        conn = self.db.get_conn()
        conn.execute("ALTER TABLE jobs ADD COLUMN resume_md_path TEXT")
        conn.execute("INSERT INTO settings (key, value) VALUES ('live_mode', 'off')")
        conn.execute("INSERT INTO runs (role) VALUES ('Old Run')")
        conn.commit()
        conn.close()

        code, out = call(self.db.cmd_migrate)
        self.assertEqual(code, 0)

        conn = self.db.get_conn()
        settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)")]
        conn.close()
        self.assertNotIn("live_mode", settings)
        self.assertEqual(settings.get("onboarded"), "yes")
        self.assertNotIn("resume_md_path", cols)

    def test_migrate_does_not_mark_an_empty_install_as_onboarded(self):
        call(self.db.cmd_migrate)
        conn = self.db.get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='onboarded'").fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_migrate_is_idempotent(self):
        call(self.db.cmd_migrate)
        code, _ = call(self.db.cmd_migrate)
        self.assertEqual(code, 0)


class TestSettings(DbTestCase):
    def test_roundtrip(self):
        call(self.db.cmd_set_setting, key="onboarded", value="yes")
        _, out = call(self.db.cmd_get_setting, key="onboarded")
        self.assertEqual(out["value"], "yes")
        call(self.db.cmd_set_setting, key="onboarded", value="no")
        _, out = call(self.db.cmd_get_setting, key="onboarded")
        self.assertEqual(out["value"], "no")


if __name__ == "__main__":
    unittest.main()
