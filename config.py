"""Configuration for Myrient Search Engine."""
import os
from pathlib import Path

# Base URL
MYRIENT_BASE_URL = os.getenv("MYRIENT_BASE_URL", "https://myrient.erista.me/files/")

# Paths
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "myrient.db"

# Crawler settings
CRAWL_CONCURRENCY = int(os.getenv("CRAWL_CONCURRENCY", "10"))
CRAWL_DELAY_MS = int(os.getenv("CRAWL_DELAY_MS", "50"))
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "30"))
USER_AGENT = "MyrientSearchIndexer/1.0 (+https://github.com/tagius/myrient-search)"

# Sync schedule (cron expression: default = 3 AM on 1st of month)
SYNC_SCHEDULE = os.getenv("SYNC_SCHEDULE", "0 3 1 * *")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Search
RESULTS_PER_PAGE = int(os.getenv("RESULTS_PER_PAGE", "50"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "10000"))
