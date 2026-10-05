"""
Extract email-based application targets from today's scanned jobs.

For every TO_APPLY row in applications.csv whose job board page exposes a
recruiter email ("send your CV to hr@..."), this:
  1. Fetches the job page and extracts the email address(es).
  2. Picks the right CV (IT Support / Cloud-AWS / Developer).
  3. Generates a tailored cover letter in cover_letters/generated/.
  4. Writes email_targets.json, which send_applications.py auto-loads.

Usage:  python extract_email_targets.py
Re-run it after each scan - rows already EMAILED/APPLIED are skipped.
"""
import csv
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / 'applications.csv'
OUT_JSON = BASE / 'data' / 'email_targets.json'
LETTERS_DIR = BASE / 'cover_letters' / 'generated'
USER_AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')

DEVELOPER_CV = 'cv_pdfs/Hope_John_Sunday_CV_Developer.pdf'
CLOUD_CV = 'cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf'
IT_CV = 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf'

LETTER_TEMPLATE_IT = """Dear Hiring Team,

I am writing to express my strong interest in the {role} position at {company}. As a Computer Science graduate from the University of Uyo with hands-on IT support experience and active pursuit of the AWS Cloud Practitioner and Google IT Support Professional certifications, I am excited to bring my technical skills and customer-focused approach to your team.

My background includes providing direct technical support to end users, diagnosing hardware and software issues, troubleshooting network connectivity problems, and maintaining Windows and Linux operating systems. I have hands-on experience with TCP/IP, DNS, DHCP, Wi-Fi troubleshooting, and Active Directory user account management, and I am proficient with Microsoft 365 and Google Workspace.

I am passionate about ensuring that IT infrastructure operates smoothly and reliably. My approach combines strong technical problem-solving with clear communication, ensuring issues are resolved efficiently and documented properly. I am available immediately for an interview at your convenience.

Thank you for considering my application.

Sincerely,
Hope John Sunday
+234 813 834 9412 | hopejohn204@gmail.com
"""

LETTER_TEMPLATE_DEV = """Dear Hiring Team,

I am writing to express my strong interest in the {role} position at {company}. As a Computer Science graduate from the University of Uyo with practical software development experience and active pursuit of cloud certifications, I am excited to bring my technical skills and fast, AI-leveraged development workflow to your team.

My background includes developing and maintaining web applications in Python, building REST APIs with Flask, and writing clean, well-tested code. I have hands-on experience with HTML/CSS/JavaScript, relational databases, and Linux environments, alongside version control (Git), debugging, and deployment fundamentals.

I am passionate about shipping reliable software and learning quickly. My approach combines strong problem-solving with clear communication, ensuring deliverables are built efficiently and documented properly. I am available immediately for an interview at your convenience.

Thank you for considering my application.

Sincerely,
Hope John Sunday
+234 813 834 9412 | hopejohn204@gmail.com
"""

DEV_KEYWORDS = ['developer', 'python', 'full-stack', 'full stack', 'backend', 'frontend',
                'software engineer', 'java', 'erp']
CLOUD_KEYWORDS = ['cloud', 'aws', 'devops']


def pick_cv(title):
    t = title.lower()
    if any(k in t for k in DEV_KEYWORDS):
        return DEVELOPER_CV
    if any(k in t for k in CLOUD_KEYWORDS):
        return CLOUD_CV
    return IT_CV


def build_letter(role, company, cv):
    template = LETTER_TEMPLATE_DEV if DEVELOPER_CV in cv else LETTER_TEMPLATE_IT
    return template.format(role=role, company=company or 'your organisation')


def clean_emails(page_text):
    emails = set(re.findall(EMAIL_RE, page_text))
    out = set()
    for e in emails:
        low = e.lower()
        if 'myjobmag' in low or 'example' in low or 'sentry' in low:
            continue
        if low.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
            continue
        out.add(e)
    return sorted(out)


def main():
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))

    targets = []
    count_rows = 0
    for row in rows:
        status = (row.get('Status') or '').strip().upper()
        link = (row.get('Apply Link') or '').strip()
        if status != 'TO_APPLY' or not link.startswith('http'):
            continue
        count_rows += 1
        title = (row.get('Job Title') or '').strip()
        company = (row.get('Company') or '').strip()
        app_id = row['Application ID']

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
            print(f"  [{app_id}] {title[:45]:<48} no email (portal/webform)")
            continue

        cv = pick_cv(title)
        LETTERS_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')
        letter_name = f"{app_id}_{slug[:24] or 'company'}.txt"
        letter_path = LETTERS_DIR / letter_name
        letter_path.write_text(build_letter(title, company, cv), encoding='utf-8')
        targets.append({
            'app_id': app_id,
            'title': title,
            'company': company,
            'location': row.get('Location') or 'Nigeria',
            'source': row.get('Source') or '',
            'link': link,
            'emails': emails,
            'cv': cv,
            'letter': f'generated/{letter_name}',
            'apply_method': f"Email: {emails[0]}",
        })
        print(f"  [{app_id}] {title[:45]:<48} {emails}")

    OUT_JSON.write_text(json.dumps(targets, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\nChecked {count_rows} TO_APPLY row(s) -> {len(targets)} email target(s).")
    print(f"Saved: {OUT_JSON}")
    if targets:
        print("Next: run  python send_applications.py  to dry-run, add --send to send.")


if __name__ == '__main__':
    main()
