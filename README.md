# NewsAnalyser

Live NDTV headlines with article-level sentiment analysis, visualised with Chart.js.

Seven categories — general, cricket, world, health, education, science, entertainment —
scraped from RSS feeds, classified **Positive / Negative / Neutral** with TextBlob, and
served from Neon Postgres. The scraper runs on a schedule in GitHub Actions; the site is a
read-only Flask API deployed on Vercel.

---

## Architecture

```
NDTV RSS feeds
      │
      ▼
  scraper.py ──────────► Neon Postgres (articles table)
   (GitHub Actions,        ▲
    daily 04:17 UTC)       │
                           │
                      flask_app.py  ──►  /api/*  ──►  frontend (Chart.js)
                       (Vercel)                index · category pages · trends
```

The two halves never import each other. They share only `db.py` and the `DATABASE_URL` env var,
so neither can drift from the schema the other expects.

| Piece | Runs on | Does |
|---|---|---|
| `scraper.py` | GitHub Actions, daily | Fetches 7 RSS feeds → keyword-filters → TextBlob sentiment → upserts to Postgres |
| `flask_app.py` | Vercel | Serves the static site and a read-only JSON API. No scraping. |
| `db.py` | both | Single place that reads the database env var |
| `schema.sql` | both | The `articles` table; applied automatically on every scraper run |

---

## Files

```
scraper.py            Single-file scraper — feeds, filtering, sentiment, DB write
flask_app.py          Flask API + static file server
db.py                 Postgres connection from env var
schema.sql            articles table definition
index.html            Home — today's pulse + category grid
trends.html           Sentiment-over-time line chart + data table
category.js           Shared logic for the 7 category pages
styles.css            Full stylesheet
general.html …        One page per category (7 total)
```

---

## Environment variables

Used by **both** the scraper and the web app.

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://USER:PASSWORD@HOST/neondb?sslmode=require` | Use the *pooled* host (ends in `-pooler`) for the app and the scraper |

Locally, put this in a `.env` file (git-ignored) and `pip install python-dotenv`.

---

## Setup

### 1. Database

Create a Neon Postgres database and note the connection string from the Neon console (Connect → Connection string). You do **not** need to run `schema.sql` by hand — `scraper.py` applies it on every run, so the table appears on the first scrape.

### 2. Run the scraper once, locally

```bash
pip install -r requirements.txt
python scraper.py
```

Expected output:

```
[general] scraping
  [rss] parsed 100 items
[general] 100 new · 0 refreshed
...
Done in 41s — 386 new article(s) stored.
```

### 3. Run the site locally

```bash
python flask_app.py
```

Open <http://127.0.0.1:5000>. The pages and API share one origin, so relative
`fetch('/api/…')` calls resolve — do not open `index.html` as a `file://` URL.

---

## Deployment

### GitHub Actions (the scraper)

`.github/workflows/scrape.yml` runs `python scraper.py` daily at 04:17 UTC, and can
also be triggered by hand with **Run workflow** in the Actions tab.

Add `DATABASE_URL` as a repository secret under **Settings → Secrets and variables → Actions**.

Each run is idempotent — `articles.link` is `UNIQUE`, so re-running only inserts
genuinely new articles. The `concurrency` group stops two scrapes overlapping, and the
console output is uploaded as a log artifact.

### Vercel (the site)

The app is a standard Flask app; point Vercel at `flask_app.py` with a WSGI entry, or
use a small `vercel.json` that runs `gunicorn flask_app:app`. Set `DATABASE_URL` under **Project → Settings → Environment Variables**.

The API is read-only, so the site is safe to scale — all writing happens in CI.

---

## API

| Endpoint | Returns |
|---|---|
| `GET /api/generalndtv` | General articles |
| `GET /api/cricketndtv` | Cricket |
| `GET /api/worldndtv` | World |
| `GET /api/healthndtv` | Health |
| `GET /api/edundtv` | Education |
| `GET /api/sciencendtv` | Science |
| `GET /api/enterndtv` | Entertainment |
| `GET /api/allndtv` | Every category |
| `GET /api/sentiment-trends` | Daily positive/negative/neutral percentages |

Every article row is:

```json
{
  "link": "https://sports.ndtv.com/…",
  "headline": "…",
  "datetime_posted": "September 28, 2026 11:04 PM",
  "content": "…",
  "category": "cricket",
  "analysis_result": "Positive"
}
```

`datetime_posted` keeps the original display format so the frontend's date parser is
unchanged; the DB also stores a real `published_at` TIMESTAMP (`TIMESTAMP WITH TIME ZONE`) and a `published_on` DATE
that the trends endpoint groups on.

---

## Tech stack

**Scraping** RSS via `requests` + `xml.etree` · **Sentiment** TextBlob ·
**Database** Postgres (Neon) via `psycopg2` · **API** Flask · **Frontend** vanilla HTML/CSS/JS +
Chart.js · **Scheduler** GitHub Actions

---

## Notes

- Health, education, science, and entertainment use Google News RSS scoped to
  `site:ndtv.com` and then a keyword allowlist, because the corresponding NDTV
  feeds are missing or emit malformed XML. General, cricket, and world use dedicated
  NDTV feeds and need no filtering.
- One failing feed logs an error and the run continues with the next category.
- `*.csv` and `.env` are blocked at the web layer as well as git-ignored — the static
  folder is the project root, so only the API hands out article data.
