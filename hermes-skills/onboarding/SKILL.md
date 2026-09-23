---
name: onboarding
description: >
  First-chat setup for Job Hunter. Walks a new user through adding their resume PDF, choosing the
  roles/seniority/location to search, and picking target companies, then marks setup complete. Use
  it whenever `scripts/check-setup.py` reports `configured: false`, or when the user asks to redo
  setup, change their resume, or "start over".
---

# Onboarding

Job Hunter does not do normal work (searching, tailoring resumes) until setup is
finished. This skill is how setup gets finished. The user may be a complete
beginner: use plain words, ask **one question at a time**, and keep each message
short and friendly.

Run every command from the project root. Use `python`; on macOS use `python3`
if `python` isn't found.

## Step 0 -- See what is missing

```bash
python scripts/check-setup.py
python scripts/pdf-tools.py check
```

`missing` tells you what is left. If `pdf-tools.py check` reports `"ok": false`,
tell the user what it says in `hints` (they may need Chrome or Edge, or
`pip install pypdf`) -- the resume steps won't work without a PDF reader and
a PDF maker.

## Step 1 -- Welcome

Say, in your own friendly words: Job Hunter finds fresh jobs (posted in the last
few days) straight from company career pages, matches them to your resume, and
makes a tailored resume PDF for each one. It never applies or emails anyone for
you. Setup takes about five minutes and only happens once.

## Step 2 -- Resume PDF

First look at `resume_pdf` in the `check-setup.py` output.

- **`true`:** a resume is already in place. Read it (see below), tell the user
  in one line what you found (name and most recent role), and ask whether to
  keep it or replace it with a different file. Don't ask for one they already
  have.
- **`false`:** ask for their resume **as a PDF**, either the full file path or
  dragging the file into the chat. Word documents must be exported to PDF first.

When you are given a path (it may come with quote marks; strip them), check it
exists and ends in `.pdf`, then copy it in (this is the one time a skill may
write to `resume-library/`):

```bash
python -c "import shutil,sys; shutil.copyfile(sys.argv[1], 'resume-library/resume.pdf')" "<their path>"
python scripts/pdf-tools.py extract resume-library/resume.pdf
```

If extract prints readable text, tell the user in one line what you read (name
and most recent role) so they can confirm it's the right file. If it errors (a
scan or photo has no text), explain that and ask for a text-based PDF.

## Step 3 -- Make the resume ready for ATS

Employers screen resumes with applicant tracking systems (ATS), so the tailored
resumes are built to pass them. That needs a few details up front. Load the
`resume-pdf-designer` skill and do its **Step 1**:

```bash
python scripts/pdf-tools.py ats-check resume-library/resume.pdf --base
```

Read the report and repeat only what it says (its `message` text); don't add
findings it didn't list. Then ask the user for whatever is missing, **one
question at a time, waiting for each answer**: full name, phone with country
code, City and Country, LinkedIn (optional), and a start and end month for each
job. Explain in a line why ("employers abroad can't dial a number without the
country code"). Save the answers to `resume-library/ats-profile.md` in the
format that skill shows. Never guess a detail, and quote the phone number or
dates only as they appear in the resume; if they don't know a month, note it
and move on.

Tell them the resume they gave you stays untouched: this only fills gaps for the
new ATS-friendly copies made for each job.

## Step 4 -- Roles

Ask what job titles they want to search for (one to three). Suggest ideas based
on the resume text. Then update `config/search-config.md`: replace the
`- **Role:**` lines with one line per title, exactly in that format.

## Step 5 -- Seniority and location

Ask their level (for example entry-level/junior, mid, senior) and whether they
want remote, hybrid, or a specific place. Update the `- **Seniority:**` and
`- **Location:**` lines in `config/search-config.md`.

## Step 6 -- Target companies

Show the companies currently in `config/target-companies.md` (if any) and ask
whether to keep them, replace them, or add more. Aim for at least three.

If they don't know which companies to pick, offer to look for companies hiring
for their roles and suggest a few. Only suggest companies whose **own careers
page** you have actually opened and confirmed.

Save each company in the existing format:

```
## Company Name
- Careers URL: https://...
- Industry: ...
- Notes: ...
```

Open every careers URL before saving it. If one doesn't load, tell the user and
ask for a better link rather than saving a dead one.

## Step 7 -- Freshness

Tell them the default: only jobs posted in the last **3 days** are kept, older
ones are left out. Ask if that is fine. If they want a different number, update
the `- **Max job age (days):**` line in `config/search-config.md`.

## Step 8 -- Finish

Only when the resume PDF is in place, its ATS gaps have been asked about (Step
3), and roles and companies are saved:

```bash
python scripts/db.py set-setting --key onboarded --value yes
python scripts/check-setup.py
```

Confirm `configured` is now `true`. Then give a short summary of what was set
(resume, roles, seniority, location, companies, freshness) and tell them what
to do next:

- Say **"Find jobs for me."** to run their first search.
- Say **"Start the dashboard."** to see results in the browser.
- The beginner's guide with copy-and-paste prompts is at
  `docs/Job-Hunter-User-Guide.pdf`.

## Rules

- Ask one thing at a time. Never dump every question in a single message.
- Only edit the three config files named above, `resume-library/resume.pdf` and
  `resume-library/ats-profile.md`. Ask before overwriting something the user
  already set.
- Do not start a job search, tailor resumes, or touch the database (other than
  the `onboarded` setting) until setup is complete.
- If the user asks something else mid-setup, answer briefly, then go back to
  the step you were on.
