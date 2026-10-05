# JobMatch — Bug Register

Generated: 2026-10-04
Scope: full project, `C:\Users\nyong\Downloads\Hope\JobMatch`
Method: static inspection + live runtime probes against a throwaway SQLite DB.

**Reproduced before fixing.** Every "Reproduction" below is an actual observed
result, not an inference. Probe scripts live in `%TEMP%\opencode` and are
scratch only — the durable checks are the pytest regression tests.

Legend: **REAL BUG** / **REGRESSION** / **TECH DEBT** / **CODE QUALITY** / **FEATURE REQUEST**

---

## A. REAL BUGS

| ID | Sev | Component | Bug | Reproduction | Root Cause | Fix | Status |
|----|-----|-----------|-----|--------------|------------|-----|--------|
| B-01 | CRITICAL | web_app.py:117 | `/api/customers` is in `PUBLIC_ENDPOINTS`, so anonymous callers dump every customer row including `password_hash` | `GET /api/customers` unauthenticated → `200`, 5432 bytes, `password_hash='e08aa78a…'` | Auth allow-list built from a guess; `/api/customers` treated as public | FIX-01 | Fixed |
| B-02 | CRITICAL | web_app.py:145 | Live instance has **no** `web_admin.env`, so `SETUP_MODE` is `True` and `gate()` returns `None` (allow) for **every** `/api/*` path | `GET /api/customers` → 200; `GET /api/state` → 200 (233 KB tracker dump); `POST /api/import` → 200 (executed a script) | First-run mode fails open instead of closed | FIX-01 | Fixed |
| B-03 | CRITICAL | web_app.py:175 | Anyone can claim admin via `POST /api/status_setup` while setup mode is open | `POST /api/status_setup {"password":"attacker-chosen-pw"}` → `200 {'ok':True}` and the file was written to disk | `status_setup` is public and unprotected by locality | FIX-01 | Fixed |
| B-04 | CRITICAL | web_app.py:626 | **IDOR**: `_get_request_customer_id()` honours `?customer_id=` / `body.customer_id` with **no admin check** | Customer A reads B's profile, CV text, matches, applications, tailored CVs and **writes** B's profile. Observed `stored='HIJACKED BY ALICE'` | Comment says "fallback to admin authentication" but the `is_authed()` test was missing | FIX-02 | Fixed |
| B-05 | CRITICAL | web_app.py:627 | Same unauthenticated fallback in `_get_customer_id_legacy()` | `POST /api/customer/profile?customer_id=<bob>` as Alice → `{'ok':True}` | Same as B-04 | FIX-02 | Fixed |
| B-06 | CRITICAL | web_app.py:1479 | `PATCH /api/customers/<id>` has no admin check and splats caller JSON into `update_customer`, whose allow-list includes `password_hash` | Alice PATCHes Bob's `password_hash`, then logs in as Bob: `POST /auth/login` → `200 {'customer_id':2}`, `/api/me` → `bob@example.com` | No authorization check + over-broad field allow-list + `**data` passthrough | FIX-03 | Fixed |
| B-07 | HIGH | web_app.py:1445 | `GET /api/customers/<id>` returns the full row including `password_hash` to any authenticated customer | Alice GET Bob → keys include `password_hash` | `dict(customer)` returned unfiltered | FIX-03 | Fixed |
| B-08 | CRITICAL | customer_engine.py:319 | `POST /api/cv` and `/api/customer/cv` **always 500**: `TypeError: create_or_update_profile() got an unexpected keyword argument 'cv_source'` | `save_cv_bytes()` raised TypeError; CV row written (1) but request 500s and profile never updated | `database.create_or_update_profile()` signature lacks `cv_source`/`cv_quality`/`cv_repair`, though the columns exist | FIX-04 | Fixed |
| B-09 | CRITICAL | customer_engine.py:100 | Cross-tenant leak: `load_profile()` falls back to the **shared** `data/customer_profile.json`; `save_profile()` overwrites it for every customer | Fresh customer with no DB profile received `{'name':'Alice','keywords':'nursing'}` | Single global legacy file used as a per-customer fallback | FIX-05 | Fixed |
| B-10 | CRITICAL | customer_engine.py:327,356,370 | Cross-tenant CV leak: every CV upload overwrites shared `data/customer_cv.txt`, and `get_active_cv_path()` falls back to it when a customer has no active CV | `/api/customer/cv_text?customer_id=2` returned a *different real customer's* CV text (`PRECIOUS SYLVESTER`) | Same shared-file pattern as B-09 | FIX-05 | Fixed |
| B-11 | CRITICAL | database.py:938 | Column `paystack_auth_code` is read/written by `update_customer()` but **does not exist** in the live DB → `OperationalError: no such column` | `database.update_customer(cid, paystack_auth_code=…, subscription_status='active', …)` raised. Both `billing_success()` and `paystack_webhook()` call it inside `try/except`, so **a paying customer is never activated** and still sees "Payment Successful" | Column only ever added by hand; never in `SCHEMA`, no migration | FIX-06 | Fixed |
| B-12 | HIGH | web_app.py:1024 | `start_task()` inverts its timeout test: `if killer.is_alive(): ok=False`. The timer is still running whenever a child finishes *early*, so **every successful scan/tailor/import is reported as failed** | Child printed `hello from child` and exited 0 → `status='failed' ok=False`, log `'hello from child\n\n[stopped: over 60s]\n'` | Mistook "timer pending" for "timer fired" | FIX-07 | Fixed |
| B-13 | HIGH | web_app.py:778 vs 1147 | Two view functions on `POST /api/scan`. Werkzeug resolves to the first registered → `api_customer_scan`, so the **admin** Scan button hits a customer-only view | `url_map.bind().match('/api/scan','POST')` → `api_customer_scan`; authenticated admin gets `401` | Duplicate route; the earlier fix removed a duplicate `/api/extract` but missed this one | FIX-08 | Fixed |
| B-14 | HIGH | web_app.py:1633 | `GET /api/usage?resource=scan\|tailor\|email` raises `IndexError: No item with that key` on a schema without the limit columns → 500 | Live traceback: `web_app.py:1633 IndexError: No item with that key` | Unguarded `row['monthly_scan_limit']` | FIX-09 | Fixed |
| B-15 | HIGH | web_app.py:566 | `/api/billing/status` has the same unguarded column access | Same class as B-14 | — | FIX-09 | Fixed |
| B-16 | HIGH | database.py:864 | `count_scans_this_month()` queries a `tasks` table that does not exist; the `OperationalError` is swallowed → always returns `0`, so the **monthly scan quota can never be reached** | `tasks table exists? False`; `count_scans_this_month -> 0` after activity | Table never created; caller treats 0 as "no usage" | FIX-10 | Fixed |
| B-17 | HIGH | database.py:911 | `increment_tokens_used()` runs an `UPDATE` on a raw connection with no `transaction()` → never committed; and **nothing ever calls it** | `tokens today: before=0 after=0`, still `0` after reconnect; grep shows zero callers | Missing commit + feature never wired up | FIX-10 | Partially Fixed |
| B-18 | MEDIUM | database.py:450 | `set_active_cv(customer, cv_id)` deactivates **all** the customer's CVs *before* checking ownership, then returns `False` for a foreign `cv_id` — leaving the customer with no active CV | `set_active_cv(A, B_cv) -> False` and `A active CV = None` | Non-atomic check-then-act | FIX-11 | Fixed |
| B-19 | MEDIUM | web_dashboard.html:780 | `esc()` is `String(s == null ? '' : s)` — it does **not** escape HTML, yet is used to sanitise every `innerHTML` interpolation | Source line confirmed | Misnamed no-op helper | FIX-12 | Fixed |
| B-20 | MEDIUM | web_dashboard.html:1540,1558 | Billing panel injects `plan` and `limits.*` into `innerHTML` unescaped. `subscription_status` / `monthly_*_limit` are attacker-writable through B-06 → **stored XSS** chain | Code path confirmed; `update_customer` allow-list includes those columns | No output encoding + B-06 | FIX-12 | Fixed |
| B-21 | MEDIUM | database.py:369 | `cleanup_expired_sessions()` is defined but **never called** | grep: definition only. Live DB has 20 sessions, all `revoked=0`, incl. already-expired rows | Never wired to a startup/periodic hook | FIX-11 | Fixed |
| B-22 | MEDIUM | database.py:346 | `revoke_all_customer_sessions()` never called → no way to force-logout a user (e.g. after a password change) | grep: definition only | Not wired | FIX-11 | Reported, not changed |
| B-23 | LOW | database.py:244 | `verify_customer_password()` compares hashes with `==`, not `secrets.compare_digest` (unlike `auth.verify_password`) | Source | Inconsistent, timing-observable | FIX-11 | Fixed |
| B-24 | LOW | web_app.py:840 | `pin_ok()` does `request.json.get(...)`; a JSON `Content-Type` with an empty body makes Flask raise 400 before this, but `request.json` can still be `None` for a literal `null` body | Code path | No `or {}` guard | FIX-11 | Fixed |
| B-25 | LOW | web_app.py:1572 | `/files/` blacklist approach (`'..' in filename`) plus 3 other heuristics is redundant; `os.path.commonpath` is the real control. `commonpath` raises `ValueError` on mixed drives (unreachable here) | Code read | Belt-and-braces that obscures the actual check | Reported, not changed | Open (LOW) |
| B-26 | CRITICAL | database.py:214 | `get_connection()` cached one connection per thread **forever** and never compared it to `DB_PATH`. Every test fixture assigns `database.DB_PATH = tmp_path/...`, which was silently ignored, so **the whole test suite wrote into the real `data/jobmatch.db`** | Before/after row counts on `data/jobmatch.db` plus `PRAGMA database_list` while `DB_PATH` pointed at a temp file: the temp file stayed empty, the real DB gained rows | Connection cache was not keyed on the path | FIX-14 | Fixed |
| B-27 | HIGH | customer_engine.py:304 | `POST /api/cv` unconditionally calls an **outbound LLM "CV repair"** for short/low-quality uploads, transmitting CV text to Gemini/Groq with no consent, no prompt, and no cost guard | Live upload logged `[LLM] Selected provider: gemini (model: gemini-1.5-flash)` then `CV quality 0.00 - repaired with groq` for a 5-word CV | `_should_repair()` returns True for tiny text; repair path has no provider/permission gate | Reported, not changed | Open (HIGH) |
| B-28 | MEDIUM | web_app.py:534 | `GET /billing/success` is outside the auth gate and calls the Paystack API with an attacker-supplied `?reference=`; no rate limit, no session requirement | Route audit: 8 routes are not inspected by `gate()`; this one performs an outbound paid-API call | Route is neither `/api/*` nor in `PUBLIC_ENDPOINTS`, and has no limiter decorator | Reported, not changed | Open (MEDIUM) |
| B-29 | LOW | database.py:468 | `update_session_last_seen()` is never called, so `sessions.last_seen_at` is frozen at creation for cookie sessions; no idle timeout is possible | grep: definition only | Not wired into `auth.get_current_customer_id()` | Reported, not changed | Open (LOW) |
| B-30 | HIGH | web_app.py `__main__` | **The app never ran `init_db()` on startup.** `data/jobmatch.db` predated the `tasks` table and the `customers.paystack_auth_code` column, so `CREATE TABLE IF NOT EXISTS` never ran against it. The server started cleanly and only failed per request: `GET /api/usage?resource=scan` → `500 RuntimeError: usage counting unavailable: no such table: tasks` (web_app.py:1798 → database.py:1019), while `?resource=tailor` and `?resource=email` returned 200 because they read other tables. Any Paystack billing write would have failed the same way | Live log 2026-10-04 13:43:52 — 500 on `resource=scan`, 200 on `tailor`/`email` from the same page load; `sqlite_master` on the live file had 8 tables and no `tasks`, and `PRAGMA table_info(customers)` had no `paystack_auth_code` | `init_db()` was only ever called from `database.py __main__` and the test fixtures. Nothing in the serving path applied `SCHEMA` or `MIGRATIONS`, so the dev server ran happily against an un-migrated file | `web_app.ensure_schema_ready()`, called from `__main__` **before** `app.run()`; `SystemExit(1)` on failure so it cannot serve a half-migrated database. Live DB migrated (backup `data/jobmatch.db.bak_pre_schema_migration_20261004_140122`) | Fixed |
| B-35 | HIGH | tests/test_auth.py `TestAdminAuthenticationCompatibility` | **Running the test suite deleted the production admin password.** Three tests hardcoded the relative path `web_admin.env`, wrote `adminpassword123` into it, and then `os.remove()`'d it in a `finally` block. The `client` fixture redirected the database but not `ADMIN_PATH`, so these hit the real project-root file. Consequence: after any `pytest` run, `SETUP_MODE` flipped back to true and `gate()` failed closed, so **every `/api/*` request from a phone returned 403** — with nothing in the app's log to explain why | Recreated `web_admin.env` via `POST /api/status_setup`, confirmed it existed (11 chars), ran the full suite, and it was gone. Same class of bug as B-26/R-01 ("tests write into production"), reached through a file instead of a database | The tests had no `tmp_path`/`monkeypatch` isolation for `ADMIN_PATH`, and the `finally: os.remove()` pattern looks defensive while actually being the destructive part | `client` now monkeypatches `web_app.ADMIN_PATH` into `tmp_path`, so no test can reach the real file; the three tests share an `admin_pw` fixture and no longer delete anything. Verified: `web_admin.env` survives a full suite run | Fixed |
| B-34 | HIGH | cv_tailor.py `PROVIDERS['gemini']['model']` | **Gemini had a 100% failure rate and nobody noticed.** The configured model was `gemini-1.5-flash`, which the API now rejects with `404 models/gemini-1.5-flash is not found for API version v1beta`. Because `call_gemini` returns `None` on "model not found" (to let the caller fall through to the next provider), every Gemini call failed silently and work went to Groq instead | 8 live calls per model: `gemini-1.5-flash` → **0/8, all 404**; `gemini-2.5-flash` → 404 *"no longer available to new users"*; `gemini-3.6-flash` → **7/8 HTTP 200** (one 429 rate-limit, no 503s) | The default was pinned to a model name the provider retired, and the fall-through path treats "wrong model" as a normal outcome rather than a fault | Default changed to `gemini-3.6-flash` (the only one of the three that responds). `test_cv_tailor_provider_configuration` had asserted `!= 'gemini-3.6-flash'` on the comment "3.6-flash is invalid" — a stale conclusion apparently drawn from a transient 503, and the only thing "protecting" a 100%-broken config. Both it and `test_configured_gemini_model_is_not_a_dead_one` now assert against the measured-dead set instead | Fixed |
| B-31 | HIGH | database.py `get_tokens_used_today`, cv_tailor.py, customer_engine.py | **LLM spend was never recorded, so `daily_token_budget` could not fire.** Three compounding defects: (1) the total was inferred with `json_extract()` from `tailored_cvs.qc_notes`, but that column holds free text written by `customer_engine` (`'; '.join(qc)`), so the extract always returned NULL and the budget always read 0; (2) both providers *did* return token counts (`usageMetadata.totalTokenCount`, `usage.total_tokens`) and `cv_tailor` discarded them; (3) the write that did exist ran on a raw `get_connection()` outside `transaction()`, so it never committed **and** it overwrote a human-readable QC note with a JSON blob. Every tailor/repair call was effectively free to the meter | `get_tokens_used_today()` returned 0 immediately after writing 150 tokens; `token_usage` did not exist; `qc_notes` came back as `''` after `increment_tokens_used` | Spend was derived from a column nobody controlled, and the write path bypassed the transaction helper | New append-only `token_usage` ledger (`record_token_usage`/`get_tokens_used_since`) written inside `transaction()`; `increment_tokens_used` now delegates to it; `cv_tailor` tallies provider-reported counts in `_TOKEN_TALLY` with a character-based fallback when a gateway omits `usage`, drained per CV via `take_token_usage()`; `customer_engine._ledger_tokens()` books each repair and each tailored CV against the customer. `enforce_usage('tokens')` added to `/api/tailor`, `/api/customer/run`, `/api/customer/tailor`, `/api/cv`, `/api/customer/cv` | Fixed |
| B-32 | HIGH | web_app.py `check_usage_limit('tailor')` | **The tailor quota could be overshot by an order of magnitude.** The limit was checked against `count_tailored_this_month()`, which counts rows in `tailored_cvs` — but a tailor request only *enqueues* a background process, and those rows appear minutes later. Inside the 5/hour rate-limit window a client could fire five `top=50` requests (250 CVs) while the counter still read 0 | `count_task_units_since()` reserved 50 units and `check_usage_limit` immediately refused the next request; before the fix the same call returned allowed | Quota was measured on *completion* of an *asynchronous* job, with no reservation at request time | `tasks.units` column reserves the requested `top` the moment the job is accepted; `check_usage_limit('tailor')` charges `max(reserved, completed)`; `start_or_report(..., reserve=[...])` writes the reservation **only after** `start_task` confirms the job started, so a busy-server rejection costs nothing; the worker calls `finish_task_event(ok)` so a failed run refunds its units. A run reserves `[scan 1, tailor top]` together | Fixed |
| B-33 | HIGH | web_app.py `start_or_report` | **`POST /api/tailor` returned 500 on every call.** The route passed `timeout=1800` to `start_or_report(name, script, args=None)`, which had no such parameter → `TypeError: start_or_report() got an unexpected keyword argument 'timeout'` | `inspect.signature(start_or_report)` lacked `timeout` while the call site passed it | The wrapper was added after the route and never grew the parameter the route already used | `start_or_report` now accepts `timeout` and forwards it to `start_task` | Fixed |

