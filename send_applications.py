"""
Auto-send tailored applications by email.

Supports two providers:
1. Gmail SMTP (legacy) - via sender_config.env
2. Resend API (production) - via RESEND_API_KEY env var

SETUP - Gmail SMTP:
  1. Create Google App Password: https://myaccount.google.com/apppasswords
  2. Create sender_config.env:
       HOPE_GMAIL_USER=your@gmail.com
       HOPE_GMAIL_APP_PASS=16-char-app-password

SETUP - Resend (recommended for production):
  1. Sign up at https://resend.com
  2. Verify your domain (add DNS records)
  3. Create API key
  4. Set env vars:
       RESEND_API_KEY=re_xxx
       RESEND_FROM_EMAIL=jobs@yourdomain.com
       RESEND_FROM_NAME=JobMatch

SAFETY:
  - Defaults to DRY-RUN: only prints what WOULD be sent.
  - Pass --send to actually send.
  - Only email-based applications (from EMAIL_MAP + extract_email_targets.py) are processed.
"""
import csv
import json
import os
import smtplib
import sys
from datetime import date
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False

BASE = os.path.dirname(os.path.abspath(__file__))
CVS = os.path.join(BASE, 'cv_pdfs')
LETTERS = os.path.join(BASE, 'cover_letters')
CSV_PATH = os.path.join(BASE, 'applications.csv')
CONFIG_PATH = os.path.join(BASE, 'sender_config.env')

# --- Provider Detection ---
def detect_provider():
    """Returns 'resend' if configured, else 'gmail' if configured, else None."""
    if os.environ.get('RESEND_API_KEY') and RESEND_AVAILABLE:
        return 'resend'
    cfg = load_config()
    if cfg.get('HOPE_GMAIL_USER') and cfg.get('HOPE_GMAIL_APP_PASS'):
        return 'gmail'
    return None

# --- Resend Sender ---
def send_via_resend(api_key: str, from_email: str, from_name: str, to: str, subject: str, body: str, cv_path: str, cv_name: str):
    """Send email via Resend API with PDF attachment."""
    resend.api_key = api_key
    
    with open(cv_path, 'rb') as f:
        cv_data = f.read()
    
    import base64
    cv_b64 = base64.b64encode(cv_data).decode('utf-8')
    
    params = {
        "from": f"{from_name} <{from_email}>",
        "to": [to],
        "subject": subject,
        "text": body,
        "attachments": [{
            "filename": cv_name.replace(' ', '_'),
            "content": cv_b64,
        }]
    }
    return resend.Emails.send(params)

# --- Gmail SMTP Sender ---
def send_via_gmail(smtp, msg):
    smtp.send_message(msg)

# --- Config ---
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    return cfg

# --- Email Targets ---
EMAIL_MAP = [
    {'company_kw': 'Mar and Mor', 'to': 'recruitment@marandmor.com', 'greeting': 'Dear Hiring Team,', 'subject': 'IT Support Officer - Hope John Sunday', 'letter': '04_Concept_Group_IT_Support_Lagos.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf', 'apply_method': 'Email: recruitment@marandmor.com'},
    {'company_kw': 'Felton Energy', 'to': 'wendy@feltonenergy.net', 'greeting': 'Dear Hiring Team,', 'subject': 'IT Professional - Port Harcourt', 'letter': '01_Norrenberger_IT_Support_Officer_PH.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf', 'apply_method': 'Email: wendy@feltonenergy.net'},
    {'company_kw': 'Concept Group', 'to': 'mary.taiwo@conceptgroup-ng.com', 'greeting': 'Dear Mary,', 'subject': 'IT Support Engineer - Hope John Sunday', 'letter': '04_Concept_Group_IT_Support_Lagos.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf', 'apply_method': 'Email: mary.taiwo@conceptgroup-ng.com'},
    {'company_kw': 'Mega Lifesciences', 'to': 'timothy@megawecare.com', 'greeting': 'Dear Timothy,', 'subject': 'Application for IT Support Specialist - Hope John Sunday', 'letter': '05_Mega_Lifesciences_IT_Support_Lagos.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf', 'apply_method': 'Email: timothy@megawecare.com'},
    {'company_kw': 'Junbrain', 'to': 'info@junbrain.com', 'greeting': 'Dear Junbrain Recruitment Team,', 'subject': 'Application: Junior IT Support Specialist - Hope John Sunday', 'letter': '07_Junbrain_Junior_IT_Support_Remote.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf', 'apply_method': 'Email/portal', 'job_titles': ['it support']},
    {'company_kw': 'Junbrain', 'to': 'info@junbrain.com', 'greeting': 'Dear Junbrain Recruitment Team,', 'subject': 'Application: Junior Python Developer - Hope John Sunday', 'letter': '07_Junbrain_Junior_IT_Support_Remote.txt', 'cv': 'cv_pdfs/Hope_John_Sunday_CV_Developer.pdf', 'apply_method': 'Email/portal', 'job_titles': ['python developer']},
]

