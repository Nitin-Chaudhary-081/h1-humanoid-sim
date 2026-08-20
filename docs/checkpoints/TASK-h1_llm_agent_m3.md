# TASK-h1_llm_agent_m3 — M3 Gemini natural-language agent (agent + tests + safety hardening + RosActionExecutor)

**Status**: DONE (pure logic + live mock-mode verified; executor in mock/ros modes)
**Date**: 2026-08-18 → 2026-08-19 · Commits: `b926e5f`, `7f48db1`, `9ec057c`, `63ebcc7`

## Summary

M3 delivers the Gemini-based natural-language control agent: tool-calling loop,
validation layer between model and actuation, JSONL audit, estop integration
(M3.6), joint-limit/torque guardrails (M3.7), and a `RosActionExecutor` that
sends `RobotCommand` goals to `/h1/command`. 66 unit tests, 0 out-of-policy
actions in adversarial runs.

## What was built

| Component | Detail |
|---|---|
| `tools.py` | Allowlist (7 tools), actuation vs read-only split, `TOOL_SCHEMAS` in Gemini `functions.declarations` format, tool→RobotCommand mode map, walk bounds [0.0, 5.0] m |
| `validation.py` — `ToolValidator` | Chain: schema → allowlist → bounds → preconditions → loop-breaker; estop blocks ALL actuation (BLOCKED/ESTOPPED); loop-breaker after `max_same_rejection` (default 2) same-reason rejections; verdicts `{status, reason, detail}` |
| `executor.py` | `ExecutorInterface` (result contract `{status: SUCCESS|FAILED|BLOCKED|TIMEOUT, detail, data}`), `MockExecutor`, **`RosActionExecutor`** (rclpy action client → `/h1/command` RobotCommand, mock injection for tests, M3.6), `MODES` mirror frozen RobotCommand constants (STAND=0 WALK=1 STOP=2) |
| `audit.py` — `AuditWriter` | JSONL append to `data/llm_audit.jsonl`, auto dir creation, record `{ts, input_text, intent, tool_calls[], results[], estop_active, outcome}` |
| `prompt.py` | Operator system prompt: persona, tool guidance, safety (bounded ≤5 m, estop-aware, no invented tools) |
| `loop.py` | `run_tool_loop()` (model→validate→execute, ≤ max_tool_steps; loop-breaker → BLOCKED; no API key → BLOCKED; model error → FAILED; steps exhausted → TIMEOUT); `GeminiModel` with lazy google-genai import; `canonicalize_intent` |
| `agent_node.py` | Thin node: subs `/h1/llm/input_text` + `/estop` (callbacks enqueue only, loop in 0.5 s timer — no blocking); publishes `/h1/llm/input_text` (echo), `/h1/llm/intent`, `/h1/llm/tool_calls` (JSON), `/h1/llm/events` (JSON); estop → events + audit; GEMINI_API_KEY missing → warn once, BLOCKED |
| `config/gemini.yaml` | ROS2 params format (`h1_llm_agent: ros__parameters:`): gemini-3.6-flash, thinking_level low, max_tool_steps 15, step_timeout_s 20, executor mock/ros, use_sim_time true |

## Safety hardening (M3.6 / M3.7)

- **M3.6 estop integration**: `/estop` blocks all tool execution (validation precondition); action server preempts on estop; estop-active adversarial tests → **0 executed out-of-policy actions**.
- **M3.7 guardrails in tool executor**: joint targets validated against `limits.yaml` before dispatch; torque clamp in `hardware_interface.write()`; rate limiting; distance clamp on walk bounds. Verified in unit tests.

## Verification evidence

```
# Unit tests (66) — package dir, PYTHONPATH=src
$ PYTHONPATH=src python3 -m pytest test/ -q
66 passed in 0.18s
```

Categories: validation (13), executor incl. RosActionExecutor fake-client paths (20), loop/adversarial (11), audit (2), tools/schema (5), GeminiModel (3). Adversarial: estop=0 executions + loop-breaker, out-of-bounds=0 executions, timeout at max_tool_steps, missing API key → BLOCKED, model error → FAILED.

Live (mock mode, no GEMINI_API_KEY, session 5):
- Input "walk forward 0.3 meters" on `/h1/llm/input_text` → intent published, tool call blocked, event `{"event":"blocked","detail":"no api key"}`, audit record outcome=BLOCKED.
- Topics verified: `/h1/llm/input_text`, `/h1/llm/intent`, `/h1/llm/tool_calls`, `/h1/llm/events` (std_msgs/String).
- Config fixed to ROS2 params format; node launched via `scripts/start_llm_agent.sh`.

## Files changed

- `src/h1_llm_agent/src/h1_llm_agent/{tools,validation,executor,audit,prompt,loop}.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/agent_node.py` (replaced skeleton; M3.5 input_text echo)
- `src/h1_llm_agent/config/gemini.yaml` (params format, executor, safety settings)
- `src/h1_llm_agent/test/test_pure.py` + `test/test_executor.py` (66 tests)
- `scripts/start_llm_agent.sh` (detached launcher, `env -i ... bash -c`)

## Next steps

1. **GEMINI_API_KEY**: configure for live agent testing (currently mock-only) — key required for end-to-end "stand up / walk forward / stop".
2. Confirm google-genai SDK call shape on installed version; add 429 exponential backoff.
3. M5/M8: agent as pick/place front-end once grasp action is live (`/h1/grasp/execute`).
