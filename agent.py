"""
AI Email Agent - Lingaraju Modhala - FIXED VERSION
Only replies to: DevOps, Cloud Engineer, SRE
FIX: Persistent dedup that ACTUALLY WORKS - never replies twice to same sender, EVER.
"""

import os, base64, logging, re, smtplib, time, json
from pathlib import Path
from datetime import datetime, time as dtime
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
# 🔒 PERSISTENT DEDUP - This ACTUALLY WORKS
# ══════════════════════════════════════════════════════════════════════════════
DEDUP_FILE = Path("logs") / "replied_senders.json"

def load_replied_senders():
    """Load all senders we've ever replied to."""
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r") as f:
                data = json.load(f)
                log.info(f"✅ LOADED: {len(data)} senders (will NEVER reply to them)")
                return set(data)
        except Exception as e:
            log.warning(f"⚠️ Could not load dedup file: {e}")
    log.info("📋 No dedup file yet - creating new one")
    return set()

def save_replied_sender(sender_email: str):
    """Save sender so we NEVER reply to them again."""
    if not sender_email:
        log.warning("⚠️ Empty sender email - not saving")
        return
    
    sender_email = sender_email.lower().strip()
    existing = load_replied_senders()
    
    if sender_email in existing:
        log.info(f"⚠️ Already in dedup list: {sender_email}")
        return
    
    existing.add(sender_email)
    try:
        with open(DEDUP_FILE, "w") as f:
            json.dump(sorted(list(existing)), f, indent=2)
        log.info(f"✅ SAVED TO DEDUP: {sender_email} (NEVER reply again)")
    except Exception as e:
        log.error(f"❌ Could not save dedup file: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ⏰ TIME WINDOW CHECK
# ══════════════════════════════════════════════════════════════════════════════
def is_within_run_window():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    current_time = now.time()
    start = dtime(18, 30)  # 6:30 PM IST
    end   = dtime(4, 30)   # 4:30 AM IST
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
SKIP_SENDERS  = ["noreply@", "mailer-daemon@", "notifications@github.com", "noreply.github.com"]

def extract_address(s):
    """Extract email from 'Name <email@example.com>' format."""
    if not s:
        return ""
    m = re.search(r"<(.+?)>", s)
    return (m.group(1) if m else s).strip().lower()

def connect_imap(your_email, app_password):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(your_email, app_password)
    mail.select("inbox")
    return mail

def ensure_label_exists(mail):
    try: mail.create(REPLIED_LABEL)
    except Exception: pass

def get_replied_message_ids(mail):
    """Get Message-IDs from AutoReplied Gmail label."""
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
    log.info("🔌 Connecting to Gmail via IMAP...")
    mail = connect_imap(your_email, app_password)
    ensure_label_exists(mail)
    replied_ids = get_replied_message_ids(mail)
    log.info(f"📋 Gmail AutoReplied label: {len(replied_ids)} emails")

    # ✅ LOAD PERSISTENT SENDER DEDUP
    replied_senders = load_replied_senders()

    today = datetime.now().strftime("%d-%b-%Y")

    # Search for emails
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
    log.info(f"🔍 Found {len(ids)} matching unread emails today")

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
            _, hdr_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID REPLY-TO)])")
            if not hdr_data or hdr_data[0] is None: continue
            hdr_raw = hdr_data[0][1].decode("utf-8", errors="ignore")

            # Extract fields
            subj_match = re.search(r"Subject:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            subject = subj_match.group(1).strip().replace("\r\n", " ").replace("\n", " ") if subj_match else ""

            mid_match = re.search(r"Message-ID:\s*(.+)", hdr_raw, re.IGNORECASE)
            message_id = mid_match.group(1).strip() if mid_match else uid_str

            sender_match = re.search(r"From:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            sender = sender_match.group(1).strip() if sender_match else ""

            rt_match = re.search(r"Reply-To:\s*(.+?)(?:\r?\n(?!\s)|\Z)", hdr_raw, re.IGNORECASE | re.DOTALL)
            reply_to = rt_match.group(1).strip() if rt_match else sender

            # Check 1: Skip system senders
            if any(skip in sender.lower() for skip in SKIP_SENDERS):
                log.info(f"  ⏭️  System sender: {subject[:50]}")
                continue

            # Check 2: Skip if already replied by Message-ID
            if message_id in replied_ids:
                log.info(f"  ⏭️  Already replied (Message-ID): {subject[:50]}")
                continue

            # Check 3: PERSISTENT SENDER CHECK - THIS IS THE KEY FIX!
            sender_addr = extract_address(reply_to or sender)
            if not sender_addr:
                log.warning(f"  ⚠️  Could not extract sender email from: {sender}")
                continue
                
            if sender_addr in replied_senders:
                log.info(f"  ⏭️  BLOCKED: Already replied to {sender_addr} - {subject[:50]}")
                continue

            # Get body
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
                "uid": uid_str, 
                "message_id": message_id,
                "subject": subject, 
                "sender": sender,
                "reply_to": reply_to, 
                "body": body[:4000],
                "sender_addr": sender_addr  # Pre-extracted!
            })
            log.info(f"  ✅ Queued: {subject[:50]} from {sender_addr}")
            time.sleep(0.2)

        except Exception as e:
            log.error(f"❌ Error reading email {uid_str}: {e}")
            time.sleep(1)

    log.info(f"📊 Ready to reply to {len(emails)} emails")
    return emails, mail

