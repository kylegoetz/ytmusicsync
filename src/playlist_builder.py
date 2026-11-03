import csv
from pathlib import Path
from typing import Any, TypeVar

from src.matcher import MatchResult
from src.ytm_client import YTMClient

T = TypeVar("T")


def chunk_items(items: list[T], max_size: int = 5000) -> list[list[T]]:
    """Splits a list into chunks of at most max_size items."""
    if not items:
        return []
    if max_size <= 0:
        return [items]
    return [items[i:i + max_size] for i in range(0, len(items), max_size)]


class PlaylistBuilder:
    """
    Coordinates playlist creation on YouTube Music, handling:
    - Exclusion of unmatched tracks
    - YouTube Music's 5,000 song playlist limit (auto-chunking into Part 1, Part 2...)
    - Dry-run preview mode
    - CSV audit report generation
    """

    def __init__(self, ytm_client: YTMClient | None = None):
        self.ytm_client = ytm_client

    def export_report(self, match_results: list[MatchResult], output_csv_path: Path | str) -> None:
        """
        Exports a CSV audit report showing every song from the M3U, whether it was matched,
        and the YouTube Music upload it was matched to.
        """
        p = Path(output_csv_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "original_title",
            "original_artist",
            "original_album",
            "original_path",
            "matched_status",
            "match_type",
            "confidence",
            "ytm_video_id",
            "ytm_title",
            "ytm_artist",
            "ytm_album",
        ]

        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for res in match_results:
                matched = bool(res.matched_video_id)
                writer.writerow({
                    "original_title": res.track.title,
                    "original_artist": res.track.artist,
                    "original_album": res.track.album,
                    "original_path": res.track.raw_path,
                    "matched_status": "MATCHED" if matched else "UNMATCHED",
                    "match_type": res.match_type,
                    "confidence": f"{res.confidence:.2f}",
                    "ytm_video_id": res.matched_video_id or "",
                    "ytm_title": res.matched_title or "",
                    "ytm_artist": res.matched_artist or "",
                    "ytm_album": res.matched_album or "",
                })

    def sync_playlist(
        self,
        playlist_name: str,
        match_results: list[MatchResult],
        dry_run: bool = False,
        max_size: int = 5000,
        allow_duplicates: bool = False
    ) -> dict[str, Any]:
        """
        Reconstructs the playlist on YouTube Music using only matched uploaded tracks.
        Automatically splits into sequenced parts if matched tracks exceed max_size (default 5,000).
        """
        matched_results = [m for m in match_results if m.matched_video_id]
        total_tracks = len(match_results)
        matched_count = len(matched_results)
        unmatched_count = total_tracks - matched_count
        match_rate = round((matched_count / total_tracks * 100), 1) if total_tracks > 0 else 0.0

        matched_video_ids = [m.matched_video_id for m in matched_results]
        chunks = chunk_items(matched_video_ids, max_size=max_size)

        chunk_info = []
        total_chunks = len(chunks)

        for idx, chunk_ids in enumerate(chunks):
            if total_chunks > 1:
                chunk_title = f"{playlist_name} (Part {idx + 1} of {total_chunks})"
            else:
                chunk_title = playlist_name

            playlist_id = None
            if not dry_run:
                if self.ytm_client is None:
                    raise RuntimeError("YTMClient must be provided for non-dry-run execution.")
                playlist_id = self.ytm_client.create_playlist(
                    title=chunk_title,
                    description=f"Imported by ytmusicsync ({matched_count}/{total_tracks} tracks matched)"
                )
                self.ytm_client.add_playlist_items(
                    playlist_id=playlist_id,
                    video_ids=chunk_ids,
                    duplicates=allow_duplicates
                )

            chunk_info.append({
                "title": chunk_title,
                "track_count": len(chunk_ids),
                "playlist_id": playlist_id,
            })

        return {
            "playlist_name": playlist_name,
            "total_tracks": total_tracks,
            "matched_tracks": matched_count,
            "unmatched_tracks": unmatched_count,
            "match_rate": match_rate,
            "dry_run": dry_run,
            "chunks": chunk_info,
        }

