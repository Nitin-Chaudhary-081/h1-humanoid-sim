cmake_minimum_required(VERSION 3.8)
project(h1_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/ControlState.msg"
  "msg/TelemetrySample.msg"
  "msg/Alert.msg"
  "msg/PerceptionFrame.msg"
  "msg/PerceptionDetection.msg"
  "action/RobotCommand.action"
  "action/GraspExecute.action"
  DEPENDENCIES builtin_interfaces geometry_msgs std_msgs trajectory_msgs
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
