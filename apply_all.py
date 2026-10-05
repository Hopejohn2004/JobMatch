"""
Walk-through auto-applier for all scheduled portal jobs, in ONE browser session.

Per job:
  - Opens the job URL
  - Auto-fills your details (green highlight) + attaches the right CV
  - PAUSES for YOU to review, solve CAPTCHA, and click Submit (default)
  - With --auto: clicks Submit automatically when NO CAPTCHA is detected,
    and pauses for you only when it finds a reCAPTCHA/hCaptcha or no button.

Controls (type in this window):
  Enter  -> refill the current form (use after moving between form steps)
  n      -> next job (after you submitted)
  q      -> exit altogether

Usage:  python apply_all.py [--auto]
"""
import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright

from prefill_apply import PROFILE, fill_pass  # reuse profile + filler

BASE = Path(__file__).resolve().parent
CSV = BASE / "applications.csv"

JOBS = [
    ("Web Developer Remote", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/957412/web-developer-remote-at-eba-eni-brand-architect-li.html"),
    ("IT Infrastructure Support Intern", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/it-infrastructure-support-intern-green-africa"),
    ("Network Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/network-engineer-teknowledge"),
    ("Cloud Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/cloud-engineer-moniepoint-2"),
    ("State Helpdesk Officer - Plateau", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-plateau-iita"),
    ("State Helpdesk Officer - Oyo", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-oyo-iita"),
    ("State Helpdesk Officer - Ogun", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-ogun-iita"),
    ("State Helpdesk Officer - Ebonyi", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-ebonyi-iita"),
    ("State Helpdesk Officer - Kaduna", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-kaduna-iita"),
    ("State Helpdesk Officer - Adamawa", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-adamawa-iita"),
    ("State Helpdesk Officer - Jigawa", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-jigawa-iita"),
    ("State Helpdesk Officer - Kano", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/state-helpdesk-officer-kano-iita"),
    ("Helpdesk / CAFM Operator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/helpdesk-cafm-operator-enugu-international-hospital-eih"),
    ("Information Technology It Officer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/949421/information-technology-it-officer-at-gruene-capita.html"),
    ("Network Support Engineer (Level 2)", "Remote", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/network-support-engineer-level-2-estream-networks-1"),
    ("Customer Support Officer", "Ibadan & Oyo State", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/whatsapp-customer-support-officer-qz5z0n"),
    ("Technical Support Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/technical-support-engineer-lopterra"),
    ("Network Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/network-engineer-nigerian-british-university"),
    ("Quality Assurance Specialist", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/quality-assurance-specialist-9knwm0"),
    ("Quality Assurance & Training Officer", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/head-of-business-development-strategic-partnerships-m0jnx2"),
    ("Service Desk Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/955823/service-desk-analyst-at-unified-payment-services-l.html"),
    ("Devops Engineer / Linux Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-linux-administrator-ehealth4everyone-12"),
    ("Desktop Support - FMN Holdings", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/desktop-support-fmn-holdings-flour-mills-of-nigeria-plc"),
    ("System Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/system-administrator-moniepoint-8"),
    ("System Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/system-administrator-multipro-consumer-products-limited"),
    ("System Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/system-administrator-federal-university-of-health-sciences-and-technology-tsafe-fuhsatt"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-payzeep-1"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-teknowledge-2"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-netzence-sustainability-limited"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-kredete-2"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-tezza-business-solutions-ltd-6"),
    ("DevOps Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/devops-engineer-data2bots"),
    ("Graduate Trainee (Environmental Specialist)", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/graduate-trainee-environmental-specialist-unique-botenv-nigeria-limited-2"),
    ("Junior Engineer (Field Support Engineer)", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/junior-engineer-field-support-engineer-estream-networks"),
    ("Web Developer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.myjobmag.com/job/web-developer-virtual-nation"),
    ("Full Stack Web Developer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.myjobmag.com/job/full-stack-web-developer-candlelight-foundation-for-children-with-special-needs"),
    ("Web Developer & Graphic Designer at a Reputable Company", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.myjobmag.com/job/web-developer-graphic-designer"),
    ("Full Stack Web Developer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.myjobmag.com/job/full-stack-web-developer-creativemansion"),
    ("Network Support Engineer", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/network-support-engineer-erp5jk"),
    ("System Administrator", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/system-administrator-6qv6wd"),
    ("Network, Cloud & Cybersecurity", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.jobberman.com/listings/network-cloud-cybersecurity-n9jd70"),
    ("IT Systems Administrator Lead", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/it-systems-administrator-lead-teknowledge"),
    ("Managed Security Services (MSS) Cybersecurity Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/managed-security-services-mss-cybersecurity-analyst-ethnos-cyber-limited"),
    ("Analyst, Technology Security Operations", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/analyst-technology-security-operations-stanbic-ibtc-5"),
    ("Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/data-analyst-nobzo-verse-limited"),
    ("Reinsurance Systems & Data Analyst", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/reinsurance-systems-data-analyst-jean-edwards-consulting"),
    ("Business Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/business-data-analyst-myrtle-management-consultants"),
    ("HR & Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/hr-data-analyst-coisco"),
    ("Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/data-analyst-thronos-technologies-limited-1"),
    ("Associate Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/associate-data-analyst-sproxil-1"),
    ("Operations Data Analyst, NYSC", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/operations-data-analyst-nysc-ge-2"),
    ("Data Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/data-analyst-vendorcredit"),
    ("Graduate Trainee (Sales & Digitization)", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/graduate-trainee-sales-digitization-multipro-consumer-products-limited"),
    ("Tincan Island Container Graduate Trainee Program 2026 Recruitment", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/tincan-island-container-at-graduate-trainee-program-2026-tincan-island-container-terminal"),
    ("2026 Julius Berger Commercial Graduate Trainee Programme", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/2026-julius-berger-commercial-graduate-trainee-programme-julius-berger"),
    ("Database Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/database-administrator-moniepoint-5"),
    ("Database Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/database-administrator-cavista-4"),
    ("Database Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/database-administrator-uridium-technologies"),
    ("Database Administrator (Oracle, MongoDB, Cassandra, MySQL)", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/database-administrator-oracle-mongodb-cassandra-mysql-bluechip-technologies-limited-1"),
    ("Database Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/database-administrator-mudiame-university"),
    ("IT Network Engineer", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/it-network-engineer-qzwrnz"),
    ("Network Engineer", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/network-engineer-0k86p6"),
    ("Junior Network Solutions Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/junior-network-solutions-engineer-9kngr7"),
    ("SOC Engineer", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/soc-engineer-5pzvnr"),
    ("Laravel/React Developer", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.jobberman.com/listings/laravelreact-developer-erx2nk"),
    ("Backend Software Engineer", "Abuja", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.jobberman.com/listings/backend-software-engineer-0k86x8-v1"),
    ("Software Engineer", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.jobberman.com/listings/software-engineer-java-z8zng9"),
    ("Graduate Trainee", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/graduate-trainee-qz550j"),
    ("Data Analyst", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/data-analyst-j65n7v"),
    ("Assignr LLC: Customer Support Specialist", "Remote", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://weworkremotely.com/remote-jobs/assignr-llc-customer-support-specialist-2"),
    ("Sticker Mule: Software engineer", "Remote", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://weworkremotely.com/remote-jobs/sticker-mule-software-engineer-3"),
    ("Junior Software Engineer", "Ibadan & Oyo State", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.jobberman.com/listings/junior-software-engineer-gmd92q"),
    ("Quality Assurance Manager", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/959848/quality-assurance-manager-at-seven-up-bottling-com.html"),
    ("Head Enterprise Applications Support", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/959727/head-enterprise-applications-support-at-fast-credi.html"),
    ("Backend Developer Php Laravel", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/959710/backend-developer-php-laravel-at-oneverify-limited.html"),
    ("Registration Area Technical Support (RATECH) Officer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/registration-area-technical-support-ratech-officer-inec"),
    ("Network Administrator II", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/961393/network-administrator-ii-at-fountain-university-os.html"),
    ("SOC Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/956039/soc-engineer-at-dangote-industries-limited.html"),
    ("Server Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/956118/server-administrator-at-dangote-industries-limited.html"),
    ("CRM Administrator", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/961212/crm-administrator-at-zinance-limited-5-openings.html"),
    ("Site Reliability Engineer", "Remote", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://job-boards.eu.greenhouse.io/moniepoint/jobs/4784640101"),
    ("Cloud Network and Infrastructure Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.myjobmag.com/job/cloud-network-and-infrastructure-engineer-renmoney"),
    ("Infrastructure Engineer - Network or Server Specialism", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/infrastructure-engineer-network-or-server-specialism-network-led-contec-global-infotech-limited"),
    ("Network & Support Analyst", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/network-support-analyst-axxela"),
    ("Cloud Infrastructure Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Cloud_AWS.pdf",
     "https://www.jobberman.com/listings/cloud-infrastructure-engineer-k7p4jw"),
    ("Administrator, Database", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.myjobmag.com/job/administrator-database-stanbic-ibtc-1"),
    ("IT Administrator", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/it-administrator-456jq8"),
    ("Security Operations Secops Engineer", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/960124/security-operations-secops-engineer-at-teknowledge.html"),
    ("IT Associate", "Remote", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://jobicy.com/jobs/145745-it-associate"),
    ("Full Stack Developer Remote", "Nigeria", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.hotnigerianjobs.com/hotjobs/961423/full-stack-developer-remote-at-dokitami.html"),
    ("Game Support Specialist", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://www.jobberman.com/listings/game-support-specialist-j6x47r"),
    ("Software Engineer", "Lagos", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://www.jobberman.com/listings/software-engineer-n904zz"),
    ("Graduate Customer Success Manager", "Remote", "cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf",
     "https://jobicy.com/jobs/153669-graduate-customer-success-manager"),
    ("Backend Software Engineer", "Remote", "cv_pdfs/Hope_John_Sunday_CV_Developer.pdf",
     "https://remoteOK.com/remote-jobs/remote-backend-software-engineer-airspace-link-1137409"),
]

# A submit button on is only auto-clicked when none of these CAPTCHA markers exist.
CAPTCHA_SELECTORS = [
    'iframe[src*="recaptcha"]',
    'iframe[src*="google.com/recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    '.g-recaptcha',
    '.h-captcha',
    'div[data-sitekey]',
    'input[name*="captcha"]',
]

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
    'button:has-text("Send")',
    'button:has-text("Continue")',
    'button:has-text("Next")',
]


def has_captcha(page):
    for frame in page.frames:
        for sel in CAPTCHA_SELECTORS:
            try:
                if frame.locator(sel).count() > 0:
                    return True
            except Exception:
                continue
    return False


APPLY_SELECTORS = [
    'a:has-text("Apply Now")',
    'a:has-text("Apply for this")',
    'a:has-text("Apply for")',
    'a:has-text("Apply")',
    'a[href*="/apply-now"]',
    'button:has-text("Apply Now")',
    'button:has-text("Apply")',
]


def is_search_ctl(el):
    for attr in ("aria-label", "title", "alt"):
        try:
            if "search" in (el.get_attribute(attr) or "").lower():
                return True
        except Exception:
            pass
    return False


def click_apply(page):
    """From a listing page, click the real Apply link (stage 1) then the form's
    Apply/Continue button (stage 2). Follows target=_blank popups. Returns the
    page (or popup) where the application form should now be present."""
    cur = page
    for stage in (1, 2):
        clicked = False
        try:
            for frame in cur.frames:
                for sel in APPLY_SELECTORS:
                    try:
                        n = min(frame.locator(sel).count(), 10)
                    except Exception:
                        continue
                    for i in range(n):
                        try:
                            el = frame.locator(sel).nth(i)
                            if not el.is_visible():
                                continue
                            href = el.get_attribute("href") or ""
                            if el.evaluate("e => e.tagName") == "A" and not href:
                                continue
                            if href.startswith("mailto:"):
                                continue
                            txt = ""
                            try:
                                txt = el.inner_text(timeout=500) or ""
                            except Exception:
                                pass
                            if el.evaluate("e => e.tagName") == "A" and "apply" not in (txt + href).lower():
                                continue
                            if is_search_ctl(el):
                                continue
                            try:
                                with page.expect_popup(timeout=2500) as pi:
                                    el.click()
                                new = pi.value
                                try:
                                    new.wait_for_load_state("domcontentloaded", timeout=20000)
                                except Exception:
                                    pass
                                new.wait_for_timeout(2500)
                                cur = new
                            except Exception:
                                try:
                                    el.click()
                                    cur.wait_for_load_state("domcontentloaded", timeout=15000)
                                except Exception:
                                    pass
                                cur.wait_for_timeout(2500)
                            clicked = True
                            break
                        except Exception:
                            continue
                    if clicked:
                        break
                if clicked:
                    break
        except Exception:
            break
        if not clicked:
            break
    return cur


def find_submit(page):
    for frame in page.frames:
        for sel in SUBMIT_SELECTORS:
            try:
                n = min(frame.locator(sel).count(), 8)
            except Exception:
                continue
            for i in range(n):
                try:
                    el = frame.locator(sel).nth(i)
                    if not el.is_visible():
                        continue
                    if is_search_ctl(el):
                        continue
                    return el
                except Exception:
                    continue
    return None


SUCCESS_TEXT = [
    "thank you", "thanks for applying", "application received", "application submitted",
    "received your application", "submitted successfully", "application sent",
    "your application has been", "we have received",
]
SUCCESS_URL = ["applied", "application-confirmation", "success", "thank-you"]


def verify_submitted(page):
    try:
        url = (page.url or "").lower()
        if any(k in url for k in SUCCESS_URL):
            return True
        text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        low = text.lower()
        return any(phrase in low for phrase in SUCCESS_TEXT)
    except Exception:
        return False


def auto_submit(page):
    if has_captcha(page):
        print("  [!] CAPTCHA widget detected - attempting submit anyway (safe: only marked applied if page confirms).")
    sub = find_submit(page)
    if sub is None:
        print("  [!] No submit button found yet - leaving job for manual review.")
        return False
    print("  Clicking submit (force) and checking for a success confirmation...")
    try:
        sub.click(force=True)
        page.wait_for_timeout(5000)
        if verify_submitted(page):
            print("  Submitted and confirmed by the page.")
            return True
        print("  Clicked submit but no clear success page - leaving unconfirmed.")
        return False
    except Exception as e:
        print(f"  [warn] submit click failed: {e}")
        return False


def run_auto(page, cv_full):
    prev = None
    for step in range(6):
        filled = fill_pass(page, cv_full)
        uniq = list(dict.fromkeys(filled))
        if filled:
            print(f"  Filled {len(uniq)} field(s) (green):")
            for u in uniq:
                print("   *", u)
        else:
            print("  No fields matched on this step.")
        if auto_submit(page):
            return True
        if not filled:
            print("  Nothing fillable and submit unconfirmed - stopping this job.")
            return False
        cur = sorted(uniq)
        if prev is not None and cur == prev:
            print("  Form state did not change after submit - stopping this job.")
            return False
        prev = cur
        print("  Step advanced - refilling any new fields and re-submitting...")
    print("  Gave up after 6 steps - leaving job for manual review.")
    return False


def log_line(msg):
    try:
        logpath = BASE / "logs" / "apply_all_runs.log"
        logpath.parent.mkdir(exist_ok=True)
        with open(logpath, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except Exception:
        pass


def already_applied(url):
    try:
        with open(CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("Apply Link") or "").strip() == url and \
                   (r.get("Status") or "").strip().upper() in ("APPLIED", "EMAILED", "WATCHLIST"):
                    return r["Status"].strip()
    except Exception:
        pass
    return None


def mark_applied(label, url):
    try:
        with open(CSV, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        today = date.today().isoformat()
        fu = (date.today() + timedelta(days=5)).isoformat()
        changed = 0
        for r in rows:
            if url and (r.get("Apply Link") or "").strip() == url and \
               (r.get("Status") or "").strip().upper() == "TO_APPLY":
                r["Status"] = "APPLIED"
                r["Date Applied"] = today
                r["Next Follow-up"] = fu
                changed += 1
        if changed:
            fieldnames = list(rows[0].keys())
            with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
            log_line(f"TRACKER: {label} -> APPLIED ({url})")
        else:
            log_line(f"TRACKER: no TO_APPLY row matched for {label} ({url})")
    except Exception as e:
        log_line(f"TRACKER: error updating {label}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Walk-through (or --auto) job applier.")
    ap.add_argument("--auto", action="store_true",
                    help="auto-fill AND auto-click Submit when no CAPTCHA is detected")
    ap.add_argument("--start", type=int, default=0, help="1-based index of first job to try")
    ap.add_argument("--max", type=int, default=0, help="max jobs to process in this run (0 = all)")
    args = ap.parse_args()

    mode = "AUTO-SUBMIT (CAPTCHA-aware)" if args.auto else "MANUAL SUBMIT (you click)"
    todo = JOBS[args.start - 1:] if args.start > 0 else JOBS
    if args.max > 0:
        todo = todo[:args.max]
    print("=" * 70)
    print(f"  WALK-THROUGH APPLIER - {len(todo)} of {len(JOBS)} jobs, ONE browser session")
    print("  Profile:", PROFILE["full_name"])
    print("  Mode:", mode)
    print("  Progress auto-saves to applications.csv + logs/apply_all_runs.log")
    print("=" * 70)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BASE / ".browser_profile"),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for idx, (label, loc, cv, url) in enumerate(todo, 1):
            cv_full = str(BASE / cv)
            st = already_applied(url)
            if st:
                print(f"\n===== [{idx}/{len(JOBS)}] {label} | {loc} =====")
                print(f"  SKIP - already {st} in tracker.")
                log_line(f"SKIP [{idx}/{len(JOBS)}] {label} already {st}")
                continue
            print(f"\n===== [{idx}/{len(JOBS)}] {label} | {loc} =====")
            log_line(f"OPEN [{idx}/{len(JOBS)}] {label} ({url})")
            try:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"[warn] could not open page: {e}")
                    log_line(f"WARN goto failed {label}: {e}")
                try:
                    page = click_apply(page)
                except Exception:
                    pass
                submitted_ok = False
                if args.auto:
                    submitted_ok = run_auto(page, cv_full)
                else:
                    filled = fill_pass(page, cv_full)
                    if filled:
                        uniq = list(dict.fromkeys(filled))
                        print(f"  Filled {len(uniq)} field(s) (green):")
                        for u in uniq:
                            print("   *", u)
                    else:
                        print("  No fields matched yet - may need to click 'Apply' on the page.")
                    print("  >> Review, solve CAPTCHA, and click SUBMIT yourself.")

                while True:
                    try:
                        cmd = input("     [Enter]=refill  [n]=next job  [q]=quit > ").strip().lower()
                    except EOFError:
                        cmd = "q"
                    if cmd == "q":
                        print("Quitting.")
                        log_line(f"QUIT at {label} - session ended early")
                        ctx.close()
                        return
                    if cmd == "n":
                        if args.auto and submitted_ok:
                            mark_applied(label, url)
                        elif args.auto:
                            print("  Not marked applied - left in TO_APPLY for your review.")
                            log_line(f"SKIP (unverified) {label}")
                        else:
                            mark_applied(label, url)
                        log_line(f"NEXT {label}")
                        break
                    filled = fill_pass(page, cv_full)
                    if filled:
                        print(f"  Refilled {len(filled)} field(s). Review + submit again if needed.")
                    else:
                        print("  Still nothing to fill - navigate to the form, then Enter or n.")
                    if args.auto:
                        submitted_ok = auto_submit(page)
            except Exception as e:
                print(f"  [error] job failed: {e}")
                log_line(f"ERROR {label}: {e}")
                try:
                    page.title(timeout=2000)
                except Exception:
                    print("  Browser is gone - ending session.")
                    log_line("BROWSER LOST - ending session")
                    break
        try:
            ctx.close()
        except Exception:
            pass
    print("\nDone. Progress was saved to applications.csv and logs/apply_all_runs.log")


if __name__ == "__main__":
    main()
