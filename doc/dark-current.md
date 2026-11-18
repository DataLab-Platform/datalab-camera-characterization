# Dark Current and Hot Pixels

[← Documentation index](README.md)

This method measures the dark current, its spatial non-uniformity and the hot pixels from a dark ramp: frames taken with the shutter closed at several exposure times.

Recipe: `org.datalab.camera-characterization:dark-current`, version 1.0.0.

## Run

Select the dark frames, then choose **Plugins > Camera & Detector Characterization > Run dark-current analysis...**, or use the **Dark current and hot pixels** method of the **Applications** catalog. **Open dark-ramp example** opens the demonstration.

## Inputs

The method has one **Dark frames** slot. Every frame carries its exposure time in `plugin.org.datalab.camera-characterization.exposure_time_s`. By default, at least three exposure levels are needed. Also set the frame role to `dark`: otherwise, the other methods take these frames as flat frames. See [Use your own frames](getting-started.md#use-your-own-frames).

**Parameters:** minimum frame and level counts, saturation level and warning fraction, conversion gain (0 keeps LSB units), hot-pixel threshold, background window, spatial block side for intrinsic dispersion (default 8 pixels), histogram bins, aggregation block size. The aggregation block size controls memory use; it does not set the spatial scale of the uncertainty estimate.

## Results

| Output | Type | Content |
| --- | --- | --- |
| `dark_ramp` | Signal | Mean dark signal (LSB) versus exposure time for the fixed summary population, with the metrics table |
| `dark_variance_ramp` | Signal | Mean temporal variance (LSB²) versus exposure time for the same population |
| `dark_current_map` | Image | Slope of each measurable pixel, including hot and partially censored pixels; e⁻/s with a supplied gain, otherwise LSB/s |
| `offset_map` | Image | Intercept of the same fit, always in LSB; both maps contain NaN where no fit is possible |
| `hot_pixel_map` | Image | Classification of every pixel: 0 measurable without a hot flag, 1 measurable hot candidate, 2 stuck at the same rail, 3 indeterminate |
| `summary_pixel_mask` | Image | 1 included, 0 excluded: only class 0 pixels with a usable level at **every** exposure enter the summary |
| `dark_current_distribution` | Signal | Histogram of all measurable slopes (classes 0 and 1); the sum of bin counts is the number of slopes on the map |

The table gives the total number of sensor pixels, the numbers of measurable slopes and summary pixels, and the counts of hot, stuck and indeterminate pixels. The hot-pixel fraction in ppm uses **all sensor pixels** as its denominator. The mean, median, observed sample standard deviation of slopes, relative non-uniformity and ramp fits use the **summary mask**, not the histogram population. Each output records its population, included count and total sensor pixel count in its metadata. An empty summary leaves these statistics unavailable; any measurable individual slopes and the classification are still returned.

## Method

The mean dark signal of a pixel grows linearly with the exposure time `t`:

```text
dark_signal_dn(t) = offset_dn + D_dn_per_s * t
```

The intercept is the offset: bias and fixed offset pattern. The slope `D` is the dark current. Multiplied by a conversion gain `K`, for instance from the [photon transfer curve](photon-transfer.md), it is in e⁻/s.

1. Use native ADC codes and preserve the offset. At each exposure, exclude a pixel's level if **any** frame reaches the upper rail, or if **at least two frames and at least half the repeats** are at or below zero. This low-rail pile-up rule detects censoring without discarding a level for a single zero. A retained level is not proof of an absence of clipping.
2. Fit the per-level means at the remaining exposures, with equal weight per level. Two distinct usable levels give a slope and intercept but cannot test linearity; a warning counts such fits. R² for the mean ramp is undefined for a constant signal and is not reported for a two-point fit.
3. Assign **stuck** only if every frame at every exposure is at the same rail. Switching from low to high is not stuck. A non-stuck pixel with fewer than two usable levels is **indeterminate**, not hot: early clipping can be due to offset rather than dark current.
4. Flag a **hot candidate** only for a measurable slope above its local median background (5 × 5 pixels by default). For nonzero uncertainty, the excess must exceed the configured sigma multiplier; the estimated uncertainty combines local temporal slope noise and robust spatial spread. If that uncertainty vanishes, allow each level mean a rounding error of ±0.5 native LSB and propagate it through its slope fit. Flag the pixel only if its lowest possible slope still exceeds the median of the neighbors' highest possible slopes. A smooth glow is spatial structure, not itself evidence of isolated hot pixels.

For example, at 1, 2, 4 and 8 s, repeated values of **0, 0, 8, 28 LSB** leave two usable levels: the map reports **5 LSB/s** and an intercept of **−12 LSB**. That pixel contributes to the histogram, but not to the summary. **4094, 4095, 4095, 4095** with a 4095 LSB rail has only one usable level: its class is 3 with no slope.

Dark electrons also follow a Poisson law. The ratio of the mean and variance ramp slopes therefore gives an indicative conversion gain, `K_dark = slope(mean) / slope(variance)`. It needs enough dark electrons to dominate the read noise.

## Observed and intrinsic dispersion

**Dark-current non-uniformity** remains the primary result: the sample standard deviation (SD) of the slope map on `summary_pixel_mask`. It includes the noise in each fitted slope. A uniform simulated sensor with 4 LSB read noise, four frames at each of 1, 2, 4 and 8 s, gives an observed SD of **0.368 LSB/s**. This does not establish a non-uniform sensor.

**Intrinsic dark-current dispersion** asks how much of the spatial variation repeats in two independent acquisitions of this sensor. It estimates the SD of the expected native-code slopes on a separately selected population. A repeatable glow or gradient contributes; a fixed offset does not. It is not a measurement of isolated pixel variation with the glow removed.

1. Acquire **at least four independent frames at every exposure**, with stable temperature, acquisition settings and a linear response away from both rails. In input order within each exposure, reserve the first two frames (three for an odd count), then alternate the remainder between balanced sets A and B. For example, with four frames, use 1–2 for selection, 3 for A and 4 for B. Reusing an image, or temporal drift shared by the fits, violates independence.
2. Select pixels solely on the reserved frames: exclude any pixel touching either rail at any exposure, then exclude local hot candidates using the same excess test as for the main ramp, fitted on reserved frames alone. Do **not** use `summary_pixel_mask`. Fit A and B on all exposures with equal weight per level. If a selected pixel reaches a rail in either fit set, withhold the entire covariance instead of silently dropping the pixel. The table records the population and exclusions; its attributes give the exposure times, per-level split, block size and counts.
3. Center each slope map on these `N` pixels. The **signed split-slope covariance** is `C = sum(a * b) / (N − 1)`, in (LSB/s)² or (e⁻/s)² with a supplied gain. Independent zero-mean slope errors make this an estimate of the sample variance of the fixed true slopes; unequal noise from pixel to pixel or exposure to exposure is allowed.
4. The **approximate 95% interval** measures repeat-acquisition uncertainty, not variation between sensors. For independent, approximately Gaussian slope maps with matched noise covariance, `sum((a² − b²)/2)` has zero expectation and the same variance as `sum(a * b)`. Sum this contrast within each spatial tile first; the standard error is the square root of the sum of squared tile contrasts divided by `N − 1`. This retains within-tile noise correlations without resampling the glow itself. A Student multiplier uses the effective number of contributing tiles minus one degree of freedom. At least 16 populated tiles, nonzero contrast and at least eight effective tiles are required.

Choose the block side using independent knowledge of the **noise** correlation scale: noise across tiles must be approximately independent. Long-range row/column noise across tiles, strongly skewed slope errors, shared drift, or systematic quantization/clipping bias invalidate the interpretation; the method cannot establish these assumptions from a single ramp. The interval does not include uncertainty in a supplied conversion gain.

Only a covariance interval **strictly above zero** yields a measured SD, `sqrt(C)`. Otherwise the SD cell stays empty and the diagnostic gives the reason. If the interval crosses zero, the table can still show the compatible range from zero to the square root of its upper endpoint: the zero is a **boundary, not an estimate**. A wholly negative interval is retained in signed units with no physical SD range. Missing repeats, selected pixels or spatial information do not erase the observed SD.

## Demonstration

The **Synthetic uncooled CMOS dark ramp** simulates a 96 × 128, 12-bit sensor (2 e⁻/LSB, 3 e⁻ read noise). Its mean dark current is 40 e⁻/s with 10 % non-uniformity, 0.2 % of hot pixels are 30 times hotter, and an amplifier glow of 150 e⁻/s peaks in the lower-right corner. It holds four dark frames at each of 0.5, 1, 2, 4 and 8 s; most hot pixels saturate at 8 s. The glow shows in the dark-current map but not in the offset map: a ramp separates what grows with the exposure from the fixed pattern.

The validation suite checks the results against the simulator truth: mean dark current within 3 %, non-uniformity within 10 %, hot-pixel recall and precision of at least 95 %, and indicative gain within 5 %.

On the shipped 20-frame example, the independent selection includes **12,251 of 12,288** pixels (36 excluded at a rail, one additional hot candidate). The observed SD is **31.076 e⁻/s**; the split estimate is **31.033 e⁻/s** (approximate 95% interval **30.967–31.099 e⁻/s**), versus **31.031 e⁻/s** on the simulator truth. Agreement of the two populations in this example is not an assumption of the method.

## Limits

Temperature is not modeled. Stabilize the sensor and record its temperature throughout the ramp: temperature-dependent drift during the exposure sequence can look like dark current. The temperature dependence is sensor-specific; a fixed doubling interval cannot be assumed. Random telegraph signal, nonlinear dark signal and glow that does not grow with the exposure are not modeled.
