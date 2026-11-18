"""Dark-ramp core method and recipe."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization.core import (
    CameraCharacterizationError,
    CameraExposureSeries,
    CameraSimulationParameters,
    DarkCurrentParameters,
    DispersionStatus,
    characterize_dark_current,
    metadata_key,
    simulate_camera_frames,
    validate_dark_ramp_inputs,
)
from datalab_camera_characterization.workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    DarkCurrentRecipeParameters,
)

EXPOSURES_S = (1.0, 2.0, 4.0, 8.0)


def _dark_image(frame: np.ndarray, exposure: float | None = None) -> ImageObj:
    image = create_image("dark", frame.copy(), units=("", "", "LSB"))
    for key, value in {
        "frame_role": "dark",
        "bit_depth": 12,
        "bit_shift": 0,
        "saturation_dn": 4095,
    }.items():
        image.metadata[metadata_key(key)] = value
    if exposure is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure
    return image


def _series(glow: float = 0.0) -> tuple[CameraExposureSeries, ...]:
    """Simulate one dark ramp of a sensor with hot pixels."""
    series = []
    for stream, exposure_time_s in enumerate(EXPOSURES_S, start=1):
        result = simulate_camera_frames(
            CameraSimulationParameters(
                shape=(64, 64),
                frame_count=4,
                exposure_time_s=exposure_time_s,
                signal_electrons=0.0,
                dark_current_e_per_s=20.0,
                dark_current_nonuniformity_fraction=0.05,
                dark_hot_pixel_fraction=0.003,
                dark_hot_pixel_factor=25.0,
                amplifier_glow_e_per_s=glow,
                defective_pixel_fraction=0.001,
                seed=11,
                noise_stream=stream,
            )
        )
        series.append(CameraExposureSeries(result.frames_dn, exposure_time_s))
    return tuple(series), result.truth


@pytest.mark.parametrize("glow", [0.0, 200.0])
def test_dark_ramp_recovers_dark_current_and_hot_pixels(glow: float) -> None:
    """Hot pixels are isolated outliers; smooth glow is not reported as hot."""
    series, truth = _series(glow)

    result = characterize_dark_current(
        series,
        DarkCurrentParameters(conversion_gain_e_per_dn=2.0),
    )
    regular = result.regular_pixel_mask
    true_rate = truth.dark_current_map_e_per_s[regular].mean()

    assert result.to_electrons(result.dark_current_dn_per_s) == pytest.approx(
        true_rate, rel=0.02
    )
    hot = truth.dark_hot_pixel_mask
    assert np.all(result.hot_pixel_mask[hot])
    # A steep glow gradient may cause at most one statistical false alarm.
    assert np.count_nonzero(result.hot_pixel_mask & ~hot) <= 1
    assert result.stuck_pixel_count == 4
    assert result.conversion_gain_from_dark_e_per_dn == pytest.approx(2.0, rel=0.1)
    assert result.fit_r_squared > 0.999


def test_dark_ramp_reports_insufficient_levels_and_exposure_order() -> None:
    """Too few or unordered dark levels produce structured errors."""
    series, _truth = _series()

    short = validate_dark_ramp_inputs(series[:2])
    unordered = validate_dark_ramp_inputs((series[1], series[0], series[2]))

    assert "insufficient_dark_levels" in {item.code for item in short.errors}
    assert "exposure_order" in {item.code for item in unordered.errors}
    with pytest.raises(CameraCharacterizationError, match="insufficient_dark_levels"):
        characterize_dark_current(series[:2])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"background_window": 4},
        {"conversion_gain_e_per_dn": 0.0},
        {"hot_pixel_threshold_sigma": 0.0},
        {"dispersion_block_side": 0},
    ],
)
def test_dark_current_parameters_are_validated(kwargs: dict) -> None:
    """Invalid settings are rejected before any calculation."""
    with pytest.raises(ValueError):
        DarkCurrentParameters(**kwargs)


@pytest.mark.parametrize(("gain", "rate_unit"), [(2.0, "e-/s"), (0.0, "LSB/s")])
def test_dark_current_recipe_builds_maps_and_anchored_table(
    gain: float, rate_unit: str
) -> None:
    """The recipe returns ramps, maps, histogram and an anchored table."""
    series, truth = _series()
    images = []
    for item in series:
        for frame in item.frames_dn:
            images.append(_dark_image(frame, item.exposure_time_s))
    parameters = DarkCurrentRecipeParameters()
    parameters.conversion_gain_e_per_dn = gain

    outcome = DARK_CURRENT_RECIPE.run(
        {"dark_frames": tuple(images)},
        parameters,
        RecipeExecutionContext(),
    )

    outputs = {output.id: output.value for output in outcome.objects}
    assert list(outputs) == [
        "dark_ramp",
        "dark_variance_ramp",
        "dark_current_map",
        "offset_map",
        "hot_pixel_map",
        "summary_pixel_mask",
        "dark_current_distribution",
    ]
    assert outputs["dark_current_map"].zunit == rate_unit
    assert outputs["dark_ramp"].yunit == "LSB"
    assert outputs["dark_variance_ramp"].yunit == "LSB^2"
    assert outputs["offset_map"].zunit == "LSB"
    assert np.count_nonzero(outputs["hot_pixel_map"].data == 1) == np.count_nonzero(
        truth.dark_hot_pixel_mask
    )
    (metrics,) = outcome.results
    assert metrics.anchor_id == "dark_ramp"
    rows = {row[0]: row for row in metrics.value.data}
    assert rows["Mean dark current"][2] == rate_unit
    intrinsic = characterize_dark_current(series).intrinsic_dispersion
    factor = gain or 1.0
    assert rows["Split-slope covariance"][1:3] == [
        pytest.approx(factor**2 * intrinsic.covariance),
        f"({rate_unit})^2",
    ]
    assert rows["Intrinsic dark-current dispersion"][1:3] == [
        pytest.approx(factor * intrinsic.sd_dn_per_s),
        rate_unit,
    ]
    assert rows["Intrinsic dispersion 95% upper"][1] == pytest.approx(
        factor * intrinsic.sd_ci95[1]
    )
    assert metrics.value.attrs["dispersion_split_reserved_a_b"] == [[2, 1, 1]] * 4


def test_dark_current_recipe_requires_exposure_metadata() -> None:
    """Dark frames without exposure time cannot be placed on the ramp."""
    image = _dark_image(np.zeros((4, 4), dtype=np.uint16))

    with pytest.raises(RecipeValidationError, match="Dark image"):
        DARK_CURRENT_RECIPE.run(
            {"dark_frames": (image,)},
            DarkCurrentRecipeParameters(),
            RecipeExecutionContext(),
        )


def test_dark_current_output_populations() -> None:
    """Keep classes, measurable fits and all-level summary membership distinct."""
    images = []
    for i, t in enumerate(EXPOSURES_S):
        frames = np.full((4, 9, 9), 100 + 2 * t, dtype=np.uint16)
        frames[:, 1, 1] = 100 + 20 * t
        frames[:, 1, 3] = 0
        frames[:, 1, 5] = 4095
        frames[:, 3, 1] = (4094, 4095, 4095, 4095)[i]
        frames[:, 3, 3] = (0, 0, 4095, 4095)[i]
        frames[:, 3, 5] = (0, 0, 8, 16)[i]  # class 0, slope 2, outside summary
        if i == 0:
            frames[:, 5, 1] = [0, 136, 136, 136]  # isolated zero; mean still 102
            frames[:, 5, 3] = [0, 0, 204, 204]  # repeated pile-up; same mean
        if i == 3:
            frames[:, 5, 5] += 1  # sub-resolution excess on a noiseless background
            frames[0, 7, 3] = 4095  # one high clip invalidates the historical mean
        images.extend(_dark_image(frame, t) for frame in frames)
    parameters = DarkCurrentRecipeParameters()
    parameters.aggregation_block_size = 3  # also split the last block
    parameters.conversion_gain_e_per_dn = 2.0
    outcome = DARK_CURRENT_RECIPE.run(
        {"dark_frames": tuple(images)}, parameters, RecipeExecutionContext()
    )
    outputs = {output.id: output.value for output in outcome.objects}
    classes = np.zeros((9, 9), dtype=np.uint8)
    classes[1, 1] = 1
    classes[1, (3, 5)] = 2
    classes[3, (1, 3)] = 3
    np.testing.assert_array_equal(outputs["hot_pixel_map"].data, classes)
    summary = classes == 0
    summary[[3, 5, 7], [5, 3, 3]] = False
    np.testing.assert_array_equal(outputs["summary_pixel_mask"].data, summary)
    rates = outputs["dark_current_map"].data
    np.testing.assert_array_equal(np.isfinite(rates), classes < 2)
    assert rates[3, 5] == pytest.approx(4)  # 2 LSB/s converted to e-/s
    assert outputs["offset_map"].data[5, 1] == pytest.approx(100)  # still LSB
    histogram = outputs["dark_current_distribution"]
    assert histogram.y.sum() == 77
    for role, count in (
        ("dark_ramp", 73),
        ("dark_current_map", 77),
        ("hot_pixel_map", 81),
        ("dark_current_distribution", 77),
    ):
        assert outputs[role].metadata[metadata_key("population_pixel_count")] == count
        assert outputs[role].metadata[metadata_key("total_pixel_count")] == 81
    (metrics,) = outcome.results
    rows = {row[0]: row[1] for row in metrics.value.data}
    assert rows["Mean dark current"] == pytest.approx(np.mean(rates[summary]))
    assert rows["Dark-current non-uniformity"] == pytest.approx(
        np.std(rates[summary], ddof=1)
    )
    assert rows["Hot-pixel fraction"] == pytest.approx(1e6 / 81)
    assert [
        rows[k]
        for k in (
            "Total pixels",
            "Measurable slopes",
            "Summary pixels",
            "Hot pixels",
            "Stuck pixels",
            "Indeterminate pixels",
        )
    ] == [81, 77, 73, 1, 2, 2]
    assert "two_point_dark_fit" in {item.code for item in outcome.diagnostics}


def test_two_level_dark_ramp_does_not_establish_linearity() -> None:
    series = [CameraExposureSeries(np.full((2, 2, 2), 100 + 2 * t), t) for t in (1, 2)]
    result = characterize_dark_current(
        series, DarkCurrentParameters(minimum_exposure_levels=2)
    )
    assert result.dark_current_dn_per_s == pytest.approx(2)
    assert np.isnan(result.fit_r_squared)
    assert any(item.code == "two_point_dark_fit" for item in result.validation.warnings)
    assert result.intrinsic_dispersion.status is DispersionStatus.TOO_FEW_REPEATS
    assert result.intrinsic_dispersion.pixel_mask is None


@pytest.mark.parametrize(
    ("codes", "slope"), [((0, 0, 8, 28), 5), ((0, 0, 4095, 4095), None)]
)
def test_empty_summary_preserves_pixel_evidence(codes, slope) -> None:
    series = [
        CameraExposureSeries(np.full((2, 2, 2), code), t)
        for code, t in zip(codes, EXPOSURES_S, strict=True)
    ]
    result = characterize_dark_current(series)
    assert result.summary_pixel_count == 0
    assert np.isnan(result.mean_dark_dn).all()
    assert np.isnan(result.dark_current_nonuniformity_dn_per_s)
    assert any(item.code == "no_summary_pixels" for item in result.validation.warnings)
    if slope is None:
        assert result.indeterminate_pixel_count == 4
        assert np.isnan(result.dark_current_map_dn_per_s).all()
    else:
        assert result.measured_pixel_count == 4
        np.testing.assert_allclose(result.dark_current_map_dn_per_s, slope)


def test_split_mask_and_fits_use_disjoint_repeats() -> None:
    """Neither an outlier nor rail hits in the fit frames can change selection."""
    rng = np.random.default_rng(381)
    series = []
    for t, n in zip(EXPOSURES_S, (4, 5, 6, 7)):
        frames = rng.normal(100 + 2 * t, 1.0, (n, 32, 40))
        reserved = 2 if n % 2 == 0 else 3
        frames[:reserved, 1, 1] = 0  # exclude on reserved frames alone
        frames[:reserved, 2, 2] += 18 * t  # pilot hot candidate
        frames[reserved:, 3, 3] += 18 * t  # hot only in fit frames
        series.append(CameraExposureSeries(frames, t))
    result = characterize_dark_current(series)
    intrinsic = result.intrinsic_dispersion
    mask = intrinsic.pixel_mask
    assert mask is not None and not mask.flags.writeable
    assert not mask[1, 1] and not mask[2, 2] and mask[3, 3]
    assert not result.summary_pixel_mask[3, 3]
    # Reference: explicit per-level means and NumPy OLS/cov, not the core fit.
    slopes = []
    for half in (0, 1):
        means = [
            item.frames_dn[p + half :: 2].mean(axis=0)[mask]
            for item, p in zip(series, (2, 3, 2, 3))
        ]
        slopes.append(np.polyfit(EXPOSURES_S, means, 1)[0])
    assert intrinsic.covariance == pytest.approx(np.cov(slopes)[0, 1])

    series[-1].frames_dn[-1, 6, 6] = 4095
    censored = characterize_dark_current(series).intrinsic_dispersion
    np.testing.assert_array_equal(censored.pixel_mask, mask)
    assert censored.status is DispersionStatus.MEASUREMENT_RAIL
    assert censored.fit_rail_pixels == 1
    assert np.isnan(censored.covariance)


def test_negative_covariance_is_not_a_measured_zero_in_workflow() -> None:
    rng = np.random.default_rng(44)
    pattern = rng.normal(size=(32, 40))
    images = []
    for t in EXPOSURES_S:
        frames = rng.normal(100 + 2 * t, 0.5, (4, 32, 40))
        frames[2] += t * pattern
        frames[3] -= t * pattern
        images.extend(_dark_image(frame, t) for frame in frames)
    outcome = DARK_CURRENT_RECIPE.run(
        {"dark_frames": tuple(images)},
        DarkCurrentRecipeParameters(),
        RecipeExecutionContext(),
    )
    rows = {row[0]: row for row in outcome.results[0].value.data}
    assert rows["Split-slope covariance"][1] < 0
    assert rows["Split-slope covariance 95% upper"][1] < 0
    assert rows["Intrinsic dark-current dispersion"][1] is None
    assert rows["Intrinsic dispersion 95% upper"][1] is None
    assert "intrinsic_dark_dispersion_negative_interval" in {
        d.code for d in outcome.diagnostics
    }


@pytest.mark.parametrize(
    ("side", "status"),
    [(16, DispersionStatus.TOO_FEW_BLOCKS), (8, DispersionStatus.NO_CONTRAST)],
)
def test_unavailable_uncertainty_is_not_a_detection(side, status) -> None:
    truth = 2 + np.linspace(0, 1, 32)[:, None] * np.ones((1, 32))
    series = [
        CameraExposureSeries(np.repeat((100 + t * truth)[None], 4, axis=0), t)
        for t in EXPOSURES_S
    ]
    intrinsic = characterize_dark_current(
        series, DarkCurrentParameters(dispersion_block_side=side)
    ).intrinsic_dispersion
    assert intrinsic.status is status
    assert intrinsic.covariance == pytest.approx(np.var(truth, ddof=1))
    assert np.isnan(intrinsic.sd_dn_per_s) and np.isnan(intrinsic.sd_ci95).all()
