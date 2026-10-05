"""
Polite follow-up for applications already emailed by Hope John Sunday.

Since email addresses were not persisted in applications.csv, this re-fetches
each EMAILED job posting, recovers the recruiter email, and drafts a short,
professional follow-up (respectful nudge + re-attached CV).

Flow:
  1. Read applications.csv, take rows with Status = EMAILED.
  2. Re-fetch each posting page and recover the email address(es).
  3. Pick the matching CV (IT Support / Cloud-AWS / Developer).
  4. Write a follow-up letter to cover_letters/followups/ and a target list
     to data/followup_targets.json (dry-run: nothing sent, you can review).
  5. With --send (and optional --limit N for batching): actually send.

Usage:
  python send_followups.py              # re-extract targets + draft letters (safe)
  python send_followups.py --send --limit 8      # send in small batches
"""
import csv
import json
import os
import re
import smtplib
import sys
from datetime import date, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / 'applications.csv'
CONFIG_PATH = BASE / 'sender_config.env'
LETTERS_DIR = BASE / 'cover_letters' / 'followups'
OUT_JSON = BASE / 'data' / 'followup_targets.json'
USER_AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')

DEVELOPER_CV = 'cv_pdfs/Hope_John_Sunday_CV_Developer.pdf'
CLOUD_CV = 'cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf'
IT_CV = 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf'

DEV_KEYWORDS = ['developer', 'python', 'full-stack', 'full stack', 'backend', 'frontend',
                'software engineer', 'java', 'erp']
CLOUD_KEYWORDS = ['cloud', 'aws', 'devops']

FOLLOWUP_TEMPLATE = """Dear Hiring Team,

I am following up on my application for the {role} position at {company}, which I submitted last week.

Should my qualifications match what you are currently looking for, I would be glad to make myself available for an interview at your convenience. My CV is attached again for your quick reference, and I remain genuinely interested in contributing to your team.

Thank you for your time and consideration.

Sincerely,
Hope John Sunday
+234 813 834 9412 | hopejohn204@gmail.com
LinkedIn: linkedin.com/in/hope-sunday-3170a7403 | GitHub: github.com/Hopejohn2004
"""


def pick_cv(title):
    t = (title or '').lower()
    if any(k in t for k in DEV_KEYWORDS):
        return DEVELOPER_CV
    if any(k in t for k in CLOUD_KEYWORDS):
        return CLOUD_CV
    return IT_CV


def clean_emails(page_text):
    emails = set(re.findall(EMAIL_RE, page_text))
    out = set()
    for e in emails:
        low = e.lower()
        if 'myjobmag' in low or 'jobberman' in low or 'example' in low or 'sentry' in low:
            continue
        if low.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
            continue
        out.add(e)
    return sorted(out)


def load_config():
    cfg = {}
    if CONFIG_PATH.exists():
        for line in CONFIG_PATH.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip()
    return cfg


