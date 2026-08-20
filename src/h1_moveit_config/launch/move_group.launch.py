"""Launch file for MoveIt2 move_group with H1-2 configuration."""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare launch arguments
    use_sim_time_arg = DeclareLaunchArgument(
        "use_sim_time",
        default_value="true",
        description="Use simulation (Gazebo) clock if true",
    )

    # Get package share directories
    h1_moveit_config_share = FindPackageShare("h1_moveit_config")
    h1_description_share = FindPackageShare("ros_gz_h1_description")

    # Config file paths
    srdf_file = PathJoinSubstitution([h1_moveit_config_share, "config", "h1_2.srdf"])
    kinematics_file = PathJoinSubstitution([h1_moveit_config_share, "config", "kinematics.yaml"])
    joint_limits_file = PathJoinSubstitution([h1_moveit_config_share, "config", "joint_limits.yaml"])
    ompl_planning_file = PathJoinSubstitution([h1_moveit_config_share, "config", "ompl_planning.yaml"])
    pilz_cartesian_file = PathJoinSubstitution([h1_moveit_config_share, "config", "pilz_cartesian_limits.yaml"])
    moveit_cpp_file = PathJoinSubstitution([h1_moveit_config_share, "config", "moveit_cpp.yaml"])

    # URDF file path
    urdf_file = PathJoinSubstitution([h1_description_share, "models/h1_ign", "h1_2_handless.urdf"])

    def create_move_group_node(context):
        """Create move_group node with all parameters."""
        use_sim_time = LaunchConfiguration("use_sim_time").perform(context) == "true"

        # Load URDF content
        urdf_path = urdf_file.perform(context)
        with open(urdf_path, 'r') as f:
            urdf_content = f.read()

        return Node(
            package="moveit_ros_move_group",
            executable="move_group",
            name="move_group",
            output="screen",
            parameters=[
                # Robot description (URDF)
                {"robot_description": urdf_content},
                # Semantic description (SRDF)
                {"robot_description_semantic": srdf_file.perform(context)},
                # Kinematics
                {"robot_description_kinematics": kinematics_file.perform(context)},
                # Joint limits
                {"robot_description_planning": joint_limits_file.perform(context)},
                # OMPL planning
                {"ompl_planning": ompl_planning_file.perform(context)},
                # Pilz Cartesian limits
                {"pilz_cartesian_limits": pilz_cartesian_file.perform(context)},
                # MoveItCpp config
                {"moveit_cpp": moveit_cpp_file.perform(context)},
                # Use sim time
                {"use_sim_time": use_sim_time},
                # Planning scene monitor
                {"planning_scene_monitor/publish_planning_scene": True},
                {"planning_scene_monitor/publish_geometry_updates": True},
                {"planning_scene_monitor/publish_state_updates": True},
                {"planning_scene_monitor/publish_transforms_updates": True},
                # Trajectory execution
                {"trajectory_execution/allowed_execution_duration_scaling": 1.2},
                {"trajectory_execution/allowed_goal_duration_margin": 0.5},
                {"trajectory_execution/allowed_start_tolerance": 0.01},
                # Capabilities
                {"capabilities": "move_group/MoveGroupCartesianPathService "
                                 "move_group/MoveGroupExecuteTrajectoryAction "
                                 "move_group/MoveGroupGetPlanningSceneService "
                                 "move_group/MoveGroupKinematicsService "
                                 "move_group/MoveGroupMoveAction "
                                 "move_group/MoveGroupPlanService "
                                 "move_group/MoveGroupQueryPlannersService "
                                 "move_group/MoveGroupStateValidationService"},
                # Disable certain capabilities to reduce overhead
                {"disable_capabilities": "move_group/MoveGroupGetControllerInfoService"},
            ],
            arguments=["--ros-args", "--log-level", "info"],
        )

    return LaunchDescription([
        use_sim_time_arg,
        OpaqueFunction(function=create_move_group_node),
    ])