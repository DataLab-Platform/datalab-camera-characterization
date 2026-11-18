"""Analytical camera review witnesses (plugin 0.2.1, revision c9e43f6).

On that baseline the linear PTC recovered 2 e-/LSB, but a variance dip was
called saturation and clipping produced infinite SNR. The dark ramp missed
the isolated hot pixel, misclassified both rail cases, fitted 4.2087 LSB/s
through censored zeros and reported R² = 1 for a constant signal.
"""

from __future__ import annotations

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraExposureSeries,
    CameraValidationParameters,
    DarkCurrentCharacterization,
    DarkCurrentParameters,
    PhotonTransferCharacterization,
    PhotonTransferParameters,
    characterize_dark_current,
    characterize_photon_transfer,
)

ADC = CameraValidationParameters(saturation_dn=4095)
PIXEL = (8, 8)


def _dark_ramp(
    codes: tuple[int, ...], background_slope: int = 2
) -> DarkCurrentCharacterization:
    series = []
    for t, code in zip((1, 2, 4, 8), codes, strict=True):
        frames = np.full((4, 16, 16), 100 + background_slope * t, dtype=np.uint16)
        frames[:, PIXEL[0], PIXEL[1]] = code
        series.append(CameraExposureSeries(frames, t))
    return characterize_dark_current(series, DarkCurrentParameters(validation=ADC))


def test_isolated_dark_slope_is_hot_without_noise() -> None:
    result = _dark_ramp((120, 140, 180, 260))
    assert result.dark_current_map_dn_per_s[PIXEL] == pytest.approx(20)
    assert result.hot_pixel_mask[PIXEL]
    assert result.hot_pixel_count == 1
    assert not result.regular_pixel_mask[PIXEL]
    assert result.dark_current_dn_per_s == pytest.approx(2)


@pytest.mark.parametrize(
    "codes",
    [(4094, 4095, 4095, 4095), (0, 0, 4095, 4095)],
    ids=["high-offset", "switching-rails"],
)
def test_unmeasurable_pixel_is_not_hot_or_stuck(codes: tuple[int, ...]) -> None:
    result = _dark_ramp(codes)
    assert not result.hot_pixel_mask[PIXEL]
    assert not result.stuck_pixel_mask[PIXEL]
    assert result.indeterminate_pixel_mask[PIXEL]
    assert np.isnan(result.dark_current_map_dn_per_s[PIXEL])
    assert np.isnan(result.offset_map_dn[PIXEL])
    assert not result.regular_pixel_mask[PIXEL]


def test_low_rail_levels_are_not_slope_measurements() -> None:
    result = _dark_ramp((0, 0, 8, 28))
    # Only (4 s, 8 LSB) and (8 s, 28 LSB) survive.
    assert result.usable_level_count[PIXEL] == 2
    assert result.dark_current_map_dn_per_s[PIXEL] == pytest.approx(5)
    assert result.offset_map_dn[PIXEL] == pytest.approx(-12)
    assert not result.summary_pixel_mask[PIXEL]
    diagnostics = {item.code: item for item in result.validation.warnings}
    assert diagnostics["two_point_dark_fit"].details["pixel_count"] == 1
    assert diagnostics["low_rail_censoring"].details["non_stuck_pixel_counts"] == [
        1,
        1,
        0,
        0,
    ]


def test_constant_dark_ramp_has_undefined_r_squared() -> None:
    result = _dark_ramp((100,) * 4, background_slope=0)
    assert result.dark_current_dn_per_s == 0
    assert result.offset_dn == 100
    assert np.isnan(result.fit_r_squared)


def _pair(mean: float, variance: float, common: float = 0.0) -> np.ndarray:
    """Balanced checkerboard with known sample variance, plus an optional drift."""
    signs = 2 * (np.indices((16, 16)).sum(axis=0) % 2) - 1
    delta = signs * np.sqrt(variance / 2) + common
    return np.stack((mean - delta, mean + delta))


