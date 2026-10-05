import json
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, 'data')

# Product fast-mode: set JOBMATCH_FAST=1 (or import and set this True) to cap
# the number of pages/posts fetched from the slow Nigerian sources. The
# personal pipeline keeps the full crawl; the product uses the lighter pass.
FAST = os.environ.get('JOBMATCH_FAST', '0') == '1'

TARGET_KEYWORDS = [
    'it support', 'technical support', 'help desk', 'helpdesk',
    'system administrator', 'sysadmin', 'network administrator',
    'network support', 'network technician', 'cloud support',
    'cloud engineer', 'aws', 'junior developer', 'junior software',
    'it technician', 'desktop support', 'field support',
    'junior systems', 'it officer', 'infrastructure support',
    'linux administrator', 'windows administrator', 'devops',
    'python developer', 'flask', 'web developer', 'full stack',
    'entry level it', 'graduate it', 'it intern', 'tech support',
    'support engineer', 'systems administrator', 'network engineer',
    'security analyst', 'cloud administrator', 'computer operator',
    'it graduate trainee', 'software engineer', 'backend developer',
    # --- roles Hope can be trained into / upskilled toward ---
    'service desk', 'application support', 'applications support',
    'qa analyst', 'qa engineer', 'quality assurance', 'quality analyst',
    'data analyst', 'business intelligence', 'database administrator',
    'cybersecurity', 'cyber security', 'information security', 'security operations',
    'soc analyst', 'soc engineer', 'devops engineer', 'site reliability',
    'azure', 'intune', 'microsoft 365', 'google cloud', 'kubernetes',
    'react developer', 'node.js', 'django', 'mobile developer', 'android developer',
    'apprentice', 'graduate trainee', 'internship', 'junior qa',
    'technical writer', 'customer support', 'noc technician', 'it audit',
    'junior data', 'junior network', 'junior security', 'junior cloud',
    'wordpress', 'administrator', 'systems engineer', 'infrastructure engineer',
    'customer success', 'customer service', 'support specialist',
    'support analyst', 'support agent', 'client support'
]

EXCLUDE_KEYWORDS = [
    'senior', 'lead developer', 'lead engineer', 'staff', 'principal',
    'vp', 'vice president', 'dir of', 'director', 'head of',
    'manager of', 'engineering manager', 'architect', 'chief',
    'sre manager', 'cfo', 'ceo', 'cto', 'coo', 'controller',
    'counsel', 'executive', 'swe manager', 'tech lead manager'
]

LOCATION_KEYWORDS = [
    'uyo', 'akwa ibom', 'port harcourt', 'rivers', 'nigeria',
    'lagos', 'abuja', 'remote', 'anywhere', 'worldwide',
    'global', 'distributed', 'work from home', 'wfh',
    'africa', 'emea', 'south africa', 'kenya', 'ghana',
    'rest of world', 'row',
]

# Postings from non-English/European-local markets that a Uyo-based junior cannot apply to.
# These would otherwise slip through the generic keyword matching (Arbeitnow returns lots of German jobs).
NOISE_KEYWORDS = [
    'werkstudent', 'working student', 'dokumentenmanager', 'technischer',
    'property manager', 'mitarbeiter', 'bewerbung', 'projektassistent',
    'gehalt', 'stellvertretung', 'teamleiter', 'abteilung',
    'berufserfahrung', 'personalreferent', 'betriebsstätte',
    'festanstellung', 'befristet', 'kennenlernen',
    'm/w/d', '(mwd)', '(f/m/d)', '(w/m/d)', 'gmbh',
    'deutschland', 'germany', 'europa', 'european', 'europe',
    'munich', 'berlin', 'hamburg', 'frankfurt', 'cologne', 'stuttgart',
    'amsterdam', 'netherlands', 'dutch', 'brussels', 'belgium', 'belgique',
    'sweden', 'stockholm', 'denmark', 'copenhagen', 'finland', 'helsinki',
    'norway', 'oslo', 'austria', 'vienna', 'switzerland', 'zurich', 'schweiz',
    'poland', 'warsaw', 'cracow', 'madrid', 'barcelona', 'spain', 'españa',
    'portugal', 'lisbon', 'lisboa', 'italy', 'rome', 'milan', 'france', 'paris',
    'london', 'united kingdom', 'santiago', 'chile', 'mexico', 'latam',
    'engineer (m/w/d)', 'technician (m/w/d)', 'manager (m/w/d)',
    'firmware validation engineer', 'e-commerce & retail operations',
    'werkstudent (m/w/d)', 'trainee (m/w/d)', 'mechanical ', 'kfz-'
]

USER_AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def is_noise(title, description):
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in NOISE_KEYWORDS)


def is_relevant(title, description, keywords):
    if is_noise(title, description):
        return False
    text = (title + ' ' + description).lower()
    title_lower = title.lower()
    if any(kw in text for kw in EXCLUDE_KEYWORDS):
        return False
    # Title match is the strongest signal - a job is only useful if a
    # target keyword appears in the title, or in a highly relevant description.
    if any(kw in title_lower for kw in keywords):
        return True
    return any(kw in text for kw in keywords)


def check_location_match(location_text):
    text = location_text.lower()
    return any(kw in text for kw in LOCATION_KEYWORDS)