## B. REGRESSIONS (introduced by earlier milestones)

| ID | Sev | Component | Bug | Reproduction | Root Cause | Fix | Status |
|----|-----|-----------|-----|--------------|------------|-----|--------|
| R-01 | HIGH | tests/ vs customer_engine.py | The test suite writes **test data into production**: `data/customer_profile.json` was overwritten with `{"name":"Test User",...}`, **and** the real `data/jobmatch.db` was mutated (customer 1 renamed to "Test User", several `*@example.com` customers created) | File mtime 12:27:10 == pytest run; `data/jobmatch.db` customer 1 = `Test User`; `PRAGMA database_list` showed the real file open while `DB_PATH` pointed at a temp path | `PROFILE_PATH` was an unredirected module global **and** the connection cache ignored `DB_PATH` (B-26) | FIX-05 + FIX-13 + FIX-14 | Fixed (file writes); **real-DB rows still need owner-approved cleanup** |
| R-02 | MEDIUM | database.py:21 | `JOBMATCH_DB_PATH` is set by `tests/conftest.py` and every fixture, but `database.py` hardcoded `DB_PATH = DB_DIR/'jobmatch.db'` and never read it | Fixture sets env var; module ignores it | Env-var support was documented in the tests but never implemented | FIX-13 | Fixed |
| R-03 | MEDIUM | database.py:275 / 938 | `update_customer()` is **defined twice**; the second (line 938) silently shadowed the first. mypy: `Name "update_customer" already defined on line 275` | ruff `F811`, mypy `no-redef` | Billing columns were added by copy-pasting a second definition | FIX-11 | Fixed (one definition, whitelist-enforced) |
| R-04 | LOW | pyproject.toml | `[tool.ruff] select/ignore` are deprecated top-level keys → ruff prints a migration warning on every run | `warning: The top-level linter settings are deprecated` | ruff moved to `[tool.ruff.lint]` | FIX-13 | Fixed |
| R-05 | MEDIUM | pyproject.toml | `readme = "README.md"` but no `README.md` exists → `python -m build` / `pip install .` fails; `paystackapi` is imported by the billing routes but was undeclared | `python -m build` → missing README; `pip show paystackapi` not in deps | Packaging metadata out of sync with the tree | Reported, not changed | Open (MEDIUM) |

