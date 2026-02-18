"""Quick test: crawl just a few directories from Myrient to validate the pipeline."""
import asyncio
import sys
import os
import logging

# Ensure we can import from project root
sys.path.insert(0, os.path.dirname(__file__))

# Override config for testing
os.environ["DATA_DIR"] = os.path.join(os.path.dirname(__file__), "data")

from config import DB_PATH, MYRIENT_BASE_URL
from indexer.database import Database
from indexer.parser import parse_directory_listing, build_entry, extract_platform, extract_region

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def test_fetch_and_parse():
    """Fetch the root directory and a couple of subdirectories."""
    import aiohttp

    db = Database(DB_PATH)
    db.initialize()
    logger.info("Database initialized at %s", DB_PATH)

    async with aiohttp.ClientSession(
        headers={"User-Agent": "MyrientSearchTest/1.0"}
    ) as session:

        # 1. Fetch root listing
        logger.info("Fetching root: %s", MYRIENT_BASE_URL)
        async with session.get(MYRIENT_BASE_URL) as resp:
            html = await resp.text()
            logger.info("Root page: HTTP %d, %d bytes", resp.status, len(html))

        entries = parse_directory_listing(html)
        logger.info("Root has %d entries", len(entries))

        # Show first 10 entries
        for e in entries[:10]:
            logger.info("  %s %s (size=%s, dir=%s)",
                        "DIR" if e["is_directory"] else "FILE",
                        e["name"], e["size"], e["is_directory"])

        # Build and insert root entries
        root_db_entries = []
        first_subdir = None
        for e in entries:
            entry = build_entry(e["href"], e["name"], e["is_directory"],
                                e["size"], e["date"], "")
            root_db_entries.append(entry)
            if e["is_directory"] and first_subdir is None:
                first_subdir = e["name"]

        db.insert_entries_batch(root_db_entries)
        logger.info("Inserted %d root entries into DB", len(root_db_entries))

        # 2. Fetch a subdirectory to test deeper parsing
        if first_subdir:
            sub_url = MYRIENT_BASE_URL + first_subdir + "/"
            logger.info("Fetching subdirectory: %s", sub_url)
            async with session.get(sub_url) as resp:
                html = await resp.text()

            sub_entries = parse_directory_listing(html)
            logger.info("Subdirectory '%s' has %d entries", first_subdir, len(sub_entries))

            sub_db_entries = []
            for e in sub_entries[:50]:  # Limit for test
                entry = build_entry(e["href"], e["name"], e["is_directory"],
                                    e["size"], e["date"], first_subdir + "/")
                sub_db_entries.append(entry)
                logger.info("  %s %s → collection=%s, platform=%s, region=%s",
                            "DIR" if e["is_directory"] else "FILE",
                            e["name"][:60],
                            entry["collection"], entry["platform"], entry["region"])

            db.insert_entries_batch(sub_db_entries)
            logger.info("Inserted %d sub-entries into DB", len(sub_db_entries))

            # 2b. Go one level deeper if there's a subdirectory
            deeper_dir = next((e for e in sub_entries if e["is_directory"]), None)
            if deeper_dir:
                deeper_path = first_subdir + "/" + deeper_dir["name"] + "/"
                deeper_url = MYRIENT_BASE_URL + deeper_path
                logger.info("Fetching deeper: %s", deeper_url)
                async with session.get(deeper_url) as resp:
                    html = await resp.text()

                deeper_entries = parse_directory_listing(html)
                logger.info("Deep dir '%s' has %d entries", deeper_dir["name"], len(deeper_entries))

                deeper_db_entries = []
                for e in deeper_entries[:30]:
                    entry = build_entry(e["href"], e["name"], e["is_directory"],
                                        e["size"], e["date"], deeper_path)
                    deeper_db_entries.append(entry)

                db.insert_entries_batch(deeper_db_entries)
                logger.info("Inserted %d deep entries into DB", len(deeper_db_entries))

    # 3. Test search
    logger.info("\n── Testing search ──")
    stats = db.get_stats()
    logger.info("DB stats: %s", stats)

    # Search for anything
    collections = db.get_collections()
    logger.info("Collections: %s", [(c["collection"], c["count"]) for c in collections[:10]])

    # Try a search query if we have files
    if stats["total_files"] > 0:
        results = db.search("Nintendo", page=1, per_page=5)
        logger.info("Search 'Nintendo': %d total results", results["total"])
        for r in results["results"]:
            logger.info("  → %s (collection=%s)", r["name"][:60], r["collection"])

    logger.info("\nTest complete!")


if __name__ == "__main__":
    asyncio.run(test_fetch_and_parse())
