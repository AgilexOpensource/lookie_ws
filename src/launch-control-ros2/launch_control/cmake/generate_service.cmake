# Keep the original shell/run.sh and service/*.service as legacy examples.
execute_process(COMMAND id -un OUTPUT_VARIABLE _build_user
  OUTPUT_STRIP_TRAILING_WHITESPACE RESULT_VARIABLE _user_result)
if(NOT _user_result EQUAL 0)
  message(FATAL_ERROR "Cannot determine build user")
endif()
set(LAUNCH_CONTROL_SERVICE_USER "${_build_user}" CACHE STRING
  "Account used by the generated systemd service")
if(NOT LAUNCH_CONTROL_SERVICE_USER MATCHES "^[a-zA-Z_][a-zA-Z0-9_-]*[$]?$")
  message(FATAL_ERROR "Invalid LAUNCH_CONTROL_SERVICE_USER")
endif()

# Standard colcon isolated install: <install-base>/<package>.
# Standard merged install: <install-base>.
get_filename_component(_prefix_name "${CMAKE_INSTALL_PREFIX}" NAME)
if(_prefix_name STREQUAL "${PROJECT_NAME}")
  get_filename_component(_install_base "${CMAKE_INSTALL_PREFIX}" DIRECTORY)
else()
  set(_install_base "${CMAKE_INSTALL_PREFIX}")
endif()
set(LAUNCH_CONTROL_SETUP "${_install_base}/setup.bash" CACHE FILEPATH
  "Absolute path to the colcon workspace setup.bash (created after build)")
if(NOT IS_ABSOLUTE "${LAUNCH_CONTROL_SETUP}")
  message(FATAL_ERROR "LAUNCH_CONTROL_SETUP must be absolute")
endif()
# Fail explicitly for characters needing shell/systemd-specific escaping.
foreach(_path IN ITEMS "${CMAKE_INSTALL_PREFIX}" "${LAUNCH_CONTROL_SETUP}")
  if(_path MATCHES "[\n\r\t\"'`$%;\\\\]")
    message(FATAL_ERROR "Unsupported character in deployment path: ${_path}")
  endif()
endforeach()

file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated")
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/shell/run.sh.in"
  "${CMAKE_CURRENT_BINARY_DIR}/generated/run.sh" @ONLY)
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/service/launch_control.service.in"
  "${CMAKE_CURRENT_BINARY_DIR}/generated/launch_control.service" @ONLY)
install(PROGRAMS "${CMAKE_CURRENT_BINARY_DIR}/generated/run.sh"
  DESTINATION lib/${PROJECT_NAME})
# Separate destination: do not overwrite either legacy service file.
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/generated/launch_control.service"
  DESTINATION share/${PROJECT_NAME}/service/generated)
message(STATUS "launch_control service user: ${LAUNCH_CONTROL_SERVICE_USER}")
message(STATUS "launch_control setup: ${LAUNCH_CONTROL_SETUP}")
