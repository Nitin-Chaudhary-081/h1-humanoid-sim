"""Tool registry for the h1_llm_agent (pure logic, no ROS imports).

Defines the allowlist of tools the Gemini agent may call, in Google
Gemini function-calling format (function_declarations style), plus the
actuation/read-only split and tool -> RobotCommand mode mapping.

RobotCommand modes mirror h1_interfaces/action/RobotCommand.action (FROZEN):
  STAND=0, WALK=1, STOP=2
"""

ALLOWED_TOOLS = frozenset([
    'stand',
    'walk',
    'stop',
    'get_pose',
    'get_joint_states',
    'list_capabilities',
    'stop_robot',
])

# Tools that physically move / actuate the robot. Gated by the /estop
# precondition in the validation layer. Everything else is read-only.
ACTUATION_TOOLS = frozenset(['stand', 'walk', 'stop', 'stop_robot'])

READONLY_TOOLS = frozenset(['get_pose', 'get_joint_states', 'list_capabilities'])

# Tool name -> RobotCommand mode string (mode constants live in executor.MODES).
TOOL_MODE_MAP = {
    'stand': 'STAND',
    'walk': 'WALK',
    'stop': 'STOP',
    'stop_robot': 'STOP',
}

# Parameter bounds (meters forward, per RobotCommand.action WALK semantics).
WALK_DISTANCE_MIN = 0.05
WALK_DISTANCE_MAX = 1.0

# Tool parameters. Keys are the JSON-schema property names; values are
# (type, required) so both the schemas and the validator stay in sync.
TOOL_PARAMS = {
    'stand': {},
    'walk': {'distance_m': ('number', True)},
    'stop': {},
    'get_pose': {},
    'get_joint_states': {},
    'list_capabilities': {},
    'stop_robot': {},
}

_DESCRIPTIONS = {
    'stand': 'Stand up',
    'walk': 'Walk forward',
    'stop': 'Stop moving',
    'get_pose': 'Read pose',
    'get_joint_states': 'Read joints',
    'list_capabilities': 'List capabilities',
    'stop_robot': 'Halt robot',
}

_PARAM_DESCRIPTIONS = {
    'distance_m': 'Meters forward, bounded to [0.0, 5.0] (0 = default step count).',
}


def _schema_for(tool_name):
    params = TOOL_PARAMS[tool_name]
    properties = {}
    required = []
    for name, (ptype, is_required) in params.items():
        properties[name] = {
            'type': ptype,
            'description': _PARAM_DESCRIPTIONS.get(name, ''),
        }
        if is_required:
            required.append(name)
    schema = {'type': 'object', 'properties': properties}
    if required:
        schema['required'] = required
    return schema


# Gemini functions.declarations style: name, description, parameters.
TOOL_SCHEMAS = [
    {
        'name': tool_name,
        'description': _DESCRIPTIONS[tool_name],
        'parameters': _schema_for(tool_name),
    }
    for tool_name in sorted(ALLOWED_TOOLS)
]

SCHEMA_BY_NAME = {s['name']: s for s in TOOL_SCHEMAS}


def get_schema(tool_name):
    return SCHEMA_BY_NAME.get(tool_name)
