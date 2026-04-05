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
#  keywords     = title must contain at least one (sends email)
#  search_terms = what to search on hiring42.com
# =============================================================================
PROFILES = [
    {
        "name": "DevOps Engineer",
        "keywords": [
            "devops engineer",
            "sr. devops",
            "sr devops",
            "senior devops",
            "lead devops",
            "devops lead",
            "devsecops",
            "dev ops",
            "ci/cd engineer",
            "build and release",
            "release engineer",
            "pipeline engineer",
            "devops",
        ],
        "search_terms": [
            "devops",
            "devsecops",
            "ci/cd engineer",
            "build and release",
            "pipeline engineer",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
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
        "search_terms": [
            "cloud engineer",
            "aws engineer",
            "azure engineer",
            "gcp engineer",
            "platform engineer",
            "infrastructure engineer",
            "cloud architect",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_CLOUD",
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
            "sre",
        ],
        "search_terms": [
            "sre",
            "site reliability",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_SRE",
    },
    {
        "name": "Kubernetes / Container Engineer",
        "keywords": [
            "kubernetes engineer",
            "kubernetes developer",
            "k8s engineer",
            "docker engineer",
            "openshift engineer",
            "container engineer",
            "helm engineer",
            "kubernetes",
            "docker",
            "openshift",
        ],
        "search_terms": [
            "kubernetes",
            "docker",
            "openshift",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
    },
    {
        "name": "Terraform / Automation Engineer",
        "keywords": [
            "terraform engineer",
            "terraform developer",
            "infrastructure automation",
            "ansible engineer",
            "gitops engineer",
            "terraform",
            "ansible",
            "argocd",
            "helm",
            "gitlab",
            "jenkins",
        ],
        "search_terms": [
            "terraform",
            "ansible",
            "jenkins",
        ],
        "resume_file": "resume_lingaraju_b64.txt",
        "cc_secret":   "CC_DEVOPS",
    },
]

def get_profile_for_title(title):
    """Return best matching profile for a job title, or None."""
    t = title.lower()
    for profile in PROFILES:
        if any(kw in t for kw in profile["keywords"]):
            return profile
    return None

def is_relevant_title(title):
    return get_profile_for_title(title) is not None

def build_search_list():
    """Flat deduplicated list of {search, profile} from all profiles."""
    seen   = set()
    result = []
    for profile in PROFILES:
        for term in profile["search_terms"]:
            if term not in seen:
                seen.add(term)
                result.append({"search": term, "profile": profile})
    return result

# =============================================================================
#  DATE HELPERS
# =============================================================================
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
    data = {
        "date":       get_today_date(),
        "senders":    sorted(list(senders)),
        "send_count": send_count,
    }
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
#  SELENIUM / BROWSER HELPERS
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
    """Wait for React root with content-based fallback."""
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
    """Load hiring42 search page with up to 3 retries."""
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
    """Scroll to bottom to load all lazy-loaded job cards."""
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
#  PAGE PARSER
# =============================================================================
def parse_jobs_from_page(driver, seen_emails, profile):
    """
    Parse job cards from hiring42 page body text.
    Card layout:
        <Job Title>
        <C2C> <W2> <ONSITE> <ALL> <N YRS>   (badge tokens)
        <City, ST>
        <email@domain.com>
        Posted: Mmm DD, YY, HH:MM am/pm      <- block boundary
        Score: X.XX
        ACTIVE
    """
    jobs          = []
    email_pattern = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    body_text     = driver.find_element(By.TAG_NAME, "body").text
    log.info("@ symbols on page: %d", body_text.count("@"))

    lines = [l.strip() for l in body_text.split('\n') if l.strip()]

    # Each block ends at the "Posted:" line
    job_blocks = []
    current    = []
    for line in lines:
        current.append(line)
        if re.match(r'^Posted:', line, re.IGNORECASE):
            job_blocks.append(current[:])
            current = []

    log.info("Job blocks found: %d", len(job_blocks))

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

        # Title = first meaningful line; must match profile keywords
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
                continue
            if is_bad_title(line):
                log.info("  SKIP bad title: %s", line[:60])
                continue
            if is_relevant_title(line):
                title = line
                break
            log.info("  SKIP irrelevant title: %s", line[:60])
            break

        if not title:
            log.info("  NO relevant title for: %s", email_addr)
            continue

        seen_emails.add(email_addr)
        jobs.append({
            "title":        title,
            "email":        email_addr,
            "cc_secret":    profile["cc_secret"],
            "resume_file":  profile["resume_file"],
            "profile_name": profile["name"],
        })
        log.info("  MATCH [%s]: %s -> %s", profile["name"], title[:50], email_addr)

    return jobs

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

    msg = MIMEMultipart()
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
    time.sleep(5)

def log_sent(job):
    csv_path = "logs/sent_log_hiring42.csv"
    is_new   = not os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,email,title,profile,cc\n")
        cc = os.environ.get(job["cc_secret"], "none")
        f.write('{}, "{}","{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            job["email"],
            job["title"],
            job.get("profile_name", ""),
            cc,
        ))

# =============================================================================
#  SEND LOOP
# =============================================================================
def send_jobs(jobs, replied_senders, daily_send_count, smtp_server, sent):
    smtp_email = os.environ["SMTP_EMAIL"]
    for job in jobs:
        if daily_send_count >= MAX_DAILY_SENDS:
            log.warning("DAILY LIMIT REACHED.")
            break
        email_addr = job["email"]
        if email_addr in replied_senders:
            log.info("SKIP (already sent today): %s", email_addr)
            continue
        try:
            log.info("SENDING [%d/%d]: %s -> %s",
                     daily_send_count + 1, MAX_DAILY_SENDS,
                     job["title"][:45], email_addr)
            send_email(job, smtp_server)
            log_sent(job)
            replied_senders.add(email_addr)
            daily_send_count += 1
            sent             += 1
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

# =============================================================================
#  MAIN
# =============================================================================
def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42.com)")
    log.info("Date filter: %s", " | ".join(get_valid_posted_strings()))
    log.info("=" * 70)

    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing  = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    replied_senders, daily_send_count = load_daily_dedup()
    if MAX_DAILY_SENDS - daily_send_count <= 0:
        log.warning("Daily limit already reached. Stopping.")
        return

    smtp_email  = os.environ["SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp_server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])
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
                break

            search_term = item["search"]
            profile     = item["profile"]
            log.info("=" * 50)
            log.info("Searching: '%s'  [Profile: %s]", search_term, profile["name"])

            height = load_search_page(driver, search_term)
            if height < 1500:
                log.warning("Page too small (height=%d) - skipping '%s'", height, search_term)
                continue

            scroll_all(driver)

            jobs = parse_jobs_from_page(driver, seen_emails, profile)
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
    log.info("Done - Sent: %d | Daily total: %d/%d", sent, daily_send_count, MAX_DAILY_SENDS)
    log.info("=" * 70)

if __name__ == "__main__":
    main()
