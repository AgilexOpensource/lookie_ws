cmake_minimum_required(VERSION 3.8)
project(camera_compress_transport)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(image_transport REQUIRED)
find_package(OpenCV REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(pluginlib REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)

pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0)

add_library(${PROJECT_NAME} SHARED
  src/camera_compress_publisher.cpp
  src/camera_compress_subscriber.cpp
  src/depth_rvl_compress_publisher.cpp
  src/depth_rvl_compress_subscriber.cpp
  src/depth_png_compress_publisher.cpp
  src/depth_png_compress_subscriber.cpp
  src/vaapi_publisher.cpp
  src/vaapi_subscriber.cpp
)

target_include_directories(${PROJECT_NAME} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

target_link_libraries(${PROJECT_NAME} ${OpenCV_LIBRARIES} PkgConfig::GST)

ament_target_dependencies(${PROJECT_NAME}
  cv_bridge
  image_transport
  pluginlib
  rclcpp
  sensor_msgs
)

install(TARGETS ${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)

install(DIRECTORY include/
  DESTINATION include
)

pluginlib_export_plugin_description_file(image_transport camera_compress_plugins.xml)

ament_package()
