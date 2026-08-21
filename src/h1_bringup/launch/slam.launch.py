import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, LogInfo, RegisterEventHandler
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    pkg_bringup = get_package_share_directory('h1_bringup')

    slam_params_file = LaunchConfiguration('slam_params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')

    declare_slam_params_file_cmd = DeclareLaunchArgument(
        'slam_params_file',
        default_value=os.path.join(pkg_bringup, 'config', 'mapper_params_online_async.yaml'),
        description='Full path to the ROS2 parameters file for slam_toolbox')

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation (Gazebo) clock if true')

    lidar_frame_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='lidar_frame_static_tf',
        arguments=['--frame-id', 'lidar_link', '--child-frame-id', 'h1_ign/lidar_link/lidar',
                   '--x', '0', '--y', '0', '--z', '0', '--yaw', '0', '--pitch', '0', '--roll', '0'],
        output='screen',
    )

    slam_toolbox_node = LifecycleNode(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[
            slam_params_file,
            {'use_sim_time': use_sim_time}
        ],
        namespace='',
        remappings=[
            ('/scan', '/h1/lidar/scan'),
        ],
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(slam_toolbox_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=slam_toolbox_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[
                LogInfo(msg="[LifecycleLaunch] Slamtoolbox node is activating."),
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(slam_toolbox_node),
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        )
    )

    return LaunchDescription([
        declare_slam_params_file_cmd,
        declare_use_sim_time_cmd,
        slam_toolbox_node,
        lidar_frame_tf,
        configure_event,
        activate_event,
    ])