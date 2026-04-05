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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent_hiring42.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DEDUP_FILE      = Path("logs") / "daily_replied_senders_hiring42.json"
MAX_DAILY_SENDS = 450
JOBS_BASE_URL   = "https://www.hiring42.com/all_jobs"

# =============================================================================
#  EMAIL BODY
# =============================================================================
SHARED_REPLY = """Hi,

In response to your job posting.
Here I am attaching my consultant's resume.
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Best regards,
Lingaraju Modhala
Phone: +1 940 281 5324
Email: rajumodhala777@gmail.com"""

# =============================================================================
#  JOB PROFILES
# =============================================================================
PROFILES = [
    {
        "name": "DevOps Engineer",
        "keywords": [
            "devops", "devsecops", "dev ops",
            "ci/cd", "build and release", "release engineer", "pipeline engineer",
        ],
        "search_terms": ["devops", "devsecops", "ci/cd engineer", "build and release", "pipeline engineer"],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
    },
    {
        "name": "Cloud Engineer",
        "keywords": [
            "cloud engineer", "cloud architect", "cloud infrastructure",
            "aws", "azure", "gcp", "platform engineer", "infrastructure engineer",
        ],
        "search_terms": ["cloud engineer", "aws engineer", "azure engineer", "gcp engineer",
                         "platform engineer", "infrastructure engineer", "cloud architect"],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_CLOUD",
    },
    {
        "name": "Site Reliability Engineer",
        "keywords": ["site reliability", "sre", "reliability engineer"],
        "search_terms": ["sre", "site reliability"],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_SRE",
    },
    {
        "name": "Kubernetes / Container Engineer",
        "keywords": ["kubernetes", "k8s", "docker", "openshift", "container engineer", "helm engineer"],
        "search_terms": ["kubernetes", "docker", "openshift"],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
    },
    {
        "name": "Terraform / Automation Engineer",
        "keywords": ["terraform", "ansible", "argocd", "gitops",
                     "infrastructure automation", "jenkins", "gitlab", "helm"],
        "search_terms": ["terraform", "ansible", "jenkins"],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
    },
]

# =============================================================================
#  PROFILE MATCHING
# =============================================================================
def get_profile_for_title(title):
    t = title.lower()
    for profile in PROFILES:
        if any(kw in t for kw in profile["keywords"]):
            return profile
    return None

def is_relevant_title(title):
    return get_profile_for_title(title) is not None

def build_search_list():
    seen, result = set(), []
    for profile in PROFILES:
        for term in profile["search_terms"]:
            if term not in seen:
                seen.add(term)
                result.append({"search": term, "profile": profile})
    return result

# =============================================================================
#  DATE HELPERS  —  TODAY ONLY
# =============================================================================
def get_today_date():
    return str(date.today())

def get_valid_posted_strings():
    """Today's date in both zero-padded and non-padded formats."""
    d = datetime.now()
    valid = set()
    valid.add("Posted: " + d.strftime("%b %d, %y"))   # e.g. Apr 05, 26
    try:
        valid.add("Posted: " + d.strftime("%b %-d, %y"))  # e.g. Apr 5, 26 (Linux)
    except Exception:
        valid.add("Posted: " + d.strftime("%b %#d, %y"))  # Windows fallback
    return list(valid)

def is_posted_today(text):
    return any(d in text for d in get_valid_posted_strings())

# =============================================================================
#  DEDUP HELPERS
# =============================================================================
def load_daily_dedup():
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if data.get("date") == get_today_date():
                    senders    = set(data.get("senders", []))
                    send_count = data.get("send_count", 0)
                    log.info("TODAY (%s): %d senders already replied, %d/%d sent",
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

# =============================================================================
#  SKIP / NOISE LISTS
# =============================================================================
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
    "search",
}

SKIP_TITLE_PHRASES = [
    "explore verified roles", "explore roles", "verified roles",
    "across the network", "submit your", "find similar",
    "post a job", "quick actions", "login", "sign up", "how to",
]

INLINE_NOISE = re.compile(
    r'^(C2C|W2|1099|ALL|REMOTE|ONSITE|HYBRID|REMOTE\/ONSITE HYBRID'
    r'|EXP N\/A|\d+[\-\s]?\d*\s*YRS?|US CITI\w*|H1B|GREEN CARD'
    r'|OPT|CPT|GC|USC|ACTIVE|SCORE.*|Score.*)$',
    re.IGNORECASE
)

def is_bad_title(title):
    t = title.lower()
    for phrase in SKIP_TITLE_PHRASES:
        if phrase in t:
            return True
    if title.startswith("Posted:"):
        return True
    if re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', title):
        return True
    if len(title) > 80:
        return True
    return False

# =============================================================================
#  SELENIUM HELPERS
# =============================================================================
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

