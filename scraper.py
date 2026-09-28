"""scraper.py — scrape NDTV, analyse sentiment, store in MySQL.

Run it directly to do one pass; GitHub Actions runs it daily on a schedule:

    python scraper.py

Self-contained on purpose: feed config, RSS parsing, relevance filtering,
sentiment, and the database write all live here, so the scheduled job needs
nothing but this file plus schema.sql.

Feed strategy per category:
  general/cricket/world : dedicated NDTV Feedburner feeds, no filtering needed
  health/education      : Google News RSS scoped to site:ndtv.com, then keyword
  science/entertainment  : filtered, because the matching NDTV feeds are
                          either missing or emit malformed XML
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime as dt

import requests
from textblob import TextBlob

from db import ensure_schema, get_connection

# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    "general":   "https://feeds.feedburner.com/ndtvnews-latest",
    "cricket":   "https://feeds.feedburner.com/ndtvsports-cricket",
    "world":     "https://feeds.feedburner.com/ndtvnews-world-news",
    "health": (
        "https://news.google.com/rss/search"
        "?q=site:ndtv.com+health+OR+medical+OR+disease+OR+hospital+OR+wellness"
        "+OR+nutrition+OR+medicine+OR+diet+OR+doctor&hl=en-IN&gl=IN&ceid=IN:en"
    ),
    "education": (
        "https://news.google.com/rss/search"
        "?q=site:ndtv.com+education+OR+school+OR+exam+OR+university+OR+CBSE"
        "+OR+college+OR+student+OR+admission+OR+IIT+OR+NEET&hl=en-IN&gl=IN&ceid=IN:en"
    ),
    "science": (
        "https://news.google.com/rss/search"
        "?q=site:ndtv.com+science+OR+space+OR+NASA+OR+research+OR+discovery"
        "+OR+planet+OR+asteroid+OR+genome+OR+fossil+OR+physics&hl=en-IN&gl=IN&ceid=IN:en"
    ),
    "entertainment": (
        "https://news.google.com/rss/search"
        "?q=site:ndtv.com+entertainment+OR+bollywood+OR+movie+OR+film+OR+actor"
        "+OR+actress+OR+celebrity+OR+music+OR+concert+OR+OTT&hl=en-IN&gl=IN&ceid=IN:en"
    ),
}

# Categories whose feed is not already on-topic. An article is kept only if
# headline + content contains at least one of these keywords.
CATEGORY_KEYWORDS = {
    "health": [
        "health", "medical", "disease", "hospital", "doctor", "patient",
        "medicine", "drug", "vaccine", "virus", "bacteria", "cancer",
        "diabetes", "surgery", "nutrition", "diet", "wellness", "mental health",
        "therapy", "clinic", "pandemic", "epidemic", "symptom", "treatment",
        "blood pressure", "heart", "lung", "kidney", "obesity", "fitness",
        "exercise", "ayurveda", "yoga", "stress", "anxiety", "depression",
        "who", "icmr", "aiims", "pharmacy", "antibiotic", "infection",
    ],
    "education": [
        "school", "college", "university", "exam", "student", "cbse", "icse",
        "education", "board", "admission", "academic", "class", "result",
        "degree", "course", "teacher", "learning", "scholarship", "campus",
        "jee", "neet", "upsc", "iit", "iim", "nit", "nta", "ugc", "aicte",
        "syllabus", "curriculum", "textbook", "faculty", "professor",
        "lecture", "tuition", "coaching", "placement", "graduation",
        "phd", "research degree", "distance education", "e-learning",
    ],
    "science": [
        "science", "scientist", "research", "discovery", "space", "nasa",
        "isro", "asteroid", "planet", "quantum", "physics", "biology",
        "chemistry", "rover", "telescope", "genome", "dna", "experiment",
        "fossil", "species", "universe", "galaxy", "satellite", "comet",
        "meteor", "particle", "radiation", "climate", "atmosphere",
        "geological", "archaeological", "dinosaur", "evolution", "mars",
        "moon", "solar system", "black hole", "supernova", "exoplanet",
        "laboratory", "microscope", "gene", "protein", "enzyme", "cell",
        "ecology", "biodiversity", "carbon", "energy", "quantum computing",
        "launch", "orbit", "mission", "probe", "rocket",
    ],
    "entertainment": [
        "movie", "film", "actor", "actress", "bollywood", "celebrity",
        "music", "song", "concert", "television", "tv show", "series",
        "cinema", "director", "award", "oscar", "filmfare", "box office",
        "entertainment", "streaming", "ott", "netflix", "amazon prime",
        "disney+", "hotstar", "star", "singer", "dance", "fashion",
        "web series", "trailer", "release", "premiere", "shooting",
        "casting", "script", "producer", "studio", "hollywood",
        "shah rukh", "salman", "aamir", "deepika", "priyanka", "ranveer",
        "ranbir", "karan johar", "rohit shetty", "south film", "kollywood",
        "tollywood", "playback", "album", "single", "music video",
    ],
}

_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

def get_sentiment(text) -> str:
    """TextBlob polarity bucketed into the three categories the site displays."""
    try:
        polarity = TextBlob(str(text)).sentiment.polarity
    except Exception:
        return "Neutral"
    if polarity > 0:
        return "Positive"
    if polarity < 0:
        return "Negative"
    return "Neutral"


# ---------------------------------------------------------------------------
# Date handling
# ---------------------------------------------------------------------------

# The site shows "May 03, 2025 04:10 am"; keep the API contract identical.
_PREFERRED_OUT = "%B %d, %Y %I:%M %p"
_PARSE_FORMATS = [
    "%B %d, %Y %I:%M %p", "%B %d, %Y", "%d %B %Y", "%Y-%m-%d",
    "%d/%m/%Y", "%m/%d/%Y", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
]
_PREFIXES = ("updated:", "published on:", "posted on:")


def _parse_pub_date(pub_date: str):
    """RSS pubDate -> (display_string, datetime). Either may be None."""
    if not pub_date:
        return None, None

    from email.utils import parsedate_to_datetime
    for parser in (
        lambda value: parsedate_to_datetime(value),
        lambda value: dt.fromisoformat(value.replace("Z", "+00:00")),
    ):
        try:
            parsed = parser(pub_date)
            if parsed is not None:
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                return parsed.strftime(_PREFERRED_OUT), parsed
        except Exception:
            continue

    return (pub_date or "").strip() or None, None


def _normalise_for_sort(value: str) -> str:
    """Strip publisher prefixes/timezones the frontend strips before parsing."""
    cleaned = str(value).strip()
    for prefix in _PREFIXES:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return re.sub(r"\s*IST\b", "", cleaned, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# RSS fetching
# ---------------------------------------------------------------------------

def _sanitise_xml(raw_bytes: bytes) -> bytes:
    """Make bytes xml.etree can parse: unwrap HTML, strip scripts, fix bare &."""
    text = raw_bytes.decode("utf-8", errors="replace")

    rss_match = re.search(r"(<rss\b.*?</rss>)", text, flags=re.DOTALL | re.IGNORECASE)
    if rss_match:
        text = rss_match.group(1)

    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    return text.encode("utf-8")


def _fetch_rss(url: str, timeout: int = 18) -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsAnalyserRSSReader/3.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as error:
        print(f"  [rss] network error: {error}")
        return []

    if response.status_code != 200:
        print(f"  [rss] HTTP {response.status_code}")
        return []

    try:
        root = ET.fromstring(_sanitise_xml(response.content))
    except ET.ParseError as error:
        print(f"  [rss] XML parse error: {error}")
        return []

    items = root.findall(".//item")
    if not items:
        print("  [rss] feed returned 0 items")
        return []

    articles = []
    for item in items:
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        link = re.sub(r"#(?:publisher|publish).*$", "", link)
        headline = (item.findtext("title") or "").strip()
        headline = re.sub(r"\s+-\s+NDTV\s*$", "", headline, flags=re.IGNORECASE).strip()
        if not link or not headline:
            continue

        display_date, published_at = _parse_pub_date((item.findtext("pubDate") or "").strip())

        raw_content = (
            item.findtext(f"{{{_CONTENT_NS}}}encoded")
            or item.findtext("description")
            or ""
        )
        content = re.sub(r"<[^>]+>", " ", raw_content).strip()
        content = re.sub(r"\s{2,}", " ", content)

        articles.append({
            "link": link,
            "headline": headline,
            "content": content,
            "datetime_posted": display_date or "",
            "published_at": published_at,
        })

    print(f"  [rss] parsed {len(articles)} items")
    return articles


def _is_relevant(article: dict, keywords: list) -> bool:
    text = (article.get("headline", "") + " " + article.get("content", "")).lower()
    return any(keyword.lower() in text for keyword in keywords)


def scrape_category(category: str) -> list:
    """Fetch and relevance-filter one category. Returns raw article dicts."""
    articles = _fetch_rss(RSS_FEEDS[category])

    keywords = CATEGORY_KEYWORDS.get(category)
    if keywords and articles:
        before = len(articles)
        articles = [a for a in articles if _is_relevant(a, keywords)]
        print(f"  [filter] {len(articles)}/{before} passed the {category} keyword check")

    return articles


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

_INSERT_SQL = """
    INSERT INTO articles
        (link, headline, content, category, published_at, published_on, scraped_at, analysis_result)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        -- Refresh the derived columns on re-scrape; headline/content stay as first seen.
        published_at    = COALESCE(VALUES(published_at), published_at),
        published_on    = COALESCE(VALUES(published_on), published_on),
        analysis_result = VALUES(analysis_result)
