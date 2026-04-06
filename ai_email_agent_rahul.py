"""
AI Email Agent - Rahul (Data Engineer)
Scans: sudheeritservices1@gmail.com (IMAP)
Sends: harshithacloud81@gmail.com (SMTP)
Replies to: Data Engineer, Data Analyst, ETL/Pipeline Engineer, BI Engineer

FIXES:
1.  Dedup checked FIRST before anything else
2.  Dedup saved IMMEDIATELY after each send (not at the end)
3.  UTF-8-sig fix for dedup file (BOM handling)
4.  Skips own sent emails (sudheeritservices1 / harshithacloud81)
5.  Skips any email with subject starting with "Re:"
6.  SCAN from sudheeritservices1@gmail.com
7.  SEND from harshithacloud81@gmail.com
8.  Daily send cap (450) to avoid Gmail 550 limit errors
9.  SINGLE SMTP connection reused for all emails (avoids Google block)
10. 5 second delay between sends (avoids spam detection)
11. Searches READ + UNREAD emails (not just UNSEEN)
12. Last 2 days window (catches evening emails from previous day)
13. Broader keyword list - catches all common Data Engineer subject patterns
14. Generic "Data Engineer" catch-all role (last priority)
15. Dedup is NOW the VERY FIRST check — fetches only From/Reply-To header
    first, checks dedup immediately, and only fetches Subject/Message-ID
    if the sender has NOT been replied to yet.
"""

import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta
import imaplib
import email as emaillib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent_rahul.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# DAILY DEDUP - Resets every day at midnight
# ══════════════════════════════════════════════════════════════════════════════
DEDUP_FILE = Path("logs") / "daily_replied_senders_rahul.json"
MAX_DAILY_SENDS = 450


def get_today_date():
    return str(date.today())


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
                    log.info("TODAY (%s): %d senders, %d/%d sent so far",
                             today, len(senders), send_count, MAX_DAILY_SENDS)
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
        log.info("SAVED TO DEDUP: %d senders, %d/%d sent today",
                 len(senders), send_count, MAX_DAILY_SENDS)
    except Exception as e:
        log.error("Could not save dedup file: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# TIME WINDOW CHECK
# ══════════════════════════════════════════════════════════════════════════════
def is_within_run_window():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    current_time = now.time()
    start = dtime(18, 30)
    end = dtime(4, 30)
    return current_time >= start or current_time <= end


# ══════════════════════════════════════════════════════════════════════════════
# REPLY TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════
SHARED_REPLY = """Hi,




In response to your job posting.
Here I am attaching my consultant's updated resume. 
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Best regards,
Rahul Kumar Gunti
Phone: (216) 336-9198
Email: harshithacloud81@gmail.com"""


# ══════════════════════════════════════════════════════════════════════════════
# ROLES & KEYWORDS - ordered specific → generic (catch-all last)
# ══════════════════════════════════════════════════════════════════════════════
ROLES = [
    {
        "name": "Azure Data Engineer",
        "keywords": [
            "azure data engineer",
            "azure databricks",
            "azure synapse",
            "synapse analytics",
            "azure data factory",
            "azure data platform",
            "microsoft fabric data engineer",
            "ms fabric data engineer",
        ],
        "resume_file": "resume_rahul_b64.txt",
        "cc_secret": "CC_DATA_ENGINEER",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Snowflake / dbt Engineer",
        "keywords": [
            "snowflake engineer",
            "snowflake developer",
            "snowflake architect",
            "snowflake dbt",
            "snowflake data engineer",
            "dbt engineer",
            "dbt developer",
            "dbt analytics engineer",
            "lead snowflake",
            "senior snowflake",
            "snowflake with",
            "with snowflake",
            "snowflake",
        ],
        "resume_file": "resume_rahul_b64.txt",
        "cc_secret": "CC_SNOWFLAKE",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Databricks / Spark Engineer",
        "keywords": [
            "databricks engineer",
            "databricks developer",
            "pyspark engineer",
            "pyspark developer",
            "spark data engineer",
            "azure databricks developer",
            "databricks data engineer",
            "pyspark",
            "spark streaming",
            "databricks",
        ],
        "resume_file": "resume_rahul_b64.txt",
        "cc_secret": "CC_DATABRICKS",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Senior / Lead Data Engineer",
        "keywords": [
            "senior data engineer",
            "sr. data engineer",
            "sr data engineer",
            "lead data engineer",
            "principal data engineer",
            "staff data engineer",
            "data engineer with azure",
            "data engineer with databricks",
            "data engineer with snowflake",
            "data engineer with pyspark",
            "data engineer with spark",
            "data engineer with kafka",
            "cloud data engineer",
            "data platform engineer",
        ],
        "resume_file": "resume_rahul_b64.txt",
        "cc_secret": "CC_SENIOR_DE",
        "reply": SHARED_REPLY,
    },
    {
        # ── Catch-all: must be LAST ──────────────────────────────────────────
        "name": "Data Engineer (General)",
        "keywords": [
            "data engineer",
            "data analyst",
            "etl engineer",
            "etl developer",
            "etl pipeline",
            "bi engineer",
            "bi developer",
            "data pipeline",
            "dba/data engineer",
            "dba data engineer",
            "hiring data engineer",
            "looking for data engineer",
            "requirement data engineer",
            "urgent data engineer",
        ],
        "resume_file": "resume_rahul_b64.txt",
        "cc_secret": "CC_DATA_ENGINEER",
        "reply": SHARED_REPLY,
    },
]

REPLIED_LABEL = "AutoReplied_Rahul"

SKIP_SENDERS = [
    "noreply@",
    "no-reply@",
    "mailer-daemon@",
    "notifications@github.com",
    "noreply.github.com",
    "sudheeritservices1@gmail.com",
    "harshithacloud81@gmail.com",
]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def extract_address(s):
    if not s:
        return ""
    m = re.search(r"<(.+?)>", s)
    return (m.group(1) if m else s).strip().lower()


def connect_imap():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ["IMAP_EMAIL"], os.environ["IMAP_APP_PASSWORD"])
    mail.select("inbox")
    return mail