def wait_for_react(driver, timeout=60):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return document.getElementById('root') && "
                "document.getElementById('root').children.length > 0"
            )
        )
        WebDriverWait(driver, 20).until(
            lambda d: "@" in d.find_element(By.TAG_NAME, "body").text
            or "Posted:" in d.find_element(By.TAG_NAME, "body").text
        )
        time.sleep(3)
        h = driver.execute_script("return document.body.scrollHeight")
        log.info("React ready. Height: %d", h)
        return h
    except Exception as e:
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            h    = driver.execute_script("return document.body.scrollHeight")
            if "Posted:" in body or "@" in body:
                log.info("React timeout but page has content (height=%d) - continuing", h)
                return h
        except Exception:
            pass
        log.warning("React wait timed out: %s", e)
        return 0

def load_search_page(driver, search_term, retries=3):
    params = urlencode({"search": search_term})
    url    = f"{JOBS_BASE_URL}?{params}"
    for attempt in range(1, retries + 1):
        try:
            log.info("Loading (attempt %d/%d): %s", attempt, retries, url)
            driver.get(url)
            h = wait_for_react(driver)
            if h > 0:
                return h
            log.warning("Empty page on attempt %d - waiting 15s", attempt)
            time.sleep(15)
        except Exception as e:
            log.warning("Load error attempt %d: %s", attempt, e)
            time.sleep(15)
    log.warning("All %d attempts failed for '%s'", retries, search_term)
    return 0

def scroll_all(driver):
    """Scroll full page so all lazy-loaded cards are visible."""
    time.sleep(1)
    last_height = driver.execute_script("return document.body.scrollHeight")
    no_change   = 0
    attempts    = 0
    while attempts < 150:
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(0.8)
        attempts  += 1
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            no_change += 1
            if no_change >= 5:
                break
        else:
            no_change   = 0
            last_height = new_height
    log.info("Scrolled %d times, final height: %d", attempts, last_height)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

# =============================================================================
#  PAGE PARSER  —  generator: yields one matched job at a time
# =============================================================================
def iter_jobs_from_page(driver, seen_emails):
    """
    Scans ALL job blocks on the page.
    Yields only jobs posted TODAY that match a profile.
    seen_emails is updated immediately on each yield to prevent duplicates.

    Block layout in body text:
        <Job Title>
        <badge tokens: C2C  W2  ONSITE  ALL  N YRS>
        <City, ST>
        <email@domain.com>
        Posted: Mmm DD, YY, HH:MM am/pm   ← block boundary
        Score: X.XX
        ACTIVE
    """
    email_pat = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    body_text = driver.find_element(By.TAG_NAME, "body").text
    log.info("@ symbols on page: %d", body_text.count("@"))

    lines = [l.strip() for l in body_text.split('\n') if l.strip()]

    # Split body into blocks — each block ends at "Posted:" line
    job_blocks, current = [], []
    for line in lines:
        current.append(line)
        if re.match(r'^Posted:', line, re.IGNORECASE):
            job_blocks.append(current[:])
            current = []

    log.info("Total blocks on page: %d", len(job_blocks))

    today_total   = 0
    matched_total = 0

    for block in job_blocks:
        block_text = '\n'.join(block)

        # ── Filter: today only ─────────────────────────────────────────────
        if not is_posted_today(block_text):
            continue
        today_total += 1

        # ── Extract email ──────────────────────────────────────────────────
        emails = email_pat.findall(block_text)
        if not emails:
            continue
        email_addr = emails[0].lower()

        if email_addr in seen_emails:
            log.info("  SKIP (already sent today): %s", email_addr)
            continue
        if any(skip in email_addr for skip in SKIP_EMAILS):
            continue

        # ── Find job title: scan ALL lines (no early break on non-match) ───
        title = None
        for line in block:
            if not line:
                continue
            if line.lower() in SKIP_LINES:
                continue
            if re.match(r'^(Posted:|Score:)', line, re.IGNORECASE):
                continue
            if "@" in line:
                continue
            if INLINE_NOISE.match(line):
                continue
            if re.match(r'^[A-Za-z\s\.\-]+,\s*[A-Z]{2}$', line):
                continue   # "Atlanta, GA" style lines
            if is_bad_title(line):
                log.info("  SKIP bad title: %s", line[:60])
                continue
            if is_relevant_title(line):
                title = line
                break
            # ← intentionally NO break here: keep scanning next lines
            log.info("  SKIP irrelevant line: %s", line[:60])

        if not title:
            log.info("  TODAY but no profile match: %s", email_addr)
            continue

        matched_profile = get_profile_for_title(title)
        matched_total  += 1
        log.info("  MATCH [%s]: %s -> %s",
                 matched_profile["name"], title[:50], email_addr)

        # Mark seen immediately so duplicate blocks don't double-send
        seen_emails.add(email_addr)

        yield {
            "title":        title,
            "email":        email_addr,
            "cc_secret":    matched_profile["cc_secret"],
            "resume_file":  matched_profile["resume_file"],
            "profile_name": matched_profile["name"],
        }

    log.info("Page summary: %d posted today | %d matched & sent", today_total, matched_total)