"""


def store_articles(connection, category: str, articles: list) -> tuple:
    """Insert articles, skipping links already stored.

    Returns (new_count, refreshed_count). ON DUPLICATE KEY still backs the
    write so a concurrent run can't trip the unique key, but the counts are
    derived from a pre-check because MySQL's rowcount lumps inserts and
    updates together.
    """
    if not articles:
        return 0, 0

    links = [article["link"] for article in articles]
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT link FROM articles WHERE link IN ({_placeholders(len(links))})",
            links,
        )
        seen = {row["link"] for row in cursor.fetchall()}

    scraped_at = dt.now().replace(microsecond=0)
    rows = []
    for article in articles:
        published_at = article.get("published_at")
        rows.append((
            article["link"],
            article["headline"],
            article.get("content", ""),
            category,
            published_at,
            published_at.date() if published_at else None,
            scraped_at,
            get_sentiment(article.get("content") or article["headline"]),
        ))

    with connection.cursor() as cursor:
        cursor.executemany(_INSERT_SQL, rows)

    return len(links) - len(seen), len(seen)


def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    started = dt.now()
    print(f"Scraper started {started:%Y-%m-%d %H:%M:%S}")

    try:
        connection = get_connection()
    except Exception as error:
        print(f"Fatal: {error}")
        return 1

    total = 0
    try:
        ensure_schema(connection)
        for category in RSS_FEEDS:
            print(f"\n[{category}] scraping")
            try:
                articles = scrape_category(category)
                new_n, refreshed_n = store_articles(connection, category, articles)
                connection.commit()
                total += new_n
                print(f"[{category}] {new_n} new · {refreshed_n} refreshed")
            except Exception as error:
                connection.rollback()
                # One bad feed must not abort the remaining categories.
                print(f"[{category}] failed: {error}")
    finally:
        connection.close()

    print(f"\nDone in {(dt.now() - started).seconds}s — {total} new article(s) stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
