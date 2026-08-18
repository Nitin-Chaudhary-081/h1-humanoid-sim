# Pure-logic unit tests for h1_visualization (no ROS imports).
import json
from pathlib import Path

import pytest

from h1_visualization import layout_utils, marker_utils

LAYOUT_PATH = Path(__file__).resolve().parents[1] / "config" / "foxglove_layout.json"


# --- layout_utils ---------------------------------------------------------


def test_shipped_layout_is_valid():
    assert LAYOUT_PATH.exists(), f"layout not found: {LAYOUT_PATH}"
    errors = layout_utils.validate_layout(LAYOUT_PATH)
    assert errors == [], f"shipped layout must pass validation, got: {errors}"


def test_load_layout_returns_dict():
    data = layout_utils.load_layout(LAYOUT_PATH)
    assert isinstance(data, dict)
    assert "configById" in data
    assert "layout" in data


def test_validate_layout_missing_file():
    errors = layout_utils.validate_layout("/nonexistent/layout.json")
    assert errors
    assert "not found" in errors[0]


def test_validate_layout_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    errors = layout_utils.validate_layout(bad)
    assert errors
    assert "not valid JSON" in errors[0]


def test_validate_layout_rejects_missing_3d_topic(tmp_path):
    data = layout_utils.load_layout(LAYOUT_PATH)
    del data["configById"]["3D!h1-sim"]["topics"]["/tf"]
    p = tmp_path / "missing_tf.json"
    p.write_text(json.dumps(data))
    errors = layout_utils.validate_layout(p)
    assert any("/tf" in e for e in errors)


def test_validate_layout_rejects_unknown_panel_ref(tmp_path):
    data = layout_utils.load_layout(LAYOUT_PATH)
    data["layout"]["first"] = "3D!does-not-exist"
    p = tmp_path / "bad_ref.json"
    p.write_text(json.dumps(data))
    errors = layout_utils.validate_layout(p)
    assert any("unknown panel id" in e for e in errors)


def test_validate_layout_rejects_missing_plot_path(tmp_path):
    data = layout_utils.load_layout(LAYOUT_PATH)
    data["configById"]["Plot!joint-angles"]["paths"] = []
    p = tmp_path / "no_plots.json"
    p.write_text(json.dumps(data))
    errors = layout_utils.validate_layout(p)
    assert any("joint_states.position" in e for e in errors)


def test_validate_layout_rejects_non_object_root(tmp_path):
    p = tmp_path / "root.json"
    p.write_text("[1, 2, 3]")
    errors = layout_utils.validate_layout(p)
    assert errors
    assert "JSON object" in errors[0]


def test_validate_layout_missing_config_by_id(tmp_path):
    p = tmp_path / "noid.json"
    p.write_text('{"layout": {}}')
    errors = layout_utils.validate_layout(p)
    assert any("configById" in e for e in errors)


# --- marker_utils ---------------------------------------------------------


def test_mode_labels():
    assert marker_utils.mode_label(marker_utils.MODE_STAND) == "STAND"
    assert marker_utils.mode_label(marker_utils.MODE_WALK) == "WALK"
    assert marker_utils.mode_label(marker_utils.MODE_STOP) == "STOP"
    assert marker_utils.mode_label(99) == "UNKNOWN"


def test_status_labels():
    assert marker_utils.status_label(marker_utils.STATUS_IDLE) == "IDLE"
    assert marker_utils.status_label(marker_utils.STATUS_RUNNING) == "RUNNING"
    assert marker_utils.status_label(marker_utils.STATUS_FAILED) == "FAILED"
    assert marker_utils.status_label(marker_utils.STATUS_ESTOPPED) == "ESTOPPED"
    assert marker_utils.status_label(42) == "UNKNOWN"


def test_status_color_mapping():
    assert marker_utils.status_color(marker_utils.STATUS_RUNNING).startswith("#")
    assert marker_utils.status_color(marker_utils.STATUS_SUCCEEDED) == marker_utils.status_color(
        marker_utils.STATUS_RUNNING
    )
    assert marker_utils.status_color(marker_utils.STATUS_FAILED) == marker_utils.status_color(
        marker_utils.STATUS_ESTOPPED
    )
    assert marker_utils.status_color(marker_utils.STATUS_FAILED) != marker_utils.status_color(
        marker_utils.STATUS_IDLE
    )


def test_status_rgba_is_4_floats_in_range():
    for status in range(6):
        r, g, b, a = marker_utils.status_rgba(status)
        for value in (r, g, b, a):
            assert 0.0 <= value <= 1.0


def test_walk_arrow_length_caps_at_3_meters():
    assert marker_utils.walk_arrow_length(2.0) == pytest.approx(2.0)
    assert marker_utils.walk_arrow_length(10.0) == pytest.approx(3.0)
    assert marker_utils.walk_arrow_length(-1.0) == 0.0
    assert marker_utils.walk_arrow_length(5.0, cap=2.5) == pytest.approx(2.5)


def test_state_text():
    assert marker_utils.state_text(marker_utils.MODE_WALK, marker_utils.STATUS_RUNNING) == (
        "WALK / RUNNING"
    )
    assert marker_utils.state_text(
        marker_utils.MODE_STAND, marker_utils.STATUS_IDLE, "holding"
    ) == "STAND / IDLE: holding"
