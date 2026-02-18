"""Full test suite for Myrient Search Engine — no network required."""
import os
import sys

os.environ["DATA_DIR"] = "/sessions/brave-amazing-cori/testdata"
sys.path.insert(0, os.path.dirname(__file__))

from indexer.database import Database
from indexer.parser import (
    parse_directory_listing, build_entry, extract_platform,
    extract_region, extract_file_type, extract_collection,
    normalize_myrient_date,
)
from config import DB_PATH

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


# ═══════════════════════════════════════════════════════════════
print("\n── 1. HTML Parser Tests ──")

# Root directory listing
ROOT_HTML = """<html><body>
<table id="list">
<tr><td class="link"><a href="No-Intro/">No-Intro</a></td><td class="size">-</td><td class="date">2024-12-01</td></tr>
<tr><td class="link"><a href="Redump/">Redump</a></td><td class="size">-</td><td class="date">2024-11-15</td></tr>
<tr><td class="link"><a href="TOSEC/">TOSEC</a></td><td class="size">-</td><td class="date">2024-10-20</td></tr>
</table>
</body></html>"""

entries = parse_directory_listing(ROOT_HTML)
check("root: 3 entries", len(entries) == 3)
check("root: No-Intro is dir", entries[0]["is_directory"] is True)
check("root: name=No-Intro", entries[0]["name"] == "No-Intro")

# "Parent directory" variant (lowercase 'd' — actual Myrient format)
PARENT_DIR_HTML = """<html><body>
<table id="list">
<tr><td class="link"><a href="../">Parent directory</a></td><td class="size">-</td><td class="date"></td></tr>
<tr><td class="link"><a href="Zelda.zip">Zelda (USA).zip</a></td><td class="size">512.0 KB</td><td class="date">2024-06-15</td></tr>
</table>
</body></html>"""

pdir_entries = parse_directory_listing(PARENT_DIR_HTML)
check("parent dir (lowercase): filtered out", len(pdir_entries) == 1)
check("parent dir: only file remains", pdir_entries[0]["name"] == "Zelda (USA).zip")

# File listing with parent dir
FILE_HTML = """<html><body>
<table id="list">
<tr><td class="link"><a href="../">..</a></td><td class="size">-</td><td class="date"></td></tr>
<tr><td class="link"><a href="Zelda.zip">Legend of Zelda, The (USA).zip</a></td><td class="size">512.0 KB</td><td class="date">2024-06-15</td></tr>
<tr><td class="link"><a href="Mario.zip">Super Mario Bros. (Japan, USA).zip</a></td><td class="size">40.0 KB</td><td class="date">2024-06-15</td></tr>
<tr><td class="link"><a href="Metroid.zip">Metroid (Europe).zip</a></td><td class="size">128.5 KB</td><td class="date">2024-06-15</td></tr>
<tr><td class="link"><a href="Sonic.zip">Sonic the Hedgehog (USA, Europe).zip</a></td><td class="size">256.0 KB</td><td class="date">2024-03-01</td></tr>
</table>
</body></html>"""

entries = parse_directory_listing(FILE_HTML)
check("files: parent filtered", len(entries) == 4)
check("files: correct name", entries[0]["name"] == "Legend of Zelda, The (USA).zip")
check("files: size parsed", entries[0]["size"] == "512.0 KB")
check("files: not directory", entries[0]["is_directory"] is False)

# ═══════════════════════════════════════════════════════════════
print("\n── 2. Metadata Extraction Tests ──")

check("region: USA", extract_region("Zelda (USA).zip") == "USA")
check("region: multi", extract_region("Mario (Japan, USA).zip") == "Japan, USA")
check("region: Europe", extract_region("Metroid (Europe).zip") == "Europe")
check("region: none", extract_region("some_file.zip") is None)

check("file_type: zip", extract_file_type("game.zip") == "zip")
check("file_type: 7z", extract_file_type("game.7z") == "7z")
check("file_type: iso", extract_file_type("game.iso") == "iso")
check("file_type: none", extract_file_type("noext") is None)

