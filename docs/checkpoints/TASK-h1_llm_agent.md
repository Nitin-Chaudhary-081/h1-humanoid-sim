# TASK: h1_llm_agent — M3 Gemini natural-language agent (Wave 1, pure logic)

**Agent**: h1_llm_agent workstream · **Branch**: `wt-h1_llm_agent` (unmerged, no push)
**Date**: 2026-08-18 · **Status**: DONE (verified live, mock mode)

## What was built

Pure-logic modules (no ROS imports, importable without google-genai):
- `src/h1_llm_agent/src/h1_llm_agent/tools.py` — allowlist (7 tools), actuation vs
  read-only split, `TOOL_SCHEMAS` in Gemini functions.declarations format
  (name/description/parameters), tool→RobotCommand mode map, walk bounds [0.0, 5.0] m.
- `validation.py` — `ToolValidator`: schema → allowlist → bounds → preconditions
  (estop blocks ALL actuation, reason `ESTOPPED`, status BLOCKED) → loop-breaker
  (consecutive same-reason rejections ≥ `max_same_rejection`, default 2).
  Verdicts `{status: ALLOWED|REJECTED|BLOCKED, reason, detail}`.
- `executor.py` — `ExecutorInterface` (ABC, result contract `{status: SUCCESS|
  FAILED|BLOCKED|TIMEOUT, detail, data}`), `MockExecutor` (walk → `{mode:'WALK',
  distance}` etc.), `RosActionExecutor` skeleton raising NotImplementedError with
  docstring describing the future `/h1/command` RobotCommand action call (Wave 2),
  `MODES` mirroring the FROZEN `RobotCommand.action` constants (STAND=0 WALK=1 STOP=2).
- `audit.py` — `AuditWriter`: JSONL append to configurable path (default
  `/home/ubuntu/humanoid_sim_ws/data/llm_audit.jsonl`), auto parent-dir creation,
  record `{ts, input_text, intent, tool_calls[], results[], estop_active, outcome}`.
- `prompt.py` — concise operator system prompt (persona, tool guidance, safety:
  bounded ≤5 m movement, estop-aware, no invented tools).
- `loop.py` — `run_tool_loop()` (model→validate→execute, ≤ max_tool_steps,
  loop-breaker abort → BLOCKED, no-key/missing-genai → BLOCKED 'no api key',
  model error → FAILED, steps exhausted → TIMEOUT), `GeminiModel` with LAZY
  google-genai import (works without the package installed), `ToolCall`,
  `canonicalize_intent`.

Thin node wrapper:
- `agent_node.py` — subscribes `/h1/llm/input_text` + `/estop` (callbacks only
  enqueue/flip state; loop runs in a 0.5 s timer — no blocking callbacks);
  publishes `/h1/llm/intent`, `/h1/llm/tool_calls` (JSON), `/h1/llm/events` (JSON,
  every event incl. validation rejections); estop → log + events + audit record
  (per spec: NO `/h1/alerts` publishing — note: contract table lists agent as a
  possible `/h1/alerts` pub, revisit with MAIN THREAD in Wave 2 if wanted);
  GEMINI_API_KEY missing → warn once, all calls BLOCKED 'no api key'.
- `config/gemini.yaml` — added `executor: mock` + `use_sim_time: true` (rest was
  skeleton): model gemini-3.6-flash, thinking_level low, max_tool_steps 15,
  step_timeout_s 20, max_same_rejection 2, topic names per contract.

## Changed files (all under src/h1_llm_agent/, plus checkpoint)

- `src/h1_llm_agent/src/h1_llm_agent/tools.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/validation.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/executor.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/audit.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/prompt.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/loop.py` (new)
- `src/h1_llm_agent/src/h1_llm_agent/agent_node.py` (replaced skeleton)
- `src/h1_llm_agent/config/gemini.yaml` (added executor/use_sim_time)
- `src/h1_llm_agent/test/test_pure.py` (replaced stub)
- `docs/checkpoints/TASK-h1_llm_agent.md` (this file)

## Verification evidence (ACCEPTANCE)

Command (package dir; import root is `src/h1_llm_agent/src`, per skeleton layout):
```
cd /tmp/opencode/wt-h1_llm_agent/src/h1_llm_agent && PYTHONPATH=src python3 -m pytest test/ -q
```
Result: `46 passed in 2.64s` (0 failed). Full output:

```
..............................................                           [100%]
46 passed in 2.64s
```

Coverage: allowlist/bounds/schema rejections; estop blocks ALL actuation tools
(BLOCKED/ESTOPPED) while read-only tools stay allowed; loop-breaker trips after 2
same-reason rejections and resets on allow/different reason; MockExecutor statuses
+ interface compliance; RosActionExecutor NotImplementedError mentions `/h1/command`;
MODES == frozen constants; audit writes JSONL + creates dirs; TOOL_SCHEMAS == exactly
the 7 allowlisted tools, valid Gemini declaration shape, descriptions ≤3 words;
adversarial: estop-active ⇒ 0 actuation commands executed (loop aborts BLOCKED),
walk(100) twice ⇒ 0 executed; no-api-key ⇒ BLOCKED 'no api key'; TIMEOUT at
max_tool_steps; GeminiModel parses function calls against an injected fake
`google.genai` (sys.modules) — real SDK call shape (config dict vs types objects)
to be confirmed during Wave 2 integration.

Also verified on this box (no rclpy, no google-genai): pure modules import cleanly;
no-key path raises ApiKeyMissingError('no api key'); `agent_node.py` compiles
(py_compile) — cannot import rclpy here, so node logic is compile-checked only.

## Live verification (main thread, 2026-08-19)

Node `h1_llm_agent` verified live against the running sim (executor=mock, no GEMINI_API_KEY):

- Input "walk forward 0.3 meters" on `/h1/llm/input_text` (std_msgs/String, sub) →
  `/h1/llm/intent` published with intent="walk forward 0.3 meters".
- Tool calls blocked (mock mode, no API key) on `/h1/llm/tool_calls`; event
  `{"event":"blocked","detail":"no api key"}` published on `/h1/llm/events`.
- Audit record appended to `data/llm_audit.jsonl` with outcome=BLOCKED — contract match confirmed.
- **Config fixed during this wave**: `config/gemini.yaml` wrapped in proper ROS 2
  params format (`h1_llm_agent: ros__parameters:`); node started via
  `scripts/start_llm_agent.sh` (detached launcher, `env -i ... bash -c` per AGENTS.md).

## Commits (branch wt-h1_llm_agent, 5 units)

980df6e validation layer + tool registry · 481e16c executor (+skeleton) ·
4d982d5 audit + prompt · 7f48db1 loop + node + config · b926e5f tests

## Next step (Wave 2, MAIN THREAD)

1. Verify `RosActionExecutor` against running sim: rclpy action client →
   `/h1/command` RobotCommand goal (mode STAND/WALK/STOP, distance_m), map
   result.status/message → executor contract; set `executor: ros`.
2. Confirm google-genai SDK call shape (config dict vs types.GenerateContentConfig;
   `timeout` kwarg) on the installed version; add 429 exponential backoff.
3. Launch-test agent vs fake neighbors (unique ROS_DOMAIN_ID), then smoke.sh;
   optionally publish `/h1/alerts` on estop (contract already lists agent as pub —
   needs MAIN THREAD decision).