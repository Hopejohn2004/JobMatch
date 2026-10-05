"""
customer_engine.py - The JobMatch product engine (multi-customer).

Turns the personal toolkit into a product flow:
  user states target keywords (or uploads a CV) -> system scans -> finds
  matching jobs -> automatically tailors the user's CV to the top matches.

This engine now supports multiple customers with explicit customer_id context.

CLI:
  python customer_engine.py profile --customer-id 1 --keywords "it support lagos" --name "Ada"
  python customer_engine.py profile --customer-id 1 --location remote
  python customer_engine.py scan --customer-id 1              # scan with profile keywords
  python customer_engine.py tailor --customer-id 1 --top 8    # tailor CV to top-N matched jobs
  python customer_engine.py run --customer-id 1 --top 8 --cover   # scan + tailor in one shot

Key files (legacy, kept for backward compatibility during transition):
  data/customer_profile.json  - name, target keywords, location preference, cv path
  data/customer_cv.txt        - the uploaded master CV text
  tailored_cvs/               - per-job tailored CVs + cover letters

New multi-customer storage:
  data/jobmatch.db            - SQLite database with customer isolation
  data/customers/<customer_id>/ - customer-specific files
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import cv_tailor
import database
import job_scraper

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
PROFILE_PATH = DATA / 'customer_profile.json'  # Legacy
CV_PATH = DATA / 'customer_cv.txt'              # Legacy
TAILORED_DIR = BASE / 'tailored_cvs'            # Legacy (shared, will be migrated)
SCANNED_PATH = DATA / 'scanned_jobs.json'
RESULTS_PATH = DATA / 'customer_results.json'   # Legacy

# Customer-specific file storage
CUSTOMERS_DIR = DATA / 'customers'

DEFAULT_LOCATIONS = ['uyo', 'akwa ibom', 'port harcourt', 'rivers', 'nigeria',
                     'lagos', 'abuja', 'remote', 'work from home', 'worldwide']

# A customer who types two or three keywords gets a thin candidate pool: the
# scanner only keeps a job when a target keyword appears in it, so "customer
# service" alone misses every "Client Support" posting. These generic
# service-role synonyms widen the pool inside one scan - a second scan would
# double the runtime and blow the web run_script timeout.
SERVICE_SYNONYMS = ['customer service', 'customer support', 'client service', 'customer care',
                    'client support', 'customer relations', 'help desk', 'service desk',
                    'virtual assistant', 'appointment scheduling', 'call centre', 'call center',
                    'customer experience', 'client success', 'remote support']


# ---------------------------------------------------------------- customer context
def get_customer_dir(customer_id: int) -> Path:
    """Get the customer-specific directory, creating if needed."""
    customer_dir = CUSTOMERS_DIR / str(customer_id)
    (customer_dir / 'profile').mkdir(parents=True, exist_ok=True)
    (customer_dir / 'cvs').mkdir(parents=True, exist_ok=True)
    (customer_dir / 'tailored_cvs').mkdir(parents=True, exist_ok=True)
    (customer_dir / 'results').mkdir(parents=True, exist_ok=True)
    return customer_dir


def get_customer_tailored_dir(customer_id: int) -> Path:
    """Get the customer-specific tailored CVs directory."""
    return get_customer_dir(customer_id) / 'tailored_cvs'


# ---------------------------------------------------------------- profile (database-backed)
# The legacy profile/CV files are SHARED across every customer. They are still
# read by the standalone CLI (customer_engine.py profile ... with no
# --customer-id) but they must never be used to answer a per-customer request:
# doing so handed one customer another customer's profile and CV text.
LEGACY_ONLY = os.environ.get('JOBMATCH_LEGACY_FILES') == '1'


def load_profile(customer_id: int) -> dict:
    """Load customer profile from database."""
    profile = database.get_customer_profile(customer_id)
    customer = database.get_customer(customer_id)
    if profile:
        return {
            'name': customer['name'] if customer else '',
            'keywords': profile['keywords'] or '',
            'preferred_locations': profile['preferred_locations'] or '',
            'job_types': profile['job_types'] or '',
            'target_roles': profile['target_roles'] or '',
            'home_country': profile['home_country'] or 'nigeria',
            'cv_source': profile['cv_source'] if 'cv_source' in profile.keys() else '',
            'cv_quality': profile['cv_quality'] if 'cv_quality' in profile.keys() else 0,
            'cv_repair': profile['cv_repair'] if 'cv_repair' in profile.keys() else '',
            'updated': profile['updated_at'] if 'updated_at' in profile.keys() else '',
        }
    if customer is None:
        return {}
    # No profile row yet. Return an empty-but-valid profile for a real
    # customer. Falling back to the shared legacy file here is what leaked one
    # customer's saved profile to every other customer.
    return {
        'name': customer['name'] or '',
        'keywords': '', 'preferred_locations': '', 'job_types': '',
        'target_roles': '', 'home_country': customer['country'] or 'nigeria',
        'cv_source': '', 'cv_quality': 0, 'cv_repair': '',
        'updated': customer['updated_at'] if 'updated_at' in customer.keys() else '',
    }


def save_profile(customer_id: int, name='', keywords='', location='', cv_source='', **extra) -> dict:
    """Save customer profile to database."""
    # Update database
    profile = database.get_customer_profile(customer_id)
    if profile:
        database.create_or_update_profile(
            customer_id=customer_id,
            keywords=keywords or profile['keywords'],
            preferred_locations=location or profile['preferred_locations'],
            job_types=extra.get('job_types', profile['job_types']),
            target_roles=extra.get('target_roles', profile['target_roles']),
            home_country=extra.get('country', profile['home_country']),
        )
    else:
        database.create_or_update_profile(
            customer_id=customer_id,
            keywords=keywords,
            preferred_locations=location,
            job_types=extra.get('job_types', ''),
            target_roles=extra.get('target_roles', ''),
            home_country=extra.get('country', 'nigeria'),
        )

    saved = load_profile(customer_id)
    if name:
        saved['name'] = name
        # Keep the display name on the customer row too.
        database.update_customer(customer_id, name=name[:100])
    if cv_source:
        saved['cv_source'] = cv_source
    # 'location' is part of the documented shape of this return value (and the
    # legacy file format), so keep it as an alias of preferred_locations.
    saved['location'] = saved.get('preferred_locations', '')
    saved['updated'] = datetime.now().isoformat(timespec='seconds')

    # Mirror to the legacy file ONLY for explicit CLI/legacy use. Writing it
    # unconditionally meant the last customer to save a profile overwrote the
    # file that every other customer fell back to reading.
    if LEGACY_ONLY:
        legacy_profile = dict(saved)
        DATA.mkdir(parents=True, exist_ok=True)
        with open(PROFILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(legacy_profile, f, indent=2)

    return saved


# ---------------------------------------------------------------- CV handling (database-backed)
def _pymupdf_text(data):
    """Second opinion on embedded PDF text - often cleaner than pypdf."""
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype='pdf') as document:
            return '\n'.join(page.get_text('text') for page in document).strip()
    except Exception as e:
        print(f'  [warn] pymupdf text unavailable: {e}')
        return None


def _ocr_pdf(data):
    try:
        import os
        import shutil

        import pymupdf
        import pytesseract
        from PIL import Image

        tesseract = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
        if not tesseract:
            candidates = (
                r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            )
            tesseract = next((path for path in candidates if os.path.isfile(path)), None)
        if not tesseract:
            return None

        pytesseract.pytesseract.tesseract_cmd = tesseract
        parts = []
        with pymupdf.open(stream=data, filetype='pdf') as document:
            for page in document:
                try:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
                    image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                    text = pytesseract.image_to_string(
                        image, lang='eng', config='--psm 3', timeout=90
                    ).strip()
                    if text:
                        parts.append(text)
                except Exception as e:
                    print(f'  [warn] OCR failed for a PDF page: {e}')
        result = '\n'.join(parts).strip()
        return result if len(re.sub(r'\s+', '', result)) >= 20 else None
    except Exception as e:
        print(f'  [warn] PDF OCR unavailable: {e}')
        return None


def extract_cv_text(data, filename):
    """Extract plain text from an uploaded CV file (txt/md/pdf/docx)."""
    ext = (os.path.splitext(filename or '')[1] or '').lower()
    try:
        if ext in ('.txt', '.md', '.rtf'):
            for enc in ('utf-8', 'latin-1', 'cp1252'):
                try:
                    return data.decode(enc)
                except (UnicodeDecodeError, AttributeError):
                    continue
            return data.decode('latin-1', errors='replace')
        if ext == '.pdf':
            candidates = []
            try:
                import io

                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(data))
                text = '\n'.join((p.extract_text() or '') for p in reader.pages).strip()
                if text:
                    candidates.append(('pypdf', text))
            except Exception as e:
                print(f'  [warn] embedded PDF text unavailable: {e}')
            text = _pymupdf_text(data)
            if text:
                candidates.append(('pymupdf', text))
            best_name, best_text, best_q = '', '', -1.0
            for name, text in candidates:
                q = cv_tailor.cv_text_quality(text)
                print(f'  [extract] {name}: {len(text.split())} words, quality {q:.2f}')
                if q > best_q:
                    best_name, best_text, best_q = name, text, q
            if best_text and best_q >= 0.75:
                return best_text
            ocr = _ocr_pdf(data)
            if ocr:
                q = cv_tailor.cv_text_quality(ocr)
                print(f'  [extract] ocr: {len(ocr.split())} words, quality {q:.2f}')
                if q > best_q:
                    best_name, best_text, best_q = 'ocr', ocr, q
            if best_text:
                if best_q < 0.75:
                    print(f'  [extract] best option ({best_name}) is still garbled - '
                          f'will be repaired by the LLM before tailoring')
                return best_text
            return None
        if ext in ('.docx', '.dotx'):
            import io
            import xml.etree.ElementTree as ET
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(data))
            xml = z.read('word/document.xml')
            root = ET.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            parts = []
            for para in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                parts.append(''.join(t.text or '' for t in
                                      para.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')))
            return '\n'.join(p for p in parts if p.strip())
        if ext == '.doc':
            text = data.decode('latin-1', errors='replace')
            text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]+', '', text)
            return re.sub(r'\n{3,}', '\n\n', text)
    except Exception as e:
        print(f'  [warn] could not extract text from {filename or "upload"}: {e}')
    return None


def _should_repair(ext, text):
    """Decide whether the extracted text needs an LLM cleanup pass."""
    if ext in ('.pdf', '.doc'):
        return True
    return cv_tailor.needs_repair(text)


def _ledger_tokens(customer_id: int, kind: str, note: str = None) -> int:
    """Drain cv_tailor's token tally into the customer's ledger.

    cv_tailor accumulates every provider-reported count in a module global
    because the retry/fallback loop can make several calls per unit of work.
    Draining it here is what makes daily_token_budget enforceable at all.
    """
    used = cv_tailor.take_token_usage()
    if not used['tokens']:
        return 0
    try:
        database.record_token_usage(customer_id, used['tokens'], kind=kind,
                                    note=note or f"{used['calls']} llm call(s)")
    except Exception as e:
        # Never let accounting bookkeeping fail the customer's actual work.
        print(f'  [warn] could not record token usage: {e}')
        return 0
    print(f"  [tokens] {used['tokens']} ({kind}, {used['calls']} call(s))")
    return used['tokens']


def save_cv_bytes(customer_id: int, data: bytes, filename: str = None, repair: bool = True) -> str:
    """Store an uploaded CV for a specific customer, cleaning a mangled text layer before we use it."""
    text = extract_cv_text(data, filename)
    if not text or not text.strip():
        return None

    customer_dir = get_customer_dir(customer_id)
    cvs_dir = customer_dir / 'cvs'

    raw_text = text
    ext = (os.path.splitext(filename or '')[1] or '').lower()
    quality = cv_tailor.cv_text_quality(text)
    notes = []
    if repair and _should_repair(ext, text):
        fixed, notes = cv_tailor.repair_cv_text(text)
        _ledger_tokens(customer_id, 'cv_repair')
        if cv_tailor.cv_text_quality(fixed) >= quality:
            text = fixed
        else:
            notes.append('repair did not improve on the extraction - kept the original')
    quality = cv_tailor.cv_text_quality(text)

    # Save raw and cleaned text
    raw_path = cvs_dir / 'customer_cv_raw.txt'
    clean_path = cvs_dir / 'customer_cv.txt'
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(raw_text.strip() + '\n')
    with open(clean_path, 'w', encoding='utf-8') as f:
        f.write(text.strip() + '\n')

    # Calculate file hash
    file_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

    # Store in database
    database.create_customer_cv(
        customer_id=customer_id,
        original_filename=filename or 'upload',
        stored_path=str(clean_path.relative_to(BASE)),
        file_hash=file_hash,
        text_content=text,
        quality_score=quality,
    )

    # Update profile with CV info
    database.create_or_update_profile(
        customer_id=customer_id,
        cv_source=filename or 'upload',
        cv_quality=round(quality, 2),
        cv_repair='; '.join(notes),
    )

    # The shared data/customer_cv.txt is deliberately NOT written here. It was a
    # single global file, so every upload overwrote it and get_active_cv_path
    # handed it to whichever customer had no CV of their own.
    if LEGACY_ONLY:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(CV_PATH, 'w', encoding='utf-8') as f:
            f.write(text.strip() + '\n')

    print(f'  CV quality {quality:.2f}'
          + (f' - {"; ".join(notes)}' if notes else ' (clean, no repair needed)'))
    return str(clean_path)


def set_cv_text(customer_id: int, text: str) -> str:
    """Set CV text directly for a customer."""
    customer_dir = get_customer_dir(customer_id)
    clean_path = customer_dir / 'cvs' / 'customer_cv.txt'
    with open(clean_path, 'w', encoding='utf-8') as f:
        f.write(text.strip() + '\n')

    # Store in database
    file_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    quality = cv_tailor.cv_text_quality(text)
    database.create_customer_cv(
        customer_id=customer_id,
        original_filename='direct_text',
        stored_path=str(clean_path.relative_to(BASE)),
        file_hash=file_hash,
        text_content=text,
        quality_score=quality,
    )

    if LEGACY_ONLY:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(CV_PATH, 'w', encoding='utf-8') as f:
            f.write(text.strip() + '\n')

    return str(clean_path)


def get_active_cv_path(customer_id: int) -> str:
    """Get the path to the active CV for a customer.

    Returns '' when the customer has no CV of their own. Falling back to the
    shared legacy data/customer_cv.txt here returned the *last customer's* CV
    text to every other customer, which then got tailored and emailed onward.
    """
    cv = database.get_customer_active_cv(customer_id)
    if cv and cv['stored_path']:
        path = BASE / cv['stored_path']
        if path.exists():
            return str(path)
    return ''


def parse_keywords(keywords_raw):
    """Turn user-provided keywords into a clean list for the scanner."""
    keywords = []
    for part in re.split(r'[,;\n]+', keywords_raw or ''):
        part = part.strip().lower()
        if part and part not in keywords:
            keywords.append(part)
    if not keywords:
        # Fall back to deriving from the uploaded CV.
        # We can't easily do this without a customer_id, so return defaults
        pass
    return keywords or list(job_scraper.TARGET_KEYWORDS[:25])


# "Remote" on a job board often means "remote, but only for people in this one
# country" or "remote, but only if you can work US office hours". Those are not
# worth the customer's LLM budget, so they are filtered out with a reason.
ANYWHERE_MARKERS = ('worldwide', 'anywhere', 'global', 'any country', 'anywhere in the world',
                    'international', 'multiple locations', 'no location restriction',
                    'work from any', 'fully remote worldwide')
OFFSHORE_HOURS = ('east coast', 'west coast', 'central time', 'mountain time', 'pacific time',
                  'us time', 'u.s. time', 'us hours', 'est/pst', 'americas only',
                  'north america', 'united states only', 'u.s. only', 'us-based', 'us only',
                  'canada only', 'uk only', 'emea only')
COUNTRIES = {
    'nigeria': ('nigeria',), 'ghana': ('ghana',), 'kenya': ('kenya',),
    'south africa': ('south africa',), 'ethiopia': ('ethiopia',), 'uganda': ('uganda',),
    'tanzania': ('tanzania',), 'rwanda': ('rwanda',), 'senegal': ('senegal',),
    'ivory coast': ('ivory coast', 'cote divoire'), 'cameroon': ('cameroon',),
    'zambia': ('zambia',), 'zimbabwe': ('zimbabwe',), 'botswana': ('botswana',),
    'namibia': ('namibia',), 'egypt': ('egypt',), 'morocco': ('morocco',),
    'angola': ('angola',), 'mozambique': ('mozambique',),
    'sierra leone': ('sierra leone',), 'liberia': ('liberia',), 'gambia': ('gambia',),
    'united states': ('united states', 'usa', 'u.s.', 'us'),
    'canada': ('canada',), 'united kingdom': ('united kingdom', 'uk', 'england', 'scotland'),
    'ireland': ('ireland',), 'germany': ('germany',), 'france': ('france',),
    'spain': ('spain',), 'italy': ('italy',), 'netherlands': ('netherlands', 'holland'),
    'poland': ('poland',), 'portugal': ('portugal',), 'sweden': ('sweden',),
    'norway': ('norway',), 'denmark': ('denmark',), 'finland': ('finland',),
    'australia': ('australia',), 'new zealand': ('new zealand',), 'india': ('india',),
    'pakistan': ('pakistan',), 'bangladesh': ('bangladesh',),
    'philippines': ('philippines',), 'indonesia': ('indonesia',), 'vietnam': ('vietnam',),
    'thailand': ('thailand',), 'malaysia': ('malaysia',), 'singapore': ('singapore',),
    'japan': ('japan',), 'china': ('china',), 'south korea': ('south korea',),
    'brazil': ('brazil',), 'mexico': ('mexico',), 'argentina': ('argentina',),
    'colombia': ('colombia',), 'chile': ('chile',), 'turkey': ('turkey',),
    'israel': ('israel',), 'uae': ('uae', 'united arab emirates'),
    'saudi arabia': ('saudi arabia',), 'qatar': ('qatar',), 'kuwait': ('kuwait',),
    'romania': ('romania',), 'hungary': ('hungary',), 'czech republic': ('czech republic',),
    'ukraine': ('ukraine',), 'greece': ('greece',), 'austria': ('austria',),
    'switzerland': ('switzerland',),
}
COUNTRY_RE = {name: re.compile(r'(?<![a-z])(?:' + '|'.join(
    re.escape(w) for w in words) + r')(?![a-z])') for name, words in COUNTRIES.items()}
REGIONS = {
    'europe': ('europe', 'european union', 'eu only', 'dach', 'benelux', 'nordics'),
    'asia': ('asia', 'apac', 'asean'),
    'latin america': ('latin america', 'south america', 'central america', 'latam'),
    'middle east': ('middle east', 'gulf countries'),
    'australasia': ('australasia',),
    'caribbean': ('caribbean',),
}
REGION_RE = {name: re.compile(r'(?<![a-z])(?:' + '|'.join(
    re.escape(w) for w in words) + r')(?![a-z])') for name, words in REGIONS.items()}
HOURS_RE = re.compile(r'(?<![a-z])(?:' + '|'.join(
    re.escape(h) for h in sorted(OFFSHORE_HOURS, key=len, reverse=True)) + r')(?![a-z])')


def location_verdict(job, pref, home_country='nigeria'):
    """Return (ok, reason). Reason is '' when the job is a usable match."""
    pref = (pref or '').strip().lower()
    loc = (job.get('location') or '')
    loc_l = loc.lower()
    if not pref or pref in ('any', 'anywhere', 'worldwide', 'all'):
        return True, ''

    if pref == 'remote':
        if not any(k in loc_l for k in ('remote', 'worldwide', 'global', 'anywhere',
                                        'work from home', 'wfh', 'virtual')):
            return False, f'not remote ({loc or "no location"})'
        hours = HOURS_RE.search(loc_l)
        if hours:
            return False, f'requires {hours.group(0)} hours'
        if any(m in loc_l for m in ANYWHERE_MARKERS):
            return True, ''                       # explicitly open to everyone
        blocked = {name for name, rx in COUNTRY_RE.items() if rx.search(loc_l)}
        blocked |= {name for name, rx in REGION_RE.items() if rx.search(loc_l)}
        home = (home_country or '').lower().strip()
        blocked = {b for b in blocked if b != home}
        if home and not any(rx.search(home) for rx in REGION_RE.values()):
            blocked = {b for b in blocked if home not in b}
        if blocked:
            return False, f'only open to {", ".join(sorted(blocked)[:2])}'
        return True, ''

    if pref == 'nigerian':
        nigeria = ('nigeria', 'lagos', 'abuja', 'uyo', 'akwa', 'rivers', 'port harcourt')
        if any(k in loc_l for k in nigeria):
            return True, ''
        return False, f'not in Nigeria ({loc or "no location"})'
    ok = pref in loc_l
    return ok, '' if ok else f'not in {pref} ({loc or "no location"})'


def matches_location(job, pref, home_country='nigeria'):
    return location_verdict(job, pref, home_country)[0]


# ---------------------------------------------------------------- scan
def _run_scan_internal(keywords):
    """Run scanner but temporarily override the target keyword list."""
    old = job_scraper.TARGET_KEYWORDS
    old_fast = job_scraper.FAST
    scan_kws = list(keywords) + [s for s in SERVICE_SYNONYMS if s not in keywords]
    job_scraper.TARGET_KEYWORDS = scan_kws
    job_scraper.FAST = True
    try:
        job_scraper.main()
    finally:
        job_scraper.TARGET_KEYWORDS = old
        job_scraper.FAST = old_fast


def run_scan(customer_id: int, keywords: list = None) -> dict:
    """Run the multi-source scanner restricted to the customer's keywords."""
    profile = load_profile(customer_id)
    kws = parse_keywords(keywords or profile.get('keywords', ''))
    _run_scan_internal(kws)
    data = json.load(open(SCANNED_PATH, encoding='utf-8'))
    print(f'  scan complete: {data.get("total_results", 0)} matches '
          f'for {len(kws)} keywords')

    # Store jobs in database and create matches
    _store_scanned_jobs(customer_id, data, kws)

    return data


