cmake_minimum_required(VERSION 3.8)
project(realsense_manager)

option(USE_LIFECYCLE_NODE "Enable lifecycle manager and camera nodes" OFF)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

if(USE_LIFECYCLE_NODE)
  set(USE_LIFECYCLE_VALUE true)
else()
  set(USE_LIFECYCLE_VALUE false)
endif()

configure_file(
  config/global_settings.yaml.in
  ${CMAKE_CURRENT_BINARY_DIR}/global_settings.yaml
  @ONLY
)

install(PROGRAMS
  scripts/realsense_manager_node
  scripts/realsense_lifecycle_manager_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch DESTINATION share/${PROJECT_NAME}
  PATTERN "__pycache__" EXCLUDE
)
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/../README.md
  DESTINATION share/${PROJECT_NAME}
)
install(FILES
  config/cameras.yaml
  ${CMAKE_CURRENT_BINARY_DIR}/global_settings.yaml
  DESTINATION share/${PROJECT_NAME}/config
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_config_store test/test_config_store.py)
  ament_add_pytest_test(test_device_enumerator test/test_device_enumerator.py)
  ament_add_pytest_test(test_package_info test/test_package_info.py)
endif()

ament_package()
