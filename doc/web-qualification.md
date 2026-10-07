# DataLab-Web Qualification

The Camera Web adapter is tested against one explicit browser matrix:

| Component              | Version |
| ---------------------- | ------- |
| DataLab-Web            | 0.9.0   |
| Pyodide                | 0.26.4  |
| Camera plugin          | 0.2.0   |
| Relative-DN recipe     | 1.1.0   |
| Photon transfer recipe | 1.0.0   |
| Dark-current recipe    | 1.0.0   |

The photon transfer and dark-current recipes are qualified by DataLab-Web's `tests/e2e/application_methods.spec.ts`: each generated example is opened through its deep link, its recipe is started from the Applications dialog, and the created outputs must appear in the visible object tree without page errors. DataLab-Web's Python contracts run the same pairs through the generic host and require unambiguous slot bindings. The detailed visible and memory gates below apply to the relative-DN recipe.

## Visible workflow gate

The Playwright gate boots DataLab-Web's worker-hosted Pyodide runtime, opens
the packaged `camera_quickstart.h5`, and executes the shared headless recipe on
the imported campaign. The Web host transactionally commits all ten outputs,
attaches the metrics `TableResult` to the response anchor, and persists one
`RecipeRunRecord` on every output.

The browser test then uses the normal React object tree and side panel to
require all of the following visible evidence:

- a Plotly line trace titled **Camera response**;
- a decoded, non-blank, non-uniform raster titled **Relative PRNU-like map**;
- the **Relative Camera characterization metrics** table, including the
  response-slope row.

The test also injects a failure during the second cross-panel insertion and
checks that every object and group from the partial commit is removed.

## Pyodide memory budget

Memory is measured after loading the quickstart and running Python garbage
collection, so Pyodide startup and package installation are outside the
increment. The recipe must satisfy both limits:

- incremental WASM linear heap: at most 64 MiB;
- retained signal/image arrays: at most three times the input-array bytes.

The reference Windows/Chromium run on 2026-08-11, using the structured 96 x 128
quickstart frames, grew the WASM heap by 0.00 MiB and retained 0.39 MiB of
output arrays, or 0.84 times the input-array
bytes. The automated thresholds remain deliberately above this observation to
allow WASM page rounding and browser variation while still detecting an
unbounded working set.

## Scope

This gate qualifies browser distribution, execution, host commit, visible
rendering, and demo-workspace memory. It does not establish EMVA 1288
compliance, calibrated metrology, scientific validation on real cameras, or a
general-purpose Applications user experience. After this evidence was
recorded, a separate reviewed manifest change advanced `web_status` from
`untested` to `verified`; that status applies only to the version matrix above.
