# TASK-h1_moveit_m5 — M5 MoveIt2 config (h1_moveit_config) + trajectory follower (h1_moveit_follower)

**Status**: DONE (config validated; follower pure-logic tested) · **Date**: 2026-08-19
Commits: `9ec057c`, `63ebcc7`

## Summary

M5 arm manipulation: MoveIt2 configuration package generated from the
`h1_2_handless.urdf` (joint limits verified) plus a
FollowJointTrajectory → `/h1/<joint>/cmd_pos` follower node. The follower
exposes the `/h1/moveit/follow_trajectory` action server consumed by the grasp
pipeline. 32 follower tests pass; SRDF/kinematics/OMPL configs validated.

## What was built

### `h1_moveit_config` (CMake package — config only)

| File | Content |
|---|---|
| `config/h1_2.srdf` (66 lines) | Robot SRDF: planning groups (arm, legs, torso), joint pairs, default IK group, group states |
| `config/kinematics.yaml` (21) | KDL/URDF kinematics plugin, solver params per group |
| `config/joint_limits.yaml` (224) | Full joint limits extracted from the URDF (validated against heinz — 21 actuated joints) |
| `config/ompl_planning.yaml` (119) | OMPL planners (RRTConnect, etc.) + pipeline config |
| `config/pilz_cartesian_limits.yaml` (30) | PILZ Cartesian limits |
| `config/moveit_cpp.yaml` (78) | moveit_cpp client config (planning timeout, pipeline selection) |
| `launch/move_group.launch.py` | Static move_group bringup |

MoveIt2 integration for the arm only — legs stay frozen during arm planning
(plan.md §1C), per the follower's arm-only filtering.

### `h1_moveit_follower` (ament_python)

| Component | Detail |
|---|---|
| `trajectory_follower.py` — pure logic | `TrajectoryFollower`: interpolation correctness (time steps, joint mapping), **arm-only joint filtering**, preempt handling, `check_trajectory_tolerance()` |
| `follower_node.py` — `FollowerNode` | Action server `/h1/moveit/follow_trajectory` (FollowJointTrajectory from `control_msgs`); on goal: creates 17× `/h1/<joint>/cmd_pos` Float64 publishers, control timer drives interpolation @ 50 Hz, feedback + result, cancel handler, stop on preempt |

## Verification evidence

```
# Follower tests (32) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
32 passed
```

Coverage: interpolation at intermediate times, joint-name mapping (MoveIt names
→ cmd_pos topics), arm-only filter (legs/torso untouched), tolerance checking
(within/outside), preempt → clean stop, msg conversion, node-level action
handling with fake-ROS patterns.

Config validation: `verify_m6_config.py` (scripts/) parses SRDF + kinematics +
OMPL + moveit_cpp + limits — all valid, groups resolve, joint sets match the URDF.

## Files changed

- `src/h1_moveit_config/config/{h1_2.srdf, kinematics.yaml, joint_limits.yaml, ompl_planning.yaml, pilz_cartesian_limits.yaml, moveit_cpp.yaml}` (new)
- `src/h1_moveit_config/launch/move_group.launch.py` (new)
- `src/h1_moveit_follower/src/h1_moveit_follower/trajectory_follower.py` (new)
- `src/h1_moveit_follower/src/h1_moveit_follower/follower_node.py` (new)
- `src/h1_moveit_follower/test/test_trajectory_follower.py` (32 tests)

## Next steps

1. Live-sim verify: move_group + follower vs running sim; send a grasp trajectory from h1_grasp_pipeline and watch arm joints move while legs hold pose.
2. M8: full pick-place sequence (perceive → plan → follow → lift) with Foxglove visibility.
