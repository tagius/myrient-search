"""Parse Myrient HTTP directory listings and extract metadata from paths."""
import re
import json
import logging
from pathlib import Path
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Load categories from bundled JSON
_CATEGORIES_PATH = Path(__file__).parent.parent / "data" / "categories.json"
_CATEGORIES: dict | None = None
_FLAT_CATEGORIES: list[tuple[str, str]] | None = None  # (platform_string, manufacturer)


def _load_categories() -> tuple[dict, list[tuple[str, str]]]:
    """Load and flatten categories for matching."""
    global _CATEGORIES, _FLAT_CATEGORIES
    if _CATEGORIES is not None:
        return _CATEGORIES, _FLAT_CATEGORIES

    try:
        with open(_CATEGORIES_PATH) as f:
            _CATEGORIES = json.load(f)
    except FileNotFoundError:
        logger.warning("categories.json not found at %s, using empty categories", _CATEGORIES_PATH)
        _CATEGORIES = {"Categories": {}, "Types": [], "Regions": [], "Special": {}}

    # Build flat list sorted by string length (longest first for greedy matching)
    flat = []
    for manufacturer, platforms in _CATEGORIES.get("Categories", {}).items():
        # Add manufacturer itself as a matchable string
        flat.append((manufacturer, manufacturer))
        for platform in platforms:
            # Build the full string as it appears in Myrient paths
            # e.g. "Nintendo - Game Boy Advance" or just "Game Boy Advance"
            full = f"{manufacturer} - {platform}" if manufacturer != platform else platform
            flat.append((full, manufacturer))
            flat.append((platform, manufacturer))

    # Sort by length descending — longest match wins
    _FLAT_CATEGORIES = sorted(flat, key=lambda x: len(x[0]), reverse=True)
    return _CATEGORIES, _FLAT_CATEGORIES


def parse_directory_listing(html: str) -> list[dict]:
    """Parse an HTML directory listing page from Myrient.

    Myrient uses a standard table with id="list":
        <table id="list">
          <tr><td class="link"><a href="...">Name</a></td>
              <td class="size">123 MB</td>
              <td class="date">2024-01-15 10:30</td></tr>
        </table>

    Returns list of dicts with keys: name, href, size, date, is_directory
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    entries = []

    # Find all table rows — Myrient uses <table id="list"> or just <pre> with links
    rows = tree.css("table#list tr")
    if rows:
        entries = _parse_table_rows(rows)
    else:
        # Fallback: some pages use <pre> with <a> tags (simpler listing)
        pre = tree.css_first("pre")
        if pre:
            entries = _parse_pre_listing(pre)

    return entries


def _parse_table_rows(rows) -> list[dict]:
    """Parse <tr> rows from a table#list."""
    entries = []
    for row in rows:
        link = row.css_first("td.link a, td:first-child a")
        if not link:
            continue

        href = link.attributes.get("href", "")
        name = link.text(strip=True)

        # Skip parent directory and current directory entries
        # Myrient uses "Parent directory" (lowercase 'd') and has "." links
        if name in ("../", "..", ".", "./", "Parent Directory") or \
           name.lower().startswith("parent dir") or \
           href in ("../", "/", "./", "."):
            continue

        size_td = row.css_first("td.size, td:nth-child(2)")
        date_td = row.css_first("td.date, td:nth-child(3)")

        size_text = size_td.text(strip=True) if size_td else ""
        date_text = date_td.text(strip=True) if date_td else ""

        is_directory = href.endswith("/") or size_text in ("-", "")

        decoded_name = unquote(name.rstrip("/"))
        if decoded_name in (".", ".."):
            continue

        entries.append({
            "name": decoded_name,
            "href": href,
            "size": size_text if size_text not in ("-", "") else None,
            "date": date_text if date_text else None,
            "is_directory": is_directory,
        })

    return entries


def _parse_pre_listing(pre_node) -> list[dict]:
    """Fallback parser for <pre>-based directory listings."""
    entries = []
    for link in pre_node.css("a"):
        href = link.attributes.get("href", "")
        name = link.text(strip=True)

        if name in ("../", "..", ".", "./", "Parent Directory") or \
           name.lower().startswith("parent dir") or \
           href in ("../", "/", "./", "."):
            continue

        decoded_name = unquote(name.rstrip("/"))
        if decoded_name in (".", ".."):
            continue

        is_directory = href.endswith("/")
        entries.append({
            "name": decoded_name,
            "href": href,
            "size": None,
            "date": None,
            "is_directory": is_directory,
        })

    return entries


# ── Metadata extraction from paths ──────────────────────────────────────

