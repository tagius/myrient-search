/* ═══════════════════════════════════════════════════════════════
   Myrient Search — Frontend Logic
   Multi-select searchable dropdowns + two-tier manufacturer/platform
   ═══════════════════════════════════════════════════════════════ */

const MYRIENT_BASE = "https://myrient.erista.me/files/";
let currentPage = 1;
let currentQuery = "";
let totalPages = 0;
let debounceTimer = null;
let currentSort = "relevance";
let currentSortOrder = "asc";

// ─── DOM refs ────────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const hero = $("#hero");
const searchInput = $("#searchInput");
const searchBtnText = $("#searchBtnText");
const searchSpinner = $("#searchSpinner");
const statusBar = $("#statusBar");
const resultCount = $("#resultCount");
const searchTime = $("#searchTime");
const resultsSection = $("#results");
const resultsList = $("#resultsList");
const pagination = $("#pagination");
const prevBtn = $("#prevBtn");
const nextBtn = $("#nextBtn");
const pageInfo = $("#pageInfo");
const statsDisplay = $("#statsDisplay");
const crawlStatus = $("#crawlStatus");
const syncBanner = $("#syncBanner");
const syncMessage = $("#syncMessage");
const syncBtn = $("#syncBtn");

// ═══════════════════════════════════════════════════════════════
// MULTI-SELECT DROPDOWN CLASS
// ═══════════════════════════════════════════════════════════════
class MultiSelect {
    constructor(el, { allLabel = "All", onChange = () => {} } = {}) {
        this.el = el;
        this.allLabel = allLabel;
        this.onChange = onChange;
        this.selected = new Set();
        this.items = [];       // { value, label, count, group? }
        this.trigger = el.querySelector(".ms-trigger");
        this.label = el.querySelector(".ms-label");
        this.arrow = el.querySelector(".ms-arrow");
        this.panel = el.querySelector(".ms-panel");
        this.searchInput = el.querySelector(".ms-search");
        this.optionsCont = el.querySelector(".ms-options");

        this._bindEvents();
    }

    _bindEvents() {
        // Open/close
        this.trigger.addEventListener("click", (e) => {
            e.stopPropagation();
            this.toggle();
        });
        this.trigger.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                this.toggle();
            }
        });

        // Filter as user types
        this.searchInput.addEventListener("input", () => this._renderOptions());

        // Prevent clicks inside panel from closing
        this.panel.addEventListener("click", (e) => e.stopPropagation());

        // Close on outside click
        document.addEventListener("click", () => this.close());
    }

    toggle() {
        if (this.el.classList.contains("open")) {
            this.close();
        } else {
            // Close all other dropdowns first
            document.querySelectorAll(".ms-dropdown.open").forEach((d) => {
                if (d !== this.el) d.classList.remove("open");
            });
            this.el.classList.add("open");
            this.searchInput.value = "";
            this._renderOptions();
            this.searchInput.focus();
        }
    }

    close() {
        this.el.classList.remove("open");
    }

    setItems(items) {
        this.items = items;
        this.selected.clear();
        this._updateLabel();
        this._renderOptions();
    }

    getSelected() {
        return [...this.selected];
    }

    getSelectedString() {
        return this.selected.size > 0 ? [...this.selected].join(",") : "";
    }

    _renderOptions() {
        const filter = this.searchInput.value.toLowerCase();
        let html = "";
        let currentGroup = null;

        for (const item of this.items) {
            // Filter
            if (filter && !item.label.toLowerCase().includes(filter) &&
                !(item.group && item.group.toLowerCase().includes(filter))) {
                continue;
            }

            // Group header
            if (item.group && item.group !== currentGroup) {
                currentGroup = item.group;
                html += `<div class="ms-group-header">${escHtml(item.group)}</div>`;
            }

            const sel = this.selected.has(item.value) ? " selected" : "";
            const countHtml = item.count != null
                ? `<span class="ms-option-count">${item.count.toLocaleString()}</span>`
                : "";

            html += `
                <div class="ms-option${sel}" data-value="${escAttr(item.value)}">
                    <span class="ms-check"></span>
                    <span class="ms-option-text">${escHtml(item.label)}</span>
                    ${countHtml}
                </div>`;
        }

        if (!html) {
            html = `<div style="padding:12px;text-align:center;color:var(--text-dim);font-size:0.85rem">No matches</div>`;
        }

        this.optionsCont.innerHTML = html;

        // Bind click events
        this.optionsCont.querySelectorAll(".ms-option").forEach((opt) => {
            opt.addEventListener("click", () => {
                const val = opt.dataset.value;
                if (this.selected.has(val)) {
                    this.selected.delete(val);
                    opt.classList.remove("selected");
                } else {
                    this.selected.add(val);
                    opt.classList.add("selected");
                }
                this._updateLabel();
                this.onChange(this.getSelected());
            });
        });
    }

    _updateLabel() {
        if (this.selected.size === 0) {
            this.label.textContent = this.allLabel;
            this.label.classList.remove("has-selection");
        } else if (this.selected.size === 1) {
            const val = [...this.selected][0];
            const item = this.items.find((i) => i.value === val);
            this.label.textContent = item ? item.label : val;
            this.label.classList.add("has-selection");
        } else {
            this.label.textContent = `${this.selected.size} selected`;
            this.label.classList.add("has-selection");
        }
    }
}

