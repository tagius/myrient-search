"""FastAPI application entry point for Myrient Search Engine."""
import asyncio
import logging
import threading

from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path

from config import DB_PATH, HOST, PORT, SYNC_SCHEDULE
from indexer.database import Database
from indexer.sync import run_sync, run_sync_blocking
from backend.search import router as search_router

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Database
db = Database(DB_PATH)
db.initialize()

# FastAPI app
app = FastAPI(
    title="Myrient Search Engine",
    description="Lightweight search engine for the Myrient game archive",
    version="1.0.0",
)

# Mount API routes
app.include_router(search_router)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
_assets_dir = FRONTEND_DIR / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/")
async def index():
    """Serve the main search page."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.post("/api/sync")
async def trigger_sync(full: bool = False):
    """Trigger a manual sync. Use full=true for complete re-crawl."""
    state = db.get_crawl_state()
    if state and state.get("status") == "crawling":
        return JSONResponse(
            status_code=409,
            content={"detail": "Crawl already in progress"}
        )

    # Run in background thread to not block the server
    thread = threading.Thread(
        target=run_sync_blocking,
        args=(db, full),
        daemon=True
    )
    thread.start()

    return {"message": f"{'Full' if full else 'Incremental'} sync started"}


# ── Scheduled sync ──────────────────────────────────────────────────────

def _setup_scheduler():
    """Set up APScheduler for periodic sync."""
    try:
        parts = SYNC_SCHEDULE.split()
        if len(parts) != 5:
            logger.warning("Invalid SYNC_SCHEDULE '%s', using default", SYNC_SCHEDULE)
            return

        minute, hour, day, month, day_of_week = parts

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_sync_blocking,
            "cron",
            args=[db, False],
            minute=minute,
            hour=hour,
            day=day if day != "*" else None,
            month=month if month != "*" else None,
            day_of_week=day_of_week if day_of_week != "*" else None,
            id="myrient_sync",
            name="Myrient incremental sync",
            misfire_grace_time=3600,
        )
        scheduler.start()
        logger.info("Scheduled sync: %s", SYNC_SCHEDULE)
    except Exception as e:
        logger.error("Failed to set up scheduler: %s", e)


@app.on_event("startup")
async def startup():
    """Run on application startup."""
    logger.info("Myrient Search Engine starting up")
    logger.info("Database: %s", DB_PATH)

    # Reset stale crawl state — if the container was stopped mid-crawl,
    # the status remains "crawling" which blocks everything: the frontend
    # polls /api/sync/status forever, manual sync returns 409, and
    # filters never load because pollSync() prevents loadFilters().
    crawl_state = db.get_crawl_state()
    if crawl_state and crawl_state.get("status") == "crawling":
        logger.warning("Found stale crawl_state='crawling' from previous run — resetting to idle")
        db.update_crawl_state(status="idle", message="Reset after restart")

    # ── Schema migrations (idempotent) ──
    db.migrate_add_content_hash()
    db.migrate_add_last_modified_index()
    normalized = db.migrate_normalize_dates()
    if normalized:
        logger.info("Startup: normalized %d date values to ISO 8601", normalized)

    # Clean up any './' duplicate entries left from previous crawls
    cleanup_result = db.cleanup_dotslash_duplicates()
    if cleanup_result["total_removed"] > 0:
        logger.info("Startup cleanup: removed %d duplicate entries (had './' in path)",
                     cleanup_result["total_removed"])

    stats = db.get_stats()
    logger.info("Current index: %d files, %d dirs", stats["total_files"], stats["total_dirs"])

    _setup_scheduler()

    # Auto-crawl if database is empty
    if stats["total_files"] == 0:
        logger.info("Database is empty — starting initial crawl in background")
        thread = threading.Thread(
            target=run_sync_blocking,
            args=(db, True),
            daemon=True
        )
        thread.start()


# ── CLI entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
