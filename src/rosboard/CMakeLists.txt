cmake_minimum_required(VERSION 3.12)
project(rosboard)

find_package(ament_cmake REQUIRED)

if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/bin/startup")
  message(FATAL_ERROR "Copy the prebuilt binary to rosboard/bin/startup before building")
endif()

file(GLOB_RECURSE ROSBOARD_SHELL_SCRIPTS CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/shell/*")
set(ROSBOARD_SHELL_PROGRAMS)
foreach(script ${ROSBOARD_SHELL_SCRIPTS})
  if(NOT IS_DIRECTORY "${script}")
    get_filename_component(script_name "${script}" NAME)
    if(NOT script_name MATCHES "^\\.")
      list(APPEND ROSBOARD_SHELL_PROGRAMS "${script}")
    endif()
  endif()
endforeach()

install(PROGRAMS bin/startup ${ROSBOARD_SHELL_PROGRAMS}
  DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
install(DIRECTORY config/ DESTINATION share/${PROJECT_NAME}/config)

ament_package()
