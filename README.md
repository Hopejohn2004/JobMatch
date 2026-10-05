# JobMatch

AI-assisted job matching, CV tailoring and application tracking. Point it at your CV,
and it scrapes remote job boards, ranks the ones worth applying to, tailors your CV and
cover letter to each one, and tracks what you sent.

Built as a personal job-hunting toolkit, then rebuilt as a multi-tenant SaaS.

---

## Features

- **Multi-customer SaaS** - public self-serve signup, per-customer data isolation,
  admin customer switcher, hashed passwords and signed sessions.
- **Job discovery** - scrapes remote-first job boards and company career pages,
  with ATS integrations (Teamtailor, Breezy HR, Recruitee, Comeet, Personio).
- **CV tailoring** - LLM-powered CV rewriting and cover-letter generation with
  pluggable providers (Groq, Gemini, OpenAI, OpenRouter) and automatic fallback.
- **Token metering** - every LLM call is metered against a per-customer ledger,
  so usage is billable and abuse is detectable.
- **Application tracking** - record what was sent, to whom, and follow up later.
- **PDF export** - tailored CVs and cover letters rendered to PDF.
- **Email sending** - Resend with a Gmail SMTP fallback.
- **Billing hooks** - Paystack integration for subscriptions.

## Tech stack

Python 3.12, Flask, SQLite, Playwright, BeautifulSoup, Redis (rate limiting),
Paystack, Resend.

---

## Quick start

```bash
git clone https://github.com/Hopejohn2004/JobMatch.git
cd JobMatch

python -m venv .venv
# Windows:   .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e ".[dev,llm]"
```

### Configure

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Then edit `.env`. At minimum you need:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | **yes** | Signs session cookies. Generate with `python -c "import secrets;print(secrets.token_hex(32))"` |
| `GROQ_API_KEY` | one LLM key | Primary CV-tailoring provider |
| `GEMINI_API_KEY` | one LLM key | Fallback provider |
| `REDIS_URL` | no | Rate-limit storage. Omit or use `memory://` for single-process dev |
| `PAYSTACK_SECRET_KEY` | billing | Paystack secret key |
| `RESEND_API_KEY` | email | Transactional email |

`.env` is gitignored. Never commit it.

### Run

```bash
python web_app.py
```

Open <http://127.0.0.1:5000>.

## Tests

```bash
pytest              # full suite
ruff check .        # lint
mypy .              # type check
```

---

## Deployment

### Render

`render.yaml` is included. Create a Blueprint from the repo, then set the environment
variables in the Render dashboard. Render provides a stable public URL, which is
preferable to an ad-hoc tunnel for anything user-facing.

### Cloudflare Tunnel (local demo)

```bash
cloudflared tunnel --url http://localhost:5000
```

This gives a temporary `*.trycloudflare.com` URL. It is fine for demos and has **no
uptime guarantee** - do not sell it to anyone.

### Production notes

- Run behind `gunicorn`, not the Flask development server.
- Set `REDIS_URL` to a real Redis instance so rate limiting is shared across workers.
- Set `FLASK_ENV=production` so the app refuses to run with debug enabled.
- Terminate TLS at the edge and keep `ProxyFix` middleware in place.

## Security

If you find a vulnerability, please open a private security advisory rather than a
public issue. Never commit `.env`, real CVs, or database backups - the last of these
has contained customer emails and password hashes in the past.

## License

MIT