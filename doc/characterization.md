# Relative Characterization in DN

The headless core accepts one dark stack and a sequence of flat-field stacks at
strictly increasing exposure times. It reports all detectable input anomalies
before running characterization and produces only relative quantities in
digital numbers.

This implementation is not a calibrated radiometric model and does not claim
EMVA 1288 compliance. It does not estimate conversion gain, quantum efficiency,
responsivity, or photon flux.

## Input Contract

Each series may be a stack shaped `(frames, height, width)` or a sequence of 2D
arrays. Dark and flat series must:

- use the same image shape and real numeric dtype;
- contain at least the configured number of frames;
- contain only finite values;
- provide at least two unsaturated flat exposure levels;
- list flat exposure times in strictly increasing order.

`validate_camera_inputs` returns a `CameraInputValidation` containing immutable
diagnostics with a severity, stable code, English message, and structured
details. Errors block characterization. Warnings preserve the result and cover
zero temporal variance, configured excessive variance, and excessive
saturation.

The saturation fraction and maximum temporal variance are explicit caller
thresholds. They are workflow criteria, not implicit normative limits.

## Metric Definitions

The global dark mean is subtracted from each flat-series mean:

```text
mean_signal_dn[level] = mean(flat[level]) - mean(dark)
```

A negative value is retained rather than clipped: it indicates that the flat
mean is below the dark mean and should be treated as a dataset or acquisition
anomaly when interpreting downstream ratios.

For each stack, temporal variance is the spatial mean of the unbiased
per-pixel sample variance:

```text
temporal_variance_dn2 = mean_pixels(var_frames(pixel, ddof=1))
temporal_noise_dn = sqrt(temporal_variance_dn2)
relative_snr = mean_signal_dn / temporal_noise_dn
```

The response curve is `mean_signal_dn` versus exposure time. A first-degree
least-squares fit uses only levels whose saturated-pixel fraction is below the
configured warning threshold. Linearity residuals are reported in DN for every
level, including excluded saturated levels:

```text
residual_dn = measured_signal_dn - fitted_signal_dn
```

The saturation onset is the first level meeting the saturation-fraction
threshold. The relative dynamic-range estimate is:

```text
maximum_unsaturated_signal_dn / dark_temporal_noise_dn
```

When a measured noise is zero, the corresponding relative SNR or dynamic range
is represented as positive infinity rather than hidden or replaced by an
arbitrary finite value.

## Spatial Definitions

The spatial calculation uses the mean dark image `D` and one selected mean
flat image `F`. The selected flat is the highest-exposure level retained by
the temporal linear fit. The DSNU-like map is expressed in DN:

```text
dsnu_like_dn = D - mean_pixels(D)
```

The PRNU-like map is the fractional deviation of the dark-corrected flat:

```text
flat_signal_dn = F - D
prnu_like_fraction = flat_signal_dn / mean_pixels(flat_signal_dn) - 1
```

The mean dark-corrected flat signal must be positive. Dark and flat spatial
non-uniformity metrics are the sample standard deviations (`ddof=1`) of these
maps. Row and column profiles are means of the PRNU-like map along the other
axis. Histograms contain every map pixel.

A candidate pixel exceeds the configured absolute sigma threshold in either
map. Zero-variance maps contribute no candidates. This union is a screening
aid, not a defect classification or acceptance standard; the threshold and
relative formulas are explicit because no EMVA compliance is claimed.

## Memory Scope

Mean and variance use a per-pixel parallel Chan/Welford accumulator. For an
existing state with count `N`, mean `mean`, and sum of squared deviations `M2`,
a block with corresponding values `n`, `block_mean`, and `block_M2` is merged
as follows:

```text
delta = block_mean - mean
merged_mean = mean + delta * n / (N + n)
merged_M2 = M2 + block_M2 + delta**2 * N * n / (N + n)
sample_variance = merged_M2 / (N + n - 1)
```

`compute_image_stack_statistics` exposes the block implementation directly.
`ImageStackAccumulator` also accepts individual frames or caller-provided
blocks when the data source can stream them. The convenience API accepts a 3D
array or a sequence of 2D arrays. Results contain read-only per-pixel mean and
variance arrays.

Mean images retained as recipe outputs use a dedicated mean-only aggregator.
It scans at most one configured block at a time and accumulates into one
float64 image, avoiding an unused full-size variance map and an extra output
copy.

`validate_camera_inputs` and `characterize_relative_dn` accept the keyword-only
`aggregation_block_size`. The default is one frame, minimizing transient
memory. A larger value trades additional temporary memory for fewer NumPy
operations. Float conversion, finite-value scans, mean/variance temporaries,
and saturation masks receive no more than that number of frames at once.

For frames shaped `(height, width)` and block size `B`, temporary
frame storage scales as `O(B * height * width)` and accumulator state scales as
`O(height * width)`, independent of the total frame count. Existing 3D input
stacks remain owned by the caller. A sequence of existing 2D arrays avoids an
additional complete stack: only the current block is materialized.

Unit tests compare multiple block sizes, incomplete final blocks, integer data,
and high-offset floating-point data against NumPy `mean` and `var(ddof=1)`.
Equivalence is numerical within explicit floating-point tolerances, not a
bit-for-bit promise across block sizes or NumPy versions. Characterization
extracts the scalar mean and temporal variance for one exposure before
releasing its per-pixel maps; its retained state therefore does not grow with
the number of flat levels. The reproducible 2048 x 2048 time and incremental
memory protocol is documented in [`validation.md`](validation.md).