def extract_collection(path: str) -> str | None:
    """Extract the top-level collection from a path.

    e.g. "No-Intro/Nintendo - Game Boy/game.zip" → "No-Intro"
    """
    parts = path.strip("/").split("/")
    return parts[0] if parts else None


def extract_platform(path: str) -> str | None:
    """Extract the platform/console from a path using categories.json.

    Uses longest-match strategy to avoid false positives.
    """
    _, flat_cats = _load_categories()
    decoded = unquote(path)

    for platform_str, _manufacturer in flat_cats:
        if platform_str.lower() in decoded.lower():
            return platform_str

    # Fallback: use second path component if available
    parts = decoded.strip("/").split("/")
    if len(parts) >= 2:
        return parts[1]

    return None


_KNOWN_REGIONS = [
    'USA', 'Europe', 'Japan', 'World', 'Germany', 'France', 'Spain',
    'Italy', 'Korea', 'Brazil', 'UK', 'Asia', 'Australia', 'Netherlands',
    'Sweden', 'Norway', 'Denmark', 'Finland', 'Portugal', 'Russia',
    'China', 'Taiwan', 'Hong Kong', 'Canada',
]
_REGION_RE = '(?:' + '|'.join(_KNOWN_REGIONS) + ')'
_REGION_PATTERN = re.compile(
    r'\((' + _REGION_RE + r'(?:\s*,\s*' + _REGION_RE + r')*)\)',
    re.IGNORECASE
)


def extract_region(name: str) -> str | None:
    """Extract region from filename. e.g. 'Game (USA, Europe).zip' → 'USA, Europe'"""
    match = _REGION_PATTERN.search(name)
    return match.group(1) if match else None


def extract_file_type(name: str) -> str | None:
    """Extract file extension. e.g. 'game.zip' → 'zip'"""
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    return None


def normalize_myrient_date(raw: str | None) -> str | None:
    """Normalize Myrient date formats to ISO 8601.

    Myrient uses two date formats in its directory listings:
      - "2024-01-15 10:30"   (nginx autoindex default)
      - "18-Feb-2025 10:57"  (nginx fancyindex / some pages)

    Returns ISO 8601 format: "2024-01-15T10:30:00"
    Returns None for empty/None input.
    """
    if not raw or not raw.strip():
        return None

    raw = raw.strip()

    # Already ISO 8601?
    if "T" in raw:
        return raw

    # Format 1: "2024-01-15 10:30" → "2024-01-15T10:30:00"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})$", raw)
    if m:
        return f"{m.group(1)}T{m.group(2)}:00"

    # Format 2: "18-Feb-2025 10:57" → "2025-02-18T10:57:00"
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}:\d{2})$", raw)
    if m:
        try:
            from datetime import datetime
            dt = datetime.strptime(raw, "%d-%b-%Y %H:%M")
            return dt.strftime("%Y-%m-%dT%H:%M:00")
        except ValueError:
            pass

    # Unknown format — return as-is
    return raw


def _normalize_path(path: str) -> str:
    """Remove redundant './' segments and normalize path separators.

    e.g. 'No-Intro/./Sony/./game.zip' → 'No-Intro/Sony/game.zip'
    """
    import posixpath
    # Split, filter out empty and '.' segments, rejoin
    parts = path.split("/")
    cleaned = [p for p in parts if p and p != "."]
    result = "/".join(cleaned)
    # Preserve trailing slash for directories
    if path.endswith("/") and result:
        result += "/"
    return result


def build_entry(href: str, name: str, is_directory: bool,
                size: str | None, date: str | None,
                parent_url_path: str) -> dict:
    """Build a full entry dict ready for database insertion."""
    # Full path relative to /files/
    if parent_url_path.endswith("/"):
        full_path = parent_url_path + name + ("/" if is_directory else "")
    else:
        full_path = parent_url_path + "/" + name + ("/" if is_directory else "")

    # Clean up leading slash and normalize away "./" segments
    full_path = _normalize_path(full_path.lstrip("/"))

    return {
        "path": full_path,
        "name": name,
        "is_directory": is_directory,
        "file_size": size,
        "last_modified": normalize_myrient_date(date),
        "collection": extract_collection(full_path),
        "platform": extract_platform(full_path) if not is_directory or full_path.count("/") <= 2 else extract_platform(full_path),
        "region": extract_region(name) if not is_directory else None,
        "file_type": extract_file_type(name) if not is_directory else None,
        "parent_path": _normalize_path(full_path.rsplit("/", 2)[0] + "/") if "/" in full_path.rstrip("/") else "",
    }
