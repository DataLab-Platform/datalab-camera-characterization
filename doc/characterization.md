# Relative Characterization in DN

The headless core accepts one dark stack and a sequence of flat-field stacks at
strictly increasing exposure times. It reports all detectable input anomalies
before running characterization and produces only relative quantities in
digital numbers.

This implementation is not a calibrated radiometric model and does not claim
EMVA 1288 compliance. It does not estimate conversion gain, quantum efficiency,
responsivity, or photon flux.

## Input Contract

Each stack has shape `(frames, height, width)`. Dark and flat stacks must:

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

## Memory Scope

The current implementation converts and processes complete stacks in memory.
It is the batch numerical reference for roadmap phase 2.5, which will introduce
incremental or block mean/variance aggregation and prove equivalence against
these results before making campaign-size or memory-budget claims.
