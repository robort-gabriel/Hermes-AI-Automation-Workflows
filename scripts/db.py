#!/usr/bin/env python3
"""CLI for the Job Hunter SQLite database.

Used by the job-finder and resume-editor Hermes skills to read and write
runs/jobs/events without any skill needing to write raw SQL. Run with --help
for the full command list. The dashboard server reads this same database
directly (read-only) -- it never calls this CLI with a mutating subcommand.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "job-hunter.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


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
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO jobs
           (run_id, company, title, url, location, source, posted_date,
            match_score, match_notes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'found')""",
        (args.run_id, args.company, args.title, args.url, args.location,
         args.source, args.posted_date, args.match_score, args.match_notes),
    )
    jid = cur.lastrowid
    _touch_run(conn, args.run_id, "job_found", f"{args.company}: {args.title}", job_id=jid)
    conn.commit()
    conn.close()
    print(json.dumps({"id": jid, "run_id": args.run_id, "status": "found"}))


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
    conn = get_conn()
    conn.execute(
        """UPDATE jobs SET status='resume_ready', job_folder=?, resume_md_path=?,
             resume_pdf_path=?, error_message=NULL WHERE id = ?""",
        (args.job_folder, args.resume_md_path, args.resume_pdf_path, args.id),
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

    a = sub.add_parser("start-run", help="Start a new search run")
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

    a = sub.add_parser("add-job", help="Log a job listing found for a run")
    a.add_argument("--run-id", type=int, required=True)
    a.add_argument("--company", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--location", default=None)
    a.add_argument("--source", default=None, help="'target-list' or 'search-verified'")
    a.add_argument("--posted-date", default=None)
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

    a = sub.add_parser("save-resume", help="Record a tailored resume for a job (status -> resume_ready)")
    a.add_argument("--id", type=int, required=True)
    a.add_argument("--job-folder", required=True)
    a.add_argument("--resume-md-path", required=True)
    a.add_argument("--resume-pdf-path", default=None)
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

    a = sub.add_parser("get-setting", help="Read one key from the settings table (e.g. live_mode)")
    a.add_argument("--key", required=True)
    a.set_defaults(func=cmd_get_setting)

    a = sub.add_parser("set-setting", help="Write one key in the settings table (e.g. live_mode)")
    a.add_argument("--key", required=True)
    a.add_argument("--value", required=True)
    a.set_defaults(func=cmd_set_setting)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