def _store_scanned_jobs(customer_id: int, data: dict, keywords: list):
    """Store scanned jobs in database and create job matches for the customer."""
    for cat in ('nigerian_onsite', 'remote_global', 'other_matches'):
        for job in data.get('jobs', {}).get(cat, []) or []:
            job_id = database.create_job(
                source=job.get('source', ''),
                title=job.get('title', ''),
                company=job.get('company', ''),
                location=job.get('location', ''),
                url=job.get('link', ''),
                description=job.get('description', ''),
                external_id=job.get('link', '')
            )
            # Calculate fit score
            profile = load_profile(customer_id)
            pref = profile.get('preferred_locations') or profile.get('location', 'any')
            home = profile.get('home_country', 'nigeria')
            ok, _ = location_verdict(job, pref, home)
            if ok:
                title = (job.get('title') or '').lower()
                hay = ' '.join([job.get('title') or '', job.get('company') or '',
                                job.get('description') or '', job.get('location') or '']).lower()
                covered = 0
                for kw in keywords:
                    if kw in title:
                        covered += 3
                    elif kw in hay:
                        covered += 1
                fit = round(covered * 10 + min(float(job.get('score') or 0), 60) * 0.1, 1)
                database.create_job_match(
                    customer_id=customer_id,
                    job_id=job_id,
                    score=float(job.get('score', 0)),
                    fit_score=fit,
                    reason=f'Keyword coverage: {covered}',
                    status='new'
                )


