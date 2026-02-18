# Myrient Search Engine

A lightweight, self-hosted search engine for [Myrient](https://myrient.erista.me/files/) — a 390TB+ game preservation archive with 13M+ files.

Single Docker container. No external databases. SQLite + FTS5 full-text search.

## Quick Start (Docker)

```bash
# 1. Build and start
docker compose up -d

# 2. Open in browser
open http://localhost:8080
```

That's it. On first launch, the crawler automatically starts indexing Myrient in the background. You can watch progress in the web UI (sync banner at top) or check logs:

```bash
docker compose logs -f
```

The initial crawl takes **1–4 hours** depending on your connection. The search works immediately with partial results as indexing progresses.

## Configuration

Edit `.env` to customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAWL_CONCURRENCY` | `10` | Parallel HTTP requests during crawl |
| `CRAWL_DELAY_MS` | `50` | Delay between requests (ms) |
| `SYNC_SCHEDULE` | `0 3 1 * *` | Monthly sync cron (3 AM, 1st of month) |
| `PORT` | `8080` | Web server port |

## Manual Sync

Click **"Sync Now"** in the footer, or via API:

```bash
# Incremental sync (fast — skips unchanged directories)
curl -X POST http://localhost:8080/api/sync

# Full re-crawl
curl -X POST "http://localhost:8080/api/sync?full=true"
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/search?q=zelda` | Full-text search with BM25 ranking |
| `GET /api/search?q=mario&collection=No-Intro&platform=Nintendo+-+SNES` | Filtered search |
| `GET /api/collections` | List collections with counts |
| `GET /api/platforms` | List platforms with counts |
| `GET /api/browse?path=No-Intro/` | Browse directory tree |
| `GET /api/stats` | Index statistics |
| `GET /api/sync/status` | Crawl progress |
| `POST /api/sync` | Trigger manual sync |

## Deploy to UmbrelOS

Copy the project folder to your Umbrel server, then:

```bash
docker compose up -d
```

The SQLite database is stored in a Docker volume (`myrient-data`) and persists across restarts.

## Architecture

```
Single Docker Container (~100–200MB RAM)
├── FastAPI backend (Python 3.12)
├── SQLite + FTS5 (full-text search, ~500MB–1GB DB)
├── Async crawler (aiohttp, rate-limited)
├── APScheduler (monthly sync)
└── Static frontend (vanilla HTML/CSS/JS)
```

## License

MIT
