# HOW TO RUN THIS PROJECT - HOPE JOHN SUNDAY

**Folder:** `C:\Users\nyong\Downloads\Jobs`
**Goal:** Every day, find new IT / cloud / junior tech jobs that fit you, and apply to them — from your own computer.

Nothing in this project applies for you by itself. It finds jobs, helps you fill forms and write emails, and keeps a tracker — but **you stay in charge** of every submission.

---

## 1. WHAT THE SYSTEM DOES

```
                        ┌────────────────────────────────────────────┐
│  job_scraper.py   (Your daily scanner)     │
│  12 job sources: MyJobMag, Jobberman,      │
│  HotNigerianJobs, RemoteOK, Arbeitnow,     │
│  Remotive, Working Nomads, Himalayas,      │
│  Virtual Click Jobs, Jobspresso,           │
│  Jobicy, HN Who-is-Hiring                  │
                        └──────────────────┬─────────────────────────┘
                                           │
              (optional, extra coverage)   ├─  career_crawler.py
              crawls company career pages  │    (worldwide, finds ATS
              detected from your scan      │     job boards to read)
                                           ▼
data/scanned_jobs.json
                                           │
                          ┌────────────────┴─────────────────┐
                          │  import_scanned_jobs.py          │
                          │  (adds new jobs to tracker)      │
                          └────────────────┬─────────────────┘
                                           ▼
                                   applications.csv
                          (Your list of jobs + what to do)
                                           │
              ┌────────────────────────────┴───────────────────────────┐
              │                                                         │
              ▼                                                         ▼
   EMAIL applications                                        PORTAL/WEB applications
   extract_email_targets.py                                     python apply_all.py --auto
   send_applications.py --send                                   (or prefill_top_jobs.bat)
```

The **tracker** (`applications.csv`) is the heart of the system. Every job is a row with a status, and every script reads or writes it.

---

## 2. FILES AT A GLANCE

