"""Thin ROS 2 node: /h1/control_state (h1_interfaces/ControlState) -> /h1/control_markers.

Publishes a visualization_msgs/MarkerArray for Foxglove:
  - TEXT_VIEW_FACING marker at z~1.0 in frame 'h1_ign' showing mode/status/detail,
    colored by status (green RUNNING/SUCCEEDED, yellow IDLE, red FAILED/ESTOPPED).
  - ARROW marker along +X of 'h1_ign' while mode == WALK with length = goal
    distance capped at 3 m (arrow_cap_m param).

Markers are re-published on every /h1/control_state message (~10 Hz) and use a
transient-local publisher so late-joining Foxglove clients receive the latest
marker state.
"""
import rclpy
from builtin_interfaces.msg import Duration
from h1_interfaces.msg import ControlState
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from visualization_msgs.msg import Marker, MarkerArray

from h1_visualization.marker_utils import (
    MODE_WALK,
    state_text,
    status_rgba,
    walk_arrow_length,
)

_TEXT_MARKER_ID = 1
_ARROW_MARKER_ID = 2
_WALK_ARROW_RGBA = (0.93, 0.51, 0.02, 0.9)  # amber


class VizNode(Node):
    def __init__(self) -> None:
        super().__init__("h1_viz_node")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.declare_parameter("marker_frame", "h1_ign")
        self.declare_parameter("text_z", 1.0)
        self.declare_parameter("arrow_z", 0.9)
        self.declare_parameter("arrow_cap_m", 3.0)
        self.declare_parameter("marker_lifetime_s", 1.0)
        self._marker_frame = str(self.get_parameter("marker_frame").value)
        self._text_z = float(self.get_parameter("text_z").value)
        self._arrow_z = float(self.get_parameter("arrow_z").value)
        self._arrow_cap = float(self.get_parameter("arrow_cap_m").value)
        self._lifetime = Duration(sec=int(self.get_parameter("marker_lifetime_s").value))

        state_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self._state_sub = self.create_subscription(
            ControlState, "/h1/control_state", self._on_state, state_qos
        )
        markers_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._markers_pub = self.create_publisher(
            MarkerArray, "/h1/control_markers", markers_qos
        )
        self.get_logger().info(
            "h1_viz_node ready: /h1/control_state -> /h1/control_markers (frame %s)" %
            self._marker_frame,
        )

    def _on_state(self, msg: ControlState) -> None:
        array = MarkerArray(markers=self._markers_for(msg))
        self._markers_pub.publish(array)
        self.get_logger().debug(
            "published %d markers: %s"
            % (len(array.markers), state_text(msg.mode, msg.status, msg.detail)),
        )

    def _markers_for(self, msg: ControlState) -> list[Marker]:
        return [self._text_marker(msg), self._walk_arrow_marker(msg)]

    def _text_marker(self, msg: ControlState) -> Marker:
        marker = Marker()
        marker.header.frame_id = self._marker_frame
        marker.header.stamp = msg.stamp
        marker.ns = "control"
        marker.id = _TEXT_MARKER_ID
        marker.type = Marker.TEXT_VIEW_FACING
        marker.action = Marker.ADD
        marker.pose.position.z = self._text_z
        marker.scale.z = 0.25
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = status_rgba(
            msg.status
        )
        marker.text = state_text(msg.mode, msg.status, msg.detail)
        marker.lifetime = self._lifetime
        return marker

    def _walk_arrow_marker(self, msg: ControlState) -> Marker:
        marker = Marker()
        marker.header.frame_id = self._marker_frame
        marker.header.stamp = msg.stamp
        marker.ns = "walk"
        marker.id = _ARROW_MARKER_ID
        marker.type = Marker.ARROW
        marker.lifetime = self._lifetime
        if msg.mode != MODE_WALK:
            marker.action = Marker.DELETE
            return marker
        marker.action = Marker.ADD
        marker.pose.position.z = self._arrow_z
        length = walk_arrow_length(msg.goal_distance, cap=self._arrow_cap)
        marker.scale.x = length
        marker.scale.y = 0.12
        marker.scale.z = 0.12
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = _WALK_ARROW_RGBA
        return marker


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VizNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
