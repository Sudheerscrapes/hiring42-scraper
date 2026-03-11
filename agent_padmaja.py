"""
AI Email Agent - Padmaja Ambati
Only replies to: SAP SAC / Datasphere / BI Analytics roles
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
        logging.FileHandler("logs/agent_padmaja.log"),
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
RESUME_FILE   = "resume_padmaja_sac_b64.txt"
RESUME_NAME   = "Resume_Padmaja_Ambati_SAC_Datasphere.docx"
SKIP_SENDERS  = ["noreply@", "mailer-daemon@", "notifications@github.com", "noreply.github.com"]

# ── Role Blocklist — skip emails mentioning these roles ────────────────────────
BLOCKED_ROLES = [
    "project manager", "program manager", "product manager",
    "engagement manager", "delivery manager", "account manager",
    "sap manager", "practice manager", "service manager",
    "scrum master", "agile coach",
    "sap director", "director of sap",
    "sap sd consultant", "sap sd functional",
    "sap abap", "abap developer", "abap consultant",
    "sap basis", "basis consultant",
    "sap mm consultant", "sap pp consultant",
    "sap hcm", "sap hr consultant",
    "sap crm", "sap ariba",
    "sap technical consultant", "sap developer",
    # Power BI — not applicable
    "power bi consultant", "power bi developer", "power bi analyst",
    "power bi architect", "senior power bi", "lead power bi",
    "power bi engineer", "power bi specialist",
    # Other unrelated SAP/non-SAP roles
    "sap rar", "sap revenue accounting",
    "workforce software", "workforce management",
    "hotlist", "available consultants", "bench consultants",
    "sap fico", "sap fi consultant", "sap co consultant",
    "sap mm", "sap pp", "sap wm", "sap pm",
    "sap successfactors", "sap hcm", "sap hr",
    "sap ariba", "sap mdg", "sap ewm",
    "sap tm consultant", "sap apo",
]

def is_blocked_role(subject: str) -> bool:
    subject_lower = subject.lower()
    return any(blocked in subject_lower for blocked in BLOCKED_ROLES)

# ── Location Filter ────────────────────────────────────────────────────────────
ALLOWED_LOCATIONS = ["texas", "remote", "tx,", " tx ", "(tx)", ", tx"]

def is_allowed_location(subject: str, body: str) -> bool:
    combined = (subject + " " + body).lower()
    return any(loc in combined for loc in ALLOWED_LOCATIONS)

REPLY_BODY = """Hi,

I hope you're doing well. I'm writing to express my interest in the SAP Analytics / BI opportunity.

I am a Senior BI and Analytics Consultant with 15+ years of experience delivering enterprise reporting and analytics solutions across healthcare and retail domains. I have strong expertise in SAP Datasphere, SAP Analytics Cloud (SAC), Power BI, and Tableau for operational and executive analytics. I have proven experience integrating data from SAP S/4HANA, ECC, and non-SAP systems into centralized analytics platforms, designing scalable multi-layer data models, ETL pipelines, and governed semantic layers. I have delivered real-time dashboards for claims processing, benefits administration, workforce, payroll, finance, and supply chain analytics, with deep experience in SAC Planning, FP&A, budgeting, forecasting, and data governance.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a great fit for your team.

Thank you for your time and consideration.