# ---------------------------------------------------------------- tailor
def flat_jobs(data):
    jobs = []
    for cat in ('nigerian_onsite', 'remote_global', 'other_matches'):
        for j in data.get('jobs', {}).get(cat, []) or []:
            jobs.append(j)
    return jobs


def rank_jobs(jobs, keywords):
    """Order jobs by how well they match THIS customer's keywords."""
    kws = [k.lower().strip() for k in keywords if k and k.strip()]
    ranked = []
    for job in jobs:
        title = (job.get('title') or '').lower()
        hay = ' '.join([job.get('title') or '', job.get('company') or '',
                        job.get('description') or '', job.get('location') or '']).lower()
        covered = 0
        for kw in kws:
            if kw in title:
                covered += 3
            elif kw in hay:
                covered += 1
        fit = round(covered * 10 + min(float(job.get('score') or 0), 60) * 0.1, 1)
        ranked.append((fit, covered, job))
    ranked.sort(key=lambda t: (-t[0], -t[1]))
    return ranked


def run_tailor(customer_id: int, top: int = 8, cover: bool = False, provider: str = None, force: bool = False):
    """Tailor the customer's CV to the top-N matched jobs."""
    profile = load_profile(customer_id)
    cv_path = get_active_cv_path(customer_id)
    if not cv_path or not os.path.exists(cv_path):
        print('  [error] no customer CV yet - upload one first (--cv or via web)')
        return []

    data = json.load(open(SCANNED_PATH, encoding='utf-8'))
    pref = profile.get('preferred_locations') or profile.get('location', 'any')
    home = profile.get('home_country', 'nigeria')
    kws = parse_keywords(profile.get('keywords', ''))

    jobs, dropped = [], []
    for job in flat_jobs(data):
        ok, reason = location_verdict(job, pref, home)
        (jobs if ok else dropped).append(job if ok else (job, reason))
    if dropped:
        for job, reason in dropped[:6]:
            print(f'  [skip] {job.get("title", "")[:52]!r} - {reason}')
        if len(dropped) > 6:
            print(f'  [skip] ...and {len(dropped) - 6} more filtered by location')

    ranked = rank_jobs(jobs, kws)
    strong = [t for t in ranked if t[1]]
    weak = [t for t in ranked if not t[1]]
    chosen = (strong + weak)[:max(top, 0)]
    if strong:
        print(f'  {len(strong)} job(s) match the target keywords; '
              f'{len(weak)} kept only as filler')

    print(f'  tailoring {len(chosen)} job(s) for '
          f'{profile.get("name") or "customer"} (loc pref: {pref or "any"})')

    tailored_dir = get_customer_tailored_dir(customer_id)
    results = []
    for i, (fit, _covered, job) in enumerate(chosen, 1):
        name = f'{i:02d}_'
        r = cv_tailor.tailor_job(job, base_cv=cv_path, cover=cover,
                                 provider=provider, force=force,
                                 out_dir=tailored_dir, cv_prefix=name)
        # Charge this job's LLM calls to the customer before moving on, so a
        # crash halfway through the batch still accounts for the work done.
        _ledger_tokens(customer_id, 'tailor', note=job.get('title', '')[:120])

        # Get source CV ID
        source_cv = database.get_customer_active_cv(customer_id)
        source_cv_id = source_cv['id'] if source_cv else None

        # Store in database
        job_id = None
        job_url = job.get('link', '')
        if job_url:
            existing = database.get_job_by_url(job_url)
            if existing:
                job_id = existing['id']

        if job_id and source_cv_id:
            database.create_tailored_cv(
                customer_id=customer_id,
                job_id=job_id,
                source_cv_id=source_cv_id,
                stored_path=r['cv'],
                cover_letter_path=r.get('letter'),
                qc_notes='; '.join(r.get('qc', []))
            )

        results.append({
            'title': job.get('title', ''),
            'company': job.get('company', ''),
            'location': job.get('location', ''),
            'source': job.get('source', ''),
            'score': job.get('score', 0),
            'fit': fit,
            'link': job.get('link', ''),
            'cv': os.path.basename(r['cv']) if os.path.exists(r['cv']) else None,
            'letter': os.path.basename(r['letter']) if r.get('letter') else None,
            'qc': r.get('qc', []),
        })

