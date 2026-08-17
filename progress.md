# Project Progress

> Living document — updated by main thread after every milestone. Read first thing every session.
> Last updated: 2026-08-17

## Status legend
- [ ] pending · [~] in progress · [x] done (with evidence) · [!] blocked

---

## M0 — Environment

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M0.1 | AWS CLI v2 installed | [x] | v2.36.24 at /usr/local/bin/aws |
| M0.2 | Credentials verified | [x] | account 250738719996 (user dev-user), creds from ~/.env → ~/.aws/credentials (chmod 600) |
| M0.3 | Region corrected | [x] | Was us-east-1 in .env; instance metadata shows **ap-south-1** (Mumbai). Fixed .env + credentials. |
| M0.4 | Lightsail instance identified | [x] | "Ubuntu-1" (bundle small_3_1, $5/mo plan), public IP 13.207.111.213, created 2026-08-07, running. THIS machine = that instance. |
| M0.5 | Budget updated to $5 | [x] | "My Zero-Spend Budget" $1 → **$5**; `aws budgets describe-budgets` confirms limit 5 USD |
| M0.6 | Budget alerts → email | [x] | 5 notifications: ACTUAL 50/80/100 + FORECASTED 80/100 (PERCENTAGE, GREATER_THAN), subscriber stickfitofficial@gmail.com (confirmed at create; API doesn't return subscribers on describe). Removed 3 stale no-subscriber alerts. |
| M0.7 | Free-tier monitor script | [x] | ~/scripts/aws_cost_monitor.sh — prints plan state ($197.96 credits, expires 2026-12-14), risky free-tier offers, Lightsail hours (240h used, trial window ends ~2026-11-05). Run OK. |
| M0.8 | Daily cron | [x] | `0 9 * * * ~/scripts/aws_cost_monitor.sh >> ~/scripts/aws_monitor.log` |
| M0.9 | Deep research complete | [x] | 6 research agents: Unitree packages, Gemini+ROS2, AWS free-tier, ROS2 stack/headless, ROS2 best practices, multi-agent orchestration, H1 control methods, LLM-agent safety. Findings → plan.md §1. |
| M0.10 | plan.md + progress.md created | [x] | This repo, plus AGENTS.md pending |
| M0.11 | Install ROS 2 Jazzy + Gazebo Harmonic (vendor) + foxglove-bridge + deps | [x] | Discovery: ROS Jazzy was already dpkg-installed from an earlier session but /opt/ros had been wiped → reinstalled all 333 ros-jazzy pkgs. Verified: ros2 doctor OK, `gz sim --version` = Gazebo Sim 8.11.0 (Harmonic), foxglove_bridge 3.4.1 |
| M0.12 | colcon defaults + workspace scaffold + git init | [x] | ~/.colcon/defaults.yaml (symlink-install, parallel-workers 1, Release, sequential); bashrc sources /opt/ros/jazzy/setup.bash; git repo (main) 3 commits; AGENTS.md + docs/contracts/topics.md created |
| M0.13 | M0 verify: ros2 / gz / bridge up | [x] | ros2 doctor OK; gz sim 8.11.0; `foxglove_bridge` listens on 8765. Firewall: port 8765 restricted to 106.202.127.217/32 (was open to all); ports 22/80 preserved |

## M1 — Unitree H1 simulation running (critical path)

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M1.1 | Clone K-d4wg/ros2_heinz → src/ | [ ] | Primary repo (only maintained H1 Jazzy+Harmonic). Backup fork rejected (adds nothing). |
| M1.2 | Patch launch for headless (`-s -r --headless-rendering`, rviz:=false) | [ ] | Launch hardcodes gz_args; must edit before run |
| M1.3 | rosdep install + colcon build | [ ] | `--packages-select h1_gazebo_sim`, `-j1`, Release |
| M1.4 | Launch headless sim | [ ] | Verify: spawns, /joint_states + /h1/odometry publishing, no OOM (watch free -m) |
| M1.5 | Foxglove bridge + firewall | [ ] | Port 8765 rule → restrict user IP 106.202.127.217; bridge launch; 3D panel shows H1 URDF |
| M1.6 | scripts/smoke.sh passes | [ ] | Headless sim gate: wait 30s, assert topics publishing |

## M2 — Basic commands

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M2.1 | h1_control: stand node | [ ] | Hold standing pose via /h1/<joint>/cmd_pos; verify /joint_states + Foxglove |
| M2.2 | Motion replay player | [ ] | LocoMuJoCo UnitreeH1 npz (walk/stepinplace) → joint map (19→27, zero ankle_roll+wrists) → 50-100 Hz cmd_pos |
| M2.3 | IMU ankle compensation | [ ] | Stretch steps; honest expectation: several steps then fall |
| M2.4 | Actions: Stand/Walk/Stop | [ ] | Foundation for M3 agent |

## M3 — LLM natural-language agent (Gemini)

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M3.1 | h1_interfaces contract frozen | [ ] | Per Wave-0; single-writer |
| M3.2 | Agent node (google-genai, gemini-3.6-flash) | [ ] | Tool loop max_steps 15, validation layer, /estop, JSONL audit |
| M3.3 | Tool executor → ROS actions | [ ] | stand/walk/stop first |
| M3.4 | Tests: unit + mock executor + safety prompts | [ ] | 0 executed out-of-policy actions |
| M3.5 | Foxglove /llm/* topics | [ ] | input_text, intent, tool_calls visible |

## M4 — Telemetry + anomaly detection

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M4.1 | h1_telemetry lifecycle node | [ ] | joint_states/odom/imu → CSV+JSONL in data/ |
| M4.2 | Anomaly detector | [ ] | thresholds + IsolationForest (offline-trained) + /anomaly_flag |
| M4.3 | Foxglove time series | [ ] | |
| M4.4 | AWS sync (Wave 2) | [ ] | S3 bucket + lifecycle, DynamoDB 5/5, Lambda ingest, SNS → email |

## M5+ — Extended roadmap (planned, not started)

| Milestone | Status | Notes |
|-----------|--------|-------|
| M5 Vision pick-place (ArUco → grasp; MoveIt2 + follower) | [ ] | Arm-only planning, legs frozen |
| M6 SLAM + Nav2 | [ ] | Needs lidar plugin; legged controller; partial on 2 GB |
| M7 Voice (whisper.cpp + Silero VAD) | [ ] | NOT concurrent with sim on 2 GB |
| M8 RL (MuJoCo CPU, ONNX export) | [ ] | Isaac rejected (GPU needed) |
| M9 MLOps + digital twin (ONNX quantize, Lambda URL dashboard) | [ ] | |

---

## Session log

### 2026-08-17 — Session 1 (M0-AWS done)
- Installed AWS CLI v2.36.24; verified creds; discovered real region ap-south-1 (was us-east-1 in .env) and confirmed this VPS = Lightsail "Ubuntu-1" via instance metadata.
- Budget: updated "My Zero-Spend Budget" $1→$5; replaced 3 dead notifications with 5 live ones → stickfitofficial@gmail.com.
- Created ~/scripts/aws_cost_monitor.sh + daily cron. Run shows: FREE plan ACTIVE, $197.96 credits, expires 2026-12-14; Lightsail 240h used, trial window ends ~2026-11-05.
- 6 deep-research subagents completed; findings locked into plan.md §1.
- Created plan.md + progress.md.

### Next session
1. M0.11: install ROS 2 Jazzy + Gazebo Harmonic (ros-jazzy-ros-gz vendor) + foxglove-bridge + ros-dev-tools + ccache (apt only, ~1-2 GB)
2. M0.12: colcon defaults, workspace scaffold, git init, AGENTS.md
3. M0.13: verify toolchain (ros2/gz/bridge)
4. Then M1 (clone ros2_heinz, headless patch, build, launch, Foxglove)