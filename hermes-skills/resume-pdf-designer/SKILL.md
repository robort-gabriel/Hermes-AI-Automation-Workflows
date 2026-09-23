---
name: resume-pdf-designer
description: >
  Make a resume PDF that passes applicant tracking systems (ATS): collect any missing details from
  the user, write ATS-safe content, build a clean single-column PDF, and verify it by reading it back
  like an ATS does. Adapted from the pdf-designer skill for resumes. Use it whenever a resume PDF is
  produced (from resume-editor, or when the user asks to "make my resume ATS friendly", "fix my
  resume", or "format my resume").
---

# Resume PDF Designer (ATS edition)

Adapted from the `pdf-designer` skill (WeasyPrint HTML to PDF, clean type, restrained colour). That
skill makes designed guides with covers, cards, icons and columns. A resume needs the opposite:
what an applicant tracking system can read without guessing. So the design is fixed in code
(`scripts/resume-build.py`) and you supply the words. **Do not write your own HTML or CSS for a
resume.**

The aim is a PDF that **passes on the first build**, not one that gets fixed later. That means
knowing the candidate's details before you tailor, so ask for what is missing (Step 1).

Run every command from the project root. Use `python`; on macOS use `python3` if `python` isn't
found. Write scratch files (the resume JSON) to the system temp folder and nowhere else. **Never put
a resume JSON, or any copy of a resume, in the project folder**: it holds the user's personal details.
Delete the scratch file when you are done.

## Step 1 -- Get what an ATS needs (ask, don't guess)

Read the base resume: `python scripts/pdf-tools.py extract resume-library/resume.pdf`, then read
`resume-library/ats-profile.md` if it exists (details the user gave earlier; it wins over the PDF).
Check the base resume's content: `python scripts/pdf-tools.py ats-check resume-library/resume.pdf --base`.

**Report the check honestly.** Tell the user only what the report says: use its `pass`, `failures`
and `warnings` and their `message` text. Don't add problems it didn't list, don't call something a
failure when it is a warning, and don't quote details (a phone number, a date, a count) that aren't in
the report or in the resume text you extracted. If you're unsure of a value, read the resume again.

You need all of these before building. If one is missing or unclear, **ask the user one question,
in plain words, then wait for the answer** before the next. Save each answer to
`resume-library/ats-profile.md` so you never ask twice.

| Needed | Why an ATS cares | Ask like this |
| --- | --- | --- |
| Full name | The first line is read as the candidate's name | "What name should be on your resumes?" |
| Email | The one field every ATS requires | (only if missing) |
| Phone **with country code** | Foreign employers can't dial a local number | "What's your phone number with the country code, like +234...?" |
| Location as City, Country | ATS filters search by location | "Which city and country should I put?" |
| LinkedIn address | Recruiters look for it | "Do you have a LinkedIn address to include?" |
| Month and year for every job (start and end, or Present) | Experience is calculated from months | "Which month did you start at <employer>?" |
| Exact job titles and employer names | Titles are matched against the posting | (ask if vague or missing) |
| Degree spelled out, school, graduation month and year | Degree filters | (ask if missing) |

Never invent or estimate a fact. If the user doesn't know a month, use the year only and tell them
the ATS check will flag it. Save answers in this form (one per line, private, git-ignored):

```
Full name: Sam Doe
Phone: +234 801 234 5678
Location: Lagos, Nigeria
LinkedIn: linkedin.com/in/samdoe
Dates: Acme Ltd | Start: Mar 2023 | End: Present
```

## Step 2 -- Write the content for the ATS and the job

Only from the base resume and the user's saved answers. Never add a skill, employer, title, date or
number that isn't there.

- **Headline** under the name: the job's exact title only if it truthfully describes the candidate;
  otherwise the candidate's real title.
- **Mirror the posting's words** where they truthfully describe real experience. Use the posting's
  exact spelling of tools and skills ("Amazon Web Services (AWS)", not just "AWS", when the
  posting spells it out). Put the most relevant skills first.
- **Skills:** grouped lines of plain terms, real tool and skill names, the acronym and its long form
  once. No ratings, bars or levels.
- **Bullets:** start with a verb, one idea each, under two lines, with a number where the resume has
  one. Most relevant bullets first, older or unrelated ones trimmed.
- **Standard words for sections:** Professional Summary, Skills, Experience, Projects, Education,
  Certifications. The builder writes these headings; don't rename them.
- **Dates:** `Jan 2024 - Present` style everywhere, month and year.
- **Plain characters only:** hyphens, not em or en dashes; no emoji, symbols or icons; no pronouns
  ("I", "my").
- **Length:** one page if it fits. Two at most, and the second page must be well used. If it runs
  over, cut the least relevant content. Don't shrink the text.

## Step 3 -- Build

Write the resume as JSON to a temp file, then:

```bash
python scripts/resume-build.py <temp>/resume.json jobs/<id>-<slug>/resume.pdf --keywords "kw1,kw2,kw3"
```

Pass the posting's key skills and tools as `--keywords` so the report shows which ones are missing.

JSON shape (only `name`, `contact`, `skills`, `education` and one of `experience` / `projects` are
required; leave out what doesn't apply):

```json
{
  "name": "Sam Doe",
  "headline": "Data Analyst",
  "contact": {"email": "sam@example.com", "phone": "+234 801 234 5678", "location": "Lagos, Nigeria",
              "linkedin": "linkedin.com/in/samdoe", "github": "github.com/samdoe"},
  "summary": "Two or three sentences.",
  "skills": [{"label": "Data", "items": ["SQL", "Python", "Power BI"]}],
  "experience": [{"title": "Data Analyst", "company": "Acme Ltd", "location": "Lagos, Nigeria",
                  "start": "Mar 2023", "end": "Present", "bullets": ["Built ..."]}],
  "projects": [{"name": "Sales Dashboard", "stack": "SQL, Power BI", "bullets": ["Built ..."]}],
  "education": [{"degree": "Bachelor of Science in Statistics", "school": "University of Lagos",
                 "location": "Lagos, Nigeria", "end": "Jul 2022"}],
  "certifications": [{"name": "Google Data Analytics Certificate", "issuer": "Google", "year": "2023"}],
  "section_order": ["summary", "skills", "experience", "projects", "education", "certifications"],
  "page": "A4"
}
```

- `page`: `A4`, or `Letter` when the job is in the US or Canada.
- `section_order`: put `projects` before `experience` only for a candidate with little work history.
- Optional `accent`: a dark hex colour. Default is navy `#1F3A5F`, used only on the name and section
  headings. Set `accent` to the `Accent colour` line in `config/author-profile.md`.

The builder cleans the text (plain hyphens and quotes, no ligatures or emoji), normalises dates, picks
the font size, and prints a JSON report. Exit code `2` means your JSON is missing something: it lists
exactly what, so ask the user for it (Step 1) and run again. It does not guess.

## Step 4 -- Read the report and fix it before saving

The report's `ats` object comes from reading the finished PDF back the way an ATS does.

- `pass: true` and `failures` empty: good. Read every `warnings` entry and fix each one you can (a
  country code, a missing month, a mixed date style, a missing keyword the candidate really has).
  Warnings you can't fix because the user hasn't given the information: tell the user plainly.
- `failures` not empty: change the JSON (usually shorter content or missing details) and rebuild. Up
  to three rebuilds. If it still fails, tell the user why and stop; don't save a failing resume.
- Confirm `pages` is 1, or 2 with a well-filled second page, and that `first_line` is the
  candidate's name.

Then read it once yourself: `python scripts/pdf-tools.py extract jobs/<id>-<slug>/resume.pdf`. It
should read like the resume, top to bottom, in order, with no stray symbols.

## What the fixed design does, and why (so you never work around it)

| Choice | Reason |
| --- | --- |
| One left-aligned column | Parsers read top to bottom; columns get interleaved |
| Arial, real embedded text | Standard font, extractable; no images or text as pictures |
| Ligatures off, no letter-spacing | "fi" and "N A M E" read back as garbage otherwise |
| Contact details in the body | Many ATS skip page headers and footers |
| Company, place and dates on one left-aligned line, separated by " \| " | Right-aligned dates get attached to the wrong job |
| No tables, icons, photos, progress bars, text boxes, cards | Parsers drop or scramble them |
| Standard section headings | ATS recognise "Experience", "Education", "Skills" |
| One dark accent on the name and headings only | Looks designed to a human; ignored by a parser |
| Visible URLs as plain text | Survive parsing and printing |
| PDF title set to "Name - Resume" | Some systems show it as the file's label |

Not carried over from `pdf-designer` because they hurt ATS parsing: cover pages, coloured backgrounds,
callout boxes, cards, icons, flex/grid layouts, web fonts, running headers and footers, and its
20-page minimum.

## Clean up

Delete the temp JSON. The job folder keeps only `resume.pdf`, `job-posting.json` and `match-notes.md`.
