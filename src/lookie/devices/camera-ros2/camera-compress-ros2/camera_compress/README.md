# camera_compress

ROS 2 的 `ament_cmake` 包，包含两个独立 Python 压缩脚本，并预留 C++ 节点目录。

## 目录

```text
camera_compress/
  CMakeLists.txt
  package.xml
  include/camera_compress/   # C++ 头文件
  src/                      # C++ 源文件
  scripts/                  # 独立 Python 可执行脚本
  launch/                   # ROS 2 launch 文件
  config/                   # 参数及配置文件
```

## Python 脚本

`scripts/` 已包含 `compress_camera.py` 和 `compress_camera2.py`，入口使用 `#!/usr/bin/env python3`。
CMake 会自动安装该目录下的 `.py` 文件并赋予执行权限，不需要 `setup.py` 或 `ament_cmake_python`。
在工作空间根目录构建并加载安装环境：

```bash
colcon build --packages-select camera_compress
source install/setup.bash
```

脚本一同时压缩彩色图像和对齐深度图像，默认命名空间为 `camera_left`：

```bash
ros2 run camera_compress compress_camera.py --ros-args -p topic_namespace:=camera_left
```

输入话题分别为 `/camera_left/color/image_rect_raw` 和 `/camera_left/aligned_depth_to_color/image_raw`。
彩色图像编码为 JPEG，深度图像编码为 PNG，输出话题是在对应输入话题后追加 `/compressed`。

脚本二支持分别开关彩色和深度压缩，默认 `compress_rgb=true`、`compress_depth=false`、`topic_name=image_raw`：

```bash
ros2 run camera_compress compress_camera2.py --ros-args \
  -p topic_namespace:=camera_left \
  -p compress_rgb:=true \
  -p compress_depth:=false \
  -p topic_name:=image_raw
```

脚本二的输入话题按 `<topic_namespace>/color/<topic_name>` 和
`<topic_namespace>/aligned_depth_to_color/<topic_name>` 构造，输出同样追加 `/compressed`。
其话题名称是相对名称；需要固定到根命名空间时，使用以 `/` 开头的 `topic_namespace`。

通常选择一个脚本运行。两者默认节点名均为 `compress_camera_node`；若要同时运行，
应通过 `-r __node:=<不同节点名>` 区分节点，并使用不同相机话题，避免重复发布。

`package.xml` 已声明 `rclpy`、`sensor_msgs`、`cv_bridge` 和 `python3-opencv` 运行依赖。
新增或修改脚本后需重新构建；后续引入其他库时也需补充对应依赖。
如果以后需要可导入的 Python 模块包，再引入 `ament_cmake_python`，并创建对应模块目录。

## C++ 节点

`src/vaapi_compress.cpp` 是独立节点，不走 `image_transport`。彩色图优先用 VA-API JPEG，失败再退回软件编码；对齐深度用 PNG。

```bash
ros2 run camera_compress vaapi_compress --ros-args -p topic_namespace:=camera/camera
```

默认 `topic_namespace=camera_left`，`jpeg_quality=90`，`png_compression=1`。输入话题是 `/<topic_namespace>/color/image_rect_raw` 和 `/<topic_namespace>/aligned_depth_to_color/image_raw`，输出在对应话题后加 `/compressed`。

`image_transport` 插件在旁边的 `camera_compress_transport` 包里，话题后缀是 `camera_compress` 和 `vaapi_compress`。
