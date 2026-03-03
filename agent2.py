"""
AI Email Agent - 100% FREE
Uses Gmail SMTP (App Password) - No Google Cloud, No Credit Card
Only replies to: Data Analyst roles
Searches Gmail by keyword in subject - no false positives
Resume loaded from repo file resume_data_analyst.b64
"""

import os
import base64
import logging
import re
import smtplib
import time
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import email as emaillib

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent2.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

SHARED_REPLY = """Hi,

I hope you're doing well. I'm writing to express my interest in any suitable Data Analyst opportunities that match my background and experience.

I am a Senior Data Analyst with 8+ years of experience transforming raw data into actionable insights, specializing in financial reporting, business intelligence, and data visualization. My expertise includes SQL, Python, Tableau, Power BI, AWS, Snowflake, and data governance.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a good fit for your team.

Thank you for your time and consideration.

Best regards,
Malathi Gambiraopet
Phone: +1 609 323 0664
Email: gmalathi211@gmail.com"""

ROLES = [
    {
        "name": "Data Analyst",
        "keywords": [
            "data analyst", "senior data analyst", "business analyst",
            "bi analyst", "business intelligence analyst",
            "financial analyst", "reporting analyst",
            "sql analyst", "tableau developer", "power bi developer",
            "data reporting analyst", "analytics analyst",
            "data visualization analyst", "insights analyst",
            "marketing analyst", "operations analyst",
            "data governance analyst", "clinical data analyst",
            "healthcare data analyst", "risk analyst",
        ],
        "resume_file": "resume_data_analyst.b64",
        "cc_secret": "CC_DATA_ANALYST",
        "reply": SHARED_REPLY,
    },
]

REPLIED_LABEL = "AutoReplied"

SKIP_SENDERS = [
    "noreply.github.com",
    "notifications@github.com",
    "github.com",
]

def connect_imap(your_email, app_password):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(your_email, app_password)
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
        for uid in msg_ids[0].split():
            try:
                _, msg_data = mail.fetch(uid, "(BODY[HEADER.FIELDS (MESSAGE-ID)])")
                raw = msg_data[0][1].decode("utf-8", errors="ignore")
                m = re.search(r"Message-ID:\s*(.+)", raw, re.IGNORECASE)
                if m:
                    replied_ids.add(m.group(1).strip())
            except Exception:
                pass
    except Exception:
        pass
    mail.select("inbox")
    return replied_ids

def mark_as_replied(mail, uid, your_email, app_password):
    try:
        mail.select("inbox")
        mail.copy(uid, REPLIED_LABEL)
    except Exception:
        try:
            time.sleep(2)
            mail = connect_imap(your_email, app_password)
            mail.select("inbox")
            mail.copy(uid, REPLIED_LABEL)
        except Exception as e:
            log.warning(f"  Could not mark as replied: {e}")
    return mail

def fetch_todays_matching_emails(your_email, app_password):
    log.info("Connecting to Gmail via IMAP...")
    mail = connect_imap(your_email, app_password)

    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info(f"Already replied to {len(replied_ids)} emails previously")

    today = datetime.now().strftime("%d-%b-%Y")

    all_uid_set = set()
    for role in ROLES:
        for kw in role["keywords"]:
            try:
                _, msg_ids = mail.search(
                    None, f'(UNSEEN SINCE "{today}" SUBJECT "{kw}")'
                )
                for uid in msg_ids[0].split():
                    all_uid_set.add(uid)
            except Exception:
                pass

    ids = list(all_uid_set)
    log.info(f"Found {len(ids)} matching unread emails today")

    emails = []
    seen_uids = set()

    for i, uid in enumerate(ids):
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue
        seen_uids.add(uid_str)

        if i > 0 and i % 10 == 0:
            try:
                mail.logout()
            except Exception:
                pass
            log.info(f"  Reconnecting IMAP at email {i}...")
            time.sleep(2)
            mail = connect_imap(your_email, app_password)

        try:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            if not msg_data or msg_data[0] is None:
                continue

            raw = msg_data[0][1]
            msg = emaillib.message_from_bytes(raw)
            message_id = msg.get("Message-ID", uid_str).strip()

            if message_id in replied_ids:
                log.info(f"  Already replied: {msg.get('Subject', '')[:60]}")
                continue

            sender = msg.get("From", "")
            if any(skip in sender for skip in SKIP_SENDERS):
                log.info(f"  Skipping notification: {msg.get('Subject', '')[:60]}")
                continue

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            emails.append({
                "uid":        uid_str,
                "message_id": message_id,
                "subject":    msg.get("Subject", ""),
                "sender":     msg.get("From", ""),
                "reply_to":   msg.get("Reply-To", msg.get("From", "")),
                "body":       body[:4000],
            })
            time.sleep(0.3)

        except Exception as e:
            log.error(f"Error reading email {uid_str}: {e}")
            time.sleep(1)

    return emails, mail

