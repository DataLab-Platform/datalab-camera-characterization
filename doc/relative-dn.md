# Relative Characterization in DN

[← Documentation index](README.md)

This method describes how the response, the temporal noise and the spatial non-uniformity of a camera behave, from dark and flat frames. Results stay in digital numbers (DN): the method estimates no conversion gain, quantum efficiency or radiometric quantity. For the conversion gain, use the [photon transfer curve](photon-transfer.md).

Recipe: `org.datalab.camera-characterization:relative-dn-characterization`, version 1.1.0.

## Run

Select the frames, then choose **Plugins > Camera & Detector Characterization > Run camera characterization...**, or use the **Relative Camera characterization** method of the **Applications** catalog. The [quickstart](getting-started.md#run-the-quickstart) is its demonstration.

## Inputs

| Slot | Content |
| --- | --- |
| Dark frames | At least 2 frames, shutter closed |
| Flat frames | At least 4 frames of a uniform field, each with its exposure time |

- Each image holds one 2D frame. All frames have the same shape and data type, and finite values only.
- Flat frames carry their exposure time, in seconds, in `plugin.org.datalab.camera-characterization.exposure_time_s`. Frames with the same exposure form one level. At least two levels must be unsaturated.
- To set this key and the frame role on your own frames, see [Use your own frames](getting-started.md#use-your-own-frames).

The inputs are checked before the computation. Errors stop the run. Warnings, such as zero or excessive temporal variance and excessive saturation, are kept with the results.

**Parameters:** minimum frame and level counts, saturation level and warning fraction, optional maximum temporal variance (0 disables it), aggregation block size, candidate-pixel threshold and histogram bins. These are workflow criteria, not acceptance limits.

## Results

| Output | Type | Content |
| --- | --- | --- |
| `response` | Signal | Mean dark-subtracted signal versus exposure, with the metrics table |
| `mean_dark` | Image | Mean of all dark frames |
| `mean_flat` | Image | Mean of the highest level kept by the linear fit |
| `dsnu_like_map` | Image | Centered mean dark image, in DN |
| `prnu_like_map` | Image | Relative deviation of the dark-corrected flat image |
| `candidate_pixel_map` | Image | Pixels beyond the threshold in either map |
| `prnu_row_profile`, `prnu_column_profile` | Signal | Row and column means of the PRNU-like map |
| `dsnu_distribution`, `prnu_distribution` | Signal | Histograms of both maps |

The metrics table gives the response slope and intercept, the dark temporal noise, the largest fit residual, the maximum unsaturated signal, the relative dynamic range, the selected flat exposure, the spatial non-uniformities, the candidate pixels and the saturation onset. Every status is `Not assessed`: no pass/fail standard is applied.

## Method

For each level, the dark mean is subtracted from the flat mean. The temporal variance is the spatial mean of the per-pixel sample variance:

```text
mean_signal_dn = mean(flat) - mean(dark)
temporal_variance_dn2 = mean_pixels(var_frames(pixel, ddof=1))
temporal_noise_dn = sqrt(temporal_variance_dn2)
relative_snr = mean_signal_dn / temporal_noise_dn
```

- **Response:** a straight-line fit of `mean_signal_dn` versus exposure, on the levels below the saturation warning fraction. Residuals are given for every level.
- **Saturation onset:** the first level that reaches the saturation warning fraction.
- **Dynamic range:** `maximum_unsaturated_signal_dn / dark_temporal_noise_dn`.
- **Spatial maps:** from the mean dark image `D` and the mean flat image `F` of the highest fitted level, `dsnu_like_dn = D - mean(D)` and `prnu_like = (F - D) / mean(F - D) - 1`. The non-uniformities are their standard deviations (`ddof=1`).
- **Candidate pixels:** pixels beyond the sigma threshold in either map. This is a screening aid, not a defect classification.

A negative mean signal is kept, not clipped: it points to a problem in the data. A zero noise gives an infinite SNR or dynamic range.

## Demonstration

The [quickstart](getting-started.md#run-the-quickstart) campaign shows every output. A separate synthetic campaign checks the method against the simulator truth: response slope within 0.5 %, dark noise within 2 % and fit residuals below 0.2 DN. A noiseless campaign checks the DSNU-like and PRNU-like maps against the truth maps. See [Qualification](qualification.md).

## Limits

- Results are relative quantities in DN. The method does not claim EMVA 1288 compliance.
- The PRNU-like map includes vignetting and dust: from frames alone, sensor PRNU and illumination cannot be separated.

## Python

```python
from datalab_camera_characterization.core import (
    CameraExposureSeries,
    CameraValidationParameters,
    characterize_relative_dn,
)

result = characterize_relative_dn(
    dark_frames,
    (
        CameraExposureSeries(flat_low, exposure_time_s=0.01),
        CameraExposureSeries(flat_high, exposure_time_s=0.02),
    ),
    CameraValidationParameters(saturation_dn=4095),
)
```
