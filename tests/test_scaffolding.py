def test_dependencies_importable():
    import src
    assert src.__name__ == "src"