def ensure_label_exists(mail):
    try:
        mail.create(REPLIED_LABEL)
    except Exception:
        pass


def get_replied_message_ids(mail):
    replied_ids = set()
    try:
        mail.select(REPLIED_LABEL)
        _, msg_ids = mail.search(None, "ALL")
        if msg_ids[0]:
            uid_list = ",".join(m.decode() for m in msg_ids[0].split())
            _, data = mail.fetch(uid_list, "(BODY[HEADER.FIELDS (MESSAGE-ID)])")
            for item in data:
                if isinstance(item, tuple):
                    raw = item[1].decode("utf-8", errors="ignore")
                    m = re.search(r"Message-ID:\s*(.+)", raw, re.IGNORECASE)
                    if m:
                        replied_ids.add(m.group(1).strip())
    except Exception:
        pass
    mail.select("inbox")
    return replied_ids


def mark_as_replied(mail, uid):
    for attempt in range(3):
        try:
            fresh = connect_imap()
            fresh.select("inbox")
            fresh.copy(uid, REPLIED_LABEL)
            fresh.logout()
            return mail
        except Exception as e:
            log.warning("Mark attempt %d failed: %s", attempt + 1, e)
            time.sleep(2)
    log.error("Failed to mark email as replied after 3 attempts")
    return mail


def mark_as_read(mail, uid):
    """Mark the email as read (remove \\Seen flag) in the IMAP inbox."""
    for attempt in range(3):
        try:
            fresh = connect_imap()
            fresh.select("inbox")
            fresh.store(uid, "+FLAGS", "\\Seen")
            fresh.logout()
            log.info("Marked as READ: uid %s", uid)
            return mail
        except Exception as e:
            log.warning("Mark-as-read attempt %d failed: %s", attempt + 1, e)
            time.sleep(2)
    log.error("Failed to mark email as read after 3 attempts (uid %s)", uid)
    return mail