// ═══════════════════════════════════════════════════════════════
// INITIALIZE DROPDOWNS
// ═══════════════════════════════════════════════════════════════
const collectionMs = new MultiSelect(
    document.querySelector('[data-filter="collection"]'),
    { allLabel: "All Collections", onChange: () => { if (currentQuery) doSearch(1); } }
);

const manufacturerMs = new MultiSelect(
    document.querySelector('[data-filter="manufacturer"]'),
    {
        allLabel: "All Manufacturers",
        onChange: (selected) => {
            // When manufacturer changes, re-filter platform options
            updatePlatformOptions();
            if (currentQuery) doSearch(1);
        },
    }
);

const platformMs = new MultiSelect(
    document.querySelector('[data-filter="platform"]'),
    { allLabel: "All Platforms", onChange: () => { if (currentQuery) doSearch(1); } }
);

const regionMs = new MultiSelect(
    document.querySelector('[data-filter="region"]'),
    { allLabel: "All Regions", onChange: () => { if (currentQuery) doSearch(1); } }
);

// ─── Global manufacturer data (for two-tier filtering) ───────
let allManufacturers = [];  // from /api/manufacturers
let allPlatformItems = [];  // flattened with group info

function updatePlatformOptions() {
    const selMfrs = new Set(manufacturerMs.getSelected());
    if (selMfrs.size === 0) {
        // Show all platforms
        platformMs.setItems(allPlatformItems);
    } else {
        // Filter to only platforms from selected manufacturers
        platformMs.setItems(
            allPlatformItems.filter((p) => selMfrs.has(p.group))
        );
    }
}

// ─── File type icon mapping ──────────────────────────────────
const FILE_ICONS = {
    zip: "📦", "7z": "📦", rar: "📦", gz: "📦", tar: "📦",
    iso: "💿", bin: "💿", cue: "💿", img: "💿", chd: "💿", cso: "💿",
    nes: "🎮", sfc: "🎮", smc: "🎮", gba: "🎮", gbc: "🎮",
    gb: "🎮", nds: "🎮", n64: "🎮", z64: "🎮", v64: "🎮",
    md: "🎮", gen: "🎮", sms: "🎮", gg: "🎮",
    pdf: "📄", txt: "📄", nfo: "📄", dat: "📄",
    jpg: "🖼️", png: "🖼️", bmp: "🖼️",
    mp3: "🎵", flac: "🎵", ogg: "🎵", wav: "🎵",
    xci: "🎮", nsp: "🎮", wbfs: "🎮", wad: "🎮",
    pbp: "🎮", pkg: "🎮", vpk: "🎮",
};

