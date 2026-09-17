# Job Hunter

Finds real job listings on companies' own career pages, matches them against
your CV, and tailors a resume per match -- then shows everything on a local,
read-only dashboard. It stops there: no contact extraction, no cover letter,
no application send. Purely research -> find -> tailor -> present.

The pipeline itself (the job-finder and resume-editor skills, plus the daily
cron run) lives in a Hermes AI profile, not in this repo. This repo holds the
dashboard, the SQLite database + `db.py` CLI, and version-controlled config.
See [CLAUDE.md](CLAUDE.md) for the full architecture.

## Requirements

- Python 3, stdlib only -- nothing under `scripts/` imports a third-party
  package, so there's nothing to `pip install`.
- A free local port, **5301** (the dashboard binds to `127.0.0.1` only).
- Hermes AI installed, to actually run the job-finder / resume-editor skills.

## Setup

1. **Add your CV.** Replace the placeholder in `resume-library/resume.md`
   with your real resume. See `resume-library/README.md`.
2. **Set your targets.** Edit `config/target-companies.md` with real company
   names + careers URLs, and fill in your role/seniority/location defaults in
   `config/search-config.md`.
3. **Initialize the database:**
   ```powershell
   python scripts\db.py init
   ```
   Idempotent to re-run, but destructive -- it deletes any existing DB first.
4. **Create `.env`** from `.env.example` and set `PROJECT_ROOT` to this
   folder's full path. `live_mode` stays `off` until you've verified a manual
   run end to end.
5. **Run the dashboard:**
   ```powershell
   python scripts\dashboard-server.py
   ```
   Open **http://127.0.0.1:5301/**.

## Running a search

All pipeline work happens through Hermes, not the dashboard:

- In chat: "find jobs" (optionally with a role/seniority/location), which
  loads the `job-finder` skill, then "tailor my resume for job `<id>`" (or
  "for all of them"), which loads `resume-editor`.
- Once cron is wired up and `live_mode` is `on`, the daily job-finder run
  happens automatically; resume tailoring for anything it finds still needs
  either a second cron job or a chat trigger, per your Hermes profile setup.

The dashboard just reflects whatever state is in the database -- reload it or
wait for the 15s auto-refresh to see new runs/jobs appear.

## Running tests

```powershell
python -m unittest discover -s tests
```

## What's NOT included

- No demo/dummy data -- the pipeline starts empty and fills up from your own
  runs.
- The example entries in `config/target-companies.md` are placeholders --
  replace them with your own.
- No approve/publish/send step of any kind, by design -- see
  [CLAUDE.md](CLAUDE.md) for why the dashboard is read-only.
