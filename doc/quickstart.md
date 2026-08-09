# Desktop Quickstart

The packaged quickstart produces a first relative-DN Camera characterization
without writing Python. It uses a deterministic synthetic campaign containing
four dark frames and four flat exposure levels with four frames per level.

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

Titles beginning with `Dark` are preassigned as dark frames. Every other image
is preassigned as a flat frame. These assignments remain explicit and editable
before execution.

## Expected Result

The Signal panel receives one response curve. The Image panel keeps the 20
inputs and receives a mean dark image and a mean flat image. The response curve
anchors a table containing the response slope, intercept, temporal noise,
linearity residual, maximum unsaturated signal, relative dynamic range, and
selected flat exposure.

The example and current workflow are alpha, synthetic, relative-DN tools. They
do not claim EMVA 1288 compliance, calibrated radiometry, or a normative camera
assessment.

## Regenerate the Resource

Maintainers may regenerate the native DataLab workspace from the versioned
simulator parameters:

```powershell
$env:PYTHONPATH="src;../DataLab;../Sigima;../guidata;../PlotPy;../PythonQwt"
python scripts/generate_quickstart.py
```

The generated resource is
`src/datalab_camera_characterization/examples/camera_quickstart.h5`.