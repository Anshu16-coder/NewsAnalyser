-- NewsAnalyser — MySQL schema
--
-- Run once against your database to create the table:
--     mysql -h HOST -u USER -p < schema.sql
--
-- scraper.py applies this automatically on every run, so running it manually
-- is only needed if you want the table to exist before the first scrape.

CREATE TABLE IF NOT EXISTS articles (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    -- Google News RSS hands back redirect URLs up to ~800 chars, so this is
    -- sized for those rather than the ~190-char NDTV ones.
    link            VARCHAR(1024)   NOT NULL,
    headline        VARCHAR(512)    NOT NULL,
    content         TEXT,
    category        VARCHAR(32)     NOT NULL,
    -- When the publisher posted it. Naive local (IST) time, as published.
    published_at    DATETIME        NULL,
    -- Date-only projection of published_at, so the trends query is a plain
    -- GROUP BY instead of re-parsing a display string on every request.
    published_on    DATE            NULL,
    scraped_at      DATETIME        NOT NULL,
    analysis_result ENUM('Positive', 'Negative', 'Neutral') NOT NULL DEFAULT 'Neutral',
    PRIMARY KEY (id),
    -- Scraper runs many times a day; this is what makes re-runs idempotent.
    -- MySQL caps a utf8mb4 index key at 3072 bytes = 768 chars, so this stays
    -- within range. Past that the fix is a hash column, not a wider VARCHAR.
    UNIQUE KEY uq_articles_link (link),
    KEY idx_articles_category_published (category, published_on),
    KEY idx_articles_published_on (published_on),
    KEY idx_articles_sentiment (analysis_result)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci;
