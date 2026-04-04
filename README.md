
# 📧 AI Email Agent - Recruitment Auto Responder

An automated email agent that replies to job recruitment emails with a resume attachment.
Runs every 15 minutes via GitHub Actions — completely free.

---

## How It Works

1. Connects to Gmail via IMAP
2. Searches today's unread emails by job-related keywords in the subject line
3. Matches emails to a role (DevOps, .NET, MuleSoft,sap SD,Data engineer etc.)
4. Sends a reply with the consultant's resume attached
5. Marks the email as replied to avoid duplicates
6. Resets daily at midnight (max 450 emails/day per agent)

---

## ⚡ Key Features & Fixes

1. Dedup checked FIRST before anything else — no duplicate replies ever
2. Dedup saved IMMEDIATELY after each send — safe even if script crashes mid-run
3. UTF-8-sig fix for dedup file — handles BOM encoding issues on Windows
4. Skips own sent emails — ignores sudheeritservices1 and rajumodhala777 as senders
5. Skips any email with subject starting with Re: — avoids replying to reply threads
6. SCAN from sudheeritservices1@gmail.com — single inbox watched by all agents
7. SEND from separate accounts — each consultant has their own sending email(zoho integrations-Gmail-Different accounts-integrations)
8. Daily send cap of 450 — avoids Gmail 550 limit errors and Zoho blocks
9. SINGLE SMTP connection reused for all emails — avoids Google/Zoho blocks
10. 5 second delay between sends — avoids spam detection triggers

---

## 👥 Consultants & Agents

| Agent | Consultant | Roles Covered | Scan Inbox | Send From |
|---|---|---|---|---|
| agent.py | Lingaraju Modhala | DevOps, Cloud, SRE, Kubernetes, Terraform | sudheeritservices1@gmail.com | rajumodhala777@gmail.com |
| agent_satish.py | Satish | Lead .NET, C#, Azure .NET, Full Stack .NET | sudheeritservices1@gmail.com | sudheer@adeptscripts.com |
| agent_kartick.py | Kartick Kiran | Lead MuleSoft, Anypoint, Integration | sudheeritservices1@gmail.com | sudheer@adeptscripts.com |

---

## Roles Covered

| Agent | Role | Example Keywords |
|---|---|---|
| Lingaraju | DevOps Engineer | devops, ci/cd, devsecops, release engineer, platform engineer |
| Lingaraju | Cloud Engineer | cloud architect, aws engineer, azure engineer, gcp engineer |
| Lingaraju | Site Reliability Engineer | site reliability, sre engineer, sre lead |
| Lingaraju | Kubernetes / Docker | kubernetes, k8s, docker, openshift, helm |
| Lingaraju | Terraform / Automation | terraform, ansible, gitops, infrastructure automation |
| Satish | Lead .NET Developer | lead .net, senior .net, .net tech lead, principal .net |
| Satish | .NET / C# Developer | .net developer, c# developer, asp.net, dotnet core |
| Satish | Azure .NET Developer | azure .net, microservices .net, web api, asp.net mvc |
| Satish | Full Stack .NET | full stack .net, .net angular, .net react |
| Kartick | Lead MuleSoft Developer | lead mulesoft, senior mulesoft, mulesoft tech lead |
| Kartick | MuleSoft Developer | mulesoft developer, anypoint platform, mule4, mule esb |
| Kartick | Integration Developer | integration developer, middleware, esb developer |

---

## Setup

### 1. Clone the repo

git clone https://github.com/Sudheerscrapes/email-agent.git
cd email-agent

### 2. Add your resume
Convert your .docx resume to base64 using certutil (Windows):

certutil -encode "Your_Resume.docx" resume_name_b64.txt

### 3. Set GitHub Secrets
Go to Settings -> Secrets and variables -> Actions and add:

| Secret | Description |
|---|---|
| IMAP_EMAIL | sudheeritservices1@gmail.com |
| IMAP_APP_PASSWORD | Gmail App Password |
| SMTP_EMAIL | rajumodhala777@gmail.com |
| SMTP_APP_PASSWORD | Gmail App Password |
| SATISH_SMTP_EMAIL | sudheer@adeptscripts.com |
| SATISH_SMTP_APP_PASSWORD | Zoho App Password |
| KARTICK_SMTP_EMAIL | sudheer@adeptscripts.com |
| KARTICK_SMTP_APP_PASSWORD | Zoho App Password |
| CC_DEVOPS | CC email for DevOps replies |
| CC_CLOUD | CC email for Cloud replies |
| CC_SRE | CC email for SRE replies |
| CC_SATISH | CC email for .NET replies |
| CC_KARTICK | CC email for MuleSoft replies |

### 4. Enable Gmail IMAP
Gmail -> Settings -> See all settings -> Forwarding and POP/IMAP -> Enable IMAP

### 5. Generate Gmail App Password
Google Account -> Security -> 2-Step Verification -> App Passwords -> Generate

### 6. Generate Zoho App Password
Zoho Account -> Security -> Multi-Factor Authentication -> Enable -> App Passwords -> Generate

---

## Schedule

Runs every 15 minutes automatically via GitHub Actions.
You can also trigger it manually from the Actions tab.
Only runs between 6:30 PM - 4:30 AM IST to target US business hours.

---

## Unread Email Preservation

Emails that are read but do not match any role are kept as unread in your inbox.
This ensures other email agents running on the same inbox can still find and process those emails.
Only emails that receive a reply are marked as handled.

---

## Duplicate Prevention

Every replied email is copied to a Gmail label (AutoReplied, AutoReplied_Satish, AutoReplied_Kartick).
On each run, the agent checks this label and skips any already-replied emails.
A daily dedup file also tracks replied senders and resets at midnight.

---

## Adding a New Consultant

1. Encode resume: certutil -encode "Resume.docx" resume_name_b64.txt
2. Create agent_name.py with role keywords
3. Create .github/workflows/agent_name.yml
4. Add secrets in GitHub Settings
5. git add, commit and push

---

## Logs

| File | Description |
|---|---|
| logs/agent.log | Lingaraju run log |
| logs/agent_satish.log | Satish run log |
| logs/agent_kartick.log | Kartick run log |
| logs/sent_log.csv | Lingaraju sent emails |
| logs/sent_log_satish.csv | Satish sent emails |
| logs/sent_log_kartick.csv | Kartick sent emails |

Logs are uploaded as GitHub Actions artifacts after every run.
Download from Actions -> latest run -> Artifacts.

---


