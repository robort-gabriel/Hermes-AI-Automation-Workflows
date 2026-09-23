# Search Config

Defaults the job-finder skill uses for an unattended (cron) run, and the
baseline a chat-invoked run falls back to when the user doesn't specify a
field. A chat request always overrides these for that one run. The
onboarding skill fills this file in during the first chat.

## Role defaults

Each `Role` line is one search track. When a chat request doesn't name a
role, an unattended run starts one separate run per `Role` line (each taken to
completion before the next starts) rather than picking just one.

- **Role:** AI Automation Engineer
- **Role:** Macro Analyst
- **Seniority:** Entry-level / Junior
- **Location:** Remote, worldwide

Titles vary more than the underlying role, so the finder also accepts close
matches (for example "Automation Engineer", "AI Workflow Engineer", "Market
Analyst", "Research Analyst" with a macro/markets focus).

## Freshness

- **Max job age (days):** 3

Only jobs posted within this many days are kept. Anything older is excluded,
and `scripts/db.py add-job` refuses it even if a skill tries to log it. A job
whose posting date can't be verified is still logged, but is flagged
"date unknown" on the dashboard so you can judge it yourself. This one line is
the single place to change the window.

## Job sources

Jobs come straight from company career pages. Order of preference:

1. **Your target companies** -- every careers URL in
   `config/target-companies.md`, visited directly. Careers pages hosted by the
   company's hiring system (Greenhouse, Lever, Ashby, Workable, BambooHR, and
   similar) count, because they are the company's own postings.
2. **More companies' own career pages** -- when the target list turns up too
   few matches, search for other companies hiring for the role, then open each
   company's own careers page (or its hiring-system page) and read the listing
   there. Log the listing from that page, never from the search result.
3. **Job boards are never a source.** A board result may only be used as a
   lead to find the company's own careers page; if that page can't be found
   or doesn't show the listing, the job is not logged.

### Job boards and aggregators (never log from these)

- linkedin.com
- indeed.com
- glassdoor.com
- ziprecruiter.com
- monster.com
- dice.com
- simplyhired.com
- lensa.com

A listing counts as live only after the page itself has been fetched and shows
the role as open (not a 404, not a stale cache, not a board mirroring the page).

## Cadence

- Suggested: once daily at 08:00, through the Hermes cron job the installer
  creates **paused**. Turn it on or off from chat (see the user guide). The
  schedule itself lives in the Hermes cron job, not here.

## Dedupe window

- Skip a job already logged for the same company + title within the last 30
  days (`python scripts/db.py recent-titles --days 30`).
