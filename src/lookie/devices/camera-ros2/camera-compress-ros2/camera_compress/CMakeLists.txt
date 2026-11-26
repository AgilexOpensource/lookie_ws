cmake_minimum_required(VERSION 3.8)
project(camera_compress)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(OpenCV REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)

pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0)

add_executable(vaapi_compress src/vaapi_compress.cpp)
target_link_libraries(vaapi_compress ${OpenCV_LIBRARIES} PkgConfig::GST)
ament_target_dependencies(vaapi_compress
  cv_bridge
  rclcpp
  sensor_msgs
)

install(TARGETS vaapi_compress
  DESTINATION lib/${PROJECT_NAME}
)

file(GLOB PYTHON_SCRIPTS CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/scripts/*.py"
)
if(PYTHON_SCRIPTS)
  install(PROGRAMS ${PYTHON_SCRIPTS}
    DESTINATION lib/${PROJECT_NAME}
  )
endif()

install(DIRECTORY include/
  DESTINATION include
  PATTERN ".gitkeep" EXCLUDE
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
  PATTERN ".gitkeep" EXCLUDE
  PATTERN "__pycache__" EXCLUDE
)

install(FILES README.md
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