## C. TECHNICAL DEBT

| ID | Component | Issue |
|----|-----------|-------|
| T-01 | dual storage | `database.py` (DB) **and** `data/customers/<id>/` (files) are both authoritative. `/api/customer` reads results from disk while `/api/matches` reads the DB; they can disagree. The file side is currently empty (only `data/customers/1/`, 0 files) while the DB holds 352 applications. |
| T-02 | `customer_engine.py` | Module-global `job_scraper.TARGET_KEYWORDS` / `FAST` are swapped per scan and restored in `finally`. `web_app.api_customer_scan` calls `run_scan()` **in-process** under `threaded=True`, and `run_scan` also writes the single shared `data/scanned_jobs.json`. Two concurrent customer scans can score customer B with customer A's keywords and persist the wrong jobs. `start_task`'s one-at-a-time guard does not cover the in-process path. |
| T-03 | legacy CSV | `applications.csv` is global, not per-customer; `/api/state` and `/api/status` let any authenticated customer read and rewrite the admin's tracker. 5 rows have an empty `Apply Link`, which `/api/status` (keyed on `Apply Link`) can never update — permanently stuck at `TO_APPLY`. |
| T-04 | BOM drift | `web_app.write_csv_rows()` writes `utf-8`; `import_scanned_jobs.write_rows()` writes `utf-8-sig`. After any `/api/status` update the BOM is dropped and Excel shows mojibake in column A. |
| T-05 | secrets | `RESUME_NEXT_SESSION.md:13-14` and `:29` contain the admin password, the send PIN and the model/credit status **in plaintext**. `.gitignore` does not exclude `.md`, so these commit. Not rotated here — that is an owner action. |
| T-06 | secrets | **Fixed.** `.gitignore` did not exclude `data/*.db` (11 customers, PBKDF2 hashes, emails) nor `data/customers/`, `data/*.txt`, `data/customer_cv.txt`, `*.db-wal`/`-shm`. All are now excluded. (`*.env` was already covered by the `*.env` rule.) |
| T-07 | secrets | `cv_tailor.ENV_FILES` reads API keys from a sibling repo (`../Ideas/Twitter/x-llm-bot/.env`). Hardcoded external path; the project cannot be moved or deployed without it. |
| T-08 | deps | `flask-limiter 4.1.1` installed but `pyproject.toml` pins `>=3.5,<4`. Installed state violates the declared constraint. |
| T-09 | deps | `paystackapi` is imported by `api_checkout`/`billing_success`/`paystack_webhook` but is **not declared** in `pyproject.toml`. On a clean install billing dies with `ModuleNotFoundError`, swallowed into a 500 that returns `str(e)`. |
| T-10 | deps | `pyproject.toml` declares `readme = "README.md"`; no `README.md` exists → `pip install .` fails. |
| T-11 | LLM | `cv_tailor.PROVIDERS['gemini']['model'] = 'gemini-1.5-flash'` (retired by Google). `RESUME_NEXT_SESSION.md` documents `gemini-3.6-flash`. Code and docs disagree; the primary provider is dead so every call pays for a fallback. |
| T-12 | LLM | `OPENROUTER_API_KEY` in the sibling `.env` starts with `https:` — a base URL pasted into the key field, so that provider cannot authenticate. |
| T-13 | CI | No CI config. 215 ruff errors and 37 mypy errors are committed; `SITUATION_REPORT.md` nevertheless claims "Health Status: Stable ✅". |
| T-14 | data | Live DB has 9 of 11 customers named `Test User` / `Landing User` / `Public Signup User` and 20 never-pruned sessions — residue from earlier manual runs (the current suite does **not** write to it; verified by row-count diff). |
| T-15 | error handling | `handle_500` calls `logger.exception` outside an `except` block, so the log line may carry no traceback. |
| T-16 | info leak | `api_checkout` returns `str(e)` to the client on failure. |

