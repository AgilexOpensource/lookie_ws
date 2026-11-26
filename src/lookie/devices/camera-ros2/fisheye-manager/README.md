# Fisheye Manager

`fisheye-manager` 为 DECXIN USB 鱼眼相机提供持久化 alias 配置、设备枚举、USB 路径绑定、参数管理和 YAML 驱动的多相机启动。

该目录包含两个 ROS 2 包：

| 包 | 功能 |
|---|---|
| `fisheye_manager_msgs` | Manager 使用的消息与服务接口 |
| `fisheye_manager` | Python Manager 节点、YAML 存储和 launch 文件 |

驱动仍是独立的 `fisheye_ros2`。Manager 只写 YAML 并 Include `fisheye_ros2/fisheye_camera_node.launch.py`，不修改驱动包。

**注意：运行多相机 launch 前，需要先 source 已安装 `fisheye_ros2` 的工作空间。**

## 和 RealSense Manager 的差异

DECXIN 鱼眼的 `serial` 经常重复，不能当绑定键。本包用 `expected_usb_path` 作为打开设备的主键：

- 已绑定：`expected_usb_path` 非空
- `bind_camera` / `set_expected_usb_path` 写的是 YAML 里的 `expected_usb_path`，不是驱动参数列表里的 `usb_path`
- 多相机 launch 读取 `expected_usb_path`，再把它作为驱动 launch 参数 `usb_path` 传入

## 编译

```bash
cd /home/agilex/develop/camera_ros_rs/rs2_master3
source /opt/ros/humble/setup.bash
colcon build --packages-up-to fisheye_manager
source install/setup.bash
```

## 配置文件

默认路径：

```text
~/.config/fisheye_manager/cameras.yaml
```

文件不存在时 Manager 会自动创建：

```yaml
schema_version: 1
revision: 0
cameras: {}
```

完整示例：

```yaml
schema_version: 1
revision: 3
cameras:
  fisheye:
    enabled: true
    expected_usb_path: 1-10.1:1.0
    parameters:
      camera_name: camera_fisheye
      camera_namespace: ''
      camera_fps: 30
      camera_height: 480
      camera_width: 640
```

| 字段 | 含义 |
|---|---|
| `enabled` | multi-camera launch 是否创建该节点 |
| `expected_usb_path` | 绑定用的稳定 USB 物理路径。启动多相机时由 launch 填进驱动参数 `usb_path`，不要写进 `parameters` |
| `parameters` | 传给 `fisheye_camera_node.launch.py` 的驱动参数，例如 `camera_name`、`camera_fps` |

所有 alias 的 `camera_name` 必须全局唯一。同一个 `expected_usb_path` 也不能分给两个 alias。

## 启动 Manager

```bash
ros2 launch fisheye_manager fisheye_manager.launch.py
```

启动日志会打印包版本，例如 `Fisheye Manager v0.1.0 (fisheye_manager_msgs v0.1.0)`。也可以用 ROS 指令查询已安装版本：

```bash
ros2 pkg xml fisheye_manager -t version
ros2 pkg xml fisheye_manager_msgs -t version
```

指定配置文件：

```bash
ros2 launch fisheye_manager fisheye_manager.launch.py \
  config_file:=/home/agilex/camera_config/fisheye_cameras.yaml
```

## Topic

节点名默认为 `/fisheye_manager`。

| Topic | 类型 | 发布时机 |
|---|---|---|
| `~/device_inventory` | `fisheye_manager_msgs/msg/DeviceInventory` | `query_devices` 成功后 |
| `~/alias_inventory` | `fisheye_manager_msgs/msg/AliasInventory` | `query_aliases` 后 |
| `~/events` | `fisheye_manager_msgs/msg/ManagerEvent` | CRUD、绑定和参数修改后 |

`device_inventory` 和 `alias_inventory` 使用 Reliable + Transient Local，深度 1。

## Service

| Service | 功能 |
|---|---|
| `~/query_devices` | 枚举当前 DECXIN 鱼眼（udevadm + VID:PID 过滤） |
| `~/query_aliases` | 读取 YAML alias |
| `~/create_alias` | 新增 alias |
| `~/delete_alias` | 删除 alias |
| `~/rename_alias` | 修改 alias 键名 |
| `~/update_alias` | 修改节点名、命名空间和启用状态 |
| `~/bind_camera` | 把 alias 绑定到 `expected_usb_path` |
| `~/unbind_camera` | 清除 `expected_usb_path` |
| `~/set_expected_usb_path` | 设置或清除预期 USB 路径 |
| `~/set_camera_parameters` | 写入任意类型化驱动参数 |

查询当前设备：

```bash
ros2 service call /fisheye_manager/query_devices \
  fisheye_manager_msgs/srv/QueryDevices \
  "{request_id: device_query_001}"
```

创建并绑定：

```bash
ros2 service call /fisheye_manager/create_alias \
  fisheye_manager_msgs/srv/CreateAlias \
  "{alias: fisheye, camera_name: camera_fisheye, camera_namespace: ''}"

ros2 service call /fisheye_manager/bind_camera \
  fisheye_manager_msgs/srv/BindCamera \
  "{alias: fisheye, expected_usb_path: '1-10.1:1.0', require_present: true}"
```

这里的 `expected_usb_path` 是 YAML 绑定字段，来自 `query_devices` 或 `ros2 run fisheye_ros2 camera_scan.py list` 的 USB Path。它不是 `set_camera_parameters` 里的驱动参数。managed launch 启动相机时会把它转成驱动的 `usb_path`。

设置分辨率和帧率：

```bash
ros2 service call /fisheye_manager/set_camera_parameters \
  fisheye_manager_msgs/srv/SetCameraParameters \
  "{alias: fisheye, parameters: [
    {name: camera_width, value: {type: 2, integer_value: 640}},
    {name: camera_height, value: {type: 2, integer_value: 480}},
    {name: camera_fps, value: {type: 2, integer_value: 30}}
  ]}"
```

参数服务只更新 YAML，成功响应里的 `restart_required` 为 `true`。重新启动 multi-camera launch 后生效。

## 启动多台相机

```bash
ros2 launch fisheye_manager managed_multi_camera.launch.py
```

launch 只启动同时满足以下条件的 alias：

- `enabled: true`
- `expected_usb_path` 非空

每台相机 Include 一次 `fisheye_ros2/fisheye_camera_node.launch.py`。YAML 中未在驱动 `configurable_parameters` 声明的参数会在启动任何相机前报错。

单相机仍可直接使用驱动：

```bash
ros2 launch fisheye_ros2 fisheye_camera_node.launch.py
```

## 测试

```bash
colcon test --packages-select fisheye_manager fisheye_manager_msgs
colcon test-result --verbose
```
