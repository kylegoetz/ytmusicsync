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
            "local_file_found",
            "resolved_path",
            "matched_status",
            "match_type",
            "confidence",
            "ytm_video_id",
            "ytm_title",
            "ytm_artist",
            "ytm_album",
            "diagnostic_notes"
        ]

        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for res in match_results:
                matched = bool(res.matched_video_id)
                file_found = getattr(res.track, "file_exists", False)
                resolved = getattr(res.track, "resolved_path", "") or ""
                
                notes = []
                if not matched:
                    notes.append("Unmatched in YTM uploads")
                if not file_found:
                    notes.append("Audio file missing on disk")
                if res.match_type == "fuzzy":
                    notes.append(f"Fuzzy match ({res.confidence*100:.0f}%)")

                writer.writerow({
                    "original_title": res.track.title,
                    "original_artist": res.track.artist,
                    "original_album": res.track.album,
                    "original_path": res.track.raw_path,
                    "local_file_found": "YES" if file_found else "NO",
                    "resolved_path": resolved,
                    "matched_status": "MATCHED" if matched else "UNMATCHED",
                    "match_type": res.match_type,
                    "confidence": f"{res.confidence:.2f}",
                    "ytm_video_id": res.matched_video_id or "",
                    "ytm_title": res.matched_title or "",
                    "ytm_artist": res.matched_artist or "",
                    "ytm_album": res.matched_album or "",
                    "diagnostic_notes": "; ".join(notes) if notes else "OK"
                })

    def export_failure_log(
        self,
        match_results: list[MatchResult],
        output_log_path: Path | str,
        playlist_name: str
    ) -> Path:
        """
        Exports a human-readable text log detailing all failures:
        - Tracks missing from YouTube Music uploads
        - Missing local audio files
        - Fuzzy matches that may need review
        """
        p = Path(output_log_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        unmatched = [m for m in match_results if not m.matched_video_id]
        missing_files = [m for m in match_results if not getattr(m.track, "file_exists", False)]
        fuzzy = [m for m in match_results if m.match_type == "fuzzy"]
        total = len(match_results)
        matched_count = total - len(unmatched)

        pct_str = f"{matched_count/total*100:.1f}%" if total > 0 else "0.0%"

        lines = [
            "==================================================================",
            f"   DIAGNOSTIC & FAILURE AUDIT REPORT: {playlist_name}",
            "==================================================================",
            f"Total Playlist Entries:             {total}",
            f"Successfully Matched to YTM:        {matched_count} ({pct_str})",
            f"Missing from YouTube Uploads:       {len(unmatched)}",
            f"Missing Local Audio Files:          {len(missing_files)}",
            f"Fuzzy Matched (Review Recommended): {len(fuzzy)}",
            "==================================================================",
            "",
        ]

        if unmatched:
            lines.extend([
                f"--- [!] MISSING FROM YOUTUBE MUSIC UPLOADS ({len(unmatched)} tracks) ---",
                "These songs exist in your M3U playlist, but were NOT found in your uploaded library.",
                "Action needed: Upload these files to music.youtube.com or check their ID3 artist/title tags.",
                "",
            ])
            for idx, m in enumerate(unmatched, 1):
                t = m.track
                file_status = "Found on local drive" if getattr(t, "file_exists", False) else "NOT found on local drive"
                lines.append(f"  {idx}. \"{t.title}\" by \"{t.artist or 'Unknown Artist'}\" (Album: \"{t.album or 'Unknown'}\")")
                lines.append(f"     Path in M3U: {t.raw_path}")
                lines.append(f"     Local File:  {file_status}")
                lines.append("")

        if missing_files:
            lines.extend([
                f"--- [?] MISSING LOCAL AUDIO FILES ({len(missing_files)} files) ---",
                "These audio files could not be found at their path on your local drive.",
                "Note: If these were already uploaded to YouTube Music, ytmusicsync can still reconstruct them!",
                "",
            ])
            for idx, m in enumerate(missing_files, 1):
                t = m.track
                status = f"Matched to YTM upload '{m.matched_title}' [{m.matched_video_id}]" if m.matched_video_id else "NOT matched in YTM uploads"
                lines.append(f"  {idx}. \"{t.title}\" by \"{t.artist or 'Unknown Artist'}\"")
                lines.append(f"     Expected Path: {t.raw_path}")
                lines.append(f"     Sync Status:   {status}")
                lines.append("")

        if fuzzy:
            lines.extend([
                f"--- [*] FUZZY MATCHES ({len(fuzzy)} tracks) ---",
                "These tracks matched with minor differences in spelling, edition, or punctuation.",
                "",
            ])
            for idx, m in enumerate(fuzzy, 1):
                t = m.track
                lines.append(f"  {idx}. Original: \"{t.title}\" by \"{t.artist}\"")
                lines.append(f"     Matched:  \"{m.matched_title}\" by \"{m.matched_artist}\" (Confidence: {m.confidence*100:.0f}%)")
                lines.append(f"     Video ID: {m.matched_video_id}")
                lines.append("")

        if not unmatched and not missing_files and not fuzzy:
            lines.append("All tracks matched cleanly with 100% confidence and local files verified!")

        p.write_text("\n".join(lines), encoding="utf-8")
        return p

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

