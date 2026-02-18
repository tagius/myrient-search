"""Smart incremental sync for keeping the index up-to-date."""
import asyncio
import logging

from indexer.database import Database
from indexer.crawler import MyrientCrawler

logger = logging.getLogger(__name__)


async def run_sync(db: Database, full: bool = False):
    """Run a sync operation.

    Args:
        db: Database instance
        full: If True, ignore cached ETags and re-crawl everything.
              If False, use incremental sync (skip unchanged directories).
    """
    state = db.get_crawl_state()
    if state and state.get("status") == "crawling":
        logger.warning("Crawl already in progress, skipping")
        return

    logger.info("Starting %s sync", "full" if full else "incremental")
    crawler = MyrientCrawler(db, incremental=not full)

    try:
        await crawler.crawl()
    except Exception as e:
        logger.error("Sync failed: %s", e)
        db.update_crawl_state(
            status="error",
            message=f"Sync failed: {e}"
        )
        raise


def run_sync_blocking(db: Database, full: bool = False):
    """Blocking wrapper for run_sync (used by scheduler)."""
    asyncio.run(run_sync(db, full=full))
