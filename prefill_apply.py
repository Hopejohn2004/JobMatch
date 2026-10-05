"""
SAFE FORM-PREFILL ASSISTANT for Hope John Sunday.

Opens a real Chrome window for a job application URL, automatically fills in
your details on visible forms (heuristic field matching), and PAUSES. You review,
fix CAPTCHAs, and click Submit yourself. It NEVER clicks submit.

Usage:
  python prefill_apply.py --url "https://jobs.example.com/apply"
  python prefill_apply.py --url "https://jobs.example.com/apply" --cv cv_pdfs/Hope_John_Sunday_CV_IT_Support.pdf

Controls in the terminal:
  Enter  -> run a fill pass on the current page/frame (run again after each step)
  q      -> quit

Logins are saved per-site in .browser_profile/ so you only authenticate once.
"""
import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent

PROFILE = {
    "full_name": "Hope John Sunday",
    "first_name": "Hope",
    "last_name": "Sunday",
    "email": "hopejohn204@gmail.com",
    "phone": "+234 813 834 9412",
    "city": "Uyo",
    "country": "Nigeria",
    "address": "Uyo, Akwa Ibom State, Nigeria",
    "linkedin": "linkedin.com/in/hope-sunday-3170a7403",
    "github": "github.com/Hopejohn2004",
    "degree": "B.Sc. Computer Science",
    "school": "University of Uyo",
    "years_experience": "1",
    "start": "Immediately",
    "current_role": "IT Support Specialist",
    "pitch": ("Computer Science graduate and IT support specialist with hands-on "
              "experience in Windows/Linux administration, networking (TCP/IP, DNS, DHCP), "
              "user account management, and Microsoft 365 / Google Workspace support. "
              "Currently pursuing AWS Cloud Practitioner and Google IT Support Professional "
              "certifications, with practical project experience in cloud and cybersecurity "
              "including network intrusion detection research (CIC-IDS2017, scikit-learn). "
              "Available immediately and eager to grow with your team."),
}

DEFAULT_CV = str(BASE / "cv_pdfs" / "Hope_John_Sunday_CV_ATS.pdf")

RULES = [
    (r"resume|curriculum|upload.*cv|\bcv\b", "file"),
    (r"first.?name|forename", "first_name"),
    (r"last.?name|surname|family.?name", "last_name"),
    (r"full.?name|your.?name|applicant.?name|\bname\b", "full_name"),
    (r"e-?mail|email", "email"),
    (r"\bphone\b|mobile|telephone|contact.?no", "phone"),
    (r"linkedin", "linkedin"),
    (r"git(?:hub)?|portfolio|\burl\b|website", "github"),
    (r"\bcity\b|\btown\b", "city"),
    (r"country|nationality", "country"),
    (r"address|street|where do you live|\bstate\b", "address"),
    (r"degree|qualification|education.?level", "degree"),
    (r"university|school|college|institution", "school"),
    (r"years?.?exp|experience.*year|exp.*year", "years_experience"),
    (r"start.?date|availability|notice|when can you start", "start"),
    (r"current.?role|job.?title|position.*apply|role.*title", "current_role"),
    (r"summary|about.?you|tell.*yourself|cover.?letter|bio|introduce", "pitch"),
]

TEXT_FIELDS = {"full_name", "first_name", "last_name", "email", "phone", "city",
               "address", "linkedin", "github", "degree", "school",
               "years_experience", "start", "current_role"}


def match_field(el_id, el_name, el_placeholder, el_label, el_autocomplete):
    hay = " ".join([el_id, el_name, el_placeholder, el_label, el_autocomplete]).lower()
    for pattern, field in RULES:
        if re.search(pattern, hay):
            return field
    return None


def field_value(field):
    v = PROFILE.get(field, "")
    if field in ("linkedin", "github"):
        return "https://" + v
    return v


