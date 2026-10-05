"""
career_crawler.py - Worldwide company career-page crawler.

Discovers companies from the scan data (scanned_jobs.json / new_jobs_alert.json),
detects the ATS powering each company's careers site (Greenhouse, Lever, Ashby,
Workable, SmartRecruiters), fetches real-time job listings from each, and keeps
only roles that fit the profile (or roles worth training into).

Supplemental: `--company "Acme"` probes any company's career page on demand.

Output: career_jobs.json  (merged into the main scanner via job_scraper.py)
"""
import argparse
import html as _html
import json
import os
import re
from datetime import datetime

import requests

from job_scraper import (
    TARGET_KEYWORDS,
    check_location_match,
    compute_score,
    is_noise,
    is_relevant,
)

HERE = os.path.dirname(os.path.abspath(__file__))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Job-listing portals. Their job pages are NOT company career pages - anchor-fallback
# scraping would just harvest the portal's own sidebar widgets and mislabel them.
AGGREGATOR_HOSTS = (
    'myjobmag.com', 'hotnigerianjobs.com', 'jobberman.com',
    'remoteok.com', 'arbeitnow.com', 'remotive.com',
    'workingnomads.com', 'news.ycombinator.com', 'hn.algolia.com',
    'indeed.com', 'linkedin.com', 'glassdoor.com', 'careerjet.com', 'totalh.net',
    'wellfound.com', 'otta.com', 'workew.com', 'remotehub.io',
    'workatastartup.com', 'jobspresso.co', 'jobgether.com',
    'virtualclickjobs.com', 'himalayas.app', 'brightermonday.co.ke',
    'brightermonday.co.ug', 'brightermonday.co.tz', 'jora.com',
    'za.jora.com', 'careerjet.com',
)


def host_of(url):
    try:
        from urllib.parse import urlparse
        return (urlparse(url).netloc or '').lower()
    except Exception:
        return ''


def is_aggregator(url):
    host = host_of(url)
    return any(host == h or host.endswith('.' + h) for h in AGGREGATOR_HOSTS)


def clean(html_text):
    text = re.sub(r'<[^>]+>', ' ', html_text or '')
    return re.sub(r'\s+', ' ', _html.unescape(text)).strip()


def make_job(source, company, title, location, description, link, score_bonus=0):
    if is_noise(title, description):
        return None
    if not is_relevant(title, description, TARGET_KEYWORDS):
        return None
    loc = (location or '').strip()
    if not loc:
        loc = 'Remote' if 'remote' in (description or '').lower() else 'Worldwide'
    return {
        'source': source,
        'company': company,
        'title': title,
        'location': loc[:120],
        'description': description[:500],
        'link': link,
        'score': compute_score(title, description) + score_bonus,
        'location_match': check_location_match(loc),
    }


def detect_ats(url):
    low = (url or '').lower()
    m = re.search(r'boards(-api)?\.greenhouse\.io/v1/boards/([a-z0-9\-]+)', low)
    if m:
        return 'greenhouse', m.group(2)
    m = re.search(r'boards\.greenhouse\.io/([a-z0-9\-]+)', low)
    if m:
        return 'greenhouse', m.group(1)
    m = re.search(r'jobs\.lever\.co/([a-z0-9\-]+)', low)
    if m:
        return 'lever', m.group(1)
    m = re.search(r'(api\.ashbyhq\.com/posting-api/job-board|jobs\.ashbyhq\.com)/([a-z0-9.\-]+)', low)
    if m:
        return 'ashby', m.group(2)
    m = re.search(r'apply\.workable\.com/([a-z0-9\-]+)', low)
    if m:
        return 'workable', m.group(1)
    m = re.search(r'careers\.smartrecruiters\.com/([a-zA-Z0-9\-]+)', low)
    if m:
        return 'smart', m.group(1)
    m = re.search(r'(api\.teamtailor\.com|careers\.teamtailor\.com)/([a-z0-9\-]+)', low)
    if m:
        return 'teamtailor', m.group(2)
    m = re.search(r'(api\.breezy\.hr|breezy\.hr)/([a-z0-9\-]+)', low)
    if m:
        return 'breezy', m.group(2)
    m = re.search(r'(api\.recruitee\.com|recruitee\.com)/([a-z0-9\-]+)', low)
    if m:
        return 'recruitee', m.group(2)
    m = re.search(r'(api\.comeet\.com|comeet\.com)/([a-z0-9\-]+)', low)
    if m:
        return 'comeet', m.group(2)
    m = re.search(r'(api\.personio\.com|personio\.com)/([a-z0-9\-]+)', low)
    if m:
        return 'personio', m.group(2)
    m = re.search(r'(api\.teamtailor\.com|teamtailor\.com)/([a-z0-9\-]+)', low)
    if m:
        return 'teamtailor', m.group(2)
    return None, None