function getIcon(name, isDir) {
    if (isDir) return "📁";
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    return FILE_ICONS[ext] || "📄";
}

// ─── API helper ──────────────────────────────────────────────
async function api(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);
    for (const [k, v] of Object.entries(params)) {
        if (v !== null && v !== undefined && v !== "") {
            url.searchParams.set(k, v);
        }
    }
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
}

// ═══════════════════════════════════════════════════════════════
// SEARCH
// ═══════════════════════════════════════════════════════════════
let isSearching = false;

async function doSearch(page = 1) {
    const q = searchInput.value.trim();
    if (!q) { hideResults(); return; }
    if (isSearching) return;  // prevent concurrent searches

    isSearching = true;
    currentQuery = q;
    currentPage = page;
    hero.classList.add("compact");

    searchBtnText.textContent = "";
    searchSpinner.classList.remove("hidden");

    resultsList.innerHTML = `
        <div class="loading-state">
            <div class="loading-spinner"></div>
            <div class="loading-text">Searching...</div>
        </div>`;
    resultsSection.classList.remove("hidden");
    statusBar.classList.add("hidden");

    const t0 = performance.now();

    // Build filter values — comma-separated for multi-select
    const collectionVal = collectionMs.getSelectedString();

    // For platform, combine manufacturer-implied platforms if no explicit platform selected
    let platformVal = platformMs.getSelectedString();
    if (!platformVal && manufacturerMs.getSelected().length > 0) {
        // Get all platforms under selected manufacturers
        const selMfrs = new Set(manufacturerMs.getSelected());
        const impliedPlatforms = allPlatformItems
            .filter((p) => selMfrs.has(p.group))
            .map((p) => p.value);
        platformVal = impliedPlatforms.join(",");
    }

    const regionVal = regionMs.getSelectedString();

    try {
        const data = await api("/api/search", {
            q,
            collection: collectionVal,
            platform: platformVal,
            region: regionVal,
            sort_by: currentSort,
            sort_order: currentSortOrder,
            page,
            per_page: 50,
        });

        const elapsed = ((performance.now() - t0) / 1000).toFixed(2);
        totalPages = data.pages;

        resultCount.textContent = `${data.total.toLocaleString()} results`;
        searchTime.textContent = `in ${elapsed}s`;
        statusBar.classList.remove("hidden");

        if (data.results.length === 0) {
            resultsList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔍</div>
                    <div>No results found for "<strong>${escHtml(q)}</strong>"</div>
                    <div style="margin-top:0.5rem;font-size:0.88rem">
                        Try different keywords or adjust your filters
                    </div>
                </div>`;
        } else {
            resultsList.innerHTML = data.results.map(renderResult).join("");
        }

        if (totalPages > 1) {
            pagination.classList.remove("hidden");
            prevBtn.disabled = page <= 1;
            nextBtn.disabled = page >= totalPages;
            pageInfo.textContent = `Page ${page} of ${totalPages}`;
        } else {
            pagination.classList.add("hidden");
        }

        history.replaceState({ q, page }, "", `?q=${encodeURIComponent(q)}&page=${page}`);

    } catch (err) {
        resultsList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⚠️</div>
                <div>Search failed: ${escHtml(err.message)}</div>
            </div>`;
        statusBar.classList.remove("hidden");
        resultCount.textContent = "Error";
        searchTime.textContent = "";
    } finally {
        isSearching = false;
        searchBtnText.textContent = "Search";
        searchSpinner.classList.add("hidden");
    }
}

function isRecentEntry(dateStr) {
    if (!dateStr) return false;
    try {
        // Dates are ISO 8601 like "2025-02-18T10:57:00"
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = (now - d) / (1000 * 60 * 60 * 24);
        return diffDays <= 30;
    } catch { return false; }
}

function formatDate(dateStr) {
    if (!dateStr) return "";
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
    } catch { return dateStr; }
}

