# Relative-DN Recipe Contract

The plugin registers one versioned DataLab recipe:

```text
org.datalab.camera-characterization:relative-dn-characterization
```

The recipe is headless. It accepts Sigima image objects, calls the portable
Camera core, and returns a `RecipeOutcome`. It does not mutate a DataLab
workspace or import GUI modules.

## Inputs

The descriptor declares two required image slots with `many` cardinality:

- `dark_frames`: individual dark acquisitions;
- `flat_frames`: individual uniform-illumination acquisitions.

Every image contains one 2D frame. Flat images require the namespaced metadata
key exported as `EXPOSURE_TIME_METADATA_KEY`:

```text
plugin.org.datalab.camera-characterization.exposure_time_s
```

Its value is a finite non-negative number in seconds. Flat frames with equal
values form one exposure series; series are sorted by increasing exposure.
The core then validates shape, dtype, finitude, frame counts, exposure order,
saturation, and the number of usable levels before calculating outputs.

## Parameters

`CameraRecipeParameters` exposes minimum frame and flat-level counts,
saturation level and warning fraction, an optional temporal-variance warning
threshold, and the aggregation block size. A zero maximum temporal variance
disables that optional warning threshold. These settings are workflow criteria,
not normative camera acceptance limits.

## Outcome

The recipe produces three named scientific objects:

| Output ID | Type | Meaning |
| --- | --- | --- |
| `response` | Signal | Mean dark-subtracted signal versus exposure; anchor object |
| `mean_dark` | Image | Mean of all dark frames |
| `mean_flat` | Image | Mean of the highest-exposure level retained by the linear fit |

The `metrics` result is a non-normative `TableResult` whose `anchor_id` is
`response`. It includes response slope and intercept, dark temporal noise,
maximum absolute fitted residual, maximum unsaturated signal, relative dynamic
range, selected flat exposure, and saturation onset when detected. Every status
is initially `Not assessed`; no implicit pass/fail standard is claimed.

Mean images preserve the source coordinate calibration, axis labels, and units.
They deliberately do not copy acquisition-specific metadata from an arbitrary
input frame. Stable output-role metadata identifies computed objects. The
selected flat exposure is recorded on `mean_flat`.

## Diagnostics And Commit

Missing or invalid exposure metadata raises `RecipeValidationError`. Structured
core errors raise `CameraCharacterizationError` before an outcome exists, so a
recipe runner cannot commit partial outputs. Core warnings are converted to
immutable `RecipeDiagnostic` values in the successful outcome.

On Desktop, `RecipeRunner` attaches `metrics` to `response`, commits the signal
and images transactionally, and stores the same `RecipeRunRecord` on every
output. That record provides campaign-level input/output UUID provenance;
workspace mutation and rollback remain host responsibilities.

The Desktop adapter constructs and edits the descriptor's
`CameraRecipeParameters` with the DataLab main window as dialog parent. This
parameter form is reused by **Run camera characterization...**. The action is
available for selections of at least six images, the mathematical minimum for
two dark frames and two two-frame flat levels under the current parameter
bounds.

Before execution, a transient DataSet presents one required dark/flat choice
per selected image. Titles containing `dark` are prefilled as dark and all
others as flat, but these values remain visible and editable; title matching is
only a UI convenience and is not used by the recipe or scientific core. The
accepted assignments are passed directly as `dark_frames` and `flat_frames`.
Input metadata is not modified. Cancellation at either form produces no
outputs, and structured execution errors are displayed before returning to the
unchanged workspace.

## Memory Scope

The workflow passes sequences of existing 2D image arrays to the core instead
of building complete 3D stacks. Value scans, float conversion, saturation
masks, and statistics materialize at most `aggregation_block_size` frames at a
time. The input `ImageObj` arrays and 2D result arrays remain resident.
Representative 2048 x 2048 memory/time measurements are documented in
[`validation.md`](validation.md).
