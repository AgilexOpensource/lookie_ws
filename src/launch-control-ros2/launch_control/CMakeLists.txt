cmake_minimum_required(VERSION 3.8)
project(launch_control)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(ament_cmake REQUIRED)
find_package(launch_control_msgs REQUIRED)

install(PROGRAMS
  scripts/launch_control.py
  DESTINATION lib/${PROJECT_NAME}
)

# BEGIN legacy installation (kept for comparison)
# install(PROGRAMS
#   shell/run.sh
#   DESTINATION lib/${PROJECT_NAME}
# )
# END legacy installation
# New implementation: generate the installed entry point and deployment unit.
include(cmake/generate_service.cmake)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY service
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
