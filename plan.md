# Humanoid Robot Simulation Project — Plan

**Robot**: Unitree H1-2 (via `ros2_heinz` package) in ROS 2 Jazzy + Gazebo Harmonic
**Host**: Lightsail VPS "Ubuntu-1" — Ubuntu 24.04, 2 vCPU, 2 GB RAM, 8 GB swap, no GPU, ap-south-1
**LLM**: Google Gemini (`gemini-3.6/3.7-flash`, free tier, function calling) — NOT DeepSeek/OpenAI
**Viz**: Foxglove (web/desktop) via `foxglove_bridge` (ws://13.207.111.213:8765, restricted to user IP)
**AWS**: Always-Free only — Budgets ($5, alerts→stickfitofficial@gmail.com), Free Tier API, S3, DynamoDB (provisioned), Lambda, SNS, CloudWatch. All CLI-only.

---

## 1. Research findings (deep research, 6 agents) — decisions locked in

### A. Best coding practices (ROS 2, from Henki/ROS docs/MoveIt/Nav2)
1. **Interfaces contract package** (`h1_interfaces`) — all cross-package msg/srv/action defined once, frozen early. Everything depends on it; nothing depends on node packages.
2. **Logic separated from ROS** — pure Python classes (testable without ROS), thin node wrappers.
3. **ament_python** for pure-Python packages; entry points via `console_scripts`; never chmod+run.
4. **XML launch files** for static bringups; Python launch only for real logic. Params in `config/*.yaml`, never hardcoded.
5. **QoS hygiene**: sensors = BEST_EFFORT/volatile, commands = RELIABLE, static data = TRANSIENT_LOCAL. `use_sim_time` everywhere in sim.
6. **Lifecycle nodes** for hardware-adjacent things (telemetry monitor). SingleThreadedExecutor default; never block callbacks; no sync service calls inside callbacks.
7. **No RViz on VPS** — Foxglove only. No GUI Gazebo — `gz sim -s -r --headless-rendering`.
8. **Testing**: unit tests on pure logic (pytest, no ROS) → `launch_testing` integration with fake publishers + unique ROS_DOMAIN_ID → headless-sim smoke script. No arbitrary sleep in tests.
9. **Build on 2 GB**: `colcon build --symlink-install --parallel-workers 1`, `MAKEFLAGS=-j1`, Release, ccache (1 GB), `--packages-select` (never full rebuild). Binary apt packages only — never build MoveIt/Nav2/Gazebo from source.
10. **ros2_control NOT used** — ros2_heinz uses direct topic control (`/h1/<joint>/cmd_pos`); Unitree vendor protocol is the documented exception. MoveIt integration needs a small FollowJointTrajectory→cmd_pos follower node.

### B. Multi-subagent orchestration methods (for fast results)
1. **Spec-driven + interface freeze**: define `h1_interfaces` + topics contract (`docs/contracts/topics.md`) FIRST; freeze at a commit; parallel agents never touch it.
2. **Wave model** (topological dispatch):
   - **Serial spine** (main thread): scaffold+interfaces → sim bringup (M1) → control basics (M2) — the critical path, highest risk.
   - **Wave 1 parallel** (subagents, depend only on frozen interfaces): h1_control, h1_llm_agent, h1_telemetry, h1_perception, h1_visualization.
   - **Wave 2 parallel**: integrations against running sim (LLM↔actions, telemetry↔AWS, perception↔camera).
3. **One package per workstream**; git worktree per agent; **merge topologically, build+smoke test after EVERY merge** ("green, green, A+B red" landing problem).
4. **Checkpoint discipline**: every subagent session ends writing structured handoff (changed files, evidence, verification commands, next step) into `docs/checkpoints/`; `progress.md` updated by main thread.
5. **3–5 parallel agents max** (token cost ∝ linear, throughput ∝ sublinear); tasks ≤ 90 min; specs contain ONE acceptance command.
6. **Quality gates**: fresh-context reviewer (read-only) after each package; default-FAIL evidence (feature not "done" without observed verification output).

### C. H1 locomotion reality check (community-verified)
- ros2_heinz = **H1-2 handless**, 27 joints (21 actuated via JointPositionController P=725/D=15, wrists un-actuated), Bullet Featherstone physics, 1000 Hz, `self_collide=false`, `/h1/odometry` 50 Hz, IMU available. Spawned standing at z=1.04.
- **Gazebo humanoids CANNOT walk with simple control** (Unitree official: "Gazebo simulation cannot do high-level control, namely walking"; community confirms fall-without-RL/MPC).
- Ranked options for M2 walking:
  1. **Motion replay (recommended)**: LocoMuJoCo mocap `.npz` (walk.npz, stepinplace, onestep*) → joint-name map (19-DOF→H1-2, zero ankle_roll/wrists) → interpolate 50–100 Hz to cmd_pos. Honest result: several steps, then fall. Add IMU ankle compensation to extend.
  2. RL ONNX policy (risky sim2sim transfer, joint-set mismatch).
  3. Open-loop sine gait (10–20% success — fallback demo only).
- **M2 "stand" works out of the box** (spawned standing; keep pose via cmd_pos).
- **M3 pick-place**: MoveIt2 config generated from h1_2_handless.urdf (joint limits verified), arm-only planning while legs frozen, needs trajectory-follower node. MoveIt via `moveit_py`.

### D. LLM agent design (Gemini, from ROSClaw/llm_to_ros/Google robotics docs)
- **Architecture**: single agent node, tool-calling loop (max_steps 10–15, per-step timeout), **validation layer between model and actuation** (schema → allowlist → bounds → preconditions → loop-breaker), independent `/estop` node NOT routed through LLM.
- **Gemini specifically needs the safety layer** — ROSClaw eval: Gemini had highest out-of-policy rate among frontier models (31–38% adversarial prompts).
- **Tools (5–10, semantic, verb_noun ≤3 words)**: `navigate_to(x,y,theta)`, `pick_object(id)`, `place_object(id,target)`, `move_joint(name,pos,dur)`, `get_pose()`, `get_joint_states()`, `locate_object(name)`, `stop_robot()`, `list_capabilities()`.
- Structured results `{status: SUCCESS|FAILED|BLOCKED|TIMEOUT, detail, data}`; loop-breaker after 2× same rejection; JSONL audit log; observability topics `/llm/input_text`, `/llm/intent`, `/llm/tool_calls`, `/llm/events`.
- **Vision**: ArUco-first (sim deterministic), YOLO-nano+ONNX second, Gemini vision third. No GroundingDINO/VLA on CPU.
- **Voice (later)**: whisper.cpp `base.en-q5_1` + Silero VAD — feasible but NOT concurrent with running sim on 2 GB (schedule separately).
- SDK: `google-genai` (NOT deprecated google-generativeai). Model `gemini-3.6-flash` (GA) or `gemini-3.7-flash`; thinking_level=low; Interactions API; exponential backoff on 429.

### E. AWS (verified against new Free plan — credits, not legacy 12-month)
- **Always-Free only**: Lambda (1M req), DynamoDB provisioned (25/25 — on-demand NOT free), CloudWatch (10 metrics/10 alarms/5 GB logs), SNS, SQS, Step Functions (4k transitions). Lambda Function URLs replace API Gateway (not on plan). **No IoT Core** (not on plan; skip until real robots).
- S3 = only credit draw (~$0.12/mo @ 5 GB); lifecycle expire 30d.
- Budget done: $5/mo, alerts 50/80/100 ACTUAL + 80/100 FORECASTED → stickfitofficial@gmail.com. Monitor script `~/scripts/aws_cost_monitor.sh` + daily cron.

---

## 2. Workspace layout

```
~/humanoid_sim_ws/
├── plan.md  progress.md  AGENTS.md  requirements.txt  .repos
├── scripts/
│   ├── smoke.sh                  # headless-sim integration gate
│   └── aws_cost_monitor.sh       # (in ~/scripts, daily cron)
├── docs/
│   ├── contracts/topics.md       # topic names, types, QoS, frames
│   └── checkpoints/TASK-*.md     # subagent handoffs
├── data/                         # telemetry CSV/JSONL, rosbags
└── src/
    ├── h1_interfaces/            # [CONTRACT] msg/srv/action — FROZEN
    ├── ros2_heinz/               # vendor: h1_gazebo_sim (H1-2, Jazzy+Harmonic)
    ├── h1_bringup/               # composition root: launch XML + headless patch
    ├── h1_control/               # stand + motion-replay (LocoMuJoCo npz) node
    ├── h1_llm_agent/             # Gemini agent: tool loop + validation + /estop
    ├── h1_perception/            # ArUco + YOLO-nano ONNX detector
    ├── h1_telemetry/             # lifecycle node: CSV/JSONL + IsolationForest
    ├── h1_visualization/         # Foxglove layout, markers, bridge launch
    └── h1_aws_sync/              # S3 upload cron + DynamoDB/SNS alerts (Wave 2)
```

Topic/interface contracts (defined in `h1_interfaces`, see docs/contracts/topics.md):
- `/h1/joint_states` (sensor_msgs/JointState) — sim → all
- `/h1/<joint>/cmd_pos` (std_msgs/Float64) — control → sim bridge (vendor)
- `/h1/odometry`, `/h1/imu` (vendor)
- `/h1/perception/detections` (h1_interfaces/PerceptionFrame)
- `/h1/telemetry` (h1_interfaces/TelemetrySample)
- `/h1/llm/input_text`, `/h1/llm/intent`, `/h1/llm/tool_calls`, `/h1/llm/events`
- `/h1/motion/goal` (action NavigateTo), `/h1/pick_place` (action PickPlace)
- `/anomaly_flag` (std_msgs/Bool + h1_interfaces/Alert), `/estop` (std_msgs/Bool)

---

## 3. Milestones (each: implemented → tested → visualized in Foxglove → "done" in progress.md)

### M0 — Environment (in progress)
- [x] M0-AWS: AWS CLI v2, creds verified (account 250738719996), region fixed ap-south-1
- [x] M0-AWS: budget $5 + 5 alerts → stickfitofficial@gmail.com
- [x] M0-AWS: `~/scripts/aws_cost_monitor.sh` + daily cron (credits $197.96, expires 2026-12-14)
- [ ] M0-ROS: install ROS 2 Jazzy (ros-base) + `ros-jazzy-ros-gz` (Gazebo Harmonic vendor) + foxglove-bridge + nav2/slam-toolbox/robot-localization + build tools + ccache
- [ ] M0-ROS: colcon defaults (symlink-install, parallel-workers 1), workspace scaffold, git init, AGENTS.md
- [ ] M0-ROS: verify: `ros2 --version`, `gz sim --version`, `ros2 launch foxglove_bridge` connects

### M1 — Unitree H1 sim running (critical path, serial)
- [ ] Clone `K-d4wg/ros2_heinz` into src/, patch launch for headless (`-s -r --headless-rendering`, rviz:=false)
- [ ] Build with colcon (packages-select), rosdep install
- [ ] Launch headless; **verify**: robot spawns, `/joint_states` + `/h1/odometry` publishing, no OOM
- [ ] Foxglove: firewall rule (port 8765 → user IP 106.202.127.217), bridge up, **3D panel shows H1** (URDF auto-loaded)
- [ ] Smoke script `scripts/smoke.sh` passes

### M2 — Basic commands (stand / scripted motion)
- [ ] `h1_control`: stand node (hold standing pose via cmd_pos) — verify joint angles via /joint_states + Foxglove
- [ ] Motion player: LocoMuJoCo `UnitreeH1/walk.npz` + stepinplace → joint mapping → cmd_pos; IMU ankle compensation
- [ ] Honest walk demo (several steps); Foxglove shows leg motion + odometry
- [ ] Command interface: ROS 2 actions (Stand, Walk, Stop) — foundation for M3

### M3 — LLM natural-language agent (Gemini) — Wave 1 parallel with M2's interface needs
- [ ] `h1_interfaces` frozen (msg/srv/action for tools)
- [ ] Agent node: google-genai + `gemini-3.6-flash`, tool loop (max_steps 15), validation layer, `/estop`, JSONL audit
- [ ] Tool executor → ROS 2 actions (stand/walk/stop first; pick/place later)
- [ ] Tests: unit (validation, loop-breaker, schema) + mock executor; adversarial safety prompts (0 executed out-of-policy)
- [ ] Foxglove: `/llm/input_text`, `/llm/intent`, `/llm/tool_calls` visible
- [ ] **Success criteria**: "stand up", "walk forward", "stop" → robot executes in sim

### M4 — Telemetry + anomaly detection — Wave 1 parallel
- [ ] `h1_telemetry`: lifecycle node, subscribes joint_states/odometry/imu → CSV+JSONL (data/), 1–10 Hz
- [ ] Anomaly: thresholds.yaml + IsolationForest (trained offline on nominal bag), `/anomaly_flag`, DiagnosticStatus
- [ ] Foxglove time-series + anomaly markers
- [ ] AWS sync (Wave 2): S3 bucket + lifecycle 30d, DynamoDB (provisioned 5/5), Lambda ingest + SNS alert → email

### M5+ — Extended roadmap (after M0–M4, each a separate mini-plan)
- [ ] M5 Vision pick-place: ArUco world markers → grasp poses; MoveIt2 config + trajectory follower; perception→pick_place
- [ ] M6 SLAM+Nav2: 2D lidar on H1 (add plugin), slam_toolbox, Nav2 legged controller (MPPI/VP); partial on 2 GB
- [ ] M7 Voice: whisper.cpp base.en + Silero VAD → text → M3 agent (scheduled outside sim runtime)
- [ ] M8 RL: MuJoCo CPU policy dev (unitree_mujoco / LocoMuJoCo), ONNX export; Isaac rejected (no GPU)
- [ ] M9 MLOps/digital twin: ONNX quantize + latency bench, Foxglove↔cloud sync, Lambda Function URL dashboard

---

## 4. Execution strategy (subagents)

```
Phase 0 (MAIN, serial):  scaffold, AGENTS.md, plan/progress, contracts → commit + FREEZE interfaces
   │
M0-ROS (MAIN or 1 agent): system installs (apt), colcon defaults, workspace verify
   │
M1 (MAIN, critical path): ros2_heinz build + headless patch + smoke + Foxglove verified
   │
Wave 1 (3–4 PARALLEL agents, frozen contracts only):
   ├─ h1_control        (spec: stand + motion player + actions)
   ├─ h1_llm_agent      (spec: Gemini loop + validator + /estop + tests, mock executor)
   ├─ h1_telemetry      (spec: logger + IsolationForest + tests)
   └─ h1_visualization  (spec: foxglove layout + markers)      [h1_perception joins in M5]
   │   each: own git worktree, spec w/ ONE acceptance command, checkpoint file
   │
Wave 2 (2–3 PARALLEL agents, against RUNNING sim):
   ├─ LLM ↔ actions integration (M3 complete)
   ├─ telemetry ↔ AWS sync (M4 complete)
   └─ smoke.sh full-stack gate
   │
Final: sequential merge + full smoke + progress.md "done" per milestone
```

Rules: merge topologically + build/test after every merge; never 2 agents on same package; h1_interfaces single-writer (main); specs ≤90 min tasks; fresh-context reviewer after each package; update progress.md after every milestone.

## 5. Cost & risk guardrails
- Monthly spend target: **$0** (all Always-Free); S3 ~$0.12/mo credit draw. Budget $5 alerts active.
- Lightsail trial ends ~2026-11-05; monitor script tracks hours (240h used @ Aug 17). After trial: delete or ~$5/mo → decide later.
- 2 GB RAM is THE constraint: headless sim only, no RViz, sequential builds, `-j1`, never sim+voice together, zram/swap for bursts.
- Gemini free tier: ~15 RPM / 1500 RPD — serial agent loop, exponential backoff on 429.
- Foxglove port 8765 restricted to user IP; DDS ports never exposed.