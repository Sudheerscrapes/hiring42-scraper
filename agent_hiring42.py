@"
"""
AI Email Agent - Lingaraju Modhala (hiring42.com Scraper)
Scrapes: https://www.hiring42.com/all_jobs
Sends: rajumodhala777@gmail.com (Gmail SMTP)
Replies to: DevOps, Cloud Engineer, SRE, Kubernetes, Terraform roles

FEATURES:
1. Scrapes hiring42.com using Selenium (headless Chrome)
2. TODAY + YESTERDAY filter
3. Dedup checked FIRST before anything else
4. Dedup saved IMMEDIATELY after each send
5. UTF-8-sig fix for dedup file (BOM handling)
6. Skips own sent emails
7. Daily send cap (450)
8. SINGLE SMTP connection reused for all emails
9. 5 second delay between sends
"""

import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/agent_hiring42.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

DEDUP_FILE = Path("logs") / "daily_replied_senders_hiring42.json"
MAX_DAILY_SENDS = 450
JOBS_URL = "https://www.hiring42.com/all_jobs"

def get_today_date():
    return str(date.today())

def get_valid_posted_strings():
    today = datetime.now()
    yesterday = datetime.now() - timedelta(days=1)
    today_str = "Posted: " + today.strftime("%b %d, %y").replace(" 0", " ")
    yesterday_str = "Posted: " + yesterday.strftime("%b %d, %y").replace(" 0", " ")
    return [today_str, yesterday_str]

def is_posted_recently(card_text):
    valid_dates = get_valid_posted_strings()
    return any(d in card_text for d in valid_dates)

def load_daily_dedup():
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                file_date = data.get("date", "")
                today = get_today_date()
                if file_date == today:
                    senders = set(data.get("senders", []))
                    send_count = data.get("send_count", 0)
                    log.info("TODAY (%s): %d senders, %d/%d sent so far", today, len(senders), send_count, MAX_DAILY_SENDS)
                    return senders, send_count
                else:
                    log.info("NEW DAY! (was %s, now %s) - Resetting dedup", file_date, today)
                    return set(), 0
        except Exception as e:
            log.warning("Could not load dedup file: %s", e)
    log.info("TODAY (%s): No dedup file yet - starting fresh", get_today_date())
    return set(), 0

