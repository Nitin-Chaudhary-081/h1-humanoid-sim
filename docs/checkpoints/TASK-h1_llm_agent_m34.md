# Checkpoint: M3.4 (LLM agent tests) + M3.5 (Foxglove /llm/* topics visible)

## Changed Files

### src/h1_llm_agent/src/h1_llm_agent/agent_node.py
- Added publisher for `/h1/llm/input_text` (echoes received input text for Foxglove visualization)
- Updated `_on_input_text` callback to republish received message on the input_text topic
- Updated docstring to reflect all four published topics: input_text (echo), intent, tool_calls, events

## Test Results

```
cd /home/ubuntu/wt-h1_llm_agent && PYTHONPATH=src/h1_llm_agent/src python3 -m pytest src/h1_llm_agent/test/ -q
```

**Output: 66 passed in 0.18s**

All test categories verified:
- **Validation** (13 tests): ToolValidator chain (schema → allowlist → bounds → preconditions → loop-breaker), estop blocks all actuation, loop-breaker trips on repeated rejections
- **Executor** (20 tests): MockExecutor deterministic responses, RosActionExecutor with fake action client (success, rejection, timeout, server unavailable, exceptions), interface compliance, MODES match frozen RobotCommand constants
- **Loop** (11 tests): run_tool_loop adversarial cases (estop=0 executions+loop-breaker, out-of-bounds=0 executions+loop-breaker, timeout at max_tool_steps, missing API key → BLOCKED, model error → FAILED), audit record written, canonicalize_intent
- **Audit** (2 tests): JSONL format, creates directories, timestamps, read_records
- **Tools** (5 tests): schemas match ALLOWED_TOOLS exactly (7 tools), Gemini declarations format, walk bounds required, descriptions ≤3 words, SYSTEM_PROMPT has safety/estop guidance
- **GeminiModel** (3 tests): API key missing raises ApiKeyMissingError, fake google-genai parsing of function calls + text, importable without google-genai installed

## M3.5 Verification

Agent node now publishes all four `/h1/llm/*` topics as `std_msgs/String`:
- `/h1/llm/input_text` — echoes user input (NEW)
- `/h1/llm/intent` — canonicalized intent string
- `/h1/llm/tool_calls` — JSON with input_text + tool calls per step
- `/h1/llm/events` — JSON events (validation, execution, loop_breaker, timeout, blocked, estop)

## Next Step

M3 integration: verify live against running sim (Wave 2) — agent_node with `executor_type: ros` sending RobotCommand actions to h1_control, confirm Foxglove shows all `/llm/*` topics, test "stand up", "walk forward", "stop" natural language commands execute in sim.