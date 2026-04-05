import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

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
    today_str = "Posted: " + today.strftime("%b %d, %y")
    yesterday_str = "Posted: " + yesterday.strftime("%b %d, %y")
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
    return True

SHARED_REPLY = """Hi,

In response to your job posting.
Here I am attaching my consultant's resume.
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Best regards,
Lingaraju Modhala
Phone: +1 940 281 5324
Email: rajumodhala777@gmail.com"""

SEARCH_KEYWORDS = [
    {"search": "devops", "cc_secret": "CC_DEVOPS"},
    {"search": "cloud engineer", "cc_secret": "CC_CLOUD"},
    {"search": "sre", "cc_secret": "CC_SRE"},
    {"search": "site reliability", "cc_secret": "CC_SRE"},
    {"search": "kubernetes", "cc_secret": "CC_DEVOPS"},
    {"search": "terraform", "cc_secret": "CC_DEVOPS"},
    {"search": "devops engineer", "cc_secret": "CC_DEVOPS"},
    {"search": "aws engineer", "cc_secret": "CC_CLOUD"},
    {"search": "azure engineer", "cc_secret": "CC_CLOUD"},
    {"search": "gcp engineer", "cc_secret": "CC_CLOUD"},
    {"search": "platform engineer", "cc_secret": "CC_DEVOPS"},
    {"search": "infrastructure engineer", "cc_secret": "CC_DEVOPS"},
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

def find_search_box(driver):
    """Try multiple strategies to find a visible, interactable search input."""
    selectors = [
        "input[type='search']",
        "input[placeholder*='search' i]",
        "input[placeholder*='Search' i]",
        "input[name*='search' i]",
        "input[id*='search' i]",
        "input[class*='search' i]",
        "input[type='text']",
        "input",
    ]
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    log.info("Found search box with selector: %s", selector)
                    return el
        except Exception:
            continue
    return None

def submit_search(driver, search_box, search_term):
    """Scroll into view, click via JS, type keyword, then submit."""
    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", search_box)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", search_box)
        time.sleep(0.5)
        search_box.clear()
        search_box.send_keys(search_term)
        time.sleep(1)
    except Exception as e:
        log.warning("Could not type into search box: %s", e)
        return False

    # Try submit button first
    btn_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button[class*='search' i]",
        "button[aria-label*='search' i]",
        "button.search-btn",
        "button",
    ]
    for btn_sel in btn_selectors:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, btn_sel)
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    log.info("Submitted via button: %s", btn_sel)
                    return True
        except Exception:
            continue

    # Fallback: Enter key
    try:
        search_box.send_keys(Keys.RETURN)
        log.info("Submitted via Enter key")
        return True
    except Exception as e:
        log.warning("Enter key submission failed: %s", e)
        return False

def search_and_scrape(driver, search_term, seen_emails):
    jobs = []
    try:
        log.info("Searching for: %s", search_term)
        driver.get(JOBS_URL)
        time.sleep(4)

        # Save page source for debugging if needed
        try:
            with open("logs/page_debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except Exception:
            pass

        search_box = find_search_box(driver)
        if not search_box:
            log.warning("No interactable search box found for: %s — trying URL param approach", search_term)
            # Fallback: try appending search as URL query param
            try:
                encoded = search_term.replace(" ", "+")
                driver.get(JOBS_URL + "?search=" + encoded)
                time.sleep(4)
            except Exception as e:
                log.error("URL param fallback also failed: %s", e)
                return jobs
        else:
            success = submit_search(driver, search_box, search_term)
            if not success:
                log.warning("Search submission failed for: %s", search_term)
                return jobs
            time.sleep(4)

        # Scroll to load all results
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        while scroll_attempts < 20:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_attempts += 1
        log.info("Scrolled %d times for: %s", scroll_attempts, search_term)

        email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
        job_cards = driver.find_elements(By.CSS_SELECTOR, "div, li, article, tr")

        for card in job_cards:
            try:
                text = card.text.strip()
                if not text or len(text) < 10:
                    continue

                if not is_posted_recently(text):
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

                seen_emails.add(email_addr)
                jobs.append({
                    "title": title,
                    "email": email_addr,
                    "cc_secret": SEARCH_KEYWORDS[0]["cc_secret"],
                })
                log.info("Found: %s -> %s", title[:50], email_addr)

            except Exception:
                continue

        log.info("Found %d jobs for search: %s", len(jobs), search_term)

    except Exception as e:
        log.error("Search error for '%s': %s", search_term, e)

    return jobs

def get_resume():
    fname = "resume_lingaraju_b64.txt"
    if not Path(fname).exists():
        raise ValueError("Resume file not found!")
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

def send_email(job, smtp_server, cc_secret):
    smtp_email = os.environ["SMTP_EMAIL"]
    to_email = job["email"]
    cc_email = os.environ.get(cc_secret, "")
    subject = "Re: " + job["title"]
    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(SHARED_REPLY, "plain"))
    resume_bytes = get_resume()
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

def log_sent(job, cc_secret):
    csv_path = "logs/sent_log_hiring42.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new:
            f.write("timestamp,email,title,cc\n")
        cc = os.environ.get(cc_secret, "none")
        f.write('{}, "{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
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

    smtp_email = os.environ["SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
        log.info("SMTP connected: %s", smtp_email)
    except Exception as e:
        log.error("Could not connect to SMTP: %s", e)
        return

    driver = get_chrome_driver()
    seen_emails = set(replied_senders)
    sent = 0

    try:
        for kw in SEARCH_KEYWORDS:
            if daily_send_count >= MAX_DAILY_SENDS:
                log.warning("DAILY LIMIT REACHED. Stopping.")
                break

            jobs = search_and_scrape(driver, kw["search"], seen_emails)

            for job in jobs:
                if daily_send_count >= MAX_DAILY_SENDS:
                    break

                email_addr = job["email"]
                if email_addr in replied_senders:
                    log.info("SKIPPING - already sent to %s today", email_addr)
                    continue

                try:
                    log.info("SENDING to %s for: %s", email_addr, job["title"][:50])
                    send_email(job, smtp_server, kw["cc_secret"])
                    log_sent(job, kw["cc_secret"])
                    replied_senders.add(email_addr)
                    daily_send_count += 1
                    sent += 1
                    save_daily_dedup(replied_senders, daily_send_count)
                except Exception as e:
                    log.error("Error sending to %s: %s", email_addr, e, exc_info=True)
                    try:
                        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
                        smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
                        log.info("SMTP reconnected")
                    except Exception as se:
                        log.error("SMTP reconnect failed: %s", se)
                        break

    finally:
        try:
            driver.quit()
            log.info("Browser closed")
        except Exception:
            pass

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
