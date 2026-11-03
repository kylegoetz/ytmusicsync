import csv
from unittest.mock import MagicMock

from src.m3u_parser import TrackEntry
from src.matcher import MatchResult
from src.playlist_builder import PlaylistBuilder, chunk_items


def test_chunk_items():
    items = list(range(12500))
    chunks = chunk_items(items, max_size=5000)
    assert len(chunks) == 3
    assert len(chunks[0]) == 5000
    assert len(chunks[1]) == 5000
    assert len(chunks[2]) == 2500

def test_export_report(tmp_path):
    report_file = tmp_path / "test_report.csv"
    results = [
        MatchResult(
            track=TrackEntry(raw_path="/Music/Track1.mp3", title="Song 1", artist="Artist 1", album="Album 1"),
            matched_video_id="vid1",
            matched_title="Song 1",
            matched_artist="Artist 1",
            matched_album="Album 1",
            confidence=1.0,
            match_type="exact_full"
        ),
        MatchResult(
            track=TrackEntry(raw_path="/Music/Track2.mp3", title="Song 2", artist="Artist 2", album="Album 2"),
            matched_video_id=None,
            matched_title=None,
            matched_artist=None,
            matched_album=None,
            confidence=0.0,
            match_type="none"
        )
    ]
    
    builder = PlaylistBuilder(ytm_client=None)
    builder.export_report(results, report_file)
    
    assert report_file.exists()
    with open(report_file, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["original_title"] == "Song 1"
        assert reader[0]["matched_status"] == "MATCHED"
        assert reader[0]["ytm_video_id"] == "vid1"
        assert reader[1]["original_title"] == "Song 2"
        assert reader[1]["matched_status"] == "UNMATCHED"
        assert reader[1]["ytm_video_id"] == ""

def test_build_playlist_dry_run():
    builder = PlaylistBuilder(ytm_client=None)
    results = [
        MatchResult(
            track=TrackEntry(raw_path="", title=f"Song {i}", artist="Artist"),
            matched_video_id=f"vid_{i}" if i % 2 == 0 else None,
            matched_title=f"Song {i}" if i % 2 == 0 else None,
            matched_artist="Artist" if i % 2 == 0 else None,
            matched_album="Album" if i % 2 == 0 else None,
            confidence=1.0 if i % 2 == 0 else 0.0,
            match_type="exact_full" if i % 2 == 0 else "none"
        )
        for i in range(10)
    ]
    
    summary = builder.sync_playlist(
        playlist_name="Test Dry Run",
        match_results=results,
        dry_run=True,
        max_size=5
    )
    
    assert summary["total_tracks"] == 10
    assert summary["matched_tracks"] == 5
    assert summary["unmatched_tracks"] == 5
    assert summary["match_rate"] == 50.0
    assert summary["dry_run"] is True
    assert len(summary["chunks"]) == 1  # 5 matched items fits in max_size=5

def test_build_playlist_live_with_chunking():
    mock_client = MagicMock()
    mock_client.create_playlist.side_effect = ["pl_part1", "pl_part2"]
    mock_client.add_playlist_items.return_value = 5
    
    builder = PlaylistBuilder(ytm_client=mock_client)
    # 7 matched tracks with max_size=4 -> 2 playlists created
    results = [
        MatchResult(
            track=TrackEntry(raw_path="", title=f"Song {i}", artist="Artist"),
            matched_video_id=f"vid_{i}",
            matched_title=f"Song {i}",
            matched_artist="Artist",
            matched_album="Album",
            confidence=1.0,
            match_type="exact_full"
        )
        for i in range(7)
    ]
    
    summary = builder.sync_playlist(
        playlist_name="My Big Playlist",
        match_results=results,
        dry_run=False,
        max_size=4
    )
    
    assert summary["dry_run"] is False
    assert len(summary["chunks"]) == 2
    assert summary["chunks"][0]["title"] == "My Big Playlist (Part 1 of 2)"
    assert summary["chunks"][1]["title"] == "My Big Playlist (Part 2 of 2)"
    assert mock_client.create_playlist.call_count == 2
    assert mock_client.add_playlist_items.call_count == 2

