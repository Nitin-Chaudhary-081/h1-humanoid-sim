"""H1-2 real-hardware bringup launch (no Gazebo, no sim clock).

Brings up the full stack for the physical robot:
  * robot_state_publisher (URDF from ros_gz_h1_description, wall clock)
  * h1_hardware_interface bridges: joint state, motor command aggregator,
    IMU, lidar, camera (Unitree SDK companion process <-> ROS graph)
  * foxglove_bridge for remote visualization
  * h1_control control_server (Stand/Walk/Stop actions -> /h1/<joint>/cmd_pos)
  * h1_telemetry (lifecycle, autostart, AWS sync enabled)
  * h1_visualization markers, h1_llm_agent (Gemini), h1_perception (ArUco),
    h1_grasp_pipeline (MoveIt2), h1_moveit_follower, MoveIt move_group

Flags:
  dry_run:=true        print the planned node graph and exit (CI validation)
  enable_llm:=false    skip the Gemini agent
  use_moveit:=false    skip move_group (grasp then falls back to heuristic IK)

Also runnable without a ROS environment for CI:
  python3 launch/hardware.launch.py --dry-run
"""

import os

_LAUNCH_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.dirname(_LAUNCH_DIR)  # h1_bringup package root (source or install/share)


def _urdf_path():
    """Best-effort URDF location; resolved properly at launch time via ament."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(
            get_package_share_directory('ros_gz_h1_description'),
            'models/h1_ign', 'h1_2_handless.urdf')
    except Exception:
        return os.path.join(_PKG_DIR, '..', 'ros2_heinz', 'h1_gazebo_sim',
                            'ros_gz_h1_description', 'models/h1_ign',
                            'h1_2_handless.urdf')


def _plan():
    """Static description of the hardware node graph (no ROS imports)."""
    return [
        {'kind': 'node', 'package': 'robot_state_publisher',
         'executable': 'robot_state_publisher', 'name': 'robot_state_publisher',
         'params': [], 'inline': {'use_sim_time': False},
         'description': 'URDF TF tree (wall clock)'},
        {'kind': 'node', 'package': 'h1_hardware_interface',
         'executable': 'joint_state_bridge', 'name': 'h1_joint_state_bridge',
         'params': ['h1_hardware_interface', 'config/bridge.yaml'],
         'inline': {}, 'description': 'motor encoders -> /h1/joint_states'},
        {'kind': 'node', 'package': 'h1_hardware_interface',
         'executable': 'command_bridge', 'name': 'h1_command_bridge',
         'params': ['h1_hardware_interface', 'config/bridge.yaml'],
         'inline': {}, 'description': '/h1/<joint>/cmd_pos -> /h1/hardware/commands'},
        {'kind': 'node', 'package': 'h1_hardware_interface',
         'executable': 'imu_bridge', 'name': 'h1_imu_bridge',
         'params': ['h1_hardware_interface', 'config/bridge.yaml'],
         'inline': {}, 'description': 'body IMU -> /h1/imu/data'},
        {'kind': 'node', 'package': 'h1_hardware_interface',
         'executable': 'lidar_bridge', 'name': 'h1_lidar_bridge',
         'params': ['h1_hardware_interface', 'config/bridge.yaml'],
         'inline': {}, 'description': 'L1/L2 -> /h1/lidar/scan'},
        {'kind': 'node', 'package': 'h1_hardware_interface',
         'executable': 'camera_bridge', 'name': 'h1_camera_bridge',
         'params': ['h1_hardware_interface', 'config/bridge.yaml'],
         'inline': {}, 'description': 'RGB-D -> /camera/image_raw + camera_info'},
        {'kind': 'node', 'package': 'foxglove_bridge',
         'executable': 'foxglove_bridge', 'name': 'foxglove_bridge',
         'params': [], 'inline': {'port': 8765, 'address': '0.0.0.0'},
         'description': 'remote visualization (base station)'},
        {'kind': 'node', 'package': 'h1_control', 'executable': 'control_server',
         'name': 'h1_control_server',
         'params': ['h1_bringup', 'config/hardware/h1_control.yaml'],
         'inline': {},
         'remaps': {'/imu': '/h1/imu/data'},
         'description': 'Stand/Walk/Stop actions, PD command generation'},
        {'kind': 'lifecycle', 'package': 'h1_telemetry',
         'executable': 'telemetry_node', 'name': 'h1_telemetry_node',
         'params': ['h1_bringup', 'config/hardware/h1_telemetry.yaml'],
         'inline': {},
         'remaps': {'/joint_states': '/h1/joint_states', '/imu': '/h1/imu/data'},
         'description': 'telemetry + anomaly detection, AWS sync on'},
        {'kind': 'node', 'package': 'h1_visualization', 'executable': 'viz_node',
         'name': 'h1_viz_node',
         'params': [], 'inline': {'use_sim_time': False, 'marker_frame': 'pelvis'},
         'description': 'control state markers (Foxglove)'},
        {'kind': 'node', 'package': 'h1_llm_agent', 'executable': 'agent_node',
         'name': 'h1_llm_agent',
         'params': ['h1_bringup', 'config/hardware/h1_llm_agent.yaml'],
         'inline': {}, 'condition': 'enable_llm',
         'description': 'Gemini NL agent (env GEMINI_API_KEY)'},
        {'kind': 'node', 'package': 'h1_perception', 'executable': 'perception_node',
         'name': 'h1_perception_node',
         'params': ['h1_bringup', 'config/hardware/h1_perception.yaml'],
         'inline': {}, 'description': 'ArUco detection on /camera/image_raw'},
        {'kind': 'node', 'package': 'h1_moveit_follower', 'executable': 'follower_node',
         'name': 'h1_moveit_follower',
         'params': ['h1_bringup', 'config/hardware/h1_follower.yaml'],
         'inline': {}, 'description': 'FollowJointTrajectory -> arm cmd_pos'},
        {'kind': 'node', 'package': 'h1_grasp_pipeline', 'executable': 'grasp_node',
         'name': 'h1_grasp_node',
         'params': ['h1_bringup', 'config/hardware/h1_grasp.yaml'],
         'inline': {}, 'description': 'perception -> grasp pose -> MoveIt2'},
        {'kind': 'include', 'package': 'h1_moveit_config',
         'launch': 'move_group.launch.py',
         'args': {'use_sim_time': 'false'}, 'condition': 'use_moveit',
         'description': 'MoveIt2 move_group (arm planning)'},
    ]


def _format_plan():
    lines = ['H1-2 hardware launch plan (%d entities):' % len(_plan())]
    for e in _plan():
        if e['kind'] == 'include':
            lines.append('  include  %s/%s  args=%s  [%s]'
                         % (e['package'], e['launch'], e['args'], e['description']))
            continue
        kind = 'lifecycle' if e['kind'] == 'lifecycle' else 'node'
        params = []
        for pkg, rel in e['params']:
            params.append('@%s/%s' % (pkg, rel))
        params.extend('%s=%s' % (k, v) for k, v in sorted(e['inline'].items()))
        remaps = e.get('remaps') or {}
        cond = ' (unless %s=false)' % e['condition'] if e.get('condition') else ''
        lines.append('  %-8s %s/%s (%s)%s' % (kind, e['package'], e['executable'],
                                               e['name'], cond))
        lines.append('           params: %s' % (params or '-'))
        lines.append('           remaps: %s' % (remaps or '-'))
        lines.append('           %s' % e['description'])
    lines.append('URDF: %s' % _urdf_path())
    return '\n'.join(lines)


def generate_launch_description():
    """Entry point used by `ros2 launch h1_bringup hardware.launch.py`."""
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
    from launch.conditions import IfCondition
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
    from launch_ros.actions import LifecycleNode, Node
    from launch_ros.substitutions import FindPackageShare

    use_sim_time = LaunchConfiguration('use_sim_time')
    enable_llm = LaunchConfiguration('enable_llm')
    use_moveit = LaunchConfiguration('use_moveit')
    dry_run = LaunchConfiguration('dry_run')

    def _entities(context):
        if dry_run.perform(context).lower() == 'true':
            print(_format_plan())
            print('\ndry_run: no entities launched.')
            return []

        urdf_path = _urdf_path()
        with open(urdf_path, 'r') as f:
            urdf_content = f.read()

        entities = []
        for e in _plan():
            if e['kind'] == 'include':
                entities.append(IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(
                        os.path.join(FindPackageShare(e['package']).perform(context),
                                     'launch', e['launch'])),
                    launch_arguments=e['args'].items(),
                    condition=IfCondition(LaunchConfiguration(e['condition'])),
                ))
                continue

            parameters = []
            for pkg, rel in e['params']:
                if pkg == 'h1_bringup':
                    parameters.append(os.path.join(_PKG_DIR, rel))
                else:
                    parameters.append(PathJoinSubstitution(
                        [FindPackageShare(pkg), rel]))
            inline = dict(e['inline'])
            if e['name'] in ('robot_state_publisher',):
                inline['robot_description'] = urdf_content
            inline.setdefault('use_sim_time', False)
            parameters.append(inline)

            common = {
                'package': e['package'],
                'executable': e['executable'],
                'name': e['name'],
                'output': 'screen',
                'parameters': parameters,
            }
            if e.get('remaps'):
                common['remappings'] = [(src, dst) for src, dst in e['remaps'].items()]
            if e.get('condition'):
                common['condition'] = IfCondition(LaunchConfiguration(e['condition']))
            if e['kind'] == 'lifecycle':
                entities.append(LifecycleNode(autostart=True, **common))
            else:
                entities.append(Node(**common))
        return entities

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false',
                              description='Wall-clock time on the real robot'),
        DeclareLaunchArgument('dry_run', default_value='false',
                              description='Print the planned node graph and exit (CI)'),
        DeclareLaunchArgument('enable_llm', default_value='true',
                              description='Launch the Gemini LLM agent (needs GEMINI_API_KEY)'),
        DeclareLaunchArgument('use_moveit', default_value='true',
                              description='Launch MoveIt move_group for arm planning'),
        OpaqueFunction(function=_entities),
    ])


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='H1-2 hardware launch plan (dry-run only; use ros2 launch to run)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the planned node graph and exit')
    args = parser.parse_args()
    if args.dry_run:
        print(_format_plan())
        return 0
    parser.error('run via: ros2 launch h1_bringup hardware.launch.py [dry_run:=true]')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())