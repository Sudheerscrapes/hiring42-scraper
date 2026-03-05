# AI Email Agent -recruitment-auto-responder
An automated Gmail agent that replies to job recruitment emails with a resume attachment. Runs every 15 minutes via GitHub Actions — completely free.

---

## How It Works

1. Connects to Gmail via IMAP
2. Searches today's unread emails by job-related keywords in the subject line
3. Matches emails to a role (DevOps, Cloud Engineer, or SRE)
4. Sends a reply with the resume attached
5. Marks the email as replied to avoid duplicates

---

## Roles Covered(#example)

| Role | Example Keywords |
|------|-----------------|
| DevOps Engineer | devops, ci/cd, devsecops, release engineer, platform engineer |
| Cloud Engineer | cloud architect, aws engineer, azure engineer, gcp engineer |
| Site Reliability Engineer | site reliability, sre engineer, sre lead |

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Sudheerscrapes/email-agent.git
cd email-agent
```

### 2. Add your resume

Convert your `.docx` resume to base64 and save as `resume_b64.txt`:

```python
python -c "
import base64
from pathlib import Path
data = Path('Your_Resume.docx').read_bytes()
Path('resume_b64.txt').write_text(base64.b64encode(data).decode('ascii'))
"
```

### 3. Set GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|--------|-------------|
| `YOUR_EMAIL` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your regular password) |
| `RESUME_DEVOPS_B64` | Base64 encoded resume for DevOps roles |
| `RESUME_CLOUD_B64` | Base64 encoded resume for Cloud roles |
| `RESUME_SRE_B64` | Base64 encoded resume for SRE roles |
| `CC_DEVOPS` | (Optional) CC email for DevOps replies |
| `CC_CLOUD` | (Optional) CC email for Cloud replies |
| `CC_SRE` | (Optional) CC email for SRE replies |

### 4. Enable Gmail IMAP

In Gmail → **Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP**

### 5. Generate Gmail App Password

**Google Account → Security → 2-Step Verification → App Passwords → Generate**

---

## Schedule

Runs every 15 minutes automatically via GitHub Actions. You can also trigger it manually from the **Actions** tab.

---

## Unread Email Preservation

Emails that are read but **do not match any role** are kept as **unread** in your inbox. This ensures other email agents running on the same inbox can still find and process those emails. Only emails that receive a reply are marked as handled.

---

## Duplicate Prevention

Every replied email is copied to an `AutoReplied` Gmail label. On each run, the agent checks this label and skips any already-replied emails.

---

## Logs

Logs are uploaded as GitHub Actions artifacts after every run. Download from **Actions → latest run → Artifacts**.
