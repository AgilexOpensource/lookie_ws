cmake_minimum_required(VERSION 3.8)
project(realsense_manager_msgs)

# Colcon forwards this workspace-wide option to every CMake package.
option(USE_LIFECYCLE_NODE "Unused compatibility option" OFF)

find_package(ament_cmake REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AliasCamera.msg"
  "msg/AliasConfig.msg"
  "msg/AliasInventory.msg"
  "msg/AliasStatus.msg"
  "msg/Device.msg"
  "msg/DeviceInfo.msg"
  "msg/DeviceInventory.msg"
  "msg/DeviceStatus.msg"
  "msg/ManagerEvent.msg"
  "srv/BindByUsb.srv"
  "srv/BindCamera.srv"
  "srv/CreateAlias.srv"
  "srv/DeleteAlias.srv"
  "srv/QueryAliases.srv"
  "srv/QueryDevices.srv"
  "srv/RenameAlias.srv"
  "srv/SetCameraParameters.srv"
  "srv/SetCameraProfile.srv"
  "srv/SetExpectedUsbPath.srv"
  "srv/UnbindCamera.srv"
  "srv/UpdateAlias.srv"
  DEPENDENCIES rcl_interfaces std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
