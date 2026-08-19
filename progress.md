# Project Progress

> Living document — updated by main thread after every milestone. Read first thing every session.
> Last updated: 2026-08-19

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
| M1.1 | Clone K-d4wg/ros2_heinz → src/ | [x] | src/ros2_heinz (4 pkgs: description/gazebo/bringup/controller), unmodified vendor |
| M1.2 | Patch launch for headless (`-s -r --headless-rendering`, rviz:=false) | [x] | New own pkg h1_bringup (launch/h1_headless.launch.py): gz_args `-s -r --headless-rendering`, LIBGL_ALWAYS_SOFTWARE=1, rviz arg default false; config/ros_gz_h1_bridge.yaml copied from vendor; foxglove_bridge node included; robot_state_publisher use_sim_time |
| M1.3 | rosdep install + colcon build | [x] | All 5 pkgs built (1m30s, colcon defaults Release/sequential/symlink). GOTCHA: colcon_ros silently falls back to generic python build (no ament_prefix_path hook → "package not found") if catkin_pkg can't parse package.xml — invalid maintainer email `robot@localhost` caused it; fixed to robot-agent@example.com |
| M1.4 | Launch headless sim | [x] | scripts/launch_h1.sh (setsid detached). gz server 191MB, bridge up. /joint_states ~55Hz, /h1/odometry ~3Hz (BEST_EFFORT), /clock OK. RAM 1.6/1.9Gi used, no OOM |
| M1.5 | Foxglove bridge + firewall | [x] | Bridge 8765 verified end-to-end (requires subprotocol `foxglove.sdk.v1`, sent automatically by Foxglove web). User confirmed H1 renders correctly in 3D panel (needed /tf + /tf_static added to panel transforms, fixed frame `h1_ign`). Firewall: user IP rotates (ISP) — observed SSH 106.202.127.217 → 27.59.95.70, browser 27.59.85.75; port now restricted to all three /32s |
| M1.6 | scripts/smoke.sh passes | [x] | 5/5 PASS: joint_states, h1/odometry (best_effort), clock, gz server, foxglove bridge → SMOKE OK
| M1.7 | Repo published on GitHub | [x] | https://github.com/Nitin-Chaudhary-081/h1-humanoid-sim (public). README with animated H1 SVG (SMIL walk cycle, assets/h1_walk.svg). Real sim footage deferred: headless camera rendering unreliable on GPU-less box. Note: user deletes push token after this commit; future pushes need new auth. |

## M2 — Basic commands

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M2.1 | h1_control: stand node | [x] | Stand action server holds pose via /h1/<joint>/cmd_pos; verified by direct Python action client (Stand PASS) |
| M2.2 | Motion replay player | [x] | LocoMuJoCo npz loaded; walk verified (0.3 m goal reached, "walked 0.30 of 0.30 m"). Fix: sync execute callback (no asyncio) + MultiThreadedExecutor (rclpy.spin blocks timers during walk). Limit: open-loop replay loses balance after ~0.3 m (no balance controller) |
| M2.3 | IMU ankle compensation | [x] | EMA-smoothed pitch/roll from IMU quaternion → ankle pitch / hip roll offsets; wired in control_server.py _compute_pose; unit tests pass (48 total). Commit 8828550 |
| M2.4 | Actions: Stand/Walk/Stop | [x] | All verified via direct Python action client: STAND PASS, WALK 0.3 m PASS, STOP PASS (idle and after walk); full sequence run clean (Stand→Stop→Stand→Walk→Stop); re-verified on fresh upright sim after WALK race fix (commit be01aef) |

