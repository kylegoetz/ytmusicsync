from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import time

from ytmusicapi import YTMusic
from src.cache_manager import UploadsCache


class YTMClient:
    """
    Wrapper for ytmusicapi that handles authenticated operations on YouTube Music
    focusing strictly on user uploads and playlist creation.
    """

    DEFAULT_AUTH_FILES = ["browser.json", "oauth.json", "headers.json"]

    def __init__(self, auth_path: Optional[str | Path] = None):
        self.auth_path = self._resolve_auth_file(auth_path)
        self._ytmusic: Optional[YTMusic] = None

    def _resolve_auth_file(self, auth_path: Optional[str | Path]) -> Optional[Path]:
        if auth_path:
            p = Path(auth_path)
            if p.exists():
                return p
            raise FileNotFoundError(f"Authentication file not found at: {auth_path}")

        for candidate in self.DEFAULT_AUTH_FILES:
            p = Path(candidate)
            if p.exists():
                return p
        return None

    @property
    def ytmusic(self) -> YTMusic:
        if self._ytmusic is None:
            if not self.auth_path or not self.auth_path.exists():
                raise RuntimeError(
                    "No authentication credentials found. Run 'ytmusicsync auth' first "
                    "or provide browser.json / oauth.json."
                )
            self._ytmusic = YTMusic(str(self.auth_path))
        return self._ytmusic

    def test_connection(self) -> Dict[str, Any]:
        """Validates that credentials work by making a light library call."""
        try:
            # Fetch a single uploaded track to verify access to uploads
            sample = self.ytmusic.get_library_upload_songs(limit=1)
            return {"status": "ok", "sample_count": len(sample)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def sync_uploaded_songs_to_cache(
        self,
        cache: UploadsCache,
        limit: Optional[int] = None,
        batch_callback: Optional[Callable[[int], None]] = None
    ) -> int:
        """
        Fetches uploaded songs from YouTube Music and persists them to the local SQLite cache.
        Supports fetching large libraries (30,000+ tracks) and calls batch_callback on progress.
        """
        # Note: ytmusicapi's get_library_upload_songs handles internal pagination continuations.
        # Passing limit=None fetches all tracks.
        print("Connecting to YouTube Music and fetching uploaded tracks catalog...")
        songs = self.ytmusic.get_library_upload_songs(limit=limit)
        
        total_synced = 0
        batch_size = 500
        for i in range(0, len(songs), batch_size):
            chunk = songs[i:i + batch_size]
            inserted = cache.upsert_songs(chunk)
            total_synced += inserted
            if batch_callback:
                batch_callback(total_synced)

        return total_synced

    def create_playlist(self, title: str, description: str = "") -> str:
        """Creates a playlist on YouTube Music and returns the playlistId."""
        desc = description or "Created by ytmusicsync from iTunes playlist"
        playlist_id = self.ytmusic.create_playlist(title=title, description=desc)
        if isinstance(playlist_id, dict):
            # In some versions it may return a dict response or string ID
            return playlist_id.get("id", str(playlist_id))
        return str(playlist_id)

    def add_playlist_items(
        self,
        playlist_id: str,
        video_ids: List[str],
        duplicates: bool = False,
        batch_size: int = 50,
        pause_seconds: float = 0.5
    ) -> int:
        """
        Adds video IDs to a playlist in safe batches to avoid API timeouts.
        Returns total items added.
        """
        total_added = 0
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i:i + batch_size]
            self.ytmusic.add_playlist_items(
                playlistId=playlist_id,
                videoIds=batch,
                duplicates=duplicates
            )
            total_added += len(batch)
            if pause_seconds > 0 and (i + batch_size) < len(video_ids):
                time.sleep(pause_seconds)
        return total_added