# Save results to customer-specific directory
    customer_dir = get_customer_dir(customer_id)
    results_path = customer_dir / 'results' / 'customer_results.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump({'profile': {k: v for k, v in profile.items()},
                   'generated': datetime.now().isoformat(timespec='seconds'),
                   'results': results}, f, indent=2)
    
    print(f'  results written: {results_path}')
    return results


# ---------------------------------------------------------------- cli
def main():
    # Parse customer_id first (before subcommand)
    import sys
    customer_id = 1  # default for backward compatibility
    remaining_args = []
    i = 0
    while i < len(sys.argv):
        if sys.argv[i] == '--customer-id' and i + 1 < len(sys.argv):
            try:
                customer_id = int(sys.argv[i + 1])
            except (ValueError, IndexError):
                pass
            i += 2
        else:
            remaining_args.append(sys.argv[i])
            i += 1
    
    # Now parse the subcommand with remaining args
    ap = argparse.ArgumentParser(description='JobMatch customer engine')
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('profile')
    p.add_argument('--name', default='')
    p.add_argument('--keywords', default='')
    p.add_argument('--location', default='', help='any | remote | nigerian | uyo')
    p.add_argument('--country', default='',
                   help="home country, used to drop remote jobs that are only open "
                        "to applicants elsewhere (default nigeria)")

    c = sub.add_parser('cv')
    c.add_argument('--text', help='paste CV text directly')
    c.add_argument('--file', help='path to a CV file (txt/pdf/docx)')

    sub.add_parser('scan')

    t = sub.add_parser('tailor')
    t.add_argument('--top', type=int, default=8)
    t.add_argument('--cover', action='store_true')
    t.add_argument('--provider', default=None)
    t.add_argument('--force', action='store_true')

    r = sub.add_parser('run')
    r.add_argument('--top', type=int, default=8)
    r.add_argument('--cover', action='store_true')
    r.add_argument('--provider', default=None)
    r.add_argument('--force', action='store_true')

    args = ap.parse_args(remaining_args[1:])  # skip script name
    cmd = args.cmd or 'profile'

    if cmd == 'profile':
        profile = save_profile(customer_id, name=args.name, keywords=args.keywords,
                               location=args.location, country=args.country)
        print(json.dumps(profile, indent=2))
    elif cmd == 'cv':
        if args.file and os.path.exists(args.file):
            data = open(args.file, 'rb').read()
            path = save_cv_bytes(customer_id, data, os.path.basename(args.file))
        elif args.text:
            path = set_cv_text(customer_id, args.text)
        else:
            sys.exit('  use --text "..." or --file path/to/cv.pdf')
        print(f'  CV saved: {path}')
    elif cmd == 'scan':
        run_scan(customer_id)
    elif cmd == 'tailor':
        run_tailor(customer_id, top=args.top, cover=args.cover, provider=args.provider, force=args.force)
    elif cmd == 'run':
        run_scan(customer_id)
        run_tailor(customer_id, top=args.top, cover=args.cover, provider=args.provider, force=args.force)


if __name__ == '__main__':
    main()
