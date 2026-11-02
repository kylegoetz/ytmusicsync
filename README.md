# ytmusicsync

A simple, reliable Python tool to reconstruct your legacy iTunes `.m3u` / `.m3u8` playlists on YouTube Music **using exclusively the music you personally uploaded**.

---

## Why this tool?

When you export playlists from a large legacy iTunes library (30,000+ tracks), streaming matchers often match songs to random YouTube videos, karaoke covers, or live bootlegs. 

`ytmusicsync` guarantees:
1. **Uploads Only:** Matches strictly against the tracks you uploaded to YouTube Music. It will never add random public streaming catalog tracks or YouTube videos.
2. **Handles 30,000+ Tracks:** Caches your full uploaded catalog locally in a fast SQLite database so you never have to re-download 30k tracks on every sync.
3. **Overcomes YouTube's 5,000 Track Cap:** If a playlist has more than 5,000 songs, it automatically splits it into sequenced parts (e.g. `My Playlist (Part 1 of 3)`).
4. **Safety & Audit Reports:** Includes a non-destructive `--dry-run` mode and creates a `.csv` audit file showing exactly which songs were matched and which were missing from your uploads.
5. **Batch Folder Sync:** Sync a single `.m3u` file or an entire directory of smart playlists at once.

---

## Quick Start Guide

### Step 1: Install Dependencies

Make sure you have Python 3.10+ installed. In your terminal, navigate to this folder and run:

```bash
pip install -r requirements.txt
```

*(If using a virtual environment: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`)*

---

### Step 2: Connect your YouTube Music Account

Run:
```bash
python main.py auth
```

Select **Option [1] Browser Session Setup** (the easiest method — no developer account needed):

1. Open [music.youtube.com](https://music.youtube.com) in your web browser (Chrome or Firefox) while signed into your Google account.
2. Open Developer Tools: press `F12` (or Right-Click anywhere $\rightarrow$ **Inspect**), then click the **Network** tab.
3. In the filter box at the top of Network, type `browse`.
4. Click on **Uploads** or **Library** on YouTube Music to trigger network traffic.
5. In the Network list, right-click on the `browse` entry:
   - Select **Copy** $\rightarrow$ **Copy request headers**.
6. Back in your terminal, paste the copied text when prompted, press `Enter`, then press `Ctrl-D` (on Mac/Linux) or `Ctrl-Z` + `Enter` (on Windows).
7. It will save `browser.json` and verify your connection!

*(Alternative: If you prefer Google Cloud OAuth, select Option [2] and follow the prompts).*

---

### Step 3: Cache your Uploaded Songs

Because fetching 30,000+ uploaded songs over the internet takes a few minutes, `ytmusicsync` downloads your uploaded track catalog once and stores it in a fast local database (`uploads_cache.sqlite`):

```bash
python main.py cache
```

You will see a live progress bar as it fetches your uploaded songs. Once completed, all playlist matching runs locally in seconds without re-downloading!

> **Note:** If you upload more songs to YouTube Music in the future, just re-run `python main.py cache` to update your local catalog.

---

### Step 4: Preview Playlists with Dry-Run (Safe Mode)

Before creating anything on YouTube Music, test your matching accuracy without making changes:

#### To test a single playlist:
```bash
python main.py sync "path/to/playlist.m3u" --dry-run
```

#### To test an entire folder of playlists:
```bash
python main.py batch-sync "path/to/playlists_folder" --dry-run
```

This will print match statistics in your terminal:
```text
Processing playlist: 'Classic Rock' (Classic Rock.m3u)
Extracted 1,240 track entries from M3U.
Matching tracks to uploaded library: 100%|██████████| 1240/1240 [00:01<00:00, 1082tracks/s]

--- Sync Summary ---
Playlist:        Classic Rock
Total Tracks:    1240
Matched Tracks:  1198 (96.6%)
Unmatched:       42
Mode:            DRY-RUN (no changes made)
Audit Report:    sync_report_Classic Rock.csv
```

A detailed CSV report (`sync_report_<playlist_name>.csv`) is generated. You can open it in Excel or Numbers to see every matched song and inspect any unmatched tracks.

---

### Step 5: Sync Playlists to YouTube Music

When you are satisfied with the dry run results, run the command without `--dry-run`:

#### Sync a single playlist:
```bash
python main.py sync "path/to/playlist.m3u"
```

#### Sync all playlists in a folder:
```bash
python main.py batch-sync "path/to/playlists_folder"
```

Your playlists will immediately appear in your YouTube Music library, containing your uploaded tracks in original playlist order!

---

## Helpful Options

| Option | Command | Description |
|---|---|---|
| `--dry-run` | `sync` / `batch-sync` | Previews matches and writes CSV report without creating playlists |
| `--allow-duplicates` | `sync` / `batch-sync` | Allows the same uploaded song to appear multiple times if present in M3U |
| `--fuzzy-threshold` | `sync` / `batch-sync` | Fuzzy matching sensitivity (default: `88.0`). Higher is stricter |
| `--cache-db` | `cache` / `sync` | Specify a custom SQLite database location |
| `--name "Custom Name"` | `sync` | Set a custom playlist name instead of the M3U filename |
| `--reports-dir` | `batch-sync` | Destination folder for audit CSV reports (default: `reports/`) |

---

## Troubleshooting

- **"Uploads cache is empty"**:
  Run `python main.py cache` first so the tool knows what songs you have uploaded.
- **"Authentication error"**:
  Run `python main.py auth` and re-paste your browser request headers. (Make sure you are logged into YouTube Music in the browser you copied from).
- **Audio file paths in M3U**:
  The parser works whether original audio files exist on disk or not. If files are missing, it intelligently parses the track title, artist, and album from the `#EXTINF` tags and folder path structure.
