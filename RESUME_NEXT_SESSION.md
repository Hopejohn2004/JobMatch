# RESUME HERE — JobMatch product state (saved 2026-09-26)

## Project
Turn Hope's personal job toolkit (`Hope\Jobs` original) into a sellable product:
customer tells the system what job they want (or uploads their CV) -> system scans
13 job sources, filters by location/keywords, LLM-tailors their CV (+optional cover
letter) to top matches -> served as download links from a phone dashboard.

PRODUCT CODE LIVES IN THIS FOLDER: `C:\Users\nyong\Downloads\Hope\JobMatch`
DO NOT TOUCH ORIGINAL: `C:\Users\nyong\Downloads\Hope\Jobs` (Hope's personal pipeline)

## Credentials / Keys
- Admin login (dashboard gate): `HopeAdmin2026`  (file: web_admin.env)
- Send PIN (protects AI spend, needed for Scan+tailor): `311759`  (file: web_pin.env)
- API keys: in `C:\Users\nyong\Downloads\Hope\Ideas\Twitter\x-llm-bot\.env`
  (GEMINI, GROQ, OPENROUTER all work; OPENAI has ZERO credits)
- Working LLM models (verified):
  - Gemini: gemini-3.6-flash (2.5-flash is 404 for new users; 3.6 gives transient 503s
    roughly every other call - the provider fallback absorbs it, just noisy)
  - Groq: openai/gpt-oss-120b (llama-3.3-70b-versatile is 404)
  - OpenRouter free: google/gemma-4-31b-it:free (deepseek free unavailable)
  - Fallback order in cv_tailor.py: gemini -> groq -> openrouter -> openai -> local

## How to run
```
cd C:\Users\nyong\Downloads\Hope\JobMatch
python web_app.py
```
Open http://127.0.0.1:5000 -> login (HopeAdmin2026) -> 🧑💼 Find tab.
Server uses threaded=True (single-threaded Flask used to freeze during long scans).

## Architecture
- job_scraper.py: 13+ sources, FAST mode (JOBMATCH_FAST=1 or job_scraper.FAST=True)
  makes prod scan ~170s. web_app run_script timeout = 420s, so a second scan pass
  would not fit - widen recall with keywords, never by scanning twice.
- customer_engine.py: product engine. CLI subcommands: profile|cv|scan|tailor|run.
  Writes: data/customer_profile.json, data/customer_cv.txt, data/customer_results.json,
  and data/customer_cv_raw.txt (pre-repair copy of an uploaded CV).
- cv_tailor.py: tailor_job() per-job CV rewrite. Reads env from cv_tailor.env then
  ..\Ideas\Twitter\x-llm-bot\.env. sanitize_text() strips markdown.
- web_app.py: routes /api/customer* (POST profile/cv/run/tailor, CV text), /files/<name>,
  /api/login /api/logout /api/auth_state /api/status_setup. Session-auth gate blocks
  /api/* and /files/* with 401 unless logged in. PIN-gates run/tailor (LLM spend).
- web_dashboard.html: mobile-first. Tabs New/Jobs/Tracker/Emails/🧑💼 Find.

## Data-integrity layer added 2026-09-26 (do not remove, this was a real bug)
Uploaded PDFs often have a SCRAMBLED text layer (pypdf gave "Custorner",
"resoWing", "B.A. Linguistios"), and the LLM then copied the garble into
customer-facing CVs - including INVENTED phone numbers (08060075844 became
080-6007-5844) and impossible dates (2027-2023).
- customer_engine.extract_cv_text(): extracts with pypdf AND pymupdf AND tesseract OCR,
  scores each with cv_tailor.cv_text_quality(), keeps the best.
- customer_engine._should_repair(): PDF/.doc always go through the LLM repair pass
  (once per upload, then cached in customer_cv.txt). txt/md/docx extract exactly and
  are trusted. A quality heuristic alone CANNOT tell a scrambled text layer from a
  clean PDF that hard-wraps mid-word, and we measured that a dictionary-based
  detector does not separate them either - hence format-driven, not score-driven.
- cv_tailor.repair_cv_text(): repairs garble with a no-fabrication prompt, then
  REJECTS the repair if it dropped half the text or lost a phone number.
- cv_tailor.enforce_protected(): runs on EVERY written CV + cover letter. Verbatim
  block (name/phones/emails/links) is injected into the prompt, and any phone in
  the output that is not in the source is snapped back to the source spelling or
  removed; future years and reversed ranges are repaired. Issues surface as `qc` in
  data/customer_results.json and print as "[qc] ..." in the run log.
- Re-validated: Precious's real CV went 0.38 -> 0.84 quality, zero qc issues,
  no invented skills, phones byte-identical to the source.

## Matching quality layer added 2026-09-26
- job_scraper.compute_score() no longer hardcodes IT keywords. It scores against the
  ACTIVE TARGET_KEYWORDS (which customer_engine swaps per customer), title hits worth
  3x description hits. Old hardcoded tech lists made a customer-service profile score
  5-23 on identical-quality jobs.
- job_scraper.scrape_weworkremotely(): WWR titles are "Company: Role" - company and the
  real region were being thrown away (blank company, vague "Remote"). Now parsed.
- customer_engine.rank_jobs(): fit = keyword_coverage*10 + min(score,60)*0.1. Coverage
  dominates because the legacy stored scores are unbounded and tech-biased.
- customer_engine.location_verdict(): for a "remote" preference, drops jobs that are only
  open to one foreign country ("Remote - South Africa (Gauteng / Cape Town)") or that
  require offshore hours ("Remote (Worldwide) - Working East Coast Hours"), with the
  reason printed as [skip]. Home country = profile `country` (default nigeria).
- customer_engine.SERVICE_SYNONYMS: widens scan recall for thin keyword lists without a
  second scan (see the 420s timeout note above). 12 -> 19 candidates for Precious.

## Verified working (2026-09-26)
- Full CLI run: scan + tailor, 3 remote jobs, 3 CVs + 3 cover letters, all qc clean.
- Full web API test: unauthed /api/* and /files/* -> 401; wrong admin -> 401; correct
  admin -> 200; wrong PIN on run AND tailor -> 401; correct PIN -> run executes;
  /files/ serves the CVs (200, ~2.7KB); path traversal -> 404; logout re-engages gate.
- Stale 9/23+9/25 customer outputs (20 files, containing the invented-phone bug) moved to
  archive/customer_runs_pre_fix/. Unnumbered files there are the personal pipeline - keep.

## Test data currently in DB
- profile "Precious Syl Vester Edward", remote, keywords = customer service / support /
  relations / client service / virtual assistant / appointment scheduling.
  CV = My CV_Resume.pdf (repaired; quality 0.84). Her original PDF is NOT on disk - she
  uploaded it from her phone, so re-upload is needed to re-test ingestion end to end.
- 3 results: Kobie Marketing (33), Warehance (17), VXI Global Solutions (29, filler).

## Status / Next steps
1. [DONE] Reusable scanner + customer_engine + cv_tailor + dashboard Find tab + login gate
2. [DONE] Login gate, threaded server, data-integrity layer, matching-quality layer
3. [NEXT] Biggest constraint is now SUPPLY, not code: for a remote customer-service
   profile the global aggregators only yield ~3 genuinely applicable remote roles
   (16 of 19 candidates were onsite Nigerian jobs). Next moves, in order:
   a. Add remote-first sources (RemoteOK/WWR are thin; consider Arbeitnow/S Remotive
      filters, jobgether, weworkremotely region feeds, African remote boards).
   b. Cloudflare Tunnel for a live demo link -> landing page + Paystack.
   c. Multi-customer profiles (engine is single-profile by design; profile file is the
      only thing that needs keying).
   d. Fold in the x-llm-bot router so one place owns provider choice + spend caps.
4. [LATER] Original: extend career_crawler.py so product can crawl ANY company career page
   (wire into customer_engine FAST path).

## Other projects (exist, do not rebuild)
- Ideas\Twitter\x-llm-bot (full X bot, LLM client layer + tests) — source of usable keys
- Ideas\ict-knowledge-engine-phase1 (separate, running uvicorn :8001)
- Bet Project / Bet_Project_PHASE6 (Poisson value betting; backtest gate NOT passed,
  keep as portfolio) — may be running in the background, check before starting
- Hustle\ (PC repair price list + Upwork profile docs)
