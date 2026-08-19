"""M4 h1_telemetry: lifecycle node — telemetry logging + anomaly detection.

Subscribes /h1/joint_states, /h1/odometry, /h1/imu (sensor topics:
BEST_EFFORT), samples at 1 Hz, publishes /h1/telemetry (TelemetrySample),
raises /anomaly_flag (std_msgs/Bool) + /h1/alerts (Alert, WARN/CRITICAL)
on threshold/z-score breach, and appends each sample to CSV + JSONL.

Pure logic lives in sibling modules (ring_buffer, body_state, thresholds,
anomaly, writer) so unit tests never import ROS.
"""

import os

import rclpy
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from .anomaly import AnomalyScorer
from .body_state import fall_risk_score, imu_orientation_pitch_roll_deg
from .ring_buffer import RateCounter
from .thresholds import ThresholdEvaluator
from .writer import SampleWriter

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
)

# Severity mapping: tilt-related thresholds are CRITICAL, the rest WARN.
CRITICAL_SUFFIXES = ('body_pitch_deg_max', 'body_roll_deg_max',
                     'fall_risk_score_max')

DEFAULT_DATA_DIR = '/home/ubuntu/humanoid_sim_ws/data'
DEFAULT_SAMPLE_PERIOD = 1.0


def read_cpu_load():
    """0..1 CPU load fraction: psutil if importable else /proc/loadavg."""
    try:
        import psutil  # optional, not installed on the 2 GB box
        return psutil.cpu_percent(interval=None) / 100.0
    except ImportError:
        pass
    try:
        with open('/proc/loadavg') as f:
            load1 = float(f.read().split()[0])
    except (OSError, IndexError, ValueError):
        return 0.0
    n_cpus = os.cpu_count() or 1
    return min(1.0, load1 / n_cpus)


def read_ram_used_mb():
    """Used RAM in MB from /proc/meminfo (MemTotal - MemAvailable)."""
    meminfo = {}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                key, rest = line.split(':', 1)
                meminfo[key.strip()] = rest.strip()
        total_kb = int(meminfo['MemTotal'].split()[0])
        avail_kb = int(meminfo['MemAvailable'].split()[0])
    except (OSError, KeyError, IndexError, ValueError):
        return 0.0
    return (total_kb - avail_kb) / 1024.0


