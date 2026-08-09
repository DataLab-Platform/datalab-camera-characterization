"""Namespaced metadata conventions shared by Camera workflows."""

from __future__ import annotations

import re

from .. import PLUGIN_ID

METADATA_PREFIX = f"plugin.{PLUGIN_ID}"
_LOCAL_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def metadata_key(local_key: str) -> str:
    """Return a stable, plugin-namespaced metadata key.

    Args:
        local_key: Lowercase key local to the Camera plugin

    Returns:
        Fully namespaced metadata key

    Raises:
        ValueError: If the local key is not stable and machine-readable
    """
    if not isinstance(local_key, str) or not _LOCAL_KEY_PATTERN.fullmatch(local_key):
        raise ValueError(
            "Camera metadata keys must contain lowercase letters, digits, '.', "
            "'_' or '-'"
        )
    return f"{METADATA_PREFIX}.{local_key}"
