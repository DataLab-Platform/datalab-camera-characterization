# Scientific Camera Simulator

The Camera application includes a simulated scientific camera. It is a DataLab tool: open it from the Camera page of the **Applications** catalog (**Tools** section), or from the **Plugins > Camera & Detector Characterization** menu of the image panel. It works the same way in DataLab Desktop and DataLab-Web.

The window shows a live view on the left and the camera settings on the right. Every change of a setting refreshes the view. **Live** refreshes it continuously, with new noise at every frame, like the viewer of a real camera. **Acquire** adds the frames to the workspace, in a new group per acquisition; the window stays open for the next acquisition.

## Settings

The settings are grouped in four tabs.

- **Acquisition.** Single exposure, or a sequence of exposure times (in ms, separated by commas). Number of frames per exposure. Shutter open (flat frames) or closed (dark frames). With the shutter open, dark frames can be added at the longest exposure time.
- **Illumination.** Photoelectron rate per pixel, vignetting and dust shadows.
- **Sensor.** Frame size, ADC resolution, conversion gain, read noise, offset, PRNU, DSNU, row and column patterns, defective pixels, and the serial number.
- **Dark current.** Dark current, its non-uniformity, hot pixels and amplifier glow.

The ADC saturates at its largest code, 2^bits - 1 DN. The live view uses this full range, so the image gets brighter as the exposure grows, and saturated pixels stand out. Below the view, a summary gives the mean and standard deviation of the frame, and the share of saturated pixels.

The serial number seeds the sensor: PRNU, DSNU, defects and hot pixels stay the same from one acquisition to the next, as on a real camera. Change it to simulate another camera of the same model. Each frame draws new temporal noise.

One acquisition is limited to 20 megapixels (all frames together), which keeps DataLab-Web within the browser memory.

## Acquired Frames

Frames are named like the generated examples, for instance `Dark 136 ms 01` or `Flat 10 ms 02`. Each frame carries the metadata the Camera methods expect:

- `plugin.org.datalab.camera-characterization.frame_role`: `dark` or `flat`;
- `plugin.org.datalab.camera-characterization.exposure_time_s`: the exposure time, in seconds;
- `plugin.org.datalab.camera-characterization.synthetic` and `.simulation_seed`, which record the simulated origin.

So an acquisition can be analyzed right away:

| Acquisition | Method |
| --- | --- |
| Exposure sequence, shutter open, with dark frames (the default sequence) | Photon transfer curve, relative camera characterization |
| Exposure sequence with the shutter closed, for instance `500, 1000, 2000, 4000, 8000` ms (raise the dark current to a few tens of e⁻/s to see it clearly) | Dark current and hot pixels |

## Limits

The simulator uses the model described in [`simulation.md`](simulation.md), with the same limitations: no wavelength or quantum efficiency, no charge transfer, temporal drift, nonlinear response or blooming, and no calibrated radiometry. It helps learning the methods and checking a workflow; it does not replace measurements of a real camera.
