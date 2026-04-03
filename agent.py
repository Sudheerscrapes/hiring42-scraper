"""
AI Email Agent - Lingaraju Modhala - FINAL VERSION
Only replies to: DevOps, Cloud Engineer, SRE

FIXES:
1. Dedup checked FIRST before anything else
2. Dedup saved IMMEDIATELY after each send (not at the end)
3. UTF-8-sig fix for dedup file (BOM handling)
4. Skips own sent emails (sudheeritservices1 / rajumodhala777)
5. Skips any email with subject starting with "Re:"
6. SCAN from sudheeritservices1@gmail.com
7. SEND from rajumodhala777@gmail.com
"""

import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, date, time as dtime
import imaplib
import email as emaillib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/agent.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# 📅 DAILY DEDUP - Resets every day at midnight
# ══════════════════════════════════════════════════════════════════════════════
DEDUP_FILE = Path("logs") / "daily_replied_senders.json"

def get_today_date():
    return str(date.today())

def load_daily_dedup():
    """Load today's replied senders. If file is from different day, reset."""
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8-sig") as f:  # ✅ handles BOM
                data = json.load(f)
                file_date = data.get("date", "")
                today = get_today_date()
                if file_date == today:
                    senders = set(data.get("senders", []))
                    log.info(f"📅 TODAY ({today}): Loaded {len(senders)} senders from dedup file")
                    return senders
                else:
                    log.info(f"📅 NEW DAY! (was {file_date}, now {today}) - Resetting dedup")
                    return set()
        except Exception as e:
            log.warning(f"⚠️ Could not load dedup file: {e}")

    log.info(f"📅 TODAY ({get_today_date()}): No dedup file yet - starting fresh")
    return set()

