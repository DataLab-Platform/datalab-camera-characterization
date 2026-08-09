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
threshold, the aggregation block size, a candidate-pixel sigma threshold, and
the spatial histogram bin count. A zero maximum temporal variance disables
that optional warning threshold. These settings are workflow criteria, not
normative camera acceptance limits.

## Outcome

Recipe version 1.1.0 produces ten named scientific objects:

| Output ID | Type | Meaning |
| --- | --- | --- |
| `response` | Signal | Mean dark-subtracted signal versus exposure; anchor object |
| `mean_dark` | Image | Mean of all dark frames |
| `mean_flat` | Image | Mean of the highest-exposure level retained by the linear fit |
| `dsnu_like_map` | Image | Centered mean dark image in DN |
| `prnu_like_map` | Image | Fractional deviation of the dark-corrected flat image |
| `candidate_pixel_map` | Image | Union of pixels beyond either spatial sigma threshold |
| `prnu_row_profile` | Signal | Row means of the PRNU-like map |
| `prnu_column_profile` | Signal | Column means of the PRNU-like map |
| `dsnu_distribution` | Signal | DSNU-like histogram counts versus DN |
| `prnu_distribution` | Signal | PRNU-like histogram counts versus fractional deviation |

The `metrics` result is a non-normative `TableResult` whose `anchor_id` is
`response`. It includes response slope and intercept, dark temporal noise,
maximum absolute fitted residual, maximum unsaturated signal, relative dynamic
range, selected flat exposure, spatial non-uniformities, candidate count and
fraction, and saturation onset when detected. Every status is initially `Not
assessed`; no implicit pass/fail standard is claimed.
Each row uses Sigima's explicit `NO_ROI` marker because the metrics summarize
the full campaign rather than one ROI. This representation also remains
unambiguous through DataLab's native HDF5 metadata serialization.

Mean images preserve the source coordinate calibration, axis labels, and units.
They deliberately do not copy acquisition-specific metadata from an arbitrary
input frame. Stable output-role metadata identifies computed objects. The
selected flat exposure is recorded on `mean_flat`. Candidate-threshold metadata
is recorded on `candidate_pixel_map`. Profiles use the source image's physical
row or column coordinates.

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

## Packaged Quickstart

The Desktop plugin declares the native workspace
`examples/camera_quickstart.h5` through `PluginExample`. The resource is
resolved with `importlib.resources`, so opening it is independent of the
working directory and works from an installed wheel. The dedicated action
checks DataLab's memory state, confirms before replacing a non-empty workspace,
loads the example, and selects its 20 images. The normal role and parameter
forms then drive the same registered recipe and transactional runner used for
user campaigns.

The workspace is generated by `scripts/generate_quickstart.py` from fixed
simulator parameters. It contains four dark frames and four four-frame flat
series at 5, 10, 20, and 40 ms. No expected result is precomputed in the file;
the visible quickstart path exercises the production workflow.

## Distribution And Persistence Gate

The integration suite builds the wheel with PEP 517, installs it without
dependencies into a temporary target, and loads the declared plugin entry
point while the checkout is not the current directory. The packaged example
size and deterministic SHA-256 are checked from that installed target.

A Desktop lifecycle test verifies that hot reload replaces the plugin instance
while retaining exactly one Camera menu and an enabled quickstart action in an
empty workspace. A native HDF5 round-trip then verifies all quickstart input
UUIDs, all ten output UUIDs, each shared `RecipeRunRecord`, and the metrics
table attached to the response anchor.

## Memory Scope

The workflow passes sequences of existing 2D image arrays to the core instead
of building complete 3D stacks. Value scans, float conversion, saturation
masks, and statistics materialize at most `aggregation_block_size` frames at a
time. Retained mean images use the mean-only core path. The input `ImageObj`
arrays and 2D result maps remain resident.
Representative 2048 x 2048 memory/time measurements are documented in
[`validation.md`](validation.md).
