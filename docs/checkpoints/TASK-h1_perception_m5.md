# TASK-h1_perception_m5 — M5 ArUco detector (h1_perception)

**Status**: DONE (pure logic + tests) · **Date**: 2026-08-19 · Commit: `21b97ff` (+ later fixes in `63ebcc7`)

## Summary

M5 perception: a pure-logic ArUco detector with an optional cv2 backend
(mocked in tests — no cv2/ROS on the test path), publishing
`/h1/perception/detections` (`h1_interfaces/PerceptionFrame`) from a thin
`perception_node` wrapper. 25 unit tests pass.

## What was built

| Component | Detail |
|---|---|
| `aruco.py` — `ArucoDetector` | Pure logic, no ROS deps; configurable dictionary/marker_length/camera matrix/dist coeffs; `detect(image) -> List[ArucoDetection]`; `rvec_tvec_to_pose()` (rvec/tvec → Pose with point/quaternion dataclasses) |
| `ArucoDetection` / `Pose` / `Point` / `Quaternion` | Dataclasses decoupling detection output from ROS msg types |
| `perception_node.py` | Thin node: camera image sub → `ArucoDetector` → publish `/h1/perception/detections` (PerceptionFrame: markers, poses, stamp) |
| `config/*.yaml` | Camera params (marker size, dictionary, intrinsics) via `declare_parameter` — never hardcoded |

The contract (docs/contracts/topics.md) lists `/h1/perception/detections` as
the perception output consumed by the grasp pipeline (M5) — ArUco-first per
plan.md §1D (deterministic in sim; YOLO-nano ONNX and Gemini vision deferred).

## Verification evidence

```
# Unit tests (25) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
25 passed
```

Coverage: detection with mocked cv2 (valid/invalid marker IDs), rvec/tvec→pose
geometry (position + quaternion), pose math sanity (rotations/translations),
parameter bounds, node-import smoke (compile-level). No ROS, no cv2, no network.

## Files changed

- `src/h1_perception/src/h1_perception/aruco.py` (new)
- `src/h1_perception/src/h1_perception/perception_node.py` (new)
- `src/h1_perception/config/*.yaml` (new)
- `src/h1_perception/test/test_aruco.py` (25 tests)
- `h1_interfaces` — `PerceptionFrame` msg added at M5 (contract extension, documented)

## Next steps

1. Live-sim verify: spawn camera + ArUco markers, confirm `/h1/perception/detections` frames at camera rate.
2. Feed detections → `h1_grasp_pipeline` `/h1/grasp/execute` goals (see TASK-h1_grasp_pipeline_m5).
3. Optional: YOLO-nano ONNX fallback for non-marker objects (M5+).
