# YouTube Music M3U Playlist Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, user-friendly Python CLI tool (`ytmusicsync`) that reads legacy iTunes M3U/M3U8 playlist exports and reconstructs matching playlists on YouTube Music containing **only** songs from the user's uploaded music library.

**Architecture:** A modular Python pipeline consisting of an authentication manager (OAuth + browser headers), an M3U/M3U8 tag and path parser, an uploaded music fetcher with local SQLite caching (to handle 30,000+ tracks efficiently without hitting rate limits), a normalized fuzzy matching engine, and a playlist sync manager supporting dry-run previews, batch uploads, and automatic 5,000-track playlist chunking.

**Tech Stack:** Python 3.10+, `ytmusicapi` (YouTube Music unofficial API), `rapidfuzz` (fast C-accelerated fuzzy matching), `mutagen` (optional local audio tag parsing), `sqlite3` (built-in local library caching), `pytest` (test harness).

---

## Global Constraints

- Must match **only** against the user's personal YouTube Music uploads (`get_library_upload_songs`), never against YouTube's public streaming catalog or public video search.
- Must support 30,000+ songs efficiently through local persistent caching (SQLite) so library fetches can resume and don't need to re-download on every run.
- Must gracefully handle YouTube's 5,000-song-per-playlist hard limit by splitting oversized playlists into numbered parts (e.g., `Playlist (Part 1/2)`).
- Must provide a non-destructive `--dry-run` mode and generate detailed CSV audit reports (matched vs unmatched tracks).
- Must be friendly for a user with basic programming literacy: simple setup, clear console prompts, progress bars (`tqdm`), and actionable error messages.

## Review Focus

1. **Large Library Throttling/Network Interruption:** Fetching 30,000+ uploaded songs might drop connection mid-way. Behavior: Paginated SQLite cache saves batches incrementally with resumption capability.
2. **Missing Audio Files vs Missing Metadata:** M3U files may point to old paths that no longer exist on disk, or may lack `#EXTINF` lines. Behavior: Parser extracts metadata from `#EXTINF` if present, falls back to path/directory heuristics (`.../Artist/Album/Title.ext`), and uses `mutagen` to read actual ID3/tag files if the file path is accessible locally.
3. **Punctuation & Remaster Metadata Discrepancies:** iTunes tags often have "(2009 Remaster)" or "feat. Artist" while YTM upload tags might differ. Behavior: Multi-tier matcher applies regex cleaning (removes bracketed edition tags, featured artists, track numbers) and fuzzy Levenshtein ratio scoring.
4. **Duplicate Track Ambiguity:** An artist may have the same song appear on a studio album and a greatest hits album. Behavior: Matcher prioritizes exact (Artist + Title + Album) match before falling back to (Artist + Title).
5. **YouTube Music Rate Limits & Batch Size:** Adding thousands of songs in one request can fail or time out. Behavior: `add_playlist_items` is executed in batches of 50-100 with exponential backoff / retry.

---

## User Review Required

> [!IMPORTANT]
> **Authentication Method**: YouTube Music requires authentication to access your personal uploaded library.
> - **Browser Session Setup (Recommended for ease)**: Open `music.youtube.com` in your browser, open Network DevTools, copy the `cookie` or `browse` request header, and paste it into the interactive prompt. This does not require setting up a Google Cloud Developer account.
> - **OAuth Device Flow**: Requires creating a free Google Cloud project and OAuth Client ID with "TVs and Limited Input Devices". We support both, but Browser Session setup is much faster for non-developers.

> [!WARNING]
> **5,000-Song YouTube Playlist Limit**: YouTube imposes a strict hard limit of 5,000 songs per playlist. If an M3U playlist exceeds 5,000 songs, `ytmusicsync` will automatically split it into sequenced playlists (e.g., "Library (Part 1 of 7)").

---

## Open Questions

1. **Local Audio Files Presence**: Do the original music files still exist on the local hard drive at the paths listed in the M3U files, or do only the `.m3u` text files remain? (The tool is designed to support both: reading local audio ID3 tags if files exist, or parsing the text paths and `#EXTINF` tags if files are gone.)
2. **Multiple M3U files vs Single M3U**: Will you be syncing individual playlist files, or a folder containing dozens/hundreds of M3U files? (We will support both single-file and directory batch mode.)

