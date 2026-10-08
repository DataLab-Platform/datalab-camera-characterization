# Dark Current and Hot Pixels

[← Documentation index](README.md)

This method measures the dark current, its spatial non-uniformity and the hot pixels from a dark ramp: frames taken with the shutter closed at several exposure times.

Recipe: `org.datalab.camera-characterization:dark-current`, version 1.0.0.

## Run

Select the dark frames, then choose **Plugins > Camera & Detector Characterization > Run dark-current analysis...**, or use the **Dark current and hot pixels** method of the **Applications** catalog. **Open dark-ramp example** opens the demonstration.

## Inputs

The method has one **Dark frames** slot. Every frame carries its exposure time in `plugin.org.datalab.camera-characterization.exposure_time_s`. By default, at least three exposure levels are needed. Also set the frame role to `dark`: otherwise, the other methods take these frames as flat frames. See [Use your own frames](getting-started.md#use-your-own-frames).

**Parameters:** minimum frame and level counts, saturation level and warning fraction, conversion gain (0 keeps DN units), hot-pixel threshold, background window, histogram bins, aggregation block size.

## Results

| Output | Type | Content |
| --- | --- | --- |
| `dark_ramp` | Signal | Mean dark signal of regular pixels versus exposure time, with the metrics table |
| `dark_variance_ramp` | Signal | Mean dark temporal variance versus exposure time |
| `dark_current_map` | Image | Dark current per pixel, in e⁻/s (DN/s without gain); NaN where no fit is possible |
| `offset_map` | Image | Offset per pixel, in DN |
| `hot_pixel_map` | Image | 0 regular, 1 hot, 2 stuck |
| `dark_current_distribution` | Signal | Histogram of the dark-current map |

The metrics table gives the mean and median dark current, its absolute and relative non-uniformity, the offset, the ramp fit R², the numbers of hot and stuck pixels, the indicative gain from dark shot noise, and the number of exposure levels.

## Method

The mean dark signal of a pixel grows linearly with the exposure time `t`:

```text
dark_signal_dn(t) = offset_dn + D_dn_per_s * t
```

The intercept is the offset: bias and fixed offset pattern. The slope `D` is the dark current. Multiplied by a conversion gain `K`, for instance from the [photon transfer curve](photon-transfer.md), it is in e⁻/s.

1. For each level, the per-pixel mean, temporal variance and maximum are computed.
2. Each pixel is fitted over the levels where it never saturates. The slopes form the dark-current map and the intercepts the offset map.
3. Pixels stuck at an ADC limit at every level are stuck pixels.
4. Hot pixels are isolated pixels whose dark current exceeds the local background (median over `background_window` pixels, 5 by default) by more than `hot_pixel_threshold_sigma` standard deviations. This deviation combines the spread of the map with the slope uncertainty expected from the temporal noise, so smooth structures such as amplifier glow are not hot pixels. Pixels that saturate before two levels can be fitted are hot pixels too.
5. Ramps, means and non-uniformity use regular pixels only.

Dark electrons also follow a Poisson law. The ratio of the mean and variance ramp slopes therefore gives an indicative conversion gain, `K_dark = slope(mean) / slope(variance)`. It needs enough dark electrons to dominate the read noise.

## Demonstration

The **Synthetic uncooled CMOS dark ramp** simulates a 96 × 128, 12-bit sensor (2 e⁻/DN, 3 e⁻ read noise). Its mean dark current is 40 e⁻/s with 10 % non-uniformity, 0.2 % of hot pixels are 30 times hotter, and an amplifier glow of 150 e⁻/s peaks in the lower-right corner. It holds four dark frames at each of 0.5, 1, 2, 4 and 8 s; most hot pixels saturate at 8 s. The glow shows in the dark-current map but not in the offset map: a ramp separates what grows with the exposure from the fixed pattern.

The validation suite checks the results against the simulator truth: mean dark current within 3 %, non-uniformity within 10 %, hot-pixel recall and precision of at least 95 %, and indicative gain within 5 %.

## Limits

Temperature is not modeled: dark current roughly doubles every 6 to 8 °C, so a ramp is meaningful only at a stable sensor temperature. Random telegraph signal, nonlinear dark signal and glow that does not grow with the exposure are not modeled.
