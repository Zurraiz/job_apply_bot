# Job Application Bot

Searches LinkedIn, Indeed, Glassdoor, and Remote.co daily — AI-scores matches,
auto-applies to the top N jobs, and logs everything to Google Sheets.

---

## Quick Start

### 1. Install dependencies

```bash
cd job_bot
pip install -r requirements.txt
playwright install chromium
```

### 2. Add your resume
Copy your resume into the `data/` folder:
```bash
cp ~/Downloads/your_resume.pdf data/resume.pdf
```

### 3. Configure the bot
Edit `config/config.json`:

| Field | What to set |
|---|---|
| `anthropic_api_key` | Your Claude API key from console.anthropic.com |
| `profile.name` | Your full name |
| `profile.email` | Your email |
| `profile.target_roles` | List of job titles you want |
| `profile.skills` | Your key skills |
| `profile.location_preference` | "Remote" or a city |
| `profile.min_salary` | Minimum salary (used for scoring) |
| `search_keywords` | Keyword phrases to search |
| `applications_per_day` | Max jobs to apply to per day (recommend 5–15) |
| `min_match_score` | Minimum AI match score 0–10 (recommend 6.0–7.5) |
| `linkedin_email` + `linkedin_password` | Your LinkedIn login |
| `dry_run` | Keep `true` until you're ready to apply for real |

### 4. Set up Google Sheets

Follow the steps in `setup_sheets.py`, then run:
```bash
python setup_sheets.py
```

### 5. Test it (dry run)
```bash
python bot.py
```
Check `logs/bot.log` and `data/applications.csv` (fallback log).

### 6. Enable real applications
In `config/config.json`, set:
```json
"dry_run": false
```

### 7. Run daily (scheduler)
```bash
python scheduler.py
```
Leave this running. It will apply every day at the time set in `schedule.run_daily_at`.

---

## How It Works

```
1. Scrape ──► LinkedIn + Indeed + Glassdoor + Remote.co (past 24hrs)
2. Dedupe ──► Skip jobs already seen
3. Score  ──► Claude AI scores each job 0–10 against your profile
4. Filter ──► Keep only jobs ≥ min_match_score, take top N
5. Write  ──► Generate a tailored cover letter with Claude
6. Apply  ──► LinkedIn Easy Apply (Playwright) or Indeed Instant Apply
7. Log    ──► Append row to Google Sheets with status + score
```

---

## Google Sheets Structure

| Column | Description |
|---|---|
| Date Applied | Timestamp |
| Job Title | Role name |
| Company | Employer |
| Location | Job location |
| Source | LinkedIn / Indeed / etc. |
| Match Score | AI score e.g. "8.2/10" |
| Match Reason | One-sentence AI explanation |
| Status | "Applied" / "Manual needed" / "Skipped" |
| Salary | Salary if listed |
| URL | Link to the job posting |

---

## Folder Structure

```
job_bot/
├── bot.py              ← Main bot logic
├── scheduler.py        ← Daily runner
├── setup_sheets.py     ← Google Sheets setup helper
├── requirements.txt
├── config/
│   ├── config.json     ← Your settings (fill this in)
│   └── google_service_account.json  ← Download from Google Cloud
├── data/
│   ├── resume.pdf      ← Your resume
│   ├── seen_jobs.json  ← Tracks already-seen jobs
│   └── applications.csv ← CSV fallback log
└── logs/
    ├── bot.log
    ├── scheduler.log
    └── report_YYYY-MM-DD.json
```

---

## Tips

- Start with `dry_run: true` and `applications_per_day: 5` to review matches before going live.
- Raise `min_match_score` to 7.5+ if you're getting irrelevant matches.
- LinkedIn may require 2FA — log in manually once in a non-headless browser, then set `headless: true`.
- For sites without Easy Apply, status logs as "Manual needed" — check those manually.
- Run on a VPS/server for 24/7 uptime (DigitalOcean, AWS EC2, etc.).

---

## Legal & Ethics Note

Web scraping and automated job applications may violate platforms' Terms of Service.
Use responsibly, keep volumes reasonable (≤15/day), and review what the bot applies to.
The `dry_run` mode lets you audit every match before enabling real submissions.
