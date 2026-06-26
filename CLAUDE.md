# Arizona Family Cabins — Project Guide for Claude

## What this project is
A Flask website for **arizonafamilycabins.com** — direct-booking cabin rentals for two large-group properties in Lakeside, Arizona (White Mountains). Parkway Lodge sleeps 27; Mohave Cabin with Treehouse sleeps 33. Both near Rainbow Lake.

## Owner
Shiloh Lundahl — tech illiterate, prefers Claude to handle 90%+ autonomously.

## The stack
- **Backend:** Flask + SQLAlchemy + Jinja2
- **Server:** gunicorn (`gunicorn app:app --timeout 60`)
- **DB:** Postgres on Render (via `DATABASE_URL`), SQLite locally (auto-fallback)
- **Host:** Render free Web Service
- **Domain:** arizonafamilycabins.com at Bluehost DNS
- **CRM:** HubSpot Free via `HUBSPOT_API_KEY`

## Running locally
```bash
cd arizonafamilycabins
.venv/bin/python scripts/load_content.py      # upsert JSON pages + markdown articles
.venv/bin/python -c "from app import app; app.jinja_env.auto_reload=True; app.run(port=5001)"
# visit http://127.0.0.1:5001
```
Port 5000 is blocked by macOS AirPlay — always use 5001 locally.

## After any content changes
```bash
.venv/bin/python scripts/load_content.py
.venv/bin/python scripts/check_seo.py http://127.0.0.1:5001
```
All lines must show ✓ before committing.

## Adding a new programmatic page
1. Create `content/pages/<slug>.json` with all Page model fields
2. Run `load_content.py`
3. Run `check_seo.py` — all checks must pass
4. Commit and push → Render auto-deploys

## Key rules (non-negotiable)
- Every page must have **genuinely different local facts** — never token-swap the town name
- Title ≤60 chars, meta description ≤155 chars, exactly 1 `<h1>`, 800+ words
- Self-referencing canonical to `https://arizonafamilycabins.com/<slug>/`
- Every page must link to both property pages + 3–5 contextual siblings

## Deploying to Render
- GitHub push triggers auto-deploy
- Load DB content via RUNONCE route (see app.py) — call ONCE then delete that route
- Env vars needed: `DATABASE_URL` (auto-set by Render), `PHONE_NUMBER`, `HUBSPOT_API_KEY`, `SECRET_KEY`

## DNS (Bluehost)
- A record `@` → `216.24.57.1`
- CNAME `www` → `<service>.onrender.com`
- Disable any domain parking/forwarding first

## File layout
```
app.py              — Flask routes, middleware, HubSpot push
models.py           — SQLAlchemy models: Page, Article, Lead
templates/          — Jinja2 templates (base.html + per-page)
static/css/style.css — all styles
content/pages/      — JSON files, one per programmatic page
content/articles/   — Markdown files with frontmatter, one per blog post
scripts/
  load_content.py   — upsert JSON + markdown → DB
  check_seo.py      — assert SEO rules on a running server
```
