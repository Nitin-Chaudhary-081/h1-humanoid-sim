# TASK-h1_visualization_m3_5_m4_3 — Foxglove layout (LLM + telemetry + anomaly markers)

**Status**: DONE (verified live) · **Date**: 2026-08-18 → 2026-08-19
Commits: `28f9b9b`, `21b97ff`, `3d19a48`

## Summary

M3.5 + M4.3 visualization: the Foxglove layout covers control state, joint
time-series, LLM observability and telemetry/anomaly, plus the anomaly marker
(red sphere) published on `/h1/control_markers`. 15 unit tests pass.

## What was built

### `config/foxglove_layout.json` — panel groups (50/50 binary tree)

- **3D** (`3D!h1-sim`): fixed frame `h1_ign`, URDF via `/robot_description`, `/tf` `/tf_static`, `/h1/control_markers`, Grid layer; `/h1/joint_states`, `/h1/odometry` listed.
- **Time-series** (from `/h1/joint_states`): `Plot!joint-positions`, `Plot!joint-velocities`, `Plot!joint-efforts` (position[0..5] etc.), `Plot!odom-vx`.
- **Telemetry** (from `/h1/telemetry`): `Plot!telemetry-body-pitch-roll`, `Plot!telemetry-fall-risk`, `Plot!telemetry-anomaly-score`, `Plot!telemetry-system-load`.
- **Anomaly**: `Plot!anomaly-flag` (`/anomaly_flag.data`) + `Log!alerts` (`/h1/alerts`).
- **LLM** (M3.5): `Log!llm-input`, `Log!llm-tool-calls`, `Log!llm-events`, `Log!llm-intent` — all four `/h1/llm/*` topics.
- **Raw**: `RawMessages!control-state` (`/h1/control_state`).

### Code

- `layout_utils.py` — pure module: `validate_layout(path)` (REQUIRED_3D_TOPICS, PLOT_PATH_NEEDLES, LOG_TOPICS), `load_layout(path)`; no ROS imports.
- `marker_utils.py` — pure module: mode/status labels, status→color, `walk_arrow_length` (cap 3 m), `state_text`, and **`anomaly_marker()`** (red SPHERE id 3 at (0,0,0.9), scale 0.3, frame `h1_ign`, only when anomaly=True).
- `viz_node.py` — subs `/h1/control_state` (RELIABLE) + `/h1/telemetry`, `/h1/alerts`, `/anomaly_flag` (BEST_EFFORT); publishes `/h1/control_markers` (MarkerArray, RELIABLE + **TRANSIENT_LOCAL** so late-joining Foxglove sees last state).
  - Text marker (id 1, ns `control`, TEXT_VIEW_FACING, z=1.0): `"MODE / STATUS[: detail]"`, color by status.
  - Arrow marker (id 2, ns `walk`): while mode==WALK, length `min(goal_distance, 3.0)` along +X at z=0.9.
  - Anomaly marker published when `/h1/telemetry.anomaly` or `/anomaly_flag.data` = True.

## Verification evidence

```
# Unit tests (15) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
15 passed
```

Live (session 5): `/h1/control_markers` at ~0.4 Hz, 2 markers per message
(ns=control TEXT_VIEW_FACING green "STOP / SUCCEEDED: stopped", ns=walk ARROW),
frame `h1_ign`. Layout passes its own validator (`validate_layout → []`).
Bug fixed: RcutilsLogger.debug kwargs → positional `%`-format; rebuild + relaunch.

## Importing the layout

1. Connect to `ws://13.207.111.213:8765` (port restricted to user IP).
2. Layouts → Import layout from file… → `src/h1_visualization/config/foxglove_layout.json` (also at `share/h1_visualization/config/` after colcon install).
3. Layout "H1-2 Sim — Control & Viz" appears with all panel groups.

## Files changed

- `src/h1_visualization/config/foxglove_layout.json` (rewritten: 4 panel groups)
- `src/h1_visualization/src/h1_visualization/layout_utils.py` (extended validation)
- `src/h1_visualization/src/h1_visualization/marker_utils.py` (+ anomaly_marker)
- `src/h1_visualization/src/h1_visualization/viz_node.py` (telemetry/anomaly subs + marker logic)
- `src/h1_visualization/test/test_pure.py` (15 tests)
- `package.xml` / `setup.py` (description updates)

## Next steps

1. M8: re-verify all panels against a live telemetry run; confirm anomaly sphere appears on forced fall.
2. M9 digital twin: push layout + metrics to cloud dashboard.
