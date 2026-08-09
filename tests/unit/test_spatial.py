"""Tests for non-normative relative spatial Camera characterization."""

from __future__ import annotations

import numpy as np
import pytest

from datalab_camera_characterization.core import characterize_spatial_dn


def test_spatial_characterization_has_explicit_relative_definitions() -> None:
    """Maps, profiles, histograms, and candidates follow the DN contract."""
    mean_dark = np.array(((8.0, 10.0), (10.0, 12.0)))
    mean_flat = np.array(((28.0, 30.0), (50.0, 52.0)))

    result = characterize_spatial_dn(
        mean_dark,
        mean_flat,
        candidate_threshold_sigma=1.0,
        histogram_bin_count=4,
    )

    expected_dark_map = np.array(((-2.0, 0.0), (0.0, 2.0)))
    expected_flat_map = np.array(((-1.0 / 3.0, -1.0 / 3.0), (1.0 / 3.0, 1.0 / 3.0)))
    np.testing.assert_allclose(result.dsnu_like_map_dn, expected_dark_map)
    np.testing.assert_allclose(result.prnu_like_map_fraction, expected_flat_map)
    assert result.dark_nonuniformity_dn == pytest.approx(np.std(mean_dark, ddof=1))
    assert result.flat_field_nonuniformity_fraction == pytest.approx(
        np.std(expected_flat_map, ddof=1)
    )
    np.testing.assert_allclose(result.row_profile_fraction, (-1.0 / 3.0, 1.0 / 3.0))
    np.testing.assert_allclose(
        result.column_profile_fraction,
        (0.0, 0.0),
        atol=1e-15,
    )
    np.testing.assert_array_equal(
        result.candidate_pixel_mask,
        ((True, False), (False, True)),
    )
    assert result.candidate_pixel_count == 2
    assert result.candidate_pixel_fraction == 0.5
    assert int(np.sum(result.dsnu_histogram_counts)) == mean_dark.size
    assert int(np.sum(result.prnu_histogram_counts)) == mean_flat.size
    assert result.dsnu_histogram_bin_edges_dn.size == 5
    assert result.prnu_histogram_bin_edges_fraction.size == 5

    for array in (
        result.dsnu_like_map_dn,
        result.prnu_like_map_fraction,
        result.candidate_pixel_mask,
        result.row_profile_fraction,
        result.column_profile_fraction,
        result.dsnu_histogram_counts,
        result.dsnu_histogram_bin_edges_dn,
        result.prnu_histogram_counts,
        result.prnu_histogram_bin_edges_fraction,
    ):
        assert not array.flags.writeable


def test_spatial_characterization_rejects_nonpositive_flat_signal() -> None:
    """A relative flat-field map requires positive dark-corrected signal."""
    mean_dark = np.full((2, 3), 10.0)

    with pytest.raises(ValueError, match="positive"):
        characterize_spatial_dn(mean_dark, mean_dark.copy())
