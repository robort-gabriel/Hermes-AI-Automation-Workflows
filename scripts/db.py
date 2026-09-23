#!/usr/bin/env python3
"""CLI for the Job Hunter SQLite database.

Used by the job-finder and resume-editor Hermes skills to read and write
runs/jobs/events without any skill needing to write raw SQL. Run with --help
for the full command list. The dashboard server reads this same database
directly (read-only) -- it never calls this CLI with a mutating subcommand.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "job-hunter.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"
SEARCH_CONFIG_PATH = ROOT / "config" / "search-config.md"
DEFAULT_MAX_JOB_AGE_DAYS = 3
UNKNOWN_DATE_TOKENS = {"", "unknown", "n/a", "na", "none", "null", "-"}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


def fail(code, error, message):
    """Print a JSON error and exit non-zero, so a skill run sees exactly why
    a write was refused instead of a silent no-op."""
    print(json.dumps({"error": error, "message": message}))
    sys.exit(code)


def max_job_age_days():
    """Freshness window in days, read from config/search-config.md (the
    `Max job age (days)` line) so there is one place to change it."""
    try:
        text = SEARCH_CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_MAX_JOB_AGE_DAYS
    m = re.search(r"Max job age \(days\):\*\*\s*(\d+)", text)
    return int(m.group(1)) if m else DEFAULT_MAX_JOB_AGE_DAYS


def parse_posted_date(value):
    """Return a date, or None when the posting date is unknown/missing."""
    if value is None:
        return None
    v = value.strip()
    if v.lower() in UNKNOWN_DATE_TOKENS:
        return None
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except ValueError:
        fail(2, "invalid_date",
             f"Could not read posted date '{value}'. Use YYYY-MM-DD, or omit "
             "--posted-date if the date cannot be verified.")


def require_onboarded(conn):
    row = conn.execute("SELECT value FROM settings WHERE key = 'onboarded'").fetchone()
    if not row or row["value"] != "yes":
        conn.close()
        fail(4, "not_onboarded",
             "Setup is not finished. Load the onboarding skill and complete it "
             "before starting a run.")


def cmd_init(args):
    """Always resets: deletes any existing DB file first, then recreates it
    from schema.sql. Destructive by design -- this is the command a fresh
    setup or a reset runs, so it must not silently no-op against a DB that
    already has data in it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing {DB_PATH}")
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()
    print(f"Initialized {DB_PATH}")


def _touch_run(conn, run_id, event, message=None, job_id=None):
    conn.execute("UPDATE runs SET updated_at = datetime('now') WHERE id = ?", (run_id,))
    conn.execute(
        "INSERT INTO events (run_id, job_id, event, message) VALUES (?, ?, ?, ?)",
        (run_id, job_id, event, message),
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def cmd_start_run(args):
    conn = get_conn()
    require_onboarded(conn)
    cur = conn.execute(
        "INSERT INTO runs (role, seniority, location, target_companies, status) "
        "VALUES (?, ?, ?, ?, 'new')",
        (args.role, args.seniority, args.location, args.target_companies),
    )
    rid = cur.lastrowid
    _touch_run(conn, rid, "run_created", args.role)
    conn.commit()
    conn.close()
    print(json.dumps({"id": rid, "status": "new"}))


def cmd_mark_researching(args):
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status='researching', researching_at=datetime('now'), error_message=NULL WHERE id = ?",
        (args.run_id,),
    )
    _touch_run(conn, args.run_id, "researching", "Job search started")
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "researching"}))


def cmd_mark_jobs_found(args):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE run_id = ?", (args.run_id,)).fetchone()["n"]
    conn.execute(
        "UPDATE runs SET status='jobs_found', jobs_found_at=datetime('now'), error_message=NULL WHERE id = ?",
        (args.run_id,),
    )
    _touch_run(conn, args.run_id, "jobs_found", f"{n} job(s) logged")
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "jobs_found", "job_count": n}))


