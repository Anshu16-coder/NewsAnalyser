"""NewsAnalyser — read-only Flask API + static site.

This app does no scraping. Articles are written to MySQL by scraper.py, which
GitHub Actions runs daily (see .github/workflows/scrape.yml). Run it locally
with:  python scraper.py

The API returns exactly the JSON shape the frontend already consumes:
    link, headline, datetime_posted, content, category, analysis_result
"""

import os

from flask import Flask, jsonify, send_from_directory, request, abort
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Serve the HTML/CSS/JS from the project root so the pages and the API share
# one origin. Without this the pages have to be opened as file:// URLs, where
# relative fetch() calls like /api/allndtv cannot be resolved at all.
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
CORS(app)


@app.route("/")
def send_index():
    return send_from_directory(BASE_DIR, "index.html")


@app.before_request
def block_data_file_exposure():
    # The static folder is the project root. Keep the legacy CSVs and any
    # .env out of reach of the web; only the API should hand out article data.
    path = request.path.lower()
    if path.endswith(".csv") or path.endswith(".env") or "/.git" in path:
        abort(404)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_connection():
    """Open a MySQL connection from the DB_* environment variables.

    Imports db.py so the scraper and the site cannot drift apart on which
    variables they read. On Vercel the env vars are set in project settings;
    locally they come from .env (see python-dotenv in requirements.txt).
    """
    from db import get_connection as _get_connection
    return _get_connection()


def fetch_articles(category=None):
    """Return article rows, newest first.

    Category names are matched against a fixed allowlist and bound as query
    parameters, so this stays a parameterised query with no injection surface.
    """
    allowed = {
        "general", "cricket", "world", "health",
        "education", "science", "entertainment",
    }
    columns = """
        SELECT link, headline, datetime_posted, content, category, analysis_result
    """
    order = " ORDER BY COALESCE(published_at, scraped_at) DESC, id DESC"

    if category is None:
        sql = columns + " FROM articles" + order
        params = ()
    else:
        if category not in allowed:
            raise ValueError(f"Unknown category: {category}")
        sql = columns + " FROM articles WHERE category = %s" + order
        params = (category,)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    for row in rows:
        for key in ("published_at", "scraped_at"):
            if row.get(key) is not None:
                row[key] = row[key].isoformat(sep=" ")
    return rows


def build_trend_series():
    """Daily positive/negative/neutral percentages, oldest first.

    Grouping happens in SQL against the published_on column, so this is a
    single indexed scan instead of re-parsing a display string per row on
    every request.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    published_on AS date,
                    SUM(analysis_result = 'Positive') AS positive,
                    SUM(analysis_result = 'Negative') AS negative,
                    SUM(analysis_result = 'Neutral')  AS neutral,
                    COUNT(*)                         AS total_articles
                FROM articles
                WHERE published_on IS NOT NULL
                GROUP BY published_on
                ORDER BY published_on ASC
            """)
            rows = cursor.fetchall()

    series = []
    for row in rows:
        total = int(row["total_articles"])
        if not total:
            continue
        positive = round(int(row["positive"]) / total * 100, 1)
        negative = round(int(row["negative"]) / total * 100, 1)
        neutral = round(int(row["neutral"]) / total * 100, 1)
        # Rounding to 1dp can leave the three shares at 99.9 or 100.1; push
        # the difference onto the largest share so each day totals 100.
        drift = round(100 - (positive + negative + neutral), 1)
        if drift:
            largest = max((("positive", positive), ("negative", negative), ("neutral", neutral)),
                          key=lambda pair: pair[1])
            if largest[0] == "positive":
                positive = round(positive + drift, 1)
            elif largest[0] == "negative":
                negative = round(negative + drift, 1)
            else:
                neutral = round(neutral + drift, 1)

        date = row["date"]
        series.append({
            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "total_articles": total,
        })
    return series


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _category_route(category):
    """Build a GET handler for one category."""
    def handler():
        try:
            articles = fetch_articles(category)
        except Exception as error:
            return jsonify({"error": f"Database error: {error}"}), 500
        if not articles:
            return jsonify({"message": "No articles found."}), 404
        return jsonify(articles)
    handler.__name__ = f"fetch_{category}"
    return handler


app.add_url_rule("/api/generalndtv", "fetch_general", _category_route("general"), methods=["GET"])
app.add_url_rule("/api/cricketndtv", "fetch_cricket", _category_route("cricket"), methods=["GET"])
app.add_url_rule("/api/worldndtv",   "fetch_world",   _category_route("world"),   methods=["GET"])
app.add_url_rule("/api/healthndtv",  "fetch_health",  _category_route("health"),  methods=["GET"])
app.add_url_rule("/api/edundtv",     "fetch_education", _category_route("education"), methods=["GET"])
app.add_url_rule("/api/sciencendtv", "fetch_science", _category_route("science"), methods=["GET"])
app.add_url_rule("/api/enterndtv",   "fetch_entertainment", _category_route("entertainment"), methods=["GET"])


@app.route("/api/allndtv", methods=["GET"])
def fetch_all_ndtv():
    try:
        articles = fetch_articles()
    except Exception as error:
        return jsonify({"error": f"Database error: {error}"}), 500
    if not articles:
        return jsonify({"message": "No articles found."}), 404
    return jsonify(articles)


@app.route("/api/sentiment-trends", methods=["GET"])
def fetch_sentiment_trends():
    try:
        series = build_trend_series()
    except Exception as error:
        return jsonify({"error": f"Database error: {error}"}), 500
    if not series:
        return jsonify({"message": "No trend data available."}), 404
    return jsonify(series)


if __name__ == "__main__":
    app.run()