## M3 — LLM natural-language agent (Gemini)

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M3.1 | h1_interfaces contract frozen | [x] | h1_interfaces frozen; contract documented in docs/contracts/topics.md |
| M3.2 | Agent node (google-genai, gemini-3.6-flash) | [x] | agent node live in sim (mock executor, no API key): intent published, blocked event + audit written; gemini.yaml params format fixed |
| M3.3 | Tool executor → ROS actions | [x] | tool executor wired to /h1/command action (mock-mode blocked); verified via /h1/llm/input_text probe |
| M3.4 | Tests: unit + mock executor + safety prompts | [x] | 66 tests pass (validation, executor, loop, audit, tools, prompt, GeminiModel); adversarial: estop blocks all actuation, out-of-bounds trips loop-breaker, timeout, missing API key; 0 executed out-of-policy actions |
| M3.5 | Foxglove /llm/* topics | [x] | /h1/llm/input_text, /h1/llm/intent, /h1/llm/tool_calls, /h1/llm/events published by agent_node (std_msgs/String); visible in Foxglove web |

## M4 — Telemetry + anomaly detection

| # | Task | Status | Evidence / Notes |
|---|------|--------|------------------|
| M4.1 | h1_telemetry lifecycle node | [x] | lifecycle node live: configured+activated, /h1/telemetry + /h1/alerts + /anomaly_flag verified, data/telemetry.csv+jsonl written at 1 Hz; logger/type/topic bugs fixed this wave |
| M4.2 | Anomaly detector | [x] | 8 threshold rules loaded; CRITICAL fall_risk alert fired live (robot fallen); z-score AnomalyScorer live |
| M4.3 | Foxglove time series | [x] | foxglove_layout.json with 4 panel groups: Time-series (joint pos/vel/eff + odom), Telemetry (body pitch/roll, fall risk, anomaly score, system load), Anomaly (flag plot + alerts log), LLM (4 log panels); anomaly marker (red sphere at base_link) published on /h1/control_markers when /anomaly_flag=True; 15 tests pass |
| M4.4 | AWS sync (Wave 2) | [x] | S3 bucket `h1-sim-telemetry` + 30d lifecycle ✅; DynamoDB `h1_alerts` (5 RCU/5 WCU) ✅; SNS topic `h1-alerts` + email sub ✅ (confirmation pending); IAM role + Lambda `h1-telemetry-ingest` (dev-user lacks iam:CreateRole — manual step needed); 46 tests pass; sync_runner reads telemetry.jsonl → S3 + DynamoDB + SNS |

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

### 2026-08-19 — Session 7 (Wave 1 complete: M2.3, M3.4, M3.5, M4.3, M4.4)
- Main branch already at commit 9ec057c with all Wave 1 features complete (M3.6, M3.5+M4.3, M2.3, M4.4).
- Verified build + tests on main: h1_llm_agent (66 pass), h1_aws_sync (46 pass), h1_control (48 pass), h1_visualization (15 pass).
- M2.3 IMU ankle compensation: EMA-smoothed pitch/roll from IMU quaternion → ankle/hip joint offsets in _compute_pose; unit tests added.
- M3.4 LLM agent tests: 66 tests covering validation chain, executor, tool loop, audit, GeminiModel parsing; adversarial cases pass (0 out-of-policy executions).
- M3.5 Foxglove /llm/* topics: agent_node publishes input_text, intent, tool_calls, events (std_msgs/String).
- M4.3 Foxglove time-series: foxglove_layout.json with 4 panel groups + anomaly marker on /h1/control_markers.
- M4.4 AWS sync: S3/DynamoDB/SNS resources created (Always-Free); Lambda blocked on IAM role creation (manual step); sync_telemetry.py reads data/telemetry.jsonl → uploads to S3, writes alerts to DynamoDB, notifies SNS.
- Cleaned up 4 git worktrees used for parallel development.

### 2026-08-19 — Session 5 (Wave 1 live verification)
- h1_telemetry verified live: lifecycle node configured+activated via scripts/telemetry_lifecycle.py; 8 threshold rules loaded; /h1/telemetry, /h1/alerts, /anomaly_flag publishing; data/telemetry.csv (47 samples) + telemetry.jsonl (47 lines) at 1 Hz sim-time; CRITICAL fall_risk alert fired (robot fallen: pitch -83°, roll -90°).
- Bugs fixed this wave: RcutilsLogger format-string TypeError (%-formatting), create_publisher/subscription passed string type names instead of message classes, subscription topics corrected to /joint_states + /imu (bridge publishes without /h1 prefix). New scripts: telemetry_lifecycle.py, start_telemetry_node.sh.
- h1_visualization verified live: /h1/control_markers at ~0.4 Hz, 2 markers (ns=control TEXT_VIEW_FACING + ns=walk ARROW), frame h1_ign. Fix: RcutilsLogger.debug() kwarg bug → rebuild.
- h1_llm_agent verified in mock mode (no GEMINI_API_KEY): input "walk forward 0.3 meters" → intent published, tool_calls blocked, event {"event":"blocked","detail":"no api key"}, data/llm_audit.jsonl outcome=BLOCKED. gemini.yaml fixed to ROS2 params format (`h1_llm_agent: ros__parameters:`).
- New helper scripts: launch_detached.sh, start_viz_node.sh, start_llm_agent.sh, start_telemetry_node.sh, telemetry_lifecycle.py — all use `env -i ... bash -c` per AGENTS.md.
- NOTE: sim robot is currently FALLEN (from M2 walk tests) — restart the sim before further walk verification. M2.3 IMU ankle compensation still pending.

### 2026-08-17 — Session 1 (M0-AWS done)
- Installed AWS CLI v2.36.24; verified creds; discovered real region ap-south-1 (was us-east-1 in .env) and confirmed this VPS = Lightsail "Ubuntu-1" via instance metadata.
- Budget: updated "My Zero-Spend Budget" $1→$5; replaced 3 dead notifications with 5 live ones → stickfitofficial@gmail.com.
- Created ~/scripts/aws_cost_monitor.sh + daily cron. Run shows: FREE plan ACTIVE, $197.96 credits, expires 2026-12-14; Lightsail 240h used, trial window ends ~2026-11-05.
- 6 deep-research subagents completed; findings locked into plan.md §1.
- Created plan.md + progress.md.

### Next session
1. **M5 Vision pick-place**: ArUco world markers → grasp poses; MoveIt2 config + trajectory follower (h1_moveit_follower exists); perception→pick_place action
2. **M6 SLAM + Nav2**: Add 2D lidar plugin to H1; slam_toolbox + Nav2 legged controller (MPPI/VP); partial on 2 GB
3. **M7 Voice**: whisper.cpp base.en + Silero VAD → text → M3 agent (schedule separately, not concurrent with sim)
4. **Lambda IAM role**: Complete manual IAM role creation for `h1-telemetry-ingest` Lambda (dev-user lacks `iam:CreateRole`)
5. **Gemini API key**: Configure GEMINI_API_KEY for live LLM agent testing (currently mock-only)