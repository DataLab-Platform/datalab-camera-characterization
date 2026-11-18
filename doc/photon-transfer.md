# Photon Transfer Curve

[← Documentation index](README.md)

This method estimates the conversion gain of a linear camera, in e⁻/LSB, from the temporal variance of the signal versus its mean. It reports the measured dark temporal noise in electrons and estimates read noise only from a usable short bias. It also reports saturation capacity, dynamic range and SNR. It follows the usual photon transfer practice (Janesick) and is inspired by EMVA 1288, without claiming compliance.

Recipe: `org.datalab.camera-characterization:photon-transfer`, version 1.0.0.

## Run

Select the frames, then choose **Plugins > Camera & Detector Characterization > Run photon transfer analysis...**, or use the **Photon transfer curve** method of the **Applications** catalog. **Open photon transfer example** opens the demonstration.

## Inputs

The inputs are the same as for the [relative characterization](relative-dn.md#inputs): repeated dark frames and repeated uniform flat frames on an increasing exposure ladder. Use raw, linear camera output, fixed settings and illumination stable both within and between levels. Two independent frames per level are sufficient for one difference. Preserve acquisition order within each exposure group.

The default gain uses **Raw temporal variance**. **Centered differences of independent pairs** is an optional comparison. Only confirm **Illumination independently verified stable across the ladder** if an independent check supports that statement; otherwise a sub-rail plateau cannot establish a limiting response. Neither setting is needed to run the example.

## Results

| Output | Type | Content |
| --- | --- | --- |
| `ptc` | Signal | Selected dark-subtracted variance versus net mean signal (LSB², LSB), with the metrics table |
| `ptc_fit` | Signal | Fitted straight line on the levels actually used |
| `noise_vs_signal` | Signal | Total temporal noise versus signal, in electrons |
| `snr_vs_signal` | Signal | Measured SNR versus signal in electrons |
| `snr_model` | Signal | SNR model (photoelectron shot noise plus the reference dark variance at each level) versus signal in electrons |

The metrics table identifies the dark exposures used for correction and noise, the gain mode, both gains on the same fit levels (when estimable), both variance curves, and the largest common-mode term removed from the flat and dark pairs. The `ptc_analysis` metadata on the curve and table retain the fit and clipping masks, rail population and threshold, each frame mean, pair counts and removed variances, and the evidence and status of the response limit. The `dark_reference` metadata retain the original dark means and raw variances; the source images are unchanged.

## Method

For a linear sensor limited by shot noise, the collected electron count follows a Poisson distribution: its variance equals its mean. With a conversion gain `K` in e⁻/LSB, the dark-corrected mean `mu_y` (LSB) and variance `sigma2_y` (LSB²) follow `sigma2_y = mu_y / K`. The slope of the variance versus the mean is therefore `1 / K`.

1. Establish one pixel population for every flat and dark statistic (by default, exclude pixels stuck at either ADC rail in any dark reference used). For the raw variance use every repeat: average the per-pixel sample variances (`ddof=1`), not the spatial variance of a flat.
2. Subtract the dark mean and variance at each flat exposure when the full ladder has matching darks. Otherwise use a single identified reference; multiple partially matching dark exposures require an explicit choice. Subtract like from like: raw flat minus raw dark, or centered pairs minus centered dark pairs.
3. Fit the selected net variance against positive net signal, excluding significantly clipped levels and the demonstrated limit and its successors. The upper bound is `fit_upper_fraction` times the largest remaining signal (70% by default). Inspect the residuals and R²; a good fit does not prove that the illumination was stable. Too few distinct data points or a non-positive slope stop the run. The variance peak is recorded separately and selects neither the fit nor the response limit.

Then:

```text
dark_noise_e        = K * dark_temporal_noise_dn
capacity_e          = K * reported_net_signal_dn
dynamic_range_db    = 20 * log10(capacity_e / dark_noise_e)
model_snr(mu_e)     = mu_e / sqrt(mu_e + K**2 * dark_variance_at_level_dn2)
```

Only a zero-exposure bias, or a separately identified camera-minimum bias with negligible dark current (**Known short bias exposure**), can provide **Estimated read noise**. Its variance must be measurable and not significantly censored at either rail on the measured pixels. Otherwise the result is the **dark temporal noise** at the reported exposure, not a measurement of the electronics alone. A finite dark exposure can include dark shot noise; digitization is included in the observed noise, not subtracted as a universal constant. The noise-versus-signal curve and measured SNR always use the measured flat noise, not the noise of the bias.

### Reading the limit and dynamic range

| Status | Evidence and interpretation |
| --- | --- |
| **Observed: ADC clipping** | On pixels not stuck at a rail in the darks or throughout the flat ladder, at least the configured fraction (default 1%, rounded up, and at least two distinct pixels) reaches the high rail in **each** frame of a level and of all later levels. The reported signal is the net mean at the first such exposure, not the ADC code times the gain. One transient clipped frame censors that level without proving a repeatable ceiling. |
| **Observed: sub-rail response plateau** | Independent illumination stability is confirmed. At least three terminal, unclipped levels are spaced by at least 10% in exposure at each step. Their net means' full range plus the largest within-level repeat span (flat plus correction dark) must not exceed 1% of the smallest terminal signal. The preceding repeatable signal must be positive and more than 10% lower. This is a plateau of the **observed system response**: it cannot distinguish the physical pixel well, electronics, or processing. |
| **Lower bound** | No limit is demonstrated. Report only a positive, unclipped level with measurable flat variance, repeat span no greater than 1% of net signal, and a resolved rise of more than 1% relative to a preceding repeatable level. Do not extend the bound through high clipping or a resolved fall. For example, 512 → 540 LSB while variance falls from 256 to 255 LSB² is not proof of saturation. At 2 e⁻/LSB the demonstrated bound is 1,080 e⁻, not a measured capacity of 1,024 e⁻. |
| **Indeterminate** | Without a defensible signal there is no capacity value. The dynamic range also requires a positive, uncensored raw temporal noise of the designated dark. A missing or unresolved denominator is not an infinite range. |

Capacity in electrons is a signal equivalent under the fitted linear gain, **not** a measurement of physical full well. Dynamic range inherits the status of the numerator and is an indicative ratio to the noise of the stated dark, not EMVA dynamic range. Neither a measured SNR nor a shot-noise SNR prediction is plotted for a significantly clipped level or a verified response plateau. Zero measured flat variance does not give infinite measured SNR.

### Common-mode diagnostic and optional pair centering

For each stack (including the darks), compare the sample variance of frame means with the raw temporal variance. The diagnostic flags a ratio greater than both 10% and `9/N` for `N` measured pixels. This is a screening heuristic, not a significance test for correlated pixels and not proof of an optical cause: pickup, camera drift and illumination changes can all move the mean. Inspect the retained frame means also for slow changes between pairs.

Form adjacent **disjoint** pairs `(0,1), (2,3), …`; with an odd count, only the pair statistics omit the final frame. Means and raw variances still use it. For each difference image `D` on the same `N` pixels, subtract its own spatial mean. The centered estimate is `mean_pairs(sum_pixels((D - mean_pixels(D))²) / (2 N))`. Two independent equally noisy acquisitions contribute to a difference; spatial normalization is by `N`, not `N-1`. The removed term is `mean_pairs(mean_pixels(D)² / 2)` in LSB². Centered plus removed reconstructs the **uncentered pair** estimate, not necessarily the all-frame raw sample variance for more than two repeats.

Centering removes real camera common-mode noise as well as a spatially uniform change of illumination. For independent identically distributed pixels it also removes about `1/N` of the independent variance; small populations, temporal/spatial correlations, multiplicative fluctuations over a non-uniform field and changes of gain require separate checks. Independent repeats are an acquisition assumption, not guaranteed by forming disjoint pairs. In the balanced analytical ±2% witness the raw fit gives 1.086 e⁻/LSB and the centered fit gives 2.000 e⁻/LSB. Noise and measured SNR continue to describe the **raw flat** and dark-noise quantities describe the **raw dark**, even when the gain comes from the centered fit.

## Demonstration

The **Synthetic photon transfer ladder** simulates a 96 × 128, 12-bit sensor (2 e⁻/LSB, 3 e⁻ read noise) under a uniform illumination of 60,000 e⁻/s. It holds 4 dark frames and 16 levels of 2 frames: from 1 ms to 64 ms, then dense steps from 96 ms to 140 ms around saturation (about 133 ms).

The validation suite checks the results against the simulator truth: gain within 3 %, noise of the dark reference within 10 %, saturation capacity between 90 % and 100 % of the ADC limit, and dynamic range within 1.5 dB.

## Limits

The model assumes a linear sensor limited by shot noise. A single dark reference cannot remove the exposure dependence of dark current. Neither matched nor single-reference darks correct nonlinearity, gain changes between levels or temporal drift. Quantum efficiency and responsivity need a calibrated photon flux: they are out of scope.