| File | What it does |
|------|--------------|
| `job_scraper.py` | Daily scanner. Pulls jobs from 12 sources, keeps only ones matching your skills, scores them. |
| `career_crawler.py` | Optional worldwide crawler. Probes company career pages from your scan and reads their job listings. Saves to `data/career_jobs.json`. |
| `import_scanned_jobs.py` | Merges new jobs from `data/scanned_jobs.json` into `applications.csv` as **TO_APPLY**. Safe to re-run (no duplicates). |
| `data/scanned_jobs.json` | Full results of your last scan (read it to review jobs). |
| `data/new_jobs_alert.json` | Only the jobs that are **NEW** since yesterday. Your first thing to look at. |
| `applications.csv` | The tracker. One line per job: status, apply link, next follow-up. |
| `extract_email_targets.py` | Looks at your **TO_APPLY** jobs, finds the recruiter's email, picks the right CV, writes a tailored letter. Output: `data/email_targets.json`. |
| `send_applications.py` | Sends those emails from your Gmail and marks rows **EMAILED**. **Requires `--send` to actually send.** |
| `apply_all.py` | Batch portal applier. Opens each job site in a browser, pre-fills the form, pauses for you at CAPTCHAs. `--auto` clicks submit itself when no CAPTCHA. |
| `prefill_top_jobs.bat` | Same idea, one job at a time with a menu (pick 1–15, browser opens, you submit). |
| `prefill_apply.py` | The filler engine both of the above use. |
| `data/daily_scans\` | A dated snapshot file per scan (used to detect new jobs). |
| `run_daily_scan.bat` | Double-click shortcut to run the daily scanner. |
| `run_daily_scan_silent.bat` | Same, but writes to `logs/daily_scan.log` instead of popping a window (for Task Scheduler). |
| `sender_config.env` | Your Gmail app password. **Never share or paste this file anywhere.** |
| `cv_pdfs\` | Your generated CV PDFs (IT Support, Developer, Cloud/AWS). The scripts pick the right one automatically. |
| `cv_text\` | The plain-text CV sources `cv_to_pdf.py` converts into `cv_pdfs\`. |

---

## 3. YOUR DAILY ROUTINE (STEP BY STEP)

### STEP 1 — Scan for jobs (do this every day)

Double-click `run_daily_scan.bat`  — or in a terminal:

```
python job_scraper.py
```

This takes ~1–2 minutes and prints how many matches it found from each source.

Optional extra coverage (~30 seconds):
```
python career_crawler.py
python job_scraper.py      # re-run so the career-page jobs get merged in
```

### STEP 2 — Add the new jobs to your tracker

```
python import_scanned_jobs.py
```

New jobs appear in `applications.csv` as **TO_APPLY**. Re-runs are safe — it never duplicates.

### STEP 3 — Review what came in

Open `data/new_jobs_alert.json` (or just read the console output). Ask yourself:
- Is it **onsite Nigeria** (Uyo, PH, Lagos, Abuja)? High priority.
- Is it **remote/global**? Good too, once you verify it actually hires internationally.
- Is the company/site sketchy? (see Safety section) — skip it if so.
- If a job clearly doesn't fit or is a scam, change its status in `applications.csv` to **WATCHLIST** or delete the row.

### STEP 4 — Apply. Two routes (pick per job):

**Route A — Email application (fastest, works for most TO_APPLY jobs)**
```
python extract_email_targets.py
```
This reads your TO_APPLY jobs, grabs recruiter emails, writes your targeted letters, and stages them in `data/email_targets.json`. It prints how many targets it found.

First check the list without sending anything:
```
python send_applications.py
```
It prints exactly what it WOULD send (to whom, CV, letter). Review it.

To actually send (preview first with `--limit`):
```
python send_applications.py --send --limit 5     # send 5
python send_applications.py --send               # send all staged
```
After sending, those rows become **EMAILED**.

**Route B — Website/portal application (for jobs with online forms)**
Edit `apply_all.py` → the `JOBS = [...]` list near the top and add the job's link (copy the format of the lines already there). Then:

```
python apply_all.py --auto
```
- Opens each job in a real Chrome browser.
- Pre-fills your details and attaches the right CV.
- **Without a CAPTCHA:** clicks Submit automatically.
- **With a CAPTCHA (or missing button):** pauses for you to solve and finish manually.
- While it's running: `Enter` refills the form, `n` moves to the next job, `q` quits.

Prefers single-job style instead? Run `prefill_top_jobs.bat` and pick a number — browser opens, form pre-fills, **you submit with your own hands**.

After applying, mark the row:
```
Status      = APPLIED
Date Applied= today (YYYY-MM-DD)
Next Follow-up = today + 5 days  (example: 2026-09-17)
Apply Method = the URL or "Email: <address>"
```

### STEP 5 — Follow up (the part most people skip, and it works)

Open `applications.csv`, sort by *Next Follow-up*. Tomorrow's? Follow up:
- Email route → polite reply to the same thread: *"Just checking in on my application from [date]. I remain available for an interview at your convenience."*
- Portal route → re-open the link, look for a contact, or apply again after 1–2 weeks if it's still open.

When a job is dead, mark it **WATCHLIST** (keeping an eye out for a similar one) or delete the row.

---

## 4. QUICK REFERENCE (COPY-PASTE)

```
python job_scraper.py                    # FULL SCAN
python import_scanned_jobs.py            # MERGE NEW JOBS INTO TRACKER

python career_crawler.py                 # WORLDWIDE CAREER PAGES (optional)
python career_crawler.py --max 25        # crawl more companies
python career_crawler.py --company "Innov8 Hub"   # one company by name
python career_crawler.py --company "https://boards.greenhouse.io/greenhouse"

python extract_email_targets.py          # PREPARE EMAIL APPLICATIONS
python send_applications.py              # PREVIEW WHAT WOULD SEND
python send_applications.py --send --limit 3
python send_applications.py --send