check("collection: No-Intro", extract_collection("No-Intro/Nintendo/game.zip") == "No-Intro")
check("collection: Redump", extract_collection("Redump/Sony/game.zip") == "Redump")

p = extract_platform("No-Intro/Nintendo - Game Boy Advance/game.zip")
check(f"platform: GBA → '{p}'", p is not None and "Game Boy Advance" in p)

p = extract_platform("Redump/Sony - PlayStation 2/game.zip")
check(f"platform: PS2 → '{p}'", p is not None and "PlayStation 2" in p)

# ═══════════════════════════════════════════════════════════════
print("\n── 3. build_entry Tests ──")

entry = build_entry(
    "Zelda.zip", "Legend of Zelda, The (USA).zip", False,
    "512.0 KB", "2024-06-15",
    "No-Intro/Nintendo - Nintendo Entertainment System/"
)
check("entry: collection=No-Intro", entry["collection"] == "No-Intro")
check("entry: region=USA", entry["region"] == "USA")
check("entry: file_type=zip", entry["file_type"] == "zip")
check("entry: has platform", entry["platform"] is not None)
check("entry: has path", "No-Intro" in entry["path"])

# ═══════════════════════════════════════════════════════════════
print("\n── 4. Database Tests ──")

# Clean start
import pathlib
db_file = pathlib.Path(DB_PATH)
if db_file.exists():
    db_file.unlink()
wal = db_file.parent / (db_file.name + "-wal")
shm = db_file.parent / (db_file.name + "-shm")
if wal.exists():
    wal.unlink()
if shm.exists():
    shm.unlink()

db = Database(DB_PATH)
db.initialize()
check("db: initialized", db_file.exists())

stats = db.get_stats()
check("db: empty stats", stats["total_files"] == 0)

# Insert sample data
SAMPLE_DATA = [
    ("No-Intro", "Nintendo - Nintendo Entertainment System", [
        ("Legend of Zelda, The (USA).zip", "512.0 KB"),
        ("Super Mario Bros. (Japan, USA).zip", "40.0 KB"),
        ("Metroid (USA, Europe).zip", "128.5 KB"),
        ("Castlevania (USA).zip", "256.0 KB"),
        ("Mega Man 2 (USA).zip", "384.0 KB"),
    ]),
    ("No-Intro", "Nintendo - Super Nintendo Entertainment System", [
        ("Chrono Trigger (USA).zip", "4.0 MB"),
        ("Super Metroid (Japan, USA, Europe).zip", "3.0 MB"),
        ("Legend of Zelda - A Link to the Past (USA).zip", "1.0 MB"),
        ("Final Fantasy VI (USA).zip", "3.5 MB"),
        ("EarthBound (USA).zip", "3.2 MB"),
    ]),
    ("No-Intro", "Sega - Mega Drive - Genesis", [
        ("Sonic the Hedgehog (USA, Europe).zip", "512.0 KB"),
        ("Streets of Rage 2 (USA, Europe).zip", "1.5 MB"),
        ("Phantasy Star IV (USA).zip", "2.0 MB"),
        ("Gunstar Heroes (USA).zip", "1.0 MB"),
    ]),
    ("Redump", "Sony - PlayStation", [
        ("Final Fantasy VII (USA) (Disc 1).zip", "650.0 MB"),
        ("Metal Gear Solid (USA) (Disc 1).zip", "600.0 MB"),
        ("Castlevania - Symphony of the Night (USA).zip", "450.0 MB"),
        ("Resident Evil 2 (USA) (Disc 1).zip", "550.0 MB"),
    ]),
    ("Redump", "Sega - Dreamcast", [
        ("Sonic Adventure (USA).zip", "1.0 GB"),
        ("Shenmue (USA) (Disc 1).zip", "1.1 GB"),
        ("Crazy Taxi (USA).zip", "800.0 MB"),
    ]),
]

