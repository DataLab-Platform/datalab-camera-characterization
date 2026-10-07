# Photon Transfer Recipe

The plugin registers a second versioned recipe:

```text
org.datalab.camera-characterization:photon-transfer
```

It estimates the conversion gain of a linear camera from the photon transfer curve (PTC): the temporal variance of the signal as a function of its mean. The method follows the usual photon transfer practice (Janesick) and is inspired by EMVA 1288, but the plugin does not claim EMVA 1288 compliance.

## Physical Principle

For a linear sensor whose temporal noise is dominated by photon shot noise, the number of collected electrons follows a Poisson law: its variance equals its mean. With a conversion gain `K` in electrons per DN, the dark-corrected mean signal `mu_y` and the dark-corrected temporal variance `sigma2_y` (both in DN) satisfy:

```text
sigma2_y = mu_y / K
```

The slope of the variance versus the mean therefore gives `1 / K`. Once `K` is known, every DN quantity converts to electrons:

```text
read_noise_e         = K * dark_temporal_noise_dn
saturation_capacity  = K * mu_y_sat
dynamic_range_db     = 20 * log10(saturation_capacity / read_noise_e)
model_snr(mu_e)      = mu_e / sqrt(mu_e + read_noise_e**2)
```

`mu_y_sat` is the mean signal at the maximum of the temporal variance: above that point, pixels start clipping at the ADC limit or at the full well, so their variance collapses. With a sensor limited by its ADC, as in the demonstration, the saturation capacity is slightly below the ADC limit because the brightest pixels clip first.

## Computation

1. Pixels stuck at an ADC limit in the dark frames (dead pixels at 0 DN, hot pixels at saturation) are excluded from every spatial mean when **Exclude pixels stuck at ADC limits in the dark** is enabled.
2. For each exposure level, the per-pixel mean and the per-pixel temporal variance (`ddof=1`) are computed with the bounded-memory aggregator. Per-pixel temporal statistics remove fixed-pattern noise (PRNU and DSNU), so two frames per level are enough: with two frames, this is the pair-difference method.
3. The dark mean and dark variance are subtracted from each level.
4. The saturation point is the level with the largest variance.
5. A first-degree least-squares fit of variance versus mean uses the levels with a positive mean below `fit_upper_fraction` of the saturation signal (70 % by default).
6. The read noise is the dark temporal noise converted to electrons. It therefore includes the ADC quantization noise of 1/12 DN².

If the variance still increases at the last level, the saturation capacity is reported as a lower bound and a `saturation_not_reached` warning is attached to the outcome.

## Inputs and Parameters

The inputs are the same as for the relative-DN recipe: a `dark_frames` slot and a `flat_frames` slot. Flat frames carry their exposure time in `EXPOSURE_TIME_METADATA_KEY`. Frames sharing an exposure form one series.

`PhotonTransferRecipeParameters` exposes the minimum frame count, the minimum number of flat levels, the saturation level and saturation warning fraction, the upper bound of the linear fit, the minimum number of fitted levels, the stuck-pixel exclusion and the aggregation block size. Fewer fitted levels than required, or a non-positive slope, stop the recipe with a structured `CameraCharacterizationError`.

## Outcome

| Output ID | Type | Meaning |
| --- | --- | --- |
| `ptc` | Signal | Temporal variance versus mean signal (DN², DN); anchor object |
| `ptc_fit` | Signal | Fitted straight line up to the saturation point |
| `noise_vs_signal` | Signal | Total temporal noise versus signal, both in electrons |
| `snr_vs_signal` | Signal | Measured SNR versus signal in electrons |
| `snr_model` | Signal | Shot-noise and read-noise SNR model versus signal in electrons |

The `metrics` table is attached to `ptc`. It reports the conversion gain, read noise, dark temporal noise, saturation capacity and signal, dynamic range, fit intercept and R², number of fitted levels and number of excluded pixels. Statuses are `Not assessed`, except for the saturation rows that state whether saturation was reached or is a lower bound.

## Demonstration

The **Synthetic photon transfer ladder** example is generated in memory. A 96 × 128, 12-bit sensor with a conversion gain of 2 e⁻/DN and 3 e⁻ read noise receives a uniform illumination of 60,000 e⁻/s. The campaign contains four dark frames and 16 exposure levels of two frames each: a geometric ladder from 1 ms to 64 ms, then dense steps from 96 ms to 140 ms around the ADC saturation (about 133 ms). Every series shares the same static sensor maps but draws an independent noise realization.

Illumination is uniform on purpose: the photon transfer method requires a uniform field. Vignetting and dust belong to the relative-DN quickstart.

The validation suite checks the recovered values against the simulator truth: conversion gain within 3 %, read noise within 10 % of the electronic read noise combined with quantization noise, saturation capacity between 90 % and 100 % of the ADC limit, and dynamic range within 1.5 dB.

## Limits

The model assumes a linear, shot-noise-limited sensor. Nonlinearity, gain changes between levels, temporal drift, and dark current at long exposures are not corrected. Quantum efficiency and responsivity require a calibrated photon flux and are out of scope.
