#!/usr/bin/env python3
"""Read-only local dashboard server for Job Hunter.

Serves dashboard.html, its bundled fonts (assets/), the generated files under
jobs/ (tailored resume PDFs), and a handful of GET-only JSON endpoints backed
directly by the SQLite database. This server never mutates state: there is
no /api/find, /api/tailor, or any other action endpoint, no subprocess calls,
and no background pipeline thread. Every state transition (run/job status)
happens exclusively through `scripts/db.py`, called only by Hermes skills
(chat-invoked or cron) -- never from here. Any non-GET request is rejected.
"""
import json
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "job-hunter.db"
DASHBOARD_PATH = ROOT / "dashboard.html"
PORT = 5301

JOB_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
ASSET_TYPES = {
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
# The page is one self-contained file: inline script/style, local fonts, and
# fetches only to itself. Anything else (other origins, framing) is refused.
PAGE_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


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
            "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC, id DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC, id DESC").fetchall()
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


def resolve_inside(base, parts):
    """Resolve `parts` under `base`, or None if the result would land outside
    it. A raw base.joinpath(*parts) lets /jobs/../../.env or an absolute-looking
    segment escape the folder and read anything the process can access."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    if target.is_relative_to(base) and target.is_file():
        return target
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type, cache="no-store", csp=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header("Content-Security-Policy", PAGE_CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload, indent=2).encode("utf-8"), "application/json")

    def _not_found(self):
        self._json({"error": "not found"}, status=404)

    def _serve_static(self, base, parts, types, cache):
        path = resolve_inside(base, parts)
        if path is None:
            return False
        content_type = types.get(path.suffix.lower())
        if content_type is None:
            return False
        self._send(200, path.read_bytes(), content_type, cache=cache)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        # Decode each segment so names with spaces or accents resolve. Traversal
        # tricks (%2e%2e, %5c, %2f) decode into real path parts and are then
        # caught by resolve_inside's containment check.
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if parsed.path in ("/", "/index.html"):
                self._send(200, DASHBOARD_PATH.read_bytes(), "text/html; charset=utf-8", csp=True)
                return

            if parts == ["api", "runs"]:
                status = (qs.get("status") or [None])[0]
                self._json(fetch_runs(status))
                return

            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                run = fetch_run(int(parts[2]))
                self._json(run) if run else self._not_found()
                return

            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job = fetch_job(int(parts[2]))
                self._json(job) if job else self._not_found()
                return

            if len(parts) >= 2 and parts[0] == "jobs":
                if self._serve_static(ROOT / "jobs", parts[1:], JOB_FILE_TYPES, "no-store"):
                    return

            if len(parts) >= 2 and parts[0] == "assets":
                if self._serve_static(ROOT / "assets", parts[1:], ASSET_TYPES, "public, max-age=86400"):
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
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"Job Hunter dashboard (read-only) at http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
