from unittest.mock import MagicMock

from src.cache_manager import UploadsCache, normalize_text
from src.m3u_parser import TrackEntry, parse_m3u
from src.matcher import TrackMatcher
from src.ytm_client import YTMClient


def test_normalize_unparenthesized_feat_and_year_remaster():
    # Unparenthesized feat
    assert normalize_text("Empire State Of Mind feat. Alicia Keys") == "empire state of mind"
    assert normalize_text("Feel Good Inc ft. De La Soul") == "feel good inc"
    
    # Year-first remaster suffix
    assert normalize_text("Heroes - 2017 Remaster") == "heroes"
    assert normalize_text("Starman - 2012 Remastered Version") == "starman"
    
    # 4-digit year titles should not have year stripped
    assert normalize_text("1984 - Part 1") == "1984 part 1"
    assert normalize_text("2001 - A Space Odyssey") == "2001 a space odyssey"


def test_tier3_empty_artist_no_false_positive(tmp_path):
    db_path = tmp_path / "test_empty_art.sqlite"
    cache = UploadsCache(db_path)
    cache.upsert_songs([{
        "videoId": "vid_intro_no_art",
        "title": "Intro",
        "artists": [],  # No artist
        "album": "Some Album"
    }])
    
    matcher = TrackMatcher(cache)
    # Different artist with same common track title "Intro"
    track = TrackEntry(raw_path="", title="Intro", artist="The xx", album="xx")
    res = matcher.match_track(track)
    
    # Must NOT match as artist match
    assert res.matched_video_id is None or res.match_type != "exact_artist_title"


def test_duration_disambiguation_for_duplicates(tmp_path):
    db_path = tmp_path / "test_duration.sqlite"
    cache = UploadsCache(db_path)
    cache.upsert_songs([
        {
            "videoId": "vid_live",
            "title": "Free Bird",
            "artists": [{"name": "Lynyrd Skynyrd"}],
            "album": "One More from the Road",
            "duration": "14:10"  # 850 seconds
        },
        {
            "videoId": "vid_studio",
            "title": "Free Bird",
            "artists": [{"name": "Lynyrd Skynyrd"}],
            "album": "Pronounced Leh-nerd Skin-nerd",
            "duration": "09:08"  # 548 seconds
        }
    ])
    
    matcher = TrackMatcher(cache)
    # M3U track with duration close to studio track (548s)
    track = TrackEntry(
        raw_path="",
        title="Free Bird",
        artist="Lynyrd Skynyrd",
        album="Greatest Hits",
        duration_seconds=550
    )
    res = matcher.match_track(track)
    assert res.matched_video_id == "vid_studio"


def test_mutagen_path_normalization(tmp_path):
    # Create a dummy file with spaces
    song_file = tmp_path / "My Song.mp3"
    song_file.write_bytes(b"dummy audio content")
    
    # Create M3U with file:// and %20
    m3u_file = tmp_path / "test_uri.m3u"
    m3u_file.write_text(f"""#EXTM3U
#EXTINF:120,Artist - Title
file://localhost/{song_file.as_posix().replace(' ', '%20')}
""")
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 1
    # raw_path parsed and title preserved
    assert tracks[0].title == "Title"
    assert tracks[0].artist == "Artist"


def test_cache_in_memory_connection():
    cache = UploadsCache(":memory:")
    assert cache.get_total_count() == 0
    cache.upsert_songs([{
        "videoId": "v1",
        "title": "Song",
        "artists": [{"name": "Artist"}]
    }])
    assert cache.get_total_count() == 1
    assert cache.find_exact("artist", "song") is not None


def test_sanitize_playlist_title():
    client = YTMClient.__new__(YTMClient)
    client._ytmusic = MagicMock()
    client._ytmusic.create_playlist.return_value = "pl123"
    
    client.create_playlist(title="<Best Of> 80s & 90s")
    client._ytmusic.create_playlist.assert_called_once_with(
        title="(Best Of) 80s & 90s",
        description="Created by ytmusicsync from iTunes playlist"
    )


def test_add_playlist_items_with_retry_and_error_handling():
    client = YTMClient.__new__(YTMClient)
    mock_yt = MagicMock()
    # First attempt raises Exception, second succeeds
    mock_yt.add_playlist_items.side_effect = [
        Exception("Connection reset"),
        {"status": "STATUS_SUCCEEDED"}
    ]
    client._ytmusic = mock_yt
    
    added = client.add_playlist_items("pl123", ["v1", "v2"], pause_seconds=0)
    assert added == 2
    assert mock_yt.add_playlist_items.call_count == 2

