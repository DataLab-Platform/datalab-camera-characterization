# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

First version of the Camera & Detector Characterization plugin.

Methods:

- Relative characterization in DN: response curve, temporal noise, linearity, saturation onset, dynamic range, DSNU-like and PRNU-like maps, candidate pixels, profiles and distributions, with a metrics table.
- Photon transfer curve: conversion gain, read noise, saturation capacity, dynamic range and SNR.
- Dark current and hot pixels: dark-current and offset maps, non-uniformity, hot pixels and an indicative gain, from a dark ramp.
- Input checks before every run, with clear diagnostics. Frames are assigned to the dark or flat slots from their exposure time and optional frame role.

Tools and examples:

- Scientific camera simulator, with a live view and acquisitions of dark and flat frames ready for the methods.
- Packaged quickstart campaign, and generated photon transfer and dark-ramp examples, all validated against the simulator truth.
- Deterministic synthetic camera model with ground-truth maps.
- Guide to set the exposure time and frame role on your own frames.

DataLab integration:

- DataLab Desktop: plugin menu, Applications catalog, welcome page tiles, and results saved with their provenance in DataLab workspaces.
- DataLab-Web: the same methods, verified for DataLab-Web 0.9.0 and Pyodide 0.26.4.

Quality:

- Bounded memory: statistics process a configurable number of frames at a time.
- Alpha gate (tests and memory budget), and a Stable gate that requires a real camera campaign and an independent review.
