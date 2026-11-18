# Real-camera acquisition protocol — blank worksheet

Complete the design and acceptance criteria before examining the candidate results. After capture, append the observed conditions, deviations and exclusions. Identify the dated design revision in the final protocol. This worksheet is not evidence of an acquisition.

| Record before capture | Planned value, source and tolerance |
| --- | --- |
| Campaign ID, operator, date, site, sensor/serial or justified redaction, data access/license | |
| Candidate build and methods, camera firmware, readout rate, analogue gain, offset, shutter, ROI/origin, binning and pixel pitch | |
| ADC active bits, native step and rails, alignment/packing, unit and endianness; how raw linear output and disabled corrections were verified | |
| Light source, geometry, optics, aperture, diffuser, wavelength/band, uniformity map, reference monitor and calibration | |
| Temperature probe/location and calibration, warm-up, sampling period, stability criterion and maximum permitted drift | |
| Exposure ladder and units, measured timing, minimum repetitions at each pose, order/interleaving, recovery after saturation | |
| Short bias series, matched closed-shutter series, illuminated series through clipping/plateau, separate dark ramp as applicable | |
| Independent run IDs and restart conditions; reserved frames for masks or independent slope fits | |
| Per-method estimators, fit ranges, population/denominator, exclusions and diagnostics; acceptance limits with units, uncertainty and independent reference | |

| Run and frame IDs | UTC time, role, exposure and gain | Sensor/ambient temperatures | Monitor reading, spatial uniformity | Raw location, deviations or exclusion reason |
| --- | --- | --- | --- | --- |
| | | | | |

Store original unprocessed frames, timestamps, thermal and illumination logs, calibration records, frame ledger and any numerical reference inputs together in the hashed campaign artifact. Record actual sample counts per run and exposure, not only totals. Document every conversion on a copy, rejected acquisition and rerun. Identify the final dataset and protocol by digest in each method report.
