"""
Merge the latest scanned_jobs.json into applications.csv as new TO_APPLY rows.

Idempotent: rows already present (same role+company OR same apply link) are skipped,
so it is safe to run after every daily scan.

Usage:  python import_scanned_jobs.py
"""
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCAN = BASE / 'data' / 'scanned_jobs.json'
CSV_PATH = BASE / 'applications.csv'
FIELDS = ['Application ID', 'Date Applied', 'Job Title', 'Company', 'Location',
          'Source', 'Apply Link', 'Apply Method', 'Status', 'Next Follow-up', 'Notes']

CATEGORY_ORDER = ['nigerian_onsite', 'remote_global', 'other_matches']


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def strip_company(title, company):
    if not company:
        return title
    pat = re.compile(r'\s+at\s+' + re.escape(company.strip()) + r'[\s,.\-]*$', re.IGNORECASE)
    cleaned = pat.sub('', title.strip())
    return cleaned or title.strip()


def load_rows():
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    with open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if not SCAN.exists():
        print(f'[ERROR] no scan file: {SCAN}')
        sys.exit(1)
    with open(SCAN, encoding='utf-8') as f:
        data = json.load(f)

    jobs = []
    for cat in CATEGORY_ORDER:
        jobs.extend(data.get('jobs', {}).get(cat, []))
    scan_date = data.get('scan_date', '')[:10]

    rows = load_rows()
    if not rows:
        print('[ERROR] applications.csv has no rows')
        sys.exit(1)

    known_role = {(norm(r['Job Title']), norm(r['Company'])) for r in rows}
    known_link = {norm(r['Apply Link']) for r in rows}

    new_rows = []
    skipped = 0
    next_id = max(int(r['Application ID']) for r in rows) + 1
    follow = (date.today() + timedelta(days=5)).isoformat()

    for j in jobs:
        title = strip_company(j['title'], j.get('company', ''))
        company = j.get('company', '') or ''
        link = j.get('link', '') or ''
        key = (norm(title), norm(company))
        link_key = norm(link)
        if key in known_role or (link_key and link_key in known_link):
            skipped += 1
            continue
        known_role.add(key)
        if link_key:
            known_link.add(link_key)
        new_rows.append({
            'Application ID': str(next_id),
            'Date Applied': scan_date or date.today().isoformat(),
            'Job Title': title,
            'Company': company,
            'Location': j.get('location', '') or 'Nigeria',
            'Source': j.get('source', ''),
            'Apply Link': link,
            'Apply Method': 'Online portal',
            'Status': 'TO_APPLY',
            'Next Follow-up': follow,
            'Notes': f"Score {j.get('score', 0)} - from daily scan",
        })
        next_id += 1

    if not new_rows:
        print(f'No new jobs to import ({skipped} already tracked).')
        return

    write_rows(rows + new_rows)
    print(f'Imported {len(new_rows)} new job(s) as TO_APPLY (skipped {skipped} already present).')
    print(f'  Scan date:  {scan_date}')
    print(f'  Follow-up:  {follow}')
    for nr in new_rows[:10]:
        print(f'  [{nr["Application ID"]}] {nr["Job Title"]} | {nr["Company"]} | {nr["Location"]}')
    if len(new_rows) > 10:
        print(f'  ... and {len(new_rows) - 10} more.')


if __name__ == '__main__':
    main()
