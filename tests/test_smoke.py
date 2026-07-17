def test_import_tetrapy():
    import tetrapy
    import tetrapy.convolve  # noqa: F401
    assert tetrapy is not None
