"""DataLab-Web adapter status tests."""

from datalab_camera_characterization.adapters.web import WEB_STATUS


def test_web_adapter_remains_explicitly_unsupported() -> None:
    """A Python package install must not imply Web compatibility."""
    assert WEB_STATUS == "unsupported"