def clean_html(text, limit=600):
    """Strip the HTML that most sources embed in their description field.

    Left in, it renders as literal "<img src=...>" text on the dashboard, which
    is what the job cards were showing.
    """
    if not text:
        return ''
    import html as html_mod
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.I | re.S)
    text = re.sub(r'<br\s*/?>|</p>|</li>|</h\d>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()[:limit]


def compute_score(title, description):
    """Score a job against the ACTIVE target keywords.

    The keyword weights used to be hardcoded to tech roles ("it support",
    "aws", "devops"), which made scores meaningless for any other customer - a
    customer-service profile scored 5-23 on identical-quality jobs. TARGET_KEYWORDS
    is swapped per customer by customer_engine, so read it at call time and let
    the title (where a target keyword really matters) outweigh the body text.
    """
    title_l = (title or '').lower()
    text = f'{title or ""} {description or ""}'.lower()
    score = 0
    for kw in TARGET_KEYWORDS:
        kw = (kw or '').lower().strip()
        if len(kw) < 3:
            continue
        if kw in title_l:
            score += 12
        elif kw in text:
            score += 4
    if re.search(r'(?<![a-z])(senior|sr|lead|head of|principal|manager|director|supervisor)(?![a-z])',
                 title_l):
        score += 4
    if re.search(r'(?<![a-z])(junior|jr|entry[ -]?level|intern|graduate|assistant|trainee)(?![a-z])',
                 title_l):
        score -= 2
    if any(loc in text for loc in ['uyo', 'akwa ibom', 'port harcourt', 'rivers']):
        score += 15
    elif 'nigeria' in text or 'lagos' in text or 'abuja' in text:
        score += 10
    elif 'remote' in text:
        score += 8
    return max(score, 0)


def pick(node, selectors):
    """Return the first child matching any of the candidate CSS selectors, or None."""
    for sel in selectors:
        found = node.select_one(sel)
        if found:
            return found
    return None


# ============ SOURCE 1: Arbeitnow (Global/Remote) ============
def scrape_arbeitnow():
    jobs = []
    try:
        url = 'https://www.arbeitnow.com/api/job-board-api'
        resp = requests.get(url, timeout=15)
        data = resp.json().get('data', [])
        for job in data:
            title = job.get('title', '')
            desc = job.get('description', '') or ''
            company = job.get('company_name', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '')
            if is_relevant(title, desc, TARGET_KEYWORDS):
                jobs.append({
                    'source': 'Arbeitnow',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': desc[:500],
                    'link': link,
                    'score': compute_score(title, desc),
                    'location_match': check_location_match(location)
                })
    except Exception as e:
        print(f'  [Arbeitnow] Error: {e}')
    return jobs


# ============ SOURCE 2: Jobberman (Nigeria) ============
def scrape_jobberman():
    jobs = []
    try:
        base_url = 'https://www.jobberman.com/jobs'
        params_list = [
            {'q': 'it support', 'l': 'Nigeria'},
            {'q': 'network engineer', 'l': 'Nigeria'},
            {'q': 'cloud', 'l': 'Nigeria'},
            {'q': 'software development', 'l': 'Nigeria'},
            {'q': 'graduate trainee', 'l': 'Nigeria'},
            {'q': 'data analyst', 'l': 'Nigeria'},
        ]
        seen_titles = set()
        for params in params_list:
            try:
                resp = requests.get(base_url, headers=USER_AGENT, params=params, timeout=20)
            except Exception:
                continue
            if resp.status_code != 200:
                print(f'  [Jobberman] Status: {resp.status_code}')
                continue
            soup = BeautifulSoup(resp.text, 'lxml')
            cards = soup.select('[data-cy="listing-cards-components"]')
            for card in cards:
                title_el = pick(card, ['a[data-cy="listing-title-link"]', 'a[href*="/listings/"]', 'h3 a'])
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                title = title.strip('|').strip() or (title_el.get('title') or '')
                if not title or title.lower() in seen_titles or not is_relevant(title, '', TARGET_KEYWORDS):
                    continue
                seen_titles.add(title.lower())
                company_el = pick(card, ['p.text-sm.text-blue-700', 'div.flex.items-center ~ p', 'p:nth-of-type(2)'])
                company = company_el.get_text(strip=True) if company_el else ''
                loc_el = pick(card, ['span.text-loading-hide', 'span.bg-brand-secondary-100'])
                location = (loc_el.get_text(strip=True) if loc_el else '') or 'Nigeria'
                href = title_el.get('href', '')
                jobs.append({
                    'source': 'Jobberman',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': '',
                    'link': requests.compat.urljoin(base_url, href),
                    'score': compute_score(title, '') + 20,
                    'location_match': check_location_match(location)
                })
            time.sleep(0.5)
    except Exception as e:
        print(f'  [Jobberman] Error: {e}')
    return jobs


# ============ SOURCE 3: MyJobMag (Nigeria) ============
def scrape_myjobmag():
    jobs = []
    try:
        queries = [
            'it support', 'technical support', 'network engineer', 'cloud engineer',
            'python developer', 'helpdesk', 'system administrator', 'devops engineer',
            'security analyst', 'data analyst', 'web developer', 'graduate trainee',
            'database administrator', 'network support', 'desktop support', 'it officer',
        ]
        if FAST:
            queries = queries[:8]
        pages = 1 if FAST else 2
        seen_links = set()
        for q in queries:
            for page in (1, 2)[:pages]:
                url = f'https://www.myjobmag.com/search/jobs?q={q.replace(" ", "+")}&page={page}'
                try:
                    resp = requests.get(url, headers=USER_AGENT, timeout=20)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, 'lxml')
                for item in soup.select('.job-list li.job-list-li'):
                    title_el = pick(item, ['h2 a', 'a[href*="/job/"]'])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                        continue
                    href = title_el.get('href', '')
                    if href.startswith('/'):
                        href = 'https://www.myjobmag.com' + href
                    if href in seen_links:
                        continue
                    seen_links.add(href)
                    logo_img = pick(item, ['li.job-logo img', 'img[title]'])
                    company = (logo_img.get('title', '').strip() if logo_img else '')
                    company = re.sub(r'\s+logo$', '', company)
                    if not company and ' at ' in title:
                        company = title.split(' at ', 1)[1].strip()
                    location = 'Nigeria'
                    item_text = item.get_text(' ', strip=True).lower()
                    for kw in ['remote', 'uyo', 'akwa ibom', 'port harcourt', 'lagos', 'abuja']:
                        if kw in item_text:
                            location = kw.title()
                            break
                    jobs.append({
                        'source': 'MyJobMag',
                        'company': company,
                        'title': title,
                        'location': location,
                        'description': '',
                        'link': href,
                        'score': compute_score(title, '') + 25,
                        'location_match': check_location_match(location)
                    })
            time.sleep(1)
    except Exception as e:
        print(f'  [MyJobMag] Error: {e}')
    return jobs


