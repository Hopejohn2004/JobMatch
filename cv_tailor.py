"""
cv_tailor.py - Rewrite a CV to match a target job (ATS-tailored).

Part of the JobMatch product experiment (a copy of the personal toolkit).
Turns ONE master CV into a version tuned to a specific job posting:

  - Auto-picks the best base CV (IT Support / Developer / Cloud) by keyword score.
  - Fetches the job description from the posting URL if it wasn't captured.
  - Rewrites the CV with an LLM: reorders skills, rephrases bullets to use the
    job's keywords, retunes the summary. STRICTLY no invented facts.
  - Falls back to a local keyword-tailor if no API key is configured.

Usage:
  python cv_tailor.py --url https://www.myjobmag.com/job/it-support-...
  python cv_tailor.py --job "<job link or exact title fragment>"
  python cv_tailor.py --text "IT Support & Network Administrator - Lagos. 3 yrs exp..."
  python cv_tailor.py --job "<fragment>" --cover      # also write a cover letter
  python cv_tailor.py --job "<fragment>" --provider groq

LLM providers (in priority order, all read from env):
  GEMINI_API_KEY    -> Gemini REST (free tier)          [default]
  GROQ_API_KEY      -> Groq REST (free tier)
  OPENROUTER_API_KEY-> OpenRouter REST (uses:free models)
  OPENAI_API_KEY    -> OpenAI REST (paid)

Env is read from:  cv_tailor.env  (this folder), then
                   ..\\Ideas\\Twitter\\x-llm-bot\\.env
Output:  tailored_cvs\\<Company>_tailored_cv.txt   (+ _cover_letter.txt with --cover)

No facts are invented. Anything the model must not change stays verbatim.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import date

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CV_TEXT_DIR = os.path.join(BASE, 'cv_text')
SCANNED_PATH = os.path.join(BASE, 'data', 'scanned_jobs.json')
FETCH_DIR = os.path.join(BASE, 'data', 'fetched_jobs')
OUT_DIR = os.path.join(BASE, 'tailored_cvs')

ENV_FILES = [
    os.path.join(BASE, 'cv_tailor.env'),
    os.path.join(BASE, '..', 'Ideas', 'Twitter', 'x-llm-bot', '.env'),
]

PROVIDERS = {
    'gemini': {
        'key': 'GEMINI_API_KEY',
        # B-34: this was 'gemini-1.5-flash', which the API now 404s ("not
        # found for API version v1beta"). Every Gemini call was failing and
        # silently falling through to the next provider. Verified live
        # 2026-10-04: gemini-3.6-flash -> HTTP 200; 2.5-flash -> 404 ("no longer
        # available to new users").
        'model': 'gemini-3.6-flash',
    },
    'groq': {
        'key': 'GROQ_API_KEY',
        'model': 'openai/gpt-oss-120b',
    },
    'openrouter': {
        'key': 'OPENROUTER_API_KEY',
        'model': 'google/gemma-4-31b-it:free',
    },
    'openai': {
        'key': 'OPENAI_API_KEY',
        'model': 'gpt-4o-mini',
    },
}

STOPWORDS = set(['a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'have', 'in', 'into', 'is', 'it', 'of', 'on', 'or', 'that', 'the', 'their', 'to', 'with', 'your', 'any', 'role', 'will', 'you', 'we', 'our', 'plus', 'years', 'year', 'experience', 'job', 'work', 'must', 'able', 'ability', 'etc', 'including', 'minimum', 'skills', 'strong', 'etc'])

# A CV that came out of a bad PDF/OCR extraction shows a few tells: fragments
# that continue on the next line, words glued with an inner capital
# ("resoWing"), punctuation stuck inside a word ("brow:sin"), and phone numbers
# that lost their leading digits. cv_text_quality() scores those so a customer's
# master CV can be repaired BEFORE anything is tailored from it.
INNER_UPPER = re.compile(r'[a-z]{2,}[A-Z]')
INNER_PUNCT = re.compile(r'[A-Za-z][^\w\s.,;:!?\'"()\[\]&\-/+=@][A-Za-z]')
PHONEISH = re.compile(r'(?:\+?\d[\d\s().\-]{5,}\d)')
# "2027 - 2023" is two dates, not a phone number. Real numbers either carry a
# trunk/country prefix, a long unbroken run, or several groups of 2-5 digits.
YEAR_RANGE = re.compile(r'^\s*\+?(?:19|20)\d{2}\s*[-–—]?\s*(?:to\s*)?(?:19|20)?\d{2}\s*$', re.I)
THIS_YEAR = date.today().year


def _real_phone(raw):
    """True when a PHONEISH match is a phone number, not dates or quantities."""
    raw = raw.group(0) if hasattr(raw, 'group') else raw
    digits = re.sub(r'\D', '', raw)
    if len(digits) < 7 or YEAR_RANGE.match(raw):
        return False
    runs = re.findall(r'\d+', raw)
    longest = max((len(r) for r in runs), default=0)
    if longest >= 7:
        # one unbroken run: a phone, unless it is an obvious timestamp/id
        return raw.strip()[:1] in '+0' or 10 <= len(digits) <= 15
    # grouped (770-93-80391, 0803 917 7093): 2-5 digits per group
    return all(2 <= len(r) <= 5 for r in runs) and len(runs) >= 2


# ---------------------------------------------------------------- env
def load_env():
    vals = {}
    for path in ENV_FILES:
        resolved = os.path.normpath(path)
        if not os.path.exists(resolved):
            continue
        try:
            for line in open(resolved, encoding='utf-8-sig'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    vals[k.strip()] = v.strip()
        except Exception:
            pass
    return vals


def get_key(env, provider):
    return env.get(PROVIDERS[provider]['key'], '')


def get_model(env, provider):
    """Get model for provider, checking env override first."""
    env_key = f"{PROVIDERS[provider]['key']}_MODEL"
    if env_key in env and env[env_key]:
        return env[env_key]
    return PROVIDERS[provider]['model']


# ---------------------------------------------------------------- jobs
def fetch_job_text(link):
    """Fetch a job posting page and strip it down to readable text."""
    safe = re.sub(r'[^A-Za-z0-9]+', '_', link.split('/')[-1])
    cache = os.path.join(FETCH_DIR, safe + '.txt')
    if os.path.exists(cache):
        return open(cache, encoding='utf-8').read()
    try:
        r = requests.get(link, timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        r.raise_for_status()
        import bs4
        soup = bs4.BeautifulSoup(r.text, 'lxml')
        for el in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            el.decompose()
        text = re.sub(r'\n\s*\n+', '\n\n', soup.get_text('\n'))
        text = re.sub(r'[ \t]+', ' ', text)
        os.makedirs(FETCH_DIR, exist_ok=True)
        open(cache, 'w', encoding='utf-8').write(text)
        return text
    except Exception as e:
        print(f'  [warn] could not fetch job page: {e}')
        return ''


def find_job(fragment):
    d = json.load(open(SCANNED_PATH, encoding='utf-8'))
    for cat in ('nigerian_onsite', 'remote_global', 'other_matches'):
        for job in d.get('jobs', {}).get(cat, []) or []:
            hay = ' '.join([
                job.get('title', ''), job.get('company', ''),
                job.get('link', ''), job.get('source', '')]).lower()
            if fragment.lower() in hay:
                return job, cat
    return None, None


def resolve_job(args):
    title = company = link = location = desc = ''
    if args.url:
        link = args.url
        text = fetch_job_text(link)
        first = [l.strip() for l in text.splitlines() if l.strip()][:1]
        title = first[0] if first else 'Job posting'
        desc = text
    elif args.job:
        job, cat = find_job(args.job)
        if not job:
            sys.exit(f'  [error] no job found matching: {args.job}')
        title = job.get('title', '')
        company = job.get('company', '')
        link = job.get('link', '')
        location = job.get('location', '')
        desc = job.get('description', '')
        if not desc and link:
            desc = fetch_job_text(link)
    elif args.text:
        desc = args.text
        first = [l.strip() for l in desc.splitlines() if l.strip()][:1]
        title = first[0] if first else 'Job posting'
    else:
        sys.exit('  [error] provide one of: --url | --job | --text')
    return {'title': title, 'company': company, 'link': link,
            'location': location, 'desc': desc}


# ---------------------------------------------------------------- CV picking
def cv_keywords(text, top=60):
    raw = re.findall(r'[A-Za-z][A-Za-z0-9.+#/-]{2,}', text.lower())
    counts = {}
    for w in raw:
        if w in STOPWORDS or len(w) < 3:
            continue
        counts[w] = counts.get(w, 0) + 1
    return set(sorted(counts, key=counts.get, reverse=True)[:top])


def pick_best_cv(desc):
    files = glob.glob(os.path.join(CV_TEXT_DIR, '*.txt'))
    if not files:
        return None, set()
    jk = cv_keywords(desc)
    best, best_score = None, -1
    for f in files:
        cv = open(f, encoding='utf-8').read()
        score = len(jk & cv_keywords(cv))
        if score > best_score:
            best, best_score = f, score
    cv = open(best, encoding='utf-8').read()
    return best, cv, jk


# ---------------------------------------------------------------- CV hygiene
def cv_text_quality(text):
    """Score 0.0-1.0 for how cleanly a CV's text was extracted (1.0 = clean).

    The dominant tell is structural: a good extraction almost never starts a
    line with a lowercase letter, while a scrambled one is full of fragments
    that continue on the next line. Camel-case brands ("LinkedIn", "CloudWorld")
    also trip the glued-word check, so that signal is deliberately weak.
    Below ~0.75 we ask an LLM to repair the text before tailoring from it.
    """
    if not text or not text.strip():
        return 0.0
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", text)
    if len(words) < 25:
        return 0.0                      # too little text to judge

    lower_start = sum(1 for l in lines if l.strip()[:1].islower())
    frag = sum(1 for l in lines if len(l.strip()) < 4)
    glued = len(INNER_UPPER.findall(text))
    punct = len(INNER_PUNCT.findall(text))
    phones = [m.group(0) for m in PHONEISH.finditer(text) if _real_phone(m)]
    bad_phone = sum(1 for p in phones if len(re.sub(r'\D', '', p)) < 7)
    letter_phone = len(re.findall(r'\b[A-Za-z]{1,3}\s?\d{4,}', text))

    penalty = (1.3 * lower_start / len(lines)
               + 0.6 * frag / len(lines)
               + 0.10 * min(glued / 8, 1)
               + 0.5 * punct / max(len(words) / 20, 1)
               + 0.05 * bad_phone
               + 0.03 * letter_phone)
    return max(0.0, min(1.0, 1.0 - penalty))


def needs_repair(text, threshold=0.75):
    return cv_text_quality(text) < threshold


def protected_fields(cv):
    """Identity/contact details that must survive tailoring byte-for-byte."""
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', cv)
    phones, seen = [], set()
    for m in PHONEISH.finditer(cv):
        if not _real_phone(m):
            continue
        raw = m.group(0).strip()
        digits = _digits(raw)
        if digits in seen:
            continue
        seen.add(digits)
        phones.append({'text': raw, 'digits': digits})
    urls = re.findall(r'(?:https?://|www\.)[^\s,;)]+', cv)
    name = ''
    for line in cv.splitlines():
        if line.strip():
            name = line.strip()
            break
    return {'name': name, 'emails': emails, 'phones': phones, 'urls': urls}


def _digits(value):
    return re.sub(r'\D', '', value)


def _fix_dates(text):
    """Drop impossible years and repair reversed ranges like '2027 - 2023'."""
    issues = []
    def _clean_year(m):
        year = int(m.group(0))
        if year > THIS_YEAR:
            issues.append(f'removed impossible year {year}')
            return ''
        return m.group(0)
    text = re.sub(r'\b((?:19|20)\d{2})\b', _clean_year, text)
    text = re.sub(r'(?<=[\w)])\s+[-–—]\s+(?=\d{4}\b)', ' ', text)   # orphaned dash
    text = re.sub(r'[ \t]+[-–—][ \t]*$', '', text, flags=re.M)      # trailing dash

    def _range(m):
        a, b = m.group(1), m.group(2)
        if int(b) < int(a):
            issues.append(f'reordered reversed date range {a}-{b}')
            return f'{b} - {a}'
        return m.group(0)
    return re.sub(r'\b((?:19|20)\d{2})\s*[-–—]+\s*(?:to\s+)?((?:19|20)\d{2})\b',
                  _range, text), issues


def enforce_protected(text, protected):
    """Make sure tailoring never invents contact details or impossible dates.

    The LLM regroups digits when it rewrites a CV (08060075844 became
    080-6007-5844). Any number in the output that does not exist in the source
    CV is snapped back to the source spelling, or removed if it matches nothing.
    Returns (text, issues).
    """
    issues = []
    source = {p['digits']: p['text'] for p in protected.get('phones', [])}
    if source:
        def _phone(m):
            raw = m.group(0).strip()
            if not _real_phone(m):
                return raw
            digits = _digits(raw)
            if not digits:
                return raw
            if digits in source:
                canonical = source[digits]
                if canonical != raw:
                    issues.append(f'renormalised phone {raw} -> {canonical}')
                return canonical
            # same number, regrouped by the model -> restore the original spelling
            for known_digits, known_text in source.items():
                if len(known_digits) == len(digits) and _similar(known_digits, digits) >= 0.8:
                    issues.append(f'restored phone {raw} -> {known_text}')
                    return known_text
            issues.append(f'removed unrecognised phone "{raw}"')
            return ''
        text = PHONEISH.sub(_phone, text)
    for email in protected.get('emails', []):
        if email in text:
            continue
        stem = re.split(r'[@.]', email)[0]
        if len(stem) > 3 and stem.lower() in text.lower():
            issues.append(f'email {email} rewritten by the model')
    text, date_issues = _fix_dates(text)
    issues.extend(date_issues)
    return re.sub(r'[ \t]{2,}', ' ', text), issues


def _similar(a, b):
    """Digit-sequence similarity: same number, possibly shifted or regrouped."""
    if not a or not b or abs(len(a) - len(b)) > 1:
        return 0.0
    if a == b:
        return 1.0
    same = sum(1 for x, y in zip(a, b) if x == y)
    shift = sum(1 for i in range(len(a)) if i + 1 < len(b) and a[i] == b[i + 1])
    return max(same, shift) / max(len(a), len(b))


REPAIR_RULES = """
The text below is the TEXT LAYER of a CV pulled out of a PDF or a scan. The
extraction scrambled it: words split across lines, letters swapped, a
contact-details box dumped into the middle, punctuation inside words.

