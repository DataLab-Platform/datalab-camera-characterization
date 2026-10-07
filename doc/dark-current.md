# Dark-Current Recipe

The plugin registers a third versioned recipe:

```text
org.datalab.camera-characterization:dark-current
```

It measures dark current, its spatial non-uniformity and hot pixels from a dark-frame exposure ramp: frames acquired with the shutter closed at several exposure times.

## Physical Principle

Thermally generated electrons accumulate during the exposure, at a rate that depends on the pixel and on the temperature. For one pixel, the mean dark signal in DN grows linearly with the exposure time `t`:

```text
dark_signal_dn(t) = offset_dn + D_dn_per_s * t
```

The intercept is the exposure-independent offset (bias and offset fixed pattern). The slope is the dark current. With a conversion gain `K` in e⁻/DN, for instance from the photon transfer recipe, the dark current in electrons is `K * D`.

Dark electrons also obey Poisson statistics. Their contribution to the temporal variance therefore grows as `D / K` per second, and the ratio of the two ramp slopes gives an independent, indicative estimate of the conversion gain:

```text
K_dark = slope(mean dark signal) / slope(dark temporal variance)
```

This estimate needs enough dark electrons to dominate the read noise; it is reported as indicative only.

## Computation

1. Frames are grouped by `EXPOSURE_TIME_METADATA_KEY`; at least three exposure levels are required by default.
2. For each level, the per-pixel mean, temporal variance and maximum are computed.
3. Each pixel is fitted by least squares over the levels where it never reaches saturation. The slope map is the dark-current map; the intercept map is the offset map.
4. Pixels stuck at an ADC limit at every level are reported as stuck pixels.
5. Hot pixels are isolated pixels whose dark current exceeds the local background (median filter over `background_window` pixels, 5 by default) by more than `hot_pixel_threshold_sigma` standard deviations. The standard deviation combines the intrinsic spread of the map (robust median absolute deviation) with the slope uncertainty expected from each pixel's temporal noise, smoothed locally. Smooth structures such as amplifier glow, whose shot noise is larger, are therefore not reported as hot pixels. Pixels that saturate before two levels can be fitted are the hottest of all and are also hot pixels.
6. Ramps, means and the non-uniformity use regular pixels only: not stuck, not hot, unsaturated at every level.

## Inputs and Parameters

The recipe has one `dark_frames` slot. Every frame carries its exposure time. The generated demonstration also writes `FRAME_ROLE_METADATA_KEY = "dark"` so that its frames are not taken as flat frames by the other recipes, although they carry an exposure time. To set these keys on your own frames, see [`preparing-frames.md`](preparing-frames.md).

`DarkCurrentRecipeParameters` exposes the minimum frame count, the minimum number of exposure levels, the saturation level and warning fraction, the conversion gain (0 keeps DN units), the hot-pixel threshold, the background window, the histogram bin count and the aggregation block size.

## Outcome

| Output ID | Type | Meaning |
| --- | --- | --- |
| `dark_ramp` | Signal | Mean dark signal of regular pixels versus exposure time; anchor object |
| `dark_variance_ramp` | Signal | Mean dark temporal variance versus exposure time |
| `dark_current_map` | Image | Per-pixel dark current in e⁻/s, or DN/s without gain; NaN where no fit is possible |
| `offset_map` | Image | Per-pixel exposure-independent offset in DN |
| `hot_pixel_map` | Image | 0 regular, 1 hot, 2 stuck |
| `dark_current_distribution` | Signal | Histogram of the dark-current map |

The `metrics` table is attached to `dark_ramp`. It reports the mean and median dark current, the absolute and relative dark-current non-uniformity, the offset, the ramp fit R², the hot-pixel count and fraction, the stuck-pixel count, the indicative gain from dark shot noise and the number of exposure levels.

## Demonstration

The **Synthetic uncooled CMOS dark ramp** example is generated in memory. A 96 × 128, 12-bit sensor (2 e⁻/DN, 3 e⁻ read noise) has a mean dark current of 40 e⁻/s with 10 % lognormal non-uniformity, 0.2 % hot pixels whose dark current is 30 times higher, and an amplifier glow of 150 e⁻/s peaking in the lower-right corner. Four dark frames are acquired at 0.5, 1, 2, 4 and 8 s. Most hot pixels saturate at 8 s, which exercises the per-pixel saturation exclusion.

The glow is dark current: it appears in the dark-current map but not in the offset map. This separates exposure-proportional structures from the fixed offset pattern, which a single dark frame cannot do.

The validation suite checks the mean dark current within 3 %, the non-uniformity within 10 %, hot-pixel recall and precision of at least 95 %, and the indicative gain within 5 % of the simulator truth.

## Limits

Temperature is not controlled or modeled: dark current roughly doubles every 6 to 8 °C, so a ramp is only meaningful at a stable sensor temperature. Random telegraph signal pixels, nonlinear dark-signal accumulation and glow that is not proportional to the exposure are not modeled.
