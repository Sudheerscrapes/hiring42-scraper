"""
AI Email Agent - Satish (Lead .NET Developer)
Scans: sudheeritservices1@gmail.com (IMAP - Gmail)
Sends: sudheer@adeptscripts.com (SMTP - Zoho)
Replies to: .NET Developer, ASP.NET, C#, Azure .NET roles

FIXES:
1. Dedup checked FIRST before anything else
2. Dedup saved IMMEDIATELY after each send (not at the end)
3. UTF-8-sig fix for dedup file (BOM handling)
4. Skips own sent emails
5. Skips any email with subject starting with "Re:"
6. SCAN from sudheeritservices1@gmail.com (Gmail IMAP)
7. SEND from sudheer@adeptscripts.com (Zoho SMTP)
8. Daily send cap (450) to avoid limit errors
9. SINGLE SMTP connection reused for all emails
10. 5 second delay between sends (avoids spam detection)
11. certutil base64 header strip + padding fix
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
    handlers=[logging.FileHandler("logs/agent_satish.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# DAILY DEDUP - Resets every day at midnight
# ══════════════════════════════════════════════════════════════════════════════
DEDUP_FILE = Path("logs") / "daily_replied_senders_satish.json"
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

SHARED_REPLY = """Hi,




In response to your job posting.
Here I am attaching my consultant's updated resume.
Please review the resume and let me know if it matches your position.
Looking forward to working with you.

Thanks & Regards,

Sudheer Kumar, Mandava

Mail: sudheer@adeptscripts.com

Mobile: +1 8374225556

8501 WADE BOULEVARD SUITE 870
FRISCO TX 7503
Recruitment Manager

www.adeptscripts.com

