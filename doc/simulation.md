# Deterministic Camera Simulation

The simulator produces a stack of unsigned integer camera frames and the exact
static/noiseless ground truth used to generate them. It is intended for testing
future relative characterization algorithms, not for claiming a calibrated or
EMVA 1288-compliant camera model.

## Units and Model

The conversion gain is expressed in electrons per digital number (`e-/DN`).
For each pixel, the expected electron count is:

```text
expected_electrons = signal_electrons * prnu_gain
                   + dark_current_e_per_s * exposure_time_s
```

When shot noise is enabled, the collected charge is sampled from a Poisson
distribution with this expectation. Gaussian read noise is then added in
electrons. Conversion to digital numbers follows:

```text
dn = offset_dn + dsnu_dn + collected_electrons / conversion_gain_e_per_dn
```

Dead pixels are set to zero and hot pixels to the configured saturation value.
The result is clipped, rounded to the nearest DN, and stored in the smallest
unsigned dtype that supports the configured ADC bit depth.

PRNU uses a strictly positive lognormal gain map whose population mean is one
and whose relative standard deviation is `prnu_fraction`. DSNU uses a signed
normal offset map centered on zero, with `dsnu_dn` as its standard deviation.
Negative DSNU values represent pixels below the sensor-wide offset; DSNU is not
treated as an absolute dark signal. The simulated DSNU is therefore an
offset-pattern model, not a complete physical model of dark-current
non-uniformity.

The defective-pixel fraction is converted to the nearest whole number of
pixels. That count may be zero for a sufficiently small image or fraction. The
selected pixels are divided as evenly as possible into dead and hot masks; an
odd remainder becomes one additional hot pixel.

## Reproducibility

`numpy.random.SeedSequence` derives independent generators for PRNU, DSNU,
defective-pixel selection, and frame noise. For a fixed shape and seed, static
maps remain unchanged when the frame count, exposure, or signal level changes.
The returned arrays are read-only so that a result retains its original truth.
Bitwise reproducibility is asserted for repeated runs using the same supported
NumPy random implementation; serialized test fixtures should record the NumPy
version when cross-environment replay matters.

`CameraSimulationTruth` contains:

- the original seed;
- PRNU gain and DSNU offset maps;
- expected electron and DN maps before defect overrides, clipping, and
    quantization;
- disjoint dead-pixel and hot-pixel masks.

## Limitations

The model does not currently include photon wavelength, quantum efficiency,
pixel response correlations, charge transfer effects, temporal drift,
nonlinear response, blooming, or calibrated radiometric quantities. Future
characterization code must not infer support for those effects from these
synthetic frames.
