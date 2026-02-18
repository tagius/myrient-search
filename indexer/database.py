"""SQLite database with FTS5 full-text search for Myrient entries."""
import hashlib
import re
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Main file/directory table
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_directory BOOLEAN NOT NULL DEFAULT 0,
    file_size TEXT,
    last_modified TEXT,
    collection TEXT,
    platform TEXT,
    region TEXT,
    file_type TEXT,
    parent_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search virtual table
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    name,
    path,
    collection,
    platform,
    region,
    content='entries',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, name, path, collection, platform, region)
    VALUES (new.id, new.name, new.path, new.collection, new.platform, new.region);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, name, path, collection, platform, region)
    VALUES ('delete', old.id, old.name, old.path, old.collection, old.platform, old.region);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, name, path, collection, platform, region)
    VALUES ('delete', old.id, old.name, old.path, old.collection, old.platform, old.region);
    INSERT INTO entries_fts(rowid, name, path, collection, platform, region)
    VALUES (new.id, new.name, new.path, new.collection, new.platform, new.region);
END;

-- Sync metadata for smart incremental updates
CREATE TABLE IF NOT EXISTS sync_meta (
    path TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_crawled TIMESTAMP,
    entry_count INTEGER
);

-- Crawl state tracking
CREATE TABLE IF NOT EXISTS crawl_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT DEFAULT 'idle',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    dirs_crawled INTEGER DEFAULT 0,
    files_found INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    message TEXT
);

