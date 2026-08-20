# TASK-h1_telemetry_m4 — M4 telemetry + anomaly detection + AWS sync integration

**Status**: DONE (unit-gated + verified live in sim) · **Date**: 2026-08-18 → 2026-08-19
Commits: `5179e28`, `08e7a34`, `3d19a48`, `9ec057c`

## Summary

M4 delivers the telemetry lifecycle node (CSV + JSONL logging at 1 Hz),
threshold + z-score anomaly detection with `/h1/alerts` and `/anomaly_flag`,
and the AWS sync integration (S3/DynamoDB/SNS) via `h1_aws_sync` (M4.4).
47 telemetry tests + 46 aws_sync tests, live CRITICAL fall_risk alert observed.

## What was built

| Component | Detail |
|---|---|
| `ring_buffer.py` — `RingBuffer`, `RateCounter` | Fixed-capacity deque; Hz from N=100 stamp window (guards <2 samples / zero span / dupes) |
| `body_state.py` | Quaternion → pitch/roll deg (rotation matrix, zero-norm safe); `fall_risk_score` heuristic (0..1, linear ramp 20→60 deg) |
| `thresholds.py` — `ThresholdEvaluator` | `_min`/`_max` bounds on bare metric keys; yaml loader; unknown-suffix keys dropped |
| `anomaly.py` — `AnomalyScorer` | Rolling-window z-score (window 50, \|z\|>3.5), constant-window deviation → +inf; `isolation_forest_score()` documented stub (real IF trained offline, later) |
| `writer.py` — `SampleWriter` | CSV + JSONL append, dir auto-create, header once, stable column order |
| `telemetry_node.py` | LifecycleNode: configure (params `thresholds_yaml`/`data_dir`/`sample_period`, use_sim_time true) → activate (BEST_EFFORT subs `/joint_states`, `/h1/odometry`, `/imu`; 1 Hz timer); publishes `/h1/telemetry` (TelemetrySample), `/h1/alerts` (Alert), `/anomaly_flag`; CPU via /proc/loadavg, RAM via /proc/meminfo; throttled no-data logging |
| `config/thresholds.yaml` | 8 rules (`<metric>_min|_max`); tilt metrics → CRITICAL |

Live-observed values (session 5): joint_states_hz≈839–1000, odometry_hz≈50,
imu_hz≈100; `data/telemetry.csv` 47 samples @ 1 Hz sim-time; robot fallen →
body_pitch_deg≈−83.45, body_roll_deg≈−90, fall_risk_score=1.0, anomaly=True,
**CRITICAL alert** `"fall_risk_score_max=1.00 (limit > 0.80)"` on `/h1/alerts`.

## AWS sync integration (M4.4, see TASK-h1_aws_sync_m44)

`SyncRunner` (h1_aws_sync) reads `data/telemetry.jsonl` → S3 `h1-sim-telemetry`
(lifecycle 30d) + DynamoDB `h1_alerts` (provisioned 5/5, pk=timestamp/sk=alert_id,
idempotent condition) + SNS `h1-alerts` → email (stickfitofficial@gmail.com).
Watermark file for resume; AlertThrottle sliding window; exponential backoff retry.

## Verification evidence

```
# Telemetry tests (47) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
47 passed in 1.28s

# aws_sync tests (46) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
46 passed
```

Live: lifecycle configure+activate via `scripts/telemetry_lifecycle.py`
("h1_telemetry configured" / "active: sampling @ 1.0 Hz"); thresholds "(8 rules)";
topics confirmed `/h1/telemetry` + `/h1/alerts` + `/anomaly_flag`.

## Bugs fixed during this wave

1. RcutilsLogger format-string calls passed extra positional args instead of `%`-formatting → TypeError on activate.
2. `create_publisher`/`create_subscription` passed STRING type names instead of message classes → crashes.
3. Subscription topics corrected to `/joint_states` + `/imu` (bridge publishes WITHOUT `/h1` prefix).

## Files changed

- `src/h1_telemetry/src/h1_telemetry/{ring_buffer,body_state,thresholds,anomaly,writer}.py` (new)
- `src/h1_telemetry/src/h1_telemetry/telemetry_node.py` (rewritten as LifecycleNode)
- `src/h1_telemetry/config/thresholds.yaml`, `src/h1_telemetry/test/*` (47 tests)
- `scripts/telemetry_lifecycle.py`, `scripts/start_telemetry_node.sh` (helpers)

## Deviations / decisions

- No sklearn: live detector = rolling z-score; IsolationForest is a documented stub (`AnomalyScorer.isolation_forest_score`) pending offline training on a nominal bag.
- psutil absent → /proc/loadavg + /proc/meminfo parsers with safe fallbacks.

## Next steps

1. Train real IsolationForest on a nominal telemetry bag; replace the stub.
2. Complete Lambda IAM role (admin step) → enable `h1-telemetry-ingest` end-to-end.
3. Foxglove time-series panels already live (M4.3); add cloud-dashboard view in M9.