# =============================================================================
#  RESUME LOADER
# =============================================================================
def get_resume(fname="resume_lingaraju_b64.txt"):
    if not Path(fname).exists():
        raise ValueError(f"Resume file not found: {fname}")
    raw = Path(fname).read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16').strip()
    else:
        text = raw.decode('latin-1').strip()
    lines = [l for l in text.splitlines() if not l.startswith("-----")]
    b64   = re.sub(r'\s+', '', "".join(lines))
    missing = len(b64) % 4
    if missing:
        b64 += "=" * (4 - missing)
    return base64.b64decode(b64)

# =============================================================================
#  EMAIL SENDER
# =============================================================================
def send_email(job, smtp_server):
    smtp_email = os.environ["SMTP_EMAIL"]
    to_email   = job["email"]
    cc_email   = os.environ.get(job["cc_secret"], "")
    subject    = "Re: " + job["title"]

    msg            = MIMEMultipart()
    msg["From"]    = smtp_email
    msg["To"]      = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email

    msg.attach(MIMEText(SHARED_REPLY, "plain"))

    resume_bytes = get_resume(job.get("resume_file", "resume_lingaraju_b64.txt"))
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
    log.info(">>> SENT [%s]: %s | Subject: %s",
             job.get("profile_name", ""), to_email, subject)

def log_sent(job):
    csv_path = "logs/sent_log_hiring42.csv"
    is_new   = not os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,email,title,profile,cc\n")
        cc = os.environ.get(job["cc_secret"], "none")
        f.write('{}, "{}","{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            job["email"], job["title"],
            job.get("profile_name", ""), cc,
        ))

# =============================================================================
#  SMTP HELPERS
# =============================================================================
def connect_smtp():
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    server.login(os.environ["SMTP_EMAIL"], os.environ["SMTP_APP_PASSWORD"])
    return server

def reconnect_smtp(old_server):
    try:
        old_server.quit()
    except Exception:
        pass
    try:
        server = connect_smtp()
        log.info("SMTP reconnected")
        return server
    except Exception as e:
        log.error("SMTP reconnect failed: %s", e)
        return None

# =============================================================================
#  MAIN
# =============================================================================
def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42.com)")
    log.info("Today filter: %s", " | ".join(get_valid_posted_strings()))
    log.info("=" * 70)

    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing  = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    replied_senders, daily_send_count = load_daily_dedup()
    if daily_send_count >= MAX_DAILY_SENDS:
        log.warning("Daily limit already reached. Stopping.")
        return

    try:
        smtp_server = connect_smtp()
        log.info("SMTP connected")
    except Exception as e:
        log.error("SMTP failed: %s", e)
        return

    driver      = get_chrome_driver()
    seen_emails = set(replied_senders)
    sent        = 0
    search_list = build_search_list()

    log.info("Profiles: %d | Search terms: %d", len(PROFILES), len(search_list))

    try:
        for item in search_list:
            if daily_send_count >= MAX_DAILY_SENDS:
                log.warning("DAILY LIMIT REACHED. Stopping.")
                break

            search_term = item["search"]
            log.info("=" * 50)
            log.info("Searching: '%s'", search_term)

            height = load_search_page(driver, search_term)
            if height < 1500:
                log.warning("Page too small (height=%d) - skipping '%s'", height, search_term)
                continue

            scroll_all(driver)

            # ── KEY CHANGE: send immediately on each match, don't batch ───
            for job in iter_jobs_from_page(driver, seen_emails):
                if daily_send_count >= MAX_DAILY_SENDS:
                    log.warning("DAILY LIMIT REACHED mid-page. Stopping.")
                    break

                log.info("SENDING NOW [%d/%d]: %s -> %s",
                         daily_send_count + 1, MAX_DAILY_SENDS,
                         job["title"][:45], job["email"])
                try:
                    send_email(job, smtp_server)
                    log_sent(job)
                    replied_senders.add(job["email"])
                    daily_send_count += 1
                    sent             += 1
                    save_daily_dedup(replied_senders, daily_send_count)
                    time.sleep(5)
                except Exception as e:
                    log.error("Send error %s: %s", job["email"], e)
                    smtp_server = reconnect_smtp(smtp_server)
                    if smtp_server is None:
                        log.error("Cannot reconnect SMTP. Stopping.")
                        raise SystemExit(1)

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
    log.info("Done - Sent: %d | Daily total: %d/%d", sent, daily_send_count, MAX_DAILY_SENDS)
    log.info("=" * 70)


if __name__ == "__main__":
    main()
