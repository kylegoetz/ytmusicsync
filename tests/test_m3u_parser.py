import pytest
from pathlib import Path
from src.m3u_parser import TrackEntry, parse_m3u, find_m3u_files, parse_path_metadata

def test_parse_standard_extinf(tmp_path):
    content = """#EXTM3U
#EXTINF:215,Daft Punk - One More Time
/Music/iTunes/iTunes Media/Music/Daft Punk/Discovery/01 One More Time.mp3
#EXTINF:180,Radiohead - Creep
Music/Radiohead/Pablo Honey/02 Creep.m4a
"""
    m3u_file = tmp_path / "test.m3u"
    m3u_file.write_text(content, encoding="utf-8")
    
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 2
    
    assert tracks[0].artist == "Daft Punk"
    assert tracks[0].title == "One More Time"
    assert tracks[0].album == "Discovery"
    assert tracks[0].duration_seconds == 215
    assert tracks[0].raw_path.endswith("01 One More Time.mp3")
    
    assert tracks[1].artist == "Radiohead"
    assert tracks[1].title == "Creep"
    assert tracks[1].album == "Pablo Honey"
    assert tracks[1].duration_seconds == 180

def test_parse_windows_paths_and_uri(tmp_path):
    content = """#EXTM3U
#EXTINF:240,Pink Floyd - Time
file://localhost/C:/Users/Music/iTunes/iTunes%20Media/Music/Pink%20Floyd/The%20Dark%20Side%20of%20the%20Moon/04%20Time.mp3
#EXTINF:200,The Beatles - Help!
C:\\Users\\Music\\iTunes\\iTunes Media\\Music\\The Beatles\\Help!\\01 Help!.mp3
"""
    m3u_file = tmp_path / "windows.m3u"
    m3u_file.write_text(content, encoding="utf-8")
    
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 2
    assert tracks[0].artist == "Pink Floyd"
    assert tracks[0].title == "Time"
    assert tracks[0].album == "The Dark Side of the Moon"
    
    assert tracks[1].artist == "The Beatles"
    assert tracks[1].title == "Help!"
    assert tracks[1].album == "Help!"

def test_parse_raw_paths_without_extinf(tmp_path):
    content = """/Users/test/Music/iTunes/iTunes Media/Music/Fleetwood Mac/Rumours/02 Dreams.mp3
/Users/test/Music/iTunes/iTunes Media/Music/Queen/A Night at the Opera/04 Bohemian Rhapsody.m4a
"""
    m3u_file = tmp_path / "no_extinf.m3u"
    m3u_file.write_text(content, encoding="utf-8")
    
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 2
    assert tracks[0].artist == "Fleetwood Mac"
    assert tracks[0].album == "Rumours"
    assert tracks[0].title == "Dreams"
    
    assert tracks[1].artist == "Queen"
    assert tracks[1].album == "A Night at the Opera"
    assert tracks[1].title == "Bohemian Rhapsody"

def test_parse_latin1_encoding(tmp_path):
    # Latin-1 characters like accented e (é) in Björk or Café
    content = """#EXTM3U
#EXTINF:200,Bj\xf6rk - Hyperballad
/Music/Bj\xf6rk/Post/02 Hyperballad.mp3
"""
    m3u_file = tmp_path / "latin1.m3u"
    m3u_file.write_bytes(content.encode("latin-1"))
    
    tracks = parse_m3u(m3u_file)
    assert len(tracks) == 1
    assert tracks[0].artist == "Björk"
    assert tracks[0].title == "Hyperballad"

def test_find_m3u_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "p1.m3u").write_text("#EXTM3U\n")
    (tmp_path / "p2.m3u8").write_text("#EXTM3U\n")
    (tmp_path / "sub" / "p3.M3U").write_text("#EXTM3U\n")
    (tmp_path / "ignore.txt").write_text("not a playlist")
    
    found = find_m3u_files(tmp_path)
    assert len(found) == 3
    names = {f.name for f in found}
    assert names == {"p1.m3u", "p2.m3u8", "p3.M3U"}
