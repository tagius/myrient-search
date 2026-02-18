"""Search API endpoints."""
import logging
from fastapi import APIRouter, Query, HTTPException
from indexer.database import Database
from backend.models import (
    SearchResponse, CollectionInfo, PlatformInfo, StatsResponse, CrawlStatusResponse
)
from config import DB_PATH, RESULTS_PER_PAGE, MYRIENT_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
db = Database(DB_PATH)


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    collection: str | None = Query(None, description="Filter by collection"),
    platform: str | None = Query(None, description="Filter by platform"),
    file_type: str | None = Query(None, description="Filter by file extension"),
    region: str | None = Query(None, description="Filter by region"),
    sort_by: str = Query("relevance", description="Sort by: relevance, name, size, type, region, platform, date"),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(RESULTS_PER_PAGE, ge=1, le=200, description="Results per page"),
):
    """Full-text search across all indexed Myrient entries."""
    try:
        result = db.search(
            query=q,
            collection=collection,
            platform=platform,
            file_type=file_type,
            region=region,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            per_page=per_page,
        )
        return SearchResponse(**result)
    except Exception as e:
        logger.warning("Search error for query '%s': %s", q, e)
        # Return empty results instead of 500 for query parsing errors
        return SearchResponse(total=0, page=page, per_page=per_page, pages=0, results=[])


@router.get("/collections", response_model=list[CollectionInfo])
async def collections():
    """List all collections with file counts."""
    return db.get_collections()


@router.get("/platforms", response_model=list[PlatformInfo])
async def platforms(
    collection: str | None = Query(None, description="Filter by collection"),
):
    """List all platforms, optionally filtered by collection."""
    return db.get_platforms(collection)


@router.get("/manufacturers")
async def manufacturers():
    """List manufacturers with their platforms grouped, for the two-tier filter."""
    return db.get_manufacturers()


@router.get("/browse")
async def browse(path: str = Query("", description="Directory path to browse")):
    """Browse entries in a specific directory."""
    entries = db.browse(path)
    return {"path": path, "entries": entries}


@router.get("/stats", response_model=StatsResponse)
async def stats():
    """Database statistics."""
    return db.get_stats()


@router.get("/sync/status", response_model=CrawlStatusResponse)
async def sync_status():
    """Current crawl/sync status."""
    state = db.get_crawl_state()
    if not state:
        return CrawlStatusResponse(status="unknown")
    return CrawlStatusResponse(**{
        k: v for k, v in state.items() if k != "id"
    })


@router.post("/cleanup")
async def cleanup():
    """Remove duplicate entries caused by './' paths in the database.

    Safe to run multiple times — idempotent. Returns counts of what was cleaned.
    """
    try:
        result = db.cleanup_dotslash_duplicates()
        return result
    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recently-added")
async def recently_added(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    page: int = Query(1, ge=1),
    per_page: int = Query(RESULTS_PER_PAGE, ge=1, le=200),
):
    """Return files added/modified within the last N days, newest first."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:00")

    with db.connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM entries "
            "WHERE is_directory = 0 AND last_modified >= ?",
            (cutoff,)
        ).fetchone()["c"]

        offset = (page - 1) * per_page
        rows = conn.execute(
            "SELECT * FROM entries "
            "WHERE is_directory = 0 AND last_modified >= ? "
            "ORDER BY last_modified DESC "
            "LIMIT ? OFFSET ?",
            (cutoff, per_page, offset)
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
        "cutoff": cutoff,
        "results": [dict(r) for r in rows],
    }


@router.get("/health")
async def health():
    """Lightweight health check — no DB queries."""
    return {"status": "ok"}


@router.get("/config")
async def get_config():
    """Return public configuration."""
    return {"base_url": MYRIENT_BASE_URL}
