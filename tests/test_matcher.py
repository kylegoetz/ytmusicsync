import pytest

from src.cache_manager import UploadsCache
from src.m3u_parser import TrackEntry
from src.matcher import TrackMatcher


@pytest.fixture
def populated_cache(tmp_path):
    db_path = tmp_path / "matcher_test.sqlite"
    cache = UploadsCache(db_path)
    sample_tracks = [
        {
            "videoId": "vid_full",
            "title": "Heroes",
            "artists": [{"name": "David Bowie"}],
            "album": "Heroes",
            "duration_seconds": 367
        },
        {
            "videoId": "vid_remaster",
            "title": "Heroes (2017 Remaster)",
            "artists": [{"name": "David Bowie"}],
            "album": "Legacy",
            "duration_seconds": 367
        },
        {
            "videoId": "vid_daft",
            "title": "Around the World",
            "artists": [{"name": "Daft Punk"}],
            "album": "Homework",
            "duration_seconds": 429
        },
        {
            "videoId": "vid_feat",
            "title": "Empire State of Mind",
            "artists": [{"name": "Jay-Z"}],
            "album": "The Blueprint 3",
            "duration_seconds": 276
        },
        {
            "videoId": "vid_gorillaz",
            "title": "Feel Good Inc.",
            "artists": [{"name": "Gorillaz"}],
            "album": "Demon Days",
            "duration_seconds": 223
        }
    ]
    cache.upsert_songs(sample_tracks)
    return cache

def test_match_exact_full(populated_cache):
    matcher = TrackMatcher(populated_cache)
    track = TrackEntry(raw_path="", title="Heroes", artist="David Bowie", album="Heroes")
    result = matcher.match_track(track)
    
    assert result.matched_video_id == "vid_full"
    assert result.match_type == "exact_full"
    assert result.confidence == 1.0

def test_match_exact_artist_title_with_noise(populated_cache):
    matcher = TrackMatcher(populated_cache)
    track = TrackEntry(raw_path="", title="01 - Around The World", artist="Daft Punk", album="Unknown Album")
    result = matcher.match_track(track)
    
    assert result.matched_video_id == "vid_daft"
    assert result.match_type in ("exact_full", "exact_artist_title")
    assert result.confidence >= 0.95

def test_match_featured_artists_in_title(populated_cache):
    matcher = TrackMatcher(populated_cache)
    track = TrackEntry(
        raw_path="",
        title="Empire State Of Mind (feat. Alicia Keys)",
        artist="Jay-Z",
        album="The Blueprint 3"
    )
    result = matcher.match_track(track)
    
    assert result.matched_video_id == "vid_feat"
    assert result.confidence >= 0.95

def test_match_fuzzy(populated_cache):
    matcher = TrackMatcher(populated_cache, fuzzy_threshold=85.0)
    # Slight typo: "Feel Good Inc" without period and minor variation
    track = TrackEntry(raw_path="", title="Feel Good Inc", artist="Gorillaz", album="")
    result = matcher.match_track(track)
    
    assert result.matched_video_id == "vid_gorillaz"
    assert result.confidence >= 0.85

def test_unmatched_track(populated_cache):
    matcher = TrackMatcher(populated_cache)
    track = TrackEntry(raw_path="", title="Nonexistent Song", artist="Nonexistent Artist")
    result = matcher.match_track(track)
    
    assert result.matched_video_id is None
    assert result.match_type == "none"
    assert result.confidence == 0.0