# ══════════════════════════════════════════════════════════════════════════════
# FETCH MATCHING EMAILS
# Searches READ + UNREAD, last 2 days, broad keyword list
# DEDUP is checked FIRST — only From/Reply-To header fetched initially.
# Subject + Message-ID are fetched only if sender is NOT in dedup.
# ══════════════════════════════════════════════════════════════════════════════
def fetch_matching_emails():
    log.info("Connecting to Gmail via IMAP...")
    mail = connect_imap()
    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info("Gmail %s label: %d emails", REPLIED_LABEL, len(replied_ids))

    replied_senders, send_count = load_daily_dedup()

    # Last 2 days - catches emails from yesterday evening too
    since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
    log.info("Searching emails since: %s (last 2 days)", since_date)

    all_uid_set = set()

    # Search both ALL and UNSEEN to catch read + unread emails
    for role in ROLES:
        for kw in role["keywords"]:
            for flag in ["ALL", "UNSEEN"]:
                try:
                    search_str = f'({flag} SINCE "{since_date}" SUBJECT "{kw}")'
                    _, msg_ids = mail.search(None, search_str)
                    found = msg_ids[0].split() if msg_ids[0] else []
                    if found:
                        log.info("  [%s] '%s' → %d hits", flag, kw, len(found))
                    for uid in found:
                        all_uid_set.add(uid)
                except Exception as e:
                    log.debug("Search error for '%s': %s", kw, e)

    ids = list(all_uid_set)
    log.info("Found %d candidate emails (last 2 days, read+unread)", len(ids))

    emails, seen_uids = [], set()
    for i, uid in enumerate(ids):
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue
        seen_uids.add(uid_str)

        # Reconnect IMAP every 50 emails to avoid timeout
        if i > 0 and i % 50 == 0:
            try:
                mail.logout()
            except Exception:
                pass
            log.info("Reconnecting IMAP at email %d...", i)
            time.sleep(1)
            mail = connect_imap()

        try:
            # ── STEP 1: Fetch ONLY From + Reply-To (cheapest possible call)
            #    so we can run dedup BEFORE doing any more IMAP work.
            _, from_data = mail.fetch(
                uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO)])"
            )
            if not from_data or from_data[0] is None:
                continue
            from_raw = from_data[0][1].decode("utf-8", errors="ignore")

            sender_match_quick = re.search(
                r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)",
                from_raw, re.IGNORECASE | re.DOTALL
            )
            sender_quick = sender_match_quick.group(1).strip() if sender_match_quick else ""

            rt_match_quick = re.search(
                r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)",
                from_raw, re.IGNORECASE | re.DOTALL
            )
            reply_to_quick = rt_match_quick.group(1).strip() if rt_match_quick else sender_quick

            # ── DEDUP CHECK — absolute first gate, before fetching Subject ──
            sender_addr_quick = extract_address(reply_to_quick or sender_quick)
            if sender_addr_quick and sender_addr_quick in replied_senders:
                log.info("DEDUP SKIP (pre-fetch): %s", sender_addr_quick)
                continue

            # Skip system/own senders early too
            if any(skip in sender_quick.lower() for skip in SKIP_SENDERS):
                log.info("Skipping system sender (pre-fetch): %s", sender_quick[:60])
                continue

            # ── STEP 2: Now fetch full header (Subject + Message-ID) ────────
            _, hdr_data = mail.fetch(
                uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])"
            )
            if not hdr_data or hdr_data[0] is None:
                continue
            hdr_raw = hdr_data[0][1].decode("utf-8", errors="ignore")

            subj_match = re.search(
                r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)",
                hdr_raw, re.IGNORECASE | re.DOTALL
            )
            subject = (
                subj_match.group(1).strip().replace("\r\n", " ").replace("\n", " ")
                if subj_match else ""
            )

            # Skip reply threads (Re:, RE:, re :)
            if re.match(r"^re\s*:", subject, re.IGNORECASE):
                log.info("Skipping reply thread: %s", subject[:60])
                continue

            mid_match = re.search(r"Message-ID:\s*(.+)", hdr_raw, re.IGNORECASE)
            message_id = mid_match.group(1).strip() if mid_match else uid_str

            sender_match = re.search(
                r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)",
                hdr_raw, re.IGNORECASE | re.DOTALL
            )
            sender = sender_match.group(1).strip() if sender_match else ""

            rt_match = re.search(
                r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)",
                hdr_raw, re.IGNORECASE | re.DOTALL
            )
            reply_to = rt_match.group(1).strip() if rt_match else sender

            # Skip already replied by Message-ID
            if message_id in replied_ids:
                log.info("Already replied (Message-ID): %s", subject[:60])
                continue

            sender_addr = extract_address(reply_to or sender)
            if not sender_addr:
                log.warning("Could not extract sender email from: %s", sender)
                continue

            # Final dedup guard with fully-resolved address
            if sender_addr in replied_senders:
                log.info("Already replied today (dedup): %s", sender_addr)
                continue

            emails.append({
                "uid": uid_str,
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "reply_to": reply_to,
                "sender_addr": sender_addr
            })
            log.info("Queued [%d]: %s | %s", len(emails), subject[:55], sender_addr)
            time.sleep(0.1)

        except Exception as e:
            log.error("Error reading email %s: %s", uid_str, e)
            time.sleep(1)

    log.info("Ready to process %d emails", len(emails))
    return emails, mail, replied_senders, send_count