def save_daily_dedup(senders, send_count=0):
    data = {
        "date": get_today_date(),
        "senders": sorted(list(senders)),
        "send_count": send_count
    }
    try:
        with open(DEDUP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log.info("SAVED TO DEDUP: %d senders, %d/%d sent today", len(senders), send_count, MAX_DAILY_SENDS)
    except Exception as e:
        log.error("Could not save dedup file: %s", e)

def is_within_run_window():
    return True  # TIME CHECK DISABLED FOR TESTING

SHARED_REPLY = """Hi,

In response to your job posting.
Here I am attaching my consultant's resume.
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Best regards,
Lingaraju Modhala
Phone: +1 940 281 5324
Email: rajumodhala777@gmail.com"""

ROLES = [
    {
        "name": "DevOps Engineer",
        "keywords": [
            "devops engineer",
            "sr. devops",
            "sr devops",
            "senior devops",
            "lead devops",
            "devsecops",
            "dev ops",
            "ci/cd engineer",
            "build and release",
            "release engineer",
            "pipeline engineer",
            "devops ai engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret": "CC_DEVOPS",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Cloud Engineer",
        "keywords": [
            "cloud engineer",
            "cloud architect",
            "cloud infrastructure",
            "aws cloud engineer",
            "aws engineer",
            "aws architect",
            "aws devops",
            "azure cloud engineer",
            "azure engineer",
            "azure architect",
            "azure devops engineer",
            "gcp engineer",
            "gcp architect",
            "platform engineer",
            "infrastructure engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret": "CC_CLOUD",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Site Reliability Engineer",
        "keywords": [
            "site reliability engineer",
            "site reliability",
            "sre engineer",
            "sr. sre",
            "senior sre",
            "lead sre",
            "sre lead",
            "reliability engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret": "CC_SRE",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Kubernetes / Docker Engineer",
        "keywords": [
            "kubernetes engineer",
            "kubernetes developer",
            "k8s engineer",
            "docker engineer",
            "openshift engineer",
            "container engineer",
            "helm engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret": "CC_DEVOPS",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Terraform / Automation Engineer",
        "keywords": [
            "terraform engineer",
            "terraform developer",
            "infrastructure automation",
            "ansible engineer",
            "gitops engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret": "CC_DEVOPS",
        "reply": SHARED_REPLY,
    },
]

SKIP_EMAILS = [
    "rajumodhala777@gmail.com",
    "sudheeritservices1@gmail.com",
    "noreply@",
    "mailer-daemon@",
]

def get_chrome_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    return driver

def detect_role(title):
    title_lower = title.lower()
    for role in ROLES:
        if any(kw in title_lower for kw in role["keywords"]):
            log.info("Matched role: %s for title: %s", role["name"], title)
            return role
    return None

def scrape_jobs():
    valid_dates = get_valid_posted_strings()
    log.info("Launching Chrome headless browser...")
    log.info("Date filter: %s", " OR ".join(valid_dates))
    driver = get_chrome_driver()
    jobs = []

    try:
        driver.get(JOBS_URL)
        log.info("Opened: %s", JOBS_URL)
        time.sleep(5)

        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        while scroll_attempts < 10:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_attempts += 1
        log.info("Page scrolled %d times", scroll_attempts)

        email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
        job_cards = driver.find_elements(By.CSS_SELECTOR, "div, li, article, tr")
        log.info("Found %d potential job elements", len(job_cards))

        seen_emails = set()
        skipped_old = 0
        for card in job_cards:
            try:
                text = card.text.strip()
                if not text or len(text) < 10:
                    continue

                # TODAY + YESTERDAY ONLY CHECK
                if not is_posted_recently(text):
                    skipped_old += 1
                    continue

                emails_found = email_pattern.findall(text)
                if not emails_found:
                    continue

                email_addr = emails_found[0].lower()
                if email_addr in seen_emails:
                    continue
                if any(skip in email_addr for skip in SKIP_EMAILS):
                    continue

                lines = [l.strip() for l in text.split('\n') if l.strip()]
                if not lines:
                    continue
                title = lines[0]

                role = detect_role(title)
                if role is None:
                    log.info("No role match for: %s", title[:50])
                    continue

                seen_emails.add(email_addr)
                jobs.append({
                    "title": title,
                    "email": email_addr,
                    "role": role,
                })
                log.info("Job found: %s -> %s", title[:50], email_addr)

            except Exception:
                continue

        log.info("Skipped %d old job listings", skipped_old)
        log.info("Total matching jobs today+yesterday: %d", len(jobs))

    except Exception as e:
        log.error("Scraping error: %s", e)
    finally:
        driver.quit()
        log.info("Browser closed")

    return jobs

def get_resume(role):
    fname = role["resume_file"]
    if not Path(fname).exists():
        raise ValueError("Resume file '{}' not found!".format(fname))
    raw = Path(fname).read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16').strip()
    else:
        text = raw.decode('latin-1').strip()
    lines = text.splitlines()
    lines = [l for l in lines if not l.startswith("-----")]
    b64 = re.sub(r'\s+', '', "".join(lines))
    missing = len(b64) % 4
    if missing:
        b64 += "=" * (4 - missing)
    return base64.b64decode(b64)

def send_email(job, smtp_server):
    smtp_email = os.environ["SMTP_EMAIL"]
    to_email = job["email"]
    role = job["role"]
    cc_email = os.environ.get(role["cc_secret"], "")

    subject = "Re: " + job["title"]

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email

    msg.attach(MIMEText(role["reply"], "plain"))

    resume_bytes = get_resume(role)
    part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
    part.set_payload(resume_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", 'attachment; filename="Resume_Lingaraju_Modhala.docx"')
    msg.attach(part)

    recipients = [to_email]
    if cc_email:
        for cc in cc_email.split(","):
            cc = cc.strip()
            if cc and cc not in recipients:
                recipients.append(cc)

    smtp_server.sendmail(smtp_email, recipients, msg.as_string())

    log.info("Sent from : %s", smtp_email)
    log.info("Sent to   : %s", to_email)
    if cc_email:
        log.info("CCd       : %s", cc_email)

    time.sleep(5)

def log_sent(job):
    csv_path = "logs/sent_log_hiring42.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new:
            f.write("timestamp,role,email,title,cc\n")
        cc = os.environ.get(job["role"]["cc_secret"], "none")
        f.write('{},"{}", "{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            job["role"]["name"],
            job["email"],
            job["title"],
            cc
        ))

def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42.com)")
    log.info("SCRAPE : https://www.hiring42.com/all_jobs")
    log.info("SEND from : rajumodhala777@gmail.com")
    log.info("Date filter : %s", " OR ".join(get_valid_posted_strings()))
    log.info("Time      : %s", datetime.now().isoformat())
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("Outside run window. Skipping.")
        return
    log.info("Proceeding...")

    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    replied_senders, daily_send_count = load_daily_dedup()

    remaining = MAX_DAILY_SENDS - daily_send_count
    log.info("Daily budget: %d/%d used, %d remaining", daily_send_count, MAX_DAILY_SENDS, remaining)
    if remaining <= 0:
        log.warning("Daily limit reached. Stopping.")
        return

    jobs = scrape_jobs()
    if not jobs:
        log.info("No matching jobs found.")
        return

    smtp_email = os.environ["SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
        log.info("SMTP connected: %s", smtp_email)
    except Exception as e:
        log.error("Could not connect to SMTP: %s", e)
        return

    sent = 0
    for job in jobs:
        try:
            email_addr = job["email"]

            if email_addr in replied_senders:
                log.info("SKIPPING - already sent to %s today", email_addr)
                continue

            if daily_send_count >= MAX_DAILY_SENDS:
                log.warning("DAILY LIMIT REACHED. Stopping.")
                break

            log.info("SENDING to %s for: %s", email_addr, job["title"][:50])
            send_email(job, smtp_server)
            log_sent(job)

            replied_senders.add(email_addr)
            daily_send_count += 1
            sent += 1

            save_daily_dedup(replied_senders, daily_send_count)

        except Exception as e:
            log.error("Error sending to %s: %s", job.get("email"), e, exc_info=True)
            try:
                smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
                smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
                log.info("SMTP reconnected")
            except Exception as se:
                log.error("SMTP reconnect failed: %s", se)
                break

    try:
        smtp_server.quit()
        log.info("SMTP connection closed")
    except Exception:
        pass

    log.info("=" * 70)
    log.info("Done - Sent to %d recruiters from hiring42.com", sent)
    log.info("Daily sends : %d/%d", daily_send_count, MAX_DAILY_SENDS)
    log.info("Cost: 0.00")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
"@ | Out-File -FilePath "agent_hiring42.py" -Encoding utf8
