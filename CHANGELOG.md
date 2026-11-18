# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-11-18

Camera settings, axes and result tables now use LSB (one ADC step) instead of DN. This label change does not alter numeric values or saved parameter names.

- All three methods use the declared native ADC range rather than assuming a 12-bit camera. Imports with ambiguous units, coding or frame roles need an explicit declaration; inconsistent geometries cannot be analyzed together. Native conversion does not modify the source images.
- Relative characterization and photon transfer use matching dark exposures when available. They distinguish noise in the reference dark from an estimate of electronic read noise. The simulator can acquire reference darks at each exposure or a zero-exposure bias.
- Photon transfer no longer treats a variance peak as proof of saturation. It reports observed clipping, a reproducible response plateau, a lower bound or an indeterminate result. Clipped levels have no measured SNR. Raw temporal variance remains the default; an optional comparison with centered frame pairs shows how common-mode fluctuations affect the gain estimate.
- Dark-current maps now distinguish a hot pixel, a pixel stuck at one ADC rail and a pixel whose slope cannot be measured. The summary identifies its pixel population. A separate estimate of intrinsic spatial dispersion, with an uncertainty interval when supported, complements the observed spread of the measured slopes.

Recipe IDs and versions stay the same for plugin 0.3.0: relative characterization **1.1.0**, photon transfer **1.0.0**, and dark current **1.0.0**. Saved results remain readable without recalculation. To reproduce a historical analysis, use the plugin version recorded in its provenance with the original inputs and parameters. Rerunning a 0.2.1 analysis with 0.3.0 is a new calculation: saturation decisions and dark-pixel classifications can differ even when the recipe version matches.

### Requirements

The minimum requirements are unchanged: Python 3.10, DataLab 1.4, NumPy 1.22 and SciPy 1.10.1.

## Earlier releases

First version of the Camera & Detector Characterization plugin.

Methods:

- Relative characterization in LSB: response curve, temporal noise, linearity, saturation onset, dynamic range, DSNU-like and PRNU-like maps, candidate pixels, profiles and distributions, with a metrics table.
- Photon transfer curve: conversion gain, read noise, saturation capacity, dynamic range and SNR.
- Dark current and hot pixels: dark-current and offset maps, non-uniformity, hot pixels and an indicative gain, from a dark ramp.
- Input checks before every run, with clear diagnostics. Frames are assigned to the dark or flat slots from their exposure time and optional frame role.

Tools and examples:

- Scientific camera simulator, with a live view and acquisitions of dark and flat frames ready for the methods.
- Packaged quickstart campaign, and generated photon transfer and dark-ramp examples, all validated against the simulator truth.
- Deterministic synthetic camera model with ground-truth maps.
- Guide to set the exposure time and frame role on your own frames.

DataLab integration:

- DataLab Desktop: plugin menu, Applications panel, welcome page tiles, and results saved with their provenance in DataLab workspaces.
- DataLab-Web: the same methods; version 0.2.0 was verified with DataLab-Web 0.9.0 and Pyodide 0.26.4. The 0.2.1 candidate remains unverified with DataLab-Web 0.11.0.

Quality:

- Bounded memory: statistics process a configurable number of frames at a time.
- Alpha gate (tests and memory budget), and a Stable gate that requires a real camera campaign and an independent review.
