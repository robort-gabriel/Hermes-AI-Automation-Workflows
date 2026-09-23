# Resume Library

Your permanent, source-of-truth resume lives here, as a **PDF**. Every run
reads it; nothing ever overwrites it (tailored copies go to
`jobs/<id>-<company-slug>/resume.pdf`, not here).

## Files

- `resume.pdf` -- your base resume. It must be a text-based PDF (exported from
  Word, Google Docs, etc.), not a scan or a photo, so the skills can read it.
- `ats-profile.md` -- optional. Details you gave the chat so tailored resumes pass
  applicant tracking systems (ATS): your phone with the country code, City and
  Country, LinkedIn, and start and end months for your jobs. The chat creates and
  fills it by asking you one question at a time; you can edit it by hand. It wins
  over `resume.pdf` for contact details and dates. Example:

  ```
  Full name: Sam Doe
  Phone: +234 801 234 5678
  Location: Lagos, Nigeria
  LinkedIn: linkedin.com/in/samdoe
  Dates: Acme Ltd | Start: Mar 2023 | End: Present
  ```

There is no Markdown resume anywhere in this project. Resumes are PDF only,
both the one you provide and every tailored one the pipeline makes.

## How it gets here

You don't have to copy it yourself. On your first chat with the `job-hunter`
profile, the onboarding skill asks for your resume PDF and puts it in place,
then asks for any ATS details it's missing. To swap in a new resume later, ask
in chat ("I have a new resume at <path>") or replace `resume.pdf` here yourself.

## Rules

- The resume-editor skill never edits `resume.pdf` and never invents
  experience, employers, titles, or dates that aren't in it or in
  `ats-profile.md`. The only times a skill writes here are onboarding (a new
  resume) and when you answer its ATS questions.

## Privacy

`resume.pdf` and `ats-profile.md` are git-ignored on purpose: they hold your real
name, contact details, and work history. Everything in this folder except this
README is ignored, so nothing personal can be committed or pushed by accident.
