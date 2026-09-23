---
name: job-finder
description: >
  Find real, recently posted job listings on companies' own career pages (never job boards) that
  match the user's role/seniority/location, score them against the user's resume PDF, and log them
  to the Job Hunter database. Use this when the user asks to "find jobs", "run the job finder",
  "what's open at my target companies", or when the daily search runs.
---

# Job Finder

Stage 1 of the Job Hunter pipeline. Finds and scores real job listings and logs
them to the shared database. It does not tailor a resume or contact anyone --
that is `resume-editor`'s job, and this pipeline has no apply/send stage.

Run every command from the project root (`PROJECT_ROOT` in the project's
`.env`). Use `python`; on macOS use `python3` if `python` isn't found.
The database is written only through `scripts/db.py` -- never raw SQL.

## Step 0 -- Check setup

```bash
python scripts/check-setup.py
```

If `configured` is `false`, **stop**. Do not search. Load the `onboarding`
skill and finish it first. (`db.py start-run` refuses to run until onboarding
is complete, so skipping this only wastes a turn.)

## Step 1 -- Start the run(s)

If the user named a role/seniority/location in chat, use those for one run.

Otherwise (including every unattended/cron run), read `config/search-config.md`.
Each `- **Role:**` line is one search track: start one separate run per Role
line and take each one through every step below to completion (Step 8) before
starting the next. Don't merge roles into one run.

```bash
python scripts/db.py start-run --role "<role>" --seniority "<seniority>" --location "<location>"
python scripts/db.py mark-researching --run-id <run-id>
```

`start-run` prints the `id` -- that is `<run-id>` below.

## Step 2 -- Note the freshness window and recent titles

Read `Max job age (days)` from `config/search-config.md` (default 3) and work
out today's date. **Only jobs posted within that many days count.**

```bash
python scripts/db.py recent-titles --days 30
```

Don't log a company + title already found in the last 30 days.

## Step 3 -- Read the resume

```bash
python scripts/pdf-tools.py extract resume-library/resume.pdf
```

This is the only source for match scoring. Never assume skills or experience
that aren't in it. If it prints an error, tell the user (a scanned/photo PDF
has no readable text) and stop the run with `mark-run-failed`.

## Step 4 -- Find listings on company career pages

Jobs come from company career pages, in this order:

1. **Target companies.** For each `## Company` in `config/target-companies.md`,
   open its `Careers URL` directly and read the live listings. Careers pages
   hosted by the company's hiring system (Greenhouse, Lever, Ashby, Workable,
   BambooHR and similar) are the company's own postings and count.
2. **More companies' own career pages.** If the target list yields few
   matches, search for other companies hiring for the role, then go to each
   company's own careers (or hiring-system) page and read the listing there.
   Log source `career-page-discovered` for these.
3. **Never a job board.** Skip every aggregator listed in
   `config/search-config.md` (LinkedIn, Indeed, Glassdoor, ...). A board result
   is only a lead: use it to find the company's own careers page, and if that
   page is missing or doesn't show the listing, don't log the job.

Fetch each listing page itself and confirm it shows the role as open. A
listing that fails that check is not logged, with no exceptions.

## Step 5 -- Check freshness

For each listing, find its **posted/published date** on the page or in the
hiring system's data (for example a "Posted" line, `datePosted` in the page's
structured data, or a published-at field). Convert relative dates ("2 days
ago") to a real date using today's date. Use the *posted* date, not an
"updated" or "last modified" date.

- Posted within the window -> keep it.
- Posted longer ago than the window -> **discard it**. Do not log it.
- No date can be verified anywhere -> keep it but omit `--posted-date`; it is
  logged as "date unknown" and flagged on the dashboard.

## Step 6 -- Score each match

Judge fit against the resume text:
- **match_score** (0-100): skills/keyword overlap and seniority fit. Be honest;
  a low score is a valid, useful result.
- **match_notes**: 1-3 sentences on why it fits (or barely fits), naming the
  specific overlapping skills and any seniority mismatch.

## Step 7 -- Log each match

```bash
python scripts/db.py add-job \
  --run-id <run-id> \
  --company "<company>" \
  --title "<job title>" \
  --url "<posting URL on the company's own careers page>" \
  --location "<location>" \
  --source "target-list" \
  --posted-date "<YYYY-MM-DD>" \
  --match-score <0-100> \
  --match-notes "<why it fits>"
```

Use `--source "career-page-discovered"` for Step 4.2 finds. Leave out
`--posted-date` only when the date truly can't be verified.

If `add-job` exits non-zero it did **not** log the job: exit 3 means it is older
than the window (skip it), exit 2 means a bad date format (fix it to
YYYY-MM-DD or omit it).

## Step 8 -- Close the research stage

```bash
python scripts/db.py mark-jobs-found --run-id <run-id>
```

If nothing qualified (no listings, or none within the window), reject the run
instead of forcing weak matches:

```bash
python scripts/db.py mark-run-rejected --run-id <run-id> --reason "No qualifying listings posted within the last <N> days"
```

## Notes

This skill only creates runs and logs jobs. It never tailors a resume (that's
`resume-editor`, run separately) and never marks a run presented. On a genuine
failure, `mark-run-failed` with the exact reason and move on -- don't guess.
