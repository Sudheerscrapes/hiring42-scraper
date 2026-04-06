import os, base64, logging, re, json, time, smtplib, sys
from pathlib import Path
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import requests

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent_hiring42_api.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# =============================================================================
#  CONFIG
# =============================================================================
API_URL = "https://m9l0gpbw58.execute-api.ap-south-1.amazonaws.com/Prod/get-jobs"
HEADERS = {
    "Content-Type": "application/json",
    "Origin":       "https://www.hiring42.com",
    "Referer":      "https://www.hiring42.com/",
}

DEDUP_FILE      = Path("logs") / "daily_replied_senders_api.json"
MAX_DAILY_SENDS = 450

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
        "cc_secret":   "CC_DEVOPS",
        "resume_file": "resume_lingaraju_b64.txt",
    },
    {
        "name": "Cloud Engineer",
        "keywords": [
            "cloud engineer", "cloud architect", "cloud infrastructure",
            "aws", "azure", "gcp", "platform engineer", "infrastructure engineer",
        ],
        "cc_secret":   "CC_CLOUD",
        "resume_file": "resume_lingaraju_b64.txt",
    },
    {
        "name": "Site Reliability Engineer",
        "keywords": ["site reliability", "sre", "reliability engineer"],
        "cc_secret":   "CC_SRE",
        "resume_file": "resume_lingaraju_b64.txt",
    },
    {
        "name": "Kubernetes / Container Engineer",
        "keywords": ["kubernetes", "k8s", "docker", "openshift", "container engineer"],
        "cc_secret":   "CC_DEVOPS",
        "resume_file": "resume_lingaraju_b64.txt",
    },
    {
        "name": "Terraform / Automation Engineer",
        "keywords": [
            "terraform", "ansible", "argocd", "gitops",
            "infrastructure automation", "jenkins", "gitlab", "helm",
        ],
        "cc_secret":   "CC_DEVOPS",
        "resume_file": "resume_lingaraju_b64.txt",
    },
]

SKIP_EMAILS = [
    "rajumodhala777@gmail.com",
    "sudheeritservices1@gmail.com",
    "noreply@",
    "mailer-daemon@",
]

def get_profile_for_title(title):
    t = title.lower()
    for profile in PROFILES:
        if any(kw in t for kw in profile["keywords"]):
            return profile
    return None

# =============================================================================
#  DATE HELPERS
#
#  ROOT CAUSE of "0 jobs found":
#  The script computed "today = Apr 06 00:00 local" = 1775433600
#  But ALL jobs on page 1 were timestamped Apr 05 (1775284620 to 1775409840)
#  So zero jobs passed the filter.
#
#  FIX: Use a rolling LAST-24-HOURS window instead of calendar midnight.
#  This always catches jobs posted in the past 24 hours regardless of timezone.
# =============================================================================
def get_last_24h_range():
    now       = int(time.time())
    start     = now - 86400
    return start, now

def get_specific_day_range(year, month, day):
    """Calendar day range in LOCAL time."""
    start = int(datetime(year, month, day, 0, 0, 0).timestamp())
    end   = start + 86400
    return start, end

def ts_to_str(ts):
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y %H:%M")

# =============================================================================
#  API FETCH — with retry + longer delay between pages
#
#  ROOT CAUSE of 500 on page 2:
#  The API was being called too fast (0.3s delay was not enough).
#  Also the error handler was catching HTTPError but .response was None
#  because requests raised a connection error, not HTTP error.
#  FIX: increase delay to 2s, add 3 retries per page with exponential backoff.
# =============================================================================
def fetch_all_jobs():
    all_items          = []
    last_evaluated_key = None
    page               = 1

    while True:
        payload = {
            "context":            "all_jobs",
            "last_evaluated_key": last_evaluated_key,
            "status":             "active",
            "uid":                None,
        }

        log.info("Fetching page %d (last_key=%s) ...", page,
                 last_evaluated_key.get("id") if last_evaluated_key else "null")

        # ── Retry loop per page ───────────────────────────────────────────
        data      = None
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            try:
                resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break   # success
            except Exception as e:
                body = ""
                try:
                    body = e.response.text[:300]
                except Exception:
                    pass
                log.warning("  Page %d attempt %d/%d failed: %s %s",
                            page, attempt, max_tries, e, body)
                if attempt < max_tries:
                    wait = attempt * 3   # 3s, 6s
                    log.info("  Retrying in %ds ...", wait)
                    time.sleep(wait)

        if data is None:
            log.error("Page %d failed after %d attempts — stopping pagination.", page, max_tries)
            break

        items = data.get("Items", [])
        if not items:
            log.info("Empty page %d — done.", page)
            break

        all_items.extend(items)
        log.info("  Page %d: %d items (total: %d)", page, len(items), len(all_items))

        last_evaluated_key = data.get("LastEvaluatedKey")
        if not last_evaluated_key:
            log.info("No more pages.")
            break

        page   += 1
        time.sleep(2)   # 2s between pages — enough for API rate limit

    return all_items