---

## Proposed Changes

### Component 1: Core Setup & Dependency Manifest

#### [NEW] `requirements.txt`
Dependencies: `ytmusicapi>=1.8.0`, `rapidfuzz>=3.0.0`, `mutagen>=1.47.0`, `tqdm>=4.66.0`, `pytest>=7.0.0`.

#### [NEW] `src/__init__.py`
Package initialization.

---

### Component 2: M3U Parser & Metadata Extraction

#### [NEW] `src/m3u_parser.py`
Parses M3U and M3U8 files with encoding resilience (UTF-8, Latin-1, Windows-1252, UTF-8-BOM).
- Supports `#EXTINF` duration, artist, and title extraction.
- Supports path-based heuristic parsing (e.g. `Artist/Album/Track Title.mp3` iTunes directory structure).
- Optionally uses `mutagen` if the file exists on the local filesystem to inspect exact ID3/M4A tags.
- Returns a normalized list of `TrackEntry` dataclasses.

```python
@dataclass
class TrackEntry:
    raw_path: str
    title: str
    artist: str = ""
    album: str = ""
    duration_seconds: int = 0
```

---

### Component 3: YouTube Music Client & Uploads Caching

#### [NEW] `src/ytm_client.py`
Wraps `ytmusicapi` to manage authentication and interactions with personal uploads.
- Supports loading credentials from `browser.json` or `oauth.json`.
- Interactive setup helper for first-time users.
- Verification call to confirm account connection.

#### [NEW] `src/cache_manager.py`
Manages a local SQLite database (`uploads_cache.sqlite`) storing the user's uploaded songs library.
- Schema: `video_id`, `title`, `artist`, `album`, `norm_title`, `norm_artist`, `norm_album`, `duration`, `raw_json`.
- Incremental pagination fetch: updates SQLite in batches of 100 songs so network interruptions don't discard progress.
- Search queries optimized with SQL indices and normalized keys.

---

### Component 4: Track Matching Engine

#### [NEW] `src/matcher.py`
Matches an M3U `TrackEntry` against the cached uploaded library.
- **Normalization pipeline**:
  - Lowercase, strip accents/diacritics (`unicodedata.normalize`).
  - Strip punctuation and extra spaces.
  - Remove parenthetical tags: `(Remastered ...)`, `[Live]`, `(feat. ...)`.
  - Strip leading track numbers (`01 - `, `01. `).
- **Match Strategy (Ordered cascade)**:
  1. Exact Match: `norm_title` + `norm_artist` + `norm_album` (Confidence 100%)
  2. Artist + Title Match: `norm_title` + `norm_artist` (Confidence 95%)
  3. Fuzzy Match: RapidFuzz token sort ratio $\ge 88\%$ on combined Artist + Title (Confidence 88-94%)
  4. Unmatched: Flagged for review.

```python
@dataclass
class MatchResult:
    track: TrackEntry
    matched_video_id: str | None
    matched_title: str | None
    matched_artist: str | None
    confidence: float
    match_type: str  # 'exact_full', 'exact_artist_title', 'fuzzy', 'none'
```

---

### Component 5: Playlist Builder & CLI Workflow

#### [NEW] `src/playlist_builder.py`
Takes matched video IDs and creates/updates playlists on YouTube Music.
- Handles playlist chunking when track count exceeds 5,000.
- Adds tracks in safe batches (50-100 items per API call).
- Dry-run mode: prints match statistics, sample matches, and skips API writes.
- Exports a CSV report (`sync_report_<playlist_name>.csv`) showing every track, matched video ID, confidence, and status.

#### [NEW] `src/cli.py`
User-friendly command-line interface with subcommands:
- `auth`: Guides user through connection.
- `cache`: Fetches and caches the 30,000+ uploaded songs to SQLite.
- `sync`: Reconstructs an M3U file as a YouTube Music playlist.
- `batch-sync`: Syncs all M3U files in a given folder.