def _ptc(
    last_signal: int, last_variance: float, last_exposure_s: float
) -> PhotonTransferCharacterization:
    # Bias = 100 LSB, dark variance = 2 LSB², photon variance = signal / 2.
    flats = [
        CameraExposureSeries(_pair(100 + s, 2 + s / 2), s / 1000)
        for s in (16, 32, 64, 128, 256, 512)
    ]
    last_pair = _pair(100 + last_signal, last_variance)
    flats.append(CameraExposureSeries(last_pair, last_exposure_s))
    return characterize_photon_transfer(
        _pair(100, 2), flats, PhotonTransferParameters(validation=ADC)
    )


def test_linear_ptc_recovers_known_gain() -> None:
    result = _ptc(1024, 2 + 512, 1.024)
    assert result.conversion_gain_e_per_dn == pytest.approx(2)
    assert not result.saturation_reached


def test_variance_dip_is_not_saturation() -> None:
    result = _ptc(540, 2 + 255, 0.540)
    assert not result.saturation_reached
    assert result.mean_signal_dn[result.variance_peak_index] == pytest.approx(512)
    assert result.saturation_status == result.dynamic_range_status == "Lower bound"
    assert result.saturation_signal_dn == pytest.approx(540)
    assert result.saturation_capacity_e == pytest.approx(1080)


def test_fully_clipped_pair_has_no_measured_snr() -> None:
    result = _ptc(4095 - 100, 0, 64)
    snr = result.measured_snr[-1]
    assert np.ma.is_masked(snr) or np.isnan(snr)
    assert np.isnan(result.model_snr[-1])
    assert result.saturation_evidence == "adc_clipping"
    assert result.dynamic_range_status == "Observed"


def _level(t: float, signal: float, common: float = 0) -> CameraExposureSeries:
    return CameraExposureSeries(_pair(100 + signal, 2 + signal / 2, common), t)


def test_common_mode_bias_and_centered_gain_are_both_preserved():
    signals = np.array([16, 32, 64, 128, 256, 512, 1024])
    levels = [_level(s / 1000, s, 0.02 * s) for s in signals]
    dark = _pair(100, 2)
    raw = characterize_photon_transfer(dark, levels)
    centered = characterize_photon_transfer(
        dark, levels, PhotonTransferParameters(variance_mode="centered_pairs")
    )
    assert raw.conversion_gain_e_per_dn == pytest.approx(1.086, abs=0.001)
    assert centered.conversion_gain_e_per_dn == pytest.approx(2, rel=0.01)
    for r in (raw, centered):
        assert r.raw_gain_e_per_dn == raw.conversion_gain_e_per_dn
        assert r.centered_gain_e_per_dn == centered.conversion_gain_e_per_dn
        assert "frame_mean_fluctuation" in {d.code for d in r.validation.warnings}
        assert r.saturation_status == r.dynamic_range_status == "Indeterminate"
        assert r.saturation_capacity_e is None and r.dynamic_range_db is None
        term = 2 * (0.02 * signals) ** 2
        np.testing.assert_allclose([p.removed_variance_dn2 for p in r.flat_pairs], term)
        np.testing.assert_allclose(r.raw_temporal_variance_dn2, signals / 2 + term)
        np.testing.assert_allclose(r.centered_temporal_variance_dn2, signals / 2)
        np.testing.assert_allclose(
            r.measured_snr, signals / np.sqrt(2 + signals / 2 + term)
        )


def test_disjoint_pairs_and_odd_frame_apply_equally_to_matched_darks():
    def five(mean, variance, drift):
        # A step BETWEEN pairs plus an unpaired repeat: no overlapping
        # differences and no implicit all-frame variance subtraction.
        return np.concatenate(
            (
                _pair(mean - 2, variance, drift),
                _pair(mean + 2, variance, -2 * drift),
                np.full((1, 16, 16), mean + 5),
            )
        )

    darks, levels = {}, []
    for s in (16, 32, 64, 128, 256, 512):
        t = s / 1000
        darks[t] = five(100 + t, 3 + t, 0.03 * s)
        levels.append(
            CameraExposureSeries(five(100 + t + s, 3 + t + s / 2, 0.02 * s), t)
        )
    r = characterize_photon_transfer(
        darks, levels, PhotonTransferParameters(variance_mode="centered_pairs")
    )
    assert r.dark_reference.plan.mode == "matched" and r.read_noise_e is None
    assert r.conversion_gain_e_per_dn == pytest.approx(2)
    for i, level in enumerate(levels):
        t = level.exposure_time_s
        dp = dict(zip(r.dark_reference.plan.used_exposures, r.dark_pairs))[t]
        assert dp.pair_count == r.flat_pairs[i].pair_count == 2
        assert dp.removed_variance_dn2 == pytest.approx(5 * (0.03 * 1000 * t) ** 2)
        assert dp.centered_variance_dn2 == pytest.approx(3 + t)
        assert dp.pair_variance_dn2 == pytest.approx(
            dp.centered_variance_dn2 + dp.removed_variance_dn2
        )
        assert r.raw_temporal_variance_dn2[i] == pytest.approx(
            np.var(level.frames_dn, axis=0, ddof=1).mean()
            - np.var(darks[t], axis=0, ddof=1).mean()
        )


