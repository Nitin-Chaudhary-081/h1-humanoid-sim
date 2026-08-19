# TASK-h1_telemetry — M4 telemetry + anomaly detection (Wave 1)

**Workstream**: h1_telemetry · **Branch**: `wt-h1_telemetry` · **Date**: 2026-08-18
**Status**: DONE (unit-gated + verified live in sim)

## Changed files (all under src/h1_telemetry/)

| File | What |
|---|---|
| `src/h1_telemetry/ring_buffer.py` | NEW — `RingBuffer` (fixed-capacity deque) + `RateCounter` (Hz from N=100 stamp window; guards <2 samples / zero span / dupes) |
| `src/h1_telemetry/body_state.py` | NEW — quaternion (x,y,z,w) → pitch/roll deg (rotation-matrix formulas, zero-norm safe); `fall_risk_score` heuristic (0..1, linear ramp 20→60 deg, documented in docstring) |
| `src/h1_telemetry/thresholds.py` | NEW — `ThresholdEvaluator`: `_min` = lower bound, `_max` = upper bound; sample dict uses **bare** metric keys (`ram_used_mb` vs threshold `ram_used_mb_max`); yaml loader; unknown-suffix keys dropped |
| `src/h1_telemetry/anomaly.py` | NEW — `AnomalyScorer`: rolling-window z-score (window=50, |z|>3.5 flag), constant-window deviation → +inf; `isolation_forest_score()` = documented placeholder returning z-based score (real IF trained offline on nominal bag, later) |
| `src/h1_telemetry/writer.py` | NEW — `SampleWriter`: CSV + JSONL append, dir auto-create, header written once (missing/empty file), stable column order from first sample, custom paths |
| `src/h1_telemetry/telemetry_node.py` | REWRITTEN — `rclpy.lifecycle.LifecycleNode`: configure (params `thresholds_yaml`/`data_dir`/`sample_period`, `use_sim_time=true`, yaml fallback to share path, writers, publishers); activate (BEST_EFFORT subs on /h1/joint_states, /h1/odometry, /h1/imu; 1 Hz timer); sample → TelemetrySample on /h1/telemetry + /anomaly_flag + /h1/alerts (WARN/CRITICAL: tilt thresholds CRITICAL); CPU via psutil-or-/proc/loadavg, RAM via /proc/meminfo; throttled no-data logging |
| `config/thresholds.yaml` | Comment updated: documents `_min`/`_max` convention |
| `test/test_pure.py` | Filled — import smoke (no-ROS importability of all pure modules) |
| `test/test_ring_buffer.py`, `test/test_body_state.py`, `test/test_thresholds.py`, `test/test_anomaly.py`, `test/test_writer.py` | NEW — 47 pytest cases (see evidence) |

## Verification evidence

Acceptance command (pure tests, no ROS):

```
$ cd /tmp/opencode/wt-h1_telemetry && PYTHONPATH=src python3 -m pytest test/ -q
...............................................                          [100%]
47 passed in 1.28s
```

Extra static evidence (allowed, read-only, no sim/build):
- `ros2 interface show h1_interfaces/msg/TelemetrySample` → fields exactly match the node's published message (stamp, cpu_load, ram_used_mb, *_hz ×3, body_pitch/roll_deg, fall_risk_score, anomaly_score, anomaly, detail).
- `ros2 interface show h1_interfaces/msg/Alert` → stamp/level/source/message/score matched.
- `import h1_telemetry.telemetry_node` under sourced ROS env: OK; `read_cpu_load()` / `read_ram_used_mb()` return sane values (0.0 load, 1275 MB used on this box); `TelemetryNode` is a `LifecycleNode` subclass.

## Live verification (main thread, 2026-08-19)

Node `h1_telemetry_node` (LifecycleNode) verified live against the running sim by a research agent + main thread:

- **Lifecycle**: configure + activate driven via `lifecycle_msgs/ChangeState` service using the new `scripts/telemetry_lifecycle.py`; node logged "h1_telemetry configured" and "h1_telemetry active: sampling @ 1.0 Hz".
- **Thresholds**: "thresholds loaded ... (8 rules)" from `config/thresholds.yaml`.
- **Topics confirmed publishing** (direct Python probe + `ros2 topic` probes): `/h1/telemetry` (h1_interfaces/TelemetrySample), `/h1/alerts` (h1_interfaces/Alert), `/anomaly_flag` (std_msgs/Bool). Subscribes `/joint_states` (BEST_EFFORT), `/h1/odometry`, `/imu`.
- **Sampling**: 1 Hz sim-time; observed joint_states_hz≈839-1000, odometry_hz≈50, imu_hz≈100; `data/telemetry.csv` (48 lines incl. header, 47 samples, 9620 bytes) and `data/telemetry.jsonl` (47 lines, 18225 bytes) growing per sample.
- **Anomaly path fired**: robot is FALLEN → body_pitch_deg≈-83.45, body_roll_deg≈-90, fall_risk_score=1.0, anomaly=True, score=1.0, CRITICAL alert "fall_risk_score_max=1.00 (limit > 0.80)" published on `/h1/alerts`.
- **Bugs fixed during this wave**:
  - (a) RcutilsLogger format-string calls passed extra positional args instead of `%`-formatting (lines ~105-110, ~156, ~248, ~293) → TypeError on activate; converted to `%`-style.
  - (b) `create_publisher`/`create_subscription` passed STRING type names (`'h1_interfaces/msg/TelemetrySample'`) instead of message CLASSES → crashes; switched to message classes.
  - (c) Subscription topic names corrected to `/joint_states` and `/imu` (the bridge publishes WITHOUT the `/h1` prefix).
- **Helper scripts added**: `scripts/telemetry_lifecycle.py` (lifecycle configure+activate driver) and `scripts/start_telemetry_node.sh` (detached launcher, `env -i ... bash -c` per AGENTS.md).

## Commits

- `08e7a34` pure logic units + tests (46 cases)
- `5179e28` lifecycle node + thresholds bare-metric fix (+1 test, 47 total)

## Deviations / decisions

- **No sklearn/pandas/scipy**: IsolationForest is a clearly-documented stub (`AnomalyScorer.isolation_forest_score`) returning the z-based score; real IF model artifact trained offline on a nominal bag is the M4 follow-up (plan.md line 131). Rolling z-score (window 50, |z|>3.5) is the live detector.
- Threshold yaml keys are `<metric>_min|_max`; `ThresholdEvaluator.evaluate()` matches against bare metric names in the sample dict.
- Alert severity: `body_pitch_deg_max`/`body_roll_deg_max`/`fall_risk_score_max` → CRITICAL, everything else WARN (CRITICAL_SUFFIXES in telemetry_node.py).
- psutil absent on the 2 GB box → /proc/loadavg (1-min load / n_cpus) and /proc/meminfo (MemTotal−MemAvailable) parsers with safe fallbacks.

## Next step (main thread / Wave 2)

1. `colcon build --packages-select h1_telemetry` (2 GB rules: symlink-install, -j1).
2. Launch with h1_bringup; verify `/h1/telemetry` at 1 Hz, `/h1/alerts` + `/anomaly_flag` fire on a manual tilt (e.g. gz pose command or IMU edit), files in `data/telemetry.{csv,jsonl}`.
3. Foxglove time-series panel for TelemetrySample fields.
4. M4 later: train IsolationForest on the recorded nominal bag, replace the stub, then h1_aws_sync (Wave 2).