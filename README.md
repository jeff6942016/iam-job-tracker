# IAM Job Posting Tracker

A small Python tool that pulls Identity & Access Management (IAM) job postings
from the [Adzuna API](https://developer.adzuna.com), scans each posting for the
certifications, platforms, and protocols that matter for an IAM career, and
generates a weekly frequency report. Built to answer a simple question:
**which skills and certs keep showing up in the IAM roles I actually want?**

## Why

Breaking into IAM means knowing which tools and credentials employers ask for.
Rather than reading dozens of postings by hand, this script aggregates them and
counts how often each term appears, so the signal (e.g. "Entra ID appears in
70% of postings, Okta in a third, SC-300 in a quarter") is obvious at a glance.

## What it does

- Queries Adzuna for several IAM search terms and de-duplicates the results
- Scans each posting's title and description for tracked keywords across four
  categories: **certifications**, **platforms**, **protocols/concepts**, and
  **experience signals**
- Uses whole-word matching for short/ambiguous terms (`sso`, `pam`, `oidc`, ...)
  so they don't match inside other words
- Counts each term once per posting ("X of N postings mention it")
- Writes two dated reports:
  - a readable **`.txt`** summary plus the matched postings and their links
  - a **`.csv`** for spreadsheets / charting trends over time

## Setup

1. Register for a free API key at <https://developer.adzuna.com> (you get an
   `app_id` and an `app_key`).
2. Install the one dependency:
   ```bash
   pip install -r requirements.txt
   ```
3. Provide your credentials one of two ways:
   - **Environment variables** (preferred, keeps secrets out of the code):
     ```bash
     export ADZUNA_APP_ID=your_app_id
     export ADZUNA_APP_KEY=your_app_key
     ```
     (or copy `.env.example` to `.env` and load it)
   - **Directly in the script**: replace `YOUR_APP_ID_HERE` /
     `YOUR_APP_KEY_HERE` in the CONFIG section of `iam_job_tracker.py`.

## Usage

```bash
python iam_job_tracker.py
```

Two files appear in the folder, dated with the run day:
`iam_report_YYYY-MM-DD.txt` and `iam_report_YYYY-MM-DD.csv`.

## Configuration

Edit the CONFIG section at the top of `iam_job_tracker.py`:

- `SEARCH_TERMS` - the searches to run (one API call each)
- `WHERE` - location filter (e.g. `"Toronto"`, or `""` for country-wide)
- `COUNTRY` - Adzuna country code (`ca`, `gb`, `us`, ...)
- `KEYWORDS` - the terms tracked in each category; add tools as you spot them

## Scheduling (optional)

Run it weekly without thinking about it:

- **Windows** - Task Scheduler: new task, weekly trigger, action runs
  `python C:\path\to\iam_job_tracker.py`
- **macOS / Linux** - a `cron` entry, e.g. every Monday at 9am:
  ```
  0 9 * * 1  /usr/bin/python3 /path/to/iam_job_tracker.py
  ```

The script runs, writes its reports, and exits, so the machine only needs to be
on at the scheduled time (not 24/7).

## Notes & limitations

- Adzuna returns **truncated** descriptions, so a term buried deep in a full
  posting may not appear. Counts are a strong signal, not a perfect census.
- Free tier is ~1,000 calls/month; a weekly run uses a tiny fraction of that.
- Canadian coverage is thinner than what you'd see browsing LinkedIn directly;
  treat the output as directional.
- For personal job-search research. Respect Adzuna's Terms of Service.

## License

MIT - see [LICENSE](LICENSE).
