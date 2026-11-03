from unittest.mock import MagicMock

from src.cache_manager import UploadsCache, normalize_text
from src.ytm_client import YTMClient


def test_normalize_text():
    assert normalize_text("Café del Mar") == "cafe del mar"
    assert normalize_text("Hey Jude - Remastered 2009") == "hey jude"
    assert normalize_text("Clint Eastwood (feat. Del the Funky Homosapien)") == "clint eastwood"
    assert normalize_text("01 - Song Title") == "song title"
    assert normalize_text("Under Pressure [Live at Wembley]") == "under pressure"

def test_cache_crud(tmp_path):
    db_path = tmp_path / "test_uploads.sqlite"
    cache = UploadsCache(db_path)
    
    assert cache.get_total_count() == 0
    
    sample_songs = [
        {
            "videoId": "vid123",
            "entityId": "ent1",
            "title": "One More Time",
            "artists": [{"name": "Daft Punk", "id": "art1"}],
            "album": {"name": "Discovery", "id": "alb1"},
            "duration_seconds": 320
        },
        {
            "videoId": "vid456",
            "entityId": "ent2",
            "title": "Bohemian Rhapsody (2011 Mix)",
            "artists": [{"name": "Queen", "id": "art2"}],
            "album": "A Night at the Opera",
            "duration_seconds": 354
        }
    ]
    
    inserted = cache.upsert_songs(sample_songs)
    assert inserted == 2
    assert cache.get_total_count() == 2
    
    # Test find exact
    res1 = cache.find_exact(norm_artist="daft punk", norm_title="one more time", norm_album="discovery")
    assert res1 is not None
    assert res1["video_id"] == "vid123"
    
    # Test find with cleaned title
    res2 = cache.find_by_artist_and_title(norm_artist="queen", norm_title="bohemian rhapsody")
    assert len(res2) == 1
    assert res2[0]["video_id"] == "vid456"

def test_cache_duplicate_upsert(tmp_path):
    db_path = tmp_path / "test_upsert.sqlite"
    cache = UploadsCache(db_path)
    
    song = [{
        "videoId": "vid1",
        "title": "Song",
        "artists": [{"name": "Artist"}],
        "album": "Album"
    }]
    
    cache.upsert_songs(song)
    assert cache.get_total_count() == 1
    
    # Update title
    song[0]["title"] = "Song (Updated)"
    cache.upsert_songs(song)
    assert cache.get_total_count() == 1
    
    all_songs = cache.get_all_songs()
    assert all_songs[0]["title"] == "Song (Updated)"

def test_ytm_client_mock_sync(tmp_path):
    db_path = tmp_path / "test_sync.sqlite"
    cache = UploadsCache(db_path)
    auth_file = tmp_path / "browser.json"
    auth_file.write_text('{"headers": {}}')
    
    client = YTMClient(auth_path=auth_file)
    mock_yt = MagicMock()
    mock_yt.get_library_upload_songs.return_value = [
        {"videoId": "v1", "title": "Track 1", "artists": [{"name": "Artist 1"}]},
        {"videoId": "v2", "title": "Track 2", "artists": [{"name": "Artist 2"}]}
    ]
    mock_yt.create_playlist.return_value = "playlist123"
    
    client._ytmusic = mock_yt
    
    synced = client.sync_uploaded_songs_to_cache(cache)
    assert synced == 2
    assert cache.get_total_count() == 2
    
    pl_id = client.create_playlist("Test Playlist")
    assert pl_id == "playlist123"
    
    client.add_playlist_items("playlist123", ["v1", "v2"], pause_seconds=0)
    mock_yt.add_playlist_items.assert_called_once_with(
        playlistId="playlist123",
        videoIds=["v1", "v2"],
        duplicates=False
    )
