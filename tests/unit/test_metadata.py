"""Tests for Camera metadata namespacing."""

import pytest

from datalab_camera_characterization.core import metadata_key


def test_metadata_key_is_namespaced_by_plugin_id() -> None:
    """Camera metadata cannot collide with another plugin namespace."""
    assert metadata_key("exposure_time") == (
        "plugin.org.datalab.camera-characterization.exposure_time"
    )


@pytest.mark.parametrize("local_key", ["", "Role", ".role", "two words"])
def test_metadata_key_rejects_unstable_local_keys(local_key: str) -> None:
    """Metadata key suffixes remain stable and machine-readable."""
    with pytest.raises(ValueError):
        metadata_key(local_key)
