---
name: resume-editor
description: >
  Tailor the user's base resume PDF to a specific matched job (reorder/emphasize relevant skills
  and experience, mirror the posting's keywords) without inventing anything, and save an
  ATS-friendly PDF in that job's folder. Use after job-finder has logged matches, when the user
  asks to "tailor my resume for job <id>" or "for all the jobs", or as the second stage of a run.
---

# Resume Editor

Stage 2 of the Job Hunter pipeline. Takes jobs already logged by `job-finder`
and produces a tailored resume **PDF** for each. Resumes are PDF only: the base
resume is a PDF and every tailored resume is a PDF -- no Markdown resume is
kept anywhere. Never fabricate experience, never modify
`resume-library/resume.pdf`, and never contact anyone or apply on the user's
behalf.

Run every command from the project root. Use `python`; on macOS use `python3`
if `python` isn't found.

## Step 0 -- Check setup

```bash
python scripts/check-setup.py
```

If `configured` is `false`, stop and load the `onboarding` skill instead.

## Step 1 -- Pick the job(s)

```bash
python scripts/db.py list-jobs --run-id <run-id> --status found
```

Tailor each `found` job the user asked for (all of them, one id, or a score
cut-off like "75 and above"). A job already at `resume_ready` is done; skip it
unless the user asks to redo it.

## Step 2 -- Load the resume-pdf-designer skill and get what an ATS needs

Every resume is built to pass applicant tracking systems (ATS), so load the
`resume-pdf-designer` skill now and do its **Step 1** once, before tailoring
the first job: it lists the details an ATS needs (full name, phone with country
code, City and Country, a month for every role, degree details) and has you ask
the user for anything missing, one question at a time. Answers are saved in
`resume-library/ats-profile.md`, so a batch of jobs asks at most once.

If you can't ask (an unattended run) and something required is missing, don't
guess: stop, say exactly what is needed, and leave the job at `found`.

## Step 3 -- Read the inputs and tailor

- Base resume text: `python scripts/pdf-tools.py extract resume-library/resume.pdf`,
  plus `resume-library/ats-profile.md` (it wins for contact details and dates).
- The job: `python scripts/db.py get-job --id <job-id>`, plus the posting itself
  (re-fetch its `url` for the full description).
- `config/author-profile.md` for voice and tone.

Rules, no exceptions:
- **Never invent** a skill, employer, title, date, or number that isn't in the
  base resume or the user's saved answers.
- Reorder and re-emphasize what is really there: lead with the most relevant
  experience and skills, and mirror the posting's own keywords only where they
  truthfully describe something already on the resume.
- Keep employment dates and job titles exactly as the candidate has them.
- Keep it to one page if it fits, two at most.

## Step 4 -- Make the PDF (ATS-safe)

Follow `resume-pdf-designer` Steps 2 to 4: write the tailored content as JSON in
your temp folder, build it with `scripts/resume-build.py`, and fix everything its
ATS report flags **before** going on. Slug = lowercase company name with
non-alphanumerics replaced by `-`.

```bash
python scripts/resume-build.py <temp>/resume.json jobs/<job-id>-<company-slug>/resume.pdf --keywords "<the posting's key skills, comma separated>"
```

Don't write your own HTML, and don't save a resume whose ATS report has
failures. Delete the temp JSON when done.

## Step 5 -- Save the job's files

In `jobs/<job-id>-<company-slug>/` keep only:
- `resume.pdf` -- the tailored resume (from Step 4)
- `job-posting.json` -- the listing data (company, title, url, location,
  posted date, description text if fetched)
- `match-notes.md` -- the fit reasoning from job-finder plus anything you
  noticed while tailoring

No resume in any other format goes in this folder.

## Step 6 -- Record it

```bash
python scripts/db.py save-resume \
  --id <job-id> \
  --job-folder "jobs/<job-id>-<company-slug>" \
  --resume-pdf-path "jobs/<job-id>-<company-slug>/resume.pdf"
```

`save-resume` refuses anything that isn't an existing PDF. If a job isn't worth
tailoring (the user only wants strong matches), skip it explicitly:

```bash
python scripts/db.py skip-job --id <job-id> --reason "<why>"
```

## Step 7 -- Close out the run

When every `found` job in the run is tailored or skipped:

```bash
python scripts/db.py mark-resume-ready --run-id <run-id>
python scripts/db.py mark-presented --run-id <run-id>
```

`presented` is the terminal state; the dashboard shows it on its next refresh.
Do not add a contact-extraction, cover-letter, or send step -- out of scope.
