cmake_minimum_required(VERSION 3.8)
project(launch_control_msgs)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/LaunchStatus.msg"
  "srv/LaunchNode.srv"
  "srv/SetEmpty.srv"
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
