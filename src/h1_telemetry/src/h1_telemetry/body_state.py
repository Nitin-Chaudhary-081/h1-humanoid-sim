"""Body attitude estimation from a sensor_msgs-like Imu orientation.

Pure logic, no ROS imports. Quaternion convention: sensor_msgs/Imu
orientation is (x, y, z, w) with w the scalar part.

Pitch/roll are derived from the quaternion rotation matrix elements:
    pitch = asin(2*(w*y - z*x))                     [rad]
    roll  = atan2(2*(w*x + y*z), 1 - 2*(x^2 + y^2)) [rad]
converted to degrees. An invalid (zero-norm) quaternion yields 0/0 deg
instead of raising.

Fall-risk heuristic (documented formula):
    a = max(|pitch_deg|, |roll_deg|)
    score = clamp((a - 20) / (60 - 20), 0, 1)
i.e. 0 while the body is within 20 deg of upright, ramps linearly to 1.0
at >= 60 deg tilt. 60 deg is the H1-2 lying/irrecoverable posture; 20 deg
is a safe stand envelope. This is a heuristic only — tune with the
IsolationForest model trained on the nominal bag once available.
"""

import math


def _normalized(x, y, z, w):
    """Return unit quaternion (x,y,z,w); (0,0,0,0) if input has no norm."""
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0 or not math.isfinite(norm):
        return 0.0, 0.0, 0.0, 0.0
    return x / norm, y / norm, z / norm, w / norm


def quaternion_to_pitch_roll_deg(x, y, z, w):
    """Map an (x,y,z,w) quaternion to (pitch_deg, roll_deg).

    Zero-norm quaternion -> (0.0, 0.0).
    """
    x, y, z, w = _normalized(x, y, z, w)
    if w == 0.0 and x == 0.0 and y == 0.0 and z == 0.0:
        return 0.0, 0.0
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    return math.degrees(pitch), math.degrees(roll)


def imu_orientation_pitch_roll_deg(orientation):
    """orientation: object with float fields x, y, z, w (sensor_msgs-like)."""
    return quaternion_to_pitch_roll_deg(
        orientation.x, orientation.y, orientation.z, orientation.w
    )


def fall_risk_score(pitch_deg, roll_deg, safe_deg=20.0, critical_deg=60.0):
    """0..1 heuristic tilt risk, see module docstring for the formula."""
    if critical_deg <= safe_deg:
        raise ValueError('critical_deg must be > safe_deg')
    tilt = max(abs(pitch_deg), abs(roll_deg))
    if tilt <= safe_deg:
        return 0.0
    if tilt >= critical_deg:
        return 1.0
    return (tilt - safe_deg) / (critical_deg - safe_deg)
