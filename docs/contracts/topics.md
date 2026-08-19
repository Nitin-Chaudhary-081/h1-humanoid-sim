# Topic & Interface Contracts (FROZEN — Wave 1: M2/M3/M4)

| Topic | Type | Pub | Cons | QoS |
|---|---|---|---|---|
| /h1/joint_states | sensor_msgs/JointState | sim bridge | control, telemetry, viz | volatile |
| /h1/odometry | nav_msgs/Odometry | sim (~50 Hz) | control, telemetry | best_effort |
| /h1/imu | sensor_msgs/Imu | sim | control, telemetry | best_effort |
| /h1/<joint>/cmd_pos | std_msgs/Float64 | h1_control | sim bridge | reliable |
| /h1/control_state | h1_interfaces/ControlState | h1_control | viz, agent | reliable |
| /h1/telemetry | h1_interfaces/TelemetrySample | h1_telemetry | viz, aws (later) | reliable |
| /h1/alerts | h1_interfaces/Alert | telemetry, agent, estop | viz, aws (later) | reliable |
| /anomaly_flag | std_msgs/Bool | h1_telemetry | viz, aws (later) | reliable |
| /h1/llm/input_text | std_msgs/String | agent | viz | reliable |
| /h1/llm/intent | std_msgs/String | agent | viz | reliable |
| /h1/llm/tool_calls | std_msgs/String (JSON) | agent | viz | reliable |
| /h1/llm/events | std_msgs/String (JSON) | agent | viz | reliable |
| /estop | std_msgs/Bool | estop node | control, agent | reliable |

Actions (h1_interfaces, single action server on h1_control at `/h1/command`):
- **RobotCommand.action** — goal: mode `STAND | WALK(distance_m) | STOP`; result: success+message; feedback: status+detail.
  All clients (Gemini agent, CLI, future perception) go through this ONE action.
- **GraspExecute.action** — goal: target_marker_id, pregrasp_offset, grasp_depth; result: success, trajectory, message; feedback: phase, progress. Server at `/h1/grasp/execute` (h1_grasp_pipeline).
- Deferred to M5: NavigateTo / PickPlace / PerceptionFrame (h1_perception joins later — NOT part of this freeze).

Frames: odom (fixed) → base_link → pelvis (H1 torso frame, heinz base)
Time: all nodes in sim use_sim_time=true; stamps from source sensor time.
Rules: contract changes = explicit decision by MAIN THREAD ONLY (see AGENTS.md). New topics must be added here before use.
