# Unit tests for body_state.py (pure, no ROS).
import math

import pytest

from h1_telemetry.body_state import (
    fall_risk_score,
    imu_orientation_pitch_roll_deg,
    quaternion_to_pitch_roll_deg,
)


def quat_from_axis_angle(axis, angle_deg):
    """Build a (x,y,z,w) quaternion rotating around 'axis' (unit vector)."""
    r = math.radians(angle_deg)
    ax, ay, az = axis
    s = math.sin(r / 2.0)
    return ax * s, ay * s, az * s, math.cos(r / 2.0)


def test_identity_quaternion_zero_angles():
    assert quaternion_to_pitch_roll_deg(0, 0, 0, 1) == (0.0, 0.0)
    assert quaternion_to_pitch_roll_deg(0, 0, 0, -1) == (0.0, 0.0)


def test_pitch_rotation_about_y():
    for deg in (-60.0, -30.0, 30.0, 60.0):
        q = quat_from_axis_angle((0, 1, 0), deg)
        pitch, roll = quaternion_to_pitch_roll_deg(*q)
        assert pitch == pytest.approx(deg, abs=1e-6)
        assert roll == pytest.approx(0.0, abs=1e-6)


def test_roll_rotation_about_x():
    for deg in (-45.0, 45.0, 89.0):
        q = quat_from_axis_angle((1, 0, 0), deg)
        pitch, roll = quaternion_to_pitch_roll_deg(*q)
        assert roll == pytest.approx(deg, abs=1e-6)
        assert pitch == pytest.approx(0.0, abs=1e-6)


def test_combined_pitch_roll_magnitudes_bounded():
    # 30 deg about an axis between x and y -> |pitch| ~ |roll|, each < 45.
    q = quat_from_axis_angle((math.sqrt(0.5), math.sqrt(0.5), 0), 30.0)
    pitch, roll = quaternion_to_pitch_roll_deg(*q)
    assert abs(pitch) < 45.0
    assert abs(roll) < 45.0
    assert abs(pitch) > 5.0
    assert abs(roll) > 5.0


def test_zero_quaternion_invalid():
    assert quaternion_to_pitch_roll_deg(0, 0, 0, 0) == (0.0, 0.0)


def test_180_deg_roll_remains_finite():
    q = quat_from_axis_angle((1, 0, 0), 180.0)
    pitch, roll = quaternion_to_pitch_roll_deg(*q)
    assert math.isfinite(pitch)
    assert math.isfinite(roll)


def test_imu_like_orientation_object():
    class Orientation:
        x = y = z = w = 0.0

    o = Orientation()
    o.x, o.y, o.z, o.w = quat_from_axis_angle((0, 1, 0), 20.0)
    pitch, roll = imu_orientation_pitch_roll_deg(o)
    assert pitch == pytest.approx(20.0, abs=1e-6)
    assert roll == pytest.approx(0.0, abs=1e-6)


def test_fall_risk_heuristic():
    assert fall_risk_score(0.0, 0.0) == 0.0
    assert fall_risk_score(10.0, 5.0) == 0.0      # below safe envelope
    assert fall_risk_score(20.0, 0.0) == 0.0      # exactly at safe boundary
    assert fall_risk_score(40.0, 0.0) == pytest.approx(0.5)  # linear ramp
    assert fall_risk_score(0.0, 60.0) == 1.0      # critical reached
    assert fall_risk_score(90.0, 0.0) == 1.0      # past critical clamps
    assert fall_risk_score(-60.0, 0.0) == 1.0     # negative tilt also counts
    assert fall_risk_score(-30.0, 20.0) == 0.25


def test_fall_risk_invalid_range():
    with pytest.raises(ValueError):
        fall_risk_score(0.0, 0.0, critical_deg=10.0)
