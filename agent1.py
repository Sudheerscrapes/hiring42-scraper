"""
AI Email Agent - 100% FREE
Uses Gmail SMTP (App Password) - No Google Cloud, No Credit Card
Detects job roles, sends correct resume, CC correct person
"""

import os
import json
import base64
import logging
import re
import smtplib
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import email as emaillib

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# SHARED EMAIL BODY (used by all roles)
# ─────────────────────────────────────────────
SHARED_REPLY = """Hi,

I hope you're doing well. I'm writing to express my interest in any suitable Data Engineer opportunities that match my background and experience.

I am a Senior Data Engineer with 8+ years of experience architecting and optimizing scalable data pipelines across AWS, Azure, and GCP. My expertise includes ETL development, Spark, Kafka, Airflow, Snowflake, BigQuery, Redshift, and data warehouse solutions.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a good fit for your team.

Thank you for your time and consideration.

Best regards,
Swarna M
Phone: +1 757 917 8784
Email: mswarna574@gmail.com"""

# ─────────────────────────────────────────────
# ROLE CONFIG
# ─────────────────────────────────────────────
ROLES = [
    {
        "name": "Data Engineer",
        "keywords": [
            "data engineer", "senior data engineer", "cloud data engineer",
            "big data engineer", "aws data engineer", "azure data engineer",
            "gcp data engineer", "snowflake data engineer",
            "etl developer", "etl engineer", "data pipeline engineer",
            "dataops engineer", "healthcare data engineer",
            "data warehouse engineer", "spark engineer",
            "databricks engineer", "data platform engineer",
            "data integration engineer", "analytics engineer",
            "data infrastructure engineer", "hadoop engineer",
            "kafka engineer", "airflow engineer",
        ],
        "resume_secret": "RESUME_DATA_ENGINEER_B64",
        "cc_secret": "CC_DATA_ENGINEER",
        "reply": SHARED_REPLY,
    },
]

DEFAULT_ROLE = {
    "name": "Default",
    "resume_secret": "RESUME_DATA_ENGINEER_B64",
    "cc_secret": "CC_DATA_ENGINEER",
    "reply": SHARED_REPLY,
}

JOB_KEYWORDS = [
    "hiring", "job opportunity", "urgent requirement", "requirement",
    "opening", "position", "vacancy", "recruitment", "looking for",
    "immediate requirement", "greetings from", "we have an opening",
    "kindly share", "please share your resume", "relevant profile",
    "years of experience", "notice period", "current ctc",
    "expected ctc", "job description", "jd ",
]

STATE_FILE = "logs/processed_ids_swarna.json"

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────
def load_processed():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()

def save_processed(ids):
    with open(STATE_FILE, "w") as f:
        json.dump(list(ids), f)

