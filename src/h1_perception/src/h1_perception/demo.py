"""Pure logic for synthetic demo-mode marker frames — no ROS imports.

Used by the perception node's ``--spawn-marker`` demo mode to publish a
synthetic PerceptionFrame on a timer, simulating an ArUco marker at a known
position so the grasp pipeline can be tested without a camera.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class DemoDetection:
    """Synthetic marker detection (plain container, no ROS types)."""
    marker_id: int
    position: List[float]       # [x, y, z] in camera frame (meters)
    orientation: List[float]    # [x, y, z, w] quaternion
    confidence: float = 1.0


@dataclass
class DemoFrame:
    """Synthetic PerceptionFrame-compatible container.

    The perception node converts this to an h1_interfaces/PerceptionFrame
    message. Kept dependency-free so demo-mode generation is unit-testable.
    """
    frame_id: str = "camera_link"
    stamp_nanosec: int = 0
    detections: List[DemoDetection] = field(default_factory=list)


def build_demo_detection(
    marker_id: int,
    pose_xyz: Sequence[float],
    orientation_xyzw: Optional[Sequence[float]] = None,
    confidence: float = 1.0,
) -> DemoDetection:
    """Build a single synthetic marker detection.

    Args:
        marker_id: ArUco marker ID to simulate.
        pose_xyz: Marker position [x, y, z] in the camera frame (meters).
        orientation_xyzw: Optional quaternion (x, y, z, w); identity if None.
        confidence: Detection confidence (0..1).

    Returns:
        A DemoDetection with validated numeric fields.

    Raises:
        ValueError: If pose_xyz has the wrong length or orientation is not a
            unit quaternion.
    """
    pos = [float(v) for v in pose_xyz]
    if len(pos) != 3:
        raise ValueError("pose_xyz must have 3 elements [x, y, z]")

    if orientation_xyzw is None:
        quat = [0.0, 0.0, 0.0, 1.0]
    else:
        quat = [float(v) for v in orientation_xyzw]
        if len(quat) != 4:
            raise ValueError("orientation_xyzw must have 4 elements [x, y, z, w]")
        norm = np.linalg.norm(quat)
        if not np.isfinite(norm) or abs(norm - 1.0) > 1e-3:
            raise ValueError("orientation_xyzw must be a unit quaternion")

    return DemoDetection(
        marker_id=int(marker_id),
        position=pos,
        orientation=quat,
        confidence=float(confidence),
    )


def build_demo_frame(
    marker_id: int,
    pose_xyz: Sequence[float],
    orientation_xyzw: Optional[Sequence[float]] = None,
    frame_id: str = "camera_link",
    stamp_nanosec: int = 0,
    confidence: float = 1.0,
) -> DemoFrame:
    """Build a synthetic PerceptionFrame with a single marker detection.

    Args:
        marker_id: ArUco marker ID to simulate.
        pose_xyz: Marker position [x, y, z] in the camera frame (meters).
        orientation_xyzw: Optional quaternion (x, y, z, w); identity if None.
        frame_id: Frame the pose is expressed in (default camera_link).
        stamp_nanosec: Synthetic message timestamp (nanoseconds since epoch).
        confidence: Detection confidence.

    Returns:
        A DemoFrame containing one DemoDetection.
    """
    det = build_demo_detection(marker_id, pose_xyz, orientation_xyzw, confidence)
    return DemoFrame(
        frame_id=frame_id,
        stamp_nanosec=int(stamp_nanosec),
        detections=[det],
    )


def frame_to_detection_dicts(frame: DemoFrame) -> List[dict]:
    """Convert a DemoFrame to a list of plain dicts.

    Useful for feeding the GraspPipeline's MarkerDetection constructor.
    Each dict has keys: marker_id, position, orientation, confidence.
    """
    return [
        {
            "marker_id": d.marker_id,
            "position": list(d.position),
            "orientation": list(d.orientation),
            "confidence": d.confidence,
        }
        for d in frame.detections
    ]