# =============================================================================
#  FILTER
# =============================================================================
def filter_by_range(jobs, start_ts, end_ts):
    return [j for j in jobs if start_ts <= j.get("ts", 0) <= end_ts]

# =============================================================================
#  DEDUP
# =============================================================================
def get_today_str():
    return str(date.today())

def load_daily_dedup():
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                if data.get("date") == get_today_str():
                    senders    = set(data.get("senders", []))
                    send_count = data.get("send_count", 0)
                    log.info("TODAY: %d already sent, %d/%d limit",
                             len(senders), send_count, MAX_DAILY_SENDS)
                    return senders, send_count
                else:
                    log.info("NEW DAY — Resetting dedup")
                    return set(), 0
        except Exception as e:
            log.warning("Could not load dedup: %s", e)
    return set(), 0

def save_daily_dedup(senders, send_count=0):
    data = {
        "date":       get_today_str(),
        "senders":    sorted(list(senders)),
        "send_count": send_count,
    }
    with open(DEDUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log.info("SAVED: %d senders, %d sent today", len(senders), send_count)

# =============================================================================
#  RESUME
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
#  EMAIL
# =============================================================================
def connect_smtp():
    server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    server.login(os.environ["SMTP_EMAIL"], os.environ["SMTP_APP_PASSWORD"])
    return server

def reconnect_smtp(old):
    try: old.quit()
    except: pass
    try:
        s = connect_smtp()
        log.info("SMTP reconnected")
        return s
    except Exception as e:
        log.error("SMTP reconnect failed: %s", e)
        return None

def send_email(job, smtp_server):
    smtp_email = os.environ["SMTP_EMAIL"]
    to_email   = job["uid"]
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
    part.add_header("Content-Disposition",
                    'attachment; filename="Resume_Lingaraju_Modhala.docx"')
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
    csv_path = "logs/sent_log_api.csv"
    is_new   = not os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,email,title,profile,loc\n")
        f.write('{}, "{}","{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            job["uid"], job["title"],
            job.get("profile_name", ""), job.get("loc", ""),
        ))