@pytest.mark.parametrize(
    ("tail_times", "tail_signals", "drift", "confirmed", "observed"),
    [
        ((4, 8, 16), (400, 400, 401), 0, True, True),
        ((4, 8, 16), (400, 400, 401), 0, False, False),
        ((4, 4.001, 4.002), (400, 400, 401), 0, True, False),
        ((4, 8, 16), (400, 400, 500), 0, True, False),
        ((4, 8, 16), (400, 400, 401), 10, True, False),
    ],
)
def test_subrail_plateau_needs_stability_repeats_and_exposure_leverage(
    tail_times, tail_signals, drift, confirmed, observed
):
    levels = [_level(t, t * 100) for t in (0.125, 0.25, 0.5, 1, 2)]
    levels.extend(_level(t, s, drift) for t, s in zip(tail_times, tail_signals))
    r = characterize_photon_transfer(
        {0.0: _pair(100, 2)},
        levels,
        PhotonTransferParameters(stable_illumination=confirmed),
    )
    assert not r.clipped_mask.any()
    assert r.saturation_reached == observed
    if observed:
        assert r.saturation_evidence == "response_plateau"
        assert r.saturation_capacity_e == pytest.approx(800)
        assert r.mean_signal_dn[r.usable_signal_index] == pytest.approx(200)
        assert not r.fit_mask[-3:].any()
        assert np.isnan(r.measured_snr[-3:]).all()
    else:
        assert r.saturation_status == "Lower bound"


@pytest.mark.parametrize("exclude_stuck_pixels", [True, False])
def test_only_significant_clipping_of_responding_pixels_establishes_adc_limit(
    exclude_stuck_pixels,
):
    dark = _pair(100, 2)
    dark[:, 0, :3] = 4095
    flats = [_level(t, 100 * t) for t in (0.125, 0.25, 0.5, 1, 2, 4)]
    for f in flats:
        # Already >1% permanent defects in the dark and >1% flat-only defects.
        f.frames_dn[:, 0, :6] = 4095
    flats[-1].frames_dn[:, 1, 0] = 4095
    params = PhotonTransferParameters(exclude_stuck_pixels=exclude_stuck_pixels)
    r = characterize_photon_transfer(dark, flats, params)
    assert not r.saturation_reached and not r.clipped_mask.any()
    flats[-1].frames_dn[0, 1, :3] = 4095
    r = characterize_photon_transfer(dark, flats, params)
    assert not r.saturation_reached and np.isnan(r.measured_snr[-1])
    flats[-1].frames_dn[1, 1, :3] = 4095
    r = characterize_photon_transfer(dark, flats, params)
    assert r.saturation_evidence == "adc_clipping" and r.rail_population == 250
    assert np.isnan(r.measured_snr[-1]) and not r.fit_mask[-1]


def test_zero_dark_variance_cannot_give_infinite_dynamic_range():
    levels = [_level(t, 100 * t) for t in (0.125, 0.25, 0.5, 1, 2, 4)]
    r = characterize_photon_transfer({0.0: _pair(100, 0)}, levels)
    assert r.saturation_status == "Lower bound"
    assert r.saturation_capacity_e == pytest.approx(800)
    assert r.read_noise_e is None
    assert r.dynamic_range_db is None and r.dynamic_range_status == "Indeterminate"