Best regards,
Padmaja Ambati
Phone: 720-401-3612
Email: padmaja8419@gmail.com"""

ROLES = [
    {
        "name": "SAP SAC / Datasphere Consultant",
        "cc_secret": "CC_PADMAJA_SAC",
        "keywords": [
            # SAP Analytics Cloud (SAC)
            "sap analytics cloud", "sap sac", "sac consultant",
            "sac developer", "sac planning", "sac reporting",
            "senior sac consultant", "lead sac consultant",
            "sac functional consultant", "sac technical consultant",

            # SAP Datasphere
            "sap datasphere", "datasphere consultant",
            "datasphere developer", "datasphere architect",
            "sap bdc", "sap bdc consultant",

            # SAP BW / BW4HANA
            "sap bw consultant", "sap bw developer",
            "sap bw/4hana", "bw4hana consultant",
            "sap bw on hana", "sap bw4 hana",
            "sap bi consultant", "sap bi developer",
            "sap business intelligence",

            # SAP BPC
            "sap bpc consultant", "sap bpc developer",
            "sap bpc planning", "bpc standard",

            # SAP HANA
            "sap hana consultant", "sap hana developer",
            "hana modeler", "sap hana modeling",

            # SAP BusinessObjects
            "sap businessobjects", "sap bobj",
            "business objects consultant", "webi consultant",
            "crystal reports consultant",

            # Tableau
            "tableau developer", "tableau consultant",
            "senior tableau developer", "lead tableau developer",
            "tableau architect", "tableau analyst",

            # BI / Analytics general
            "bi consultant", "bi developer", "bi analyst",
            "bi architect", "bi lead", "bi manager",
            "business intelligence consultant",
            "business intelligence developer",
            "analytics consultant", "analytics developer",
            "senior analytics consultant", "lead analytics consultant",
            "data analytics consultant", "data analytics developer",

            # FP&A / Planning
            "fp&a consultant", "financial planning analyst",
            "sac fp&a", "planning consultant",
            "budgeting forecasting consultant",

            # Cloud BI / Migration
            "sap btp consultant", "sap btp developer",
            "tableau cloud migration",
            "bi cloud consultant",

            # Reporting
            "enterprise reporting consultant",
            "ssrs developer", "ssis developer",
            "ssas developer", "data warehouse consultant",
        ],
    },
]


# ── Body Keywords — search email body for these SAP-specific terms ─────────────
BODY_KEYWORDS = [
    "sap analytics cloud", "sap sac", "sac consultant", "sac planning",
    "sap datasphere", "datasphere consultant", "sap bdc",
    "sap bw consultant", "sap bw developer", "bw/4hana",
    "sap businessobjects", "sap bobj",
]

def matches_body_keywords(body: str) -> bool:
    body_lower = body.lower()
    return any(kw in body_lower for kw in BODY_KEYWORDS)

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
        # Search by subject keywords
        for role in ROLES:
            for kw in role["keywords"]:
                try:
                    _, msg_ids = self.mail.search(None, f'(UNSEEN SINCE "{today}" SUBJECT "{kw}")')
                    for uid in msg_ids[0].split():
                        uid_set.add(uid)
                except Exception:
                    pass
        # Also search by body keywords
        for kw in BODY_KEYWORDS:
            try:
                _, msg_ids = self.mail.search(None, f'(UNSEEN SINCE "{today}" BODY "{kw}")')
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

        subject_raw = extract(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)").replace("\r\n", " ").replace("\n", " ")
        from email.header import decode_header
        decoded_parts = decode_header(subject_raw)
        subject = ""
        for part, enc in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(enc or "utf-8", errors="ignore")
            else:
                subject += part
        subject = subject.strip()
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

        # First check blocklist — skip unwanted roles
        if is_blocked_role(subject):
            log.info(f"  Blocked role detected — skipping: {subject[:60]}")
            return None

        for role in ROLES:
            subject_match = any(kw in subject for kw in role["keywords"])
            body_match    = matches_body_keywords(body)

            if subject_match or body_match:
                match_source = "subject" if subject_match else "body"
                if is_allowed_location(subject, body):
                    log.info(f"  Matched via {match_source}: {role['name']} (Texas or Remote)")
                    return role
                else:
                    log.info(f"  Skipping (not Texas/Remote): {subject[:60]}")
                    return None
        return None

    # ── Resume Loading ─────────────────────────────────────────────────────────

    @staticmethod
    def load_resume() -> bytes:
        # 1. Try environment variable first (GitHub Actions)
        b64_env = os.environ.get("RESUME_PADMAJA_SAC_B64", "")
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
        cc_emails = [
            os.environ.get(role["cc_secret"], "padmaja8419@gmail.com"),
            "sudheerkumar@dgpeople.com",
        ]
        cc_emails = [c for c in cc_emails if c]
        cc_str    = ", ".join(cc_emails)
        subject   = email["subject"] if email["subject"].lower().startswith("re:") else f"Re: {email['subject']}"

        msg = MIMEMultipart()
        msg["From"]    = self.your_email
        msg["To"]      = to_email
        msg["Subject"] = subject
        if cc_str:
            msg["Cc"] = cc_str

        msg.attach(MIMEText(REPLY_BODY, "plain"))

        resume_bytes = self.load_resume()
        attachment   = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
        attachment.set_payload(resume_bytes)
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f'attachment; filename="{RESUME_NAME}"')
        msg.attach(attachment)

        recipients = [to_email] + cc_emails
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(self.your_email, self.app_password)
            server.sendmail(self.your_email, recipients, msg.as_string())

        log.info(f"  Sent to: {to_email}")
        for c in cc_emails:
            log.info(f"  CC'd:    {c}")
        time.sleep(3)

    # ── CSV Logging ────────────────────────────────────────────────────────────

    @staticmethod
    def log_sent(email: dict, role: dict):
        csv_path = Path("logs/sent_log.csv")
        write_header = not csv_path.exists()
        with csv_path.open("a") as f:
            if write_header:
                f.write("timestamp,role,sender,subject,cc\n")
            cc = "padmaja8419@gmail.com, sudheerkumar@dgpeople.com"
            f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

    # ── Main Run Loop ──────────────────────────────────────────────────────────

    def run(self):
        log.info("=" * 55)
        log.info("AI Email Agent - Padmaja Ambati (SAP SAC/Datasphere)")
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
        sent_ids = set()

        for email in emails:
            log.info(f"\nJOB EMAIL: {email['subject']}")
            log.info(f"   From: {email['sender']}")
            try:
                if email["message_id"] in sent_ids:
                    log.info("  Duplicate in this run — skipping")
                    continue
                role = self.detect_role(email)
                if role is None:
                    log.info("  No matching role — skipping")
                    continue
                matched += 1
                self.send_reply(email, role)
                self.log_sent(email, role)
                self.mark_as_replied(email["uid"])
                sent_ids.add(email["message_id"])
            except Exception as e:
                log.error(f"Error: {e}", exc_info=True)

        try:
            self.mail.logout()
        except Exception:
            pass

        log.info(f"\nDone - Replied to {matched} SAP SAC/Datasphere emails")
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