# =============================================================================
#  CORE
# =============================================================================
def run(start_ts, end_ts, label, send_emails=True):
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (hiring42 API)")
    log.info("Range : %s  [%s  ->  %s]", label,
             ts_to_str(start_ts), ts_to_str(end_ts))
    log.info("Mode  : %s", "SEND EMAILS" if send_emails else "VIEW ONLY")
    log.info("=" * 70)

    all_jobs = fetch_all_jobs()
    log.info("Total active jobs in API : %d", len(all_jobs))

    # Debug: show ts range of fetched jobs
    if all_jobs:
        ts_vals = [j["ts"] for j in all_jobs]
        log.info("Fetched ts range: %s  to  %s",
                 ts_to_str(min(ts_vals)), ts_to_str(max(ts_vals)))

    jobs = filter_by_range(all_jobs, start_ts, end_ts)
    log.info("Jobs in range            : %d", len(jobs))

    if not jobs:
        log.info("No jobs found in range.")
        # Show what IS available so user can pick the right date
        if all_jobs:
            log.info("Available job dates in API:")
            dates_seen = set()
            for j in sorted(all_jobs, key=lambda x: x["ts"], reverse=True):
                d = datetime.fromtimestamp(j["ts"]).strftime("%Y-%m-%d")
                if d not in dates_seen:
                    dates_seen.add(d)
                    log.info("  %s", d)
        return []

    # Print all found jobs
    log.info("-" * 70)
    log.info("ALL JOBS IN RANGE:")
    for j in sorted(jobs, key=lambda x: x["ts"], reverse=True):
        profile = get_profile_for_title(j["title"])
        flag    = "✓ MATCH" if profile else "  -----"
        log.info("  %s [%s] %s | %s | %s",
                 flag, ts_to_str(j["ts"]), j["title"], j.get("loc", ""), j["uid"])
    log.info("-" * 70)

    if not send_emails:
        return jobs

    # ── Send emails ───────────────────────────────────────────────────────
    required = ["SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing  = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return jobs

    replied_senders, daily_send_count = load_daily_dedup()
    if daily_send_count >= MAX_DAILY_SENDS:
        log.warning("Daily limit already reached.")
        return jobs

    try:
        smtp_server = connect_smtp()
        log.info("SMTP connected")
    except Exception as e:
        log.error("SMTP failed: %s", e)
        return jobs

    sent = 0
    for job in sorted(jobs, key=lambda x: x["ts"], reverse=True):
        if daily_send_count >= MAX_DAILY_SENDS:
            log.warning("DAILY LIMIT REACHED.")
            break

        email_addr = job.get("uid", "").lower()
        title      = job.get("title", "")

        if not email_addr or any(s in email_addr for s in SKIP_EMAILS):
            continue
        if email_addr in replied_senders:
            log.info("SKIP (already sent): %s", email_addr)
            continue

        profile = get_profile_for_title(title)
        if not profile:
            log.info("NO MATCH: %s", title)
            continue

        job["profile_name"] = profile["name"]
        job["cc_secret"]    = profile["cc_secret"]
        job["resume_file"]  = profile["resume_file"]

        log.info("MATCH [%s]: %s -> %s", profile["name"], title, email_addr)
        log.info("SENDING NOW [%d/%d]", daily_send_count + 1, MAX_DAILY_SENDS)

        try:
            send_email(job, smtp_server)
            log_sent(job)
            replied_senders.add(email_addr)
            daily_send_count += 1
            sent             += 1
            save_daily_dedup(replied_senders, daily_send_count)
            time.sleep(5)
        except Exception as e:
            log.error("Send error %s: %s", email_addr, e)
            smtp_server = reconnect_smtp(smtp_server)
            if smtp_server is None:
                break

    try:
        smtp_server.quit()
    except Exception:
        pass

    log.info("=" * 70)
    log.info("Done — Sent: %d | Daily total: %d/%d", sent, daily_send_count, MAX_DAILY_SENDS)
    log.info("=" * 70)
    return jobs

# =============================================================================
#  ENTRY POINT
#
#  Default (last 24 hours, send emails):
#      python agent_hiring42_api.py
#
#  View only — last 24 hours (no emails):
#      python agent_hiring42_api.py --view
#
#  View specific date (no emails):
#      python agent_hiring42_api.py --view --date 2026-04-05
#
#  Run agent on specific date (send emails):
#      python agent_hiring42_api.py --date 2026-04-05
# =============================================================================
if __name__ == "__main__":
    view_only   = "--view" in sys.argv
    target_date = None

    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            try:
                y, m, d     = sys.argv[idx + 1].split("-")
                target_date = (int(y), int(m), int(d))
            except Exception:
                print("Invalid date. Use: --date YYYY-MM-DD")
                sys.exit(1)

    if target_date:
        start_ts, end_ts = get_specific_day_range(*target_date)
        label = f"{target_date[0]}-{target_date[1]:02d}-{target_date[2]:02d}"
    else:
        start_ts, end_ts = get_last_24h_range()
        label = "LAST 24 HOURS"

    jobs = run(start_ts, end_ts, label, send_emails=not view_only)

    # ── Summary table ──────────────────────────────────────────────────────
    if jobs:
        matched = [(j, get_profile_for_title(j["title"])) for j in jobs]
        print(f"\n{'='*70}")
        print(f"  TOTAL: {len(jobs)} jobs  |  MATCHED: {sum(1 for _,p in matched if p)}")
        print(f"{'='*70}")
        print(f"\n{'#':<4} {'TIME':<20} {'TITLE':<45} {'EMAIL':<38} {'LOC':<20} PROFILE")
        print("-" * 155)
        for i, (j, profile) in enumerate(
                sorted(matched, key=lambda x: x[0]["ts"], reverse=True), 1):
            pname = profile["name"] if profile else "---"
            print(f"{i:<4} {ts_to_str(j['ts']):<20} {j['title'][:44]:<45} "
                  f"{j['uid']:<38} {j.get('loc',''):<20} {pname}")

        out = f"logs/jobs_{label.replace(' ','_')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        print(f"\n✅  Saved to {out}")