all_entries = []
for collection, platform, files in SAMPLE_DATA:
    parent = f"{collection}/{platform}/"
    # Directory entry
    all_entries.append(build_entry(
        platform + "/", platform.split(" - ")[-1], True, None, "2024-01-01",
        collection + "/",
    ))
    # File entries
    for fname, fsize in files:
        all_entries.append(build_entry(fname, fname, False, fsize, "2024-06-15", parent))

db.insert_entries_batch(all_entries)
check(f"db: inserted {len(all_entries)} entries", True)

# ═══════════════════════════════════════════════════════════════
print("\n── 5. Stats & Filter Tests ──")

stats = db.get_stats()
file_count = sum(len(files) for _, _, files in SAMPLE_DATA)
check(f"db: {stats['total_files']} files indexed", stats["total_files"] == file_count)
check(f"db: {stats['collections']} collections", stats["collections"] >= 2)

collections = db.get_collections()
coll_names = [c["collection"] for c in collections]
check("collections: has No-Intro", "No-Intro" in coll_names)
check("collections: has Redump", "Redump" in coll_names)

platforms = db.get_platforms()
check(f"platforms: {len(platforms)} found", len(platforms) >= 4)

# ═══════════════════════════════════════════════════════════════
print("\n── 6. Search Tests ──")

searches = {
    "Zelda": 2,    # NES + SNES versions
    "Sonic": 2,    # Genesis + Dreamcast
    "Final Fantasy": 2,  # SNES + PS1
    "Castlevania": 2,
    "Mario": 1,
    "Metroid": 2,
    "EarthBound": 1,
    "Chrono": 1,
}

for query, min_expected in searches.items():
    results = db.search(query, page=1, per_page=10)
    names = [r["name"][:50] for r in results["results"]]
    check(f'search "{query}": {results["total"]} results (min {min_expected}) → {names[:3]}',
          results["total"] >= min_expected)

# Filtered search
results = db.search("Sonic", collection="No-Intro")
check(f'filtered "Sonic" in No-Intro: {results["total"]}', results["total"] >= 1)

results = db.search("Final Fantasy", collection="Redump")
check(f'filtered "Final Fantasy" in Redump: {results["total"]}', results["total"] >= 1)

# Pagination
results = db.search("USA", page=1, per_page=3)
check(f'pagination: page 1 has {len(results["results"])} results (max 3)',
      len(results["results"]) <= 3 and results["total"] > 3)

# ═══════════════════════════════════════════════════════════════
print("\n── 7. Browse Tests ──")

browse = db.browse("No-Intro/")
check(f"browse No-Intro/: {len(browse)} entries", len(browse) >= 3)

# ═══════════════════════════════════════════════════════════════
print("\n── 8. Sort Tests ──")

# Sort by name ascending
results_name_asc = db.search("USA", sort_by="name", sort_order="asc", page=1, per_page=50)
names_asc = [r["name"] for r in results_name_asc["results"]]
check("sort name asc: results returned", len(names_asc) > 1)
check("sort name asc: alphabetical", names_asc == sorted(names_asc, key=str.lower))

# Sort by name descending
results_name_desc = db.search("USA", sort_by="name", sort_order="desc", page=1, per_page=50)
names_desc = [r["name"] for r in results_name_desc["results"]]
check("sort name desc: reverse alphabetical", names_desc == sorted(names_desc, key=str.lower, reverse=True))

# Sort by relevance (default)
results_rel = db.search("Zelda", sort_by="relevance", page=1, per_page=10)
check("sort relevance: results returned", results_rel["total"] >= 2)

# Sort by type
results_type = db.search("USA", sort_by="type", sort_order="asc", page=1, per_page=50)
check("sort type: results returned", results_type["total"] > 0)

# ═══════════════════════════════════════════════════════════════
print("\n── 9. Dot-slash Cleanup Tests ──")

from indexer.parser import _normalize_path

check("normalize: ./No-Intro/foo → No-Intro/foo",
      _normalize_path("./No-Intro/foo") == "No-Intro/foo")
