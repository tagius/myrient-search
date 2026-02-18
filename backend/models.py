"""Pydantic models for API responses."""
from pydantic import BaseModel


class EntryResult(BaseModel):
    path: str
    name: str
    is_directory: bool
    file_size: str | None = None
    last_modified: str | None = None
    collection: str | None = None
    platform: str | None = None
    region: str | None = None
    file_type: str | None = None
    parent_path: str | None = None


class SearchResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    results: list[EntryResult]


class CollectionInfo(BaseModel):
    collection: str
    count: int


class PlatformInfo(BaseModel):
    platform: str
    collection: str | None = None
    count: int


class StatsResponse(BaseModel):
    total_files: int
    total_dirs: int
    collections: int
    platforms: int
    last_synced: str | None = None
    crawl_status: dict | None = None


class CrawlStatusResponse(BaseModel):
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    dirs_crawled: int = 0
    files_found: int = 0
    errors: int = 0
    message: str | None = None
