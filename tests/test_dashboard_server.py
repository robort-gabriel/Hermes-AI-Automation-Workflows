"""Tests for scripts/dashboard-server.py, run against a throwaway project folder
and a real HTTP server on a random local port."""
import http.client
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = REAL_ROOT / "scripts" / "dashboard-server.py"


def load_server(root):
    spec = importlib.util.spec_from_file_location("dashboard_under_test", SERVER_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.DB_PATH = root / "data" / "job-hunter.db"
    mod.DASHBOARD_PATH = root / "dashboard.html"
    return mod


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "jobs" / "1-acme").mkdir(parents=True)
        (self.root / "assets" / "fonts").mkdir(parents=True)
        (self.root / "dashboard.html").write_text("<html><title>Job Hunter</title></html>")
        (self.root / "jobs" / "1-acme" / "resume.pdf").write_bytes(b"%PDF-1.4\n")
        (self.root / "assets" / "fonts" / "a.woff2").write_bytes(b"wOF2")
        (self.root / "assets" / "evil.py").write_text("print('no')")
        (self.root / "secret.txt").write_text("top secret")
        (self.root / ".env").write_text("PROJECT_ROOT=x")

        conn = sqlite3.connect(self.root / "data" / "job-hunter.db")
        conn.executescript((REAL_ROOT / "data" / "schema.sql").read_text())
        conn.commit()
        conn.close()

        self.mod = load_server(self.root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.mod.Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path)  # sent verbatim: no client-side ".." normalisation
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, body


class TestPage(ServerTestCase):
    def test_index_is_served_with_security_headers(self):
        status, h, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Job Hunter", body)
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "no-store")
        csp = h["content-security-policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("http", csp)  # no other origin is allowed

    def test_only_the_page_gets_a_csp(self):
        _, h, _ = self.get("/api/runs")
        self.assertNotIn("content-security-policy", h)


class TestStaticFiles(ServerTestCase):
    def test_font_is_served_with_type_and_long_cache(self):
        status, h, body = self.get("/assets/fonts/a.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(h["content-type"], "font/woff2")
        self.assertIn("max-age=86400", h["cache-control"])
        self.assertEqual(body, b"wOF2")

    def test_job_pdf_is_served_and_never_cached(self):
        status, h, _ = self.get("/jobs/1-acme/resume.pdf")
        self.assertEqual(status, 200)
        self.assertEqual(h["content-type"], "application/pdf")
        self.assertEqual(h["cache-control"], "no-store")

    def test_traversal_out_of_jobs_is_blocked(self):
        for path in ("/jobs/../secret.txt", "/jobs/../.env", "/jobs/../data/job-hunter.db",
                     "/jobs/1-acme/../../secret.txt", "/jobs/%2e%2e/secret.txt",
                     "/jobs/%2e%2e%2fsecret.txt", "/jobs/..%5csecret.txt", "/jobs/%2e%2e%5c.env",
                     "/jobs/1-acme/resume.pdf%00.txt", "/jobs/C:%5cWindows%5cwin.ini", "/jobs//etc/passwd"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"top secret", body)

    def test_traversal_out_of_assets_is_blocked(self):
        for path in ("/assets/../secret.txt", "/assets/fonts/../../.env", "/assets/../data/job-hunter.db"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"PROJECT_ROOT", body)

    def test_encoded_names_resolve(self):
        folder = self.root / "jobs" / "2-café co"
        folder.mkdir()
        (folder / "my resume.pdf").write_bytes(b"%PDF-1.4\n")
        status, h, _ = self.get("/jobs/2-caf%C3%A9%20co/my%20resume.pdf")
        self.assertEqual(status, 200)
        self.assertEqual(h["content-type"], "application/pdf")

    def test_unlisted_file_types_are_not_served(self):
        self.assertEqual(self.get("/assets/evil.py")[0], 404)
        (self.root / "jobs" / "1-acme" / "notes.exe").write_bytes(b"MZ")
        self.assertEqual(self.get("/jobs/1-acme/notes.exe")[0], 404)

    def test_odd_paths_do_not_crash_the_server(self):
        for path in ("//", "/jobs", "/assets", "/api", "/jobs/", "/nope", "/api/runs/abc", "/api/jobs/x"):
            status, _, _ = self.get(path)
            self.assertIn(status, (200, 404), path)
        self.assertEqual(self.get("/")[0], 200)  # still alive


class TestReadOnly(ServerTestCase):
    def test_mutating_methods_are_rejected(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.get("/api/runs", method=method)[0], 405, method)


class TestApi(ServerTestCase):
    def add_run(self, role):
        conn = sqlite3.connect(self.mod.DB_PATH)
        cur = conn.execute("INSERT INTO runs (role, created_at) VALUES (?, '2026-09-19 10:00:00')", (role,))
        conn.commit()
        conn.close()
        return cur.lastrowid

    def test_runs_created_in_the_same_second_are_newest_first(self):
        first, second = self.add_run("First"), self.add_run("Second")
        _, _, body = self.get("/api/runs")
        self.assertEqual([r["id"] for r in json.loads(body)], [second, first])

    def test_run_detail_includes_jobs_and_events(self):
        rid = self.add_run("Detail")
        status, _, body = self.get(f"/api/runs/{rid}")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual((data["jobs"], data["events"]), ([], []))
        self.assertEqual(self.get("/api/runs/999")[0], 404)

    def test_missing_database_gives_503_not_a_crash(self):
        self.mod.DB_PATH.unlink()
        self.assertEqual(self.get("/api/runs")[0], 503)


if __name__ == "__main__":
    unittest.main()
