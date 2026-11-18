"""Repeated-acquisition checks on a known, fixed sensor (not a pixel bootstrap)."""

from __future__ import annotations

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraExposureSeries,
    DispersionStatus,
    characterize_dark_current,
)

TIMES = (1, 2, 4, 8)


def test_uniform_review_witness_keeps_observed_spread() -> None:
    rng = np.random.default_rng(20261118)
    series = [
        CameraExposureSeries(rng.normal(100 + 2 * t, 4, (4, 64, 64)), t) for t in TIMES
    ]
    result = characterize_dark_current(series)
    intrinsic = result.intrinsic_dispersion
    assert result.dark_current_nonuniformity_dn_per_s == pytest.approx(0.36837745)
    assert intrinsic.status is DispersionStatus.UNRESOLVED
    assert np.isnan(intrinsic.sd_dn_per_s)
    assert intrinsic.covariance_ci95[0] < 0 < intrinsic.covariance_ci95[1]
    assert 0 < intrinsic.sd_ci95[1] < result.dark_current_nonuniformity_dn_per_s


@pytest.mark.parametrize("scene", ["uniform", "uniform-clustered", "glow-clustered"])
def test_signed_bias_and_interval_coverage(scene: str) -> None:
    """Include *all* signed estimates/intervals, not just positive detections."""
    seeds = 192
    y, x = np.indices((64, 64)) / 63
    rate = np.full(x.shape, 2.0)
    if scene == "glow-clustered":
        rate += 0.8 * x + 3 * np.exp(-5 * ((1 - x) ** 2 + (1 - y) ** 2))
    errors, truth, covered, issued, resolved = [], [], [], [], []
    sd_errors = []
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        series = []
        for t in TIMES:
            noise = rng.normal(size=(4, *x.shape))
            if scene != "uniform":
                # Each independent read adds spatially correlated 4 x 4 noise.
                patches = rng.normal(size=(4, 16, 16)).repeat(4, 1).repeat(4, 2)
                noise = (0.6 * noise + 0.8 * patches) * (0.6 + x) * np.sqrt((t + 3) / 6)
            series.append(CameraExposureSeries(100 + rate * t + 4 * noise, t))
        intrinsic = characterize_dark_current(series).intrinsic_dispersion
        assert intrinsic.pixel_mask is not None
        variance = np.var(rate[intrinsic.pixel_mask], ddof=1)
        low, high = intrinsic.covariance_ci95
        issued.append(np.isfinite([low, high]).all())
        if not issued[-1]:
            assert intrinsic.status is DispersionStatus.CONCENTRATED
            assert np.isnan(intrinsic.sd_dn_per_s)
        errors.append(intrinsic.covariance - variance)
        truth.append(variance)
        covered.append(low <= variance <= high)
        resolved.append(intrinsic.status is DispersionStatus.RESOLVED)
        if resolved[-1] and variance > 0:
            sd_errors.append(intrinsic.sd_dn_per_s - np.sqrt(variance))
    bias = np.mean(errors)
    coverage = np.mean(covered)
    print(
        f"{scene}: true variance={np.mean(truth):.6f}, bias={bias:+.6f} (LSB/s)^2, "
        f"coverage={sum(covered)}/{sum(issued)} issued ({seeds} acquisitions), "
        f"resolved={sum(resolved)}/{seeds}"
    )
    assert abs(bias) < 3.5 * np.std(errors, ddof=1) / np.sqrt(seeds)
    # Count abstentions as misses, and separately check the intervals issued.
    assert np.mean(issued) > 0.95
    assert abs(coverage - 0.95) < 3 * np.sqrt(0.95 * 0.05 / seeds)
    assert abs(sum(covered) / sum(issued) - 0.95) < 3 * np.sqrt(
        0.95 * 0.05 / sum(issued)
    )
    if scene == "glow-clustered":
        assert np.mean(resolved) > 0.95
        assert abs(np.mean(sd_errors)) < 0.01 * np.sqrt(np.mean(truth))
    else:
        assert np.mean(resolved) < 0.025 + 3 * np.sqrt(0.025 * 0.975 / seeds)
