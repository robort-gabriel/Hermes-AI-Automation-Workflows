# Resume Library

Your permanent, source-of-truth CV lives here. Every run reads from this
folder -- it is never overwritten or re-uploaded by the tailoring output
(tailored copies go under `jobs/<id>-<company-slug>/`, not here).

## Expected files

- `resume.md` -- your base resume in Markdown. Replace the placeholder file
  in this folder with your real one. Keep it structured (headings for
  Summary / Experience / Skills / Education) so the resume-editor skill can
  reorder and re-emphasize sections reliably.
- `resume.pdf` (optional) -- a rendered copy for your own reference. Not
  read by the pipeline; `resume.md` is the only source the skills parse.

## Rules

- Never delete or edit `resume.md` from inside a skill run -- it is read-only
  input. If your real experience changes, update it yourself.
- The resume-editor skill never invents experience, employers, titles, or
  dates that aren't in this file.
