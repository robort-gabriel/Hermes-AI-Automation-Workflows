---
name: job-finder
description: >
  Find real job listings on companies' own career pages (never generic third-party boards) that
  match the user's role/seniority/location preferences, score them against the user's CV, and log
  them to the Job Hunter database. Use this when running the daily job search or when the user asks
  to "find jobs", "run the job finder", or "what's open at my target companies".
---

# Job Finder

Stage 1 of the Job Hunter pipeline. Finds and scores real job listings, and logs
them to the shared database. Does not tailor a resume or touch any external
account -- that is `resume-editor`'s job, and there is no publish/apply stage
at all in this pipeline.

**Project root:** Set the `PROJECT_ROOT` environment variable to the project
directory (e.g. read it from `.env`). Run every command from `$PROJECT_ROOT`.

**Database:** `$PROJECT_ROOT/data/job-hunter.db` (SQLite), written only through
`scripts/db.py`. Never run ad hoc SQL against `runs`/`jobs`/`events` from
anywhere else -- it breaks `updated_at` and the event timeline.

## Step 1 -- Start the run

If the user gave a role/seniority/location in chat, use those for one run.

Otherwise (including every unattended/cron invocation), `config/search-config.md`
lists **two** role defaults (currently "AI Automation Engineer" and "Macro
Analyst") -- start one separate run per listed role default, and take each
run through every step below to completion (Step 7) before starting the
next one. Don't merge both roles into a single run.

```bash
python3 scripts/db.py start-run --role "<role>" --seniority "<seniority>" --location "<location>"
```

Note the returned `id` -- this is `<run-id>` for every command below.

```bash
python3 scripts/db.py mark-researching --run-id <run-id>
```

## Step 2 -- Check for recent duplicates

```bash
python3 scripts/db.py recent-titles --days 30
```

Keep this list in mind so you don't log a near-duplicate of a company+title
already found in the last 30 days.

## Step 3 -- Read the CV

Read `resume-library/resume.md`. This is the only source used for match
scoring in Step 5 -- never invent or assume skills/experience not present in
it.

## Step 4 -- Find listings

**Primary source -- `config/target-companies.md`:** For each `## Company`
entry, visit its `Careers URL` directly and parse the live listings on the
page. This is the preferred source because it's a real, current page on the
company's own domain -- trust it over search results.

**Supplementary source -- search-then-verify:** Only to fill gaps the target
list doesn't cover. Follow `config/search-config.md`:
1. Search restricted to individual company domains (`site:<company>.com`
   combined with the role), never a bare/general query.
2. Filter out every result on an aggregator domain listed in
   `config/search-config.md` (LinkedIn, Indeed, Glassdoor, etc.) -- if a
   result isn't on the company's own domain, discard it before fetching.
3. Fetch the page directly to confirm the listing is genuinely live (not a
   404, not stale, not an aggregator mirror) before treating it as a match.

A listing that fails the live-fetch check does not get logged, full stop --
no exceptions for "it looked real."

## Step 5 -- Score each match

For each surviving listing, judge fit against `resume-library/resume.md`:
- **match_score** (0-100): weight skills/keyword overlap and seniority fit.
  Be honest -- a low score is a valid, useful outcome; don't inflate to make
  the run look more productive.
- **match_notes**: 1-3 sentences on why it fits (or barely fits), naming the
  specific overlapping skills/keywords and any seniority mismatch.

## Step 6 -- Log each match

```bash
python3 scripts/db.py add-job \
  --run-id <run-id> \
  --company "<company>" \
  --title "<job title>" \
  --url "<posting URL, on the company's own domain>" \
  --location "<location>" \
  --source "target-list" \
  --posted-date "<YYYY-MM-DD or as listed>" \
  --match-score <0-100> \
  --match-notes "<why it fits>"
```

Use `--source "search-verified"` for listings found via Step 4's
supplementary search instead of the target list.

## Step 7 -- Close the research stage

```bash
python3 scripts/db.py mark-jobs-found --run-id <run-id>
```

If nothing qualified at all (no listings found, or none worth logging), reject
the run instead of forcing weak matches in just to have something to show:

```bash
python3 scripts/db.py mark-run-rejected --run-id <run-id> --reason "No qualifying listings found this run"
```

## Notes for automation

This skill only ever creates a run and logs jobs against it -- it never
tailors a resume (that's `resume-editor`, invoked separately after this skill
finishes) and never presents the run (that's the final `mark-presented` call
the orchestrating cron prompt or chat flow makes once resumes are ready). Gate
any autonomous/cron invocation on `python3 scripts/db.py get-setting --key
live_mode` being exactly `on`; otherwise exit silently and change nothing.