class TelemetryNode(LifecycleNode):
    def __init__(self):
        super().__init__('h1_telemetry_node')
        self._evaluator = None
        self._writer = None
        self._rate = {}
        self._scorers = {}
        self._pubs = {}
        self._subs = {}
        self._timer = None
        self._last_sensor_log = 0.0

    # ---- lifecycle ----------------------------------------------------

    def on_configure(self, state):
        self.declare_parameter('thresholds_yaml', '')
        self.declare_parameter('data_dir', DEFAULT_DATA_DIR)
        self.declare_parameter('sample_period', DEFAULT_SAMPLE_PERIOD)
        if self.has_parameter('use_sim_time'):
            self.set_parameters(
                [rclpy.parameter.Parameter('use_sim_time', value=True)])
        else:
            self.declare_parameter('use_sim_time', True)

        thresholds_path = self.get_parameter('thresholds_yaml').value
        if not thresholds_path:
            try:
                from ament_index_python.packages import get_package_share_directory
                share = get_package_share_directory('h1_telemetry')
            except (ImportError, ModuleNotFoundError):
                share = os.path.join(os.path.dirname(__file__), '..', '..', '..')
            thresholds_path = os.path.join(share, 'config', 'thresholds.yaml')

        try:
            self._evaluator = ThresholdEvaluator.from_yaml(thresholds_path)
        except OSError as exc:
            self.get_logger().error(
                'cannot load thresholds from %s: %s' % (thresholds_path, exc))
            return TransitionCallbackReturn.FAILURE
        self.get_logger().info(
            'thresholds loaded from %s (%d rules)'
            % (thresholds_path, len(self._evaluator.limits)))

        data_dir = self.get_parameter('data_dir').value
        self._writer = SampleWriter(data_dir)
        self.get_logger().info('telemetry files: %s, %s'
                               % (self._writer.csv_path, self._writer.jsonl_path))

        self._rate = {
            'joint_states': RateCounter(window_size=100),
            'odometry': RateCounter(window_size=100),
            'imu': RateCounter(window_size=100),
        }
        self._scorers = {
            'cpu_load': AnomalyScorer('cpu_load', window=50),
            'body_pitch_deg': AnomalyScorer('body_pitch_deg', window=50),
        }

        from std_msgs.msg import Bool
        from h1_interfaces.msg import Alert, TelemetrySample
        self._pubs = {
            'telemetry': self.create_publisher(
                TelemetrySample, '/h1/telemetry', 10),
            'anomaly_flag': self.create_publisher(
                Bool, '/anomaly_flag', 10),
            'alerts': self.create_publisher(
                Alert, '/h1/alerts', 10),
        }
        self.get_logger().info('h1_telemetry configured')
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state):
        from sensor_msgs.msg import Imu, JointState
        from nav_msgs.msg import Odometry

        self._subs['joint_states'] = self.create_subscription(
            JointState, '/joint_states',
            self._cb_joint_states, SENSOR_QOS)
        self._subs['odometry'] = self.create_subscription(
            Odometry, '/h1/odometry', self._cb_odometry, SENSOR_QOS)
        self._subs['imu'] = self.create_subscription(
            Imu, '/imu', self._cb_imu, SENSOR_QOS)

        period = float(self.get_parameter('sample_period').value)
        self._timer = self.create_timer(
            period, self._on_sample_timer)
        super().on_activate(state)
        self.get_logger().info('h1_telemetry active: sampling @ %.1f Hz'
                               % (1.0 / period))
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state):
        for sub in self._subs.values():
            self.destroy_subscription(sub)
        self._subs.clear()
        if self._timer is not None:
            self.destroy_timer(self._timer)
            self._timer = None
        super().on_deactivate(state)
        self.get_logger().info('h1_telemetry deactivated')
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state):
        self._evaluator = None
        self._writer = None
        self._rate.clear()
        self._scorers.clear()
        for pub in self._pubs.values():
            self.destroy_publisher(pub)
        self._pubs.clear()
        self.get_logger().info('h1_telemetry cleaned up')
        return TransitionCallbackReturn.SUCCESS

    # ---- subscriptions (non-blocking, cheap) --------------------------

    def _cb_joint_states(self, msg):
        self._rate['joint_states'].add_msg(msg.header.stamp)

    def _cb_odometry(self, msg):
        self._rate['odometry'].add_msg(msg.header.stamp)

    def _cb_imu(self, msg):
        self._rate['imu'].add_msg(msg.header.stamp)
        self._last_orientation = msg.orientation

    # ---- 1 Hz sample ----------------------------------------------------

    def _on_sample_timer(self):
        pitch_deg, roll_deg = imu_orientation_pitch_roll_deg(
            getattr(self, '_last_orientation', None) or _IDENTITY)
        risk = fall_risk_score(pitch_deg, roll_deg)
        cpu_load = read_cpu_load()
        ram_mb = read_ram_used_mb()
        joint_hz = self._rate['joint_states'].hz()
        odom_hz = self._rate['odometry'].hz()
        imu_hz = self._rate['imu'].hz()

        now = self.get_clock().now().to_msg()
        sample = {
            'stamp': now.sec + now.nanosec * 1e-9,
            'cpu_load': cpu_load,
            'ram_used_mb': ram_mb,
            'joint_states_hz': joint_hz,
            'odometry_hz': odom_hz,
            'imu_hz': imu_hz,
            'body_pitch_deg': pitch_deg,
            'body_roll_deg': roll_deg,
            'fall_risk_score': risk,
            'anomaly_score': 0.0,
            'anomaly': False,
            'detail': '',
        }

        breaches = self._evaluator.evaluate(sample)
        score = 0.0
        anomaly = False
        details = []
        for breach in breaches:
            score = max(score, 1.0)
            anomaly = True
            details.append('%s=%.2f (limit %s %.2f)'
                           % (breach.name, breach.value,
                              '<' if breach.kind == 'min' else '>',
                              breach.limit))
        for metric, scorer in self._scorers.items():
            s, flagged = scorer.update(sample[metric], breached=False)
            if flagged:
                anomaly = True
            score = max(score, s)
            if flagged:
                details.append('%s z-score outlier (score %.2f)'
                               % (metric, s))

        sample['anomaly_score'] = round(min(1.0, max(0.0, score)), 4)
        sample['anomaly'] = anomaly
        sample['detail'] = '; '.join(details)

        self._writer.write(sample)
        self._publish(sample)

        if not self._timer_ok(joint_hz, odom_hz, imu_hz):
            self._last_sensor_log = self.get_clock().now().nanoseconds
            self.get_logger().warn(
                'no sensor data yet (joint %.1f Hz, odom %.1f Hz, imu %.1f Hz)'
                % (joint_hz, odom_hz, imu_hz))

    def _timer_ok(self, joint_hz, odom_hz, imu_hz):
        now = self.get_clock().now().nanoseconds
        if now - self._last_sensor_log < 30_000_000_000:
            return True
        return joint_hz > 0.0 or odom_hz > 0.0 or imu_hz > 0.0

    def _publish(self, sample):
        from h1_interfaces.msg import Alert, TelemetrySample
        from std_msgs.msg import Bool

        now = self.get_clock().now().to_msg()
        msg = TelemetrySample()
        msg.stamp = now
        msg.cpu_load = float(sample['cpu_load'])
        msg.ram_used_mb = float(sample['ram_used_mb'])
        msg.joint_states_hz = float(sample['joint_states_hz'])
        msg.odometry_hz = float(sample['odometry_hz'])
        msg.imu_hz = float(sample['imu_hz'])
        msg.body_pitch_deg = float(sample['body_pitch_deg'])
        msg.body_roll_deg = float(sample['body_roll_deg'])
        msg.fall_risk_score = float(sample['fall_risk_score'])
        msg.anomaly_score = float(sample['anomaly_score'])
        msg.anomaly = bool(sample['anomaly'])
        msg.detail = sample['detail']
        self._pubs['telemetry'].publish(msg)

        flag = Bool()
        flag.data = bool(sample['anomaly'])
        self._pubs['anomaly_flag'].publish(flag)

        if sample['anomaly']:
            level = self._alert_level(sample['detail'])
            alert = Alert()
            alert.stamp = now
            alert.level = level
            alert.source = 'h1_telemetry'
            alert.message = 'anomaly: ' + sample['detail']
            alert.score = float(sample['anomaly_score'])
            self._pubs['alerts'].publish(alert)
            self.get_logger().warn('%s alert: %s' % (level, sample['detail']))

    def _alert_level(self, detail):
        for suffix in CRITICAL_SUFFIXES:
            if suffix in detail:
                return 'CRITICAL'
        return 'WARN'


_IDENTITY = type('IdentityQuat', (), {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0})()


def main(args=None):
    rclpy.init(args=args)
    node = TelemetryNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()