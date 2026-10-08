# Getting Started

[← Documentation index](README.md)

This page shows where the plugin appears in DataLab, how to run the quickstart, and how to prepare your own frames. DataLab Desktop and DataLab-Web work the same way.

![DataLab with the relative PRNU-like map of the quickstart campaign](images/overview.png)

## Where to Find the Plugin

- **Plugins > Camera & Detector Characterization** menu of the image panel: open the examples, run the methods and open the [camera simulator](simulator.md).
- **Applications** catalog, opened by the **Camera & Detector Characterization** tile of the welcome page. It lists each method with the inputs it expects, tells whether the current selection can run it, and offers its examples. **Try with this example** opens an example, prefills the parameters and runs the method.
- **Open quickstart example** tile of the welcome page.

## Run the Quickstart

1. Choose **Plugins > Camera & Detector Characterization > Open quickstart example**. DataLab loads 20 images in five groups and selects them. If the workspace is not empty, it asks before replacing it.
2. Choose **Run camera characterization...**.
3. Accept the parameters.

The plugin assigns each image to the dark or flat frames from its metadata. DataLab asks you only when the assignment is ambiguous or the campaign is invalid.

The quickstart is a synthetic campaign of 96 × 128 frames from one sensor:

- 4 dark frames, shutter closed: bias, row and column banding, amplifier glow in the lower-right corner, read noise, dead and hot pixels;
- 4 flat levels at 5, 10, 20 and 40 ms, with 4 frames each: a uniform illuminated field with vignetting, three dust shadows, PRNU and shot noise.

DataLab then adds:

- in the signal panel, the response curve with its metrics table, the row and column profiles and two distributions;
- in the image panel, the mean dark and flat images, and the DSNU-like, PRNU-like and candidate-pixel maps.

[Relative characterization in DN](relative-dn.md) explains each result.

## Other Examples

| Menu item | Example | Methods |
| --- | --- | --- |
| **Open photon transfer example** | 16 exposure levels up to ADC saturation | [Photon transfer curve](photon-transfer.md), [relative characterization](relative-dn.md) |
| **Open dark-ramp example** | Dark frames from 0.5 s to 8 s | [Dark current and hot pixels](dark-current.md) |

Both examples are generated in memory. Run them with **Run photon transfer analysis...** and **Run dark-current analysis...**.

## Use Your Own Frames

The methods read two metadata entries on each image:

| Key | Value | Use |
| --- | --- | --- |
| `plugin.org.datalab.camera-characterization.exposure_time_s` | Exposure time in seconds, finite and non-negative | Required on flat frames (relative-DN and photon transfer) and on dark frames (dark current) |
| `plugin.org.datalab.camera-characterization.frame_role` | `dark` or `flat` | Optional. Without it, frames with an exposure time are flat frames |

Set them with **Edit > Metadata > Add metadata...**. While the plugin is active, the **Known keys** list offers both keys. When a key is missing, the method status in the **Applications** catalog points to this dialog.

To read the exposure time from titles such as `Flat 5 ms 01`, select the frames and set:

| Field | Value |
| --- | --- |
| Metadata key | `plugin.org.datalab.camera-characterization.exposure_time_s` |
| Value pattern | `{title}` |
| Extraction pattern | `([\d.]+)\s*ms` |
| Conversion | Float |
| Scale factor | `0.001` |

`Flat 5 ms 01` gives `0.005`. The preview shows each value before you click OK. For titles in seconds such as `Dark 0.5 s 01`, use the extraction pattern `([\d.]+)\s*s\b` and a scale factor of `1`.

To set the frame role, select the dark frames, then set the key `plugin.org.datalab.camera-characterization.frame_role`, the value pattern `dark` and the String conversion. Repeat with `flat` for the flat frames. Set the role when dark frames carry an exposure time, as in a dark ramp: otherwise, the relative-DN and photon transfer methods take them as flat frames.
