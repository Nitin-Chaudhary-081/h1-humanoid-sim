# TASK-h1_grasp_pipeline_m5 — M5 grasp pipeline (ArUco → grasp → trajectory)

**Status**: DONE (pure logic + tests; MoveIt2 planner integration ready)
**Date**: 2026-08-19 · Commit: `63ebcc7`

## Summary

M5 grasp pipeline: converts ArUco marker detections into arm grasp poses and
joint-space trajectories, with a heuristic planner and an optional MoveIt2
planner (`MoveIt2Planner`), served by the `/h1/grasp/execute` action server
(`GraspExecute.action`). 33 unit tests pass.

## What was built

| Component | Detail |
|---|---|
| `grasp_pipeline.py` — pure logic (no ROS) | `GraspOffsets` (pregrasp_offset, grasp_depth, approach axis), `CameraToBaseTransform`, `MarkerDetection`, `GraspTrajectory`; `GraspPipeline`: `filter_detections()` (marker id/confidence/reachability), `transform_pose_camera_to_base()`, `compute_grasp_poses()` (grasp + pregrasp + retract poses from marker frame), `solve_ik_simplified()` (arm IK, fallback heuristic), `generate_trajectory()` (approach → grasp → lift), `_plan_with_heuristic()` / `_plan_with_moveit()` |
| `MoveIt2Planner` | Optional ROS-dependent callable wrapping MoveIt2 planning (injected into `GraspPipeline.moveit_planner`); keeps the core testable without ROS |
| `grasp_node.py` — `GraspNode` | Action server `/h1/grasp/execute` (h1_interfaces/GraspExecute: target_marker_id, pregrasp_offset, grasp_depth → success, trajectory, message; feedback phase/progress); subscribes `/h1/perception/detections` (PerceptionFrame) to resolve marker ids; publishes joint trajectory msg for the follower; cancel handler |
| `config/*.yaml` | Grasp offsets, IK settings, planning timeout via params |

Contract (docs/contracts/topics.md): action server at `/h1/grasp/execute`,
goal = marker id + offsets; all clients go through it (perception node, future
LLM agent tool).

## Verification evidence

```
# Unit tests (33) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
33 passed
```

Coverage: detection filtering (id/confidence), camera→base transform math,
grasp pose computation (offsets applied in the right frame), simplified arm IK
(feasible/infeasible targets), trajectory generation (waypoint count, ordering
approach→grasp→lift, durations), heuristic vs moveit planner selection,
trajectory→JointTrajectory msg conversion, action-goal handling (node-level,
fake-ROS patterns).

## Files changed

- `src/h1_grasp_pipeline/src/h1_grasp_pipeline/grasp_pipeline.py` (new)
- `src/h1_grasp_pipeline/src/h1_grasp_pipeline/grasp_node.py` (new)
- `src/h1_grasp_pipeline/config/*.yaml` (new)
- `src/h1_grasp_pipeline/test/test_grasp_pipeline.py` (33 tests)
- `h1_interfaces` — `GraspExecute.action` (contract, frozen)

## Next steps

1. Live-sim verify: perception detections → `/h1/grasp/execute` goal → planned trajectory published to `/h1/moveit/follow_trajectory` (h1_moveit_follower).
2. Wire an LLM tool (`pick_object(id)` / `place_object(id, target)`) to this action for M3→M5 end-to-end.
3. M8: validate grasp success metric in sim (marker lift + hold).