Repair it and return ONLY the cleaned CV as plain text:
1. Fix broken, split or glued words using context ("resoWing" -> "resolving",
   "Custorner" -> "Customer"). Never change what the CV actually says.
2. Keep every fact exactly as written: names, employers, job titles, degrees,
   dates, phone numbers, emails, references. Phone numbers, emails and names
   must be reproduced CHARACTER FOR CHARACTER - never re-group, re-space or
   re-format a phone number, and never drop a digit.
3. Do not add, remove or embellish any skill, duty, employer, date or number.
4. Do not invent missing facts and do not create new sections. If a fragment is
   unreadable, keep only the readable part.
5. Repair impossible dates: a year in the future, or a range that ends before it
   starts. Use the most plausible reading the rest of the CV supports; if
   nothing supports a correction, drop that year rather than guess.
6. Join lines that were split mid-sentence. Keep the original section headings
   and the original order of sections.
7. Plain text only. No markdown, no commentary, no code fences, no "here is".
"""


def repair_cv_text(text, provider=None, env=None):
    """LLM-repair a garbled CV text. Returns (clean_text, notes).

    Falls back to the original text whenever the repair looks destructive, so
    a bad model response can never eat a customer's CV.
    """
    env = env if env is not None else load_env()
    chosen = decide_provider(env, provider)
    if not chosen:
        return text, ['no LLM key available - CV text left as extracted']
    prompt = (f'{REPAIR_RULES}\n---\nEXTRACTED CV TEXT:\n{text[:12000]}')
    for p in [chosen] + [x for x in ('gemini', 'groq', 'openrouter', 'openai') if x != chosen]:
        if not get_key(env, p):
            continue
        try:
            fixed = tailor(env, prompt, p)
        except Exception as e:
            print(f'  [warn] CV repair via {p} failed: {str(e)[:160]}')
            continue
        if not fixed or not fixed.strip():
            continue
        fixed = sanitize_text(fixed)
        before, after = protected_fields(text), protected_fields(fixed)
        if len(fixed.split()) < 0.5 * len(text.split()):
            print('  [warn] CV repair looked destructive - keeping the extracted text')
            return text, [f'{p} repair dropped half the text - kept original']
        lost = [p2['digits'] for p2 in before['phones'] if p2['digits'] not in
                {q['digits'] for q in after['phones']}]
        if lost:
            print('  [warn] CV repair lost a phone number - keeping the extracted text')
            return text, [f'{p} repair lost phone {lost[0]} - kept original']
        quality = cv_text_quality(fixed)
        return fixed, [f'repaired with {p} '
                        f'(quality {cv_text_quality(text):.2f} -> {quality:.2f})']
    return text, ['all LLM repair attempts failed - CV text left as extracted']


# ---------------------------------------------------------------- LLM
# Both providers return token counts in the response body and both were throwing
# them away, so there was no way to bill or cap LLM spend. Tally them here and
# let the caller drain the accumulator with take_token_usage().
_TOKEN_TALLY = {'tokens': 0, 'calls': 0}


def _record_tokens(total):
    """Add a provider-reported token count to the tally. Tolerant of junk."""
    try:
        n = int(total)
    except (TypeError, ValueError):
        return
    if n > 0:
        _TOKEN_TALLY['tokens'] += n
        _TOKEN_TALLY['calls'] += 1


def take_token_usage():
    """Return {'tokens': n, 'calls': n} for LLM work done so far and reset it.

    Reset on read so each tailored CV is charged for its own calls rather than
    the running total of the whole batch.
    """
    out = dict(_TOKEN_TALLY)
    _TOKEN_TALLY['tokens'] = 0
    _TOKEN_TALLY['calls'] = 0
    return out


def build_prompt(job, cv, cover):
    head = (f'Job title: {job["title"]}\n'
            + (f'Company: {job["company"]}\n' if job['company'] else '')
            + (f'Location: {job["location"]}\n' if job['location'] else ''))
    jd = job['desc'][:6000]
    keep = protected_fields(cv)
    locked = []
    if keep['name']:
        locked.append(f'Name: {keep["name"]}')
    locked += [f'Phone: {p["text"]}' for p in keep['phones']]
    locked += [f'Email: {e}' for e in keep['emails']]
    locked += [f'Link: {u}' for u in keep['urls']]
    locked_block = ('\n'.join(locked) if locked else '(none found in the CV)')
    rules = """
