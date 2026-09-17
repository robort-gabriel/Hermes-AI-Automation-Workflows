# Search Config

Defaults the job-finder skill uses for an unattended (cron) run, and the
baseline a chat-invoked run falls back to when the user doesn't specify a
field. A chat request always overrides these for that one run.

## Role defaults

Two target roles, reflecting the two distinct tracks on the candidate's CV.
When a chat request doesn't specify a role, an unattended (cron) run starts
one separate run per role below (each processed to completion before the
next starts) rather than picking just one.

1. **Role / title:** AI Automation Engineer
   - Also matches close postings titled "AI Automation Architect", "AI
     Automation Specialist", "Automation Engineer", or "AI Workflow
     Engineer" -- title wording varies more than the underlying role.
2. **Role / title:** Macro Analyst
   - Also matches "Macro Research Analyst", "Market Analyst", or "Research
     Analyst" postings with a macro/markets focus.

- **Seniority:** Entry-level / Junior
- **Location / remote preference:** Remote, worldwide

Edit any of the above at any time -- these are just the unattended defaults;
a chat-invoked run can always override role/seniority/location for that one
run.

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
