import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, date, timedelta
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
    valid = []
    for delta in [0, 1]:
        d = datetime.now() - timedelta(days=delta)
        valid.append("Posted: " + d.strftime("%b %d, %y"))
        try:
            valid.append("Posted: " + d.strftime("%b %-d, %y"))
        except Exception:
            # Windows doesn't support %-d
            valid.append("Posted: " + d.strftime("%b %#d, %y"))
    return list(set(valid))

def is_posted_recently(card_text):
    return any(d in card_text for d in get_valid_posted_strings())

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
    # Give React SPA extra time to boot
    driver.implicitly_wait(10)
    return driver

def wait_for_react(driver, timeout=30):
    """Wait until React has rendered real content into #root."""
    log.info("Waiting for React to render...")
    try:
        # Wait until #root has children (React mounted)
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return document.getElementById('root') && document.getElementById('root').children.length > 0"
            )
        )
        # Then wait until at least one input appears
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "input"))
        )
        time.sleep(2)  # small buffer for full render
        log.info("React fully rendered")
        return True
    except Exception as e:
        log.warning("React render wait timed out: %s", e)
        return False

def do_search(driver, search_term):
    """Find the search input and click the Search button."""
    # Wait for the input to be clickable
    try:
        search_box = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input"))
        )
    except Exception as e:
        log.warning("Search box not clickable: %s", e)
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", search_box)
        time.sleep(0.5)
        # Clear via JS then click and type
        driver.execute_script("arguments[0].value = '';", search_box)
        search_box.click()
        time.sleep(0.3)
        search_box.send_keys(search_term)
        time.sleep(0.8)
        log.info("Typed '%s' into search box", search_term)
    except Exception as e:
        log.warning("Could not type in search box: %s", e)
        return False

    # Click the orange Search button by visible text
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                btn_text = btn.text.strip().lower()
                if btn_text == "search" and btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    log.info("Clicked 'Search' button")
                    return True
            except Exception:
                continue
    except Exception as e:
        log.warning("Search button click failed: %s", e)

    # Fallback: Enter key
    try:
        search_box.send_keys(Keys.RETURN)
        log.info("Pressed Enter to search")
        return True
    except Exception as e:
        log.warning("Enter fallback failed: %s", e)
        return False

def wait_for_results(driver):
    """Wait until job results appear after search."""
    try:
        # Wait for email-like text to appear in page body
        WebDriverWait(driver, 20).until(
            lambda d: "@" in d.find_element(By.TAG_NAME, "body").text
        )
        time.sleep(2)
        log.info("Job results loaded")
    except Exception:
        log.warning("Could not confirm results loaded — proceeding anyway")
        time.sleep(4)

def scroll_all(driver, search_term):
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts = 0
    while scroll_attempts < 30:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scroll_attempts += 1
    log.info("Scrolled %d times for: %s", scroll_attempts, search_term)

def scrape_jobs(driver, search_term, seen_emails, cc_secret):
    jobs = []
    email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    valid_dates = get_valid_posted_strings()
    log.info("Date filter active: %s", valid_dates)

    # Try progressively more specific selectors
    card_selectors = [
        "div[class*='job']",
        "div[class*='card']",
        "div[class*='listing']",
        "div[class*='result']",
        "li",
        "article",
        "tr",
        "div",
    ]

    job_cards = []
    for selector in card_selectors:
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, selector)
            with_email = [c for c in candidates if email_pattern.search(c.text or "")]
            if with_email:
                job_cards = candidates
                log.info("Card selector '%s': %d total, %d with emails", selector, len(candidates), len(with_email))
                break
        except Exception:
            continue

    if not job_cards:
        # Last resort: scrape entire body text for emails+dates
        log.warning("No card elements found — scraping raw body text")
        body_text = driver.find_element(By.TAG_NAME, "body").text
        log.info("Body text sample:\n%s", body_text[:2000])
        return jobs

    for card in job_cards:
        try:
            text = card.text.strip()
            if not text or len(text) < 15:
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
            title = lines[0] if lines else search_term
            seen_emails.add(email_addr)
            jobs.append({"title": title, "email": email_addr, "cc_secret": cc_secret})
            log.info("Found: %s -> %s", title[:60], email_addr)
        except Exception:
            continue

    log.info("Total new jobs found for '%s': %d", search_term, len(jobs))
    return jobs

def search_and_scrape(driver, search_term, seen_emails, cc_secret):
    jobs = []
    try:
        log.info("=" * 50)
        log.info("Searching for: %s", search_term)
        driver.get(JOBS_URL)

        # CRITICAL: wait for React SPA to fully render
        if not wait_for_react(driver):
            log.error("React did not render for: %s — skipping", search_term)
            return jobs

        success = do_search(driver, search_term)
        if not success:
            log.warning("Search failed for: %s", search_term)
            return jobs

        wait_for_results(driver)
        scroll_all(driver, search_term)
        jobs = scrape_jobs(driver, search_term, seen_emails, cc_secret)

    except Exception as e:
        log.error("search_and_scrape error for '%s': %s", search_term, e, exc_info=True)
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
    log.info("SCRAPE : %s", JOBS_URL)
    log.info("SEND from : rajumodhala777@gmail.com")
    log.info("Date filter : %s", " | ".join(get_valid_posted_strings()))
    log.info("Time      : %s", datetime.now().isoformat())
    log.info("=" * 70)

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

            jobs = search_and_scrape(driver, kw["search"], seen_emails, kw["cc_secret"])

            for job in jobs:
                if daily_send_count >= MAX_DAILY_SENDS:
                    break
                email_addr = job["email"]
                if email_addr in replied_senders:
                    log.info("SKIPPING - already sent to %s today", email_addr)
                    continue
                try:
                    log.info("SENDING to %s for: %s", email_addr, job["title"][:60])
                    send_email(job, smtp_server, job["cc_secret"])
                    log_sent(job, job["cc_secret"])
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
    except Exception:
        pass

    log.info("=" * 70)
    log.info("Done - Sent to %d recruiters", sent)
    log.info("Daily sends : %d/%d", daily_send_count, MAX_DAILY_SENDS)
    log.info("=" * 70)

if __name__ == "__main__":
    main()