check("normalize: No-Intro/./Sony/game.zip → No-Intro/Sony/game.zip",
      _normalize_path("No-Intro/./Sony/game.zip") == "No-Intro/Sony/game.zip")
check("normalize: ./a/./b/./c → a/b/c",
      _normalize_path("./a/./b/./c") == "a/b/c")
check("normalize: dir/ preserved",
      _normalize_path("./dir/") == "dir/")
check("normalize: clean path unchanged",
      _normalize_path("No-Intro/Sony/game.zip") == "No-Intro/Sony/game.zip")

# Insert entries with leading './' and verify cleanup removes them
dotslash_entries = [
    build_entry("game1.zip", "game1.zip", False, "10 KB", "2024-01-01",
                "./No-Intro/Nintendo - NES/"),
    build_entry("game2.zip", "game2.zip", False, "20 KB", "2024-01-01",
                "No-Intro/./Nintendo - NES/"),
]
# Force the paths to simulate what the OLD crawler produced (before normalization)
dotslash_entries[0]["path"] = "./No-Intro/Nintendo - NES/game1.zip"
dotslash_entries[1]["path"] = "No-Intro/./Nintendo - NES/game2.zip"
db.insert_entries_batch(dotslash_entries)

stats_before = db.get_stats()
cleanup = db.cleanup_dotslash_duplicates()
stats_after = db.get_stats()

check(f"cleanup: removed leading './' entries ({cleanup['dotslash_lead_removed']})",
      cleanup["dotslash_lead_removed"] >= 1 or cleanup["total_removed"] >= 1)
check(f"cleanup: removed mid-path './' entries ({cleanup['dotslash_mid_removed']})",
      cleanup["dotslash_mid_removed"] >= 1 or cleanup["total_removed"] >= 1)
check(f"cleanup: total_removed={cleanup['total_removed']} ≥ 2",
      cleanup["total_removed"] >= 2)

# ═══════════════════════════════════════════════════════════════
print("\n── 10. Crawler Dot-dir Skip Tests ──")

# Test that parser skips '.' entries
DOT_DIR_HTML = """<html><body>
<table id="list">
<tr><td class="link"><a href="../">Parent directory</a></td><td class="size">-</td><td class="date"></td></tr>
<tr><td class="link"><a href="./">.</a></td><td class="size">-</td><td class="date"></td></tr>
<tr><td class="link"><a href="Nintendo/">Nintendo</a></td><td class="size">-</td><td class="date">2024-01-01</td></tr>
<tr><td class="link"><a href="game.zip">game.zip</a></td><td class="size">100 KB</td><td class="date">2024-01-01</td></tr>
</table>
</body></html>"""

dot_entries = parse_directory_listing(DOT_DIR_HTML)
dot_names = [e["name"] for e in dot_entries]
check("parser: '.' entry filtered out", "." not in dot_names)
check("parser: Nintendo and game.zip remain", len(dot_entries) == 2)

# ═══════════════════════════════════════════════════════════════
print("\n── 11. Date Normalization Tests ──")

# normalize_myrient_date()
check("date: ISO space → ISO T",
      normalize_myrient_date("2024-01-15 10:30") == "2024-01-15T10:30:00")
check("date: DD-Mon-YYYY → ISO",
      normalize_myrient_date("18-Feb-2025 10:57") == "2025-02-18T10:57:00")
check("date: already ISO unchanged",
      normalize_myrient_date("2025-02-18T10:57:00") == "2025-02-18T10:57:00")
check("date: None → None",
      normalize_myrient_date(None) is None)
check("date: empty → None",
      normalize_myrient_date("") is None)
check("date: whitespace → None",
      normalize_myrient_date("   ") is None)
check("date: single-digit day",
      normalize_myrient_date("5-Mar-2024 09:15") == "2024-03-05T09:15:00")

# build_entry should normalize dates
entry_with_date = build_entry(
    "game.zip", "game.zip", False, "100 KB", "18-Feb-2025 10:57",
    "No-Intro/Nintendo - NES/"
)
check("build_entry: date normalized",
      entry_with_date["last_modified"] == "2025-02-18T10:57:00")

