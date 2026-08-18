"""Pure helpers for /h1/control_state marker styling (no ROS imports).

Mirrors the frozen h1_interfaces/msg/ControlState constants.
"""
from __future__ import annotations

MODE_STAND = 0
MODE_WALK = 1
MODE_STOP = 2

STATUS_IDLE = 0
STATUS_RUNNING = 1
STATUS_SUCCEEDED = 2
STATUS_FAILED = 3
STATUS_ESTOPPED = 4

UNKNOWN = "UNKNOWN"

_MODE_LABELS = {MODE_STAND: "STAND", MODE_WALK: "WALK", MODE_STOP: "STOP"}
_STATUS_LABELS = {
    STATUS_IDLE: "IDLE",
    STATUS_RUNNING: "RUNNING",
    STATUS_SUCCEEDED: "SUCCEEDED",
    STATUS_FAILED: "FAILED",
    STATUS_ESTOPPED: "ESTOPPED",
}
_STATUS_COLORS_HEX = {
    STATUS_RUNNING: "#00e676",
    STATUS_IDLE: "#ffc107",
    STATUS_SUCCEEDED: "#00e676",
    STATUS_FAILED: "#ff1744",
    STATUS_ESTOPPED: "#ff1744",
}
_STATUS_RGBA = {
    STATUS_RUNNING: (0.0, 0.9, 0.46, 1.0),
    STATUS_IDLE: (1.0, 0.76, 0.03, 1.0),
    STATUS_SUCCEEDED: (0.0, 0.9, 0.46, 1.0),
    STATUS_FAILED: (1.0, 0.09, 0.27, 1.0),
    STATUS_ESTOPPED: (1.0, 0.09, 0.27, 1.0),
}
_DEFAULT_RGBA = (0.62, 0.62, 0.62, 1.0)


def mode_label(mode: int) -> str:
    return _MODE_LABELS.get(mode, UNKNOWN)


def status_label(status: int) -> str:
    return _STATUS_LABELS.get(status, UNKNOWN)


def status_color(status: int) -> str:
    """Hex color string for a ControlState status (green/yellow/red)."""
    return _STATUS_COLORS_HEX.get(status, "#9e9e9e")


def status_rgba(status: int) -> tuple[float, float, float, float]:
    """RGBA in 0..1 floats for visualization_msgs/Marker color fields."""
    return _STATUS_RGBA.get(status, _DEFAULT_RGBA)


def walk_arrow_length(goal_distance: float, cap: float = 3.0) -> float:
    """Arrow length for a WALK goal, clamped to [0, cap] meters."""
    length = float(goal_distance)
    if length < 0.0:
        return 0.0
    return min(length, float(cap))


def state_text(mode: int, status: int, detail: str = "") -> str:
    """Human-readable text for the status marker, e.g. 'WALK / RUNNING: detail'."""
    text = f"{mode_label(mode)} / {status_label(status)}"
    return f"{text}: {detail}" if detail else text
