"""Pure logic for ArUco marker detection — no ROS imports.

Classes:
    ArucoDetector: detects ArUco markers in OpenCV images.

Functions:
    rvec_tvec_to_pose: convert rotation/translation vectors to geometry_msgs/Pose.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None


@dataclass
class ArucoDetection:
    """Single ArUco marker detection result."""
    marker_id: int
    rvec: np.ndarray      # shape (3, 1)
    tvec: np.ndarray      # shape (3, 1)
    corners: np.ndarray   # shape (4, 2) pixel coordinates
    pose: 'Pose'          # geometry_msgs/Pose-like object


class Pose:
    """Minimal geometry_msgs/Pose compatible container (no ROS dependency)."""
    __slots__ = ('position', 'orientation')

    def __init__(self, position=None, orientation=None):
        self.position = position or Point()
        self.orientation = orientation or Quaternion()

    def __repr__(self):
        return (f'Pose(position={self.position}, orientation={self.orientation})')


class Point:
    """Minimal geometry_msgs/Point compatible container."""
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __repr__(self):
        return f'Point(x={self.x}, y={self.y}, z={self.z})'


class Quaternion:
    """Minimal geometry_msgs/Quaternion compatible container."""
    __slots__ = ('x', 'y', 'z', 'w')

    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.w = float(w)

    def __repr__(self):
        return f'Quaternion(x={self.x}, y={self.y}, z={self.z}, w={self.w})'


def rvec_tvec_to_pose(rvec: np.ndarray, tvec: np.ndarray) -> Pose:
    """Convert OpenCV rvec (Rodrigues) and tvec to a Pose with quaternion.

    Args:
        rvec: Rotation vector, shape (3, 1) or (3,)
        tvec: Translation vector, shape (3, 1) or (3,)

    Returns:
        Pose with position (meters) and orientation (quaternion, w-last).
    """
    rvec = np.asarray(rvec).reshape(3)
    tvec = np.asarray(tvec).reshape(3)

    # Rodrigues to rotation matrix
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        R = np.eye(3)
    else:
        axis = rvec / theta
        K = np.array([
            [0, -axis[2], axis[1]],
            [axis[2], 0, -axis[0]],
            [-axis[1], axis[0], 0]
        ])
        R = np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)

    # Rotation matrix to quaternion (w-last convention)
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s

    return Pose(
        position=Point(tvec[0], tvec[1], tvec[2]),
        orientation=Quaternion(x, y, z, w)
    )


class ArucoDetector:
    """ArUco marker detector using OpenCV.

    Pure logic class — no ROS dependencies. All parameters configurable via constructor.
    """

    DICT_MAP = {
        'DICT_4X4_50': cv2.aruco.DICT_4X4_50 if CV2_AVAILABLE else None,
        'DICT_4X4_100': cv2.aruco.DICT_4X4_100 if CV2_AVAILABLE else None,
        'DICT_4X4_250': cv2.aruco.DICT_4X4_250 if CV2_AVAILABLE else None,
        'DICT_4X4_1000': cv2.aruco.DICT_4X4_1000 if CV2_AVAILABLE else None,
        'DICT_5X5_50': cv2.aruco.DICT_5X5_50 if CV2_AVAILABLE else None,
        'DICT_5X5_100': cv2.aruco.DICT_5X5_100 if CV2_AVAILABLE else None,
        'DICT_5X5_250': cv2.aruco.DICT_5X5_250 if CV2_AVAILABLE else None,
        'DICT_5X5_1000': cv2.aruco.DICT_5X5_1000 if CV2_AVAILABLE else None,
        'DICT_6X6_50': cv2.aruco.DICT_6X6_50 if CV2_AVAILABLE else None,
        'DICT_6X6_100': cv2.aruco.DICT_6X6_100 if CV2_AVAILABLE else None,
        'DICT_6X6_250': cv2.aruco.DICT_6X6_250 if CV2_AVAILABLE else None,
        'DICT_6X6_1000': cv2.aruco.DICT_6X6_1000 if CV2_AVAILABLE else None,
        'DICT_7X7_50': cv2.aruco.DICT_7X7_50 if CV2_AVAILABLE else None,
        'DICT_7X7_100': cv2.aruco.DICT_7X7_100 if CV2_AVAILABLE else None,
        'DICT_7X7_250': cv2.aruco.DICT_7X7_250 if CV2_AVAILABLE else None,
        'DICT_7X7_1000': cv2.aruco.DICT_7X7_1000 if CV2_AVAILABLE else None,
    }

    def __init__(
        self,
        camera_matrix: np.ndarray,
        dist_coeffs: np.ndarray,
        marker_length: float = 0.1,
        dictionary_id: str = 'DICT_6X6_250',
    ):
        """Initialize the ArUco detector.

        Args:
            camera_matrix: 3x3 camera intrinsic matrix (numpy array)
            dist_coeffs: 1x5 or 5x1 distortion coefficients (numpy array)
            marker_length: Physical marker side length in meters
            dictionary_id: ArUco dictionary name (e.g., 'DICT_6X6_250')

        Raises:
            ValueError: If parameters are invalid or cv2 not available.
            RuntimeError: If cv2 is not installed.
        """
        if not CV2_AVAILABLE:
            raise RuntimeError('OpenCV (cv2) is not installed')

        # Validate camera matrix
        camera_matrix = np.asarray(camera_matrix, dtype=np.float64)
        if camera_matrix.shape != (3, 3):
            raise ValueError(f'camera_matrix must be 3x3, got {camera_matrix.shape}')

        # Validate distortion coefficients
        dist_coeffs = np.asarray(dist_coeffs, dtype=np.float64).ravel()
        if dist_coeffs.shape not in ((5,), (1, 5), (5, 1)):
            raise ValueError(f'dist_coeffs must be 5 elements, got {dist_coeffs.shape}')
        dist_coeffs = dist_coeffs.reshape(5, 1)

        # Validate marker length
        if marker_length <= 0:
            raise ValueError(f'marker_length must be positive, got {marker_length}')

        # Validate dictionary
        if dictionary_id not in self.DICT_MAP:
            raise ValueError(
                f'Unknown dictionary_id: {dictionary_id}. '
                f'Valid options: {list(self.DICT_MAP.keys())}'
            )
        dict_val = self.DICT_MAP[dictionary_id]
        if dict_val is None:
            raise RuntimeError('OpenCV ArUco module not available')

        self._camera_matrix = camera_matrix
        self._dist_coeffs = dist_coeffs
        self._marker_length = float(marker_length)
        self._dictionary = cv2.aruco.getPredefinedDictionary(dict_val)
        self._parameters = cv2.aruco.DetectorParameters()

    def detect(self, image: np.ndarray) -> List[ArucoDetection]:
        """Detect ArUco markers in a BGR image.

        Args:
            image: OpenCV BGR image as numpy array (H, W, 3)

        Returns:
            List of ArucoDetection objects (empty if none found).
        """
        if not CV2_AVAILABLE:
            raise RuntimeError('OpenCV (cv2) is not installed')

        # Convert to grayscale
        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Detect markers
        corners, ids, _ = cv2.aruco.detectMarkers(
            gray, self._dictionary, parameters=self._parameters
        )

        if ids is None or len(ids) == 0:
            return []

        # Estimate pose for each marker
        rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
            corners, self._marker_length, self._camera_matrix, self._dist_coeffs
        )

        detections = []
        for i, marker_id in enumerate(ids.flatten()):
            pose = rvec_tvec_to_pose(rvecs[i], tvecs[i])
            detections.append(ArucoDetection(
                marker_id=int(marker_id),
                rvec=rvecs[i].reshape(3, 1),
                tvec=tvecs[i].reshape(3, 1),
                corners=corners[i].reshape(4, 2),
                pose=pose,
            ))

        return detections

    @property
    def camera_matrix(self) -> np.ndarray:
        return self._camera_matrix.copy()

    @property
    def dist_coeffs(self) -> np.ndarray:
        return self._dist_coeffs.copy()

    @property
    def marker_length(self) -> float:
        return self._marker_length

    @property
    def dictionary_id(self) -> str:
        for k, v in self.DICT_MAP.items():
            if v == self._dictionary:
                return k
        return 'UNKNOWN'