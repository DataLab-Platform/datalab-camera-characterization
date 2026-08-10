# Deterministic Camera Simulation

The simulator produces a stack of unsigned integer camera frames and the exact
static/noiseless ground truth used to generate them. It is intended for testing
future relative characterization algorithms, not for claiming a calibrated or
EMVA 1288-compliant camera model.

## Units and Model

The conversion gain is expressed in electrons per digital number (`e-/DN`).
For each pixel, the expected electron count is:

```text
expected_electrons = signal_electrons * prnu_gain * illumination_gain
                   + dark_current_e_per_s * exposure_time_s
```

When shot noise is enabled, the collected charge is sampled from a Poisson
distribution with this expectation. Gaussian read noise is then added in
electrons. Conversion to digital numbers follows:

```text
dn = offset_dn + fixed_offset_map_dn
    + collected_electrons / conversion_gain_e_per_dn
```

Dead pixels are set to zero and hot pixels to the configured saturation value.
The result is clipped, rounded to the nearest DN, and stored in the smallest
unsigned dtype that supports the configured ADC bit depth.

PRNU uses a strictly positive lognormal gain map whose population mean is one
and whose relative standard deviation is `prnu_fraction`. Flat-field
illumination is a separate unit-mean map: optional radial vignetting and soft
elliptical dust shadows model optical non-uniformity without reclassifying it
as sensor PRNU. This distinction is retained in `CameraSimulationTruth`, even
though a relative characterization of frames alone necessarily observes their
product.

The fixed offset map sums signed pixel DSNU, row-constant and column-constant
readout patterns, and an optional lower-right amplifier glow. Their amplitudes
are expressed in DN. Negative pixel/row/column values represent samples below
the sensor-wide offset; this remains an offset-pattern model, not a complete
physical model of dark-current non-uniformity. All structured components are
disabled by default, preserving the original uniform-field model unless they
are requested explicitly.

The defective-pixel fraction is converted to the nearest whole number of
pixels. That count may be zero for a sufficiently small image or fraction. The
selected pixels are divided as evenly as possible into dead and hot masks; an
odd remainder becomes one additional hot pixel.

## Reproducibility

`numpy.random.SeedSequence` derives independent generators for PRNU, pixel
DSNU, defective-pixel selection, frame noise, row/column patterns, and
illumination structure. For a fixed shape and seed, static maps remain
unchanged when the frame count, exposure, or signal level changes. The returned
arrays are read-only so that a result retains its original truth. Bitwise
reproducibility is asserted for repeated runs using the same supported NumPy
random implementation; serialized test fixtures should record the NumPy
version when cross-environment replay matters.

`CameraSimulationTruth` contains:

- the original seed;
- PRNU gain, flat-field illumination gain, and total fixed-offset maps;
- expected electron and DN maps before defect overrides, clipping, and
    quantization;
- disjoint dead-pixel and hot-pixel masks.

## Limitations

Vignetting, dust, banding, and glow are controlled geometric/statistical
surrogates, not a ray-traced optical system or an electronic circuit model.
The simulator does not currently include photon wavelength, quantum
efficiency, charge transfer effects, temporal drift, nonlinear response,
blooming, or calibrated radiometric quantities. Future characterization code
must not infer support for those effects from these synthetic frames.
