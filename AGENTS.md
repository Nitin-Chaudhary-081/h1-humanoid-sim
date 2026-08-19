# AGENTS.md — Humanoid Sim Workspace Rules

Read before any work. Shorter is better — every subagent reads this file.

## Project
Humanoid H1-2 sim (ros2_heinz) in ROS 2 Jazzy + Gazebo Harmonic, on a 2 GB RAM VPS.
LLM = Gemini (google-genai). VIZ = Foxglove. AWS = Always-Free only.
Plan: plan.md · Progress: progress.md · Contracts: docs/contracts/topics.md

## Environment
- Source ROS: `source /opt/ros/jazzy/setup.bash` (already in ~/.bashrc)
- Workspace: /home/ubuntu/humanoid_sim_ws; src/ packages
- **2 GB RAM**: NEVER full rebuild; `colcon build --packages-select <pkg>`; colcon defaults in ~/.colcon/defaults.yaml (symlink-install, parallel-workers 1, Release, sequential)
- Headless sim: `gz sim -s -r --headless-rendering` (add LIBGL_ALWAYS_SOFTWARE=1 if Ogre fails)
- No RViz on this box. Foxglove web ← ws://13.207.111.213:8765 (port restricted to user IP)
- RMW: default (Fast DDS) is fine; CycloneDDS optional (`ros-jazzy-rmw-cyclonedds-cpp`)

## Code rules (research-backed)
1. Pure logic in plain classes (testable, no ROS import in unit tests); node = thin wrapper
2. ament_python for Python packages; console_scripts entry points
3. Params in config/*.yaml via declare_parameter — never hardcode
4. XML launch for static bringups; Python launch only for logic
5. QoS: sensors BEST_EFFORT/volatile · commands RELIABLE · static TRANSIENT_LOCAL · use_sim_time in sim
6. No blocking callbacks (no sleep, no sync service call inside callback, no nested spin)
7. No Float32/Bool/String as semantic messages — custom msgs in h1_interfaces
8. ROS logger not print(); throttle high-freq logs

## Package ownership (single-writer per package)
| Package | Owner |
|---|---|
| h1_interfaces | MAIN THREAD ONLY — FROZEN contract, changes require decision |
| h1_bringup | MAIN THREAD ONLY |
| ros2_heinz (vendor) | never modify tracked files; patch via h1_bringup launch overrides |
| h1_control, h1_llm_agent, h1_telemetry, h1_visualization, h1_perception | one workstream each |

## Testing / gates
- Unit tests: pytest on pure logic (no ROS, no network)
- Integration: launch_testing with fake neighbors + unique ROS_DOMAIN_ID
- Smoke gate: scripts/smoke.sh (headless sim + assert topics) — run after every merge
- NEVER mark a task done without observed verification output (default-FAIL)

## Subagent workflow
- Read plan.md + progress.md + docs/contracts/topics.md + your spec before starting
- One package per worktree branch; merge topologically; build+smoke after each merge
- End session: write docs/checkpoints/TASK-<id>.md (changed files, verification evidence, next step)
- Update progress.md rows with evidence after completing a task
- git commit with descriptive messages; commit after every completed unit

## Verification commands (standard)
- `ros2 topic list` / `ros2 topic echo <t> --qos-reliability best_effort` / `ros2 topic hz <t>`
- `colcon build --packages-select <pkg>`
- `colcon test --packages-select <pkg> --event-handlers console_direct+`
- `scripts/smoke.sh`

## Gotchas
- gz sim appears frozen without `-r` (starts paused)
- ros-jazzy-ros-gz vendor packages conflict with osrfoundation.org gz-harmonic — use vendor only
- ros2 topic echo of best-effort topics shows nothing unless --qos-reliability best_effort
- TF/odom: REP 105 (odom → base_link → pelvis); H1 pelvis is base frame in heinz
- Wrists are un-actuated in heinz (plugins commented); 21 actuated joints, not 27
- **Invalid package.xml breaks ROS discovery SILENTLY**: if catkin_pkg fails to parse it (e.g. `<joint>` or other angle-bracket tokens in <description>, invalid maintainer email), colcon falls back to a generic python build — no `ament_prefix_path` hook, package invisible ("Package not found"). Symptom: `install/<pkg>/share/<pkg>/hook/` contains only `pythonpath.*`. Fix the XML, `rm -rf build/<pkg> install/<pkg>`, rebuild.
- rclpy (Jazzy) auto-declares `use_sim_time` in `Node.__init__` — use `self.set_parameters([Parameter('use_sim_time', Parameter.Type.BOOL, True)])`, never `declare_parameter('use_sim_time', ...)` (throws ParameterAlreadyDeclaredException). Exception: LifecycleNode does NOT auto-declare it.
- **Action servers need MultiThreadedExecutor**: `rclpy.spin(node)` (single-threaded) runs the execute_callback inline — a long-running walk goal blocks ALL timers (cmd/state publishers go silent, `_check_walk_complete` never runs → goals hang forever). Symptom: Stand works (finishes instantly) but Walk never publishes/never completes. Use `MultiThreadedExecutor` (or execute in a separate callback group thread).
- **FastDDS graph wedges on this box** after repeated node restarts (CLI: "rcl node's context is invalid"; topics stop flowing). Recovery: kill ALL dds processes → `rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*` → `ros2 daemon stop` → relaunch sim → start nodes. Prefer `bash -c` (not `bash -lc` — login shell sourcing can poison the ROS env) and fresh `env -i` shells for ROS commands; use bracket tricks (`[g]z sim`) in pkill patterns to avoid self-kill.
- Sim RTF on this 2 GB box ≈ 5-15% under load (1 sim-second ≈ 7-20 wall-seconds); long-distance walk goals (≥1 m) exceed wall-timeouts while open-loop mocap replay loses balance after ~0.3 m and the robot falls (odom z → ~0.1). Verify walks with short goals (0.3 m) and restart the sim to re-upright the robot.
- **Goal/mode race in action servers**: when a goal sets mode/state that other timers consume, initialize/create the resource BEFORE flipping the mode, and guard the consumer with try/except; a single unguarded timer tick or a FastDDS wedge RCLError at goal_handle.succeed() can kill the whole action server (seen: WALK crash, 'feedback publisher is invalid').