-- Indexes for fast filtering
CREATE INDEX IF NOT EXISTS idx_entries_collection ON entries(collection);
CREATE INDEX IF NOT EXISTS idx_entries_platform ON entries(platform);
CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_path);
CREATE INDEX IF NOT EXISTS idx_entries_is_dir ON entries(is_directory);
CREATE INDEX IF NOT EXISTS idx_entries_region ON entries(region);
CREATE INDEX IF NOT EXISTS idx_entries_file_type ON entries(file_type);
-- Composite index for the most common filter pattern (files-only + collection)
CREATE INDEX IF NOT EXISTS idx_entries_dir_coll ON entries(is_directory, collection);
"""

INIT_CRAWL_STATE = """
INSERT OR IGNORE INTO crawl_state (id, status) VALUES (1, 'idle');
"""


class Database:
    """SQLite database manager with FTS5 search."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        """Create tables and indexes."""
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute(INIT_CRAWL_STATE)
        logger.info("Database initialized at %s", self.db_path)

    def insert_entries_batch(self, entries: list[dict]):
        """Bulk insert/update entries. Uses INSERT OR REPLACE for upsert."""
        if not entries:
            return
        sql = """
            INSERT OR REPLACE INTO entries
                (path, name, is_directory, file_size, last_modified,
                 collection, platform, region, file_type, parent_path, updated_at)
            VALUES
                (:path, :name, :is_directory, :file_size, :last_modified,
                 :collection, :platform, :region, :file_type, :parent_path,
                 datetime('now'))
        """
        with self.connect() as conn:
            conn.executemany(sql, entries)

    def upsert_sync_meta(self, path: str, etag: str | None,
                         last_modified: str | None, entry_count: int,
                         content_hash: str | None = None):
        """Update sync metadata for a directory."""
        sql = """
            INSERT OR REPLACE INTO sync_meta
                (path, etag, last_modified, last_crawled, entry_count, content_hash)
            VALUES (?, ?, ?, datetime('now'), ?, ?)
        """
        with self.connect() as conn:
            conn.execute(sql, (path, etag, last_modified, entry_count, content_hash))

    def get_sync_meta(self, path: str) -> dict | None:
        """Get sync metadata for a directory."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_meta WHERE path = ?", (path,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def compute_content_hash(entries: list[dict]) -> str:
        """Compute a SHA256 hash of directory listing content.

        Takes the parsed entries (name, size, date) and produces a stable
        hash. If the listing hasn't changed, the hash will be identical,
        letting us skip expensive DB writes.
        """
        # Sort by name for stability (server order may vary)
        tuples = sorted(
            (e.get("name", ""), e.get("size") or "", e.get("date") or "")
            for e in entries
        )
        raw = repr(tuples).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ── Schema migrations (idempotent) ────────────────────────────

    def migrate_add_content_hash(self):
        """Add content_hash column to sync_meta if it doesn't exist."""
        with self.connect() as conn:
            try:
                conn.execute("ALTER TABLE sync_meta ADD COLUMN content_hash TEXT")
                logger.info("Migration: added content_hash column to sync_meta")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    pass  # Already exists — fine
                else:
                    raise

    def migrate_add_last_modified_index(self):
        """Add index on last_modified for date sorting."""
        with self.connect() as conn:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_last_modified "
                "ON entries(last_modified)"
            )
            logger.info("Migration: ensured idx_entries_last_modified index exists")

    # Date normalization patterns:
    #   "2024-01-15 10:30" → "2024-01-15T10:30:00"
    #   "18-Feb-2025 10:57" → "2025-02-18T10:57:00"
    _DATE_FMT_ISO_SPACE = re.compile(
        r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})$"
    )
    _DATE_FMT_DD_MON_YYYY = re.compile(
        r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}:\d{2})$"
    )

    def migrate_normalize_dates(self):
        """Normalize existing last_modified values to ISO 8601 format.

        Converts:
          "2024-01-15 10:30"   →  "2024-01-15T10:30:00"
          "18-Feb-2025 10:57"  →  "2025-02-18T10:57:00"
        Already-normalized values (containing 'T') are skipped.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, last_modified FROM entries "
                "WHERE last_modified IS NOT NULL AND last_modified != '' "
                "AND last_modified NOT LIKE '%T%'"
            ).fetchall()

            if not rows:
                logger.info("Migration: no dates to normalize")
                return 0

            updates = []
            for row in rows:
                normalized = self._normalize_date_value(row["last_modified"])
                if normalized and normalized != row["last_modified"]:
                    updates.append((normalized, row["id"]))

            if updates:
                conn.executemany(
                    "UPDATE entries SET last_modified = ? WHERE id = ?",
                    updates
                )
            logger.info("Migration: normalized %d dates out of %d checked",
                        len(updates), len(rows))
            return len(updates)

    @classmethod
    def _normalize_date_value(cls, raw: str) -> str | None:
        """Normalize a single date string to ISO 8601."""
        if not raw:
            return None

        raw = raw.strip()

        # Already ISO?
        if "T" in raw:
            return raw

        # "2024-01-15 10:30" → "2024-01-15T10:30:00"
        m = cls._DATE_FMT_ISO_SPACE.match(raw)
        if m:
            return f"{m.group(1)}T{m.group(2)}:00"

        # "18-Feb-2025 10:57" → "2025-02-18T10:57:00"
        m = cls._DATE_FMT_DD_MON_YYYY.match(raw)
        if m:
            try:
                dt = datetime.strptime(raw, "%d-%b-%Y %H:%M")
                return dt.strftime("%Y-%m-%dT%H:%M:00")
            except ValueError:
                pass

        # Unknown format — return as-is
        return raw

    def search(self, query: str, collection: str | None = None,
               platform: str | None = None, file_type: str | None = None,
               region: str | None = None,
               files_only: bool = True,
               sort_by: str = "relevance", sort_order: str = "asc",
               page: int = 1, per_page: int = 50) -> dict:
        """Full-text search with filters and pagination.

        collection, platform, region can be comma-separated for multi-select.
        Multi-word queries (e.g. "ratchet tool") use AND to find entries
        containing all terms. Special characters (+, &, etc.) are stripped
        or treated as word separators.
        """
        # Build FTS query — sanitize, tokenize, prefix-match each term
        import re
        # Replace special chars (+, &, |, -, etc.) with spaces so
        # "ratcher+tool" becomes "ratcher tool"
        cleaned = re.sub(r'[+&|/\\~^{}()\[\]<>:;!@#$%]', ' ', query)
        # Remove FTS5 operators that could cause syntax errors
        cleaned = re.sub(r'\b(AND|OR|NOT|NEAR)\b', '', cleaned, flags=re.IGNORECASE)

        fts_terms = []
        for token in cleaned.strip().split():
            token = token.strip('"\'')
            if not token:
                continue
            safe = token.replace('"', '""')
            fts_terms.append(f'"{safe}"*')

        if not fts_terms:
            return {"total": 0, "page": page, "per_page": per_page,
                    "pages": 0, "results": []}

        fts_query = " AND ".join(fts_terms)

        # Build WHERE conditions
        conditions = ["entries_fts MATCH :query"]
        params: dict = {"query": fts_query}

        if files_only:
            conditions.append("e.is_directory = 0")

        # Helper for multi-value IN clauses
        def add_multi_filter(field, value, prefix):
            values = [v.strip() for v in value.split(",") if v.strip()]
            if len(values) == 1:
                conditions.append(f"e.{field} = :{prefix}")
                params[prefix] = values[0]
            elif values:
                placeholders = ", ".join(f":{prefix}_{i}" for i in range(len(values)))
                conditions.append(f"e.{field} IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"{prefix}_{i}"] = v

        if collection:
            add_multi_filter("collection", collection, "collection")
        if platform:
            add_multi_filter("platform", platform, "platform")
        if file_type:
            conditions.append("e.file_type = :file_type")
            params["file_type"] = file_type
        if region:
            add_multi_filter("region", region, "region")

        where = " AND ".join(conditions)
        offset = (page - 1) * per_page
        params["limit"] = per_page
        params["offset"] = offset

        with self.connect() as conn:
            # Count total matches
            count_sql = f"""
                SELECT COUNT(*) as total
                FROM entries_fts
                JOIN entries e ON entries_fts.rowid = e.id
                WHERE {where}
            """
            total = conn.execute(count_sql, params).fetchone()["total"]

            # Determine sort order
            SORT_MAP = {
                "relevance": "bm25(entries_fts, 10.0, 1.0, 5.0, 5.0, 2.0)",
                "name": "e.name COLLATE NOCASE",
                "size": "e.file_size",
                "type": "e.file_type",
                "region": "e.region",
                "platform": "e.platform COLLATE NOCASE",
                "date": "e.last_modified",
            }
            order_col = SORT_MAP.get(sort_by, SORT_MAP["relevance"])
            # For relevance, lower BM25 = better match, so always ASC
            if sort_by == "relevance":
                direction = "ASC"
            else:
                direction = "DESC" if sort_order == "desc" else "ASC"

            # Fetch page of results
            results_sql = f"""
                SELECT e.*, bm25(entries_fts, 10.0, 1.0, 5.0, 5.0, 2.0) as rank
                FROM entries_fts
                JOIN entries e ON entries_fts.rowid = e.id
                WHERE {where}
                ORDER BY {order_col} {direction}
                LIMIT :limit OFFSET :offset
            """
            rows = conn.execute(results_sql, params).fetchall()

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
                "results": [dict(r) for r in rows],
            }

    def get_collections(self) -> list[dict]:
        """Get all collections with file counts."""
        sql = """
            SELECT collection, COUNT(*) as count
            FROM entries
            WHERE is_directory = 0 AND collection IS NOT NULL
            GROUP BY collection
            ORDER BY count DESC
        """
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def get_platforms(self, collection: str | None = None) -> list[dict]:
        """Get all platforms, optionally filtered by collection."""
        conditions = ["is_directory = 0", "platform IS NOT NULL"]
        params = []
        if collection:
            # Support multi-value
            colls = [c.strip() for c in collection.split(",") if c.strip()]
            if len(colls) == 1:
                conditions.append("collection = ?")
                params.append(colls[0])
            elif colls:
                placeholders = ",".join("?" * len(colls))
                conditions.append(f"collection IN ({placeholders})")
                params.extend(colls)
        where = " AND ".join(conditions)
        sql = f"""
            SELECT platform, collection, COUNT(*) as count
            FROM entries
            WHERE {where}
            GROUP BY platform, collection
            ORDER BY count DESC
        """
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_manufacturers(self) -> list[dict]:
        """Get distinct manufacturers extracted from platform names.

        Platform names follow the pattern 'Manufacturer - Console' (e.g.
        'Nintendo - Game Boy Advance'). This returns grouped manufacturer
        data with their platforms for the two-tier filter UI.
        """
        sql = """
            SELECT platform, COUNT(*) as count
            FROM entries
            WHERE is_directory = 0 AND platform IS NOT NULL
            GROUP BY platform
            ORDER BY count DESC
        """
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()

        # Group by manufacturer
        mfr_map: dict[str, list[dict]] = {}
        for row in rows:
            plat = row["platform"]
            count = row["count"]
            if " - " in plat:
                manufacturer = plat.split(" - ", 1)[0].strip()
            else:
                manufacturer = "Other"
            if manufacturer not in mfr_map:
                mfr_map[manufacturer] = []
            mfr_map[manufacturer].append({"platform": plat, "count": count})

        # Sort manufacturers by total file count
        result = []
        for mfr, platforms in sorted(
            mfr_map.items(),
            key=lambda x: sum(p["count"] for p in x[1]),
            reverse=True,
        ):
            total = sum(p["count"] for p in platforms)
            result.append({
                "manufacturer": mfr,
                "total_count": total,
                "platforms": sorted(platforms, key=lambda p: p["count"], reverse=True),
            })
        return result

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self.connect() as conn:
            total_files = conn.execute(
                "SELECT COUNT(*) as c FROM entries WHERE is_directory = 0"
            ).fetchone()["c"]
            total_dirs = conn.execute(
                "SELECT COUNT(*) as c FROM entries WHERE is_directory = 1"
            ).fetchone()["c"]
            collections = conn.execute(
                "SELECT COUNT(DISTINCT collection) as c FROM entries"
            ).fetchone()["c"]
            platforms = conn.execute(
                "SELECT COUNT(DISTINCT platform) as c FROM entries"
            ).fetchone()["c"]
            crawl = conn.execute("SELECT * FROM crawl_state WHERE id = 1").fetchone()
            # Get the most recent sync completion time
            last_synced = None
            if crawl:
                last_synced = dict(crawl).get("finished_at")
            return {
                "total_files": total_files,
                "total_dirs": total_dirs,
                "collections": collections,
                "platforms": platforms,
                "last_synced": last_synced,
                "crawl_status": dict(crawl) if crawl else None,
            }

    def browse(self, parent_path: str) -> list[dict]:
        """Browse entries in a specific directory."""
        sql = """
            SELECT * FROM entries
            WHERE parent_path = ?
            ORDER BY is_directory DESC, name ASC
        """
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, (parent_path,)).fetchall()]

    def update_crawl_state(self, **kwargs):
        """Update crawl state."""
        sets = ", ".join(f"{k} = :{k}" for k in kwargs)
        sql = f"UPDATE crawl_state SET {sets} WHERE id = 1"
        with self.connect() as conn:
            conn.execute(sql, kwargs)

    def get_crawl_state(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM crawl_state WHERE id = 1").fetchone()
            return dict(row) if row else None

    def remove_missing_entries(self, parent_path: str, current_names: set[str]):
        """Remove entries under parent_path that are no longer present."""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id, name FROM entries WHERE parent_path = ?",
                (parent_path,)
            ).fetchall()
            to_delete = [r["id"] for r in existing if r["name"] not in current_names]
            if to_delete:
                placeholders = ",".join("?" * len(to_delete))
                conn.execute(
                    f"DELETE FROM entries WHERE id IN ({placeholders})", to_delete
                )
                logger.info("Removed %d stale entries from %s", len(to_delete), parent_path)

    def cleanup_dotslash_duplicates(self) -> dict:
        """Remove entries with './' in their paths (duplicate artifacts from crawling '.' dirs).

        Strategy:
          1. Delete all entries where path contains '/./' (mid-path dot-slash).
          2. Delete all entries where path starts with './' (leading dot-slash).
          3. Delete all entries where name is '.' — current-dir entries.
          4. Clean up sync_meta entries with './' in the path.
          5. Rebuild FTS index.

        Returns dict with counts of what was cleaned.
        """
        with self.connect() as conn:
            # Count before
            total_before = conn.execute("SELECT COUNT(*) as c FROM entries").fetchone()["c"]

            # 1. Delete entries with /./ in path (mid-path dot-slash duplicates)
            dotslash_mid = conn.execute(
                "SELECT COUNT(*) as c FROM entries WHERE path LIKE '%/./%'"
            ).fetchone()["c"]
            if dotslash_mid > 0:
                conn.execute("DELETE FROM entries WHERE path LIKE '%/./%'")
                logger.info("Deleted %d entries with '/./' in path", dotslash_mid)

            # 2. Delete entries where path starts with './' (leading dot-slash)
            dotslash_lead = conn.execute(
                "SELECT COUNT(*) as c FROM entries WHERE path LIKE './%'"
            ).fetchone()["c"]
            if dotslash_lead > 0:
                conn.execute("DELETE FROM entries WHERE path LIKE './%'")
                logger.info("Deleted %d entries with leading './' in path", dotslash_lead)

            # 3. Delete entries named exactly '.'
            dot_entries = conn.execute(
                "SELECT COUNT(*) as c FROM entries WHERE name = '.'"
            ).fetchone()["c"]
            if dot_entries > 0:
                conn.execute("DELETE FROM entries WHERE name = '.'")
                logger.info("Deleted %d entries named '.'", dot_entries)

            # 4. Clean up sync_meta with './' paths
            dot_sync = conn.execute(
                "SELECT COUNT(*) as c FROM sync_meta WHERE path LIKE '%/./%' OR path LIKE './%'"
            ).fetchone()["c"]
            if dot_sync > 0:
                conn.execute("DELETE FROM sync_meta WHERE path LIKE '%/./%' OR path LIKE './%'")
                logger.info("Deleted %d sync_meta entries with '.' paths", dot_sync)

            total_after = conn.execute("SELECT COUNT(*) as c FROM entries").fetchone()["c"]

            # 5. Rebuild FTS index to remove stale entries
            try:
                conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
                logger.info("FTS index rebuilt")
            except Exception as e:
                logger.warning("FTS rebuild failed (non-critical): %s", e)

            # 6. Update query planner statistics and checkpoint WAL
            try:
                conn.execute("ANALYZE")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning("ANALYZE/checkpoint failed (non-critical): %s", e)

            removed = total_before - total_after
            logger.info("Cleanup complete: removed %d entries (%d → %d)",
                        removed, total_before, total_after)

            return {
                "dotslash_mid_removed": dotslash_mid,
                "dotslash_lead_removed": dotslash_lead,
                "dot_entries_removed": dot_entries,
                "sync_meta_removed": dot_sync,
                "total_before": total_before,
                "total_after": total_after,
                "total_removed": removed,
            }