# ══════════════════════════════════════════════════════════════════════════════
# ROLE DETECTION - first match wins (specific roles before catch-all)
# ══════════════════════════════════════════════════════════════════════════════
def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info("Matched role: %s", role["name"])
            return role
    log.info("No role matched for: %s", email["subject"][:60])
    return None


# ══════════════════════════════════════════════════════════════════════════════
# RESUME LOADER
# ══════════════════════════════════════════════════════════════════════════════
def get_resume(role):
    fname = role["resume_file"]
    if not Path(fname).exists():
        raise ValueError("Resume file '{}' not found!".format(fname))
    log.info("Resume: %s", fname)
    raw = Path(fname).read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16').strip()
    else:
        text = raw.decode('latin-1').strip()
    # Strip certutil BEGIN/END headers and all whitespace
    lines = text.splitlines()
    lines = [l for l in lines if not l.startswith("-----")]
    b64 = re.sub(r'\s+', '', "".join(lines))
    # Fix base64 padding
    missing = len(b64) % 4
    if missing:
        b64 += "=" * (4 - missing)
    return base64.b64decode(b64)


# ══════════════════════════════════════════════════════════════════════════════
# SEND REPLY
# ══════════════════════════════════════════════════════════════════════════════
def send_reply(email, role, server):
    smtp_email = os.environ["RAHUL_SMTP_EMAIL"]
    to_email = extract_address(email["reply_to"] or email["sender"])
    cc_email = os.environ.get(role["cc_secret"], "")

    subject = email["subject"]
    if not re.match(r"^re\s*:", subject, re.IGNORECASE):
        subject = "Re: " + subject

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email

    msg.attach(MIMEText(role["reply"], "plain"))

    resume_bytes = get_resume(role)
    part = MIMEBase(
        "application",
        "vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    part.set_payload(resume_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        'attachment; filename="Resume_Rahul_DataEngineer.docx"'
    )
    msg.attach(part)

    recipients = [to_email]
    if cc_email:
        recipients.append(cc_email)

    server.sendmail(smtp_email, recipients, msg.as_string())

    log.info("Sent from : %s", smtp_email)
    log.info("Sent to   : %s", to_email)
    if cc_email:
        log.info("CCd       : %s", cc_email)

    time.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# CSV SENT LOG