RESUME RULES (non-negotiable):
1. NEVER invent employers, dates, degrees, certifications, skills, projects, or
   numbers that are not already in the CV below. No fabrication of any kind.
2. Rephrase, reorder, and emphasize EXISTING content only so it matches the job.
3. Use the job posting's exact keywords where they truthfully describe content
   already present in the CV.
4. The VERBATIM BLOCK below must be copied character for character. Never
   re-group, re-space, re-punctuate or re-format a phone number, never change a
   name spelling, and never drop or add a digit.
5. Dates must be copied from the CV too. Never write a year that is not in the
   CV, and never write a range that ends before it starts.
6. Output only the rewritten resume in plain text, no preamble or explanation.
7. Keep it roughly one page: tight summary, grouped skills, experience bullets
   that mirror job keywords, education, certifications.
"""
    if cover:
        rules += """
8. THEN, separated by a single blank line and the marker "---COVER LETTER---",
   write one professional cover letter (3 short paragraphs) using the SAME rules.
   Never mention a skill, employer or number that is not in the CV above.
"""
    return (f'{head}\nJOB DESCRIPTION:\n{jd}\n\n---\nCURRENT CV:\n{cv[:8000]}\n\n'
            f'---\nVERBATIM BLOCK (copy exactly, do not reformat):\n{locked_block}\n\n{rules}')


def call_gemini(env, prompt, model):
    key = get_key(env, 'gemini')
    url = (f'https://generativelanguage.googleapis.com/v1beta/models/{model}'
           f':generateContent?key={key}')
    body = {'contents': [{'parts': [{'text': prompt}]}]}
    r = requests.post(url, json=body, timeout=120)
    if r.status_code == 429 or 'candidates' not in r.text:
        if 'model' in r.text.lower() and 'not found' in r.text.lower():
            return None  # model name wrong; caller falls back
        raise RuntimeError(f'Gemini {r.status_code}: {r.text[:400]}')
    data = r.json()
    _record_tokens((data.get('usageMetadata') or {}).get('totalTokenCount'))
    return data['candidates'][0]['content']['parts'][0]['text']


def call_openai_compat(env, provider, prompt):
    key = get_key(env, provider)
    cfg = PROVIDERS[provider]
    base = {'groq': 'https://api.groq.com/openai/v1',
            'openrouter': 'https://openrouter.ai/api/v1',
            'openai': 'https://api.openai.com/v1'}[provider]
    r = requests.post(f'{base}/chat/completions',
                      headers={'Authorization': f'Bearer {key}'},
                      json={'model': cfg['model'], 'temperature': 0.4,
                            'messages': [{'role': 'user', 'content': prompt}]},
                      timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f'{provider} {r.status_code}: {r.text[:400]}')
    data = r.json()
    usage = data.get('usage') or {}
    _record_tokens(usage.get('total_tokens')
                   or (usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0)))
    return data['choices'][0]['message']['content']


def tailor(env, prompt, provider):
    """One LLM round-trip. Provider-reported tokens are tallied; if the
    provider gave no usage block (or the call failed after the request was
    sent) fall back to a rough character estimate so the budget still moves."""
    before = _TOKEN_TALLY['tokens']
    model = get_model(env, provider)
    try:
        if provider == 'gemini':
            out = call_gemini(env, prompt, model)
        else:
            out = call_openai_compat(env, provider, prompt)
    except Exception:
        # The request went out, so charge for it even though we never saw a
        # token count - under-reporting here is how the cap gets bypassed.
        _record_tokens(_estimate_tokens(prompt, ''))
        raise
    if out is None:
        # call_gemini returns None only when the provider rejected the request
        # outright (e.g. unknown model). Nothing was generated, so charging an
        # estimate would bill the customer for a config error.
        return out
    if _TOKEN_TALLY['tokens'] == before:
        _record_tokens(_estimate_tokens(prompt, out))
    return out


def _estimate_tokens(prompt, completion):
    """Rough token count (~4 chars/token) for when no usage block is returned."""
    return (len(prompt or '') + len(completion or '')) // 4


def decide_provider(env, requested):
    order = [requested] if requested else ['gemini', 'groq', 'openrouter', 'openai']
    for p in order:
        if get_key(env, p):
            model = get_model(env, p)
            print(f'  [LLM] Selected provider: {p} (model: {model})')
            return p
    print('  [LLM] No valid provider found - check API keys')
    return None


# ---------------------------------------------------------------- local fallback
def local_tailor(job, cv, jk):
    """No-LLM fallback: reorder skills so matches come first, inject summary."""
    m = re.search(r'(PROFESSIONAL SUMMARY:?.*?)(TECHNICAL SKILLS:?|PROFESSIONAL CERTIFICATIONS:?)$',
                  cv, flags=re.I | re.S)
    matched = sorted(jk, key=len, reverse=True)[:14]
    note = (f'  [tools-local] no API key set - using local keyword reorder '
            f'(matched: {", ".join(matched[:6])}...)')
    return cv, note


# ---------------------------------------------------------------- output
def safe_name(job):
    base = job['company'] or job['title'] or 'job'
    return re.sub(r'[^A-Za-z0-9]+', '_', base).strip('_')


def sanitize_text(text):
    """Strip markdown/AI-format artifacts so the CV is plain ATS text."""
    text = text.replace('**', '')
    text = re.sub(r'[ \t]+$', '', text, flags=re.M)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def tailor_job(job, base_cv=None, cover=False, provider=None, force=False,
               out_dir=OUT_DIR, cv_prefix=''):
    """Tailor one base CV to one job. Returns {'cv': path, 'letter': path or None}.

    job       : dict with title/company/location/link/description
    base_cv   : absolute path to the master CV text, or None to auto-pick.
    cv_prefix : optional string added to output filenames (e.g. a customer id).
    """
    os.makedirs(out_dir, exist_ok=True)
    if base_cv:
        cv = open(base_cv, encoding='utf-8').read()
        jk = cv_keywords(cv)
    else:
        base_cv, cv, jk = pick_best_cv(job.get('desc') or job.get('title'))

    if not job.get('desc') and job.get('link'):
        job = dict(job, desc=fetch_job_text(job['link']))

    name = (cv_prefix or '') + safe_name(job)
    out_cv = os.path.join(out_dir, f'{name}_tailored_cv.txt')
    out_letter = os.path.join(out_dir, f'{name}_cover_letter.txt')
    result = {'cv': out_cv, 'letter': out_letter if os.path.exists(out_letter) else None,
              'qc': []}

    if not force and os.path.exists(out_cv):
        print(f'  [skip] already tailored -> {os.path.basename(out_cv)}')
        return result

    env = load_env()
    chosen = decide_provider(env, provider)
    if chosen:
        prompt = build_prompt(job, cv, cover)
        attempts = [provider] if provider else ['gemini', 'groq', 'openrouter', 'openai']
        text = None
        for p in attempts:
            if not get_key(env, p):
                continue
            print(f'  LLM      : {p} ({PROVIDERS[p]["model"]})')
            for _ in range(2):
                try:
                    text = tailor(env, prompt, p)
                    if text is not None:
                        break
                    text = None
                except Exception as e:
                    print(f'  [warn] {p} failed: {str(e)[:160]}')
                    time.sleep(2)
                    continue
            if text is not None:
                break
        if text is not None:
            letter = None
            if cover and '---COVER LETTER---' in text:
                res, letter = text.split('---COVER LETTER---', 1)
                text = res.strip()
                letter = letter.strip()
            text, issues = enforce_protected(sanitize_text(text), protected_fields(cv))
            open(out_cv, 'w', encoding='utf-8').write(text)
            result['qc'] = issues
            for issue in issues:
                print(f'  [qc]     : {issue}')
            if letter:
                letter, letter_issues = enforce_protected(sanitize_text(letter),
                                                         protected_fields(cv))
                open(out_letter, 'w', encoding='utf-8').write(letter)
            print(f'  wrote    : {os.path.basename(out_cv)}')
            if letter:
                print(f'  wrote    : {os.path.basename(out_letter)}')
            result['letter'] = out_letter if letter else None
            return result

    cv_out, note = local_tailor(job, cv, jk)
    print(note)
    open(out_cv, 'w', encoding='utf-8').write(cv_out)
    print(f'  wrote    : {os.path.basename(out_cv)}')
    return result


def main():
    ap = argparse.ArgumentParser(description='Tailor your CV to a specific job')
    ap.add_argument('--url', help='job posting URL')
    ap.add_argument('--job', help='job link or title fragment from scanned_jobs.json')
    ap.add_argument('--text', help='paste the job title + description directly')
    ap.add_argument('--cover', action='store_true', help='also write a cover letter')
    ap.add_argument('--provider', choices=list(PROVIDERS), help='force an LLM provider')
    ap.add_argument('--base', help='force a base CV file name in cv_text/ (e.g. CV_Cloud_AWS_ATS.txt)')
    ap.add_argument('--force', action='store_true', help='re-run even if output exists')
    args = ap.parse_args()

    job = resolve_job(args)
    print(f'  job      : {job["title"]}')
    if job['company']:
        print(f'  company  : {job["company"]}')
    base_cv = os.path.join(CV_TEXT_DIR, args.base) if args.base else None
    if args.base and not os.path.exists(base_cv):
        sys.exit(f'  [error] --base file not found: {args.base}')
    result = tailor_job(job, base_cv=base_cv, cover=args.cover,
                        provider=args.provider, force=args.force)
    if result['letter']:
        print('  ---------- cover letter preview (first 12 lines) ----------')
        safe = open(result['letter'], encoding='utf-8').read()
        safe = safe.encode('ascii', 'replace').decode('ascii')
        print('\n'.join(safe.splitlines()[:12]))
    print('  ---------- preview (first 30 lines) ----------')
    safe = open(result['cv'], encoding='utf-8').read()
    safe = safe.encode('ascii', 'replace').decode('ascii')
    print('\n'.join(safe.splitlines()[:30]))


if __name__ == '__main__':
    main()
