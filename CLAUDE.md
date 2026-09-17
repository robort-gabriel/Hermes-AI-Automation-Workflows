# Job Hunter -- architecture reference

A Hermes AI profile owns this pipeline (skills + cron automation); this repo
holds only three things: a read-only dashboard, a SQLite DB + `db.py` CLI,
and version-controlled config. Sibling project: `gumroad-pdf-factory`, built
the same way -- see it for the pattern this follows, with one deliberate
departure (below).

## What it does

Research -> find -> tailor -> present. Nothing more. Given a role + job type,
the pipeline finds real job listings on companies' own websites, reads the
user's CV, matches jobs against it, tailors a resume per match, and shows
everything on a dashboard. It never extracts contacts, writes a cover letter,
or sends anything.

## The pipeline (never skip a stage)

```
new -> researching -> jobs_found -> resume_ready -> presented
```

`rejected` / `failed` are side exits. State is enforced by `runs.status`.
There is no human approval gate in the send sense, because nothing is ever
sent; `presented` is the terminal state, reached automatically once the last
job in a run has been tailored (or explicitly skipped).

- **Stage 1 -- research.** `job-finder` skill. Primary source:
  `config/target-companies.md` (visit each careers URL directly). Supplement:
  search restricted to individual company domains, filtered against the
  aggregator blocklist in `config/search-config.md`, then live-fetch-verified
  before logging. Logs matches via `python3 scripts/db.py add-job`. Ends with
  `mark-jobs-found`.
- **Stage 2 -- tailor.** `resume-editor` skill. Takes each `found` job for a
  run, tailors `resume-library/resume.md` against it (reorder/emphasize,
  mirror keywords, never invent experience), writes
  `jobs/<id>-<company-slug>/` (`job-posting.json`, `resume.md`, `resume.pdf`,
  `match-notes.md`), calls `python3 scripts/db.py save-resume`. Ends with
  `mark-resume-ready` then `mark-presented`.

## The one deliberate departure from `gumroad-pdf-factory`

That project's dashboard has approve/reject/publish buttons, an agent
wrapper, and a background monitor thread. **This one does not.**
`dashboard.html` here has no action buttons, no stage-trigger endpoints, no
"run" controls. `scripts/dashboard-server.py` exposes **GET-only** JSON
endpoints (`/api/runs`, `/api/runs/<id>`, `/api/jobs/<id>`, `/api/settings`)
and serves the static HTML -- nothing that mutates state, no subprocess
calls, no agent launching. All state transitions happen exclusively through
Hermes: chat-invoked skills and the cron automation. `db.py` is the only
writer, and the dashboard server never calls it with a mutating subcommand.

## Strict rules

1. **`db.py` is the only writer.** Every state transition goes through a
   `scripts/db.py` subcommand. Never run ad hoc SQL against
   `runs`/`jobs`/`events` from anywhere else -- it breaks `updated_at` and the
   event timeline.
2. **Folder is truth, DB is an index.** All generated per-job content lives
   in `jobs/<id>-<company-slug>/`. The DB never stores resume text, PDF
   bytes, or long-form copy -- only paths into that folder. If it's not in
   the folder, it does not exist.
3. **`resume-library/resume.md` is read-only input.** No skill run ever
   edits it. It is the single source of truth for the user's real experience
   -- the resume-editor skill never invents anything not present in it.
4. **Real listings only.** A job is logged only after a direct fetch confirms
   it's live on the company's own domain. Aggregator mirrors (LinkedIn,
   Indeed, Glassdoor, etc. -- see `config/search-config.md`) are filtered
   before a fetch is even attempted, never logged even if found.
5. **Gated by `live_mode`.** Autonomous (cron) work does nothing unless
   `python3 scripts/db.py get-setting --key live_mode` is exactly `on`. Not
   `on` -> exit silently, change nothing. That is a valid outcome.
6. **One run at a time in automation.** A scheduled run processes the oldest
   unfinished run to completion before starting another.
7. **No PII leakage into content.** Job-finder's `rationale`/`match_notes`
   describe evidence in the skill's own words; they don't need to quote
   people, same spirit as the sibling project's no-PII rule.
8. **Config is read-only admin data.** `config/target-companies.md`,
   `config/search-config.md`, `config/author-profile.md` define targets,
   search defaults, and voice. Follow them; don't rewrite them unless asked.
9. **`db.py init` is destructive** -- it deletes and recreates the DB. Never
   run it against a DB with real run history.
10. **On failure, mark and report.** A genuine research or tailoring failure
    gets `mark-run-failed` / `skip-job` with the exact reason. Don't guess,
    don't silently continue.
11. **Single-user system.** No accounts, no login, no per-user tables.
12. **Stay in scope.** This pipeline stops at "present." No contact
    extraction, no cover letter, no email/application send, ever -- adding
    any of those is a scope change the user must explicitly ask for.

## Hermes profile

A dedicated Hermes profile (`job-hunter`) owns automation: `terminal.cwd`
pointing at this repo, the two skills under `hermes-skills/` installed, and
one cron job (periodic job-finder run) gated by `live_mode` -- off by
default, same pattern as `gumroad-pdf-factory`. All mutation originates from
a Hermes skill run (chat-invoked or cron), never from the dashboard process.

`install.bat` / `install.command` (thin, platform-specific launchers) call
`scripts/setup-hermes-profile.py`, which creates/repairs that profile:
`terminal.cwd`, `hermes-skills/SOUL.md`, the two skill specs, the cron job,
`.env`, the DB, and a seeded `resume-library/resume.md` if missing. It's
idempotent -- re-running it only fills in what's missing and never
overwrites existing model config, resume content, or DB data. Keep
`hermes-skills/SOUL.md` and the two `SKILL.md` files as the single source of
truth; the setup script copies them into the profile, never the other way.