def fill_pass(page, cv_path):
    filled = []
    for frame in page.frames:
        for el in frame.locator("input, textarea, select").all():
            try:
                if not el.is_visible():
                    continue
                tag = el.evaluate("e => e.tagName").lower()
                el_type = el.get_attribute("type") or "text"
                if el_type == "file":
                    el.set_input_files(cv_path)
                    filled.append(f"CV attached: {Path(cv_path).name}")
                    continue
                if el_type in ("hidden", "submit", "button", "checkbox", "radio", "password"):
                    continue
                label = ""
                try:
                    label = el.locator("xpath=ancestor::label").inner_text(timeout=200)
                except Exception:
                    pass
                if not label:
                    try:
                        el_id = el.get_attribute("id")
                        if el_id:
                            label = frame.locator(f'label[for="{el_id}"]').inner_text(timeout=200)
                    except Exception:
                        pass
                field = match_field(
                    el.get_attribute("id") or "",
                    el.get_attribute("name") or "",
                    el.get_attribute("placeholder") or "",
                    (label or "")[:120],
                    el.get_attribute("autocomplete") or "",
                )
                if not field:
                    continue
                value = field_value(field)
                if not value:
                    continue
                if tag == "select":
                    opts = el.locator("option").all()
                    texts = [o.inner_text(timeout=500).strip() for o in opts]
                    target = next((t for t in texts if t.lower() == value.lower()), None)
                    if target is None:
                        target = next((t for t in texts if value.lower() in t.lower()), None)
                    if target:
                        try:
                            el.select_option(label=target)
                        except Exception:
                            el.select_option(index=texts.index(target))
                        filled.append(f"{field} -> {value}")
                    continue
                if tag == "textarea":
                    el.fill(value)
                else:
                    el.fill(value)
                el.evaluate("""e => e.style.border='2px solid #22c55e'""")
                filled.append(f"{field} -> {value}")
            except Exception:
                continue
    return filled


def main():
    ap = argparse.ArgumentParser(description="Safe form-prefill assistant (never auto-submits).")
    ap.add_argument("--url", default="", help="Job application URL to open")
    ap.add_argument("--cv", default=DEFAULT_CV, help="Path to the CV PDF to attach")
    args = ap.parse_args()

    if not Path(args.cv).exists():
        print(f"[ERROR] CV not found: {args.cv}")
        sys.exit(1)

    print("=" * 66)
    print("  SAFE FORM-PREFILL ASSISTANT - Never clicks submit.")
    print("  Profile loaded for:", PROFILE["full_name"])
    print("  CV:", Path(args.cv).name)
    print("=" * 66)
    print("  After the browser opens, navigate to the apply form, then press\n"
          "  Enter in THIS window to fill it. Press q + Enter to quit.\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BASE / ".browser_profile"),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if args.url:
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                print(f"[opened] {args.url}")
            except Exception as e:
                print(f"[warn] could not load page automatically: {e}")

        try:
            no_console = False
            while True:
                try:
                    line = input("> ").strip().lower()
                except EOFError:
                    no_console = True
                if no_console:
                    print("\n[Info] No interactive console attached - keeping the browser open.")
                    print("Fill in the browser, solve CAPTCHAs and submit yourself.")
                    print("Close the Chrome window when you are done - this window will exit then.")
                    try:
                        page.wait_for_close(timeout=6 * 60 * 60 * 1000)
                    except Exception:
                        pass
                    break
                if line in ("q", "quit", "exit"):
                    break
                filled = fill_pass(page, args.cv)
                if filled:
                    uniq = list(dict.fromkeys(filled))
                    print(f"  Filled {len(uniq)} field(s) - highlighted green in browser:")
                    for u in uniq:
                        print("   *", u)
                else:
                    print("  No matchable fields on the current page. Navigate to the form and press Enter again.")
                print("  Review + solve CAPTCHA + click Submit yourself. Press Enter to refill or q to quit.")
        finally:
            ctx.close()

    print("Done. Submitted applications are logged in your applications.csv when you update it.")


if __name__ == "__main__":
    main()
