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
from urllib.parse import urlencode

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/agent_hiring42.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

DEDUP_FILE = Path("logs") / "daily_replied_senders_hiring42.json"
MAX_DAILY_SENDS = 450
JOBS_BASE_URL = "https://www.hiring42.com/all_jobs"

# ── Keywords that must appear in the job title ──────────────────────────────
RELEVANT_KEYWORDS = [
    "devops", "dev ops", "cloud", "sre", "site reliability",
    "kubernetes", "k8s", "terraform", "aws", "azure", "gcp",
    "platform engineer", "infrastructure", "docker", "jenkins",
    "ansible", "openshift", "devsecops", "architect", "ci/cd",
    "cicd", "helm", "argocd", "gitlab", "pipeline"
]

def is_relevant_title(title):
    t = title.lower()
    return any(kw in t for kw in RELEVANT_KEYWORDS)

# ── Date helpers ─────────────────────────────────────────────────────────────
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
            valid.append("Posted: " + d.strftime("%b %#d, %y"))
    return list(set(valid))

def is_posted_recently(text):
    return any(d in text for d in get_valid_posted_strings())

# ── Dedup helpers ────────────────────────────────────────────────────────────
def load_daily_dedup():
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if data.get("date") == get_today_date():
                    senders = set(data.get("senders", []))
                    send_count = data.get("send_count", 0)
                    log.info("TODAY (%s): %d senders, %d/%d sent",
                             get_today_date(), len(senders), send_count, MAX_DAILY_SENDS)
                    return senders, send_count
                else:
                    log.info("NEW DAY - Resetting dedup")
                    return set(), 0
        except Exception as e:
            log.warning("Could not load dedup: %s", e)
    return set(), 0

def save_daily_dedup(senders, send_count=0):
    data = {"date": get_today_date(), "senders": sorted(list(senders)), "send_count": send_count}
    with open(DEDUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log.info("SAVED: %d senders, %d sent today", len(senders), send_count)

# ── Email body ───────────────────────────────────────────────────────────────
SHARED_REPLY = """Hi,

In response to your job posting.
Here I am attaching my consultant's resume.
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Best regards,
Lingaraju Modhala
Phone: +1 940 281 5324
Email: rajumodhala777@gmail.com"""

# ── Search keywords ──────────────────────────────────────────────────────────
SEARCH_KEYWORDS = [
    {"search": "devops",                  "cc_secret": "CC_DEVOPS"},
    {"search": "cloud engineer",          "cc_secret": "CC_CLOUD"},
    {"search": "sre",                     "cc_secret": "CC_SRE"},
    {"search": "site reliability",        "cc_secret": "CC_SRE"},
    {"search": "kubernetes",              "cc_secret": "CC_DEVOPS"},
    {"search": "terraform",               "cc_secret": "CC_DEVOPS"},
    {"search": "aws engineer",            "cc_secret": "CC_CLOUD"},
    {"search": "azure engineer",          "cc_secret": "CC_CLOUD"},
    {"search": "gcp engineer",            "cc_secret": "CC_CLOUD"},
    {"search": "platform engineer",       "cc_secret": "CC_DEVOPS"},
    {"search": "infrastructure engineer", "cc_secret": "CC_DEVOPS"},
    {"search": "docker",                  "cc_secret": "CC_DEVOPS"},
    {"search": "jenkins",                 "cc_secret": "CC_DEVOPS"},
    {"search": "ansible",                 "cc_secret": "CC_DEVOPS"},
    {"search": "openshift",               "cc_secret": "CC_DEVOPS"},
    {"search": "devsecops",               "cc_secret": "CC_DEVOPS"},
    {"search": "cloud architect",         "cc_secret": "CC_CLOUD"},
]

# ── Skip lists ───────────────────────────────────────────────────────────────
SKIP_EMAILS = [
    "rajumodhala777@gmail.com",
    "sudheeritservices1@gmail.com",
    "noreply@",
    "mailer-daemon@",
]

SKIP_LINES = {
    "h42", "hiring42", "authentic talent, verified in real-time",
    "all jobs", "all candidates", "my jobs", "my candidates",
    "how to", "contact", "login / sign up", "post a job",
    "submit your candidates", "find similar jobs", "refresh",
    "filters", "state", "any state", "city", "work preference",
    "any", "remote", "hybrid", "onsite", "visa", "any visa",
    "experience (years)", "apply filters", "active",
    "search results", "jobs tailored to your search",
    "use quick actions to keep submissions high-quality and status up to date.",
    "search",   # ← FIX: skip bare "Search" UI button
}

# Promo/UI text that should never be treated as a job title
SKIP_TITLE_PHRASES = [
    "explore verified roles",
    "explore roles",
    "verified roles",
    "across the network",
    "submit your",
    "find similar",
    "post a job",
    "quick actions",
    "login",
    "sign up",
    "how to",
]

def is_bad_title(title):
    t = title.lower()
    # UI/promo phrases
    for phrase in SKIP_TITLE_PHRASES:
        if phrase in t:
            return True
    # Starts with "Posted:" — timestamp leaked into title
    if title.startswith("Posted:"):
        return True
    # Looks like a plain date/time stamp
    if re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', title):
        return True
    # Too long = probably UI text
    if len(title) > 80:
        return True
    return False

# ── Selenium helpers ─────────────────────────────────────────────────────────
def get_chrome_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    driver.implicitly_wait(5)
    return driver

def wait_for_react(driver, timeout=30):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return document.getElementById('root') && "
                "document.getElementById('root').children.length > 0"
            )
        )
        time.sleep(3)
        h = driver.execute_script("return document.body.scrollHeight")
        log.info("React ready. Height: %d", h)
        return h
    except Exception as e:
        log.warning("React wait timed out: %s", e)
        return 0