def detect_role(email):
    subject = email["subject"].lower()
    for role in ROLES:
        if any(kw in subject for kw in role["keywords"]):
            log.info(f"  🎯 Matched: {role['name']}")
            return role
    return None

def get_resume(role):
    fname = role["resume_file"]
    if not Path(fname).exists(): raise ValueError(f"Resume file '{fname}' not found!")
    log.info(f"  📎 Resume: {fname}")
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
    
    log.info(f"  📤 Sent to: {to_email}")
    if cc_email: log.info(f"  📋 CC'd: {cc_email}")
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
    log.info("🤖 AI Email Agent - Lingaraju Modhala (FIXED VERSION)")
    log.info("⚠️  FIX: Persistent dedup - NEVER replies twice to same sender")
    log.info(f"⏰ Time: {datetime.now().isoformat()}")
    log.info("=" * 70)

    if not is_within_run_window():
        log.info("⏰ Outside run window (6:30 PM - 4:30 AM IST). Skipping.")
        return
    log.info("✅ Within run window (6:30 PM - 4:30 AM IST). Proceeding...")

    your_email   = os.environ.get("YOUR_EMAIL", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    missing = []
    if not your_email:   missing.append("YOUR_EMAIL")
    if not app_password: missing.append("GMAIL_APP_PASSWORD")
    if missing:
        log.error(f"❌ Missing secrets: {', '.join(missing)}")
        return

    emails, mail = fetch_matching_emails(your_email, app_password)

    # Within-run dedup (extra safety layer)
    sent_senders = set()

    matched = 0
    for email in emails:
        log.info(f"\n📧 JOB EMAIL: {email['subject']}")
        log.info(f"   👤 From: {email['sender']}")
        
        try:
            sender_addr = email.get("sender_addr", extract_address(email["reply_to"] or email["sender"]))
            
            # Within-run check
            if sender_addr in sent_senders:
                log.info(f"  ⏭️  Already replied to {sender_addr} in THIS RUN")
                continue

            role = detect_role(email)
            if role is None:
                log.info("  ⏭️  No matching role")
                continue

            matched += 1
            log.info(f"  ✅ SENDING REPLY...")
            send_reply(email, role, your_email, app_password)
            log_sent(email, role)
            mail = mark_as_replied(mail, email["uid"], your_email, app_password)

            # ✅ SAVE TO PERSISTENT DEDUP IMMEDIATELY
            save_replied_sender(sender_addr)
            
            sent_senders.add(sender_addr)

        except Exception as e:
            log.error(f"❌ Error: {e}", exc_info=True)

    try: mail.logout()
    except Exception: pass
    
    log.info("\n" + "=" * 70)
    log.info(f"✅ Done - Replied to {matched} job emails")
    log.info(f"💾 Persistent dedup file: {DEDUP_FILE}")
    log.info("💰 Cost: 0.00")
    log.info("=" * 70)

if __name__ == "__main__":
    main()
