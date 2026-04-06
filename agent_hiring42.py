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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/agent_hiring42.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

DEDUP_FILE = Path("logs") / "daily_replied_senders_hiring42.json"
MAX_DAILY_SENDS = 450
JOBS_URL = "https://www.hiring42.com/all_jobs"
LOGIN_URL = "https://www.hiring42.com/login"

def get_today_date():
    return str(date.today())

def get_valid_posted_strings():
    today = datetime.now()
    yesterday = datetime.now() - timedelta(days=1)
    today_str = "Posted: " + today.strftime("%b %d, %y")
    yesterday_str = "Posted: " + yesterday.strftime("%b %d, %y")
    return [today_str, yesterday_str]

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

ROLE_KEYWORDS = [
    {"keywords": ["devops","devsecops","dev ops","ci/cd","pipeline engineer","release engineer","build and release"], "cc_secret": "CC_DEVOPS"},
    {"keywords": ["cloud engineer","cloud architect","aws engineer","aws architect","azure engineer","azure architect","gcp engineer","gcp architect","platform engineer","infrastructure engineer","cloud infrastructure"], "cc_secret": "CC_CLOUD"},
    {"keywords": ["site reliability","sre engineer","sre lead","reliability engineer"], "cc_secret": "CC_SRE"},
    {"keywords": ["kubernetes","k8s","docker engineer","openshift","container engineer","helm"], "cc_secret": "CC_DEVOPS"},
    {"keywords": ["terraform","ansible engineer","gitops","infrastructure automation"], "cc_secret": "CC_DEVOPS"},
]

SKIP_EMAILS = [
    "rajumodhala777@gmail.com",
    "sudheeritservices1@gmail.com",
    "noreply@",
    "mailer-daemon@",
]

EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

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

def login(driver):
    try:
        log.info("Logging in to hiring42.com...")
        driver.get(LOGIN_URL)
        time.sleep(3)

        # Take screenshot for debug
        driver.save_screenshot("logs/login_page.png")
        log.info("Login page loaded. Title: %s", driver.title)

        # Find email field
        email_field = None
        for selector in ["input[type='email']", "input[name='email']", "input[id='email']", "input[placeholder*='email']", "input[placeholder*='Email']"]:
            try:
                fields = driver.find_elements(By.CSS_SELECTOR, selector)
                for f in fields:
                    if f.is_displayed():
                        email_field = f
                        break
                if email_field:
                    break
            except Exception:
                continue

        if not email_field:
            log.error("Email field not found on login page")
            return False

        email_field.clear()
        email_field.send_keys(os.environ["HIRING42_EMAIL"])
        log.info("Entered email")
        time.sleep(1)

        # Find password field
        password_field = None
        for selector in ["input[type='password']", "input[name='password']", "input[id='password']"]:
            try:
                fields = driver.find_elements(By.CSS_SELECTOR, selector)
                for f in fields:
                    if f.is_displayed():
                        password_field = f
                        break
                if password_field:
                    break
            except Exception:
                continue

        if not password_field:
            log.error("Password field not found on login page")
            return False

        password_field.clear()
        password_field.send_keys(os.environ["HIRING42_PASSWORD"])
        log.info("Entered password")
        time.sleep(1)

        # Click login button
        login_btn = None
        for selector in ["button[type='submit']", "input[type='submit']", "button.login", "button.btn-login", "button.sign-in"]:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, selector)
                for b in btns:
                    if b.is_displayed():
                        login_btn = b
                        break
                if login_btn:
                    break
            except Exception:
                continue

        if login_btn:
            login_btn.click()
        else:
            password_field.send_keys(Keys.RETURN)

        time.sleep(5)
        driver.save_screenshot("logs/after_login.png")
        log.info("After login. Title: %s", driver.title)
        log.info("After login. URL: %s", driver.current_url)
        return True

    except Exception as e:
        log.error("Login failed: %s", e)
        return False

