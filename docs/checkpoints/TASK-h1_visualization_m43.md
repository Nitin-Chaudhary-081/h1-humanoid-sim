# M4.3 — Foxglove time-series + anomaly markers for h1_visualization

## Summary
Implemented Foxglove time-series panels and anomaly marker visualization for the h1_visualization package.

## Changed Files

### 1. `src/h1_visualization/src/h1_visualization/marker_utils.py`
- Added `anomaly_marker()` pure function that creates a red sphere marker (SPHERE type) at position (0, 0, 0.9) in frame 'h1_ign' with scale 0.3, visible only when `anomaly=True`
- Added constants: `_ANOMALY_MARKER_ID=3`, `_ANOMALY_RGBA=(1.0, 0.0, 0.0, 0.9)`, `_ANOMALY_SCALE=0.3`, `_ANOMALY_POSITION=(0.0, 0.0, 0.9)`

### 2. `src/h1_visualization/src/h1_visualization/viz_node.py`
- Added subscriptions to:
  - `/h1/telemetry` (h1_interfaces/TelemetrySample) — BEST_EFFORT QoS
  - `/h1/alerts` (h1_interfaces/Alert) — BEST_EFFORT QoS
  - `/anomaly_flag` (std_msgs/Bool) — BEST_EFFORT QoS
- Added anomaly marker publishing logic:
  - `_on_telemetry()`: publishes anomaly marker when `msg.anomaly=True`
  - `_on_anomaly_flag()`: publishes anomaly marker when `msg.data=True`
  - `_publish_anomaly_marker()`: helper that calls `anomaly_marker()` and publishes if anomaly=True
- Control markers publisher uses TRANSIENT_LOCAL durability
- Node logs all subscribed topics on startup

### 3. `src/h1_visualization/config/foxglove_layout.json`
- **3D Panel**: Enabled `/h1/joint_states` and `/h1/alerts` topics
- **Time-series Panels** (joint states from `/h1/joint_states`):
  - `Plot!joint-positions` — position[0..5]
  - `Plot!joint-velocities` — velocity[0..5]
  - `Plot!joint-efforts` — effort[0..5]
- **Telemetry Panels** (from `/h1/telemetry`):
  - `Plot!telemetry-body-pitch-roll` — body_pitch_deg, body_roll_deg
  - `Plot!telemetry-fall-risk` — fall_risk_score
  - `Plot!telemetry-anomaly-score` — anomaly_score
  - `Plot!telemetry-system-load` — cpu_load, ram_used_mb
- **Anomaly Panel**:
  - `Plot!anomaly-flag` — `/anomaly_flag.data`
  - `Log!alerts` — `/h1/alerts`
- **LLM Panel**:
  - `Log!llm-input` — `/h1/llm/input_text`
  - `Log!llm-tool-calls` — `/h1/llm/tool_calls`
  - `Log!llm-events` — `/h1/llm/events`
  - `Log!llm-intent` — `/h1/llm/intent`
- **Odometry Panel**: `Plot!odom-vx` — `/h1/odometry.twist.twist.linear.x`
- **Raw Messages**: `RawMessages!control-state` — `/h1/control_state`
- Layout structured as binary tree with 50/50 splits

### 4. `src/h1_visualization/src/h1_visualization/layout_utils.py`
- Updated validation constants to include all new required panels:
  - `REQUIRED_3D_TOPICS` now includes `/h1/joint_states`
  - `PLOT_PATH_NEEDLES` includes all joint states (position/velocity/effort), telemetry fields, and anomaly_flag
  - `LOG_TOPICS` includes `/h1/alerts` and all 4 LLM topics

### 5. `src/h1_visualization/test/test_pure.py`
- Added tests for `anomaly_marker()`:
  - `test_anomaly_marker_returns_empty_when_false`
  - `test_anomaly_marker_returns_sphere_when_true`
- Updated `test_validate_layout_rejects_missing_plot_path` to use new panel name `Plot!joint-positions`

### 6. `src/h1_visualization/package.xml` and `setup.py`
- Updated description to include M4.3 features

## Verification
- All 17 unit tests pass (`colcon test --packages-select h1_visualization`)
- Layout validation passes with zero errors
- Node starts correctly and subscribes to all 4 required topics with correct QoS:
  - `/h1/control_state` (RELIABLE)
  - `/h1/telemetry` (BEST_EFFORT)
  - `/h1/alerts` (BEST_EFFORT)
  - `/anomaly_flag` (BEST_EFFORT)
- Publisher `/h1/control_markers` uses TRANSIENT_LOCAL durability
- Anomaly marker function produces correct red sphere at (0,0,0.9) in frame 'h1_ign' with scale 0.3

## Acceptance Criteria
- [x] Foxglove layout includes all 4 panel groups (Time-series, Anomaly, LLM, 3D)
- [x] Anomaly marker (red sphere) appears when `/anomaly_flag` = True or `/h1/telemetry.anomaly` = True
- [x] QoS: sensors BEST_EFFORT, control markers TRANSIENT_LOCAL
- [x] All unit tests pass

## Next Steps
- Integrate with running simulation to verify live Foxglove visualization
- Update progress.md with M4.3 completion evidence