# ================= ATS fetch functions =================

def fetch_greenhouse(slug, company=''):
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs', timeout=20)
        data = resp.json()
        if 'jobs' not in data:
            return jobs, data.get('error') or f'status {resp.status_code}'
        for j in data['jobs']:
            jobs.append(make_job(
                'careers/greenhouse', company or slug, j.get('title', ''),
                (j.get('location') or {}).get('name', ''),
                clean(j.get('content', '')),
                j.get('absolute_url') or f'https://boards.greenhouse.io/{slug}/jobs/{j.get("id")}',
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_lever(slug, company=''):
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.lever.co/v0/postings/{slug}?mode=json', timeout=20)
        data = resp.json()
        if not isinstance(data, list):
            return jobs, (data.get('error') if isinstance(data, dict) else 'bad shape')
        for j in data:
            jobs.append(make_job(
                'careers/lever', company or slug, j.get('text', ''),
                ((j.get('categories') or {}).get('location', '')) or 'Remote',
                j.get('descriptionPlain', ''),
                j.get('hostedUrl', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_ashby(slug, company=''):
    jobs, err = [], ''
    try:
        resp = requests.post(f'https://api.ashbyhq.com/posting-api/job-board/{slug}',
                             headers={**HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
                             data={}, timeout=20)
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(data.get('error') if isinstance(data, dict) else 'bad shape')
        for j in data:
            jobs.append(make_job(
                'careers/ashby', company or slug, j.get('title', ''),
                (j.get('location') or ''),
                j.get('descriptionPlain') or clean(j.get('descriptionMarkdown', '')),
                j.get('jobUrl', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
        # Fallback: parse the public board page. Ashby embeds a JSON blob
        # (window.__appData.jobBoard.jobPostings) inside its only <script> tag.
        try:
            html_text = requests.get(f'https://jobs.ashbyhq.com/{slug}', headers=HEADERS, timeout=8).text
            marker = 'window.__appData'
            idx = html_text.find(marker)
            if idx != -1:
                blob, _ = json.JSONDecoder().raw_decode(
                    html_text[idx + len(marker):].lstrip().lstrip('= ').lstrip())
                for p in (blob.get('jobBoard') or {}).get('jobPostings', []):
                    jobs.append(make_job(
                        'careers/ashby', company or slug, p.get('title', ''),
                        p.get('locationName', ''), '',
                        f'https://jobs.ashbyhq.com/{slug}/{p.get("id")}',
                        score_bonus=2,
                    ))
            # last resort: raw posting links in the page
            if not jobs:
                pattern = re.compile(r'href="(https://jobs\.ashbyhq\.com/' + re.escape(slug) + r'/([\w\-]+))"', re.I)
                seen = set()
                for link, pid in pattern.findall(html_text):
                    if pid in seen:
                        continue
                    seen.add(pid)
                    jobs.append(make_job('careers/ashby', company or slug, pid.replace('-', ' ').title(),
                                         '', '', link, score_bonus=2))
        except Exception:
            pass
    return [j for j in jobs if j], err


def fetch_workable(slug, company=''):
    jobs, err = [], ''
    for details in ('false', 'true'):
        try:
            url = f'https://apply.workable.com/api/v1/widget/accounts/{slug}?details={details}'
            data = requests.get(url, headers=HEADERS, timeout=20).json()
            board_name = data.get('name') or company or slug
            for j in data.get('jobs', []):
                loc_parts = [p for p in (j.get('city'), j.get('country')) if p]
                loc = ', '.join(loc_parts)
                if j.get('remote'):
                    loc = 'Remote' if not loc else f'Remote ({loc})'
                jobs.append(make_job(
                    'careers/workable', board_name, j.get('title', ''),
                    loc, j.get('description', '') or '',
                    j.get('url', ''),
                    score_bonus=2,
                ))
            if jobs:
                break
        except Exception as e:
            err = repr(e)
    return [j for j in jobs if j], err


def fetch_smart(slug, company=''):
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100',
                            headers=HEADERS, timeout=20)
        data = resp.json()
        for j in data.get('content', []):
            loc = j.get('location') or {}
            loc_text = ' '.join(x for x in (loc.get('city'), loc.get('country')) if x)
            if loc.get('remote'):
                loc_text = f'Remote ({loc_text.strip()})' if loc_text.strip() else 'Remote'
            desc = ' '.join((d.get('name') or '') for d in j.get('departments', []))
            jobs.append(make_job(
                'careers/smartrecruiters', company or slug,
                j.get('jobTitle') or j.get('name') or '',
                loc_text, desc or '',
                j.get('url') or f'https://careers.smartrecruiters.com/{slug}/{j.get("id")}',
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_teamtailor(slug, company=''):
    """Teamtailor ATS - public API for job listings."""
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.teamtailor.com/v1/jobs?filter[status]=published&filter[career_site_id]={slug}',
                            headers={**HEADERS, 'Accept': 'application/json'}, timeout=20)
        data = resp.json()
        for j in data.get('data', []):
            attrs = j.get('attributes', {})
            jobs.append(make_job(
                'careers/teamtailor', company or slug, attrs.get('title', ''),
                attrs.get('location', '') or 'Remote',
                clean(attrs.get('description', '')),
                attrs.get('url', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_breezy(slug, company=''):
    """Breezy HR ATS - public API."""
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.breezy.hr/v3/companies/{slug}/positions?state=published',
                            headers={**HEADERS, 'Accept': 'application/json'}, timeout=20)
        data = resp.json()
        for j in data.get('data', []):
            jobs.append(make_job(
                'careers/breezy', company or slug, j.get('title', ''),
                j.get('location', '') or 'Remote',
                clean(j.get('description', '')),
                j.get('url', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_recruitee(slug, company=''):
    """Recruitee ATS - public API."""
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.recruitee.com/c/{slug}/offers',
                            headers={**HEADERS, 'Accept': 'application/json'}, timeout=20)
        data = resp.json()
        for j in data.get('offers', []):
            jobs.append(make_job(
                'careers/recruitee', company or slug, j.get('title', ''),
                j.get('location', '') or 'Remote',
                clean(j.get('description', '')),
                j.get('career_url', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_comeet(slug, company=''):
    """Comeet ATS - public API."""
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.comeet.com/v1.0/jobs?company={slug}',
                            headers={**HEADERS, 'Accept': 'application/json'}, timeout=20)
        data = resp.json()
        for j in data.get('jobs', []):
            jobs.append(make_job(
                'careers/comeet', company or slug, j.get('name', ''),
                j.get('location', '') or 'Remote',
                clean(j.get('description', '')),
                j.get('url', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


def fetch_personio(slug, company=''):
    """Personio ATS - public XML feed."""
    jobs, err = [], ''
    try:
        resp = requests.get(f'https://api.personio.com/v1/companies/{slug}/jobs',
                            headers={**HEADERS, 'Accept': 'application/json'}, timeout=20)
        data = resp.json()
        for j in data.get('jobs', []):
            jobs.append(make_job(
                'careers/personio', company or slug, j.get('title', ''),
                j.get('office', '') or 'Remote',
                clean(j.get('description', '')),
                j.get('url', ''),
                score_bonus=2,
            ))
    except Exception as e:
        err = repr(e)
    return [j for j in jobs if j], err


ATS_FETCHERS = {
    'greenhouse': fetch_greenhouse,
    'lever': fetch_lever,
    'ashby': fetch_ashby,
    'workable': fetch_workable,
    'smart': fetch_smart,
    'teamtailor': fetch_teamtailor,
    'breezy': fetch_breezy,
    'recruitee': fetch_recruitee,
    'comeet': fetch_comeet,
    'personio': fetch_personio,
}


def probe_careers_page(url, company=''):
    """Fetch a company homepage/careers page and try to resolve its ATS, else parse job anchors."""
    candidates = [url]
    root = re.match(r'(https?://[^/]+)', url)
    if (root and re.sub(r'^https?://', '', url).count('/') <= 1
            and 'careers' not in url.lower() and 'jobs' not in url.lower()):
        # not a careers page yet - try the obvious careers URL too
        candidates.append(root.group(1) + '/careers')

    jobs, err, ats_used = [], '', None
    for page in candidates:
        try:
            html_text = requests.get(page, headers=HEADERS, timeout=5).text
        except Exception as e:
            err = repr(e)
            continue
        ats, slug = detect_ats(html_text)
        ats2, slug2 = detect_ats(page)
        if ats or ats2:
            fetcher_ats, fetcher_slug = (ats or ats2), (slug or slug2)
            jobs, err = ATS_FETCHERS[fetcher_ats](fetcher_slug, company)
            ats_used = f'{fetcher_ats}:{fetcher_slug}'
            return jobs, err, ats_used
        # Generic fallback: collect job anchors from HTML
        try:
            soup = __import__('bs4').BeautifulSoup(html_text, 'lxml')
            for a in soup.find_all('a', href=True):
                txt = clean(a.get_text())
                href = a['href']
                if not txt or len(txt) < 4 or not re.search(r'(job|position|role|career|open-role|vacanc|openings)', href + txt, re.I):
                    continue
                if href.startswith('/'):
                    href = page.rstrip('/') + '/' + href.lstrip('/')
                j = make_job('careers/page', company or url, txt, '', '', href, score_bonus=1)
                if j:
                    jobs.append(j)
                    if len(jobs) >= 10:
                        break
            if jobs:
                ats_used = 'anchors'
                return jobs, err, ats_used
        except Exception as e:
            err = repr(e)
    return jobs[:10], err, ats_used


# ================= Discovery =================

def harvest_targets():
    """Gather company targets from scan output.

    For each unique company we prefer:
      1. an ATS job link seen in the data (Greenhouse/Lever/Ashby/Workable/Smart),
      2. any non-aggregator company link seen in the data,
      3. guesswork website candidates built from the company name (www.<name>.com,
         <name>.com/careers, careers.<name>.com) - the DuckDuckGo-free best effort.
    """
    targets = {}
    for name_ in ('scanned_jobs.json', 'new_jobs_alert.json'):
        p = os.path.join(HERE, 'data', name_)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        cats = data.get('jobs', data)
        for cat in (cats.values() if isinstance(cats, dict) else [cats]):
            for j in cat:
                if not isinstance(j, dict):
                    continue
                company = (j.get('company') or '').strip()
                link = (j.get('link') or '').strip()
                if not company or len(company) > 120:
                    continue
                entry = targets.get(company)
                if entry is None:
                    targets[company] = {'ats': None, 'links': [], 'guesses': []}
                    entry = targets[company]
                if not link.startswith('http'):
                    continue
                ats, _ = detect_ats(link)
                if ats:
                    entry['ats'] = ats
                    if link not in entry['links']:
                        entry['links'].append(link)
                elif not is_aggregator(link):
                    if link not in entry['links']:
                        entry['links'].append(link)
    # add name-derived domain guesses for every brand-like company that had no usable link
    for company, entry in targets.items():
        if not entry['links'] and not entry['ats'] and is_brandlike(company):
            entry['guesses'] = website_candidates(company)[:3]
    return targets


# Full legal/business names ("... Limited", "... Investment Group") almost never
# map to a guessable domain - guessing just wastes requests. Only attempt domain
# guessing for short, brand-like names. Everything else is flagged for manual lookup.
LEGAL_NAME_TOKENS = (
    'limited', 'incorporated', 'corporation', 'enterprises', 'enterprise',
    'technologies', 'industries', 'services', 'company', 'group', 'group of',
    'investments', 'investment', 'international', 'holdings', 'holding', ' ltd',
    ' plc ', ' plc', 'nigeria', 'nigerian', 'hospital', 'hospitals', 'colleges',
    'college', 'schools', 'school', 'universit', ' and ', ' & ', 'the ',
    'health initiatives', 'initiatives',
)


def is_brandlike(name):
    low = name.lower()
    return not any(tok in low for tok in LEGAL_NAME_TOKENS) and len(name) <= 24


def website_candidates(name):
    slug = re.sub(r'[^a-z0-9]+', '', name.lower())
    if not slug:
        return []
    cands = [f'https://www.{slug}.com', f'https://{slug}.com', f'https://www.{slug}.com/careers',
             f'https://careers.{slug}.com', f'https://{slug}.com/careers', f'https://{slug}.careers']
    return list(dict.fromkeys(cands))


def crawl_one(name, info):
    """Process one company target; returns (name, found, n_jobs, err, jobs)."""
    attempts = []
    if info['ats']:
        for link in info['links']:
            ats, slug = detect_ats(link)
            if ats:
                attempts.append(('ats', ats, slug, name))
    if not attempts and info['links']:
        attempts = [('probe', 'link', l, name) for l in info['links'][:1]]
    if not attempts and info['guesses']:
        attempts = [('probe', 'guess', g, name) for g in info['guesses'][:2]]
    if not attempts:
        return name, 'needs_lookup', 0, 'no auto-discoverable site (legal/business name)', []
    jobs, err, found = [], '', '-'
    try:
        for kind, ats_or_link, val, cname in attempts:
            if kind == 'ats':
                jobs, err = ATS_FETCHERS[ats_or_link](val, cname)
                found = f'{ats_or_link}:{val}'
            else:
                jobs, err, found = probe_careers_page(val, cname)
            if found and found != '-':
                break
    except Exception as e:
        err = repr(e)
    return name, found, len(jobs), err, jobs


def run(max_targets=12, manual=None):
    target_items = list(harvest_targets().items())
    # ATS-linked companies first, then non-aggregator-linked, then name-guesses
    target_items.sort(key=lambda kv: 0 if kv[1]['ats'] else (1 if kv[1]['links'] else 2))

    manual_links = []
    if manual:
        for m in manual:
            if m.startswith('http'):
                from urllib.parse import urlparse
                host = urlparse(m).netloc
                labels = host.split('.')
                name = labels[-2] if len(labels) > 2 else labels[0]
                manual_links.append((name, m))
            else:
                for cand in website_candidates(m):
                    manual_links.append((m, cand))

    if manual:
        todo = []
    else:
        # submit only the first `max_targets` that actually have something to try
        todo = []
        for name, info in target_items:
            if len(todo) >= max_targets:
                break
            if info['ats'] or info['links'] or info['guesses']:
                todo.append((name, info))

    all_jobs = []
    report = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda t: crawl_one(t[0], t[1]), todo))

    for i, (name, found, n_jobs, err, jobs) in enumerate(results, 1):
        all_jobs.extend(jobs)
        report.append((name, found, n_jobs, err))
        print(f'  [{i}/{len(todo)}] {name}: {found} -> {n_jobs} jobs {("(" + str(err) + ")") if err and not jobs else ""}')

    scored = list(all_jobs)
    for name, link in manual_links:
        ats, slug = detect_ats(link)
        if ats:
            jobs, err = ATS_FETCHERS[ats](slug, name)
            found = f'{ats}:{slug}'
        else:
            jobs, err, found = probe_careers_page(link, name)
        all_jobs.extend(jobs)
        scored.extend(jobs)
        report.append((name, found, len(jobs), err))
        print(f'  [manual] {name}: {found} -> {len(jobs)} jobs {("(" + str(err) + ")") if err and not jobs else ""}')

    # Dedupe
    seen = set()
    unique = []
    for j in scored:
        key = (j['title'].lower().strip(), j['company'].lower().strip(), j.get('link', ''))
        if key not in seen:
            seen.add(key)
            unique.append(j)
    unique.sort(key=lambda x: x['score'], reverse=True)
    # Drop junk: keep jobs that match the allowed location OR score meaningfully
    unique = [j for j in unique if j['location_match'] or j['score'] >= 25]

    output = {
        'scan_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'targets': report,
        'total_results': len(unique),
        'jobs': unique,
    }
    with open(os.path.join(HERE, 'data', 'career_jobs.json'), 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return unique, report


def main():
    ap = argparse.ArgumentParser(description='Crawl company career pages worldwide for matching roles.')
    ap.add_argument('--max', type=int, default=20, help='max companies to auto-crawl (default 20)')
    ap.add_argument('--company', action='append', help='probe a specific ATS URL or company name (repeatable; skips auto-crawl)')
    args = ap.parse_args()
    print('=' * 60)
    print('  WORLDWIDE CAREER-PAGE CRAWLER')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 60)
    jobs, _ = run(max_targets=args.max, manual=args.company)
    print('=' * 60)
    print(f'  CRAWL COMPLETE: {len(jobs)} relevant career-page jobs -> career_jobs.json')
    print('  Run job_scraper.py to merge them into your master scan.')
    print('=' * 60)


if __name__ == '__main__':
    main()
