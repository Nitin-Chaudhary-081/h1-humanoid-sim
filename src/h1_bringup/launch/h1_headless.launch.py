import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('h1_bringup')
    pkg_gazebo = get_package_share_directory('ros_gz_h1_gazebo')
    pkg_description = get_package_share_directory('ros_gz_h1_description')
    pkg_ros_gz_sim = get_package_share_directory('ros_gz_sim')

    urdf_file = os.path.join(pkg_description, 'models/h1_ign', 'h1_2_handless.urdf')
    with open(urdf_file, 'r') as infp:
        urdf_description = infp.read()

    world = os.path.join(pkg_bringup, 'worlds', 'empty_h1_lidar.sdf')

    gz_args = LaunchConfiguration('gz_args')
    rviz = LaunchConfiguration('rviz')
    slam = LaunchConfiguration('slam')
    nav2 = LaunchConfiguration('nav2')

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')),
        launch_arguments={'gz_args': gz_args}.items(),
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='both',
        parameters=[
            {'use_sim_time': True},
            {'robot_description': urdf_description},
        ],
    )

    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        parameters=[
            {'config_file': os.path.join(pkg_bringup, 'config', 'ros_gz_h1_bridge.yaml'),
             'qos_overrides./tf_static.publisher.durability': 'transient_local'},
        ],
        output='screen',
    )

    foxglove = Node(
        package='foxglove_bridge',
        executable='foxglove_bridge',
        name='foxglove_bridge',
        output='screen',
        parameters=[{'port': 8765, 'address': '0.0.0.0'}],
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        arguments=['-d', os.path.join(pkg_bringup, 'config', 'check_joints_gz.rviz')],
        condition=IfCondition(rviz),
    )

    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'slam.launch.py')),
        launch_arguments={
            'use_sim_time': 'true',
            'slam_params_file': os.path.join(pkg_bringup, 'config', 'mapper_params_online_async.yaml'),
        }.items(),
        condition=IfCondition(slam),
    )

    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'nav2.launch.py')),
        launch_arguments={
            'use_sim_time': 'true',
            'nav2_params_file': os.path.join(pkg_bringup, 'config', 'nav2_params.yaml'),
            'autostart': 'true',
        }.items(),
        condition=IfCondition(nav2),
    )

    return LaunchDescription([
        SetEnvironmentVariable('LIBGL_ALWAYS_SOFTWARE', '1'),
        DeclareLaunchArgument('gz_args', default_value=f'-s -r --headless-rendering {world}',
                              description='Arguments passed to gz sim (default: server-only headless auto-start)'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('slam', default_value='false', description='Enable SLAM'),
        DeclareLaunchArgument('nav2', default_value='false', description='Enable Nav2'),
        gz_sim,
        robot_state_publisher,
        bridge,
        foxglove,
        rviz_node,
        slam_launch,
        nav2_launch,
    ])