def load_email_targets():
    path = os.path.join(BASE, 'data', 'email_targets.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)

for _t in load_email_targets():
    if not _t.get('emails'):
        continue
    EMAIL_MAP.append({
        'company_kw': _t['company'],
        'to': _t['emails'][0],
        'greeting': 'Dear Hiring Team,',
        'subject': f"Application for {_t['title']} - Hope John Sunday",
        'letter': _t['letter'],
        'cv': _t['cv'],
        'apply_method': _t['apply_method'],
        'job_titles': [_t['title'].lower()],
    })

def read_csv_rows():
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def write_csv_rows(rows):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def build_emails(rows, cfg):
    emails = []
    for row in rows:
        if (row.get('Status') or '').strip().upper() == 'EMAILED':
            continue
        job_title = (row.get('Job Title') or '').lower()
        company = (row.get('Company') or '').lower()
        for entry in EMAIL_MAP:
            if entry['company_kw'].lower() not in company:
                continue
            if entry.get('job_titles') and not any(t.lower() in job_title for t in entry['job_titles']):
                continue
            letter_path = os.path.join(LETTERS, entry['letter'])
            cv_path = os.path.join(BASE, entry['cv'].replace('cv_pdfs/', 'cv_pdfs/'))
            with open(letter_path, encoding='utf-8-sig') as f:
                body = f.read().strip()
            header = (f"{entry['greeting']}\n\n"
                      f"Please find attached my CV and cover letter regarding the following opening.\n\n")
            footer = ("\n\n"
                      "Sincerely,\n"
                      "Hope John Sunday\n"
                      "+234 813 834 9412 | hopejohn204@gmail.com\n"
                      "LinkedIn: linkedin.com/in/hope-sunday-3170a7403 | GitHub: github.com/Hopejohn2004")
            emails.append({
                'row': row,
                'to': entry['to'],
                'subject': entry['subject'],
                'body': header + body + footer,
                'cv_path': cv_path,
                'cv_name': os.path.basename(cv_path),
                'letter_name': entry['letter'],
                'apply_method': entry['apply_method'],
            })
    return emails

# --- Main ---
def main():
    do_send = '--send' in sys.argv
    limit = None
    if '--limit' in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index('--limit') + 1])
        except (ValueError, IndexError):
            limit = None

    provider = detect_provider()
    if not provider:
        print('[CONFIG MISSING] No email provider configured.')
        print('Option 1 - Gmail SMTP: Create sender_config.env with HOPE_GMAIL_USER and HOPE_GMAIL_APP_PASS')
        print('Option 2 - Resend (recommended): Set RESEND_API_KEY and RESEND_FROM_EMAIL env vars')
        sys.exit(1)

    print(f'[INFO] Using email provider: {provider}')

    if provider == 'resend':
        api_key = os.environ.get('RESEND_API_KEY')
        from_email = os.environ.get('RESEND_FROM_EMAIL', 'jobs@yourdomain.com')
        from_name = os.environ.get('RESEND_FROM_NAME', 'JobMatch')
        if not api_key:
            print('[ERROR] RESEND_API_KEY not set')
            sys.exit(1)
    else:
        cfg = load_config()
        user = cfg.get('HOPE_GMAIL_USER')
        app_pass = cfg.get('HOPE_GMAIL_APP_PASS')
        if not user or not app_pass:
            print('[ERROR] Gmail credentials missing in sender_config.env')
            sys.exit(1)

    rows = read_csv_rows()
    emails = build_emails(rows, cfg if provider == 'gmail' else {})
    if limit and limit > 0:
        emails = emails[:limit]

    if not emails:
        print('No email-based applications found. Nothing to do.')
        return

    print('=' * 70)
    print(f"DRY RUN: {len(emails)} application(s) WILL be sent" if not do_send else f"SENDING {len(emails)} application(s) via {provider.upper()}...")
    print('=' * 70)

    smtp = None
    if do_send and provider == 'gmail':
        smtp = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=60)
        smtp.login(user, app_pass)

    sent = []
    try:
        for e in emails:
            if provider == 'resend':
                if do_send:
                    try:
                        result = send_via_resend(
                            api_key=api_key,
                            from_email=from_email,
                            from_name=from_name,
                            to=e['to'],
                            subject=e['subject'],
                            body=e['body'],
                            cv_path=e['cv_path'],
                            cv_name=e['cv_name']
                        )
                        print(f'[SENT]  -> {e["to"]} | {e["subject"]} (id: {result.get("id")})')
                    except Exception as ex:
                        print(f'[FAILED] -> {e["to"]} | {e["subject"]}: {ex}')
                        continue
                else:
                    print(f'[PLAN]  -> {e["to"]} | {e["subject"]}')
                    print(f'        letter: {e["letter_name"]}')
                    print(f'        cv: {e["cv_name"]}')
                    print(f'        body: {e["body"][:42].replace(chr(10), " ")}...')
            else:
                msg = MIMEMultipart()
                msg['From'] = user
                msg['To'] = e['to']
                msg['Subject'] = e['subject']
                msg.attach(MIMEText(e['body'], 'plain', 'utf-8'))
                with open(e['cv_path'], 'rb') as f:
                    part = MIMEApplication(f.read(), _subtype='pdf')
                    part.add_header('Content-Disposition', 'attachment',
                                    filename=os.path.basename(e['cv_path']).replace(' ', '_'))
                    msg.attach(part)

                if do_send:
                    send_via_gmail(smtp, msg)
                    print('[SENT]  ->', e['to'], '|', e['subject'])
                else:
                    print('[PLAN]  ->', e['to'], '|', e['subject'])
                    print('        letter:', e['letter_name'])
                    print('        cv:', e['cv_name'])
                    print('        body:', e['body'][:42].replace('\n', ' ') + '...')

            if do_send:
                e['row']['Status'] = 'EMAILED'
                e['row']['Date Applied'] = date.today().isoformat()
                sent.append(e['row'])

    finally:
        if smtp:
            smtp.quit()

    if do_send:
        write_csv_rows(rows)
        print(f'\nDone. {len(sent)} application(s) sent via {provider.upper()}. applications.csv updated (Status=EMAILED).')
    else:
        print(f'\nDry run complete. Run with --send to actually send via {provider.upper()}.')

if __name__ == '__main__':
    main()