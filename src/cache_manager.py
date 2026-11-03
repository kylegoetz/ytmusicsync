import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Self


def normalize_text(text: str) -> str:
    """
    Normalizes a song title, artist, or album string for high-accuracy matching:
    - Normalizes unicode characters (e.g. removes accents: 'Café' -> 'cafe')
    - Strips track numbering prefixes ('01 - ') bounded to 1-3 digits (preserving years like 1984)
    - Removes parenthetical additions like '(feat. ...)', '[Live at ...]', '(Remastered ...)'
    - Removes unparenthesized featured artist suffixes ('feat. Artist')
    - Removes remaster/edition suffixes (' - 2017 Remaster', ' - Remastered 2009')
    - Removes special punctuation and collapses whitespace.
    """
    if not text:
        return ""

    # Strip unicode accents/diacritics
    nfkd = unicodedata.normalize("NFKD", text)
    cleaned = "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

    # Strip leading track numbers (e.g. '01 ', '01 - ', '01. ') bounded to 1-3 digits
    cleaned = re.sub(r"^\d{1,3}[\s\.\-_]+\s*", "", cleaned)

    # Remove contents inside parentheses/brackets matching known noise
    noise_pattern = (
        r"[\(\[\{][^\(\)\[\]\{\}]*\b(?:feat\.?|ft\.?|remaster(?:ed)?|live|bonus|deluxe|edit|mix|"
        r"version|mono|stereo|anniversary|radio edit|original mix|extended)\b[^\(\)\[\]\{\}]*[\)\]\}]"
    )
    cleaned = re.sub(noise_pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove unparenthesized featured artists (e.g. "feat. Alicia Keys" or "ft. Artist")
    cleaned = re.sub(r"\b(?:feat\.?|ft\.?)\s+.*$", "", cleaned, flags=re.IGNORECASE)

    # Remove remaster, live, or edition suffixes (e.g. " - 2017 Remaster", " - Remastered 2009", " - 2011 Mix")
    suffix_noise = (
        r"\s*-\s*(?:(?:\d{4}\s+)?remaster(?:ed)?(?:\s+(?:version|\d{4}))?|"
        r"live(?:\s+at\s+[\w\s]+)?|\d{4}\s+mix|deluxe\s+version|mono|stereo).*$"
    )
    cleaned = re.sub(suffix_noise, "", cleaned, flags=re.IGNORECASE)

    # Remove any leftover empty brackets
    cleaned = re.sub(r"[\(\[\{][\s\-_]*[\)\]\}]", "", cleaned)

    # Replace punctuation (non-alphanumeric except space) with space
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Collapse repeated whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


class UploadsCache:
    """
    Local SQLite cache for storing and querying YouTube Music uploaded tracks.
    Designed for fast indexed matching across 30,000+ tracks.
    """

    def __init__(self, db_path: Path | str = "uploads_cache.sqlite"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    video_id TEXT PRIMARY KEY,
                    entity_id TEXT,
                    title TEXT NOT NULL,
                    artist TEXT,
                    album TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    norm_title TEXT NOT NULL,
                    norm_artist TEXT,
                    norm_album TEXT,
                    raw_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_norm_artist_title ON uploads(norm_artist, norm_title)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_norm_title ON uploads(norm_title)")

    def upsert_songs(self, songs: list[dict[str, Any]]) -> int:
        """
        Batch upserts song dictionaries returned by ytmusicapi.get_library_upload_songs().
        """
        records = []
        for song in songs:
            video_id = song.get("videoId")
            if not video_id:
                continue

            entity_id = song.get("entityId") or ""
            title = song.get("title") or ""
            
            artists = song.get("artists")
            if isinstance(artists, list) and artists:
                artist_name = artists[0].get("name", "") if isinstance(artists[0], dict) else str(artists[0])
            elif isinstance(artists, str):
                artist_name = artists
            else:
                artist_name = ""

            album = song.get("album")
            if isinstance(album, dict):
                album_name = album.get("name", "")
            elif isinstance(album, str):
                album_name = album
            else:
                album_name = ""

            duration = song.get("duration_seconds") or 0
            if not duration and "duration" in song and isinstance(song["duration"], str):
                parts = song["duration"].split(":")
                try:
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                except ValueError:
                    duration = 0

            norm_title = normalize_text(title)
            norm_artist = normalize_text(artist_name)
            norm_album = normalize_text(album_name)
            raw_json = json.dumps(song)

            records.append((
                video_id,
                entity_id,
                title,
                artist_name,
                album_name,
                duration,
                norm_title,
                norm_artist,
                norm_album,
                raw_json,
            ))

        with self._conn:
            self._conn.executemany("""
                INSERT INTO uploads (
                    video_id, entity_id, title, artist, album, duration_seconds,
                    norm_title, norm_artist, norm_album, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET
                    entity_id=excluded.entity_id,
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    duration_seconds=excluded.duration_seconds,
                    norm_title=excluded.norm_title,
                    norm_artist=excluded.norm_artist,
                    norm_album=excluded.norm_album,
                    raw_json=excluded.raw_json,
                    updated_at=CURRENT_TIMESTAMP
            """, records)

        return len(records)

    def get_total_count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM uploads")
        return cursor.fetchone()[0]

    def find_exact(self, norm_artist: str, norm_title: str, norm_album: str = "") -> dict[str, Any] | None:
        query = "SELECT * FROM uploads WHERE norm_artist = ? AND norm_title = ?"
        params = [norm_artist, norm_title]
        if norm_album:
            query += " AND norm_album = ?"
            params.append(norm_album)
        query += " LIMIT 1"

        row = self._conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def find_by_artist_and_title(self, norm_artist: str, norm_title: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM uploads WHERE norm_artist = ? AND norm_title = ?",
            (norm_artist, norm_title)
        ).fetchall()
        return [dict(r) for r in rows]

    def find_by_title(self, norm_title: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM uploads WHERE norm_title = ?",
            (norm_title,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_songs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT video_id, title, artist, album, norm_title, norm_artist, norm_album, duration_seconds FROM uploads"
        ).fetchall()
        return [dict(r) for r in rows]