def load_search_page(driver, search_term):
    params = urlencode({"search": search_term})
    url = f"{JOBS_BASE_URL}?{params}"
    log.info("Loading: %s", url)
    driver.get(url)
    return wait_for_react(driver)

def scroll_all(driver):
    time.sleep(1)
    last_height = driver.execute_script("return document.body.scrollHeight")
    no_change = 0
    attempts = 0
    while attempts < 150:
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(0.8)
        attempts += 1
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            no_change += 1
            if no_change >= 5:
                break
        else:
            no_change = 0
            last_height = new_height
    log.info("Scrolled %d times, height: %d", attempts, last_height)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

# ── Core parser (with title relevance fix) ───────────────────────────────────
def parse_jobs_from_page(driver, seen_emails, cc_secret):
    jobs = []
    email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    body_text = driver.find_element(By.TAG_NAME, "body").text
    log.info("Emails on page: %d", body_text.count("@"))

    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    job_blocks = []
    current = []
    for line in lines:
        current.append(line)
        if line.startswith("Posted:"):
            job_blocks.append(current[:])
            current = []

    log.info("Job blocks: %d", len(job_blocks))

    for block in job_blocks:
        block_text = '\n'.join(block)
        if not is_posted_recently(block_text):
            continue
        emails_found = email_pattern.findall(block_text)
        if not emails_found:
            continue
        email_addr = emails_found[0].lower()
        if email_addr in seen_emails:
            continue
        if any(skip in email_addr for skip in SKIP_EMAILS):
            continue

        # ── Title selection (fixed) ──────────────────────────────────────────
        title = None
        for line in block:
            # Skip known UI / noise lines
            if line.lower() in SKIP_LINES:
                continue
            if line.startswith("Posted:") or line.startswith("Score:"):
                continue
            if "@" in line:
                continue
            # Skip visa / work-auth / experience tokens
            if re.match(
                r'^(C2C|W2|1099|ALL|REMOTE|ONSITE|HYBRID|REMOTE\/ONSITE HYBRID'
                r'|EXP N\/A|\d+[\-\s]?\d*\s*YRS?|US CITI\w*|H1B|GREEN CARD'
                r'|OPT|CPT|GC|USC|ACTIVE)$',
                line, re.IGNORECASE
            ):
                continue
            # Skip "City, ST" location lines
            if re.match(r'^[A-Za-z\s\.]+,\s*[A-Z]{2}$', line):
                continue
            # Skip UI/promo garbage
            if is_bad_title(line):
                log.info("  SKIP bad title: %s", line[:60])
                continue
            # ── NEW: only accept lines with a relevant tech keyword ──────────
            if not is_relevant_title(line):
                log.info("  SKIP irrelevant title: %s", line[:60])
                continue
            title = line
            break

        # Fallback — use default rather than garbage subject
        if not title:
            title = "DevOps / Cloud Engineer"
            log.info("  FALLBACK title used for: %s", email_addr)

        seen_emails.add(email_addr)
        jobs.append({"title": title, "email": email_addr, "cc_secret": cc_secret})
        log.info("  MATCH: %s -> %s", title[:55], email_addr)

    return jobs