python apply_all.py --auto               # PORTAL APPLICATIONS (browser)
```

---

## 5. ONE-TIME SETUP (only check if something misbehaves)

1. **Python + libraries** — needs `requests`, `beautifulsoup4`, `lxml`, `playwright`, `json`, etc. One-time:
   ```
   pip install requests beautifulsoup4 lxml playwright
   playwright install chromium
   ```
2. **Gmail app password** — for email sending. Already done if `sender_config.env` exists. To redo: Google Account → Security → App passwords → create for Mail → put the 16-character code into `sender_config.env` as `HOPE_GMAIL_APP_PASS=...`.
3. **Sender config** — `sender_config.env` should have your Gmail address + app password. If missing, `send_applications.py` will tell you.
4. **CVs** — `cv_pdfs\` must contain `Hope_John_Sunday_CV_IT_Support.pdf`, `Hope_John_Sunday_CV_Developer.pdf`, `Hope_John_Sunday_CV_Cloud_AWS.pdf` (already there).

---

## 6. SAFETY RULES (important)

1. **Nothing sends automatically.** Emails need `--send`. Portals send only with `--auto` and your presence. A CAPTCHA always stops the bot and hands control to you.
2. **Recruiters will never ask you to pay to apply.** Any job asking for money to "register", "fast-track", or a "processing fee" is a scam — mark it WATCHLIST and ignore.
3. **Careful with these portal sites — they may be junk/scam pages:** `66ghz.com`, `totalh.net`, `10001mb.com`, `hirenixa`, `hiring.camp`. If one of your matches links there, double-check the company exists before entering your real details.
4. **`sender_config.env` is a secret.** Never send it, paste it, or upload it anywhere. If it ever leaks, regenerate the app password immediately.
5. **Watch your sending rate.** Email servers block senders who blast 50 identical emails. Use `--limit 5` at a time and space the batches out — your tracker prevents duplicates anyway.

---

## 7. TRACKER STATUSES

| Status | Meaning |
|--------|---------|
| **TO_APPLY** | Found and matches you — but nobody has applied yet. |
| **EMAILED** | Email application sent. Follow up after ~5 days. |
| **APPLIED** | Applied via website/portal. Follow up after ~5 days. |
| **WATCHLIST** | Not a fit / sketchy / dead — but keep an eye out for similar roles. |
| *(blank / removed)* | Skipped or done. |

**Standard rhythm:** Scan daily → apply to the top 5–10 → follow up every job older than 5 days → repeat.

---

## 8. PHONE ACCESS (WEB CONTROL PANEL)

You can control most of the system from your phone without touching the laptop — as long as the laptop is on and running the web app.

### Start it (laptop)
Double-click **`start_web_app.bat`**. A window shows the addresses — keep that window open:
```
On this laptop:   http://127.0.0.1:5000
On your phone:    http://192.168.110.203:5000
```

### Open on your phone
1. Make sure the phone is on the **same Wi-Fi** as the laptop.
2. On the phone's browser, type the laptop address shown (e.g. `http://192.168.110.203:5000`).
3. First time: Windows may ask to **allow Python through the firewall** → tick "Private networks" and Allow. Ask Windows to allow Python if you get "can't connect".

### What you can do from the phone
- **New / Jobs tabs** — see freshly scanned jobs, search, open any application link directly.
- **Tracker tab** — every tracked job with a status dropdown (TO_APPLY / EMAILED / APPLIED / WATCHLIST). Change a status and it saves instantly + auto-sets the 5-day follow-up when you mark APPLIED.
- Bottom buttons: **Scan** (run the scanner now), **Crawl** (worldwide career pages), **Import** (add new jobs to the tracker).
- **Emails tab** — one-tap prepare ("Scan TO_APPLY jobs for emails"), preview dry-run, then send with your **Send PIN** (shows in the web-app window the first time it runs; also in `web_pin.env`).
- Everything runs **on the laptop** — the phone is only a remote control, so your Gmail password and CVs never leave home.

### What you still need the laptop for
- **Portal form-filling** (`apply_all.py`, `prefill_top_jobs.bat`) — it opens a real browser, so it needs the laptop screen.
- If the laptop is asleep/off, nothing runs.

### For access from ANYWHERE (optional, later)
Once you're happy with the local version, install **Cloudflare Tunnel** (free) and point it at port 5000. You'd then open the app from anywhere with an internet connection, same look, data still on the laptop. Ask to set this up when you're ready.