def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info(f"  Matched: {role['name']}")
            return role
    return ROLES[0]

def extract_address(s):
    m = re.search(r"<(.+?)>", s)
    return m.group(1) if m else s.strip()

def get_resume(role):
    fname = role["resume_file"]
    if not Path(fname).exists():
        raise ValueError(f"Resume file '{fname}' not found in repo!")
    log.info(f"  Resume: {fname}")
    b64 = Path(fname).read_text().strip()
    b64 = re.sub(r'\s+', '', b64)
    return base64.b64decode(b64)

def send_reply(email, role, your_email, app_password):
    to_email = extract_address(email["reply_to"] or email["sender"])
    cc_email = os.environ.get(role["cc_secret"], "")
    subject  = f"Re: {email['subject']}" if not email["subject"].lower().startswith("re:") else email["subject"]

    msg = MIMEMultipart()
    msg["From"]    = your_email
    msg["To"]      = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email

    msg.attach(MIMEText(role["reply"], "plain"))

    resume_bytes = get_resume(role)
    part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
    part.set_payload(resume_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        'attachment; filename="Resume_Malathi_Gambiraopet.docx"'
    )
    msg.attach(part)

    recipients = [to_email]
    if cc_email:
        recipients.append(cc_email)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(your_email, app_password)
        server.sendmail(your_email, recipients, msg.as_string())

    log.info(f"  Sent to: {to_email}")
    if cc_email:
        log.info(f"  CC'd:    {cc_email}")

    time.sleep(3)

def log_sent(email, role):
    csv_path = "logs/sent_log.csv"
    is_new   = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new:
            f.write("timestamp,role,sender,subject,cc\n")
        cc = os.environ.get(role["cc_secret"], "none")
        f.write(
            f'{datetime.now().isoformat()},"{role["name"]}",'
            f'"{email["sender"]}","{email["subject"]}","{cc}"\n'
        )

def main():
    log.info("=" * 55)
    log.info("AI Email Agent - Malathi (FREE Gmail SMTP)")
    log.info(f"Time: {datetime.now().isoformat()}")
    log.info("=" * 55)

    your_email   = os.environ.get("YOUR_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    missing = []
    if not your_email:   missing.append("YOUR_EMAIL")
    if not app_password: missing.append("GMAIL_APP_PASSWORD")
    if missing:
        log.error(f"Missing secrets: {', '.join(missing)}")
        return

    emails, mail = fetch_todays_matching_emails(your_email, app_password)

    matched = 0
    for email in emails:
        log.info(f"\nJOB EMAIL: {email['subject']}")
        log.info(f"   From: {email['sender']}")
        matched += 1

        try:
            role = detect_role(email)
            send_reply(email, role, your_email, app_password)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"], your_email, app_password)
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)

    try:
        mail.logout()
    except Exception:
        pass

    log.info(f"\nDone - Replied to {matched} job emails")
    log.info("Cost: 0.00")

if __name__ == "__main__":
    main()
 
 