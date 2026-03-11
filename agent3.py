"""
AI Email Agent - Manasa Janga
Only replies to: Frontend / Software Engineer roles (Florida or Remote only)
Searches Gmail by keyword in subject - today only
"""

import os
import re
import base64
import time
import smtplib
import imaplib
import logging
import email as emaillib
from pathlib import Path
from datetime import datetime, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

# ── Logging Setup ──────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent3.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── TIME WINDOW CHECK (IST 6:30 PM → 4:30 AM) ─────────────────────────────────
def is_within_run_window():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    current_time = now.time()
    start = dtime(18, 30)  # 6:30 PM IST
    end   = dtime(4, 30)   # 4:30 AM IST
    # Window crosses midnight: >= 18:30 OR <= 04:30
    return current_time >= start or current_time <= end
# ──────────────────────────────────────────────────────────────────────────────

# ── Constants ──────────────────────────────────────────────────────────────────
REPLIED_LABEL = "AutoReplied"
RESUME_FILE   = "resume_manasa_b64.txt"
RESUME_NAME   = "Resume_Manasa_Janga.docx"
SKIP_SENDERS  = ["noreply@", "mailer-daemon@", "notifications@github.com", "noreply.github.com"]

# ── Location Filter ────────────────────────────────────────────────────────────
ALLOWED_LOCATIONS = ["florida", "remote", "fl,", " fl ", "(fl)"]

def is_allowed_location(subject: str, body: str) -> bool:
    combined = (subject + " " + body).lower()
    return any(loc in combined for loc in ALLOWED_LOCATIONS)

REPLY_BODY = """Hi,

I hope you're doing well. I'm writing to express my interest in the Software Engineer opportunity.

I am a Senior Software Engineer with 10+ years of experience in web application development, specializing in frontend technologies including React.js, Angular, TypeScript, and JavaScript. I have hands-on expertise building scalable SPAs, reusable component libraries, REST API integrations, and CI/CD pipelines using Azure DevOps. I am experienced with Redux, React Router, Material UI, Tailwind CSS, React Native, and testing frameworks like Jest, with a strong background in Agile/Scrum environments and cross-functional team collaboration.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a great fit for your team.

Thank you for your time and consideration.

Best regards,
Manasa Janga
Phone: +1 609 323 0664
Email: mjanga90@gmail.com"""

ROLES = [
    {
        "name": "Senior Software Engineer",
        "cc_secret": "CC_SOFTWARE_ENGINEER",
        "keywords": [
            # Job title
            "software engineer", "senior software engineer", "sr software engineer",
            "sr. software engineer", "lead software engineer",
            "software developer", "senior software developer",
            "full stack engineer", "full stack developer",
            # Frontend focused
            "frontend engineer", "front end engineer", "front-end engineer",
            "frontend developer", "front end developer", "front-end developer",
            "senior frontend engineer", "senior frontend developer",
            "ui engineer", "ui developer", "ui/ux engineer",
            # React specific
            "react engineer", "react developer", "react.js developer",
            "react js developer", "senior react developer",
            "react native developer", "react native engineer",
            # Angular specific
            "angular developer", "angular engineer",
            "senior angular developer",
            # JavaScript / TypeScript
            "javascript developer", "javascript engineer",
            "typescript developer", "typescript engineer",
            # Web / SPA
            "web developer", "web application developer",
            "spa developer", "single page application developer",
            # Cloud / DevOps adjacent
            "azure frontend", "azure react developer",
        ],
    },
]


