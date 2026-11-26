cmake_minimum_required(VERSION 3.8)
project(fisheye_ros2)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)

install(PROGRAMS 
    scripts/camera_scan.py
    scripts/camera_info_tools.py
    scripts/models.py
    scripts/read_camera_node.py
    scripts/resolver.py
    scripts/scanner.py
    scripts/utils.py
    scripts/yaml_manager.py
    DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch
  config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
