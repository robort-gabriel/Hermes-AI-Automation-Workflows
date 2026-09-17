#!/usr/bin/env python3
"""Read-only local dashboard server for Job Hunter.

Serves dashboard.html and a handful of GET-only JSON endpoints backed
directly by the SQLite database. This server never mutates state: there is
no /api/find, /api/tailor, or any other action endpoint, no subprocess calls,
and no background pipeline thread. Every state transition (run/job status)
happens exclusively through `scripts/db.py`, called only by Hermes skills
(chat-invoked or cron) -- never from here. Any non-GET request is rejected.
"""
import json
import sqlite3
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "job-hunter.db"
DASHBOARD_PATH = ROOT / "dashboard.html"
PORT = 5301


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def get_conn():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_runs(status=None):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        run = row_to_dict(r)
        counts = conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN status='resume_ready' THEN 1 ELSE 0 END) AS ready "
            "FROM jobs WHERE run_id = ?",
            (run["id"],),
        ).fetchone()
        run["job_count"] = counts["n"] or 0
        run["resume_ready_count"] = counts["ready"] or 0
        out.append(run)
    conn.close()
    return out


def fetch_run(run_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        conn.close()
        return None
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE run_id = ? ORDER BY match_score DESC, created_at ASC", (run_id,)
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM events WHERE run_id = ? ORDER BY created_at ASC", (run_id,)
    ).fetchall()
    conn.close()
    out = row_to_dict(row)
    out["jobs"] = [row_to_dict(j) for j in jobs]
    out["events"] = [row_to_dict(e) for e in events]
    return out


def fetch_job(job_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row_to_dict(row) if row else None


def fetch_setting(key):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._json({"error": "not found"}, status=404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if parsed.path in ("/", "/index.html"):
                body = DASHBOARD_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parts == ["api", "runs"]:
                status = (qs.get("status") or [None])[0]
                self._json(fetch_runs(status))
                return

            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                run_id = int(parts[2])
                run = fetch_run(run_id)
                self._json(run) if run else self._not_found()
                return

            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job_id = int(parts[2])
                job = fetch_job(job_id)
                self._json(job) if job else self._not_found()
                return

            if parts == ["api", "settings"]:
                self._json({"live_mode": fetch_setting("live_mode") or "off"})
                return

            self._not_found()
        except sqlite3.OperationalError as e:
            self._json({"error": f"database not ready: {e}"}, status=503)
        except (ValueError, FileNotFoundError):
            self._not_found()

    def do_POST(self):
        self._json({"error": "read-only dashboard: no mutating endpoints"}, status=405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} {fmt % args}")


def main():
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH} -- run: python3 scripts/db.py init")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Job Hunter dashboard (read-only) at http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
