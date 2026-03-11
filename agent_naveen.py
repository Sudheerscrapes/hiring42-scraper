"""
AI Email Agent - Naveen
Only replies to: SAP SD / OTC roles
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
        logging.FileHandler("logs/agent_naveen.log"),
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
RESUME_FILE   = "resume_naveen_sap_sd_b64.txt"
RESUME_NAME   = "Resume_Naveen_SAP_SD.docx"
SKIP_SENDERS  = ["noreply@", "mailer-daemon@", "notifications@github.com", "noreply.github.com"]

# ── Role Blocklist — skip emails mentioning these roles even if SAP SD keyword matches ──
BLOCKED_ROLES = [
    "project manager", "program manager", "product manager",
    "sap manager", "engagement manager", "delivery manager",
    "account manager", "practice manager", "service manager",
    "scrum master", "agile coach",
    "sap director", "director of sap",
    "sap architect", "solution architect", "enterprise architect",
    "sap abap", "abap developer", "abap consultant",
    "sap basis", "basis consultant", "basis administrator",
    "sap fico", "sap fi consultant", "sap co consultant",
    "sap mm consultant", "sap wm consultant", "sap pp consultant",
    "sap hcm", "sap hr consultant", "sap successfactors",
    "sap crm", "sap ariba", "sap mdg",
    "sap technical", "sap developer",
]

def is_blocked_role(subject: str) -> bool:
    subject_lower = subject.lower()
    return any(blocked in subject_lower for blocked in BLOCKED_ROLES)

REPLY_BODY = """Hi,

I hope you're doing well. I'm writing to express my interest in the SAP SD opportunity.

I am a results-driven SAP SD Functional Consultant with 6+ years of experience in end-to-end Order-to-Cash (OTC) implementations and support projects across SAP ECC and S/4HANA environments. I have hands-on expertise in Sales Document Management, Pricing & Condition Technique, Shipping & Logistics Execution, Billing & FI Integration, Credit Management, and Warehouse Management (WM). I have successfully delivered SAP SD projects for leading global clients including UnitedHealth Group, Procter & Gamble, and Siemens, with strong cross-module integration experience across SD-FI, SD-MM, and Logistics Execution.

I've attached my resume for your review. I'd appreciate the opportunity to connect and discuss how my skills could be a great fit for your team.

Thank you for your time and consideration.

Best regards,
Naveen
Phone: 
Email: naveenkadiyalasapsd@gmail.com"""

ROLES = [
    {
        "name": "SAP SD Consultant",
        "cc_secret": "CC_NAVEEN_SAP_SD",
        "keywords": [
            # SAP SD core titles
            "sap sd", "sap sd consultant", "sap sd functional consultant",
            "sap sd functional", "senior sap sd", "sr sap sd",
            "lead sap sd", "sap sd lead",
            "sap sales and distribution", "sap sales & distribution",

            # OTC / Order to Cash
            "sap otc", "order to cash", "order-to-cash",
            "otc consultant", "otc functional consultant",
            "sap order to cash", "sap order-to-cash",

            # S/4HANA SD
            "s/4hana sd", "s4hana sd", "sap s/4 sd",
            "s/4hana sales", "s4hana sales",
            "sap s/4hana functional", "s/4hana functional consultant",

            # SAP Functional broad
            "sap functional consultant", "sap ecc consultant",
            "sap ecc sd", "sap functional analyst",

            # Pricing / Billing / Shipping
            "sap pricing consultant", "sap billing consultant",
            "sap shipping consultant", "sap logistics execution",
            "sap le consultant", "sap delivery consultant",

            # Credit Management
            "sap credit management", "sap credit consultant",

            # Warehouse Management
            "sap wm consultant", "sap warehouse management",
            "sap wm sd",

            # Cross-module integration
            "sap sd fi", "sap sd mm", "sap sd fi mm",
            "sap fi sd consultant", "sap mm sd consultant",

            # General SAP roles that may include SD
            "sap consultant", "sap functional",
            "sap implementation consultant", "sap support consultant",
            "sap business analyst", "sap solution consultant",
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

        # First check blocklist — skip unwanted roles
        if is_blocked_role(subject):
            log.info(f"  Blocked role detected — skipping: {subject[:60]}")
            return None

        for role in ROLES:
            if any(kw in subject for kw in role["keywords"]):
                log.info(f"  Matched: {role['name']}")
                return role
        return None

    # ── Resume Loading ─────────────────────────────────────────────────────────

    @staticmethod
    def load_resume() -> bytes:
        # 1. Try environment variable first (GitHub Actions)
        b64_env = os.environ.get("RESUME_NAVEEN_SAP_SD_B64", "")
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
        cc_email = os.environ.get(role["cc_secret"], "naveenkadiyalasapsd@gmail.com")
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
            cc = os.environ.get(role["cc_secret"], "naveenkadiyalasapsd@gmail.com")
            f.write(f'{datetime.now().isoformat()},"{role["name"]}","{email["sender"]}","{email["subject"]}","{cc}"\n')

    # ── Main Run Loop ──────────────────────────────────────────────────────────

    def run(self):
        log.info("=" * 55)
        log.info("AI Email Agent - Naveen (SAP SD Consultant)")
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

        log.info(f"\nDone - Replied to {matched} SAP SD emails")
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
