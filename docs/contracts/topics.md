# Topic & Interface Contracts (FROZEN)

| Topic | Type | Pub | Cons | QoS |
|---|---|---|---|---|
| /h1/joint_states | sensor_msgs/JointState | sim bridge | all | volatile |
| /h1/odometry | nav_msgs/Odometry | sim (50 Hz) | control, telemetry | best_effort |
| /h1/imu | sensor_msgs/Imu | sim | control, telemetry | best_effort |
| /h1/<joint>/cmd_pos | std_msgs/Float64 | h1_control | sim bridge | reliable |
| /h1/perception/detections | h1_interfaces/PerceptionFrame | h1_perception | agent, viz | reliable |
| /h1/telemetry | h1_interfaces/TelemetrySample | h1_telemetry | viz, aws | reliable |
| /h1/llm/input_text | std_msgs/String | agent | viz | reliable |
| /h1/llm/intent | std_msgs/String | agent | viz | reliable |
| /h1/llm/tool_calls | std_msgs/String (JSON) | agent | viz | reliable |
| /h1/llm/events | std_msgs/String (JSON) | agent | viz | reliable |
| /anomaly_flag | std_msgs/Bool | h1_telemetry | viz, aws | reliable |
| /estop | std_msgs/Bool | estop node | control, agent | reliable |

Actions (h1_interfaces): NavigateTo (goal: PoseStamped), PickPlace (goal: object ids), Stand, Walk, Stop
Frames: odom (fixed) → base_link → pelvis (H1 torso frame, heinz base)
Time: all nodes in sim use_sim_time=true; stamps from source sensor time.