def read_csv_rows():
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv_rows(rows):
    if not rows:
        return
    with open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def extract_targets(rows):
    targets = []
    checked = 0
    for row in rows:
        status = (row.get('Status') or '').strip().upper()
        link = (row.get('Apply Link') or '').strip()
        if status != 'EMAILED':
            continue
        due = (row.get('Next Follow-up') or '').strip()
        if due and due > date.today().isoformat():
            continue
        app_id = row['Application ID']
        title = (row.get('Job Title') or '').strip()
        company = (row.get('Company') or '').strip()

        # Fallback: some manual applications only have the address in Apply Method.
        if not link.startswith('http'):
            method = (row.get('Apply Method') or '')
            if 'Email:' not in method:
                continue
            emails = clean_emails(method)
            if not emails:
                continue
            cv = pick_cv(title)
            LETTERS_DIR.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')
            letter_name = f"{app_id}_{slug[:24] or 'company'}.txt"
            letter_path = LETTERS_DIR / letter_name
            letter_path.write_text(FOLLOWUP_TEMPLATE.format(role=title, company=company or 'your organisation'),
                                   encoding='utf-8')
            targets.append({
                'app_id': app_id,
                'title': title,
                'company': company,
                'location': row.get('Location') or '',
                'link': link,
                'emails': emails,
                'cv': cv,
                'letter': f'followups/{letter_name}',
                'subject': f"Re: Application for {title} - Hope John Sunday",
            })
            print(f"  [{app_id}] {title[:45]:<48} {emails} (from Apply Method)")
            checked += 1
            continue

        checked += 1
        try:
            resp = requests.get(link, headers=USER_AGENT, timeout=20)
            if resp.status_code != 200:
                print(f"  [{app_id}] {title[:45]:<48} HTTP {resp.status_code} (skip)")
                continue
            soup = BeautifulSoup(resp.text, 'lxml')
            emails = clean_emails(soup.get_text(' ', strip=True))
        except Exception as e:
            print(f"  [{app_id}] {title[:45]:<48} ERROR {e}")
            continue
        if not emails:
            print(f"  [{app_id}] {title[:45]:<48} no email (skip)")
            continue

        cv = pick_cv(title)
        LETTERS_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')
        letter_name = f"{app_id}_{slug[:24] or 'company'}.txt"
        letter_path = LETTERS_DIR / letter_name
        letter_path.write_text(FOLLOWUP_TEMPLATE.format(role=title, company=company or 'your organisation'),
                               encoding='utf-8')
        targets.append({
            'app_id': app_id,
            'title': title,
            'company': company,
            'location': row.get('Location') or '',
            'link': link,
            'emails': emails,
            'cv': cv,
            'letter': f'followups/{letter_name}',
            'subject': f"Re: Application for {title} - Hope John Sunday",
        })
        print(f"  [{app_id}] {title[:45]:<48} {emails}")

    OUT_JSON.write_text(json.dumps(targets, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\nChecked {checked} EMAILED row(s) -> {len(targets)} follow-up target(s).")
    print(f"Saved: {OUT_JSON}")
    return targets


def main():
    do_send = '--send' in sys.argv
    limit = None
    if '--limit' in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index('--limit') + 1])
        except (ValueError, IndexError):
            limit = None

    cfg = load_config()
    user = cfg.get('HOPE_GMAIL_USER')
    app_pass = cfg.get('HOPE_GMAIL_APP_PASS')
    if not user or not app_pass:
        print('[CONFIG MISSING] sender_config.env not found or incomplete (see send_applications.py header).')
        sys.exit(1)

    rows = read_csv_rows()
    print('Recovering email targets for EMAILED applications...')
    targets = extract_targets(rows)
    if limit and limit > 0:
        targets = targets[:limit]
        print(f'(batch limited to {limit})')

    if not targets:
        print('No follow-up targets. Nothing to do.')
        return

    print('=' * 70)
    print(f"DRY RUN: {len(targets)} follow-up(s) WOULD be sent" if not do_send else
          f"SENDING {len(targets)} follow-up(s)...")
    print('=' * 70)

    smtp = None
    if do_send:
        smtp = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=60)
        smtp.login(user, app_pass)

    today = date.today()
    sent = 0
    try:
        for t in targets:
            letter_path = LETTERS_DIR / t['letter'].rsplit('/', 1)[-1]
            body = letter_path.read_text(encoding='utf-8').strip()
            cv_path = BASE / t['cv']
            msg = MIMEMultipart()
            msg['From'] = user
            msg['To'] = t['emails'][0]
            msg['Subject'] = t['subject']
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            if cv_path.exists():
                with open(cv_path, 'rb') as f:
                    part = MIMEApplication(f.read(), _subtype='pdf')
                    part.add_header('Content-Disposition', 'attachment',
                                    filename=os.path.basename(cv_path).replace(' ', '_'))
                    msg.attach(part)

            if do_send:
                smtp.send_message(msg)
                for row in rows:
                    if row['Application ID'] == t['app_id']:
                        row['Notes'] = ((row.get('Notes') or '') + f" | Follow-up sent {today.isoformat()}").strip()
                        row['Next Follow-up'] = (today + timedelta(days=8)).isoformat()
                        break
                sent += 1
                print('[SENT]  ->', t['emails'][0], '|', t['subject'][:60])
            else:
                print('[PLAN]  ->', t['emails'][0], '|', t['subject'][:60])
                print('        letter:', t['letter'])
                if cv_path.exists():
                    print('        cv:', os.path.basename(cv_path))
    finally:
        if smtp:
            smtp.quit()

    if do_send:
        write_csv_rows(rows)
        print(f'\nDone. {sent} follow-up(s) sent. Tracker updated (Notes + Next Follow-up).')
    else:
        print('\nDry run complete. Review letters in cover_letters/followups/, then run with --send.')


if __name__ == '__main__':
    main()