"""

ROLES = [
    {
        "name": "Lead .NET Developer",
        "keywords": [
            "lead .net developer",
            "lead .net engineer",
            "senior .net developer",
            "sr .net developer",
            "sr. .net developer",
            ".net lead developer",
            ".net tech lead",
            "principal .net developer",
        ],
        "resume_file": "resume_satish_b64.txt",
        "cc_secret": "CC_SATISH",
        "reply": SHARED_REPLY,
    },
    {
        "name": ".NET / C# Developer",
        "keywords": [
            ".net developer",
            ".net engineer",
            "dotnet developer",
            "dot net developer",
            "c# developer",
            "c# engineer",
            "csharp developer",
            "asp.net developer",
            "asp.net engineer",
            "asp.net core developer",
            ".net core developer",
            ".net core engineer",
            "dotnet core developer",
        ],
        "resume_file": "resume_satish_b64.txt",
        "cc_secret": "CC_SATISH",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Azure .NET Developer",
        "keywords": [
            "azure .net developer",
            "azure dotnet developer",
            "azure c# developer",
            ".net azure developer",
            ".net microservices developer",
            "microservices .net",
            "microservices c#",
            ".net web api developer",
            "web api developer",
            "asp.net mvc developer",
            ".net mvc developer",
            "mvc developer",
        ],
        "resume_file": "resume_satish_b64.txt",
        "cc_secret": "CC_SATISH",
        "reply": SHARED_REPLY,
    },
    {
        "name": "Full Stack .NET Developer",
        "keywords": [
            "full stack .net",
            "fullstack .net",
            "full stack dotnet",
            ".net full stack",
            ".net angular developer",
            "angular .net developer",
            ".net react developer",
            "react .net developer",
        ],
        "resume_file": "resume_satish_b64.txt",
        "cc_secret": "CC_SATISH",
        "reply": SHARED_REPLY,
    },
]

REPLIED_LABEL = "AutoReplied_Satish"

SKIP_SENDERS = [
    "noreply@",
    "mailer-daemon@",
    "notifications@github.com",
    "noreply.github.com",
    "notifications.monster.com",
    "github.com",
    "sudheeritservices1@gmail.com",
    "sudheer@adeptscripts.com",
]

def extract_address(s):
    if not s:
        return ""
    m = re.search(r"<(.+?)>", s)
    return (m.group(1) if m else s).strip().lower()

def connect_imap():
    # Gmail IMAP for scanning
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

def fetch_matching_emails():
    log.info("Connecting to Gmail via IMAP...")
    mail = connect_imap()
    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info("Gmail %s label: %d emails", REPLIED_LABEL, len(replied_ids))

    replied_senders, send_count = load_daily_dedup()
    today = datetime.now().strftime("%d-%b-%Y")

    all_uid_set = set()
    for role in ROLES:
        for kw in role["keywords"]:
            try:
                search_str = '(UNSEEN SINCE "' + today + '" SUBJECT "' + kw + '")'
                _, msg_ids = mail.search(None, search_str)
                for uid in msg_ids[0].split():
                    all_uid_set.add(uid)
            except Exception:
                pass

    ids = list(all_uid_set)
    log.info("Found %d matching unread emails today", len(ids))

    emails, seen_uids = [], set()
    for i, uid in enumerate(ids):
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue
        seen_uids.add(uid_str)

        if i > 0 and i % 50 == 0:
            try:
                mail.logout()
            except Exception:
                pass
            log.info("Reconnecting IMAP at email %d...", i)
            time.sleep(1)
            mail = connect_imap()

        try:
            _, hdr_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])")
            if not hdr_data or hdr_data[0] is None:
                continue
            hdr_raw = hdr_data[0][1].decode("utf-8", errors="ignore")

            subj_match = re.search(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            subject = subj_match.group(1).strip().replace("\r\n", " ").replace("\n", " ") if subj_match else ""

            if subject.lower().startswith("re:"):
                log.info("Skipping - own reply thread: %s", subject[:50])
                continue

            mid_match = re.search(r"Message-ID:\s*(.+)", hdr_raw, re.IGNORECASE)
            message_id = mid_match.group(1).strip() if mid_match else uid_str

            sender_match = re.search(r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            sender = sender_match.group(1).strip() if sender_match else ""

            rt_match = re.search(r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            reply_to = rt_match.group(1).strip() if rt_match else sender

            if any(skip in sender.lower() for skip in SKIP_SENDERS):
                log.info("Skipping sender: %s", subject[:50])
                continue

            if message_id in replied_ids:
                log.info("Already replied (Message-ID): %s", subject[:50])
                continue

            sender_addr = extract_address(reply_to or sender)
            if not sender_addr:
                log.warning("Could not extract sender email from: %s", sender)
                continue

            emails.append({
                "uid": uid_str,
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "reply_to": reply_to,
                "sender_addr": sender_addr
            })
            log.info("Queued: %s from %s", subject[:50], sender_addr)
            time.sleep(0.2)

        except Exception as e:
            log.error("Error reading email %s: %s", uid_str, e)
            time.sleep(1)

    log.info("Ready to process %d emails", len(emails))
    return emails, mail, replied_senders, send_count

def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info("Matched: %s", role["name"])
            return role
    return None

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

def send_reply(email, role, server):
    smtp_email = os.environ["SATISH_SMTP_EMAIL"]  # sudheer@adeptscripts.com
    to_email = extract_address(email["reply_to"] or email["sender"])
    cc_email = os.environ.get(role["cc_secret"], "")

    if not email["subject"].lower().startswith("re:"):
        subject = "Re: " + email["subject"]
    else:
        subject = email["subject"]

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
    part.add_header("Content-Disposition", 'attachment; filename="Resume_Satish_DotNet.docx"')
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

def log_sent(email, role):
    csv_path = "logs/sent_log_satish.csv"
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

def main():
    log.info("=" * 70)
    log.info("AI Email Agent - Satish (Lead .NET Developer)")
    log.info("SCAN inbox : sudheeritservices1@gmail.com (Gmail IMAP)")
    log.info("SEND from  : sudheer@adeptscripts.com (Zoho SMTP)")
    log.info("Time       : %s", datetime.now().isoformat())
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("Outside run window (6:30 PM - 4:30 AM IST). Skipping.")
        return
    log.info("Within run window (6:30 PM - 4:30 AM IST). Proceeding...")

    required = ["IMAP_EMAIL", "IMAP_APP_PASSWORD", "SATISH_SMTP_EMAIL", "SATISH_SMTP_APP_PASSWORD"]
    missing = [r for r in required if not os.environ.get(r)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    emails, mail, replied_senders, daily_send_count = fetch_matching_emails()

    remaining = MAX_DAILY_SENDS - daily_send_count
    log.info("Daily send budget: %d/%d used, %d remaining today", daily_send_count, MAX_DAILY_SENDS, remaining)
    if remaining <= 0:
        log.warning("Daily send limit already reached (%d/%d). Stopping.", daily_send_count, MAX_DAILY_SENDS)
        try:
            mail.logout()
        except Exception:
            pass
        return

    # Zoho SMTP settings
    smtp_email = os.environ["SATISH_SMTP_EMAIL"]
    smtp_server = None
    try:
        smtp_server = smtplib.SMTP_SSL("smtp.zoho.com", 465)
        smtp_server.login(smtp_email, os.environ["SATISH_SMTP_APP_PASSWORD"])
        log.info("SMTP connected (Zoho): %s", smtp_email)
    except Exception as e:
        log.error("Could not connect to Zoho SMTP: %s", e)
        try:
            mail.logout()
        except Exception:
            pass
        return

    sent_senders = set()
    matched = 0

    for email in emails:
        log.info("JOB EMAIL: %s", email["subject"])
        log.info("   From: %s", email["sender"])

        try:
            sender_addr = email.get("sender_addr", extract_address(email["reply_to"] or email["sender"]))

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
                log.warning("DAILY LIMIT REACHED (%d/%d) - stopping for today.", daily_send_count, MAX_DAILY_SENDS)
                break

            matched += 1
            log.info("SENDING REPLY... (%d/%d)", daily_send_count + 1, MAX_DAILY_SENDS)
            send_reply(email, role, smtp_server)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"])

            replied_senders.add(sender_addr)
            sent_senders.add(sender_addr)
            daily_send_count += 1

            save_daily_dedup(replied_senders, daily_send_count)

        except Exception as e:
            log.error("Error processing email: %s", e, exc_info=True)
            try:
                log.info("Reconnecting Zoho SMTP...")
                smtp_server = smtplib.SMTP_SSL("smtp.zoho.com", 465)
                smtp_server.login(smtp_email, os.environ["SATISH_SMTP_APP_PASSWORD"])
                log.info("Zoho SMTP reconnected successfully")
            except Exception as se:
                log.error("Zoho SMTP reconnect failed: %s", se)
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
    log.info("SEND account : %s", os.environ.get("SATISH_SMTP_EMAIL"))
    log.info("Daily sends  : %d/%d", daily_send_count, MAX_DAILY_SENDS)
    log.info("Daily dedup  : %s (resets at midnight)", str(DEDUP_FILE))
    log.info("Cost: 0.00")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
