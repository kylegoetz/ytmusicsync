from dataclasses import dataclass
from typing import Dict, List, Optional
import rapidfuzz.fuzz
import rapidfuzz.process

from src.m3u_parser import TrackEntry
from src.cache_manager import UploadsCache, normalize_text


@dataclass
class MatchResult:
    track: TrackEntry
    matched_video_id: Optional[str]
    matched_title: Optional[str]
    matched_artist: Optional[str]
    matched_album: Optional[str]
    confidence: float
    match_type: str  # 'exact_full', 'exact_artist_title', 'exact_title_only', 'fuzzy', 'none'


class TrackMatcher:
    """
    Matches TrackEntry items from M3U playlists against the user's uploaded songs in SQLite cache.
    Guarantees matching ONLY against user uploads.
    """

    def __init__(self, cache: UploadsCache, fuzzy_threshold: float = 88.0):
        self.cache = cache
        self.fuzzy_threshold = fuzzy_threshold
        self._all_songs_cache: Optional[List[Dict]] = None

    def _get_all_cached_songs(self) -> List[Dict]:
        if self._all_songs_cache is None:
            self._all_songs_cache = self.cache.get_all_songs()
        return self._all_songs_cache

    def match_track(self, track: TrackEntry) -> MatchResult:
        norm_title = normalize_text(track.title)
        norm_artist = normalize_text(track.artist)
        norm_album = normalize_text(track.album)

        if not norm_title:
            return MatchResult(
                track=track,
                matched_video_id=None,
                matched_title=None,
                matched_artist=None,
                matched_album=None,
                confidence=0.0,
                match_type="none"
            )

        # 1. Tier 1: Exact Match (Artist + Title + Album)
        if norm_artist and norm_album:
            exact = self.cache.find_exact(norm_artist=norm_artist, norm_title=norm_title, norm_album=norm_album)
            if exact:
                return MatchResult(
                    track=track,
                    matched_video_id=exact["video_id"],
                    matched_title=exact["title"],
                    matched_artist=exact["artist"],
                    matched_album=exact["album"],
                    confidence=1.0,
                    match_type="exact_full"
                )

        # 2. Tier 2: Exact Match (Artist + Title)
        if norm_artist:
            by_artist_title = self.cache.find_by_artist_and_title(norm_artist=norm_artist, norm_title=norm_title)
            if by_artist_title:
                # If multiple (e.g. remastered and original), prioritize matching album or duration
                best = by_artist_title[0]
                if norm_album:
                    for cand in by_artist_title:
                        if cand.get("norm_album") == norm_album:
                            best = cand
                            break
                return MatchResult(
                    track=track,
                    matched_video_id=best["video_id"],
                    matched_title=best["title"],
                    matched_artist=best["artist"],
                    matched_album=best["album"],
                    confidence=0.98 if not norm_album else 0.95,
                    match_type="exact_artist_title"
                )

        # 3. Tier 3: Match by Title (if artist was missing or unmatched)
        title_matches = self.cache.find_by_title(norm_title)
        if title_matches:
            if norm_artist:
                # Check if artist is a partial match or substring
                for cand in title_matches:
                    cand_art = cand.get("norm_artist", "")
                    if norm_artist in cand_art or cand_art in norm_artist:
                        return MatchResult(
                            track=track,
                            matched_video_id=cand["video_id"],
                            matched_title=cand["title"],
                            matched_artist=cand["artist"],
                            matched_album=cand["album"],
                            confidence=0.92,
                            match_type="exact_artist_title"
                        )
            elif len(title_matches) == 1:
                cand = title_matches[0]
                return MatchResult(
                    track=track,
                    matched_video_id=cand["video_id"],
                    matched_title=cand["title"],
                    matched_artist=cand["artist"],
                    matched_album=cand["album"],
                    confidence=0.90,
                    match_type="exact_title_only"
                )

        # 4. Tier 4: Fuzzy Matching across uploaded catalog
        all_songs = self._get_all_cached_songs()
        if not all_songs:
            return MatchResult(
                track=track,
                matched_video_id=None,
                matched_title=None,
                matched_artist=None,
                matched_album=None,
                confidence=0.0,
                match_type="none"
            )

        query_str = f"{norm_artist} {norm_title}".strip()
        best_score = 0.0
        best_cand = None

        for cand in all_songs:
            cand_str = f"{cand.get('norm_artist', '')} {cand.get('norm_title', '')}".strip()
            score = rapidfuzz.fuzz.token_sort_ratio(query_str, cand_str)
            if score > best_score:
                best_score = score
                best_cand = cand
                if best_score == 100.0:
                    break

        if best_cand and best_score >= self.fuzzy_threshold:
            return MatchResult(
                track=track,
                matched_video_id=best_cand["video_id"],
                matched_title=best_cand["title"],
                matched_artist=best_cand["artist"],
                matched_album=best_cand["album"],
                confidence=round(best_score / 100.0, 2),
                match_type="fuzzy"
            )

        return MatchResult(
            track=track,
            matched_video_id=None,
            matched_title=None,
            matched_artist=None,
            matched_album=None,
            confidence=0.0,
            match_type="none"
        )
