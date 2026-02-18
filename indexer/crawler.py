"""Async crawler for Myrient HTTP directory listings."""
import asyncio
import logging
import time
from urllib.parse import urljoin, quote, unquote

import aiohttp

from config import (
    MYRIENT_BASE_URL, CRAWL_CONCURRENCY, CRAWL_DELAY_MS, CRAWL_TIMEOUT, USER_AGENT
)
from indexer.database import Database  # also used for compute_content_hash
from indexer.parser import parse_directory_listing, build_entry, _normalize_path

logger = logging.getLogger(__name__)

# Batch size for DB inserts
BATCH_SIZE = 1000


class MyrientCrawler:
    """Async recursive crawler for Myrient file listings."""

    def __init__(self, db: Database, incremental: bool = True):
        self.db = db
        self.incremental = incremental
        self.semaphore = asyncio.Semaphore(CRAWL_CONCURRENCY)
        self.delay = CRAWL_DELAY_MS / 1000.0
        self.stats = {
            "dirs_crawled": 0,
            "dirs_skipped": 0,
            "files_found": 0,
            "errors": 0,
            "start_time": 0,
        }
        self._entry_buffer: list[dict] = []
        self._buffer_lock = asyncio.Lock()

    async def crawl(self):
        """Start the full crawl from the root."""
        self.stats["start_time"] = time.time()
        self.db.update_crawl_state(
            status="crawling",
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            dirs_crawled=0, files_found=0, errors=0,
            message="Starting crawl..."
        )

        logger.info("Starting crawl of %s (incremental=%s, concurrency=%d)",
                     MYRIENT_BASE_URL, self.incremental, CRAWL_CONCURRENCY)

        timeout = aiohttp.ClientTimeout(total=CRAWL_TIMEOUT)
        connector = aiohttp.TCPConnector(limit=CRAWL_CONCURRENCY, ttl_dns_cache=300)

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": USER_AGENT}
        ) as session:
            await self._crawl_directory(session, "")

        # Flush remaining buffer
        await self._flush_buffer()

        elapsed = time.time() - self.stats["start_time"]
        msg = (
            f"Crawl complete in {elapsed:.0f}s: "
            f"{self.stats['dirs_crawled']} dirs, "
            f"{self.stats['files_found']} files, "
            f"{self.stats['dirs_skipped']} skipped, "
            f"{self.stats['errors']} errors"
        )
        logger.info(msg)

        self.db.update_crawl_state(
            status="idle",
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            dirs_crawled=self.stats["dirs_crawled"],
            files_found=self.stats["files_found"],
            errors=self.stats["errors"],
            message=msg
        )

    async def _crawl_directory(self, session: aiohttp.ClientSession, rel_path: str):
        """Crawl a single directory and recurse into subdirectories."""
        # Normalize to strip any stray './' segments before doing anything
        rel_path = _normalize_path(rel_path)
        url = urljoin(MYRIENT_BASE_URL, quote(rel_path, safe="/"))

        # ── Fetch and parse directory ──
        try:
            async with self.semaphore:
                await asyncio.sleep(self.delay)
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        logger.warning("HTTP %d for %s", resp.status, url)
                        self.stats["errors"] += 1
                        return

                    html = await resp.text()
                    etag = resp.headers.get("ETag")
                    last_modified = resp.headers.get("Last-Modified")

        except asyncio.TimeoutError:
            logger.warning("Timeout fetching %s", url)
            self.stats["errors"] += 1
            return
        except Exception as e:
            logger.warning("Error fetching %s: %s", url, e)
            self.stats["errors"] += 1
            return

        # Parse listing
        raw_entries = parse_directory_listing(html)
        self.stats["dirs_crawled"] += 1

        # Update crawl state periodically
        if self.stats["dirs_crawled"] % 100 == 0:
            elapsed = time.time() - self.stats["start_time"]
            self.db.update_crawl_state(
                dirs_crawled=self.stats["dirs_crawled"],
                files_found=self.stats["files_found"],
                errors=self.stats["errors"],
                message=f"Crawling... {self.stats['dirs_crawled']} dirs, "
                        f"{self.stats['files_found']} files ({elapsed:.0f}s)"
            )

        # ── Content-hash change detection ──
        # Compare hash of current listing with stored hash.
        # If identical, skip all DB writes (huge speedup for unchanged dirs).
        content_hash = Database.compute_content_hash(raw_entries)
        skip_db_writes = False

        if self.incremental:
            sync_meta = self.db.get_sync_meta(rel_path)
            if sync_meta and sync_meta.get("content_hash") == content_hash:
                self.stats["dirs_skipped"] += 1
                skip_db_writes = True
                logger.debug("Skipped DB writes (hash match): %s", rel_path or "/")

        # Build entries and collect subdirectories
        subdirs = []
        current_names = set()
        entries_to_insert = []

        for raw in raw_entries:
            name = raw["name"]

            # Skip current-directory entries completely — these cause
            # infinite recursion and generate duplicate paths with './'
            if name in (".", "./"):
                continue

            current_names.add(name)

            if not skip_db_writes:
                entry = build_entry(
                    href=raw["href"],
                    name=name,
                    is_directory=raw["is_directory"],
                    size=raw["size"],
                    date=raw["date"],
                    parent_url_path=rel_path,
                )
                entries_to_insert.append(entry)

            if raw["is_directory"]:
                # Build the relative path for recursion, then normalize
                sub_path = rel_path + name + "/" if rel_path else name + "/"
                sub_path = _normalize_path(sub_path)

                # Safety: skip any path that still contains '.' segments
                if "/." in sub_path or sub_path.startswith("."):
                    logger.debug("Skipping suspicious subdir path: %s", sub_path)
                    continue

                subdirs.append(sub_path)
            else:
                self.stats["files_found"] += 1

        if not skip_db_writes:
            # Buffer entries for batch insertion
            async with self._buffer_lock:
                self._entry_buffer.extend(entries_to_insert)
                if len(self._entry_buffer) >= BATCH_SIZE:
                    batch = self._entry_buffer[:BATCH_SIZE]
                    self._entry_buffer = self._entry_buffer[BATCH_SIZE:]
                    self.db.insert_entries_batch(batch)

            # Update sync metadata with content hash
            self.db.upsert_sync_meta(rel_path, etag, last_modified,
                                     len(raw_entries), content_hash)

            # Remove stale entries (files/dirs no longer listed)
            if self.incremental:
                self.db.remove_missing_entries(rel_path, current_names)

        # Recurse into subdirectories concurrently
        if subdirs:
            tasks = [self._crawl_directory(session, sub) for sub in subdirs]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _flush_buffer(self):
        """Flush any remaining entries in the buffer."""
        async with self._buffer_lock:
            if self._entry_buffer:
                self.db.insert_entries_batch(self._entry_buffer)
                self._entry_buffer = []
