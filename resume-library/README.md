# Resume Library

Your permanent, source-of-truth CV lives here. Every run reads from this
folder -- it is never overwritten or re-uploaded by the tailoring output
(tailored copies go under `jobs/<id>-<company-slug>/`, not here).

## Expected files

- `resume.md` -- your base resume in Markdown. Git-ignored (see Privacy
  below). If it doesn't exist yet, `scripts/setup-hermes-profile.py` (run via
  `install.bat` / `install.command`) seeds it from `resume.example.md`.
  Replace it with your real resume -- keep it structured (headings for
  Summary / Experience / Skills / Education) so the resume-editor skill can
  reorder and re-emphasize sections reliably.
- `resume.example.md` -- the tracked, generic starting template. Never put
  real personal information in this file; it's the one that gets committed.
- `resume.pdf` (optional) -- a rendered copy for your own reference. Not
  read by the pipeline; `resume.md` is the only source the skills parse.

## Rules

- Never delete or edit `resume.md` from inside a skill run -- it is read-only
  input. If your real experience changes, update it yourself.
- The resume-editor skill never invents experience, employers, titles, or
  dates that aren't in this file.

## Privacy

`resume.md` is git-ignored on purpose -- it holds your real name, contact
details, and work history. Only `resume.example.md` (the generic template)
is ever committed. Your real resume stays local, untracked, and never gets
pushed anywhere. If you clone this repo on a new machine, the setup script
will seed `resume.md` from the example template for you -- then replace it
with your real one.