# ============ SOURCE 4: HotNigerianJobs (Nigeria) ============
def scrape_hotngjobs():
    jobs = []
    try:
        # Field pages group jobs into "COMPANY Job Recruitment (N Positions)" posts.
        # Each post's detail page lists the individual role openings (as job links
        # whose URL slug encodes "role-at-company"). We do ONE level of follow-up:
        # fetch the freshest posts and read the real roles out of them.
        field_urls = [
            'https://hotnigerianjobs.com/field/234/computer-it-support-jobs-in-nigeria',
            'https://hotnigerianjobs.com/field/236/programming-jobs-in-nigeria',
            'https://hotnigerianjobs.com',
            'https://hotnigerianjobs.com/hotjobs/hotjobs.html',
        ]
        field_urls = field_urls[:2] if FAST else field_urls
        budget_open = time.time() + (12 if FAST else 20)
        post_re = re.compile(r'/hotjobs/(\d+)/[^/]+\.html?')
        seen_posts = []
        for url in field_urls:
            if time.time() > budget_open:
                break
            try:
                resp = requests.get(url, headers=USER_AGENT, timeout=20)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'lxml')
            for link in soup.select('div.fet_show a[href*="/hotjobs/"], .feat_job a[href*="/hotjobs/"], a[href*="/hotjobs/"]'):
                href = link.get('href', '')
                m = post_re.search(href)
                if not m or href in seen_posts:
                    continue
                seen_posts.append(href)
            time.sleep(0.5)

        budget_fetch = time.time() + (40 if FAST else 120)
        for post_url in seen_posts[:(15 if FAST else 60)]:
            if time.time() > budget_fetch:
                print('  [HotNigerianJobs] time budget reached, stopping')
                break
            post_id = post_re.search(post_url).group(1)
            try:
                resp = requests.get(post_url, headers=USER_AGENT, timeout=20)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, 'lxml')
                for link in soup.select('a[href*="/hotjobs/"]'):
                    href = link.get('href', '')
                    m = post_re.search(href)
                    if not m or m.group(1) == post_id:
                        continue
                    if href.startswith('/'):
                        href = 'https://hotnigerianjobs.com' + href
                    slug = m.group(0).rsplit('/', 1)[-1].replace('.html', '').strip().strip('-')
                    title = re.sub(r'[-_]+', ' ', slug).strip().title()
                    # Slug encodes "role-at-company" but the company part is
                    # truncated, so keep only the role portion.
                    title = title.split(' At ')[0].strip()
                    if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                        continue
                    jobs.append({
                        'source': 'HotNigerianJobs',
                        'company': '',
                        'title': title,
                        'location': 'Nigeria',
                        'description': '',
                        'link': href,
                        'score': compute_score(title, '') + 18,
                        'location_match': True
                    })
            except Exception:
                continue
            time.sleep(0.5)
    except Exception as e:
        print(f'  [HotNigerianJobs] Error: {e}')

    # De-duplicate roles that appear in more than one recruitment post
    seen = set()
    unique = []
    for j in jobs:
        key = (j['title'].lower(), j['link'])
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique


# ============ SOURCE 5: RemoteOK (Global Remote) ============
def scrape_remoteok():
    jobs = []
    try:
        url = 'https://remoteok.com/api'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        if isinstance(data, list) and len(data) > 1:
            data = data[1:]
        for job in data:
            title = job.get('position', '') or job.get('title', '')
            desc = job.get('description', '') or ''
            company = job.get('company', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '') or job.get('apply_url', '') or ''
            if is_relevant(title, desc, TARGET_KEYWORDS):
                jobs.append({
                    'source': 'RemoteOK',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': desc[:500],
                    'link': link,
                    'score': compute_score(title, desc) + 5,
                    'location_match': check_location_match(location)
                })
    except Exception as e:
        print(f'  [RemoteOK] Error: {e}')
    return jobs


# ============ SOURCE 6: Remotive (Global Remote) ============
def scrape_remotive():
    jobs = []
    categories = ['', 'software-dev', 'devops-sysadmin', 'customer-support', 'data', 'full-stack-development']
    seen_links = set()
    try:
        for cat in categories:
            url = 'https://remotive.com/api/remote-jobs'
            if cat:
                url += f'?category={cat}'
            try:
                data = requests.get(url, timeout=20).json().get('jobs', [])
            except Exception:
                continue
            for job in data:
                title = job.get('title', '')
                desc = re.sub(r'<[^>]+>', ' ', job.get('description', '') or '')
                company = job.get('company_name', '')
                location = job.get('candidate_required_location', '') or 'Remote'
                link = job.get('url', '')
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                if is_relevant(title, desc, TARGET_KEYWORDS):
                    jobs.append({
                        'source': 'Remotive',
                        'company': company,
                        'title': title,
                        'location': location,
                        'description': re.sub(r'\s+', ' ', desc)[:500],
                        'link': link,
                        'score': compute_score(title, desc) + 5,
                        'location_match': check_location_match(location)
                    })
    except Exception as e:
        print(f'  [Remotive] Error: {e}')
    return jobs


