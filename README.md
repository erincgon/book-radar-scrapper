# BookRadar Engine

RSS-first book and literary article ingestion backend. Migrated from the StreamRadar movie/TV scraper with reusable infrastructure preserved and movie-specific logic removed.

## Architecture

```
RSS Feeds → Scrapers → Normalization → Deduplication → AI Summary → JSON / Firebase
```

### Project layout

```
scrapers/          RSS ingestion (books, publishers, reviews)
services/          Normalization, dedupe, AI, Firebase, pipeline
models/            Unified BookItem schema
utils/             HTTP client, RSS parser, HTML cleaner, logging, JSON export
config/            Settings, feed registry, env configuration
scheduler/         Hourly refresh, retry, cleanup jobs
output/            Generated JSON feeds (StreamRadar-compatible export)
```

## Migration from StreamRadar

| StreamRadar | BookRadar Engine |
|---|---|
| `ContentItem` (movie/TV) | `BookItem` (books/articles) |
| TMDB image enrichment | RSS/media thumbnails + article og:image |
| Google News + platform scrapers | Direct publisher/literary RSS only |
| Netflix/Disney/HBO scrapers | NYT Books, NPR, LitHub, publishers |
| `utils/pipeline.py` | `services/pipeline_service.py` |
| `config.py` | `config/settings.py` |
| GitHub Actions scrape.yml | `.github/workflows/bookradar.yml` |

**Removed:** TMDB, OpenLibrary, Google Books, Playwright platform scrapers, cast/trailer/episode logic.

**Preserved:** HTTP retry/rate-limit client, JSON export + meta versioning, duplicate protection, structured logging, scheduler pattern, Firebase upload hook.

## Book schema

Each normalized entry:

```json
{
  "id": "",
  "title": "",
  "author": "",
  "description": "",
  "summary_ai": "",
  "categories": [],
  "genre": [],
  "language": "English",
  "publisher": "",
  "published_date": "",
  "thumbnail": "",
  "cover_large": "",
  "article_url": "",
  "source": "",
  "source_type": "rss",
  "tags": [],
  "created_at": "",
  "updated_at": ""
}
```

## RSS sources

Default feeds in `config/settings.py`:

- **Books:** NYT Books, The Guardian Books, Kirkus, Book Smugglers
- **Publishers:** Publishers Weekly, Tor.com, Electric Literature
- **Reviews:** NPR Books, Literary Hub, Book Riot

Override with env vars:

```bash
BOOK_RSS_FEEDS=https://example.com/feed.xml,https://other.com/rss
PUBLISHER_RSS_FEEDS=
REVIEW_RSS_FEEDS=
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

One-shot ingestion:

```bash
python main.py --mode once
```

Background scheduler (hourly RSS, retry, cleanup):

```bash
python main.py --mode scheduler
```

## Firebase collections

When `FIREBASE_ENABLED=true`:

- `books` — all normalized entries
- `trending` — recent books + reviews
- `new_releases` — publisher + book announcements
- `editor_picks` — review highlights
- `categories` — feed index document

## AI summaries (optional)

Set `AI_SUMMARY_ENABLED=true` and `OPENROUTER_API_KEY`. Supported models via `OPENROUTER_MODEL`:

- `google/gemini-flash-1.5`
- `deepseek/deepseek-chat`

## Future *Radar engines

The modular layout is designed to fork for:

- **SoundRadar** — music/podcast RSS feeds
- **AnimeRadar** — anime news RSS
- **GameRadar** — gaming press RSS

Swap feed registries in `config/settings.py` and scraper modules under `scrapers/` without changing the pipeline core.

## Output

JSON files written to `output/`:

- `books.json`, `publishers.json`, `reviews.json`
- `trending.json`, `new_releases.json`, `editor_picks.json`
- `meta.json` — version hash for cache invalidation

Logs: `logs/bookradar.log`