## D. CODE QUALITY (not bugs)

- 130 × W293 / 11 × W291 trailing whitespace; 15 × SIM115 unclosed files; 10 × SIM118 `key in dict.keys()`; 8 × SIM105 `contextlib.suppress`; 6 × E741 ambiguous `l`; 4 × F401 unused import.
- `customer_engine.py:673` redefines `sys` (F811); `database.py:748`, `cv_to_pdf.py:157,163` assign unused locals.
- `web_app.py` is 1721 lines mixing auth, billing, scraping orchestration, CSV persistence and HTML serving.
- `auth.py:47` re-imports `flask.request` inside the function although it is already imported at module level.

## E. FEATURE REQUESTS (explicitly NOT bugs)

- Remote-first job sources (SITUATION_REPORT step 1) — supply problem, not a defect.
- Cloudflare Tunnel + landing page (step 2).
- Customer profile selector for multi-profile users (step 3).
- x-llm-bot router / per-customer token budgets (step 4).
- Extend `career_crawler` for product use (step 5).
- **New:** a real `README.md`, and a CI job running pytest + ruff + mypy.

---

## System map (as built)

```
Browser (mobile-first dashboard / landing)
   |  cookie: customer_session  (PBKDF2 password, 30-day, hashed token in DB)
   |  cookie: flask session     (admin password from web_admin.env)
   v
Flask  web_app.py  (threaded dev server, :5000, memory:// rate limit)
   |-- before_request gate()  -> PUBLIC_ENDPOINTS allow-list, else 401
   |-- _get_request_customer_id() / _get_customer_id_legacy()  -> g.customer_id
   |-- /api/customer*      -> customer_engine.py (subprocess or in-process)
   |-- /api/scan /import /extract -> start_task() -> subprocess, in-memory TASKS{}
   |-- /files/<cid>/<path> -> data/customers/<cid>/tailored_cvs  (commonpath guard)
   v
customer_engine.py  ->  job_scraper.py (13 sources)  |  cv_tailor.py (LLM chain)
   v
database.py (SQLite data/jobmatch.db, WAL, FK ON, thread-local conns)
   +  legacy side-channel: data/customer_profile.json, data/customer_cv.txt,
      applications.csv, tailored_cvs/          <-- all GLOBAL, all shared
External: Paystack (billing), Gmail SMTP (send), Gemini/Groq/OpenRouter/OpenAI,
          13 job boards, Playwright (portal autofill)
```

