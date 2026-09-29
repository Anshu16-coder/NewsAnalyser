CREATE TABLE IF NOT EXISTS articles (
    id              SERIAL PRIMARY KEY,
    link            VARCHAR(1024) NOT NULL,
    headline        VARCHAR(512) NOT NULL,
    content         TEXT,
    category        VARCHAR(32) NOT NULL,
    published_at    TIMESTAMP WITH TIME ZONE,
    published_on    DATE,
    scraped_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    datetime_posted VARCHAR(32) NOT NULL DEFAULT '',
    analysis_result VARCHAR(32) NOT NULL DEFAULT 'Neutral',
    UNIQUE (link)
);

CREATE INDEX IF NOT EXISTS idx_articles_category_published ON articles (category, published_on);
CREATE INDEX IF NOT EXISTS idx_articles_published_on ON articles (published_on);
CREATE INDEX IF NOT EXISTS idx_articles_sentiment ON articles (analysis_result);