def scrape_all_jobs(driver):
    all_jobs = []
    seen_emails = set()
    valid_dates = get_valid_posted_strings()
    log.info("Date filter: %s", " OR ".join(valid_dates))

    try:
        driver.get(JOBS_URL)
        log.info("Opened jobs page: %s", JOBS_URL)
        time.sleep(5)
        driver.save_screenshot("logs/jobs_page.png")
        log.info("Jobs page title: %s", driver.title)

        # Scroll to load ALL jobs
        log.info("Scrolling to load all jobs...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count += 1
            if new_height == last_height:
                log.info("All jobs loaded after %d scrolls", scroll_count)
                break
            last_height = new_height
            if scroll_count % 5 == 0:
                log.info("Scrolled %d times...", scroll_count)

        # Get full page text
        page_text = driver.find_element(By.TAG_NAME, "body").text
        blocks = page_text.split('\n')
        log.info("Total lines on page: %d", len(blocks))

        # Save raw page text for debugging
        with open("logs/page_text.txt", "w", encoding="utf-8") as f:
            f.write(page_text)
        log.info("Raw page text saved to logs/page_text.txt")

        # Parse job cards
        i = 0
        while i < len(blocks):
            line = blocks[i].strip()

            if any(d in line for d in valid_dates):
                title = ""
                email_addr = ""
                location = ""

                for j in range(max(0, i-6), i):
                    block = blocks[j].strip()
                    if not block:
                        continue

                    emails = EMAIL_PATTERN.findall(block)
                    if emails:
                        email_addr = emails[0].lower()
                        continue

                    badge_words = ["c2c","w2","onsite","remote","hybrid","yrs","exp n/a",
                                  "active","posted","score","all jobs","filters","h42",
                                  "submit your","search"]
                    if any(x in block.lower() for x in badge_words):
                        continue

                    if ',' in block and len(block) < 40:
                        location = block
                        continue

                    if len(block) > 3:
                        title = block

                if title and email_addr:
                    if email_addr not in seen_emails:
                        if not any(skip in email_addr for skip in SKIP_EMAILS):
                            seen_emails.add(email_addr)
                            all_jobs.append({
                                "title": title,
                                "email": email_addr,
                                "location": location,
                                "posted": line.strip()
                            })

        i += 1

    except Exception as e:
        log.error("Scraping error: %s", e)

    return all_jobs

def detect_role(title):
    title_lower = title.lower()
    for role in ROLE_KEYWORDS:
        if any(kw in title_lower for kw in role["keywords"]):
            return role
    return None

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
            f.write("timestamp,email,title,location,cc\n")
        cc = os.environ.get(cc_secret, "none")
        f.write('{}, "{}","{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            job["email"],
            job["title"],
            job.get("location",""),
            cc
        ))

def save_all_jobs_csv(all_jobs):
    csv_path = "logs/all_jobs_today.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("title,email,location,posted\n")
        for j in all_jobs:
            f.write('"{}","{}","{}","{}"\n'.format(
                j["title"], j["email"], j["location"], j["posted"]
            ))
    log.info("All jobs saved to: %s", csv_path)

def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42.com)")
    log.info("SCRAPE ALL JOBS : https://www.hiring42.com/all_jobs")
    log.info("SEND from : rajumodhala777@gmail.com")
    log.info("Date filter : %s", " OR ".join(get_valid_posted_strings()))
    log.info("Time      : %s", datetime.now().isoformat())
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("Outside run window. Skipping.")
        return

    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD", "HIRING42_EMAIL", "HIRING42_PASSWORD"]
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

    driver = get_chrome_driver()
    all_jobs = []
    try:
        logged_in = login(driver)
        if not logged_in:
            log.error("Login failed. Cannot scrape jobs.")
            return

        all_jobs = scrape_all_jobs(driver)
    finally:
        driver.quit()
        log.info("Browser closed")

    log.info("=" * 70)
    log.info("TOTAL JOBS FOUND TODAY/YESTERDAY: %d", len(all_jobs))
    log.info("=" * 70)

    save_all_jobs_csv(all_jobs)

    for j in all_jobs:
        log.info("JOB: %-50s | %s | %s", j["title"][:50], j["email"], j["location"])

    matching_jobs = []
    for j in all_jobs:
        role = detect_role(j["title"])
        if role:
            j["cc_secret"] = role["cc_secret"]
            matching_jobs.append(j)

    log.info("=" * 70)
    log.info("MATCHING JOBS (DevOps/Cloud/SRE/K8s/Terraform): %d", len(matching_jobs))
    log.info("=" * 70)

    if not matching_jobs:
        log.info("No matching jobs to send.")
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
    for job in matching_jobs:
        if daily_send_count >= MAX_DAILY_SENDS:
            log.warning("DAILY LIMIT REACHED. Stopping.")
            break

        email_addr = job["email"]
        if email_addr in replied_senders:
            log.info("SKIPPING - already sent to %s", email_addr)
            continue

        try:
            log.info("SENDING to %s for: %s", email_addr, job["title"][:50])
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

    try:
        smtp_server.quit()
        log.info("SMTP connection closed")
    except Exception:
        pass

    log.info("=" * 70)
    log.info("Done - Sent to %d recruiters from hiring42.com", sent)
    log.info("Total jobs found  : %d", len(all_jobs))
    log.info("Matching jobs     : %d", len(matching_jobs))
    log.info("Daily sends       : %d/%d", daily_send_count, MAX_DAILY_SENDS)
    log.info("Cost: 0.00")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
