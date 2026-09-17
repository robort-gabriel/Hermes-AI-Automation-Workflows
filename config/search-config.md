# Search Config

Defaults the job-finder skill uses for an unattended (cron) run, and the
baseline a chat-invoked run falls back to when the user doesn't specify a
field. A chat request always overrides these for that one run.

## Role defaults

- **Role / title:** _(fill in, e.g. "Senior Backend Engineer")_
- **Seniority:** _(e.g. "Senior", "Mid-level", "Staff")_
- **Location / remote preference:** _(e.g. "Remote, US" or "Hybrid, Chicago")_

## Aggregators to exclude from supplementary search

The skill searches the web only to *supplement* `target-companies.md`, and
only ever logs a listing that lives on the company's own domain. Any result
on one of these domains is filtered out before a fetch is even attempted:

- linkedin.com
- indeed.com
- glassdoor.com
- ziprecruiter.com
- monster.com
- dice.com
- simplyhired.com
- ldjobs.com / lensa.com

## Supplementary search strategy

1. Search `site:<company-domain>` combined with the role/title, restricted to
   domains not already covered in `target-companies.md`.
2. Before logging a match, fetch the page directly to confirm the listing is
   still live (not a 404, not a stale cache hit) and that it is genuinely
   hosted on the company's own domain (not an aggregator mirroring the page).

## Cadence (for the Hermes cron job)

- Suggested: once daily. Adjust in the Hermes cron schedule, not here --
  this file only carries role/search defaults.

## Dedupe window

- Skip a job already logged for the same company + title combination within
  the last 30 days (`python3 scripts/db.py recent-titles --days 30`).
