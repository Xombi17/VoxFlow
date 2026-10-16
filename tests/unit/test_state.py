from voxflow import APP_NAME, __version__


def test_bootstrap_package_metadata_is_available() -> None:
    assert APP_NAME == "voxflow"
    assert __version__ == "0.1.0"
