# Preparing Your Own Frames

The Camera methods read two metadata entries on the images:

| Key | Value | Use |
| --- | --- | --- |
| `plugin.org.datalab.camera-characterization.exposure_time_s` | Exposure time in seconds, a finite non-negative number | Required on flat frames (relative-DN and photon transfer methods) and on dark frames (dark-current method) |
| `plugin.org.datalab.camera-characterization.frame_role` | `dark` or `flat` | Optional hint: without it, frames carrying an exposure time are taken as flat frames |

DataLab, on Desktop and on the Web, sets them with **Edit > Metadata > Add metadata...**. When a key is missing, the status of the method in the **Applications** window points to this dialog, and the status is updated as soon as the metadata change. In the dialog, the **Known keys** list offers the keys above while the Camera plugin is active: choosing one copies it into **Metadata key**.

## Exposure Time Read From the Titles

For flat frames titled like `Flat 5 ms 01`, select them and set:

| Field | Value |
| --- | --- |
| Metadata key | `plugin.org.datalab.camera-characterization.exposure_time_s` |
| Value pattern | `{title}` |
| Extraction pattern | `([\d.]+)\s*ms` |
| Conversion | Float |
| Scale factor | `0.001` |

The extraction pattern finds the number written before `ms`, and the scale factor converts milliseconds into seconds: `Flat 5 ms 01` gives `0.005`. The preview shows the value of every selected frame before you click OK. Frames whose title does not match are left unchanged, unless **If no match** is set to report an error.

For dark ramps titled like `Dark 0.5 s 01`, use the extraction pattern `([\d.]+)\s*s\b` with a scale factor of `1`.

## Frame Roles

Select the dark frames and set:

| Field | Value |
| --- | --- |
| Metadata key | `plugin.org.datalab.camera-characterization.frame_role` |
| Value pattern | `dark` |
| Conversion | String |

Repeat with `flat` for the flat frames. The role is recommended when dark frames also carry an exposure time, as in a dark-current campaign: without it, the relative-DN and photon transfer methods would take them as flat frames.
