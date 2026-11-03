import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic

from src.cache_manager import UploadsCache


class YTMClient:
    """
    Wrapper for ytmusicapi that handles authenticated operations on YouTube Music
    focusing strictly on user uploads and playlist creation.
    """

    DEFAULT_AUTH_FILES = ["browser.json", "oauth.json", "headers.json"]

    def __init__(self, auth_path: str | Path | None = None):
        self.auth_path = self._resolve_auth_file(auth_path)
        self._ytmusic: YTMusic | None = None

    def _resolve_auth_file(self, auth_path: str | Path | None) -> Path | None:
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

    def test_connection(self) -> dict[str, Any]:
        """Validates that credentials work by making a light library call."""
        try:
            sample = self.ytmusic.get_library_upload_songs(limit=1)
            return {"status": "ok", "sample_count": len(sample)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def sync_uploaded_songs_to_cache(
        self,
        cache: UploadsCache,
        limit: int | None = None,
        batch_callback: Callable[[int], None] | None = None
    ) -> int:
        """
        Fetches uploaded songs from YouTube Music and persists them incrementally
        to the local SQLite cache so that interruptions preserve already-fetched songs.
        """
        print("Connecting to YouTube Music and fetching uploaded tracks catalog...")
        
        # Check if we can stream continuations directly via ytmusic internals
        try:
            from ytmusicapi.constants import MUSIC_SHELF
            from ytmusicapi.continuations import (
                get_continuation_contents,
                get_continuation_params,
            )
            from ytmusicapi.parsers.browsing import pop_songs_random_mix
            from ytmusicapi.parsers.library import (
                get_library_contents,
                parse_uploaded_items,
            )

            endpoint = "browse"
            body = {"browseId": "FEmusic_library_privately_owned_tracks"}
            response = self.ytmusic._send_request(endpoint, body)
            results = get_library_contents(response, MUSIC_SHELF)
            
            total_synced = 0
            if results is not None:
                pop_songs_random_mix(results)
                songs = parse_uploaded_items(results["contents"])
                if songs:
                    inserted = cache.upsert_songs(songs)
                    total_synced += inserted
                    if batch_callback:
                        batch_callback(total_synced)

                while "continuations" in results and (limit is None or total_synced < limit):
                    additional_params = get_continuation_params(results)
                    cont_response = self.ytmusic._send_request(endpoint, body, additional_params)
                    if "continuationContents" in cont_response:
                        results = cont_response["continuationContents"]["musicShelfContinuation"]
                    else:
                        break
                    contents = get_continuation_contents(results, parse_uploaded_items)
                    if not contents:
                        break
                    
                    inserted = cache.upsert_songs(contents)
                    total_synced += inserted
                    if batch_callback:
                        batch_callback(total_synced)

            return total_synced

        except Exception as e:
            # Fallback to standard library call if internal parser signatures differ
            print(f"Streaming mode encountered: {e}. Falling back to standard batch fetch...")
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
        """
        Creates a playlist on YouTube Music and returns the playlistId.
        Sanitizes < and > characters which YouTube Music API rejects.
        """
        sanitized_title = title.replace("<", "(").replace(">", ")").strip()
        desc = description or "Created by ytmusicsync from iTunes playlist"
        playlist_id = self.ytmusic.create_playlist(title=sanitized_title, description=desc)
        if isinstance(playlist_id, dict):
            return playlist_id.get("id", str(playlist_id))
        return str(playlist_id)

    def add_playlist_items(
        self,
        playlist_id: str,
        video_ids: list[str],
        duplicates: bool = False,
        batch_size: int = 50,
        pause_seconds: float = 0.5,
        max_retries: int = 3
    ) -> int:
        """
        Adds video IDs to a playlist in safe batches with exponential backoff and retry.
        Returns total items successfully submitted.
        """
        total_added = 0
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i:i + batch_size]
            attempt = 0
            success = False
            last_err = None

            while attempt < max_retries and not success:
                try:
                    response = self.ytmusic.add_playlist_items(
                        playlistId=playlist_id,
                        videoIds=batch,
                        duplicates=duplicates
                    )
                    # Verify response if dict returned
                    if isinstance(response, dict) and response.get("status") in ("STATUS_FAILED", "ERROR"):
                        raise RuntimeError(f"YouTube Music returned error status: {response}")
                    success = True
                    total_added += len(batch)
                except Exception as e:
                    attempt += 1
                    last_err = e
                    if attempt >= max_retries:
                        raise RuntimeError(
                            f"Failed adding batch to playlist {playlist_id} after {max_retries} attempts: {last_err}"
                        )
                    backoff = (2 ** attempt) * 0.5
                    time.sleep(backoff)

            if pause_seconds > 0 and (i + batch_size) < len(video_ids):
                time.sleep(pause_seconds)

        return total_added