# ============ SOURCE 9: WeWorkRemotely (Global Remote) ============
def scrape_weworkremotely():
    jobs = []
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get('https://weworkremotely.com/remote-jobs.rss', headers=USER_AGENT, timeout=20)
        if resp.status_code != 200:
            return jobs
        root = ET.fromstring(resp.content)
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            desc = item.findtext('description') or ''
            link = (item.findtext('link') or '').strip()
            if not title or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            # WWR titles are "Company: Role" and the RSS body carries the real
            # region. Both were being thrown away, so every result showed a
            # blank company and a vague "Remote" location.
            company, sep, role = title.partition(':')
            company = company.strip() if sep and role.strip() else ''
            if not company:
                slug = re.sub(r'^https?://weworkremotely\.com/remote-jobs/', '', link).strip('/')
                head = slug.split('-')[0].replace('-', ' ').title()
                company = head if head and 'remote' not in head.lower() else ''
            plain = re.sub(r'<[^>]+>', '\n', desc)
            region = ''
            m = re.search(r'Region:\s*([^\n|]+)', plain, re.I)
            if m:
                region = m.group(1).strip(' \t\r\n-*')
            location = region if region and len(region) < 60 else 'Remote'
            if region and not any(k in region.lower() for k in
                                  ('remote', 'anywhere', 'worldwide', 'global')):
                location = f'Remote ({region})'
            jobs.append({
                'source': 'WeWorkRemotely',
                'company': company,
                'title': role.strip() if (sep and role.strip()) else title,
                'location': location,
                'description': desc[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [WeWorkRemotely] Error: {e}')
    return jobs


# ============ SOURCE 6b: Jobicy (Global Remote, Anywhere) ============
def scrape_jobicy():
    jobs = []
    try:
        url = 'https://jobicy.com/api/v2/remote-jobs?count=60&geo=anywhere'
        data = requests.get(url, headers=USER_AGENT, timeout=20).json().get('jobs', [])
        for job in data:
            title = (job.get('jobTitle') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('jobDescription') or '') or ''
            company = job.get('companyName') or ''
            geo = job.get('jobGeo') or 'Anywhere'
            link = job.get('url') or job.get('applyLink') or ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Jobicy',
                'company': company,
                'title': title,
                'location': 'Remote',
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(geo)
            })
    except Exception as e:
        print(f'  [Jobicy] Error: {e}')
    return jobs


# ============ SOURCE 7: Working Nomads (Global Remote) ============
def scrape_workingnomads():
    jobs = []
    try:
        url = 'https://www.workingnomads.com/api/exposed_jobs/'
        data = requests.get(url, timeout=20).json()
        for job in data:
            title = job.get('title', '')
            desc = re.sub(r'<[^>]+>', ' ', job.get('description', '') or '')
            company = job.get('company_name', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '')
            if is_relevant(title, desc, TARGET_KEYWORDS):
                jobs.append({
                    'source': 'WorkingNomads',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': re.sub(r'\s+', ' ', desc)[:500],
                    'link': link,
                    'score': compute_score(title, desc) + 5,
                    'location_match': check_location_match(location)
                })
    except Exception as e:
        print(f'  [WorkingNomads] Error: {e}')
    return jobs


# ============ SOURCE 8: HN "Who is Hiring" (Global startups) ============
def scrape_hn_whoshiring():
    jobs = []
    try:
        search = requests.get(
            'https://hn.algolia.com/api/v1/search?query=%22who%20is%20hiring%22&tags=story&hitsPerPage=1',
            timeout=20).json()
        if not search.get('hits'):
            return jobs
        thread_id = search['hits'][0]['objectID']
        thread = requests.get(f'https://hn.algolia.com/api/v1/items/{thread_id}', timeout=20).json()
        for comment in thread.get('children', []):
            text = comment.get('text') or ''
            text = re.sub(r'<[^>]+>', ' ', text)
            text = html_unescape(text)
            for raw in text.splitlines():
                line = raw.strip()
                if not line or '|' not in line:
                    continue
                if line.startswith('|'):                      # true table row
                    parts = [p.strip() for p in line.split('|')]
                    parts = [p for p in parts if p]
                else:                                         # loose "Company | Role | Location" rows only
                    if len(line) > 200:
                        continue
                    parts = [p.strip() for p in line.split('|')]
                    parts = [p for p in parts if p]
                    if len(parts) < 3:
                        continue
                    if max(len(p) for p in parts[:3]) > 100:
                        continue
                if len(parts) < 3:
                    continue
                company, role, loc = parts[0], parts[1], parts[2]
                if loc.lower() == 'on-site' or len(role) < 5 or len(company) < 2:
                    continue
                # optional 4th field is often the application link
                link = parts[3] if len(parts) > 3 and parts[3].startswith('http') else ''
                if not is_relevant(f'{role} {company}', '', TARGET_KEYWORDS):
                    continue
                jobs.append({
                    'source': 'HNWantsHired',
                    'company': company,
                    'title': role,
                    'location': 'Remote' if 'remote' in loc.lower() else (loc or 'Worldwide'),
                    'description': '',
                    'link': link,
                    'score': compute_score(f'{role} {company}', ''),
                    'location_match': check_location_match(loc)
                })
    except Exception as e:
        print(f'  [HNWantsHired] Error: {e}')
    return jobs


# ============ SOURCE 10: Himalayas (Global Remote, public JSON API) ============
def scrape_himalayas(max_pages=5):
    jobs = []
    seen = set()
    try:
        cursor = None
        for _ in range(max_pages):
            params = {'limit': 100}
            if cursor:
                params['cursor'] = cursor
            data = requests.get('https://himalayas.app/jobs/api', params=params,
                                headers=USER_AGENT, timeout=25).json()
            for job in data.get('jobs') or []:
                title = (job.get('title') or '').strip()
                desc = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', job.get('description') or '')).strip()
                company = job.get('companyName') or ''
                link = job.get('applicationLink') or job.get('guid') or ''
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                restrictions = job.get('locationRestrictions') or []
                timezones = job.get('timezoneRestrictions') or []
                if restrictions:
                    location = ', '.join(str(r) for r in restrictions if str(r).strip())
                elif timezones:
                    location = 'Worldwide - timezone-restricted'
                else:
                    location = 'Worldwide'
                if not is_relevant(title, desc, TARGET_KEYWORDS):
                    continue
                jobs.append({
                    'source': 'Himalayas',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': desc[:500],
                    'link': link,
                    'score': compute_score(title, desc) + 5,
                    'location_match': check_location_match(location),
                })
            cursor = data.get('nextCursor')
            if not cursor:
                break
    except Exception as e:
        print(f'  [Himalayas] Error: {e}')
    return jobs


# ============ SOURCE 11: Virtual Click Jobs (Africa + Worldwide, JSON API) ============
def scrape_virtualclickjobs(max_pages=3):
    jobs = []
    seen = set()
    try:
        for page in range(1, max_pages + 1):
            url = 'https://virtualclickjobs.com/api/jobs'
            data = requests.get(url, params={'page': page, 'pageSize': 25},
                                headers=USER_AGENT, timeout=25).json()
            for job in data.get('jobs') or []:
                title = (job.get('title') or '').strip()
                company = job.get('company') or ''
                location = (job.get('location') or 'Remote').strip()
                notes = re.sub(r'\s+', ' ', str(job.get('notes') or '')).strip()
                slug = (job.get('slug') or '').strip()
                link = f'https://virtualclickjobs.com/jobs/{slug}' if slug else (job.get('applyUrl') or '')
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                if not is_relevant(title, notes, TARGET_KEYWORDS):
                    continue
                jobs.append({
                    'source': 'VirtualClickJobs',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': notes[:500],
                    'link': link,
                    'score': compute_score(title, notes) + 5,
                    'location_match': check_location_match(location),
                })
    except Exception as e:
        print(f'  [VirtualClickJobs] Error: {e}')
    return jobs


# ============ SOURCE 12: Jobspresso (Tech Remote, WordPress job RSS) ============
def scrape_jobspresso():
    jobs = []
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get('https://jobspresso.co/feed/?post_type=job_listing',
                            headers=USER_AGENT, timeout=25)
        if resp.status_code != 200:
            return jobs
        root = ET.fromstring(resp.content)
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', item.findtext('description') or '')
            creator = (item.findtext('{http://purl.org/dc/elements/1.1/}creator') or '')
            parts = re.split(r'<br\s*/?>', creator, flags=re.I)
            company = re.sub(r'[⚲]', '', parts[0]).strip() if parts else ''
            location = re.sub(r'[⚲]', '', parts[1]).strip() if len(parts) > 1 else 'Remote'
            if not title or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Jobspresso',
                'company': company,
                'title': title,
                'location': location or 'Remote',
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location),
            })
    except Exception as e:
        print(f'  [Jobspresso] Error: {e}')
    return jobs