Intended vs actual, in one line: **intended** per-customer isolation end to end;
**actual** per-customer isolation in the DB layer only, with three global
side-channels and a request-scoped `customer_id` that callers fully control.

---

## F. VERIFICATION LOG

Baseline was captured before any edit. All figures are measured, not estimated.

| Check | Before | After |
|-------|--------|-------|
| `pytest -q` | 80 passed, 2 skipped | **112 passed, 2 skipped** (32 new security regression tests) |
| `ruff check .` | 215 errors | **196 errors** (all style; 6 pyflakes, 0 undefined names) |
| `mypy .` | 37 errors | **34 errors** |
| ruff deprecation warning | yes | **no** |
| `data/jobmatch.db` row counts across a full `pytest` run | mutated | **unchanged** (11/7/352/352/2/352/1/20 before and after) |
| `web_admin.env` created by probes | yes | **no** (removed) |
| `init_db()` on a copy of the real DB | n/a | adds `paystack_auth_code` + `tasks`, `integrity_check: ok`, all business row counts preserved, prunes 1 expired session |

### Second pass (2026-10-04, B-30): the app never migrated the database it was pointed at

Found from a live server log, not from reading code — `GET /api/usage?resource=scan`
returned 500 `no such table: tasks` while `tailor` and `email` returned 200 from the
same page load.

