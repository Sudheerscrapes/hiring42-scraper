"""
daily_tracker.py
----------------
Tracks how many emails have been sent today via Gmail IMAP.
Reads the 'AutoReplied' label and counts only today's emails.
Run this anytime to check your daily send count.
"""

import imaplib
import email
from email.header import decode_header
from datetime import date
import os
import sys

# ── CONFIG ──────────────────────────────────────────────────────────────────
YOUR_EMAIL         = os.environ.get("IMAP_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("IMAP_APP_PASSWORD", "")
DAILY_LIMIT        = 500   # Gmail free account limit
SAFE_LIMIT         = 450   # We stop here to stay safe
LABEL              = "AutoReplied"
# ─────────────────────────────────────────────────────────────────────────────


def connect_imap(email_addr, password):
    print(f"🔌 Connecting to Gmail IMAP...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_addr, password)
    print(f"✅ Connected as {email_addr}")
    return mail


def count_today_sent(mail):
    """Count emails in AutoReplied label that were sent today."""
    today = date.today()
    today_str = today.strftime("%d-%b-%Y")

    status, _ = mail.select(f'"{LABEL}"')
    if status != "OK":
        print(f"❌ Could not find label '{LABEL}'. Make sure your agent has created it.")
        return 0

    status, messages = mail.search(None, f'(SINCE "{today_str}")')
    if status != "OK":
        print("❌ Search failed.")
        return 0

    email_ids = messages[0].split()
    count = len(email_ids)
    return count, email_ids


def show_today_subjects(mail, email_ids, limit=10):
    """Print the subjects of today's sent emails (first N)."""
    print(f"\n📋 Last {min(limit, len(email_ids))} emails replied to today:\n")
    for i, eid in enumerate(email_ids[-limit:], 1):
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="replace")
        sender = msg.get("From", "Unknown")
        print(f"  {i:>2}. {subject[:70]}")
        print(f"      From: {sender[:60]}\n")


def print_status(count):
    """Print a clear status dashboard."""
    remaining = DAILY_LIMIT - count
    safe_remaining = SAFE_LIMIT - count
    bar_filled = int((count / DAILY_LIMIT) * 30)
    bar = "█" * bar_filled + "░" * (30 - bar_filled)

    print("\n" + "═" * 55)
    print("   📊  DAILY EMAIL SEND TRACKER")
    print("═" * 55)
    print(f"   Date         : {date.today().strftime('%A, %B %d %Y')}")
    print(f"   Sent Today   : {count}")
    print(f"   Gmail Limit  : {DAILY_LIMIT}")
    print(f"   Safe Limit   : {SAFE_LIMIT}")
    print(f"   Remaining    : {remaining} (hard) / {max(0, safe_remaining)} (safe)")
    print(f"\n   [{bar}] {count}/{DAILY_LIMIT}")
    print()

    if count >= DAILY_LIMIT:
        print("   🔴 STATUS : LIMIT REACHED — Gmail will block sends")
    elif count >= SAFE_LIMIT:
        print("   🟠 STATUS : NEAR LIMIT — Stop sending soon")
    elif count >= DAILY_LIMIT * 0.7:
        print("   🟡 STATUS : 70% used — Monitor closely")
    else:
        print("   🟢 STATUS : OK — Safe to send")

    print("═" * 55 + "\n")


def main():
    if not YOUR_EMAIL or not GMAIL_APP_PASSWORD:
        print("❌ Missing credentials!")
        print("   Set environment variables:")
        print("   export IMAP_EMAIL='you@gmail.com'")
        print("   export IMAP_APP_PASSWORD='your-app-password'")
        sys.exit(1)

    mail = connect_imap(YOUR_EMAIL, GMAIL_APP_PASSWORD)

    result = count_today_sent(mail)
    if result == 0:
        count, email_ids = 0, []
    else:
        count, email_ids = result

    print_status(count)

    if email_ids:
        show_today_subjects(mail, email_ids, limit=10)
    else:
        print("   📭 No emails replied to today yet.\n")

    mail.logout()


if __name__ == "__main__":
    main()