def cmd_mark_resume_ready(args):
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status='resume_ready', resume_ready_at=datetime('now'), error_message=NULL WHERE id = ?",
        (args.run_id,),
    )
    _touch_run(conn, args.run_id, "resume_ready", "Resumes tailored")
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "resume_ready"}))


def cmd_mark_presented(args):
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status='presented', presented_at=datetime('now'), error_message=NULL WHERE id = ?",
        (args.run_id,),
    )
    _touch_run(conn, args.run_id, "presented", "Run complete -- results on the dashboard")
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "presented"}))


def cmd_mark_run_rejected(args):
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status='rejected', rejected_at=datetime('now'), error_message=? WHERE id = ?",
        (args.reason, args.run_id),
    )
    _touch_run(conn, args.run_id, "rejected", args.reason)
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "rejected"}))


def cmd_mark_run_failed(args):
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET status='failed', error_message=? WHERE id = ?",
        (args.reason, args.run_id),
    )
    _touch_run(conn, args.run_id, "failed", args.reason)
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.run_id, "status": "failed"}))


def cmd_list_runs(args):
    conn = get_conn()
    if args.status:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status = ? ORDER BY created_at DESC", (args.status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    conn.close()
    print(json.dumps([row_to_dict(r) for r in rows], indent=2))


def cmd_get_run(args):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (args.id,)).fetchone()
    if not row:
        print(json.dumps({"error": "not found"}))
        conn.close()
        sys.exit(1)
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE run_id = ? ORDER BY match_score DESC, created_at ASC", (args.id,)
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM events WHERE run_id = ? ORDER BY created_at ASC", (args.id,)
    ).fetchall()
    conn.close()
    out = row_to_dict(row)
    out["jobs"] = [row_to_dict(j) for j in jobs]
    out["events"] = [row_to_dict(e) for e in events]
    print(json.dumps(out, indent=2))