# ─────────────────────────────────────────────
# READ EMAILS VIA IMAP
# ─────────────────────────────────────────────
def fetch_unread_emails(your_email, app_password):
    log.info("📬 Connecting to Gmail via IMAP...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(your_email, app_password)
    mail.select("inbox")

    today = datetime.now().strftime("%d-%b-%Y")
    _, msg_ids = mail.search(None, f'(UNSEEN SINCE "{today}")')
    ids = msg_ids[0].split()
    log.info(f"📬 Found {len(ids)} unread emails")

    emails = []
    seen_uids = set()

    for uid in ids[-100:]:
        uid_str = uid.decode()
        if uid_str in seen_uids:
            continue
        seen_uids.add(uid_str)

        try:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = emaillib.message_from_bytes(raw)

            message_id = msg.get("Message-ID", uid_str).strip()

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
        except Exception as e:
            log.error(f"Error reading email {uid}: {e}")

    mail.logout()
    return emails

# ─────────────────────────────────────────────
# DETECTION
# ─────────────────────────────────────────────
def is_job_email(email):
    text = (email["subject"] + " " + email["body"]).lower()
    for role in ROLES:
        if any(kw in text for kw in role["keywords"]):
            return True
    return any(kw in text for kw in JOB_KEYWORDS)

def detect_role(email):
    text = (email["subject"] + " " + email["body"]).lower()
    for role in ROLES:
        if any(kw in text for kw in role["keywords"]):
            log.info(f"  🎯 Matched: {role['name']}")
            return role
    log.info("  🎯 No specific role → Default")
    return DEFAULT_ROLE

def extract_address(s):
    m = re.search(r"<(.+?)>", s)
    return m.group(1) if m else s.strip()

def extract_company(email):
    addr = extract_address(email["sender"])
    domain = addr.split("@")[-1].split(".")[0].capitalize() if "@" in addr else ""
    generic = ["gmail", "yahoo", "hotmail", "outlook", "rediffmail", "naukri"]
    if domain.lower() not in generic and domain:
        return domain
    return "your organization"

# ─────────────────────────────────────────────
# GET RESUME FROM SECRET
# ─────────────────────────────────────────────
# Map secret name → b64 filename in repo
RESUME_FILES = {
    "RESUME_DATA_ENGINEER_B64": "resume_data_engineer.b64",
}

def get_resume(role):
    # Try role-specific file first, then default
    fname = RESUME_FILES.get(role["resume_secret"], "resume_default.b64")
    fallback = "resume_default.b64"

    # Try role-specific file
    if not Path(fname).exists():
        log.warning(f"  ⚠️ {fname} not found → using {fallback}")
        fname = fallback

    if not Path(fname).exists():
        raise ValueError(
            f"❌ Resume file '{fname}' not found in repo! "
            "Make sure resume_default.b64 is committed to your repository."
        )

    log.info(f"  📎 Resume file: {fname}")
    b64 = Path(fname).read_text().strip()
    b64 = re.sub(r'\s+', '', b64)  # strip any whitespace
    return base64.b64decode(b64)

# ─────────────────────────────────────────────
# SEND EMAIL VIA SMTP
# ─────────────────────────────────────────────
def send_reply(email, role, your_name, your_email, app_password):
    to_email  = extract_address(email["reply_to"] or email["sender"])
    cc_email  = os.environ.get(role["cc_secret"], "")

    subject = f"Re: {email['subject']}" if not email["subject"].lower().startswith("re:") else email["subject"]
    body    = role["reply"]

    msg = MIMEMultipart()
    msg["From"]    = your_email
    msg["To"]      = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email

    msg.attach(MIMEText(body, "plain"))

    resume_bytes = get_resume(role)
    part = MIMEBase("application", "octet-stream")
    part.set_payload(resume_bytes)
    encoders.encode_base64(part)
    fname = "Resume_Swarna_M.docx"
    part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
    msg.attach(part)

    recipients = [to_email]
    if cc_email:
        recipients.append(cc_email)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(your_email, app_password)
        server.sendmail(your_email, recipients, msg.as_string())

    log.info(f"  ✅ Sent to: {to_email}")
    if cc_email:
        log.info(f"  📋 CC'd:    {cc_email}")

# ─────────────────────────────────────────────
# LOG
# ─────────────────────────────────────────────
def log_sent(email, role):
    csv_path = "logs/sent_log.csv"
    is_new   = not os.path.exists(csv_path)
    with open(csv_path, "a") as f:
        if is_new:
            f.write("timestamp,role,sender,subject,cc\n")
        cc = os.environ.get(role["cc_secret"], "none")
        f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("🤖 AI Email Agent — Swarna (FREE Gmail SMTP)")
    log.info(f"⏰ {datetime.now().isoformat()}")
    log.info("=" * 55)

    your_name    = os.environ.get("YOUR_NAME", "")
    your_email   = os.environ.get("YOUR_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    missing = []
    if not your_name:    missing.append("YOUR_NAME")
    if not your_email:   missing.append("YOUR_EMAIL")
    if not app_password: missing.append("GMAIL_APP_PASSWORD")
    if missing:
        log.error(f"❌ Missing secrets: {', '.join(missing)}")
        return

    processed = load_processed()
    emails = fetch_unread_emails(your_email, app_password)

    matched = 0
    for email in emails:
        dedup_key = email["message_id"]
        if dedup_key in processed:
            log.info(f"  ⏭ Already processed: {email['subject'][:60]}")
            continue

        processed.add(dedup_key)

        if not is_job_email(email):
            continue

        log.info(f"\n🎯 JOB EMAIL: {email['subject']}")
        log.info(f"   From: {email['sender']}")
        matched += 1

        try:
            role = detect_role(email)
            send_reply(email, role, your_name, your_email, app_password)
            log_sent(email, role)
        except Exception as e:
            log.error(f"❌ Error: {e}", exc_info=True)

    save_processed(processed)
    log.info(f"\n✅ Done — Replied to {matched} job emails out of {len(emails)} scanned")
    log.info("💰 Cost: ₹0.00")

if __name__ == "__main__":
    main()