// Encode a Myrient file path for download URLs
// Directory segments: only need encodeURIComponent (spaces, & etc.)
// Filename (last segment): also needs (, ), !, ', ~, * encoded
function encodeMyrientPath(path) {
    const parts = path.split("/");
    const dirs = parts.slice(0, -1).map(encodeURIComponent);
    const filename = encodeURIComponent(parts[parts.length - 1])
        .replace(/\(/g, "%28")
        .replace(/\)/g, "%29")
        .replace(/!/g, "%21")
        .replace(/'/g, "%27")
        .replace(/~/g, "%7E")
        .replace(/\*/g, "%2A");
    return [...dirs, filename].join("/");
}

function renderResult(entry) {
    const icon = getIcon(entry.name, entry.is_directory);
    const fileUrl = MYRIENT_BASE + encodeMyrientPath(entry.path);

    // Parent folder URL — everything up to the last /
    const parentPath = entry.path.includes("/")
        ? entry.path.substring(0, entry.path.lastIndexOf("/") + 1)
        : "";
    const folderUrl = MYRIENT_BASE + parentPath.split("/").map(encodeURIComponent).join("/");

    let badges = "";
    if (isRecentEntry(entry.last_modified)) {
        badges += `<span class="badge badge-new">New</span>`;
    }
    if (entry.collection) badges += `<span class="badge">${escHtml(entry.collection)}</span>`;
    if (entry.platform)   badges += `<span class="badge badge-platform">${escHtml(truncate(entry.platform, 35))}</span>`;
    if (entry.region)     badges += `<span class="badge badge-region">${escHtml(entry.region)}</span>`;
    if (entry.file_type)  badges += `<span class="badge badge-type">.${escHtml(entry.file_type)}</span>`;
    if (entry.file_size)  badges += `<span class="badge badge-size">${escHtml(entry.file_size)}</span>`;

    const dateHtml = entry.last_modified
        ? `<span class="result-date">${formatDate(entry.last_modified)}</span>`
        : "";

    return `
        <div class="result-card">
            <div class="result-icon">${icon}</div>
            <div class="result-body">
                <a href="${escAttr(folderUrl)}" target="_blank" rel="noopener" class="result-title-link" title="${escAttr(entry.name)}">${escHtml(entry.name)}</a>
                <div class="result-badges">${badges}</div>
                <div class="result-path">${escHtml(entry.path)}${dateHtml}</div>
            </div>
            <div class="result-actions">
                <a href="${escAttr(fileUrl)}" class="btn-sm btn-download" title="Download file">Download</a>
            </div>
        </div>`;
}

function hideResults() {
    hero.classList.remove("compact");
    resultsSection.classList.add("hidden");
    statusBar.classList.add("hidden");
    pagination.classList.add("hidden");
    resultsList.innerHTML = "";
}

// ═══════════════════════════════════════════════════════════════
// LOAD FILTERS
// ═══════════════════════════════════════════════════════════════
async function loadFilters() {
    try {
        const [collections, manufacturers] = await Promise.all([
            api("/api/collections"),
            api("/api/manufacturers"),
        ]);

        // Collections
        collectionMs.setItems(
            collections.map((c) => ({
                value: c.collection,
                label: c.collection,
                count: c.count,
            }))
        );

        // Manufacturers
        allManufacturers = manufacturers;
        manufacturerMs.setItems(
            manufacturers.map((m) => ({
                value: m.manufacturer,
                label: m.manufacturer,
                count: m.total_count,
            }))
        );

        // Platforms (flattened, grouped by manufacturer)
        allPlatformItems = [];
        for (const mfr of manufacturers) {
            for (const plat of mfr.platforms) {
                // Extract short console name from "Manufacturer - Console"
                const shortName = plat.platform.includes(" - ")
                    ? plat.platform.split(" - ").slice(1).join(" - ")
                    : plat.platform;
                allPlatformItems.push({
                    value: plat.platform,
                    label: shortName,
                    count: plat.count,
                    group: mfr.manufacturer,
                });
            }
        }
        platformMs.setItems(allPlatformItems);

        // Regions (static list — could be fetched but these are the common ones)
        const REGIONS = [
            "USA", "Europe", "Japan", "World", "Germany", "France", "Spain",
            "Italy", "Korea", "Brazil", "UK", "Asia", "Australia", "Netherlands",
            "Sweden", "Norway", "Denmark", "Finland", "Portugal", "Russia",
            "China", "Taiwan", "Hong Kong", "Canada",
        ];
        regionMs.setItems(REGIONS.map((r) => ({ value: r, label: r, count: null })));

    } catch (err) {
        console.warn("Failed to load filters:", err);
    }
}

// ═══════════════════════════════════════════════════════════════
// STATS & SYNC
// ═══════════════════════════════════════════════════════════════
async function loadStats() {
    try {
        const stats = await api("/api/stats");
        const parts = [];
        if (stats.total_files > 0) parts.push(`${stats.total_files.toLocaleString()} files`);
        if (stats.collections > 0) parts.push(`${stats.collections} collections`);
        if (stats.platforms > 0)   parts.push(`${stats.platforms} platforms`);
        statsDisplay.textContent = parts.join(" | ") || "No data yet";

        // Show crawler status in footer
        updateCrawlStatus(stats);

        if (stats.crawl_status && stats.crawl_status.status === "crawling") {
            showSyncBanner(stats.crawl_status.message || "Indexing...");
        }
    } catch (err) {
        statsDisplay.textContent = "Could not load stats";
    }
}

function updateCrawlStatus(stats) {
    if (!crawlStatus) return;
    const cs = stats.crawl_status;

    if (!cs) {
        crawlStatus.innerHTML = `<span class="status-dot status-error"></span> Never synced`;
        return;
    }

    if (cs.status === "crawling") {
        const msg = cs.message || "Indexing...";
        crawlStatus.innerHTML = `<span class="status-dot status-crawling"></span> ${escHtml(msg)}`;
    } else if (cs.status === "error") {
        crawlStatus.innerHTML = `<span class="status-dot status-error"></span> Sync error`;
        crawlStatus.title = cs.message || "Last sync failed";
    } else {
        // idle — show last synced time
        const syncedAt = stats.last_synced || cs.finished_at;
        if (syncedAt) {
            const ago = timeAgo(syncedAt);
            crawlStatus.innerHTML = `<span class="status-dot status-idle"></span> Synced ${ago}`;
            crawlStatus.title = `Last sync completed: ${syncedAt}`;
        } else if (cs.started_at) {
            // Crawl was started but never finished (interrupted)
            crawlStatus.innerHTML = `<span class="status-dot status-idle"></span> Indexed (sync incomplete)`;
            crawlStatus.title = `Last crawl started: ${cs.started_at}, interrupted before completion`;
        } else {
            crawlStatus.innerHTML = `<span class="status-dot status-error"></span> Never synced`;
        }
    }
}

function timeAgo(dateStr) {
    try {
        // dateStr is like "2026-02-17 22:43:11" (UTC from SQLite)
        const d = new Date(dateStr.replace(" ", "T") + "Z");
        const now = new Date();
        const diffMs = now - d;
        const mins = Math.floor(diffMs / 60000);
        if (mins < 1) return "just now";
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        if (days < 30) return `${days}d ago`;
        return dateStr.split(" ")[0];  // just date
    } catch { return dateStr; }
}

function showSyncBanner(msg) {
    syncMessage.textContent = msg;
    syncBanner.classList.remove("hidden");
    pollSync();
}

let syncPollTimer = null;
let syncPollCount = 0;
const MAX_POLL_ATTEMPTS = 600; // stop after 30 minutes (600 * 3s)

function pollSync() {
    if (syncPollTimer) return;
    syncPollCount = 0;
    syncPollTimer = setInterval(async () => {
        syncPollCount++;
        // Safety: stop polling after max attempts to prevent infinite loop
        if (syncPollCount > MAX_POLL_ATTEMPTS) {
            syncBanner.classList.add("hidden");
            clearInterval(syncPollTimer);
            syncPollTimer = null;
            loadStats();  // refresh footer on timeout
            return;
        }
        try {
            const status = await api("/api/sync/status");
            if (status.status === "crawling") {
                syncMessage.textContent = status.message || "Indexing...";
                // Update footer to show crawling status in real-time
                if (crawlStatus) {
                    crawlStatus.innerHTML = `<span class="status-dot status-crawling"></span> ${escHtml(status.message || "Indexing...")}`;
                }
            } else {
                syncBanner.classList.add("hidden");
                clearInterval(syncPollTimer);
                syncPollTimer = null;
                loadStats();
                loadFilters();
            }
        } catch {
            clearInterval(syncPollTimer);
            syncPollTimer = null;
        }
    }, 3000);
}

// ═══════════════════════════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════════════════════════
searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => doSearch(1), 300);
});