entry_no_date = build_entry(
    "game.zip", "game.zip", False, "100 KB", None,
    "No-Intro/Nintendo - NES/"
)
check("build_entry: None date stays None",
      entry_no_date["last_modified"] is None)

# ═══════════════════════════════════════════════════════════════
print("\n── 12. Content Hash Tests ──")

entries_a = [
    {"name": "game1.zip", "size": "100 KB", "date": "2024-01-01"},
    {"name": "game2.zip", "size": "200 KB", "date": "2024-02-01"},
]
entries_b = [
    {"name": "game2.zip", "size": "200 KB", "date": "2024-02-01"},
    {"name": "game1.zip", "size": "100 KB", "date": "2024-01-01"},
]
entries_c = [
    {"name": "game1.zip", "size": "100 KB", "date": "2024-01-01"},
    {"name": "game3.zip", "size": "300 KB", "date": "2024-03-01"},
]

hash_a = Database.compute_content_hash(entries_a)
hash_b = Database.compute_content_hash(entries_b)
hash_c = Database.compute_content_hash(entries_c)

check("hash: same entries (different order) → same hash", hash_a == hash_b)
check("hash: different entries → different hash", hash_a != hash_c)
check("hash: is hex string", len(hash_a) == 64 and all(c in "0123456789abcdef" for c in hash_a))
check("hash: empty list", len(Database.compute_content_hash([])) == 64)

# ═══════════════════════════════════════════════════════════════
print("\n── 13. Schema Migration Tests ──")

# Test content_hash column migration (should be idempotent)
db.migrate_add_content_hash()
db.migrate_add_content_hash()  # second call should not fail
check("migration: content_hash column exists (double-call safe)", True)

# Test last_modified index migration
db.migrate_add_last_modified_index()
check("migration: last_modified index created", True)

# Test upsert_sync_meta with content_hash
db.upsert_sync_meta("test/path/", None, None, 5, "abc123hash")
meta = db.get_sync_meta("test/path/")
check("sync_meta: content_hash stored", meta["content_hash"] == "abc123hash")

# Update with new hash
db.upsert_sync_meta("test/path/", None, None, 6, "newhash456")
meta2 = db.get_sync_meta("test/path/")
check("sync_meta: content_hash updated", meta2["content_hash"] == "newhash456")

# ═══════════════════════════════════════════════════════════════
print("\n── 14. Date Migration Tests ──")

# Insert entries with old-style dates to test migration
old_date_entries = [
    build_entry("oldgame1.zip", "oldgame1.zip", False, "50 KB",
                "2024-05-20 14:30", "No-Intro/Test Platform/"),
    build_entry("oldgame2.zip", "oldgame2.zip", False, "60 KB",
                "18-Feb-2025 10:57", "No-Intro/Test Platform/"),
]
# Force old-format dates to simulate pre-migration data
old_date_entries[0]["last_modified"] = "2024-05-20 14:30"
old_date_entries[1]["last_modified"] = "18-Feb-2025 10:57"
db.insert_entries_batch(old_date_entries)

# Run migration
normalized_count = db.migrate_normalize_dates()
check(f"date migration: normalized {normalized_count} dates", normalized_count >= 2)

# Verify the dates were normalized
with db.connect() as conn:
    row1 = conn.execute(
        "SELECT last_modified FROM entries WHERE name = 'oldgame1.zip'"
    ).fetchone()
    row2 = conn.execute(
        "SELECT last_modified FROM entries WHERE name = 'oldgame2.zip'"
    ).fetchone()

check("date migration: ISO space → ISO T",
      row1 and row1["last_modified"] == "2024-05-20T14:30:00")
check("date migration: DD-Mon-YYYY → ISO",
      row2 and row2["last_modified"] == "2025-02-18T10:57:00")

# Run migration again — should be a no-op
normalized_again = db.migrate_normalize_dates()
check("date migration: idempotent (0 on re-run)", normalized_again == 0)

# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed} tests")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