| Check | Before | After |
|-------|--------|-------|
| `tasks` table in `data/jobmatch.db` | missing | present |
| `customers.paystack_auth_code` in `data/jobmatch.db` | missing | present |
| `GET /api/usage?resource=scan` (authenticated, live DB) | **500** | **200** `{"ok":true,"used":0,"limit":30,"remaining":30}` |
| `GET /api/usage?resource=tailor` / `?resource=email` (live DB) | 200 | 200 |
| `GET /api/billing/status` (live DB) | 200 | 200 |
| `init_db()` rehearsed on a copy of the live DB | n/a | adds `tasks` + `paystack_auth_code`, all 8 row counts preserved, `integrity_check: ok`, `foreign_key_check` 0, `count_scans_this_month` returns 0 instead of raising |
| `pytest -q` | 112 passed, 2 skipped | **117 passed, 2 skipped** (5 new tests) |
| `ruff check .` | 196 errors | **196 errors** (no new findings) |
| `mypy .` | 34 errors | **34 errors** |
| `data/jobmatch.db` row counts across a full `pytest` run | 2/1/2/2/352/352/2/0 | **unchanged** |

Backup taken before migrating the live file:
`data/jobmatch.db.bak_pre_schema_migration_20261004_140122`.

Targeted checks written for this pass (scripts in `%TEMP%\opencode`):

- `verify_fixes.py` — 27 database-layer assertions: schema creation, migration
  idempotency, `update_customer` whitelist, `create_or_update_profile` cv_*
  acceptance and partial-update preservation, `record_task_event` /
  `count_scans_this_month` scoping, `set_active_cv` cross-tenant rejection
  leaving the owner's active CV intact, `increment_tokens_used` commit.
  **Result: 27/27 pass.**
- `verify_http.py` — 69 HTTP-layer assertions: setup-mode fail-closed for local
  and remote, remote `status_setup` refusal, anonymous blocking of the customer
  surface, admin-vs-customer authorization, cross-tenant IDOR refusal,
  `customer_id` body-override refusal, PATCH whitelist, list/detail secret
  redaction, `/api/usage` and `/api/billing/status`, scan-quota accounting, CV
  upload round trip with no cross-tenant bleed, `/api/scan` single-handler.
  **Result: 69/69 pass.**
- `audit_routes.py` — enumerates all 56 routes and flags those `gate()` never
  inspects. 8 are un-gated: `/`, `/landing`, `/static/*`, the four `/auth/*`
  self-authenticating endpoints, and `/billing/success` (see B-28).
- `check_dashboard_js.py` — `node --check` on the extracted inline script, plus
  assertions that `esc()` really escapes and that every `innerHTML`
  interpolation is either `esc(...)` or quote/angle-bracket-free arithmetic.
  **Result: 10/10 pass.**
- `check_render.py` — renders `/`, `/landing` and the authenticated dashboard;
  asserts every JS-referenced element id exists in the markup (67 ids / 52 refs
  on the dashboard, 42 / 23 on landing), every local `href`/`src` resolves on
  disk, and no Jinja delimiters leak. **Result: 11/11 pass.**

### Durable regression tests

`tests/test_security_regressions.py` — 37 tests, each named after the bug it
locks down. No network, no subprocesses, no outbound LLM calls. Covers: the
`DB_PATH` connection-cache bug, schema + migration idempotency, the profile
cv_* signature and partial-update preservation, scan-event accounting and the
`tasks`-table guard, the `update_customer` whitelist at both the DB and HTTP
boundaries, cross-tenant `set_active_cv`, token-accounting commit, setup-mode
fail-closed for local *and* remote, remote setup refusal, anonymous blocking,
customer-vs-admin authorization, cross-tenant IDOR, body-supplied `customer_id`
tenant switching, secret redaction, the shared-legacy-file fallbacks, the
duplicate `/api/scan` route, `/api/usage` and `/api/billing/status`, session
pruning, the dashboard escaping, and the startup schema guard (B-30: a
downgraded database still breaks usage counting, `ensure_schema_ready()` repairs
it without touching business rows, it is idempotent, `__main__` calls it before
`app.run()`, and `/api/usage?resource=scan` returns 200 against a pre-`tasks`
file). **Result: 37/37 pass.**

### Third pass (2026-10-04, B-31/B-32/B-33): metering LLM spend and closing the async quota race

Both of the agreed safeguards landed, and the pass turned up two more live bugs
along the way.

**B-31 — the daily token budget could never fire.** `get_tokens_used_today()`
derived spend from `json_extract(tailored_cvs.qc_notes, '$.tokens')`, but
`customer_engine` writes prose into that column (`'; '.join(qc)`), so the
extract returned NULL every time. Meanwhile both providers *were* returning
counts — `usageMetadata.totalTokenCount` and `usage.total_tokens` — and
`cv_tailor` threw them away. The single write that did exist ran on a raw
`get_connection()` outside `transaction()`, so it neither committed nor left the
QC notes intact.

