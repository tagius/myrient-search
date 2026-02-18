# Myrient Search Engine — Project Plan

## Overview
A lightweight, self-hosted search engine for [Myrient](https://myrient.erista.me/files/),
a 390TB+ game preservation archive with 13M+ files. Designed to run on UmbrelOS
as a single Docker container.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Docker Container                 │
│                                                  │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
│  │ Crawler/ │   │ FastAPI  │   │  Frontend   │  │
│  │ Indexer  │──▶│ Backend  │◀──│ (static)    │  │
│  └──────────┘   └────┬─────┘   └─────────────┘  │
│                      │                           │
│               ┌──────▼──────┐                    │
│               │   SQLite    │                    │
│               │  + FTS5     │                    │
│               └─────────────┘                    │
└─────────────────────────────────────────────────┘
```

### Why this stack?
- **Python + FastAPI**: async-native, great for crawling, easy AI integration later
- **SQLite + FTS5**: zero extra services, built-in full-text search, ~single file DB
- **Vanilla HTML/CSS/JS**: zero build step, fast, easy to maintain
- **Single container**: minimal resource usage for a home server

## Project Structure

```
myrient-search/
├── PLAN.md                  # This file
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── config.py                # Configuration & env vars
│
├── indexer/
│   ├── __init__.py
│   ├── crawler.py           # Async HTTP directory crawler
│   ├── parser.py            # HTML directory listing parser
│   ├── database.py          # SQLite schema + FTS5 setup
│   └── sync.py              # Smart incremental sync logic
│
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── search.py            # Search API endpoints
│   └── models.py            # Pydantic response models
│
├── frontend/
│   ├── index.html           # Main search page
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── app.js           # Search logic, filtering, UI
│   └── assets/
│       └── logo.svg
│
└── data/                    # Mounted volume for persistence
    └── myrient.db           # SQLite database (generated)
```

## Phase 1: Indexer / Crawler

### How Myrient directory listings work
- Standard HTTP directory index (Apache/nginx style)
- Each page is an HTML table with: filename, last-modified date, file size
- Directories end with `/`, files have extensions (.zip, .7z, etc.)
- URL pattern: `https://myrient.erista.me/files/{collection}/{platform}/{file}`
- Depth varies: 2-5+ levels depending on collection

### Crawling strategy
1. Start at `/files/` — fetch top-level collections
2. For each directory, parse the HTML listing to extract:
   - Entry name (file or subdirectory)
   - Last-Modified date
   - File size (for files)
   - Full URL path
3. Recurse into subdirectories
4. Store everything in SQLite

### Rate limiting & politeness
- Configurable concurrent requests (default: 5)
- Configurable delay between requests (default: 100ms)
- Respect `Retry-After` headers
- User-Agent: `MyrientSearchIndexer/1.0`
- Estimated initial crawl time: 1-4 hours depending on depth/concurrency

### Database schema
```sql
-- Main file/directory table
CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,       -- Full path from /files/
    name TEXT NOT NULL,              -- Filename or dirname
    is_directory BOOLEAN NOT NULL,
    file_size INTEGER,               -- NULL for directories
    last_modified TEXT,              -- HTTP Last-Modified value
    collection TEXT,                 -- Top-level collection (No-Intro, Redump, etc.)
    platform TEXT,                   -- Platform extracted from path
    parent_path TEXT,                -- Parent directory path
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search virtual table
CREATE VIRTUAL TABLE entries_fts USING fts5(
    name,                            -- Searchable filename
    path,                            -- Searchable full path
    collection,                      -- Filterable collection
    platform,                        -- Filterable platform
    content='entries',
    content_rowid='id'
);

-- Sync metadata for smart updates
CREATE TABLE sync_meta (
    path TEXT PRIMARY KEY,           -- Directory path
    etag TEXT,                       -- HTTP ETag header
    last_modified TEXT,              -- HTTP Last-Modified header
    last_crawled TIMESTAMP,
    entry_count INTEGER              -- Number of entries last time
);

-- Index for fast lookups
CREATE INDEX idx_entries_collection ON entries(collection);
CREATE INDEX idx_entries_platform ON entries(platform);
CREATE INDEX idx_entries_parent ON entries(parent_path);
```

## Phase 2: Smart Incremental Sync

### Strategy
1. **HTTP conditional requests**: Use `If-Modified-Since` and `If-None-Match`
   headers when re-crawling directories. If server returns `304 Not Modified`,
   skip that directory entirely.
2. **Entry count comparison**: Store the number of entries per directory.
   If a directory returns the same count AND passes conditional request,
   skip its children too.
3. **Top-down pruning**: Start from top-level dirs. If a collection hasn't
   changed, skip the entire subtree (potentially millions of files).
4. **Scheduled via cron**: configurable, default monthly.
5. **Diffing**: After re-crawl, compare with existing data:
   - New entries → INSERT
   - Missing entries → mark as removed (soft delete) or DELETE
   - Changed entries (size/date) → UPDATE

### Estimated sync time
- If <5% of directories changed: ~5-15 minutes
- Full re-index fallback: same as initial crawl

## Phase 3: Search Backend (FastAPI)

### API Endpoints
```
GET  /api/search?q=zelda&collection=No-Intro&platform=Nintendo+64&page=1&per_page=50
GET  /api/collections           — List all collections with counts
GET  /api/platforms             — List all platforms with counts
GET  /api/browse/{path}        — Browse a specific directory
GET  /api/stats                — Database statistics
POST /api/sync                 — Trigger manual sync (admin)
GET  /api/sync/status          — Check sync progress
```

### Search features
- **FTS5 full-text search** with ranking (BM25)
- **Filters**: collection, platform, file type
- **Faceted results**: return counts per collection/platform alongside results
- **Pagination**: offset-based with total count
- **Sort**: by relevance, name, date, size

## Phase 4: Frontend

### Design principles
- Clean, Google-inspired search bar (like the reference project)
- Dark theme friendly (for game/retro aesthetic)
- Mobile responsive
- No framework, no build step

### Features
- Search bar with instant results (debounced)
- Filter sidebar: collection dropdown, platform dropdown, file type
- Results list: filename, collection badge, platform, size, direct Myrient link
- Pagination
- Stats bar: total files indexed, last sync date
- Browse mode: navigate the directory tree

## Phase 5: Docker / UmbrelOS

### Dockerfile
- Python 3.11 slim base
- Single stage build
- SQLite comes built-in with Python
- Mount point for `/data` volume (database persistence)
- Expose port 8080

### docker-compose.yml
```yaml
version: '3.8'
services:
  myrient-search:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - CRAWL_CONCURRENCY=5
      - CRAWL_DELAY_MS=100
      - SYNC_SCHEDULE=0 3 1 * *    # 3 AM on 1st of month
    restart: unless-stopped
```

### UmbrelOS compatibility
- Single container, no external dependencies
- Low memory footprint (~100-200MB)
- SQLite DB size estimate: ~500MB-1GB for 13M entries
- Can be added as custom Docker app via Umbrel's app framework

## Future Phases (not in scope now)

- **Phase 6**: IGDB metadata enrichment (game covers, ratings, descriptions)
- **Phase 7**: AI advisor chatbot (game recommendations)
- **Phase 8**: UmbrelOS app store packaging

## Open questions resolved
- ✅ Stack: Python + FastAPI + SQLite FTS5
- ✅ Frontend: Vanilla HTML/CSS/JS
- ✅ Deployment: Single Docker container
- ✅ Reference repo: will be cloned for study
