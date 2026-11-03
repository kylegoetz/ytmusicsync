import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

try:
    import mutagen
except ImportError:
    mutagen = None


@dataclass
class TrackEntry:
    raw_path: str
    title: str
    artist: str = ""
    album: str = ""
    duration_seconds: int = 0


def clean_track_title(raw_title: str) -> str:
    """Removes track number prefixes like '01 ', '01 - ', '01. ' from title."""
    cleaned = re.sub(r"^\d+[\s\.\-_]+\s*", "", raw_title.strip())
    return cleaned if cleaned else raw_title.strip()


def parse_path_metadata(path_str: str) -> tuple[str, str, str]:
    """
    Infers (artist, album, title) from a file path using standard iTunes folder structure:
    ... / Artist / Album / TrackTitle.ext
    """
    # Clean URL encoding (e.g. file://localhost/C:/... or %20)
    cleaned = path_str
    if cleaned.startswith("file://localhost/"):
        cleaned = cleaned[len("file://localhost/"):]
    elif cleaned.startswith("file://"):
        cleaned = cleaned[len("file://"):]
    
    cleaned = urllib.parse.unquote(cleaned)
    # Normalize backslashes to forward slashes
    cleaned = cleaned.replace("\\", "/")
    
    # Remove drive letter if on Windows (e.g. C:/)
    if re.match(r"^[a-zA-Z]:/", cleaned):
        cleaned = cleaned[3:]

    p = Path(cleaned)
    filename_without_ext = p.stem
    title = clean_track_title(filename_without_ext)

    album = ""
    artist = ""

    parent = p.parent
    if parent and parent.name and parent.name != ".":
        album = parent.name
        grandparent = parent.parent
        if grandparent and grandparent.name and grandparent.name != ".":
            # Guard against common top-level directory names like 'Music', 'iTunes Media'
            if grandparent.name.lower() not in ("music", "itunes", "itunes media", "unknown", "compilations"):
                artist = grandparent.name

    return artist, album, title


def read_tags_with_mutagen(file_path: Path) -> tuple[str, str, str, int] | None:
    """If file exists on local filesystem, attempts to read tags via mutagen."""
    if not mutagen or not file_path.is_file():
        return None
    try:
        audio = mutagen.File(str(file_path), easy=True)
        if audio:
            artist = audio.get("artist", [""])[0] if "artist" in audio else ""
            album = audio.get("album", [""])[0] if "album" in audio else ""
            title = audio.get("title", [""])[0] if "title" in audio else ""
            duration = int(audio.info.length) if audio.info and hasattr(audio.info, "length") else 0
            return artist, album, title, duration
    except Exception:
        pass
    return None


def read_file_text(file_path: Path) -> str:
    """Reads text with fallback encodings."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    raw_bytes = file_path.read_bytes()
    for enc in encodings:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("latin-1", errors="replace")


def parse_m3u(file_path: Path) -> list[TrackEntry]:
    """
    Parses an M3U or M3U8 file and extracts TrackEntry records.
    """
    text = read_file_text(file_path)
    lines = [line.strip() for line in text.splitlines()]

    tracks: list[TrackEntry] = []
    current_extinf_duration = 0
    current_extinf_artist = ""
    current_extinf_title = ""

    for line in lines:
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            # Format: #EXTINF:<duration>,[Artist - ]Title
            info = line[8:].strip()
            comma_idx = info.find(",")
            if comma_idx != -1:
                dur_str = info[:comma_idx].strip()
                try:
                    current_extinf_duration = max(0, int(float(dur_str)))
                except ValueError:
                    current_extinf_duration = 0
                title_part = info[comma_idx + 1:].strip()
                if " - " in title_part:
                    artist_cand, title_cand = title_part.split(" - ", 1)
                    current_extinf_artist = artist_cand.strip()
                    current_extinf_title = title_cand.strip()
                else:
                    current_extinf_artist = ""
                    current_extinf_title = title_part
            continue

        if line.startswith("#"):
            # Other directives (#EXTM3U, #EXT-X-..., etc.)
            continue

        # This line is a track path
        raw_path = line
        inferred_artist, inferred_album, inferred_title = parse_path_metadata(raw_path)

        # Clean and unquote path for local filesystem check
        cleaned_path = raw_path
        if cleaned_path.startswith("file://localhost/"):
            cleaned_path = cleaned_path[len("file://localhost/"):]
        elif cleaned_path.startswith("file://"):
            cleaned_path = cleaned_path[len("file://"):]
        cleaned_path = urllib.parse.unquote(cleaned_path).replace("\\", "/")
        if re.match(r"^[a-zA-Z]:/", cleaned_path):
            cleaned_path = cleaned_path[3:]

        local_path = Path(cleaned_path)
        if not local_path.is_file():
            # Try resolving relative to the m3u location
            candidate = file_path.parent / cleaned_path
            if candidate.is_file():
                local_path = candidate

        tags = read_tags_with_mutagen(local_path)
        if tags and any(tags[:3]):
            artist = tags[0] or current_extinf_artist or inferred_artist
            album = tags[1] or inferred_album
            title = tags[2] or current_extinf_title or inferred_title
            duration = tags[3] or current_extinf_duration
        else:
            artist = current_extinf_artist or inferred_artist
            album = inferred_album
            title = current_extinf_title or inferred_title
            duration = current_extinf_duration

        tracks.append(TrackEntry(
            raw_path=raw_path,
            title=title,
            artist=artist,
            album=album,
            duration_seconds=duration,
        ))

        # Reset extinf state for the next entry
        current_extinf_duration = 0
        current_extinf_artist = ""
        current_extinf_title = ""

    return tracks


def find_m3u_files(folder_path: Path) -> list[Path]:
    """Recursively locates all .m3u and .m3u8 playlist files in a directory."""
    results: list[Path] = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            lower = f.lower()
            if lower.endswith((".m3u", ".m3u8")):
                results.append(Path(root) / f)
    return sorted(results)

