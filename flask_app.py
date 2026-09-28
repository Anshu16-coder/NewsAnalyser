"""NewsAnalyser — read-only Flask API + static site.

This app does no scraping. Articles are written to Neon Postgres by scraper.py,
which GitHub Actions runs daily (see .github/workflows/scrape.yml). Run locally:

    python scraper.py   # populate DB
    python flask_app.py # serve the site

The API returns exactly the JSON shape the frontend consumes:
    link, headline, datetime_posted, content, category, analysis_result
"""

import os

from flask import Flask, jsonify, send_from_directory, request, abort
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Serve the HTML/CSS/JS from the project root so pages and the API share
# one origin. Without this the pages have to be opened as file:// URLs.
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
CORS(app)


@app.route("/")
def send_index():
    return send_from_directory(BASE_DIR, "index.html")


@app.before_request
def block_data_file_exposure():
    # The static folder is the project root. Keep .env, CSVs and .git out of
    # reach of the web; only the API should hand out article data.
    path = request.path.lower()
    if path.endswith(".csv") or path.endswith(".env") or "/.git" in path:
        abort(404)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_connection():
    """Open a Neon Postgres connection via DATABASE_URL."""
    from db import get_connection as _get_connection
    return _get_connection()


def _rows_to_list(cursor):
    """psycopg2 DictCursor rows → plain dicts with JSON-safe values."""
    result = []
    for row in cursor.fetchall():
        d = dict(row)
        # Serialize any remaining datetime/date objects
        for key, value in d.items():
            if hasattr(value, "isoformat"):
                d[key] = value.isoformat()
        result.append(d)
    return result


def fetch_articles(category=None):
    """Return article rows, newest first.

    Category names are matched against a fixed allowlist and bound as query
    parameters — no injection surface.
    """
    allowed = {
        "general", "cricket", "world", "health",
        "education", "science", "entertainment",
    }

    # GREATEST skips NULLs, so an article with no published_at still sorts by
    # when it was scraped.
    order = " ORDER BY GREATEST(published_at, scraped_at) DESC NULLS LAST, id DESC"
    cols  = " SELECT link, headline, datetime_posted, content, category, analysis_result"

    if category is None:
        sql    = cols + " FROM articles" + order
        params = ()
    else:
        if category not in allowed:
            raise ValueError(f"Unknown category: {category}")
        sql    = cols + " FROM articles WHERE category = %s" + order
        params = (category,)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows_to_list(cursor)
    finally:
        conn.close()


def build_trend_series():
    """Daily positive/negative/neutral percentages, oldest first."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    published_on AS date,
                    SUM(CASE WHEN analysis_result = 'Positive' THEN 1 ELSE 0 END) AS positive,
                    SUM(CASE WHEN analysis_result = 'Negative' THEN 1 ELSE 0 END) AS negative,
                    SUM(CASE WHEN analysis_result = 'Neutral'  THEN 1 ELSE 0 END) AS neutral,
                    COUNT(*) AS total_articles
                FROM articles
                WHERE published_on IS NOT NULL
                GROUP BY published_on
                ORDER BY published_on ASC
            """)
            rows = _rows_to_list(cursor)
    finally:
        conn.close()

    series = []
    for row in rows:
        total = int(row["total_articles"])
        if not total:
            continue
        positive = round(int(row["positive"]) / total * 100, 1)
        negative = round(int(row["negative"]) / total * 100, 1)
        neutral  = round(int(row["neutral"])  / total * 100, 1)
        # Rounding to 1dp can leave shares at 99.9/100.1; fix on the largest.
        drift = round(100 - (positive + negative + neutral), 1)
        if drift:
            largest = max(
                (("positive", positive), ("negative", negative), ("neutral", neutral)),
                key=lambda p: p[1],
            )
            if largest[0] == "positive":
                positive = round(positive + drift, 1)
            elif largest[0] == "negative":
                negative = round(negative + drift, 1)
            else:
                neutral = round(neutral + drift, 1)

        series.append({
            "date":           row["date"],
            "positive":       positive,
            "negative":       negative,
            "neutral":        neutral,
            "total_articles": total,
        })
    return series


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _category_route(category):
    def handler():
        try:
            articles = fetch_articles(category)
        except Exception as error:
            return jsonify({"error": f"Database error: {error}"}), 500
        return jsonify(articles)   # empty list = 200 [], frontend handles it
    handler.__name__ = f"fetch_{category}"
    return handler


app.add_url_rule("/api/generalndtv", "fetch_general",       _category_route("general"),       methods=["GET"])
app.add_url_rule("/api/cricketndtv", "fetch_cricket",       _category_route("cricket"),        methods=["GET"])
app.add_url_rule("/api/worldndtv",   "fetch_world",         _category_route("world"),          methods=["GET"])
app.add_url_rule("/api/healthndtv",  "fetch_health",        _category_route("health"),         methods=["GET"])
app.add_url_rule("/api/edundtv",     "fetch_education",     _category_route("education"),      methods=["GET"])
app.add_url_rule("/api/sciencendtv", "fetch_science",       _category_route("science"),        methods=["GET"])
app.add_url_rule("/api/enterndtv",   "fetch_entertainment", _category_route("entertainment"),  methods=["GET"])


@app.route("/api/allndtv", methods=["GET"])
def fetch_all_ndtv():
    try:
        articles = fetch_articles()
    except Exception as error:
        return jsonify({"error": f"Database error: {error}"}), 500
    return jsonify(articles)


@app.route("/api/sentiment-trends", methods=["GET"])
def fetch_sentiment_trends():
    try:
        series = build_trend_series()
    except Exception as error:
        return jsonify({"error": f"Database error: {error}"}), 500
    return jsonify(series)


if __name__ == "__main__":
    app.run()