# ── Email Agent Class ──────────────────────────────────────────────────────────
class EmailAgent:

    def __init__(self, your_email: str, app_password: str):
        self.your_email   = your_email
        self.app_password = app_password
        self.mail         = None

    # ── IMAP Helpers ───────────────────────────────────────────────────────────

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(self.your_email, self.app_password)
        conn.select("inbox")
        return conn

    def connect(self):
        log.info("Connecting to Gmail via IMAP...")
        self.mail = self._imap_connect()
        self._ensure_label()

    def _ensure_label(self):
        try:
            self.mail.create(REPLIED_LABEL)
        except Exception:
            pass

    def _reconnect_if_needed(self, index: int):
        if index > 0 and index % 50 == 0:
            try:
                self.mail.logout()
            except Exception:
                pass
            log.info(f"  Reconnecting IMAP at email {index}...")
            time.sleep(1)
            self.mail = self._imap_connect()

    # ── Replied-IDs Tracking ───────────────────────────────────────────────────

    def get_replied_ids(self) -> set:
        replied = set()
        try:
            self.mail.select(REPLIED_LABEL)
            _, msg_ids = self.mail.search(None, "ALL")
            if msg_ids[0]:
                uid_list = ",".join(m.decode() for m in msg_ids[0].split())
                _, data = self.mail.fetch(uid_list, "(BODY[HEADER.FIELDS (MESSAGE-ID)])")
                for item in data:
                    if isinstance(item, tuple):
                        raw = item[1].decode("utf-8", errors="ignore")
                        match = re.search(r"Message-ID:\s*(.+)", raw, re.IGNORECASE)
                        if match:
                            replied.add(match.group(1).strip())
        except Exception:
            pass
        self.mail.select("inbox")
        log.info(f"Already replied to {len(replied)} emails previously")
        return replied

    def mark_as_replied(self, uid: str):
        for attempt in range(3):
            try:
                fresh = self._imap_connect()
                fresh.select("inbox")
                fresh.copy(uid, REPLIED_LABEL)
                fresh.logout()
                return
            except Exception as e:
                log.warning(f"  Mark attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        log.error("  Failed to mark email as replied after 3 attempts")

    # ── Email Fetching ─────────────────────────────────────────────────────────

    def _search_uids_by_keywords(self, today: str) -> set:
        uid_set = set()
        for role in ROLES:
            for kw in role["keywords"]:
                try:
                    _, msg_ids = self.mail.search(None, f'(UNSEEN SINCE "{today}" SUBJECT "{kw}")')
                    for uid in msg_ids[0].split():
                        uid_set.add(uid)
                except Exception:
                    pass
        return uid_set

    def _parse_header(self, uid) -> dict | None:
        _, hdr_data = self.mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])")
        if not hdr_data or hdr_data[0] is None:
            return None
        raw = hdr_data[0][1].decode("utf-8", errors="ignore")

        def extract(pattern):
            m = re.search(pattern, raw, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else ""

        subject    = extract(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)").replace("\r\n", " ").replace("\n", " ")
        message_id = extract(r"Message-ID:\s*(.+?)(?:\r?\n(?!\s)|\Z)") or uid.decode()
        sender     = extract(r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)")
        reply_to   = extract(r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)") or sender

        return {"subject": subject, "message_id": message_id, "sender": sender, "reply_to": reply_to}

    def _parse_body(self, uid) -> str:
        _, msg_data = self.mail.fetch(uid, "(BODY.PEEK[])")
        if not msg_data or msg_data[0] is None:
            return ""
        msg = emaillib.message_from_bytes(msg_data[0][1])
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
        else:
            return msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        return ""

    def fetch_matching_emails(self) -> list:
        replied_ids = self.get_replied_ids()
        today       = datetime.now().strftime("%d-%b-%Y")
        uid_set     = self._search_uids_by_keywords(today)
        log.info(f"Found {len(uid_set)} matching unread emails today")

        results, seen = [], set()
        for i, uid in enumerate(uid_set):
            uid_str = uid.decode()
            if uid_str in seen:
                continue
            seen.add(uid_str)
            self._reconnect_if_needed(i)

            try:
                headers = self._parse_header(uid)
                if not headers:
                    continue

                if headers["message_id"] in replied_ids:
                    log.info(f"  Already replied: {headers['subject'][:60]}")
                    continue

                if any(skip in headers["sender"].lower() for skip in SKIP_SENDERS):
                    log.info(f"  Skipping: {headers['subject'][:60]}")
                    continue

                body = self._parse_body(uid)
                results.append({**headers, "uid": uid_str, "body": body[:4000]})
                log.info(f"  Queued: {headers['subject'][:60]}")
                time.sleep(0.2)

            except Exception as e:
                log.error(f"Error reading email {uid_str}: {e}")
                time.sleep(1)

        log.info(f"Matched {len(results)} emails to reply to")
        return results

    # ── Role Detection ─────────────────────────────────────────────────────────

    @staticmethod
    def detect_role(email: dict) -> dict | None:
        subject = email["subject"].lower()
        body    = email.get("body", "").lower()

        for role in ROLES:
            if any(kw in subject for kw in role["keywords"]):
                if is_allowed_location(subject, body):
                    log.info(f"  Matched: {role['name']} (Florida or Remote)")
                    return role
                else:
                    log.info(f"  Skipping (not Florida/Remote): {subject[:60]}")
                    return None
        return None

    # ── Resume Loading ─────────────────────────────────────────────────────────

    @staticmethod
    def load_resume() -> bytes:
        # 1. Try environment variable first (GitHub Actions)
        b64_env = os.environ.get("RESUME_SOFTWARE_ENGINEER_B64", "")
        if b64_env.strip():
            log.info("  Resume: loaded from env variable")
            return base64.b64decode(re.sub(r'\s+', '', b64_env.strip()))
        # 2. Fallback to file (local)
        path = Path(RESUME_FILE)
        if not path.exists():
            raise FileNotFoundError(f"Resume file '{RESUME_FILE}' not found!")
        log.info(f"  Resume: {RESUME_FILE}")
        raw = path.read_bytes()
        if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            b64 = re.sub(r'\s+', '', raw.decode('utf-16').strip())
        else:
            b64 = re.sub(r'\s+', '', raw.decode('latin-1').strip())
        return base64.b64decode(b64)

    # ── Sending Reply ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_address(s: str) -> str:
        m = re.search(r"<(.+?)>", s)
        return m.group(1) if m else s.strip()

    def send_reply(self, email: dict, role: dict):
        to_email = self._extract_address(email["reply_to"] or email["sender"])
        cc_email = os.environ.get(role["cc_secret"], "")
        subject  = email["subject"] if email["subject"].lower().startswith("re:") else f"Re: {email['subject']}"

        msg = MIMEMultipart()
        msg["From"]    = self.your_email
        msg["To"]      = to_email
        msg["Subject"] = subject
        if cc_email:
            msg["Cc"] = cc_email

        msg.attach(MIMEText(REPLY_BODY, "plain"))

        resume_bytes = self.load_resume()
        attachment   = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
        attachment.set_payload(resume_bytes)
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f'attachment; filename="{RESUME_NAME}"')
        msg.attach(attachment)

        recipients = [to_email] + ([cc_email] if cc_email else [])
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(self.your_email, self.app_password)
            server.sendmail(self.your_email, recipients, msg.as_string())

        log.info(f"  Sent to: {to_email}")
        if cc_email:
            log.info(f"  CC'd:    {cc_email}")
        time.sleep(3)

    # ── CSV Logging ────────────────────────────────────────────────────────────

    @staticmethod
    def log_sent(email: dict, role: dict):
        csv_path = Path("logs/sent_log.csv")
        write_header = not csv_path.exists()
        with csv_path.open("a") as f:
            if write_header:
                f.write("timestamp,role,sender,subject,cc\n")
            cc = os.environ.get(role["cc_secret"], "none")
            f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

    # ── Main Run Loop ──────────────────────────────────────────────────────────

    def run(self):
        log.info("=" * 55)
        log.info("AI Email Agent - Manasa Janga (Senior Software Engineer)")
        log.info(f"Time: {datetime.now().isoformat()}")
        log.info("=" * 55)

        # ── TIME WINDOW CHECK ────────────────────────────────────────────────
        if not is_within_run_window():
            log.info("⏰ Outside run window (6:30 PM - 4:30 AM IST). Skipping.")
            return
        log.info("✅ Within run window (6:30 PM - 4:30 AM IST). Proceeding...")
        # ─────────────────────────────────────────────────────────────────────

        self.connect()
        emails  = self.fetch_matching_emails()
        matched = 0

        for email in emails:
            log.info(f"\nJOB EMAIL: {email['subject']}")
            log.info(f"   From: {email['sender']}")
            try:
                role = self.detect_role(email)
                if role is None:
                    log.info("  No matching role or location — skipping")
                    continue
                matched += 1
                self.send_reply(email, role)
                self.log_sent(email, role)
                self.mark_as_replied(email["uid"])
            except Exception as e:
                log.error(f"Error: {e}", exc_info=True)

        try:
            self.mail.logout()
        except Exception:
            pass

        log.info(f"\nDone - Replied to {matched} Software Engineer emails (Florida/Remote only)")
        log.info("Cost: 0.00")


# ── Entry Point ────────────────────────────────────────────────────────────────
def main():
    your_email   = os.environ.get("YOUR_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    missing = [k for k, v in {"YOUR_EMAIL": your_email, "GMAIL_APP_PASSWORD": app_password}.items() if not v]
    if missing:
        log.error(f"Missing secrets: {', '.join(missing)}")
        return

    EmailAgent(your_email, app_password).run()


if __name__ == "__main__":
    main()