def cmd_recent_titles(args):
    conn = get_conn()
    rows = conn.execute(
        "SELECT j.company, j.title, j.url, j.created_at FROM jobs j "
        "WHERE j.created_at >= datetime('now', ?) ORDER BY j.created_at DESC",
        (f"-{args.days} days",),
    ).fetchall()
    conn.close()
    print(json.dumps([row_to_dict(r) for r in rows], indent=2))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def cmd_add_job(args):
    posted = parse_posted_date(args.posted_date)
    limit = max_job_age_days()
    if posted is not None:
        age = (date.today() - posted).days
        if age > limit:
            fail(3, "stale",
                 f"Not logged: posted {age} days ago ({posted.isoformat()}), "
                 f"and only jobs from the last {limit} days are kept.")
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO jobs
           (run_id, company, title, url, location, source, posted_date,
            match_score, match_notes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'found')""",
        (args.run_id, args.company, args.title, args.url, args.location,
         args.source, posted.isoformat() if posted else None,
         args.match_score, args.match_notes),
    )
    jid = cur.lastrowid
    note = f"{args.company}: {args.title}"
    if posted is None:
        note += " (date unknown)"
    _touch_run(conn, args.run_id, "job_found", note, job_id=jid)
    conn.commit()
    conn.close()
    print(json.dumps({
        "id": jid, "run_id": args.run_id, "status": "found",
        "posted_date": posted.isoformat() if posted else None,
        "date_unknown": posted is None,
    }))


def cmd_get_job(args):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (args.id,)).fetchone()
    conn.close()
    if not row:
        print(json.dumps({"error": "not found"}))
        sys.exit(1)
    print(json.dumps(row_to_dict(row), indent=2))


def cmd_list_jobs(args):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE run_id = ?"
    params = [args.run_id]
    if args.status:
        query += " AND status = ?"
        params.append(args.status)
    query += " ORDER BY match_score DESC, created_at ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    print(json.dumps([row_to_dict(r) for r in rows], indent=2))


def cmd_save_resume(args):
    pdf = ROOT / args.resume_pdf_path
    if pdf.suffix.lower() != ".pdf":
        fail(2, "not_pdf", "Resumes are PDF only: --resume-pdf-path must end in .pdf")
    try:
        with open(pdf, "rb") as f:
            header = f.read(5)
    except OSError:
        fail(2, "missing_pdf", f"No file at {args.resume_pdf_path}. Render the PDF first.")
    if header != b"%PDF-":
        fail(2, "not_pdf", f"{args.resume_pdf_path} is not a valid PDF file.")
    conn = get_conn()
    conn.execute(
        """UPDATE jobs SET status='resume_ready', job_folder=?,
             resume_pdf_path=?, error_message=NULL WHERE id = ?""",
        (args.job_folder, args.resume_pdf_path, args.id),
    )
    row = conn.execute("SELECT run_id FROM jobs WHERE id = ?", (args.id,)).fetchone()
    if row:
        _touch_run(conn, row["run_id"], "resume_tailored", None, job_id=args.id)
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.id, "status": "resume_ready"}))


def cmd_skip_job(args):
    conn = get_conn()
    conn.execute("UPDATE jobs SET status='skipped', error_message=? WHERE id = ?", (args.reason, args.id))
    row = conn.execute("SELECT run_id FROM jobs WHERE id = ?", (args.id,)).fetchone()
    if row:
        _touch_run(conn, row["run_id"], "job_skipped", args.reason, job_id=args.id)
    conn.commit()
    conn.close()
    print(json.dumps({"id": args.id, "status": "skipped"}))


# ---------------------------------------------------------------------------
# Events / settings
# ---------------------------------------------------------------------------

def cmd_add_event(args):
    conn = get_conn()
    _touch_run(conn, args.run_id, args.event, args.message, job_id=args.job_id)
    conn.commit()
    conn.close()
    print(json.dumps({"run_id": args.run_id, "job_id": args.job_id, "event": args.event}))


def cmd_get_setting(args):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (args.key,)).fetchone()
    conn.close()
    print(json.dumps({"key": args.key, "value": row["value"] if row else None}))


def cmd_migrate(args):
    """Bring an existing database up to date. Idempotent and non-destructive:
    drops the retired resume_md_path column (best effort, older SQLite can't),
    removes the retired live_mode setting, and marks installs that already
    have run history as onboarded so they are not asked to set up again."""
    if not DB_PATH.exists():
        fail(2, "no_database", f"No database at {DB_PATH}. Run: python scripts/db.py init")
    conn = get_conn()
    changes = []
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)")]
    if "resume_md_path" in cols:
        try:
            conn.execute("ALTER TABLE jobs DROP COLUMN resume_md_path")
            changes.append("dropped jobs.resume_md_path")
        except sqlite3.OperationalError:
            changes.append("kept jobs.resume_md_path (this SQLite cannot drop columns; unused)")
    if conn.execute("DELETE FROM settings WHERE key = 'live_mode'").rowcount:
        changes.append("removed live_mode setting")
    has_flag = conn.execute("SELECT 1 FROM settings WHERE key = 'onboarded'").fetchone()
    has_runs = conn.execute("SELECT 1 FROM runs LIMIT 1").fetchone()
    if not has_flag and has_runs:
        conn.execute("INSERT INTO settings (key, value) VALUES ('onboarded', 'yes')")
        changes.append("marked onboarded (existing run history found)")
    conn.commit()
    conn.close()
    print(json.dumps({"migrated": True, "changes": changes}))


def cmd_set_setting(args):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (args.key, args.value),
    )
    conn.commit()
    conn.close()
    print(json.dumps({"key": args.key, "value": args.value}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Reset and recreate the database from schema.sql (deletes any existing DB file first)").set_defaults(func=cmd_init)

    sub.add_parser("migrate", help="Update an existing database to the current schema (safe to re-run)").set_defaults(func=cmd_migrate)

    a = sub.add_parser("start-run", help="Start a new search run (refused until onboarding is complete)")
    a.add_argument("--role", required=True)
    a.add_argument("--seniority", default=None)
    a.add_argument("--location", default=None)
    a.add_argument("--target-companies", default=None, help="Optional override list for this run only")
    a.set_defaults(func=cmd_start_run)

    a = sub.add_parser("mark-researching", help="Mark a run's job search as started")
    a.add_argument("--run-id", type=int, required=True)
    a.set_defaults(func=cmd_mark_researching)

    a = sub.add_parser("mark-jobs-found", help="Close the research stage for a run")
    a.add_argument("--run-id", type=int, required=True)
    a.set_defaults(func=cmd_mark_jobs_found)

    a = sub.add_parser("mark-resume-ready", help="Mark a run's resumes as tailored")
    a.add_argument("--run-id", type=int, required=True)
    a.set_defaults(func=cmd_mark_resume_ready)

    a = sub.add_parser("mark-presented", help="Close a run at its terminal state")
    a.add_argument("--run-id", type=int, required=True)
    a.set_defaults(func=cmd_mark_presented)

    a = sub.add_parser("mark-run-rejected", help="Reject a run (e.g. no qualifying jobs found)")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--reason", default=None)
    a.set_defaults(func=cmd_mark_run_rejected)

    a = sub.add_parser("mark-run-failed", help="Mark a run failed")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--reason", required=True)
    a.set_defaults(func=cmd_mark_run_failed)

    a = sub.add_parser("list-runs", help="List runs, optionally filtered by status")
    a.add_argument("--status", default=None)
    a.set_defaults(func=cmd_list_runs)

    a = sub.add_parser("get-run", help="Get one run with its jobs and event history")
    a.add_argument("--id", type=int, required=True)
    a.set_defaults(func=cmd_get_run)

    a = sub.add_parser("recent-titles", help="List job titles logged in the last N days (dupe check)")
    a.add_argument("--days", type=int, default=30)
    a.set_defaults(func=cmd_recent_titles)

    a = sub.add_parser("add-job", help="Log a job listing found for a run (refused if posted longer ago than the freshness window)")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--company", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--location", default=None)
    a.add_argument("--source", default=None, help="'target-list' or 'career-page-discovered'")
    a.add_argument("--posted-date", default=None, help="YYYY-MM-DD. Omit if the date cannot be verified; the job is then logged as 'date unknown'")
    a.add_argument("--match-score", type=int, default=None)
    a.add_argument("--match-notes", default=None)
    a.set_defaults(func=cmd_add_job)

    a = sub.add_parser("get-job", help="Get one job")
    a.add_argument("--id", type=int, required=True)
    a.set_defaults(func=cmd_get_job)

    a = sub.add_parser("list-jobs", help="List jobs for a run, optionally filtered by status")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--status", default=None)
    a.set_defaults(func=cmd_list_jobs)

    a = sub.add_parser("save-resume", help="Record a tailored resume PDF for a job (status -> resume_ready)")
    a.add_argument("--id", type=int, required=True)
    a.add_argument("--job-folder", required=True)
    a.add_argument("--resume-pdf-path", required=True, help="Project-relative path to the rendered PDF (must exist)")
    a.set_defaults(func=cmd_save_resume)

    a = sub.add_parser("skip-job", help="Mark a job skipped (e.g. match too weak to tailor a resume)")
    a.add_argument("--id", type=int, required=True)
    a.add_argument("--reason", default=None)
    a.set_defaults(func=cmd_skip_job)

    a = sub.add_parser("add-event", help="Append a free-form event to a run's timeline")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--job-id", type=int, default=None)
    a.add_argument("--event", required=True)
    a.add_argument("--message", default=None)
    a.set_defaults(func=cmd_add_event)

    a = sub.add_parser("get-setting", help="Read one key from the settings table (e.g. onboarded)")
    a.add_argument("--key", required=True)
    a.set_defaults(func=cmd_get_setting)

    a = sub.add_parser("set-setting", help="Write one key in the settings table (e.g. onboarded)")
    a.add_argument("--key", required=True)
    a.add_argument("--value", required=True)
    a.set_defaults(func=cmd_set_setting)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
