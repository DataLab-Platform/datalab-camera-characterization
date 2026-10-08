# Photon Transfer Curve

[← Documentation index](README.md)

This method estimates the conversion gain of a linear camera, in e⁻/DN, from the temporal variance of the signal versus its mean. From the gain, it gives the read noise, saturation capacity, dynamic range and SNR in electrons. It follows the usual photon transfer practice (Janesick) and is inspired by EMVA 1288, without claiming compliance.

Recipe: `org.datalab.camera-characterization:photon-transfer`, version 1.0.0.

## Run

Select the frames, then choose **Plugins > Camera & Detector Characterization > Run photon transfer analysis...**, or use the **Photon transfer curve** method of the **Applications** catalog. **Open photon transfer example** opens the demonstration.

## Inputs

The inputs are the same as for the [relative characterization](relative-dn.md#inputs): dark frames, and flat frames with their exposure time. Two frames per level are enough. The illumination must be uniform.

**Parameters:** minimum frame and level counts, saturation level and warning fraction, upper bound of the fit, minimum number of fitted levels, exclusion of pixels stuck in the dark, aggregation block size.

## Results

| Output | Type | Content |
| --- | --- | --- |
| `ptc` | Signal | Temporal variance versus mean signal (DN², DN), with the metrics table |
| `ptc_fit` | Signal | Fitted straight line up to the saturation point |
| `noise_vs_signal` | Signal | Total temporal noise versus signal, in electrons |
| `snr_vs_signal` | Signal | Measured SNR versus signal in electrons |
| `snr_model` | Signal | SNR model (shot noise and read noise) versus signal in electrons |

The metrics table gives the conversion gain, read noise, dark temporal noise, saturation capacity and signal, dynamic range, fit intercept and R², and the numbers of fitted levels and excluded pixels. The saturation rows tell whether saturation was reached; other statuses are `Not assessed`.

## Method

For a linear sensor limited by shot noise, the collected electrons follow a Poisson law: their variance equals their mean. With a conversion gain `K` in e⁻/DN, the dark-corrected mean `mu_y` and variance `sigma2_y`, both in DN, follow `sigma2_y = mu_y / K`. The slope of the variance versus the mean is therefore `1 / K`.

1. Pixels stuck at an ADC limit in the dark frames are excluded, when this option is on.
2. For each level, the per-pixel mean and temporal variance (`ddof=1`) are computed. Per-pixel statistics remove fixed-pattern noise: with two frames, this is the pair-difference method.
3. The dark mean and variance are subtracted.
4. The saturation point is the level with the largest variance.
5. The fit uses the levels with a positive mean below `fit_upper_fraction` of the saturation signal (70 % by default).

Then:

```text
read_noise_e        = K * dark_temporal_noise_dn
saturation_capacity = K * mu_y_sat
dynamic_range_db    = 20 * log10(saturation_capacity / read_noise_e)
model_snr(mu_e)     = mu_e / sqrt(mu_e + read_noise_e**2)
```

The read noise includes the ADC quantization noise of 1/12 DN². If the variance still grows at the last level, the saturation capacity is a lower bound and a `saturation_not_reached` warning is added. Too few fitted levels or a non-positive slope stop the run.

## Demonstration

The **Synthetic photon transfer ladder** simulates a 96 × 128, 12-bit sensor (2 e⁻/DN, 3 e⁻ read noise) under a uniform illumination of 60,000 e⁻/s. It holds 4 dark frames and 16 levels of 2 frames: from 1 ms to 64 ms, then dense steps from 96 ms to 140 ms around saturation (about 133 ms).

The validation suite checks the results against the simulator truth: gain within 3 %, read noise within 10 %, saturation capacity between 90 % and 100 % of the ADC limit, and dynamic range within 1.5 dB.

## Limits

The model assumes a linear sensor limited by shot noise. Nonlinearity, gain changes between levels, temporal drift and dark current at long exposures are not corrected. Quantum efficiency and responsivity need a calibrated photon flux: they are out of scope.