Replaced with an append-only `token_usage` ledger written inside `transaction()`.
`cv_tailor` tallies provider counts per call and falls back to a
character-based estimate when a gateway omits `usage`, so a missing usage block
costs an estimate instead of nothing. `customer_engine._ledger_tokens()` drains
the tally into the ledger after **each** tailored CV and after each CV repair,
so a batch that dies half way still bills what it actually spent.
`enforce_usage('tokens')` now guards all five LLM-spending routes.

*A defect found by the new tests, before it reached production:* `token_usage.created_at`
defaults to SQLite's `datetime('now')` → `'YYYY-MM-DD HH:MM:SS'`, while callers
pass Python `isoformat()` → `'YYYY-MM-DDTHH:MM:SS'`. Compared as TEXT, space
(0x20) sorts **before** `T` (0x54), so every row from the current day fell
before the midnight boundary and the budget read 0 again. The comparison now
goes through `datetime()` on both sides. Locked down by
`test_token_ledger_counts_same_day_rows`, which asserts the stored format *and*
that today's total is non-zero.

**B-32 — the tailor quota was overshootable by ~5x.** The limit was checked
against `count_tailored_this_month()`, which counts `tailored_cvs` rows — but a
tailor request only *enqueues* a background process, and those rows land minutes
later. Inside the 5/hour window a client could fire five `top=50` requests
(250 CVs) against a counter that still read 0.

`tasks.units` now reserves the requested `top` the instant the job is accepted,
and `check_usage_limit('tailor')` charges `max(reserved, completed)`. Two
details matter:

- The reservation is written **after** `start_task` confirms the job started, so
  a request refused because another task is already running costs the customer
  nothing.
- The worker calls `finish_task_event(ok)`, so a run that crashes refunds its
  units instead of billing for work that never happened. Both the
  `Popen`-failure path and the normal `finally` close the reservation.

`/api/customer/run` reserves `[scan 1, tailor top]` in one step. It previously
called `record_usage_event` *before* parsing `top`, so a request rejected for an
invalid `top` still cost the customer a scan.

**B-33 — `POST /api/tailor` returned 500 on every call.** The route passed
`timeout=1800` to `start_or_report(name, script, args=None)`, which had no such
parameter. Found by reading the call sites rather than by a test, because the
route had no coverage at all; `start_or_report` now accepts and forwards it.

**Verification**

- `python -m pytest -q` → **140 passed, 2 skipped** (was 117/2; +23 new, 0
  regressions). `ruff` 194 findings (2 *below* the 196 baseline) and `mypy` 34
  errors (at baseline), so no new debt.
- New `tests/test_token_accounting.py` — 23 tests: same-day ledger counting,
  boundary handling, per-customer isolation, Gemini/OpenAI usage capture, the
  missing-usage fallback, tally reset between CVs, junk tolerance, reservation
  accounting, refund-on-failure, `max(reserved, completed)` enforcement, the busy
  path charging nothing, `start_or_report`'s timeout signature, and both
  missing-table guards.

*Restoring B-30's fail-loudly property:* see the end of this section.
- The shared fixtures (`db`, `two_customers`, `web_app_module`, …) moved from
  `tests/test_security_regressions.py` to `tests/conftest.py`. They were
  module-local, so no other test file could use them — which is why the first run
  of the new tests errored 15 times with `fixture 'db' not found`.
- Migration rehearsed on a copy of the live DB first: `tasks.units` added,
  `token_usage` + index created, `PRAGMA integrity_check` ok, `foreign_key_check`
  clean, no row-count drift except pruning one already-expired session.
- Live DB then migrated with an online backup taken and verified first:
  `data/jobmatch.db.bak_pre_token_ledger_20261004_152936`. Post-migration counts
  unchanged: 2 customers, 2 profiles, 2 CVs, 352 jobs / matches / applications,
  2 tailored CVs.
- Live read-only check of all four quota branches for customers 1 and 12: scan /
  tailor / tokens / email all allowed, each at its configured limit
  (50,000 tokens/day, 50 tailor/month).

*A note on the verification itself:* the first attempt to delete the
self-test ledger row used a bare `connection.execute('DELETE ...')` and reported
1 row still present — the identical "write outside a transaction" mistake that
B-31 was about. Re-run through `transaction()`, the row committed and
`token_usage` is back to 0 rows. Worth remembering that `get_connection()` is
not auto-committing.

*Restoring B-30's fail-loudly property:* routing the scan quota through
`count_task_units_since` quietly dropped the `RuntimeError` guard that
`count_scans_this_month` had been given in B-30 — a missing `tasks` table would
have surfaced as a raw `sqlite3.OperationalError` instead of the deliberate,
self-describing error. Both `count_task_units_since` and `get_tokens_used_since`
now raise `RuntimeError` rather than reading 0; the latter matters most, since
"0 tokens used" against an un-migrated database would disable the cap outright.

### End-to-end proof, and what it turned up (2026-10-05)

Unit tests are not evidence that a metering fix works. One real Gemini call,
through `cv_tailor`'s own `load_env()` and `tailor()`:

```
provider tokens : 131  (calls: 1)
get_tokens_used_today(12)      -> 131
ledger row -> {'id': 2, 'customer_id': 12, 'tokens': 131, 'kind': 'tailor',
                'created_at': '2026-10-05 06:01:50'}
check_usage_limit tokens -> (True, '')
```

Real provider-reported `usageMetadata`, an append-only row, and the budget
reading it back. That is B-31 closed. Two further defects surfaced only because
the call was real:

