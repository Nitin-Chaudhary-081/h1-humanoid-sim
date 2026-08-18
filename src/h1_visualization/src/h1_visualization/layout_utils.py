"""Pure-logic helpers for the Foxglove layout artifact (no ROS imports).

Validates Foxglove app "exported layout" JSON:

    {
      "configById": {"<PanelType>!<id>": {...config}},
      "layout": {"first": ..., "second": ..., "direction": "row"|"column",
                 "splitPercentage": 0..100},
      ...
    }

Leaves of the layout tree are panel ids; internal nodes are row/column splits.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Acceptance content required in the shipped layout (see TASK spec).
REQUIRED_3D_TOPICS = ("/tf", "/tf_static", "/robot_description", "/h1/control_markers")
REQUIRED_3D_FRAME = "h1_ign"
PLOT_PATH_NEEDLES = ("/h1/joint_states.position[", "/h1/odometry.twist.twist.linear.x")
LOG_TOPICS = ("/h1/llm/events", "/h1/llm/intent")
RAW_TOPIC = "/h1/control_state"


def load_layout(path: str | Path) -> dict[str, Any]:
    """Load a Foxglove layout JSON file into a dict.

    Raises FileNotFoundError / JSONDecodeError / ValueError on bad input.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"layout root must be a JSON object, got {type(data).__name__}")
    return data


def panel_type(panel_id: str) -> str:
    """Return the panel type from an id like '3D!abc123' -> '3D'."""
    return panel_id.split("!", 1)[0]


def collect_panels(config_by_id: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return [(panel_id, config)] for every panel in configById."""
    return [(pid, cfg) for pid, cfg in config_by_id.items() if isinstance(cfg, dict)]


def _walk_layout(node: Any, panel_ids: set[str], errors: list[str]) -> None:
    """Validate the layout tree: leaf refs must exist, splits must be well-formed."""
    if isinstance(node, str):
        if node not in panel_ids:
            errors.append(f"layout references unknown panel id {node!r}")
        return
    if not isinstance(node, dict):
        errors.append(f"layout tree node must be a string or object, got {type(node).__name__}")
        return
    direction = node.get("direction")
    if direction not in ("row", "column"):
        errors.append(f"layout split must have direction 'row' or 'column', got {direction!r}")
    split = node.get("splitPercentage")
    if not isinstance(split, (int, float)) or isinstance(split, bool) or not (0 <= split <= 100):
        errors.append(f"layout split 'splitPercentage' must be a number in 0..100, got {split!r}")
    for key in ("first", "second"):
        if key not in node:
            errors.append(f"layout split missing child {key!r}")
        else:
            _walk_layout(node[key], panel_ids, errors)


def validate_layout(path: str | Path) -> list[str]:
    """Validate a Foxglove layout file. Returns a list of error strings (empty = valid)."""
    try:
        data = load_layout(path)
    except FileNotFoundError:
        return [f"layout file not found: {path}"]
    except json.JSONDecodeError as e:
        return [f"layout file is not valid JSON: {e}"]
    except ValueError as e:
        return [str(e)]

    errors: list[str] = []

    config_by_id = data.get("configById")
    if not isinstance(config_by_id, dict) or not config_by_id:
        errors.append("top-level 'configById' must be a non-empty object")
        return errors
    for pid, cfg in config_by_id.items():
        if not isinstance(cfg, dict):
            errors.append(f"panel {pid!r}: config must be an object")

    if "layout" not in data or not isinstance(data["layout"], (dict, str)):
        errors.append("top-level 'layout' must be an object or panel id string")
        return errors
    _walk_layout(data["layout"], set(config_by_id), errors)

    panels = collect_panels(config_by_id)
    threed = [(pid, cfg) for pid, cfg in panels if panel_type(pid) == "3D"]
    if not threed:
        errors.append("no 3D panel found (configById key must start with '3D!')")
    else:
        for pid, cfg in threed:
            topics = cfg.get("topics", {})
            if not isinstance(topics, dict):
                topics = {}
            for topic in REQUIRED_3D_TOPICS:
                entry = topics.get(topic)
                if not isinstance(entry, dict) or entry.get("visible") is not True:
                    errors.append(f"3D panel {pid!r}: topic {topic} must be enabled (visible: true)")
            for frame_key in ("followTf", "fixedFrame"):
                if cfg.get(frame_key) != REQUIRED_3D_FRAME:
                    errors.append(f"3D panel {pid!r}: {frame_key} must be {REQUIRED_3D_FRAME!r}")

    plot_values: list[str] = []
    for pid, cfg in panels:
        if panel_type(pid) != "Plot":
            continue
        paths = cfg.get("paths")
        if not isinstance(paths, list):
            errors.append(f"Plot panel {pid!r}: 'paths' must be a list")
            continue
        for entry in paths:
            if isinstance(entry, dict) and isinstance(entry.get("value"), str):
                plot_values.append(entry["value"])
    for needle in PLOT_PATH_NEEDLES:
        if not any(needle in value for value in plot_values):
            errors.append(f"no Plot series containing {needle!r}")

    for topic in LOG_TOPICS:
        if not any(
            panel_type(pid) == "Log" and cfg.get("topicToRender") == topic
            for pid, cfg in panels
        ):
            errors.append(f"no Log panel on {topic!r}")

    if not any(
        panel_type(pid) == "RawMessages" and cfg.get("topicPath") == RAW_TOPIC
        for pid, cfg in panels
    ):
        errors.append(f"no RawMessages panel on {RAW_TOPIC!r}")

    return errors