#### [NEW] `README.md`
Step-by-step guide written specifically for a user with basic programming literacy:
- How to install requirements (`pip install -r requirements.txt`).
- How to get credentials (with screenshot/browser instructions).
- How to run dry-run and live sync commands.

---

## Step-by-Step Task Breakdown

### Task 1: Project Scaffolding & Dependencies
**Files:**
- Create: `requirements.txt`, `src/__init__.py`
- Test: `tests/test_scaffolding.py`

- [ ] **Step 1: Write verification test for package imports**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Create `requirements.txt` and install dependencies**
- [ ] **Step 4: Verify test passes**
- [ ] **Step 5: Git commit**

---

### Task 2: M3U Parser Implementation
**Files:**
- Create: `src/m3u_parser.py`
- Test: `tests/test_m3u_parser.py`

- [ ] **Step 1: Write unit tests for various M3U formats** (standard `#EXTINF`, path-only lines, windows backslashes, URI-encoded paths, UTF-8 and Latin-1 encodings).
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `parse_m3u(file_path: Path) -> List[TrackEntry]`**
- [ ] **Step 4: Run test to verify all parser tests pass**
- [ ] **Step 5: Git commit**

---

### Task 3: Local Uploads Cache & YTM Client Wrapper
**Files:**
- Create: `src/cache_manager.py`, `src/ytm_client.py`
- Test: `tests/test_cache_manager.py`

- [ ] **Step 1: Write unit tests for SQLite cache CRUD and batch upsert**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `UploadsCache` SQLite database schema, normalizer, and querying methods**
- [ ] **Step 4: Implement `YTMClient` wrapper around `ytmusicapi` with paginated sync to `UploadsCache`**
- [ ] **Step 5: Run tests and verify cache persistence and indexing**
- [ ] **Step 6: Git commit**

---

### Task 4: Matching Engine
**Files:**
- Create: `src/matcher.py`
- Test: `tests/test_matcher.py`

- [ ] **Step 1: Write test cases covering exact matches, punctuation differences, remaster tags, and fuzzy matches**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement string normalization regex and `TrackMatcher.match_track(track: TrackEntry) -> MatchResult`**
- [ ] **Step 4: Run test to verify high-accuracy matching and fuzzy threshold gating**
- [ ] **Step 5: Git commit**

---

### Task 5: Playlist Builder & Chunking Manager
**Files:**
- Create: `src/playlist_builder.py`
- Test: `tests/test_playlist_builder.py`

- [ ] **Step 1: Write unit tests for playlist chunking (>5,000 tracks), batching, and CSV report generation**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `PlaylistBuilder` with dry-run support, batch addition, and report exporter**
- [ ] **Step 4: Run test to verify correct chunking and reporting**
- [ ] **Step 5: Git commit**

---

### Task 6: CLI & User Documentation
**Files:**
- Create: `src/cli.py`, `main.py`, `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write CLI argument parsing and help test**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `cli.py` with commands `auth`, `cache`, `sync`, and `batch-sync`**
- [ ] **Step 4: Write clear, non-technical instructions in `README.md`**
- [ ] **Step 5: Run end-to-end simulated sync test with mock data**
- [ ] **Step 6: Git commit**

---

## Verification Plan

### Automated Tests
```bash
pytest -v tests/
```
Tests will verify:
- Parsing M3U8 files with `#EXTINF` metadata and raw file paths.
- Resilient string normalization (diacritics, "feat.", "(Remastered)").
- SQLite library caching and indexed lookup performance.
- Multi-tier matching accuracy and minimum confidence thresholds.
- Safe chunking of lists exceeding 5,000 items into Part 1, Part 2.
- CSV audit report generation.

### Manual Verification
1. Run `python main.py auth` to verify credential setup and account connection.
2. Run `python main.py cache` to populate the local SQLite cache from YouTube Music uploads.
3. Run `python main.py sync sample_playlist.m3u --dry-run` to inspect matching percentage, sample matched tracks, and audit CSV without creating playlists.
4. Run `python main.py sync sample_playlist.m3u` to create the real playlist on YouTube Music and verify the playlist appears in the user's YouTube Music app pointing strictly to uploaded tracks.

