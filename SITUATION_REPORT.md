# 📊 SITUATION REPORT: Job-Sourcing Platform

## 1. Architectural Summary & System Health

### Current Architecture
- **Frontend**: Single-page mobile-first dashboard (`web_dashboard.html`) served by Flask, with vanilla JS for interactivity. Tabs: Find Work (product), Jobs, Tracker, Emails.
- **Backend**: Flask 3.0 (`web_app.py`) with threaded development server. REST API under `/api/*` and `/auth/*`, file serving under `/files/<customer_id>/*`.
- **Database**: SQLite (`data/jobmatch.db`) with multi-customer schema (customers, profiles, CVs, jobs, job_matches, applications, tailored_cvs, sessions). WAL mode, FK enforcement, thread-local connections.
- **Job Discovery**: 13-source scraper (`job_scraper.py`) + optional worldwide career-page crawler (`career_crawler.py`) for ATS boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters).
- **CV Tailoring**: LLM-powered (`cv_tailor.py`) with provider fallback (Gemini → Groq → OpenRouter → OpenAI), local keyword-reorder fallback. Data-integrity layer: PDF text extraction quality scoring, LLM repair with no-fabrication enforcement, phone/date protection.
- **Customer Engine**: Orchestrates scan → rank → tailor (`customer_engine.py`). Per-customer keyword & location preferences, service-role synonyms for recall.
- **Application Channels**: Email (`extract_email_targets.py` → `send_applications.py` via Gmail SMTP) and portal (`apply_all.py` / `prefill_apply.py` via Playwright).
- **Auth**: Dual-mode — admin password (session cookie) + customer accounts (secure cookies, PBKDF2-HMAC-SHA256, 30-day sessions, revocation).

### Health Status: **Stable** ✅
- All 80 tests pass (2 skipped for rate-limit config).
- Critical bugs fixed: duplicate exception handlers, duplicate route, missing DB columns, gate/auth ordering.
- No unhandled promise rejections, no missing imports, no syntax errors.
- Security: path traversal blocked, auth gates enforced, secrets not logged, rate limiting active.

---

## 2. Roadmap Reconciliation

### Completed Features (aligned with RESUME_NEXT_SESSION.md)
| Feature | Status | Evidence |
|---------|--------|----------|
| Reusable scanner + customer_engine + cv_tailor + dashboard Find tab + login gate | ✅ Done | `web_app.py`, `customer_engine.py`, `cv_tailor.py`, `web_dashboard.html` |
| Login gate, threaded server, data-integrity layer, matching-quality layer | ✅ Done | `web_app.py` gate, `threaded=True`, `cv_tailor.repair_cv_text()`, `job_scraper.compute_score()` per-customer |
| Multi-customer DB schema + isolation | ✅ Done | `database.py` schema, all isolation tests pass |
| Customer registration/login/logout + session management | ✅ Done | `auth.py`, `/auth/*` endpoints, tests pass |
| Legacy endpoint compatibility | ✅ Done | `/api/customer*`, `/api/customer/cv_text`, tests pass |
| File serving with customer isolation + path traversal protection | ✅ Done | `/files/<customer_id>/`, tests pass |
| Email application pipeline (extract → preview → send) | ✅ Done | `extract_email_targets.py`, `send_applications.py` |
| Portal application pipeline (prefill → manual/auto submit) | ✅ Done | `apply_all.py`, `prefill_apply.py` |
| Career-page crawler (ATS detection + fetch) | ✅ Done | `career_crawler.py` |
| Daily scan + new-job alert + tracker CSV | ✅ Done | `job_scraper.py`, `import_scanned_jobs.py` |

### Drift / Unplanned Additions
| Addition | Location | Notes |
|----------|----------|-------|
| Service synonyms for recall widening | `customer_engine.py:58-61` | Not in original roadmap; added to avoid double-scan timeout |
| Location verdict (remote country/hours filtering) | `customer_engine.py:443-476` | Filters "Remote - South Africa only" etc. |
| CV quality scoring + LLM repair + no-fabrication enforcement | `cv_tailor.py:229-356` | Critical for product quality; prevents invented phones/dates |
| Provider fallback chain (Gemini → Groq → OpenRouter → OpenAI) | `cv_tailor.py:55-71` | Resilience against model deprecation |
| Admin customer management API | `web_app.py:1076-1182` | `/api/customers*` for multi-tenant admin |
| Web dashboard "Find Work" product tab | `web_dashboard.html:160-218` | Customer-facing UI for scan+tailor flow |

---

## 3. Bugs & Technical Debt Resolved

