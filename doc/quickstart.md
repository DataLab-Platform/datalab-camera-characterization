# Desktop Quickstart

The packaged quickstart produces a first relative-DN Camera characterization
without writing Python. It uses a deterministic synthetic campaign containing
four dark frames and four flat exposure levels with four frames per level. All
frames are 96 x 128 pixels and share one static synthetic sensor.

The dark frames represent shutter-closed readout and expose bias, pixel/row/
column fixed-pattern offsets, lower-right amplifier glow, read noise, and
dead/hot pixels. The flat frames represent an illuminated uniform field, not a
scene: exposure-dependent photocharge is modulated by vignetting, three soft
dust shadows, PRNU, shot noise, and the same sensor defects. Metadata records
the frame role and the enabled physical components.

## Run the Example

1. Start DataLab with the Camera & Detector Characterization plugin installed.
2. Choose **Plugins > Camera & Detector Characterization > Open quickstart
   example**.
3. Confirm replacement if the current workspace already contains objects. The
   20 example images are loaded in five groups and selected automatically.
4. Choose **Plugins > Camera & Detector Characterization > Run camera
   characterization...**.
5. Review the dark/flat assignments and recipe parameters, then accept both
   dialogs.

Titles beginning with `Dark` are preassigned in the compact **Dark frames**
checklist. Unchecked images are assigned to Flat, so every selected image has
exactly one role before execution.

## Expected Result

The Signal panel receives one response curve. The Image panel keeps the 20
inputs and receives a mean dark image and a mean flat image. The response curve
anchors a table containing the response slope, intercept, temporal noise,
linearity residual, maximum unsaturated signal, relative dynamic range, and
selected flat exposure.

The example and current workflow are alpha, synthetic, relative-DN tools. They
do not claim EMVA 1288 compliance, calibrated radiometry, or a normative camera
assessment. The visible structures are pedagogical deterministic surrogates,
not evidence that the simulator reproduces a particular camera or optical
bench.

## Regenerate the Resource

Maintainers may regenerate the native DataLab workspace from the versioned
simulator parameters:

```powershell
$env:PYTHONPATH="src;../DataLab;../Sigima;../guidata;../PlotPy;../PythonQwt"
python scripts/generate_quickstart.py
```

The generated resource is
`src/datalab_camera_characterization/examples/camera_quickstart.h5`.