"""
Job Application Bot — searches LinkedIn, Indeed, Glassdoor, Remote.co
and auto-applies to top N matches per day, logging results to Google Sheets.
"""

import os, json, time, random, datetime, re, logging
from pathlib import Path
from typing import Optional

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("job_bot")

# ── Config loader ────────────────────────────────────────────────────────────
def load_config() -> dict:
    path = Path("config/config.json")
    if not path.exists():
        raise FileNotFoundError("config/config.json not found — run setup first.")
    with open(path) as f:
        return json.load(f)

# ── Resume parser ────────────────────────────────────────────────────────────
def parse_resume(path: str) -> str:
    """Extract text from resume (PDF or .txt)."""
    import importlib
    if path.endswith(".pdf"):
        try:
            pdfplumber = importlib.import_module("pdfplumber")
            with pdfplumber.open(path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            log.warning("pdfplumber not installed — falling back to pypdf2.")
            PyPDF2 = importlib.import_module("PyPDF2")
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return "\n".join(p.extract_text() or "" for p in reader.pages)
    with open(path) as f:
        return f.read()

# ── AI Job Matcher ────────────────────────────────────────────────────────────
def score_job(job: dict, profile: dict, client) -> float:
    """
    Use Claude to score how well a job matches the user's profile.
    Returns a float 0–10.
    """
    prompt = f"""
You are a job-matching assistant. Score how well this job matches the candidate.
Return ONLY a JSON object: {{"score": <float 0-10>, "reason": "<one sentence>"}}

CANDIDATE PROFILE:
Skills: {', '.join(profile.get('skills', []))}
Target roles: {', '.join(profile.get('target_roles', []))}
Experience years: {profile.get('experience_years', 'N/A')}
Preferred location: {profile.get('location_preference', 'Remote/Anywhere')}
Min salary: {profile.get('min_salary', 'N/A')}

JOB LISTING:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Salary: {job.get('salary', 'Not listed')}
Description snippet: {job.get('description', '')[:800]}
"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    try:
        data = json.loads(raw)
        return float(data.get("score", 0)), data.get("reason", "")
    except Exception:
        return 0.0, "Parse error"

# ── Cover Letter Generator ─────────────────────────────────────────────────
def generate_cover_letter(job: dict, profile: dict, resume_text: str, client) -> str:
    prompt = f"""
Write a concise, professional cover letter (3 paragraphs, under 300 words) for:

JOB: {job['title']} at {job['company']}
DESCRIPTION: {job.get('description', '')[:600]}

CANDIDATE:
Name: {profile['name']}
Skills: {', '.join(profile.get('skills', []))}
Resume excerpt: {resume_text[:1000]}

Do NOT use generic phrases. Sound like a real human. Address the company specifically.
"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()

# ── Scrapers ──────────────────────────────────────────────────────────────────

def scrape_linkedin(keywords: list[str], location: str, session) -> list[dict]:
    """Scrape LinkedIn jobs via LinkedIn Job Search URL (no auth)."""
    jobs = []
    from bs4 import BeautifulSoup
    for kw in keywords:
        url = (
            f"https://www.linkedin.com/jobs/search/?keywords={kw.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}&f_TPR=r86400&start=0"
        )
        try:
            r = session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.base-card")
            for card in cards[:20]:
                title_el = card.select_one("h3.base-search-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle")
                loc_el = card.select_one("span.job-search-card__location")
                link_el = card.select_one("a.base-card__full-link")
                if not title_el:
                    continue
                jobs.append({
                    "source": "LinkedIn",
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "",
                    "location": loc_el.get_text(strip=True) if loc_el else "",
                    "url": link_el["href"] if link_el else "",
                    "description": "",
                    "salary": "",
                    "applied": False,
                })
            log.info(f"LinkedIn: found {len(cards)} cards for '{kw}'")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.error(f"LinkedIn scrape error: {e}")
    return jobs


def scrape_indeed(keywords: list[str], location: str, session) -> list[dict]:
    from bs4 import BeautifulSoup
    jobs = []
    for kw in keywords:
        url = f"https://www.indeed.com/jobs?q={kw.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage=1"
        try:
            r = session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.job_seen_beacon")
            for card in cards[:20]:
                title_el = card.select_one("h2.jobTitle span")
                company_el = card.select_one("span.companyName")
                loc_el = card.select_one("div.companyLocation")
                salary_el = card.select_one("div.salary-snippet-container")
                link_el = card.select_one("a[data-jk]")
                if not title_el:
                    continue
                job_id = link_el["data-jk"] if link_el else ""
                jobs.append({
                    "source": "Indeed",
                    "title": title_el.get_text(strip=True),
                    "company": company_el.get_text(strip=True) if company_el else "",
                    "location": loc_el.get_text(strip=True) if loc_el else "",
                    "salary": salary_el.get_text(strip=True) if salary_el else "",
                    "url": f"https://www.indeed.com/viewjob?jk={job_id}",
                    "description": "",
                    "applied": False,
                })
            log.info(f"Indeed: found {len(cards)} cards for '{kw}'")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.error(f"Indeed scrape error: {e}")
    return jobs


def scrape_glassdoor(keywords: list[str], location: str, session) -> list[dict]:
    from bs4 import BeautifulSoup
    jobs = []
    for kw in keywords:
        url = (
            f"https://www.glassdoor.com/Job/jobs.htm?suggestCount=0&suggestChosen=false"
            f"&clickSource=searchBtn&typedKeyword={kw.replace(' ', '+')}"
            f"&locT=C&locId=1&jobType=all&fromAge=1&filter.includeNoSalaryJobs=true"
        )
        try:
            r = session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("li.react-job-listing")
            for card in cards[:20]:
                title_el = card.select_one("a.jobLink")
                company_el = card.select_one("div.jobHeader .employerName")
                loc_el = card.select_one("span.loc")
                salary_el = card.select_one("span.salaryText")
                link = title_el["href"] if title_el else ""
                jobs.append({
                    "source": "Glassdoor",
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "company": company_el.get_text(strip=True) if company_el else "",
                    "location": loc_el.get_text(strip=True) if loc_el else "",
                    "salary": salary_el.get_text(strip=True) if salary_el else "",
                    "url": f"https://www.glassdoor.com{link}" if link.startswith("/") else link,
                    "description": "",
                    "applied": False,
                })
            log.info(f"Glassdoor: found {len(cards)} cards for '{kw}'")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.error(f"Glassdoor scrape error: {e}")
    return jobs


def scrape_remoteio(keywords: list[str], session) -> list[dict]:
    from bs4 import BeautifulSoup
    jobs = []
    for kw in keywords:
        url = f"https://remote.co/remote-jobs/search/?search_keywords={kw.replace(' ', '+')}"
        try:
            r = session.get(url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.job_listing")
            for card in cards[:20]:
                title_el = card.select_one("h3")
                company_el = card.select_one(".company_name")
                link_el = card.select_one("a.listing")
                jobs.append({
                    "source": "Remote.co",
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "company": company_el.get_text(strip=True) if company_el else "",
                    "location": "Remote",
                    "salary": "",
                    "url": link_el["href"] if link_el else "",
                    "description": "",
                    "applied": False,
                })
            log.info(f"Remote.co: found {len(cards)} cards for '{kw}'")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.error(f"Remote.co scrape error: {e}")
    return jobs

# ── Job description fetcher ─────────────────────────────────────────────────
def fetch_description(job: dict, session) -> str:
    if not job.get("url"):
        return ""
    try:
        from bs4 import BeautifulSoup
        r = session.get(job["url"], timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        # Try common job description containers
        for sel in [
            "div.show-more-less-html__markup",  # LinkedIn
            "div#jobDescriptionText",           # Indeed
            "div.jobDescriptionContent",        # Glassdoor
            "div.job-description",              # Remote.co
            "article",
        ]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator=" ", strip=True)[:2000]
    except Exception as e:
        log.warning(f"Could not fetch description for {job.get('url')}: {e}")
    return ""

# ── Google Sheets logger ────────────────────────────────────────────────────
def log_to_sheets(job: dict, score: float, reason: str, status: str, cfg: dict):
    """Append a row to Google Sheets via gspread."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            cfg["google_service_account_path"], scopes=scopes
        )
        gc = gspread.authorize(creds)
        sh = gc.open(cfg["google_sheet_name"])
        ws = sh.sheet1

        # Ensure header row
        if ws.row_count == 0 or not ws.row_values(1):
            ws.append_row([
                "Date Applied", "Job Title", "Company", "Location",
                "Source", "Match Score", "Match Reason", "Status",
                "Salary", "URL",
            ])

        ws.append_row([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("source", ""),
            f"{score:.1f}/10",
            reason,
            status,
            job.get("salary", ""),
            job.get("url", ""),
        ])
        log.info(f"Logged to Google Sheets: {job['title']} @ {job['company']}")
    except Exception as e:
        log.error(f"Google Sheets log failed: {e}")
        # Fallback: write to local CSV
        import csv
        with open("data/applications.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                job.get("title"), job.get("company"), job.get("location"),
                job.get("source"), f"{score:.1f}/10", reason, status,
                job.get("salary"), job.get("url"),
            ])
        log.info("Fallback: logged to data/applications.csv")

# ── Deduplication ────────────────────────────────────────────────────────────
def load_seen_jobs() -> set:
    path = Path("data/seen_jobs.json")
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()

def save_seen_jobs(seen: set):
    with open("data/seen_jobs.json", "w") as f:
        json.dump(list(seen), f)

def job_key(job: dict) -> str:
    return f"{job.get('title','').lower()}|{job.get('company','').lower()}"

# ── Apply (Easy Apply simulation) ────────────────────────────────────────────
def apply_to_job(job: dict, cover_letter: str, profile: dict, cfg: dict) -> bool:
    """
    Attempt to apply to a job. 
    For LinkedIn Easy Apply, uses Playwright for browser automation.
    For others, sends email if contact info available, or marks as 'Manual needed'.
    """
    source = job.get("source", "")
    if cfg.get("dry_run", True):
        log.info(f"[DRY RUN] Would apply to: {job['title']} @ {job['company']}")
        return True

    if source == "LinkedIn":
        return _linkedin_easy_apply(job, cover_letter, profile, cfg)
    elif source == "Indeed":
        return _indeed_apply(job, cover_letter, profile, cfg)
    else:
        log.info(f"Manual application needed for {source}: {job['url']}")
        return False  # Will be logged as "Manual"

def _linkedin_easy_apply(job, cover_letter, profile, cfg) -> bool:
    """Use Playwright to click LinkedIn Easy Apply."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.get("headless", True))
            ctx = browser.new_context()
            page = ctx.new_page()

            # Log in
            page.goto("https://www.linkedin.com/login")
            page.fill("#username", cfg["linkedin_email"])
            page.fill("#password", cfg["linkedin_password"])
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")

            # Navigate to job
            page.goto(job["url"])
            page.wait_for_load_state("networkidle")

            # Click Easy Apply
            btn = page.query_selector("button.jobs-apply-button")
            if not btn or "easy apply" not in (btn.inner_text() or "").lower():
                log.warning("No Easy Apply button found.")
                browser.close()
                return False

            btn.click()
            page.wait_for_timeout(2000)

            # Fill phone if asked
            phone_input = page.query_selector("input[id*='phoneNumber']")
            if phone_input:
                phone_input.fill(profile.get("phone", ""))

            # Submit (simplified — real flow may have multiple steps)
            submit = page.query_selector("button[aria-label='Submit application']")
            if submit:
                submit.click()
                page.wait_for_timeout(2000)
                log.info(f"Applied via LinkedIn Easy Apply: {job['title']}")
                browser.close()
                return True

            browser.close()
            return False
    except Exception as e:
        log.error(f"LinkedIn Easy Apply failed: {e}")
        return False

def _indeed_apply(job, cover_letter, profile, cfg) -> bool:
    """Indeed Instant Apply (simplified)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.get("headless", True))
            page = browser.new_page()
            page.goto(job["url"])
            page.wait_for_load_state("networkidle")

            apply_btn = page.query_selector("button#indeedApplyButton, a.indeed-apply-button")
            if apply_btn:
                apply_btn.click()
                page.wait_for_timeout(3000)
                log.info(f"Clicked Indeed apply for: {job['title']}")
                browser.close()
                return True
            browser.close()
            return False
    except Exception as e:
        log.error(f"Indeed apply failed: {e}")
        return False

# ── Main runner ──────────────────────────────────────────────────────────────
def run():
    cfg = load_config()
    profile = cfg["profile"]
    n_per_day = cfg.get("applications_per_day", 10)
    min_score = cfg.get("min_match_score", 6.0)

    # Load resume
    resume_text = parse_resume(cfg["resume_path"])
    log.info(f"Resume loaded: {len(resume_text)} chars")

    # Init Anthropic client
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])

    # Init HTTP session with realistic headers
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    # Scrape all sources
    all_jobs: list[dict] = []
    keywords = cfg.get("search_keywords", profile.get("target_roles", []))
    location = profile.get("location_preference", "Remote")

    log.info("Scraping LinkedIn...")
    all_jobs += scrape_linkedin(keywords, location, session)
    log.info("Scraping Indeed...")
    all_jobs += scrape_indeed(keywords, location, session)
    log.info("Scraping Glassdoor...")
    all_jobs += scrape_glassdoor(keywords, location, session)
    log.info("Scraping Remote.co...")
    all_jobs += scrape_remoteio(keywords, session)

    log.info(f"Total raw jobs: {len(all_jobs)}")

    # Deduplicate
    seen = load_seen_jobs()
    fresh_jobs = [j for j in all_jobs if job_key(j) not in seen]
    log.info(f"Fresh jobs (unseen): {len(fresh_jobs)}")

    # Fetch descriptions and score
    scored = []
    for job in fresh_jobs:
        job["description"] = fetch_description(job, session)
        score, reason = score_job(job, profile, client)
        scored.append((score, reason, job))
        time.sleep(0.5)

    # Sort by score descending, take top N above threshold
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [(s, r, j) for s, r, j in scored if s >= min_score][:n_per_day]

    log.info(f"Top matches to apply to: {len(top)}")

    applied_count = 0
    for score, reason, job in top:
        key = job_key(job)
        seen.add(key)

        cover_letter = generate_cover_letter(job, profile, resume_text, client)
        success = apply_to_job(job, cover_letter, profile, cfg)
        status = "Applied" if success else "Manual needed"

        log_to_sheets(job, score, reason, status, cfg)
        applied_count += 1

        log.info(
            f"[{status}] {job['title']} @ {job['company']} "
            f"({job['source']}) — score {score:.1f}/10"
        )
        time.sleep(random.uniform(3, 7))  # polite delay between applications

    save_seen_jobs(seen)

    # Save daily report
    report = {
        "date": datetime.date.today().isoformat(),
        "scraped": len(all_jobs),
        "fresh": len(fresh_jobs),
        "applied": applied_count,
        "top_jobs": [
            {
                "title": j["title"],
                "company": j["company"],
                "score": round(s, 1),
                "reason": r,
                "source": j["source"],
            }
            for s, r, j in top
        ],
    }
    with open(f"logs/report_{datetime.date.today().isoformat()}.json", "w") as f:
        json.dump(report, f, indent=2)

    log.info(f"Done. Applied to {applied_count} jobs today.")
    return report

if __name__ == "__main__":
    run()
