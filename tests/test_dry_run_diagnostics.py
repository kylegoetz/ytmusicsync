import pytest
from pathlib import Path
from src.m3u_parser import TrackEntry, parse_m3u
from src.cache_manager import UploadsCache
from src.matcher import TrackMatcher
from src.playlist_builder import PlaylistBuilder

def test_m3u_parser_detects_existing_and_missing_files(tmp_path):
    # Create one actual audio file
    real_file = tmp_path / "Artist" / "Album" / "01 RealSong.mp3"
    real_file.parent.mkdir(parents=True)
    real_file.write_bytes(b"dummy mp3 data")
    
    m3u_content = f"""#EXTM3U
#EXTINF:200,Artist - Real Song
{real_file.as_posix()}
#EXTINF:180,Artist - Phantom Song
/Nonexistent/Path/02 PhantomSong.mp3
"""
    m3u_file = tmp_path / "test.m3u"
    m3u_file.write_text(m3u_content, encoding="utf-8")
    
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 2
    assert tracks[0].file_exists is True
    assert tracks[0].resolved_path == str(real_file)
    assert tracks[1].file_exists is False
    assert tracks[1].resolved_path is None

def test_m3u_parser_with_music_root(tmp_path):
    # Music backed up to a different folder (e.g. Mega folder)
    mega_root = tmp_path / "MegaSync" / "Music"
    song_file = mega_root / "Daft Punk" / "Discovery" / "01 One More Time.mp3"
    song_file.parent.mkdir(parents=True)
    song_file.write_bytes(b"dummy mp3 data")
    
    # Old iTunes path in M3U
    m3u_content = """#EXTM3U
#EXTINF:215,Daft Punk - One More Time
C:\\Users\\OldUser\\Music\\iTunes\\iTunes Media\\Music\\Daft Punk\\Discovery\\01 One More Time.mp3
"""
    m3u_file = tmp_path / "itunes.m3u"
    m3u_file.write_text(m3u_content, encoding="utf-8")
    
    # Passing music_root resolves relative to Artist/Album structure
    tracks = parse_m3u(m3u_file, music_root=mega_root)
    assert len(tracks) == 1
    assert tracks[0].file_exists is True
    assert tracks[0].resolved_path == str(song_file)

def test_failure_log_generation(tmp_path):
    cache = UploadsCache(tmp_path / "uploads.sqlite")
    # Only upload Real Song to cache
    cache.upsert_songs([{
        "videoId": "vid_real",
        "title": "Real Song",
        "artists": [{"name": "Artist"}],
        "album": "Album"
    }])
    
    tracks = [
        TrackEntry(raw_path="/Music/RealSong.mp3", title="Real Song", artist="Artist", album="Album", file_exists=True),
        TrackEntry(raw_path="/Music/MissingFromYTM.mp3", title="Unuploaded Song", artist="Artist", album="Album", file_exists=True),
        TrackEntry(raw_path="/Missing/Ghost.mp3", title="Ghost Song", artist="Ghost", album="Ghost", file_exists=False)
    ]
    
    matcher = TrackMatcher(cache)
    results = [matcher.match_track(t) for t in tracks]
    
    builder = PlaylistBuilder()
    log_path = tmp_path / "sync_failures_test.txt"
    builder.export_failure_log(results, log_path, playlist_name="Test Playlist")
    
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "DIAGNOSTIC & FAILURE AUDIT REPORT" in content
    assert "MISSING FROM YOUTUBE MUSIC UPLOADS" in content
    assert "Unuploaded Song" in content
    assert "MISSING LOCAL AUDIO FILES" in content
    assert "Ghost Song" in content

