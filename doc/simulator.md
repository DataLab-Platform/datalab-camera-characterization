# Camera Simulator

[← Documentation index](README.md)

The **Scientific camera simulator** shows a live view of a synthetic camera next to its settings. It acquires dark and flat frames that the methods can analyze right away. Use it to learn the methods and to check a workflow: it does not replace a real camera.

![Scientific camera simulator](images/simulator.png)

## Use the Simulator

Open it from the **Tools** section of the Camera page of the **Applications** catalog, or with **Plugins > Camera & Detector Characterization > Scientific camera simulator...** in the image panel. It works the same way in DataLab Desktop and DataLab-Web.

- Every change of a setting refreshes the view. Below the view, a summary gives the mean, the standard deviation and the share of saturated pixels.
- **Live** refreshes the view continuously, with new noise at every frame.
- **Acquire** adds the frames to the workspace, in a new group. The window stays open.

## Settings

| Tab | Settings |
| --- | --- |
| Acquisition | Single exposure or exposure sequence (ms, comma-separated), frames per exposure, shutter open (flat frames) or closed (dark frames), dark frames added at the longest exposure |
| Illumination | Photoelectron rate per pixel, vignetting, dust shadows |
| Sensor | Frame size, ADC resolution, conversion gain, read noise, offset, PRNU, DSNU, row and column patterns, defective pixels, serial number |
| Dark current | Dark current, its non-uniformity, hot pixels, amplifier glow |

- The ADC saturates at 2^bits − 1 DN. The view uses this full range: the image gets brighter with the exposure.
- The serial number seeds the sensor. PRNU, DSNU, defects and hot pixels stay the same between acquisitions, as on a real camera. Each frame draws new temporal noise.
- One acquisition holds at most 20 megapixels, all frames together, to fit in the browser memory of DataLab-Web.

## Acquired Frames

Frames are named like `Dark 136 ms 01` or `Flat 10 ms 02`. They carry these metadata keys, under `plugin.org.datalab.camera-characterization.`:

- `frame_role`: `dark` or `flat`;
- `exposure_time_s`: the exposure time in seconds;
- `synthetic` and `simulation_seed`: the simulated origin.

| Acquisition | Methods |
| --- | --- |
| Default exposure sequence, shutter open, with dark frames | Photon transfer curve, relative characterization |
| Exposure sequence with the shutter closed, for instance `500, 1000, 2000, 4000, 8000` ms, with a dark current of a few tens of e⁻/s | Dark current and hot pixels |

## Model

For each pixel, the simulator draws the collected electrons from a Poisson law, adds Gaussian read noise, then converts to DN:

```text
expected_electrons = signal_electrons * prnu_gain * illumination_gain + dark_current_e_per_s * exposure_time_s
dn = offset_dn + fixed_offset_map_dn + collected_electrons / conversion_gain_e_per_dn
```

Dead pixels are then set to 0 and hot pixels to saturation. The result is clipped, rounded and stored in the smallest unsigned integer type for the ADC resolution.

| Component | Model |
| --- | --- |
| PRNU | Lognormal gain map with a mean of 1 |
| Illumination | Map with a mean of 1: radial vignetting and soft dust shadows, kept apart from PRNU in the truth |
| Fixed offset | Pixel DSNU, row and column patterns, amplifier glow in DN in the lower-right corner |
| Dark current | Optional non-uniformity, dark hot pixels, and amplifier glow in e⁻/s that grows with the exposure |
| Defects | Dead and hot pixels, in equal numbers |

The same parameters and seed give identical frames. Static maps do not change with the frame count, the exposure or the signal. `noise_stream` draws independent noise on the same sensor, as in a real campaign. The returned `CameraSimulationTruth` holds the seed, the PRNU, illumination, offset and dark-current maps, the expected maps before defects and clipping, and the defect masks.

In Python:

```python
from datalab_camera_characterization.core import (
    CameraSimulationParameters,
    simulate_camera_frames,
)

result = simulate_camera_frames(
    CameraSimulationParameters(shape=(256, 320), frame_count=10, seed=42)
)
frames, truth = result.frames_dn, result.truth
```

## Limits

Vignetting, dust, banding and glow are simple geometric and statistical models, not optics or electronics. The simulator has no wavelength or quantum efficiency, no charge transfer, temporal drift, nonlinear response or blooming, and no calibrated radiometry.
