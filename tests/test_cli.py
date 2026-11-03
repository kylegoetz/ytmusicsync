
from src.cache_manager import UploadsCache
from src.cli import build_parser, main, run_sync_single


def test_cli_parser_help():
    parser = build_parser()
    subparsers = [action for action in parser._actions if action.dest == "command"]
    assert len(subparsers) == 1
    choices = subparsers[0].choices
    assert "auth" in choices
    assert "cache" in choices
    assert "sync" in choices
    assert "batch-sync" in choices

def test_run_sync_single_dry_run(tmp_path):
    m3u_file = tmp_path / "Rock Classics.m3u"
    m3u_file.write_text("""#EXTM3U
#EXTINF:200,Queen - Bohemian Rhapsody
/Music/Queen/Bohemian Rhapsody.mp3
#EXTINF:150,Unknown - Missing Track
/Music/Missing.mp3
""")
    db_file = tmp_path / "uploads.sqlite"
    
    cache = UploadsCache(db_file)
    cache.upsert_songs([{
        "videoId": "vid_queen",
        "title": "Bohemian Rhapsody",
        "artists": [{"name": "Queen"}],
        "album": "A Night at the Opera"
    }])
    
    report_file = tmp_path / "reports" / "report.csv"
    
    summary = run_sync_single(
        m3u_path=m3u_file,
        cache_db=db_file,
        dry_run=True,
        report_path=report_file
    )
    
    assert summary["playlist_name"] == "Rock Classics"
    assert summary["total_tracks"] == 2
    assert summary["matched_tracks"] == 1
    assert summary["unmatched_tracks"] == 1
    assert summary["match_rate"] == 50.0
    assert report_file.exists()

def test_batch_sync_cli(tmp_path, monkeypatch):
    playlists_dir = tmp_path / "playlists"
    playlists_dir.mkdir()
    
    (playlists_dir / "Jazz.m3u").write_text("""#EXTM3U
#EXTINF:300,Miles Davis - So What
/Music/Miles Davis/Kind of Blue/01 So What.mp3
""")
    (playlists_dir / "Rock.m3u8").write_text("""#EXTM3U
#EXTINF:250,The Who - Baba O'Riley
/Music/The Who/Who's Next/01 Baba O'Riley.mp3
""")
    
    db_file = tmp_path / "uploads.sqlite"
    cache = UploadsCache(db_file)
    cache.upsert_songs([
        {
            "videoId": "vid_miles",
            "title": "So What",
            "artists": [{"name": "Miles Davis"}],
            "album": "Kind of Blue"
        },
        {
            "videoId": "vid_who",
            "title": "Baba O'Riley",
            "artists": [{"name": "The Who"}],
            "album": "Who's Next"
        }
    ])
    
    reports_dir = tmp_path / "batch_reports"
    
    exit_code = main([
        "batch-sync",
        str(playlists_dir),
        "--dry-run",
        "--cache-db", str(db_file),
        "--reports-dir", str(reports_dir)
    ])
    
    assert exit_code == 0
    assert (reports_dir / "sync_report_Jazz.csv").exists()
    assert (reports_dir / "sync_report_Rock.csv").exists()