def save_daily_dedup(senders):
    """Save today's replied senders."""
    data = {
        "date": get_today_date(),
        "senders": sorted(list(senders))
    }
    try:
        with open(DEDUP_FILE, "w", encoding="utf-8") as f:  # ✅ plain utf-8, no BOM
            json.dump(data, f, indent=2)
        log.info(f"✅ SAVED TO DEDUP: {len(senders)} senders for {get_today_date()}")
    except Exception as e:
        log.error(f"❌ Could not save dedup file: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ⏰ TIME WINDOW CHECK
# ══════════════════════════════════════════════════════════════════════════════
def is_within_run_window():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    current_time = now.time()
    start = dtime(18, 30)
    end   = dtime(4, 30)
    return current_time >= start or current_time <= end

# ══════════════════════════════════════════════════════════════════════════════

SHARED_REPLY = """Hi,

I hope you're doing well. I'm writing to express my interest in any suitable opportunities that match my background and experience.

I have several years of experience working in cloud, DevOps, and production support environments. My work has involved supporting live systems, automating deployments, improving monitoring and reliability, and collaborating closely with cross-functional teams to keep applications stable and performant.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a good fit for your team.

Thank you for your time and consideration.

Best regards,
Lingaraju Modhala
Phone: +1 940 281 5324
Email: rajumodhala777@gmail.com"""

ROLES = [
    {
        "name": "DevOps Engineer",
        "keywords": [
            "devops", "dev ops", "ci/cd", "build and release",
            "devsecops", "release engineer", "pipeline engineer",
            "infrastructure engineer", "platform engineer",
        ],
        "resume_file": "resume_b64.txt",
        "cc_secret": "CC_DEVOPS",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Cloud Engineer",
        "keywords": [
            "cloud engineer", "cloud architect", "cloud infrastructure",
            "aws engineer", "aws architect", "aws devops",
            "azure engineer", "azure architect", "azure devops",
            "gcp engineer", "gcp architect",
        ],
        "resume_file": "resume_b64.txt",
        "cc_secret": "CC_CLOUD",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Site Reliability Engineer",
        "keywords": [
            "site reliability", "sre engineer", "sre lead",
            "sre -", "- sre", "reliability engineer",
        ],
        "resume_file": "resume_b64.txt",
        "cc_secret": "CC_SRE",
        "reply": SHARED_REPLY,
    },
]

REPLIED_LABEL = "AutoReplied"

# ✅ FIX: Skip own email addresses + system senders
SKIP_SENDERS = [
    "noreply@",
    "mailer-daemon@",
    "notifications@github.com",
    "noreply.github.com",
    "sudheeritservices1@gmail.com",   # ✅ own IMAP scan account
    "rajumodhala777@gmail.com",        # ✅ own SMTP send account
]

def extract_address(s):
    if not s:
        return ""
    m = re.search(r"<(.+?)>", s)
    return (m.group(1) if m else s).strip().lower()

def connect_imap():
    """Connect using IMAP credentials (sudheeritservices1)."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ["IMAP_EMAIL"], os.environ["IMAP_APP_PASSWORD"])
    mail.select("inbox")
    return mail

def ensure_label_exists(mail):
    try: mail.create(REPLIED_LABEL)
    except Exception: pass

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
                    if m: replied_ids.add(m.group(1).strip())
    except Exception: pass
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
            log.warning(f"  Mark attempt {attempt+1} failed: {e}")
            time.sleep(2)
    log.error("  Failed to mark email as replied after 3 attempts")
    return mail

def fetch_matching_emails():
    log.info("Connecting to Gmail via IMAP...")
    mail = connect_imap()
    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info(f"Gmail AutoReplied label: {len(replied_ids)} emails")

    replied_senders = load_daily_dedup()

    today = datetime.now().strftime("%d-%b-%Y")

    all_uid_set = set()
    for role in ROLES:
        for kw in role["keywords"]:
            try:
                _, msg_ids = mail.search(None, f'(UNSEEN SINCE "{today}" SUBJECT "{kw}")')
                for uid in msg_ids[0].split():
                    all_uid_set.add(uid)
            except Exception:
                pass

    ids = list(all_uid_set)
    log.info(f"Found {len(ids)} matching unread emails today")

    emails, seen_uids = [], set()
    for i, uid in enumerate(ids):
        uid_str = uid.decode()
        if uid_str in seen_uids: continue
        seen_uids.add(uid_str)

        if i > 0 and i % 50 == 0:
            try: mail.logout()
            except Exception: pass
            log.info(f"  Reconnecting IMAP at email {i}...")
            time.sleep(1)
            mail = connect_imap()

        try:
            _, hdr_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])")
            if not hdr_data or hdr_data[0] is None: continue
            hdr_raw = hdr_data[0][1].decode("utf-8", errors="ignore")

            subj_match = re.search(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            subject = subj_match.group(1).strip().replace("\r\n", " ").replace("\n", " ") if subj_match else ""

            # ✅ FIX: Skip own reply threads — subjects starting with "Re:"
            if subject.lower().startswith("re:"):
                log.info(f"  Skipping — own reply thread: {subject[:50]}")
                continue

            mid_match = re.search(r"Message-ID:\s*(.+)", hdr_raw, re.IGNORECASE)
            message_id = mid_match.group(1).strip() if mid_match else uid_str

            sender_match = re.search(r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            sender = sender_match.group(1).strip() if sender_match else ""

            rt_match = re.search(r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            reply_to = rt_match.group(1).strip() if rt_match else sender

            # ✅ FIX: Skip own email addresses and system senders
            if any(skip in sender.lower() for skip in SKIP_SENDERS):
                log.info(f"  Skipping sender: {subject[:50]}")
                continue

            if message_id in replied_ids:
                log.info(f"  Already replied (Message-ID): {subject[:50]}")
                continue

            sender_addr = extract_address(reply_to or sender)
            if not sender_addr:
                log.warning(f"  Could not extract sender email from: {sender}")
                continue

            emails.append({
                "uid": uid_str,
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "reply_to": reply_to,
                "sender_addr": sender_addr
            })
            log.info(f"  Queued: {subject[:50]} from {sender_addr}")
            time.sleep(0.2)

        except Exception as e:
            log.error(f"Error reading email {uid_str}: {e}")
            time.sleep(1)

    log.info(f"Ready to process {len(emails)} emails")
    return emails, mail, replied_senders

def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info(f"  Matched: {role['name']}")
            return role
    return None

def get_resume(role):
    fname = role["resume_file"]
    if not Path(fname).exists(): raise ValueError(f"Resume file '{fname}' not found!")
    log.info(f"  Resume: {fname}")
    raw = Path(fname).read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        b64 = re.sub(r'\s+', '', raw.decode('utf-16').strip())
    else:
        b64 = re.sub(r'\s+', '', raw.decode('latin-1').strip())
    return base64.b64decode(b64)

def send_reply(email, role):
    to_email = extract_address(email["reply_to"] or email["sender"])
    cc_email = os.environ.get(role["cc_secret"], "")
    smtp_email = os.environ["SMTP_EMAIL"]  # rajumodhala777@gmail.com

    subject = f"Re: {email['subject']}" if not email["subject"].lower().startswith("re:") else email["subject"]

    msg = MIMEMultipart()
    msg["From"] = smtp_email               # ✅ sends FROM rajumodhala777
    msg["To"] = to_email
    msg["Subject"] = subject
    if cc_email: msg["Cc"] = cc_email

    msg.attach(MIMEText(role["reply"], "plain"))

    resume_bytes = get_resume(role)
    part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
    part.set_payload(resume_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", 'attachment; filename="Resume_Lingaraju_Modhala.docx"')
    msg.attach(part)

    recipients = [to_email]
    if cc_email: recipients.append(cc_email)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_email, os.environ["SMTP_APP_PASSWORD"])  # ✅ login as rajumodhala777
        server.sendmail(smtp_email, recipients, msg.as_string())

    log.info(f"  Sent from : {smtp_email}")
    log.info(f"  Sent to   : {to_email}")
    if cc_email: log.info(f"  CC'd      : {cc_email}")
    time.sleep(3)

def log_sent(email, role):
    csv_path = "logs/sent_log.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new: f.write("timestamp,role,sender,subject,cc\n")
        cc = os.environ.get(role["cc_secret"], "none")
        f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Lingaraju Modhala (FINAL VERSION)")
    log.info(f"SCAN inbox : sudheeritservices1@gmail.com (IMAP_EMAIL)")
    log.info(f"SEND from  : rajumodhala777@gmail.com (SMTP_EMAIL)")
    log.info(f"Time       : {datetime.now().isoformat()}")
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("Outside run window (6:30 PM - 4:30 AM IST). Skipping.")
        return
    log.info("Within run window (6:30 PM - 4:30 AM IST). Proceeding...")

    # Validate all required env vars
    required = ["IMAP_EMAIL", "IMAP_APP_PASSWORD", "SMTP_EMAIL", "SMTP_APP_PASSWORD"]
    missing = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error(f"Missing env vars: {', '.join(missing)}")
        return

    emails, mail, replied_senders = fetch_matching_emails()

    sent_senders = set()
    matched = 0

    for email in emails:
        log.info(f"\nJOB EMAIL: {email['subject']}")
        log.info(f"   From: {email['sender']}")

        try:
            sender_addr = email.get("sender_addr", extract_address(email["reply_to"] or email["sender"]))

            # ✅ FIX 1: DEDUP CHECK FIRST — before anything else
            if sender_addr in replied_senders:
                log.info(f"  SKIPPING — already replied to {sender_addr} today (dedup file)")
                continue

            if sender_addr in sent_senders:
                log.info(f"  SKIPPING — already replied to {sender_addr} in this run")
                continue

            # Only now check the role
            role = detect_role(email)
            if role is None:
                log.info("  No matching role — skipping")
                continue

            matched += 1
            log.info(f"  SENDING REPLY...")
            send_reply(email, role)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"])

            replied_senders.add(sender_addr)
            sent_senders.add(sender_addr)

            # ✅ FIX 2: SAVE DEDUP IMMEDIATELY after each send
            save_daily_dedup(replied_senders)

        except Exception as e:
            log.error(f"Error processing email: {e}", exc_info=True)

    try: mail.logout()
    except Exception: pass

    log.info("\n" + "=" * 70)
    log.info(f"Done — Replied to {matched} job emails")
    log.info(f"SCAN account : {os.environ.get('IMAP_EMAIL')}")
    log.info(f"SEND account : {os.environ.get('SMTP_EMAIL')}")
    log.info(f"Daily dedup  : {DEDUP_FILE} (resets at midnight)")
    log.info("Cost: 0.00")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