# ══════════════════════════════════════════════════════════════════════════════
def log_sent(email, role):
    csv_path = "logs/sent_log_rahul.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new:
            f.write("timestamp,role,sender,subject,cc\n")
        cc = os.environ.get(role["cc_secret"], "none")
        f.write('{},"{}", "{}","{}","{}"\n'.format(
            datetime.now().isoformat(),
            role["name"],
            email["sender"],
            email["subject"],
            cc
        ))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Rahul (Data Engineer)")
    log.info("SCAN inbox : sudheeritservices1@gmail.com")
    log.info("SEND from  : harshithacloud81@gmail.com")
    log.info("Time       : %s", datetime.now().isoformat())
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("Outside run window (6:30 PM - 4:30 AM IST). Skipping.")
        return
    log.info("Within run window (6:30 PM - 4:30 AM IST). Proceeding...")

    required = [
        "IMAP_EMAIL", "IMAP_APP_PASSWORD",
        "RAHUL_SMTP_EMAIL", "RAHUL_SMTP_APP_PASSWORD"
    ]
    missing = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    emails, mail, replied_senders, daily_send_count = fetch_matching_emails()

    remaining = MAX_DAILY_SENDS - daily_send_count
    log.info(
        "Daily send budget: %d/%d used, %d remaining today",
        daily_send_count, MAX_DAILY_SENDS, remaining
    )
    if remaining <= 0:
        log.warning(
            "Daily send limit already reached (%d/%d). Stopping.",
            daily_send_count, MAX_DAILY_SENDS
        )
        try:
            mail.logout()
        except Exception:
            pass
        return

    smtp_email = os.environ["RAHUL_SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        smtp_server.login(smtp_email, os.environ["RAHUL_SMTP_APP_PASSWORD"])
        log.info("SMTP connected: %s", smtp_email)
    except Exception as e:
        log.error("Could not connect to SMTP: %s", e)
        try:
            mail.logout()
        except Exception:
            pass
        return

    sent_senders = set()
    matched = 0

    for email in emails:
        log.info("-" * 60)
        log.info("JOB EMAIL: %s", email["subject"])
        log.info("   From  : %s", email["sender"])

        try:
            sender_addr = email.get(
                "sender_addr",
                extract_address(email["reply_to"] or email["sender"])
            )

            if sender_addr in replied_senders:
                log.info("SKIPPING - already replied to %s today", sender_addr)
                continue

            if sender_addr in sent_senders:
                log.info("SKIPPING - already replied to %s in this run", sender_addr)
                continue

            role = detect_role(email)
            if role is None:
                log.info("No matching role - skipping")
                continue

            if daily_send_count >= MAX_DAILY_SENDS:
                log.warning(
                    "DAILY LIMIT REACHED (%d/%d) - stopping for today.",
                    daily_send_count, MAX_DAILY_SENDS
                )
                break

            matched += 1
            log.info("SENDING REPLY... (%d/%d)", daily_send_count + 1, MAX_DAILY_SENDS)
            send_reply(email, role, smtp_server)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"])
            mail = mark_as_read(mail, email["uid"])   # ← mark as READ in inbox

            replied_senders.add(sender_addr)
            sent_senders.add(sender_addr)
            daily_send_count += 1

            # Save dedup immediately after every send
            save_daily_dedup(replied_senders, daily_send_count)

        except Exception as e:
            log.error("Error processing email: %s", e, exc_info=True)
            try:
                log.info("Reconnecting SMTP...")
                smtp_server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
                smtp_server.login(smtp_email, os.environ["RAHUL_SMTP_APP_PASSWORD"])
                log.info("SMTP reconnected successfully")
            except Exception as se:
                log.error("SMTP reconnect failed: %s", se)
                break

    try:
        smtp_server.quit()
        log.info("SMTP connection closed")
    except Exception:
        pass

    try:
        mail.logout()
    except Exception:
        pass

    log.info("=" * 70)
    log.info("Done - Replied to %d job emails", matched)
    log.info("SCAN account : %s", os.environ.get("IMAP_EMAIL"))
    log.info("SEND account : %s", os.environ.get("RAHUL_SMTP_EMAIL"))
    log.info("Daily sends  : %d/%d", daily_send_count, MAX_DAILY_SENDS)
    log.info("Daily dedup  : %s (resets at midnight)", str(DEDUP_FILE))
    log.info("Cost: 0.00")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