# ============ SOURCE 13: Arbeitnow (Remote-only filter) ============
def scrape_arbeitnow_remote():
    """Arbeitnow API with remote=true filter for fully remote positions."""
    jobs = []
    try:
        url = 'https://www.arbeitnow.com/api/job-board-api'
        params = {'remote': 'true'}
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json().get('data', [])
        for job in data:
            title = job.get('title', '')
            desc = job.get('description', '') or ''
            company = job.get('company_name', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '')
            if is_relevant(title, desc, TARGET_KEYWORDS):
                jobs.append({
                    'source': 'ArbeitnowRemote',
                    'company': company,
                    'title': title,
                    'location': location,
                    'description': desc[:500],
                    'link': link,
                    'score': compute_score(title, desc),
                    'location_match': check_location_match(location)
                })
    except Exception as e:
        print(f'  [ArbeitnowRemote] Error: {e}')
    return jobs


# ============ SOURCE 14: WeWorkRemotely Region Feeds ============
def scrape_weworkremotely_regions():
    """WeWorkRemotely RSS feeds by region/category for better targeting."""
    jobs = []
    try:
        import xml.etree.ElementTree as ET
        # Region/category feeds from WWR
        region_feeds = [
            ('Programming', 'https://weworkremotely.com/categories/remote-programming-jobs.rss'),
            ('DevOps/SysAdmin', 'https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss'),
            ('Customer Support', 'https://weworkremotely.com/categories/remote-customer-support-jobs.rss'),
            ('Design', 'https://weworkremotely.com/categories/remote-design-jobs.rss'),
            ('Marketing', 'https://weworkremotely.com/categories/remote-marketing-jobs.rss'),
        ]
        for region_name, feed_url in region_feeds:
            try:
                resp = requests.get(feed_url, headers=USER_AGENT, timeout=20)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                for item in root.iter('item'):
                    title = (item.findtext('title') or '').strip()
                    desc = item.findtext('description') or ''
                    link = (item.findtext('link') or '').strip()
                    if not title or not is_relevant(title, desc, TARGET_KEYWORDS):
                        continue
                    company, sep, role = title.partition(':')
                    company = company.strip() if sep and role.strip() else ''
                    if not company:
                        slug = re.sub(r'^https?://weworkremotely\.com/remote-jobs/', '', link).strip('/')
                        head = slug.split('-')[0].replace('-', ' ').title()
                        company = head if head and 'remote' not in head.lower() else ''
                    plain = re.sub(r'<[^>]+>', '\n', desc)
                    region = ''
                    m = re.search(r'Region:\s*([^\n|]+)', plain, re.I)
                    if m:
                        region = m.group(1).strip(' \t\r\n-*')
                    location = region if region and len(region) < 60 else 'Remote'
                    if region and not any(k in region.lower() for k in
                                          ('remote', 'anywhere', 'worldwide', 'global')):
                        location = f'Remote ({region})'
                    jobs.append({
                        'source': f'WWR-{region_name}',
                        'company': company,
                        'title': role.strip() if (sep and role.strip()) else title,
                        'location': location,
                        'description': desc[:500],
                        'link': link,
                        'score': compute_score(title, desc) + 5,
                        'location_match': check_location_match(location)
                    })
            except Exception as e:
                print(f'  [WWR-{region_name}] Error: {e}')
                continue
    except Exception as e:
        print(f'  [WeWorkRemotelyRegions] Error: {e}')
    return jobs


