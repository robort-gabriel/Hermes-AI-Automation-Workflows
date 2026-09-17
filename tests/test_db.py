"""Smoke tests for scripts/db.py, run against a throwaway DB file so the
real job-hunter.db is never touched."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_SCRIPT = ROOT / "scripts" / "db.py"


def run_db(*args, env):
    result = subprocess.run(
        [sys.executable, str(DB_SCRIPT), *args],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"db.py {args} failed: {result.stderr}")
    return json.loads(result.stdout)


class TestDbPipeline(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"
        self.env = dict(os.environ)
        # db.py resolves DB_PATH relative to its own file location, so we
        # patch it via monkeypatching the module in-process instead of
        # relying on an env var the script doesn't read.
        import importlib.util
        spec = importlib.util.spec_from_file_location("db", DB_SCRIPT)
        self.db = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.db)
        self.db.DB_PATH = self.db_path

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _init(self):
        self.db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = self.db.get_conn()
        conn.executescript(self.db.SCHEMA_PATH.read_text())
        conn.commit()
        conn.close()

    def test_full_run_lifecycle(self):
        self._init()

        class Args:
            pass

        a = Args()
        a.role, a.seniority, a.location, a.target_companies = "Backend Engineer", "Senior", "Remote", None
        self.db.cmd_start_run(a)

        conn = self.db.get_conn()
        run_id = conn.execute("SELECT id FROM runs").fetchone()["id"]
        self.assertEqual(
            conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"],
            "new",
        )
        conn.close()

        a2 = Args()
        a2.run_id = run_id
        self.db.cmd_mark_researching(a2)

        a3 = Args()
        a3.run_id, a3.company, a3.title, a3.url = run_id, "Acme Co", "Backend Engineer", "https://acme.example/careers/1"
        a3.location, a3.source, a3.posted_date = "Remote", "target-list", "2026-09-01"
        a3.match_score, a3.match_notes = 85, "Strong overlap"
        self.db.cmd_add_job(a3)

        conn = self.db.get_conn()
        job = conn.execute("SELECT * FROM jobs WHERE run_id=?", (run_id,)).fetchone()
        self.assertEqual(job["status"], "found")
        job_id = job["id"]
        conn.close()

        self.db.cmd_mark_jobs_found(a2)

        a4 = Args()
        a4.id, a4.job_folder = job_id, f"jobs/{job_id}-acme-co"
        a4.resume_md_path = f"jobs/{job_id}-acme-co/resume.md"
        a4.resume_pdf_path = f"jobs/{job_id}-acme-co/resume.pdf"
        self.db.cmd_save_resume(a4)

        self.db.cmd_mark_resume_ready(a2)
        self.db.cmd_mark_presented(a2)

        conn = self.db.get_conn()
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(run["status"], "presented")
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(job["status"], "resume_ready")
        events = conn.execute("SELECT event FROM events WHERE run_id=?", (run_id,)).fetchall()
        event_names = [e["event"] for e in events]
        for expected in ["run_created", "researching", "job_found", "jobs_found", "resume_tailored", "resume_ready", "presented"]:
            self.assertIn(expected, event_names)
        conn.close()

    def test_settings_roundtrip(self):
        self._init()

        class Args:
            pass

        a = Args()
        a.key, a.value = "live_mode", "on"
        self.db.cmd_set_setting(a)

        conn = self.db.get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='live_mode'").fetchone()
        self.assertEqual(row["value"], "on")
        conn.close()


if __name__ == "__main__":
    unittest.main()
