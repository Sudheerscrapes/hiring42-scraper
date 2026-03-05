"""
AI Email Agent - Lingaraju Modhala
Only replies to: DevOps, Cloud Engineer, SRE
Searches Gmail by keyword in subject - today only
"""

import os, base64, logging, re, smtplib, time
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import email as emaillib

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("logs/agent.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

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
SKIP_SENDERS = ["noreply@", "mailer-daemon@", "notifications@github.com", "noreply.github.com"]

def connect_imap(your_email, app_password):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(your_email, app_password)
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

def mark_as_replied(mail, uid, your_email, app_password):
    for attempt in range(3):
        try:
            fresh = connect_imap(your_email, app_password)
            fresh.select("inbox")
            fresh.copy(uid, REPLIED_LABEL)
            fresh.logout()
            return mail
        except Exception as e:
            log.warning(f"  Mark attempt {attempt+1} failed: {e}")
            time.sleep(2)
    log.error("  Failed to mark email as replied after 3 attempts")
    return mail

def fetch_matching_emails(your_email, app_password):
    log.info("Connecting to Gmail via IMAP...")
    mail = connect_imap(your_email, app_password)
    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info(f"Already replied to {len(replied_ids)} emails previously")

    today = datetime.now().strftime("%d-%b-%Y")

    # Search IMAP directly by keyword — today only
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
            mail = connect_imap(your_email, app_password)

        try:
            # BODY.PEEK — does not mark email as read
            _, hdr_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])")
            if not hdr_data or hdr_data[0] is None: continue
            hdr_raw = hdr_data[0][1].decode("utf-8", errors="ignore")

            subj_match = re.search(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            subject = subj_match.group(1).strip().replace("\r\n", " ").replace("\n", " ") if subj_match else ""

            mid_match = re.search(r"Message-ID:\s*(.+)", hdr_raw, re.IGNORECASE)
            message_id = mid_match.group(1).strip() if mid_match else uid_str

            if message_id in replied_ids:
                log.info(f"  Already replied: {subject[:60]}")
                continue

            sender_match = re.search(r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            sender = sender_match.group(1).strip() if sender_match else ""

            if any(skip in sender.lower() for skip in SKIP_SENDERS):
                log.info(f"  Skipping: {subject[:60]}")
                continue

            rt_match = re.search(r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            reply_to = rt_match.group(1).strip() if rt_match else sender

            # BODY.PEEK[] — does not mark email as read
            _, msg_data = mail.fetch(uid, "(BODY.PEEK[])")
            if not msg_data or msg_data[0] is None: continue
            msg = emaillib.message_from_bytes(msg_data[0][1])
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            emails.append({
                "uid": uid_str, "message_id": message_id,
                "subject": subject, "sender": sender,
                "reply_to": reply_to, "body": body[:4000]
            })
            log.info(f"  Queued: {subject[:60]}")
            time.sleep(0.2)

        except Exception as e:
            log.error(f"Error reading email {uid_str}: {e}")
            time.sleep(1)

    log.info(f"Matched {len(emails)} emails to reply to")
    return emails, mail

def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info(f"  Matched: {role['name']}")
            return role
    return None

def extract_address(s):
    m = re.search(r"<(.+?)>", s)
    return m.group(1) if m else s.strip()

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

def send_reply(email, role, your_email, app_password):
    to_email = extract_address(email["reply_to"] or email["sender"])
    cc_email = os.environ.get(role["cc_secret"], "")
    subject = f"Re: {email['subject']}" if not email["subject"].lower().startswith("re:") else email["subject"]
    msg = MIMEMultipart()
    msg["From"] = your_email
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
        server.login(your_email, app_password)
        server.sendmail(your_email, recipients, msg.as_string())
    log.info(f"  Sent to: {to_email}")
    if cc_email: log.info(f"  CC'd:    {cc_email}")
    time.sleep(3)

def log_sent(email, role):
    csv_path = "logs/sent_log.csv"
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new: f.write("timestamp,role,sender,subject,cc\n")
        cc = os.environ.get(role["cc_secret"], "none")
        f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

def main():
    log.info("=" * 55)
    log.info("AI Email Agent - Lingaraju (FREE Gmail SMTP)")
    log.info(f"Time: {datetime.now().isoformat()}")
    log.info("=" * 55)
    your_email = os.environ.get("YOUR_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    missing = []
    if not your_email: missing.append("YOUR_EMAIL")
    if not app_password: missing.append("GMAIL_APP_PASSWORD")
    if missing:
        log.error(f"Missing secrets: {', '.join(missing)}")
        return
    emails, mail = fetch_matching_emails(your_email, app_password)
    matched = 0
    sent_ids = set()  # prevent duplicate sends in same run
    for email in emails:
        log.info(f"\nJOB EMAIL: {email['subject']}")
        log.info(f"   From: {email['sender']}")
        try:
            if email["message_id"] in sent_ids:
                log.info("  Duplicate in this run — skipping")
                continue
            role = detect_role(email)
            if role is None:
                log.info("  No matching role — skipping")
                continue
            matched += 1
            send_reply(email, role, your_email, app_password)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"], your_email, app_password)
            sent_ids.add(email["message_id"])
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)
    try: mail.logout()
    except Exception: pass
    log.info(f"\nDone - Replied to {matched} job emails")
    log.info("Cost: 0.00")

if __name__ == "__main__":
    main()
