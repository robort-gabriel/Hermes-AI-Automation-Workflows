#!/usr/bin/env python3
"""Read-only setup check. Prints one JSON object and always exits 0.

`configured` is true only when onboarding has been completed AND the base
resume PDF is present. Every skill and the profile persona run this first;
when it is false they must stop and run the onboarding skill instead of doing
normal work. Never writes anything.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "job-hunter.db"
RESUME_PATH = ROOT / "resume-library" / "resume.pdf"


def resume_is_pdf():
    try:
        with open(RESUME_PATH, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def is_onboarded():
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = 'onboarded'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return bool(row and row[0] == "yes")


def main():
    missing = []
    onboarded = False
    if not DB_PATH.exists():
        missing.append("database (run install.bat on Windows or install.command on Mac)")
    else:
        state = is_onboarded()
        if state is None:
            missing.append("database is unreadable (run: python scripts/db.py migrate)")
        else:
            onboarded = state
    resume_ok = resume_is_pdf()
    if not resume_ok:
        missing.append("resume-library/resume.pdf")
    if DB_PATH.exists() and not onboarded:
        missing.append("onboarding not completed")
    configured = not missing
    print(json.dumps({
        "configured": configured,
        "onboarded": onboarded,
        "resume_pdf": resume_ok,
        "ats_profile": (ROOT / "resume-library" / "ats-profile.md").is_file(),
        "missing": missing,
        "next": None if configured else
                "Stop normal work. Load the onboarding skill and complete it first.",
    }))


if __name__ == "__main__":
    main()
