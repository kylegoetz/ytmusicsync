def test_dependencies_importable():
    import ytmusicapi
    import rapidfuzz
    import mutagen
    import tqdm
    import src
    assert src.__name__ == "src"

