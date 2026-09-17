---
name: resume-editor
description: >
  Tailor the user's base CV to a specific matched job listing (reorder/emphasize relevant skills
  and experience, mirror job-description keywords) without inventing any experience, and write the
  result into that job's folder. Use this after job-finder has logged matches, when the user asks
  to "tailor my resume for job <id>", or as the second stage of an automated run.
---

# Resume Editor

Stage 2 of the Job Hunter pipeline. Takes one job already logged by
`job-finder` and produces a tailored resume for it. Never fabricates
experience, never edits `resume-library/resume.md` (that file is read-only
input), and never contacts anyone or submits anything -- this pipeline stops
at "present," it does not apply.

**Project root:** Set the `PROJECT_ROOT` environment variable to the project
directory. Run every command from `$PROJECT_ROOT`.

## Step 1 -- Pick the job(s) to tailor

```bash
python3 scripts/db.py list-jobs --run-id <run-id> --status found
```

Process each `found` job for the run (or the single job the user named). A
job already at `resume_ready` has already been tailored -- skip it unless the
user explicitly asks to redo it.

## Step 2 -- Read inputs

- `resume-library/resume.md` -- the base CV. Read-only; never modify it.
- The job's `match_notes` (from `db.py get-job --id <job-id>`) and its posting
  content -- re-fetch `url` if you need the full description text.
- `config/author-profile.md` -- voice/tone guidance for how to phrase edits.

## Step 3 -- Tailor the resume

Rules, no exceptions:
- **Never invent** a skill, employer, title, or date that isn't in
  `resume-library/resume.md`.
- Reorder and re-emphasize existing, truthful content: bring the most
  relevant experience/skills to the top, mirror the job posting's own
  keywords where they truthfully describe something already on the CV.
- Keep employment dates and titles exactly as written in the base resume.
- Apply the voice/tone rules from `config/author-profile.md`.

Write the tailored resume as Markdown first.

## Step 4 -- Save output to the job's folder

Create `jobs/<job-id>-<company-slug>/` (slug = lowercase company name,
non-alphanumerics replaced with `-`) if it doesn't exist, and write:
- `job-posting.json` -- the original listing data (company, title, url,
  location, posted date, full description text if fetched).
- `resume.md` -- the tailored resume from Step 3.
- `match-notes.md` -- the fit reasoning from `job-finder` plus anything you
  noticed while tailoring.
- `resume.pdf` -- render `resume.md` to PDF in this same skill session (this
  is the one step that needs an HTML/PDF renderer; nothing under `scripts/`
  in this repo does PDF work, mirroring how this project's sibling,
  gumroad-pdf-factory, keeps PDF generation inside the agent session, not in
  committed scripts).

## Step 5 -- Record it in the database

```bash
python3 scripts/db.py save-resume \
  --id <job-id> \
  --job-folder "jobs/<job-id>-<company-slug>" \
  --resume-md-path "jobs/<job-id>-<company-slug>/resume.md" \
  --resume-pdf-path "jobs/<job-id>-<company-slug>/resume.pdf"
```

If a job's match is too weak to be worth tailoring at all (e.g. the user
wants only strong matches processed), skip it explicitly instead of leaving
it silently at `found` with no explanation:

```bash
python3 scripts/db.py skip-job --id <job-id> --reason "<why>"
```

## Step 6 -- Close out the run

Once every `found` job for the run has been tailored or skipped:

```bash
python3 scripts/db.py mark-resume-ready --run-id <run-id>
python3 scripts/db.py mark-presented --run-id <run-id>
```

`presented` is the terminal state -- the dashboard reflects it automatically
on next load. Do not add a contact-extraction, cover-letter, or send step;
that is explicitly out of scope for this pipeline.

## Notes for automation

Gate any autonomous/cron invocation on `python3 scripts/db.py get-setting
--key live_mode` being exactly `on`; otherwise exit silently and change
nothing. Process jobs from oldest run first, one run fully to completion
before starting another, so a scheduled run stays bounded.