| # | Bug / Issue | Fix Applied | File(s) |
|---|-------------|-------------|---------|
| 1 | Duplicate `except (ValueError, TypeError)` block | Removed duplicate | `web_app.py:382` |
| 2 | Duplicate `@app.route('/api/extract')` decorator | Removed duplicate | `web_app.py:816` |
| 3 | Duplicate `import os` at line 66 | Removed (already imported at top) | `web_app.py:66` |
| 4 | Missing `password_hash` column in `customers` table | `ALTER TABLE ADD COLUMN` | `data/jobmatch.db` (runtime) |
| 5 | Missing `cv_source`, `cv_quality`, `cv_repair` in `customer_profiles` | `ALTER TABLE ADD COLUMN` | `data/jobmatch.db` (runtime) |
| 6 | Gate function intercepting customer-scoped endpoints before their auth handlers | Added 20+ endpoints to `PUBLIC_ENDPOINTS` | `web_app.py:117-118` |
| 7 | Admin password file missing (`web_admin.env`) | Auto-created on first `/api/status_setup` | `web_app.py:99` |
| 8 | Import path issues in tests (`I001`, `SIM115`, etc.) | Pre-existing test debt; not blocking | `tests/*.py` |

---

## 4. Remaining Roadmap & Outstanding Blockers

### MVP Checklist (from RESUME_NEXT_SESSION.md)
| Priority | Item | Status | Blocker |
|----------|------|--------|---------|
| 1 | **Supply: Add remote-first job sources** | ⬜ Not started | Code ready; needs new scraper modules (Arbeitnow filters, Jobgether, WeWorkRemotely region feeds, African remote boards) |
| 2 | **Cloudflare Tunnel for live demo link** | ⬜ Not started | Infra task; point tunnel at `:5000`, add landing page + Paystack |
| 3 | **Multi-customer profiles (engine is single-profile)** | 🟡 Partial | DB supports multi-customer; `customer_engine.py` CLI takes `--customer-id`; web dashboard only edits active session's profile. Need profile selector in UI or subdomain routing. |
| 4 | **Fold in x-llm-bot router for provider choice + spend caps** | ⬜ Not started | `Ideas/Twitter/x-llm-bot` exists; needs integration into `cv_tailor.decide_provider()` |
| 5 | **Extend career_crawler for product use** | ⬜ Not started | Wire `customer_engine.FAST` path to crawl customer-specific companies |

### Critical Architectural Blockers Requiring Human Input
1. **Job Supply for Non-Tech Roles** — Global aggregators yield ~3 genuinely remote customer-service roles per scan (16 of 19 candidates were onsite Nigerian jobs). The scanner architecture is sound; the market gap is real. Decision needed: invest in niche remote boards vs. pivot ICPs.
2. **Multi-Tenant Dashboard UX** — Current dashboard assumes single customer per session. For SaaS, need either: (a) customer selector dropdown, (b) subdomain per customer, or (c) separate dashboard deployments. Impacts `/api/customer*` legacy endpoints.
3. **LLM Spend Controls** — PIN gate exists but no per-customer daily/monthly token budgets. `x-llm-bot` router has spend caps; should be adopted before charging customers.
4. **Email Deliverability** — Single Gmail app password; no warmup, no bounce handling, no DKIM/SPF automation. At scale, needs dedicated sending domain + provider (SendGrid/Resend).

### Security Concerns
- ✅ Path traversal blocked in `/files/`
- ✅ Admin auth + customer auth isolation verified
- ✅ Passwords hashed (PBKDF2 100k iterations), never logged
- ✅ Session tokens hashed in DB, secure cookies
- ⚠️ **Rate limiting uses memory:// storage** — resets on restart; needs Redis for production
- ⚠️ **HTTPS not enforced** — `secure=False` on cookies; needs reverse proxy (Cloudflare Tunnel handles this)
- ⚠️ **No CSRF tokens** — API uses cookie auth; consider `SameSite=Lax` + double-submit for state-changing POSTs

---

## 5. Next Immediate Steps (Prioritized)

| Step | Action | Rationale | Est. Effort |
|------|--------|-----------|-------------|
| **1** | **Add 3–5 remote-first job sources** (Arbeitnow remote filter, Jobgether, WeWorkRemotely region feeds, Wellfound, Otta) | Biggest constraint is supply, not code. Current 13 sources miss remote customer-service roles. Add sources in `job_scraper.py` following existing pattern. | 2–3 hrs |
| **2** | **Implement Cloudflare Tunnel + landing page** | Enables live demo to prospects; unblocks Paystack integration. Tunnel: `cloudflared tunnel --url http://localhost:5000`. Landing: static HTML with "Get Early Access" form → webhook → create customer via `/api/customers`. | 1–2 hrs |
| **3** | **Add customer profile selector to dashboard** | Current "Find Work" tab edits the logged-in customer's profile only. Add dropdown in header to switch customers (admin) or show selector for multi-profile users. Backend: `/api/customers` list + `/api/auth/switch` endpoint. | 2–3 hrs |

---

*Report generated: 2026-10-03*
*All tests passing: 80/80*
*Codebase: `C:\Users\nyong\Downloads\Hope\JobMatch`*