# TASK-h1_visualization — Foxglove layout + control-state markers (M2/M3 viz)

Status: DONE (unit-tested, unverified on sim — main thread integrates/launches)
Branch: `wt-h1_visualization` · Commit: `28f9b9b` (single commit after the unit completed)

## Changed files (all under src/h1_visualization/)

| File | Change |
|---|---|
| `config/foxglove_layout.json` | REAL Foxglove exported-format layout (replaces placeholder) |
| `src/h1_visualization/layout_utils.py` | NEW pure module: `validate_layout(path) -> list[str]`, `load_layout(path) -> dict` (no ROS imports) |
| `src/h1_visualization/marker_utils.py` | NEW pure module: mode/status labels, status→color (hex + RGBA), `walk_arrow_length` (cap 3 m), `state_text` (no ROS imports) |
| `src/h1_visualization/viz_node.py` | Thin node implemented: `/h1/control_state` → `/h1/control_markers` (MarkerArray) |
| `test/test_pure.py` | 15 pytest tests (layout validator + marker helpers), zero ROS imports |

## What the layout contains (config/foxglove_layout.json)

App-export format: `configById` + `layout` tree (row/column splits with splitPercentage).
Panel id convention `<Type>!<id>` as exported by Foxglove.

- **3D panel** (`3D!h1-sim`): `followTf`/`fixedFrame` = `h1_ign`, topics enabled:
  `/tf`, `/tf_static`, `/robot_description` (URDF rendering), `/h1/control_markers`,
  plus a `foxglove.Grid` layer (frame `h1_ign`). `/h1/odometry` + `/h1/joint_states`
  listed but hidden.
- **Plot** (`Plot!joint-angles`): `/h1/joint_states.position[0..5]`, headerStamp,
  sliding 30 s window, floating legend.
- **Plot** (`Plot!odom-vx`): `/h1/odometry.twist.twist.linear.x`.
- **Log** (`Log!llm-events`): `topicToRender: /h1/llm/events`.
- **Log** (`Log!llm-intent`): `topicToRender: /h1/llm/intent`.
- **RawMessages** (`RawMessages!control-state`): `topicPath: /h1/control_state`.
- Arrangement: 3D left 65 %; right column = joints plot (40 %), below it odom-vx +
  raw state row, below that the two log panels side by side.

## viz_node.py behavior

- Subscribes `/h1/control_state` (h1_interfaces/ControlState, RELIABLE per contract).
- Publishes `/h1/control_markers` (visualization_msgs/MarkerArray, RELIABLE +
  TRANSIENT_LOCAL so late-joining Foxglove sees the last state).
- Text marker (id 1, ns `control`, TEXT_VIEW_FACING, z=1.0, frame `h1_ign`,
  scale.z 0.25): `"MODE / STATUS[: detail]"`, color by status — green RUNNING/
  SUCCEEDED, yellow IDLE, red FAILED/ESTOPPED, gray unknown.
- Arrow marker (id 2, ns `walk`): shown only while mode==WALK; length =
  `min(goal_distance, 3.0)` along +X of `h1_ign` at z=0.9, amber; DELETEd
  otherwise.
- Params (declared, not hardcoded): `use_sim_time` default **true**,
  `marker_frame=h1_ign`, `text_z=1.0`, `arrow_z=0.9`, `arrow_cap_m=3.0`,
  `marker_lifetime_s=1.0` (markers refresh ~10 Hz with control_state).
- Marker lifetime 1 s: avoids stale markers; transient-local replays last
  message for new clients.
- NOTE: arrow direction assumes robot spawn heading = +X of `h1_ign` (heinz
  spawns facing +X). If the frame/heading differs, adjust `marker_frame` or
  add a yaw param (main-thread call if needed — contract stays frozen).

## Verification evidence (acceptance command)

```
cd <worktree>/src/h1_visualization && PYTHONPATH=src python3 -m pytest test/ -q
...............                                                          [100%]
15 passed in 1.04s
```

The shipped layout passes its own validator (that is the acceptance evidence):
`validate_layout('config/foxglove_layout.json') -> []` (also verified via
`python3 -m json.tool` and a direct validator run, see session log).
`py_compile` of viz_node passes. NOT run: sim, launch, colcon (per workstream rules).

## How to import the layout in Foxglove

1. Connect Foxglove web/desktop to the bridge: `ws://13.207.111.213:8765`
   (port restricted to user IP).
2. In the top-left "Layouts" menu: **Import layout from file…** (web:
   `Layouts` (bottom-left button) → `Import Layout from file…`).
3. Select `src/h1_visualization/config/foxglove_layout.json` (also installed at
   `share/h1_visualization/config/foxglove_layout.json` after colcon install).
4. Layout "H1-2 Sim — Control & Viz" appears; enable the sim, and the 3D panel
   shows the H1 URDF, TF, and the status text + WALK goal arrow from
   `/h1/control_markers` when `h1_viz_node` is running.

## Next steps (main thread)

- `colcon build --packages-select h1_visualization` (entry point `viz_node`),
  launch alongside h1_control; verify `/h1/control_markers` at ~10 Hz and
  markers visible in Foxglove.
- If URDF double-renders in 3D panel (topic + layer), toggle the layer/topic —
  layout only enables the `/robot_description` topic entry by design.