document.getElementById("searchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    doSearch(1);
});

prevBtn.addEventListener("click", () => { if (currentPage > 1) doSearch(currentPage - 1); });
nextBtn.addEventListener("click", () => { if (currentPage < totalPages) doSearch(currentPage + 1); });

syncBtn.addEventListener("click", async () => {
    if (!confirm("Start a manual sync with Myrient?")) return;
    try {
        await fetch("/api/sync", { method: "POST" });
        showSyncBanner("Sync started...");
    } catch (err) {
        alert("Failed to start sync: " + err.message);
    }
});

// ─── Sort controls ────────────────────────────────────────────
document.querySelectorAll(".sort-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
        const sort = btn.dataset.sort;
        if (sort === currentSort) return;
        document.querySelectorAll(".sort-pill").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentSort = sort;
        // Auto-set sensible default direction for each sort type
        if (sort === "relevance" || sort === "name" || sort === "type" || sort === "platform" || sort === "region") {
            currentSortOrder = "asc";
        } else {
            currentSortOrder = "desc";  // size, date → largest/newest first by default
        }
        updateSortOrderBtn();
        if (currentQuery) doSearch(1);
    });
});

const sortOrderBtn = document.getElementById("sortOrderBtn");
sortOrderBtn.addEventListener("click", () => {
    currentSortOrder = currentSortOrder === "asc" ? "desc" : "asc";
    updateSortOrderBtn();
    if (currentQuery) doSearch(1);
});

