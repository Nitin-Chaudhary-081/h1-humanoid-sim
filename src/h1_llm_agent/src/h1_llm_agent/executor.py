"""Tool executors (pure logic, no ROS imports).

ExecutorInterface is the seam between the agent loop and actuation.
Wave 1 ships MockExecutor (deterministic, used by the node by default and
by all unit tests). Wave 2 integration replaces it with RosActionExecutor,
which sends RobotCommand action goals to the /h1/command action server on
h1_control — see the skeleton class below (the main thread wires it up).

Result contract (plan.md 1D): {status: SUCCESS|FAILED|BLOCKED|TIMEOUT,
detail, data}. data['mode'] is always one of MODES (RobotCommand constants).
"""
from abc import ABC, abstractmethod

from h1_llm_agent.tools import ALLOWED_TOOLS

# Mirrors h1_interfaces/action/RobotCommand.action (FROZEN): int8 STAND=0,
# WALK=1, STOP=2. Kept here so pure logic never imports h1_interfaces.
MODES = {'STAND': 0, 'WALK': 1, 'STOP': 2}


class ExecutorInterface(ABC):
    """Abstract tool executor. Plug the real ROS action client in behind
    this interface without touching the validation layer or the agent loop."""

    @abstractmethod
    def execute(self, tool_name, args=None):
        """Execute one validated tool call.

        Returns {status, detail, data}; status one of
        SUCCESS | FAILED | BLOCKED | TIMEOUT.
        Must never be called with an unvalidated tool name by the loop.
        """
        raise NotImplementedError

    def available_tools(self):
        """Names of the tools this executor can run (defaults to allowlist)."""
        return sorted(ALLOWED_TOOLS)


class MockExecutor(ExecutorInterface):
    """Deterministic in-memory executor. Simulates a successful H1-2 sim
    response for every allowlisted tool; no ROS, no physics, no network."""

    def execute(self, tool_name, args=None):
        args = args if args is not None else {}
        if tool_name == 'walk':
            return {
                'status': 'SUCCESS',
                'detail': 'walk command accepted',
                'data': {'mode': 'WALK', 'distance': float(args.get('distance_m', 0.0))},
            }
        if tool_name == 'stand':
            return {'status': 'SUCCESS', 'detail': 'standing', 'data': {'mode': 'STAND'}}
        if tool_name in ('stop', 'stop_robot'):
            return {'status': 'SUCCESS', 'detail': 'stopped', 'data': {'mode': 'STOP'}}
        if tool_name == 'get_pose':
            # H1-2 spawns standing at z = 1.04 (plan.md 1C); mock pose is static.
            return {
                'status': 'SUCCESS',
                'detail': 'pose read',
                'data': {'x': 0.0, 'y': 0.0, 'z': 1.04, 'theta': 0.0},
            }
        if tool_name == 'get_joint_states':
            return {
                'status': 'SUCCESS',
                'detail': 'joint states read',
                'data': {'joints': ['left_hip_yaw', 'right_hip_yaw',
                                    'left_hip_pitch', 'right_hip_pitch',
                                    'left_hip_roll', 'right_hip_roll',
                                    'left_knee', 'right_knee',
                                    'left_ankle_pitch', 'right_ankle_pitch',
                                    'left_ankle_roll', 'right_ankle_roll',
                                    'left_shoulder_pitch', 'right_shoulder_pitch',
                                    'left_shoulder_roll', 'right_shoulder_roll',
                                    'left_shoulder_yaw', 'right_shoulder_yaw',
                                    'left_elbow', 'right_elbow',
                                    'torso'],
                         'actuated_joints': 21},
            }
        if tool_name == 'list_capabilities':
            return {
                'status': 'SUCCESS',
                'detail': 'capabilities listed',
                'data': {'capabilities': sorted(ALLOWED_TOOLS)},
            }
        return {'status': 'FAILED', 'detail': "unknown tool '{}'".format(tool_name), 'data': {}}


class RosActionExecutor(ExecutorInterface):
    """Skeleton of the real executor (Wave 2, wired by the main thread).

    Future implementation: build an rclpy action client for the single
    h1_interfaces/RobotCommand action server at /h1/command (contract
    docs/contracts/topics.md) and send a goal with:
        mode     = MODES['STAND' | 'WALK' | 'STOP']  (stand/walk/stop/stop_robot)
        distance = args['distance_m'] for walk, else 0.0 (default step count)
    Map the action result {success, message, status, detail} onto the
    executor result contract {status, detail, data} — SUCCESS on
    success=True, FAILED otherwise, TIMEOUT when the action goal expires.
    NOT IMPLEMENTED in Wave 1: unit tests and the node default use
    MockExecutor.
    """

    def __init__(self, node=None, timeout_s=20.0):
        self._node = node
        self._timeout_s = timeout_s

    def execute(self, tool_name, args=None):
        raise NotImplementedError(
            'RosActionExecutor is a Wave 2 skeleton: it will send a '
            'RobotCommand goal (mode STAND/WALK/STOP, distance_m) to the '
            '/h1/command action server on h1_control. Use MockExecutor.')


def build_executor(kind, **kwargs):
    """Factory: 'mock' -> MockExecutor; anything else warns and falls back
    to MockExecutor (the ROS executor is not available until Wave 2)."""
    if kind == 'mock':
        return MockExecutor()
    raise ValueError("unknown executor kind '{}' (only 'mock' in Wave 1)".format(kind))