# ============ SOURCE 15: Jobgether (Remote Jobs API) ============
def scrape_jobgether():
    """Jobgether API for remote jobs - aggregates from multiple ATS boards."""
    jobs = []
    try:
        # Jobgether has a public API for remote jobs
        url = 'https://api.jobgether.com/api/v2/jobs'
        params = {
            'remote': 'true',
            'page': 1,
            'per_page': 50,
        }
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('data', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = (job.get('company') or {}).get('name', '') if isinstance(job.get('company'), dict) else (job.get('company') or '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '') or job.get('apply_url', '') or ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Jobgether',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [Jobgether] Error: {e}')
    return jobs


# ============ SOURCE 16: Wellfound (AngelList Talent) ============
def scrape_wellfound():
    """Wellfound (formerly AngelList Talent) - startup jobs, many remote."""
    jobs = []
    try:
        # Wellfound has a GraphQL API but we can scrape their job board
        # Using their search API endpoint
        url = 'https://wellfound.com/api/v1/jobs'
        params = {
            'remote': 'true',
            'per_page': 50,
            'page': 1,
        }
        headers = {**USER_AGENT, 'Accept': 'application/json', 'Referer': 'https://wellfound.com/jobs'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('jobs', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = (job.get('startup') or {}).get('name', '') if isinstance(job.get('startup'), dict) else ''
            location = 'Remote' if job.get('remote') else (job.get('location') or 'Remote')
            link = f"https://wellfound.com/jobs/{job.get('id')}" if job.get('id') else ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Wellfound',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [Wellfound] Error: {e}')
    return jobs


# ============ SOURCE 17: Otta (Tech Jobs API) ============
def scrape_otta():
    """Otta API - tech-focused job board with remote filter."""
    jobs = []
    try:
        # Otta has a public API
        url = 'https://api.otta.com/v2/jobs'
        params = {
            'remote': 'true',
            'limit': 50,
            'offset': 0,
        }
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('results', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = (job.get('company') or {}).get('name', '') if isinstance(job.get('company'), dict) else ''
            location = 'Remote' if job.get('is_remote') else (job.get('location') or 'Remote')
            link = job.get('url', '') or f"https://otta.com/jobs/{job.get('id')}" if job.get('id') else ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Otta',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [Otta] Error: {e}')
    return jobs


# ============ SOURCE 18: African Remote Boards ============
def scrape_african_remote():
    """African remote job boards - JobMag, BrighterMonday, etc."""
    jobs = []
    try:
        # BrighterMonday Kenya/Uganda/Tanzania - remote roles
        boards = [
            ('BrighterMonday Kenya', 'https://www.brightermonday.co.ke/jobs', {'q': 'remote', 'location': 'Remote'}),
            ('BrighterMonday Uganda', 'https://www.brightermonday.co.ug/jobs', {'q': 'remote', 'location': 'Remote'}),
            ('BrighterMonday Tanzania', 'https://www.brightermonday.co.tz/jobs', {'q': 'remote', 'location': 'Remote'}),
        ]
        for source_name, base_url, params in boards:
            try:
                resp = requests.get(base_url, headers=USER_AGENT, params=params, timeout=20)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, 'lxml')
                # Generic job card selectors
                for card in soup.select('[data-cy="job-card"], .job-card, article.job, .search-result-item'):
                    title_el = pick(card, ['h3 a', 'h2 a', 'a.job-title', 'a[href*="/job/"]'])
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                        continue
                    href = title_el.get('href', '')
                    if href.startswith('/'):
                        from urllib.parse import urljoin
                        href = urljoin(base_url, href)
                    company_el = pick(card, ['.company-name', '[data-cy="company-name"]', '.job-company'])
                    company = company_el.get_text(strip=True) if company_el else ''
                    location = 'Remote'
                    jobs.append({
                        'source': source_name,
                        'company': company,
                        'title': title,
                        'location': location,
                        'description': '',
                        'link': href,
                        'score': compute_score(title, '') + 10,
                        'location_match': True
                    })
            except Exception as e:
                print(f'  [{source_name}] Error: {e}')
            time.sleep(0.5)
    except Exception as e:
        print(f'  [AfricanRemote] Error: {e}')
    return jobs


# ============ SOURCE 19: Workew (Remote Jobs Aggregator) ============
def scrape_workew():
    """Workew - curated remote jobs from multiple sources."""
    jobs = []
    try:
        url = 'https://workew.com/api/jobs'
        params = {'page': 1, 'per_page': 50}
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('jobs', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = job.get('company', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('url', '') or job.get('apply_url', '') or ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'Workew',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [Workew] Error: {e}')
    return jobs


# ============ SOURCE 20: RemoteHub (Remote Jobs) ============
def scrape_remotehub():
    """RemoteHub - remote job board with API."""
    jobs = []
    try:
        url = 'https://remotehub.io/api/jobs'
        params = {'remote': 'true', 'limit': 50}
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('data', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = job.get('company', '')
            location = job.get('location', '') or 'Remote'
            link = job.get('apply_url', '') or job.get('url', '') or ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'RemoteHub',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [RemoteHub] Error: {e}')
    return jobs


# ============ SOURCE 21: YCombinator Work at a Startup ============
def scrape_yc_startup():
    """YCombinator Work at a Startup - startup jobs, many remote."""
    jobs = []
    try:
        url = 'https://www.workatastartup.com/api/v1/jobs'
        params = {'remote': 'true', 'limit': 50}
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('jobs', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = (job.get('company') or {}).get('name', '') if isinstance(job.get('company'), dict) else ''
            location = 'Remote' if job.get('remote') else (job.get('location') or 'Remote')
            link = f"https://www.workatastartup.com/companies/{job.get('company', {}).get('slug', '')}/jobs/{job.get('id')}" if job.get('id') else ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'YC Startup',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [YC Startup] Error: {e}')
    return jobs


# ============ SOURCE 22: LinkedIn Jobs (via RapidAPI or similar) ============
def scrape_linkedin_jobs():
    """LinkedIn Jobs - using public job search (limited without auth)."""
    jobs = []
    try:
        # LinkedIn public job search - limited but can get some remote roles
        # This is a basic scrape, would need RapidAPI for production
        url = 'https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search'
        params = {
            'keywords': 'remote it support',
            'location': 'Worldwide',
            'f_WT': '2',  # Remote
            'start': 0,
        }
        headers = {**USER_AGENT, 'Accept': 'text/html'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        soup = BeautifulSoup(resp.text, 'lxml')
        for card in soup.select('li.job-result-card, .base-card'):
            title_el = pick(card, ['h3 a', '.base-card__full-link'])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                continue
            href = title_el.get('href', '')
            if href.startswith('/'):
                href = 'https://www.linkedin.com' + href
            company_el = pick(card, ['h4 a', '.base-card__subtitle'])
            company = company_el.get_text(strip=True) if company_el else ''
            location_el = pick(card, ['.job-result-card__location', '.job-search-card__location'])
            location = location_el.get_text(strip=True) if location_el else 'Remote'
            jobs.append({
                'source': 'LinkedIn',
                'company': company,
                'title': title,
                'location': location,
                'description': '',
                'link': href,
                'score': compute_score(title, '') + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [LinkedIn] Error: {e}')
    return jobs


# ============ SOURCE 23: CareerJet (Job Aggregator API) ============
def scrape_careerjet():
    """CareerJet API - job aggregator with remote filter."""
    jobs = []
    try:
        # CareerJet has an affiliate API, using public search for demo
        url = 'https://www.careerjet.com/api/search'
        params = {
            'keywords': 'remote customer service',
            'location': 'remote',
            'pagesize': 50,
        }
        headers = {**USER_AGENT, 'Accept': 'application/json'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        for job in data.get('jobs', []):
            title = (job.get('title') or '').strip()
            desc = re.sub(r'<[^>]+>', ' ', job.get('description') or '') or ''
            company = job.get('company', '')
            location = job.get('locations', '') or 'Remote'
            link = job.get('url', '') or ''
            if not title or not link or not is_relevant(title, desc, TARGET_KEYWORDS):
                continue
            jobs.append({
                'source': 'CareerJet',
                'company': company,
                'title': title,
                'location': location,
                'description': re.sub(r'\s+', ' ', desc)[:500],
                'link': link,
                'score': compute_score(title, desc) + 5,
                'location_match': check_location_match(location)
            })
    except Exception as e:
        print(f'  [CareerJet] Error: {e}')
    return jobs


# ============ SOURCE 24: Jora (Job Aggregator) ============
def scrape_jora():
    """Jora - job aggregator with remote jobs."""
    jobs = []
    try:
        url = 'https://za.jora.com/jobs'
        params = {
            'q': 'remote it support',
            'l': 'Remote',
            'r': 'remote',
        }
        headers = {**USER_AGENT, 'Accept': 'text/html'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        soup = BeautifulSoup(resp.text, 'lxml')
        for card in soup.select('.job-card, .organic-job, [data-job-id]'):
            title_el = pick(card, ['h3 a', 'h2 a', '.job-title a'])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                continue
            href = title_el.get('href', '')
            if href.startswith('/'):
                href = 'https://za.jora.com' + href
            company_el = pick(card, ['.company-name', '[data-company]'])
            company = company_el.get_text(strip=True) if company_el else ''
            location = 'Remote'
            jobs.append({
                'source': 'Jora',
                'company': company,
                'title': title,
                'location': location,
                'description': '',
                'link': href,
                'score': compute_score(title, '') + 5,
                'location_match': True
            })
    except Exception as e:
        print(f'  [Jora] Error: {e}')
    return jobs


# ============ SOURCE 25: Glassdoor (Job Search) ============
def scrape_glassdoor():
    """Glassdoor job search - limited public access."""
    jobs = []
    try:
        url = 'https://www.glassdoor.com/Job/jobs.htm'
        params = {
            'sc.keyword': 'remote it support',
            'locT': 'N',
            'locId': '1',  # Worldwide
            'jobType': 'remote',
            'fromAge': 7,
        }
        headers = {**USER_AGENT, 'Accept': 'text/html'}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jobs
        soup = BeautifulSoup(resp.text, 'lxml')
        for card in soup.select('[data-test="jobListing"], .jobCard, .react-job-listing'):
            title_el = pick(card, ['a[data-test="job-title"], .jobLink'])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not is_relevant(title, '', TARGET_KEYWORDS):
                continue
            href = title_el.get('href', '')
            if href.startswith('/'):
                href = 'https://www.glassdoor.com' + href
            company_el = pick(card, ['[data-test="employer-name"], .employerName'])
            company = company_el.get_text(strip=True) if company_el else ''
            location = 'Remote'
            jobs.append({
                'source': 'Glassdoor',
                'company': company,
                'title': title,
                'location': location,
                'description': '',
                'link': href,
                'score': compute_score(title, '') + 5,
                'location_match': True
            })
    except Exception as e:
        print(f'  [Glassdoor] Error: {e}')
    return jobs


def html_unescape(text):
    import html as _h
    return _h.unescape(text)


# ============ MAIN ============
def main():
    print('=' * 60)
    print('  HOPE JOHN SUNDAY - MULTI-SOURCE JOB SCANNER')
    print(f'  Run Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 60)

    all_jobs = []

    # Fold in jobs discovered by the worldwide career-page crawler, if any.
    career_path = os.path.join(DATA, 'career_jobs.json')
    if os.path.exists(career_path):
        try:
            with open(career_path, encoding='utf-8') as f:
                career = json.load(f)
            if isinstance(career, dict):
                career = career.get('jobs', career)
            if isinstance(career, list):
                career = [c for c in career if isinstance(c, dict) and c.get('title')]
                print(f'[Career crawler] Merging {len(career)} company career-page jobs')
                all_jobs.extend(career)
        except Exception as e:
            print(f'[Career crawler] Could not merge career_jobs.json: {e}')

    sources = [
        # Global Remote APIs (fast, reliable)
        ('Arbeitnow (Global/Remote)', scrape_arbeitnow),
        ('Arbeitnow (Remote-only)', scrape_arbeitnow_remote),
        ('RemoteOK (Global Remote)', scrape_remoteok),
        ('Remotive (Global Remote)', scrape_remotive),
        ('Jobicy (Global Remote)', scrape_jobicy),
        ('WeWorkRemotely (Global Remote)', scrape_weworkremotely),
        ('WeWorkRemotely (Region Feeds)', scrape_weworkremotely_regions),
        ('Working Nomads (Global Remote)', scrape_workingnomads),
        ('Himalayas (Global Remote)', scrape_himalayas),
        ('Virtual Click Jobs (Africa + Worldwide)', scrape_virtualclickjobs),
        ('Jobspresso (Tech Remote)', scrape_jobspresso),
        ('Jobgether (Remote API)', scrape_jobgether),
        ('Wellfound (AngelList Talent)', scrape_wellfound),
        ('Otta (Tech Jobs)', scrape_otta),
        ('Workew (Curated Remote)', scrape_workew),
        ('RemoteHub (Remote Jobs)', scrape_remotehub),
        ('YC Work at a Startup', scrape_yc_startup),

        # African Remote Boards
        ('African Remote Boards', scrape_african_remote),

        # Job Aggregators (broad coverage)
        ('CareerJet', scrape_careerjet),
        ('Jora', scrape_jora),
        ('LinkedIn Jobs', scrape_linkedin_jobs),
        ('Glassdoor', scrape_glassdoor),

        # Community/Startup
        ('HN "Who is Hiring" (Global Startups)', scrape_hn_whoshiring),

        # Nigerian Boards (local/onsite focus)
        ('MyJobMag (Nigeria)', scrape_myjobmag),
        ('HotNigerianJobs (Nigeria)', scrape_hotngjobs),
        ('Jobberman (featured listings)', scrape_jobberman),
    ]

    for name, func in sources:
        print(f'\n[Scanning] {name}...')
        results = func()
        print(f'  Found {len(results)} relevant matches')
        all_jobs.extend(results)

    # Deduplicate by title+company
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = (job['title'].lower().strip(), job['company'].lower().strip())
        if key not in seen:
            seen.add(key)
            job['description'] = clean_html(job.get('description', ''))
            unique_jobs.append(job)

    # Sort by score (highest first)
    unique_jobs.sort(key=lambda x: x['score'], reverse=True)

    # Separate into categories
    onsite_ng = [j for j in unique_jobs if j['location_match'] and not any(
        kw in j['location'].lower() for kw in ['remote', 'worldwide', 'global', 'anywhere']
    )]
    remote_jobs = [j for j in unique_jobs if any(
        kw in j['location'].lower() for kw in ['remote', 'worldwide', 'global', 'anywhere']
    ) and j not in onsite_ng]
    other_jobs = [j for j in unique_jobs if j not in onsite_ng and j not in remote_jobs]

    output = {
        'scan_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_results': len(unique_jobs),
        'categories': {
            'nigerian_onsite': len(onsite_ng),
            'remote_global': len(remote_jobs),
            'other_matches': len(other_jobs)
        },
        'jobs': {
            'nigerian_onsite': onsite_ng,
            'remote_global': remote_jobs,
            'other_matches': other_jobs
        }
    }

    with open(os.path.join(DATA, 'scanned_jobs.json'), 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # --- Snapshot for daily tracking ---
    scan_key = datetime.now().strftime('%Y-%m-%d')
    snap_dir = os.path.join(DATA, 'daily_scans')
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, f'scan_{scan_key}.json')
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # --- Detect NEW jobs since last scan ---
    known = set()
    prev_scans = sorted([p for p in os.listdir(snap_dir) if p.endswith('.json')])
    for p in prev_scans:
        if p == f'scan_{scan_key}.json':
            continue
        try:
            with open(os.path.join(snap_dir, p), encoding='utf-8') as f:
                prev = json.load(f)
            for cat in prev.get('jobs', {}).values():
                for j in cat:
                    known.add((j['title'].lower().strip(), j['company'].lower().strip()))
        except Exception:
            continue

    new_jobs = [j for j in unique_jobs
                if (j['title'].lower().strip(), j['company'].lower().strip()) not in known]

    with open(os.path.join(DATA, 'new_jobs_alert.json'), 'w', encoding='utf-8') as f:
        json.dump({'scan_date': datetime.now().strftime('%Y-%m-%d %H:%M'), 'count': len(new_jobs),
                   'jobs': new_jobs}, f, indent=2, ensure_ascii=False)

    # --- Export dashboard data ---
    flat_jobs = []
    for i, j in enumerate(unique_jobs[:40], 1):
        cat = 'onsite-ng' if j in onsite_ng else ('remote' if j in remote_jobs else 'other')
        flat_jobs.append({
            'rank': i, 'title': j['title'], 'company': j['company'],
            'location': j['location'], 'link': j['link'],
            'tier': 1 if i <= 15 else 2, 'tag': cat
        })
    with open(os.path.join(DATA, 'jobs_data.js'), 'w', encoding='utf-8') as f:
        f.write('window.JOBS_DATA = ' + json.dumps(flat_jobs, ensure_ascii=False) + ';\n')

    print('\n' + '=' * 60)
    print('  SCAN COMPLETE!')
    print(f'  Total unique matches: {len(unique_jobs)}')
    print(f'  Nigerian Onsite: {len(onsite_ng)}')
    print(f'  Remote/Global: {len(remote_jobs)}')
    print(f'  Other: {len(other_jobs)}')
    print(f'  NEW jobs since last scan: {len(new_jobs)}')
    print('\n  Results saved to: data/scanned_jobs.json')
    print(f'  Snapshot: {snap_path}')
    print('  New-job alert: data/new_jobs_alert.json')
    print('  Dashboard data: data/jobs_data.js')
    print('=' * 60)

    if new_jobs:
        print('\n  !!! NEW JOBS FOUND (apply today) !!!')
        print('  ' + '-' * 56)
        for i, job in enumerate(new_jobs[:15], 1):
            print(f'  {i}. [{job["source"]}] {job["title"]} | {job["company"]} | {job["location"]}')

    # Print top 10 matches
    if unique_jobs:
        print('\n  TOP 10 MATCHES:')
        print('  ' + '-' * 56)
        for i, job in enumerate(unique_jobs[:10], 1):
            print(f'  {i}. [{job["source"]}] {job["title"]}')
            print(f'     Company: {job["company"]}')
            print(f'     Location: {job["location"]}')
            print(f'     Score: {job["score"]} | Link: {job["link"][:60]}...' if len(job["link"]) > 60 else f'     Score: {job["score"]} | Link: {job["link"]}')
            print()


if __name__ == '__main__':
    main()