function updateSortOrderBtn() {
    if (currentSortOrder === "desc") {
        sortOrderBtn.classList.add("desc");
        sortOrderBtn.title = "Descending — click to toggle";
    } else {
        sortOrderBtn.classList.remove("desc");
        sortOrderBtn.title = "Ascending — click to toggle";
    }
}

// Keyboard shortcuts
document.addEventListener("keydown", (e) => {
    // Don't capture if typing in a dropdown search
    if (e.target.classList.contains("ms-search")) return;

    if (e.key === "/" && document.activeElement !== searchInput) {
        e.preventDefault();
        searchInput.focus();
    }
    if (e.key === "Escape") {
        // Close any open dropdown first
        const openDd = document.querySelector(".ms-dropdown.open");
        if (openDd) {
            openDd.classList.remove("open");
            return;
        }
        searchInput.value = "";
        hideResults();
    }
});

// URL state on load
function loadFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    const page = parseInt(params.get("page")) || 1;
    if (q) {
        searchInput.value = q;
        doSearch(page);
    }
}

// ─── Utilities ───────────────────────────────────────────────
function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
}

function escAttr(s) {
    return (s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function truncate(s, max) {
    return s && s.length > max ? s.slice(0, max) + "…" : s;
}

// ─── Init ────────────────────────────────────────────────────
// Always load filters first (independent of crawl state), then stats
loadFilters().then(() => {
    loadStats();
    loadFromUrl();
});