- **A timezone bug in my own fix.** `created_at` read `06:01:50` while local
  time was `07:02` — the column default `datetime('now')` is **UTC** and
  space-separated, while `get_tokens_used_today()` computes a **local** midnight
  boundary. This box is UTC+1, so anything written between local midnight and
  01:00 was dated to the previous day and skipped, leaving the budget slightly
  open at the start of every day. `record_token_usage` now writes an explicit
  local `isoformat(timespec='seconds')` timestamp, matching `record_task_event`;
  `get_tokens_used_since` still compares via `datetime()` so legacy
  space-separated rows keep counting (both cases tested).
- **B-34, above:** the configured Gemini model was dead, so this was the first
  time a Gemini call had actually succeeded.

Also corrected in `cv_tailor.tailor()`: a request the provider *refuses*
(`out is None`, i.e. unknown model) is no longer charged a fallback estimate.
Nothing was generated, so charging for it would bill the customer for our
configuration error. A request that was transmitted and then failed still is
charged — under-reporting there is exactly how the cap gets bypassed.

**Test totals after this pass:** `143 passed, 2 skipped` (with `web_admin.env`
present, i.e. the real deployed configuration); ruff 188 (below the 196
baseline), mypy 34 (at baseline).

**Not reproduced, so not claimed as fixed:** the first full run after
`web_admin.env` was created showed 4 failures in `tests/test_auth.py`
(`TestSessionValidation`). The file passes in isolation and two subsequent full
runs were clean. `SETUP_MODE` is computed once at import from
`os.path.exists(ADMIN_PATH)`, so creating that file flips it for the whole
process — a real order-sensitivity in the fixtures that should be pinned down if
it ever reappears.

→ **Resolved below as B-35.** The cause was the opposite of a flake: those four
tests asserted `error == 'not authenticated'`, and which of the two correct 401s
comes back depends on whether an admin password exists. With one, `gate()`
short-circuits at web_app.py:218 with `'login required'`; without one, a local
request falls through to the route's own check (web_app.py:692 and neighbours).
They only ever passed because B-35 deleted `web_admin.env` first. Fixed by
asserting the behaviour (401 + `ok: False` + a known set of messages) rather than
one string, so the suite now passes in the *deployed* configuration — which is
the first time it has done so with `SETUP_MODE` false.

### Runtime restored (2026-10-05)

- **API keys: no change was actually needed.** `cv_tailor.ENV_FILES` already
  includes `..\Ideas\Twitter\x-llm-bot\.env` and `load_env()` reads it, so the
  keys were available all along. An earlier check that passed a bare
  `os.environ` instead of `load_env()` wrongly reported them missing. As a
  harmless belt-and-braces measure `GEMINI_API_KEY`, `GROQ_API_KEY` and
  `OPENROUTER_API_KEY` were also exported to the Windows *user* environment;
  that copy is redundant and can be removed with `setx <NAME> ""` if an extra
  plaintext copy in the registry is unwanted.
- **Admin password:** `web_admin.env` was missing, so `SETUP_MODE` was true and
  `gate()` failed closed for every non-local request — from a phone the entire
  API returned 403. Recreated through the app's own local-only
  `POST /api/status_setup`. The password is stored in **plaintext** in that file,
  which is the root of T-05.
- **B-35 above was found by this very act.** Recreating the file made four tests
  fail, and the file was gone again after the next run: the suite had been
  deleting it all along.

### Test hygiene debt still open

`tests/test_smoke.py` (the `/files/` access test) still writes
`test_legitimate_access.txt` into the **real** `tailored_cvs/` directory in the
project root rather than a `tmp_path`. It uses a unique name and cleans up in a
`finally`, so it destroys nothing today, but it is the same shape as B-35 and a
crash mid-test would leave a stray file that `/files/` can serve. Not changed
here because the `/files/` route resolves against `BASE`, so isolating it means
monkeypatching the served root.

### Data state left behind by the earlier debugging session

These are **not** code defects; they need an owner decision.

1. `data/jobmatch.db` — the pre-fix test runs (B-26/R-01) inserted fixture rows
   and renamed customer 1 to `Test User`. **RESOLVED 2026-10-04: owner approved
   deletion of ids 2-11 (all `@example.com`, created 2026-10-03, no real data).
   Deleted with FK cascades: 10 customers, 20 sessions, 6 profiles.
   Backup: `data/jobmatch.db.bak_pre_fixture_cleanup_20261004_135458`; fixture
   dir `data/customers/2/` archived to `%TEMP%\opencode\customers_dir_2_*`.
Customer 12 (`preciousedward419@gmail.com`, a genuine signup made at 13:43 on
    2026-10-04, after this pass) was kept.** Live file then migrated for B-30
    (backup `data/jobmatch.db.bak_pre_schema_migration_20261004_140122`) and
    again for B-31/B-32 (`data/jobmatch.db.bak_pre_token_ledger_20261004_152936`,
    which adds `token_usage` and `tasks.units`).
    Still outstanding: customer 1's `name` is `Test User` and `location` is
    `remote`, both clobbered by the old debug run. Owner must supply the real
    values — not guessed.
2. `data/customer_profile.json` — contained `Test User` fixture content instead
   of the original profile. **RESOLVED 2026-10-04: deleted**; both remaining
   readers guard on `.exists()` and `migrate_from_legacy()` falls back to its own
   defaults without it. Backup: `%TEMP%\opencode\customer_profile.json.bak`.
3. `applications.csv` — rewritten by a `/api/import` probe; 388 rows, 5 with an
   empty `Apply Link` that `/api/status` can never update.
4. `RESUME_NEXT_SESSION.md` — still contains plaintext credentials (T-05).
   Not rotated here; that is an owner action.