# ── Resume loader ─────────────────────────────────────────────────────────────
def get_resume():
    fname = "resume_lingaraju_b64.txt"
    if not Path(fname).exists():
        raise ValueError("Resume file not found!")
    raw = Path(fname).read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16').strip()
    else:
        text = raw.decode('latin-1').strip()
    lines = [l for l in text.splitlines() if not l.startswith("-----")]
    b64 = re.sub(r'\s+', '', "".join(lines))
    missing = len(b64) % 4
    if missing:
        b64 += "=" * (4 - missing)
    return base64.b64decode(b64)

# ── Email sender ──────────────────────────────────────────────────────────────
def send_email(job, smtp_server):
    smtp_email = os.environ["SMTP_EMAIL"]
    to_email = job["email"]
    cc_email = os.environ.get(job["cc_secret"], "")
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
    log.info(">>> SENT: %s | Subject: %s", to_email, subject)
    time.sleep(5)

def log_sent(job):
    csv_path = "logs/sent_log_hiring42.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,email,title,cc\n")
        cc = os.environ.get(job["cc_secret"], "none")
        f.write('{}, "{}","{}","{}"\n'.format(
            datetime.now().isoformat(), job["email"], job["title"], cc))

# ── Send loop ─────────────────────────────────────────────────────────────────
def send_jobs(jobs, replied_senders, daily_send_count, smtp_server, sent):
    smtp_email = os.environ["SMTP_EMAIL"]
    for job in jobs:
        if daily_send_count >= MAX_DAILY_SENDS:
            log.warning("DAILY LIMIT REACHED.")
            break
        email_addr = job["email"]
        if email_addr in replied_senders:
            log.info("SKIP (already sent): %s", email_addr)
            continue
        try:
            log.info("SENDING [%d/%d]: %s -> %s",
                     daily_send_count + 1, MAX_DAILY_SENDS,
                     job["title"][:45], email_addr)
            send_email(job, smtp_server)
            log_sent(job)
            replied_senders.add(email_addr)
            daily_send_count += 1
            sent += 1
            save_daily_dedup(replied_senders, daily_send_count)
        except Exception as e:
            log.error("Send error %s: %s", email_addr, e)
            try:
                smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
                smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
                log.info("SMTP reconnected")
            except Exception as se:
                log.error("SMTP reconnect failed: %s", se)
                break
    return replied_senders, daily_send_count, sent, smtp_server

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42.com)")
    log.info("Date filter: %s", " | ".join(get_valid_posted_strings()))
    log.info("=" * 70)

    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    replied_senders, daily_send_count = load_daily_dedup()
    if MAX_DAILY_SENDS - daily_send_count <= 0:
        log.warning("Daily limit reached. Stopping.")
        return

    smtp_email = os.environ["SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
        log.info("SMTP connected")
    except Exception as e:
        log.error("SMTP failed: %s", e)
        return

    driver = get_chrome_driver()
    seen_emails = set(replied_senders)
    sent = 0

    try:
        for kw in SEARCH_KEYWORDS:
            if daily_send_count >= MAX_DAILY_SENDS:
                break

            search_term = kw["search"]
            cc_secret   = kw["cc_secret"]
            log.info("=" * 50)
            log.info("Searching: '%s'", search_term)

            height = load_search_page(driver, search_term)
            if height < 1500:
                log.warning("Page too small (height=%d) - skipping '%s'", height, search_term)
                continue

            scroll_all(driver)

            jobs = parse_jobs_from_page(driver, seen_emails, cc_secret)
            log.info("New jobs for '%s': %d", search_term, len(jobs))

            if jobs:
                replied_senders, daily_send_count, sent, smtp_server = send_jobs(
                    jobs, replied_senders, daily_send_count, smtp_server, sent)

            time.sleep(1)

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
    log.info("Done - Sent: %d | Daily: %d/%d", sent, daily_send_count, MAX_DAILY_SENDS)
    log.info("=" * 70)

if __name__ == "__main__":
    main()
