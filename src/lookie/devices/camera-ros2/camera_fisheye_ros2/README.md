<a id="fisheye_ros2-usb-fisheye-camera-ros2-driver"></a>

# fisheye_ros2 USB Fisheye Camera ROS2 Driver

| ROS | Status |
| --- | --- |
| ![humble](https://img.shields.io/badge/ros-humble-blue.svg) | ![Pass](https://img.shields.io/badge/Pass-blue.svg) |
| ![jazzy](https://img.shields.io/badge/ros-jazzy-blue.svg) | ![Pass](https://img.shields.io/badge/Pass-blue.svg) |

## Overview

`fisheye_ros2` is a ROS2 driver package for DECXIN USB fisheye cameras. It provides camera startup, image publishing, TF publishing, automatic reconnection, runtime FPS diagnostics, and fisheye camera scanning tools.

This package is dedicated to the following device and does not list other USB capture cameras:

| Product | VID:PID |
| --- | --- |
| `DECXIN  CAMERA: DECXIN  CAMERA` | `1bcf:2cd1` |

The package focuses on solving unstable `/dev/videoX` numbering on Linux. The scanner reads `udevadm` information, lists only DECXIN fisheye cameras matching the device information above, and prints key fields such as `USB Path`, `Product`, `VID:PID`, and `Serial`. This helps confirm camera connections and configuration parameters during deployment.

## Table of Contents

- [Switch to 中文](#fisheye_ros2-usb-鱼眼相机-ros2-驱动)
- [Overview](#overview)
- [Requirements](#requirements)
- [Package Structure](#package-structure)
- [Quick Start](#quick-start)
- [Scan DECXIN Fisheye Cameras](#scan-decxin-fisheye-cameras)
- [Camera Configuration](#camera-configuration)
- [Start the Camera Node](#start-the-camera-node)
- [Node Parameters](#node-parameters)
- [Published Topics and TF](#published-topics-and-tf)
- [FAQ](#faq)
- [Maintenance Notes](#maintenance-notes)

## Requirements

- Ubuntu Linux
- ROS2 Humble or Jazzy
- Python 3
- DECXIN USB V4L2 fisheye camera: `DECXIN  CAMERA: DECXIN  CAMERA`, `1bcf:2cd1`
- System command: `udevadm`

ROS2 dependencies are declared in `package.xml`:

- `rclpy`
- `sensor_msgs`
- `cv_bridge`
- `tf2_ros`
- `geometry_msgs`
- `ament_index_python`
- `launch`
- `launch_ros`

## Package Structure

```text
fisheye-ros2/
├── CMakeLists.txt
├── package.xml
├── README.md
├── config/
│   └── cameras.yaml
├── launch/
│   └── read_camera.launch.py
└── scripts/
    ├── camera_scan.py
    ├── camera_info_tools.py
    ├── models.py
    ├── read_camera_node.py
    ├── resolver.py
    ├── scanner.py
    ├── utils.py
    └── yaml_manager.py
```

## Quick Start

### 1. Build the Workspace

Run from the `camera_ros` workspace root:

```bash
colcon build --packages-select fisheye_ros2
source install/setup.bash
```

### 2. Scan DECXIN Fisheye Cameras

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

You can also run the script directly with Python:

```bash
python3 src/fisheye-ros2/scripts/camera_scan.py list
```

### 3. Start the Camera Node

```bash
ros2 launch fisheye_ros2 read_camera.launch.py camera_alias:=fisheye
```

## Scan DECXIN Fisheye Cameras

The recommended command is `camera_scan.py`:

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

Example output:

```text
===========  =======  =========  ==============================  =========  ========
Video        Alias    USB Path   Product                         VID:PID    Serial
===========  =======  =========  ==============================  =========  ========
/dev/video0  fisheye  1-10.1:1.0  DECXIN  CAMERA: DECXIN  CAMERA  1bcf:2cd1  01.00.00
===========  =======  =========  ==============================  =========  ========
```

`Video` and `USB Path` change with the current device connection state. Use the actual output of `camera_scan.py list` on your machine.

Field descriptions:

| Field | Description |
| --- | --- |
| `Video` | Current system video device node, for example `/dev/video8` |
| `Alias` | Alias bound to this `USB Path` in `config/cameras.yaml`; shows `none` if not bound |
| `USB Path` | Physical USB path parsed from udev `ID_PATH` |
| `Product` | Camera product name |
| `VID:PID` | USB vendor ID and product ID |
| `Serial` | USB serial number, which may be empty on some cameras |

Filtering rules:

- The device must be a `/dev/video*` device that supports capture.
- `Product` must be `DECXIN  CAMERA: DECXIN  CAMERA`.
- `VID:PID` must be `1bcf:2cd1`.
- Cameras that do not match these conditions are not shown in scan results and are not used for alias resolution.

Available subcommands:

| Command | Description |
| --- | --- |
| `list` | List current capture-capable DECXIN fisheye cameras |
| `init` | Interactively generate `config/cameras.yaml` |
| `update` | Update `config/cameras.yaml` from current scan results |
| `check` | Check whether configured cameras exist |
| `resolve <alias>` | Resolve a camera alias to the current `/dev/videoX` |
| `doctor` | Print diagnostic information |

### Subcommand Details

#### `list`

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

`list` shows all current capture-capable DECXIN fisheye video devices. It does not modify any configuration file; it only reads `/dev/video*`, udev properties, and the optional `config/cameras.yaml`.

Why use it:

- Confirm whether the DECXIN fisheye camera is detected before deployment.
- Find the current real `/dev/videoX` to verify alias resolution and device connection state.
- View `USB Path`, `Product`, `VID:PID`, and `Serial` to confirm the device is the target fisheye camera.
- Check whether the device has already been bound to an alias in `config/cameras.yaml`; without a config file or matching alias, it shows `none`.

Useful with:

- `read_camera_node.py`: confirm that aliases in `config/cameras.yaml` resolve to current devices.
- `init`: list devices first, then generate alias configuration.
- Startup troubleshooting: run `list` first when the camera node fails to start.

#### `init`

```bash
ros2 run fisheye_ros2 camera_scan.py init
```

`init` creates or maintains `config/cameras.yaml`. It scans only current capture-capable DECXIN fisheye cameras and interactively asks for an alias for each camera, such as `fisheye`, `front`, or `rear`.

Why use it:

- `/dev/videoX` can change with boot order or plug order, while `USB Path` is better for recording the physical USB connection.
- An alias is easier to use and hand over than `/dev/videoX`; for example, use `fisheye` consistently for the fisheye camera.
- The resulting configuration can be reused by `resolve`, `check`, `doctor`, and `read_camera_node.py`.

Useful with:

- `list`: inspect device information first, then decide each camera alias.
- `resolve`: after generating configuration, resolve an alias to the current `/dev/videoX`.
- `check`: after generating configuration, check whether configured cameras are still online.

Notes:

- If `config/cameras.yaml` already exists, `init` asks you to choose `1. Add new cameras only` or `2. Overwrite and recreate`.
- Add mode skips cameras that already have aliases and asks only for newly inserted unconfigured cameras.
- Overwrite mode regenerates configuration from currently inserted cameras. Use it when old cameras were removed and replaced.
- After changing the physical USB port, `USB Path` may change. Use `update` or initialize the configuration again.

#### `update`

```bash
ros2 run fisheye_ros2 camera_scan.py update
```

`update` tries to update the saved `usb_path` in `config/cameras.yaml` after a camera has moved to another USB port.

Why use it:

- After deployment, the original `usb_path` may no longer be found if the camera was moved to another USB port.
- When a configured camera is missing, `update` tries to match the current scan results by `serial` or unique `product`, then asks whether to update the configuration.
- This is safer than editing YAML manually because changes are written only after interactive confirmation.

Useful with:

- `check`: run `check` first to find missing aliases, then run `update`.
- `doctor`: inspect detailed diagnostics first, then decide whether to update configuration.
- Hardware maintenance: after reconnecting or replacing cables, use `update` to fix configuration.

Notes:

- When multiple identical DECXIN fisheye cameras are connected, keep them on fixed physical USB ports and distinguish them by `USB Path`.
- If matching is uncertain, run `list` first and confirm the YAML manually.

#### `check`

```bash
ros2 run fisheye_ros2 camera_scan.py check
```

`check` verifies whether aliases configured in `config/cameras.yaml` can be found on the current system.

Why use it:

- Quickly determine whether the current hardware connection satisfies the project configuration.
- Check that cameras exist before starting ROS nodes, instead of finding device errors at runtime.
- CI, deployment scripts, or boot-time self-check scripts can call it for hardware health checks.

Useful with:

- `init`: check the configuration immediately after initialization.
- `launch`: run before starting the camera node.
- `doctor`: use `doctor` for more details when `check` fails.

Output meaning:

- `[ OK ]` means the alias resolved to a current `/dev/videoX`.
- `[ERROR]` means the configured `usb_path` currently has no matching device.

#### `resolve <alias>`

```bash
ros2 run fisheye_ros2 camera_scan.py resolve fisheye
```

`resolve` maps a camera alias from `config/cameras.yaml` to the current real `/dev/videoX`.

Why use it:

- Upper-level scripts do not need to hard-code `/dev/videoX`.
- After reboot changes `/dev/videoX`, the alias still resolves to the current device.
- It can be used in shell scripts, startup scripts, or debug commands.

Useful with:

- Shell variables: save the resolved result and pass it to other programs or debug scripts.
- `read_camera_node.py`: confirm the current device for a `camera_alias` before startup.
- Deployment scripts: dynamically check the target alias before startup.

Example:

```bash
VIDEO_DEV=$(ros2 run fisheye_ros2 camera_scan.py resolve fisheye)
echo "$VIDEO_DEV"
```

The recommended node `read_camera_node.py` uses `camera_alias`, so you usually do not need to pass `/dev/videoX` or a numeric device index manually.

#### `doctor`

```bash
ros2 run fisheye_ros2 camera_scan.py doctor
```

`doctor` prints more complete diagnostic information, including configured count, found count, missing count, and each alias's configured path and current device state.

Why use it:

- It is more useful than `check` for troubleshooting.
- It shows alias, configured `usb_path`, current device, product name, and capture status.
- It is useful for handover, field deployment, and remote support when describing camera connection state.

Useful with:

- `check`: `check` only reports OK or error; `doctor` provides details.
- `update`: confirm which configurations are missing before deciding whether to update `usb_path`.
- Project handover: include `doctor` output in issue descriptions to help others understand camera connections quickly.

## Camera Configuration

`config/cameras.yaml` stores camera aliases, physical USB paths, and device identification information. Current source configuration example:

```yaml
cameras:
  fisheye:
    usb_path: 1-10.1:1.0
    product: 'DECXIN  CAMERA: DECXIN  CAMERA'
    vendor: DECXIN_CAMERA
    vendor_id: 1bcf
    product_id: 2cd1
    serial: 01.00.00
```

Description:

- `fisheye` is the business alias used by `camera_alias:=fisheye` when starting the node.
- `usb_path` is related to the physical USB port and may change after moving the camera to another port.
- `product`, `vendor`, `vendor_id`, `product_id`, and `serial` come from udev information and are used for display, diagnostics, and assisted configuration updates.
- `read_camera_node.py` reads `cameras.yaml` through `camera_alias`, then automatically finds the current capture-capable DECXIN fisheye `/dev/videoX`.
- `cameras.yaml` uses a normal business configuration structure and should not be passed directly to the node as a ROS parameter YAML.

## Start the Camera Node

The recommended entry is `read_camera_node.py`. This node accepts `camera_alias`, reads `config/cameras.yaml`, finds the corresponding `usb_path`, scans current capture-capable DECXIN fisheye cameras, and resolves the real `/dev/videoX`.

Run directly:

```bash
ros2 run fisheye_ros2 read_camera_node.py --ros-args \
  -p camera_alias:=fisheye \
  -p camera_fps:=30 \
  -p camera_height:=480 \
  -p camera_width:=640 \
  -p camera_frame_id:=camera_fisheye \
  -p enable_fps_log:=false \
  -p reconnect_interval:=2.0
```

Use launch:

```bash
ros2 launch fisheye_ros2 read_camera.launch.py camera_alias:=fisheye
```

Enable periodic publisher-side FPS logs when diagnosing frame rate:

```bash
ros2 launch fisheye_ros2 read_camera.launch.py \
  camera_alias:=fisheye \
  enable_fps_log:=true \
  reconnect_interval:=2.0
```

Design rationale:

- Users only need to remember a business alias such as `fisheye` and do not need to handle `/dev/videoX` changes manually.
- The same configuration can be reused by `list`, `check`, `doctor`, `resolve`, and `read_camera_node.py`.
- For multiple cameras, start multiple nodes with different `camera_alias` values.
- If the configured camera is absent at startup or disconnects during operation, the node periodically resolves the alias again through its stable `usb_path` and resumes publishing after the device returns.

Runtime behavior:

- The node opens the resolved `/dev/videoX` through the V4L2 backend and requests MJPG, the configured resolution, and the configured frame rate.
- Image and camera-info publishers use `RELIABLE`, `VOLATILE`, depth-10 QoS.
- Three consecutive frame-read failures release the current device and enter the reconnect flow.
- Open, read-failure, reconnect, and FPS logs include `usb_path`; successful open logs also show the resolved device and negotiated format.

Duplicate startup policy:

- Different aliases can run at the same time for multi-camera use.
- If the same alias is already running, a later `read_camera_node.py` process detects the lock and exits. It does not replace the previous process and does not compete for the same camera.
- The default node name includes the process ID to avoid identical node names in the ROS graph when multiple instances are running.

## Node Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `camera_alias` | `fisheye` | Camera alias in `config/cameras.yaml` |
| `camera_fps` | `30` | Camera capture frame rate |
| `camera_height` | `480` | Image height |
| `camera_width` | `640` | Image width |
| `camera_frame_id` | Alias name | Camera TF frame prefix; launch default is `camera_fisheye` |
| `image_topic` | `/<alias>/color/image_raw` | Image topic |
| `camera_info_topic` | `/<alias>/color/camera_info` | Camera info topic |
| `enable_fps_log` | `false` | Enable periodic publisher-side FPS logs; exposed by the launch file |
| `fps_log_interval` | `1.0` | FPS log interval in seconds; minimum effective value is `0.1` |
| `reconnect_interval` | `2.0` | Device resolution retry interval in seconds; minimum effective value is `0.1`; exposed by the launch file |

## Published Topics and TF

| Type | Name | Description |
| --- | --- | --- |
| Topic | `/<alias>/color/image_raw` | Color image data, message type `sensor_msgs/msg/Image` |
| Topic | `/<alias>/color/camera_info` | Camera information, message type `sensor_msgs/msg/CameraInfo` |
| TF | `<camera_frame_id>` -> `<camera_frame_id>_color` | Camera color frame relation periodically published by the node |

## FAQ

### `ros2 run` Cannot Find the Script

Confirm that the workspace has been built and sourced:

```bash
colcon build --packages-select fisheye_ros2
source install/setup.bash
```

### The Node Cannot Open the Camera After Startup

If the alias exists in `config/cameras.yaml`, the node remains running and retries at `reconnect_interval`. Check the `reconnect attempt`, `camera not found`, and `failed to open` logs, which include the configured `usb_path`.

Also check:

- Whether `camera_alias` exists in `config/cameras.yaml`.
- Run `ros2 run fisheye_ros2 camera_scan.py resolve fisheye` to confirm that the alias resolves to the current real `/dev/videoX`.
- Whether the camera is occupied by another program.
- Whether the camera supports the configured resolution and frame rate.
- Whether the current user has permission to access `/dev/videoX`.

After the device becomes available again at the configured `usb_path`, publishing resumes automatically. If the camera was moved to another physical USB port, update `config/cameras.yaml` first.

### `camera_alias` Cannot Find a Camera

Check:

- Whether the alias exists in `config/cameras.yaml`.
- Run `ros2 run fisheye_ros2 camera_scan.py list` to confirm whether the corresponding `USB Path` is currently online.
- If the camera was moved to another USB port, run `camera_scan.py init` and choose add or overwrite, or use `update` to repair `usb_path`.

### Starting the Same Alias More Than Once

`read_camera_node.py` creates a runtime lock for each alias. If the same alias is already running, later startup exits and does not replace the previous node. Different aliases can run at the same time.

### `/dev/videoX` Changes After Reboot

Use the scanner first to confirm the current device:

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

If you need a stable identifier, use the `usb_path` and alias mechanism in `config/cameras.yaml` for diagnostics and resolution.

### Multiple DECXIN Fisheye Cameras Cannot Be Distinguished

If multiple DECXIN fisheye cameras have the same model and no unique serial number, relying only on `Product` is unreliable. Keep cameras on fixed physical USB ports and distinguish them by `USB Path`.

## Maintenance Notes

- Public documentation should only describe installation, configuration, running, and troubleshooting.
- After changing the package name, entry scripts, launch files, parameters, topics, or configuration fields, update this README accordingly.

---

<a id="fisheye_ros2-usb-鱼眼相机-ros2-驱动"></a>

# fisheye_ros2 USB 鱼眼相机 ROS2 驱动

| ROS | 状态 |
| --- | --- |
| ![humble](https://img.shields.io/badge/ros-humble-blue.svg) | ![Pass](https://img.shields.io/badge/Pass-blue.svg) |
| ![jazzy](https://img.shields.io/badge/ros-jazzy-blue.svg) | ![Pass](https://img.shields.io/badge/Pass-blue.svg) |

## 概述

`fisheye_ros2` 是一个面向 DECXIN USB 鱼眼相机的 ROS2 驱动包，提供相机启动、图像发布、TF 发布、自动重连、运行时 FPS 诊断，以及鱼眼相机扫描工具。

该包专用于以下设备，不再显示其它 USB capture 摄像头：

| Product | VID:PID |
| --- | --- |
| `DECXIN  CAMERA: DECXIN  CAMERA` | `1bcf:2cd1` |

该包的重点是辅助解决 Linux 下 `/dev/videoX` 编号不稳定的问题。扫描工具会读取 `udevadm` 信息，只列出匹配上述设备信息的 DECXIN 鱼眼相机，并输出 `USB Path`、`Product`、`VID:PID`、`Serial` 等关键信息，便于部署时确认相机和配置参数。

## 目录

- [切换到 English](#fisheye_ros2-usb-fisheye-camera-ros2-driver)
- [概述](#概述)
- [环境要求](#环境要求)
- [包结构](#包结构)
- [快速开始](#快速开始)
- [扫描 DECXIN 鱼眼相机](#扫描-decxin-鱼眼相机)
- [相机配置](#相机配置)
- [启动相机节点](#启动相机节点)
- [节点参数](#节点参数)
- [发布话题和 TF](#发布话题和-tf)
- [常见问题](#常见问题)
- [维护说明](#维护说明)

## 环境要求

- Ubuntu Linux
- ROS2 Humble 或 Jazzy
- Python 3
- DECXIN USB V4L2 鱼眼相机：`DECXIN  CAMERA: DECXIN  CAMERA`，`1bcf:2cd1`
- 系统命令：`udevadm`

ROS2 依赖由 `package.xml` 声明：

- `rclpy`
- `sensor_msgs`
- `cv_bridge`
- `tf2_ros`
- `geometry_msgs`
- `ament_index_python`
- `launch`
- `launch_ros`

## 包结构

```text
fisheye-ros2/
├── CMakeLists.txt
├── package.xml
├── README.md
├── config/
│   └── cameras.yaml
├── launch/
│   └── read_camera.launch.py
└── scripts/
    ├── camera_scan.py
    ├── camera_info_tools.py
    ├── models.py
    ├── read_camera_node.py
    ├── resolver.py
    ├── scanner.py
    ├── utils.py
    └── yaml_manager.py
```

## 快速开始

### 1. 编译工作空间

在 `camera_ros` 工作空间根目录执行：

```bash
colcon build --packages-select fisheye_ros2
source install/setup.bash
```

### 2. 扫描 DECXIN 鱼眼相机

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

也可以直接使用 Python 运行：

```bash
python3 src/fisheye-ros2/scripts/camera_scan.py list
```

### 3. 启动相机节点

```bash
ros2 launch fisheye_ros2 read_camera.launch.py camera_alias:=fisheye
```

## 扫描 DECXIN 鱼眼相机

推荐使用 `camera_scan.py`：

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

输出示例：

```text
===========  =======  =========  ==============================  =========  ========
Video        Alias    USB Path   Product                         VID:PID    Serial
===========  =======  =========  ==============================  =========  ========
/dev/video0  fisheye  1-10.1:1.0  DECXIN  CAMERA: DECXIN  CAMERA  1bcf:2cd1  01.00.00
===========  =======  =========  ==============================  =========  ========
```

其中 `Video` 和 `USB Path` 会随当前设备连接状态变化，实际值以本机 `camera_scan.py list` 输出为准。

字段说明：

| 字段 | 说明 |
| --- | --- |
| `Video` | 当前系统视频设备节点，例如 `/dev/video8` |
| `Alias` | `config/cameras.yaml` 中已绑定到该 `USB Path` 的别名；未绑定时显示 `none` |
| `USB Path` | 从 udev `ID_PATH` 解析出的 USB 物理路径 |
| `Product` | 相机产品名 |
| `VID:PID` | USB 厂商 ID 和产品 ID |
| `Serial` | USB 序列号，部分相机可能为空 |

筛选规则：

- 必须是支持 capture 的 `/dev/video*` 设备。
- `Product` 必须为 `DECXIN  CAMERA: DECXIN  CAMERA`。
- `VID:PID` 必须为 `1bcf:2cd1`。
- 不符合上述条件的摄像头不会出现在扫描结果中，也不会参与 alias 解析。

可用子命令：

| 命令 | 说明 |
| --- | --- |
| `list` | 列出当前可 capture 的 DECXIN 鱼眼相机 |
| `init` | 交互式生成 `config/cameras.yaml` |
| `update` | 根据当前扫描结果更新 `config/cameras.yaml` |
| `check` | 检查配置中的相机是否存在 |
| `resolve <alias>` | 将相机别名解析为当前 `/dev/videoX` |
| `doctor` | 输出诊断信息 |

### 子命令详细说明

#### `list`

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

`list` 用于查看当前系统中所有可 capture 的 DECXIN 鱼眼视频设备。它不会修改任何配置文件，只读取 `/dev/video*`、udev 属性和可选的 `config/cameras.yaml`。

为什么使用：

- 部署前先确认 DECXIN 鱼眼相机是否被系统识别。
- 查找当前真实的 `/dev/videoX`，用于确认 alias 解析结果和设备连接状态。
- 查看 `USB Path`、`Product`、`VID:PID`、`Serial`，便于确认设备确实是目标鱼眼相机。
- 查看该设备是否已经被 `config/cameras.yaml` 绑定 alias；没有配置文件或没有匹配 alias 时显示 `none`。

适合结合：

- 和 `read_camera_node.py` 结合：确认 `config/cameras.yaml` 中的 alias 能解析到当前真实设备。
- 和 `init` 结合：先用 `list` 确认设备，再用 `init` 生成别名配置。
- 和启动排障结合：相机节点启动失败时，先用 `list` 确认目标设备是否存在。

#### `init`

```bash
ros2 run fisheye_ros2 camera_scan.py init
```

`init` 用于创建或维护 `config/cameras.yaml`。执行后只会扫描当前可 capture 的 DECXIN 鱼眼相机，并通过交互方式让用户为每个相机输入 alias，例如 `fisheye`、`front`、`rear`。

为什么使用：

- `/dev/videoX` 会随启动顺序或插拔顺序变化，而 `USB Path` 更适合记录物理 USB 连接位置。
- alias 比 `/dev/videoX` 更适合项目配置和交接，例如统一使用 `fisheye` 表示鱼眼相机。
- 后续可以通过 `resolve`、`check`、`doctor` 使用这份配置做解析和诊断。

适合结合：

- 和 `list` 结合：先查看设备信息，再决定每个相机的 alias。
- 和 `resolve` 结合：生成配置后，可通过 alias 查找当前 `/dev/videoX`。
- 和 `check` 结合：生成配置后，检查配置中的相机是否仍然在线。

注意：

- 如果 `config/cameras.yaml` 已存在，`init` 会提示选择 `1. Add new cameras only` 或 `2. Overwrite and recreate`。
- 选择新增时，会跳过已经 alias 的相机，只为新插入且未配置的相机询问 alias。
- 选择覆盖时，会从当前已插入相机重新生成配置，适合旧相机全部拔掉并换成新相机的场景。
- 更换 USB 物理接口后，`USB Path` 可能变化，需要使用 `update` 或重新初始化配置。

#### `update`

```bash
ros2 run fisheye_ros2 camera_scan.py update
```

`update` 用于在相机 USB 位置发生变化后，尝试更新 `config/cameras.yaml` 中保存的 `usb_path`。

为什么使用：

- 项目部署后，如果相机换了 USB 口，原来的 `usb_path` 可能找不到。
- 当配置中的相机缺失时，`update` 会尝试根据 `serial` 或唯一的 `product` 匹配当前扫描到的相机，并询问是否更新。
- 这比手动编辑 YAML 更安全，因为用户可以在交互确认后再写入。

适合结合：

- 和 `check` 结合：先 `check` 发现某个 alias 丢失，再执行 `update`。
- 和 `doctor` 结合：先查看详细诊断，再决定是否更新配置。
- 和硬件维护流程结合：重新插拔或换线后，用 `update` 修复配置。

注意：

- 多个相同 DECXIN 鱼眼相机同时接入时，建议固定 USB 物理接口，并使用 `USB Path` 区分。
- 如果匹配不确定，应先用 `list` 查看鱼眼相机，再手动确认 YAML。

#### `check`

```bash
ros2 run fisheye_ros2 camera_scan.py check
```

`check` 用于检查 `config/cameras.yaml` 中配置的 alias 是否能在当前系统中找到对应相机。

为什么使用：

- 快速判断当前硬件连接是否满足项目配置要求。
- 启动 ROS 节点前先确认相机存在，减少运行时才发现设备错误的情况。
- CI、部署脚本或开机自检脚本可以调用它做硬件健康检查。

适合结合：

- 和 `init` 结合：初始化配置后立即检查配置是否可解析。
- 和 `launch` 结合：启动相机节点前先执行 `check`。
- 和 `doctor` 结合：`check` 失败时，用 `doctor` 查看更详细信息。

输出含义：

- `[ OK ]` 表示 alias 已解析到当前 `/dev/videoX`。
- `[ERROR]` 表示配置中的 `usb_path` 当前没有找到对应设备。

#### `resolve <alias>`

```bash
ros2 run fisheye_ros2 camera_scan.py resolve fisheye
```

`resolve` 用于把 `config/cameras.yaml` 中的相机 alias 解析为当前实际的 `/dev/videoX`。

为什么使用：

- 让上层脚本不用硬编码 `/dev/videoX`。
- 当系统重启后 `/dev/videoX` 变化时，仍可通过 alias 找到当前设备。
- 可作为 shell 脚本、启动脚本或调试命令中的设备查询步骤。

适合结合：

- 和 shell 变量结合：把解析结果保存为变量后传给其它程序或调试脚本。
- 和 `read_camera_node.py` 结合：启动前确认 `camera_alias` 对应的当前设备。
- 和部署脚本结合：启动前动态检查目标 alias 对应的设备。

示例：

```bash
VIDEO_DEV=$(ros2 run fisheye_ros2 camera_scan.py resolve fisheye)
echo "$VIDEO_DEV"
```

当前推荐节点 `read_camera_node.py` 使用 `camera_alias`，一般不需要手动传入 `/dev/videoX` 或数字编号。

#### `doctor`

```bash
ros2 run fisheye_ros2 camera_scan.py doctor
```

`doctor` 用于输出更完整的诊断信息，包括配置数量、找到数量、缺失数量，以及每个 alias 的配置路径和当前设备状态。

为什么使用：

- 比 `check` 更适合排查问题。
- 可以看到 alias、配置的 `usb_path`、当前设备、产品名和 capture 状态。
- 适合交接、现场部署、远程支持时快速描述相机连接状态。

适合结合：

- 和 `check` 结合：`check` 只判断是否 OK，`doctor` 用于进一步定位原因。
- 和 `update` 结合：确认哪些配置缺失后，再决定是否更新 `usb_path`。
- 和项目交接结合：把 `doctor` 输出附在问题描述中，便于他人快速确认相机连接状态。

## 相机配置

`config/cameras.yaml` 用于保存相机别名、USB 物理路径和设备识别信息。当前源码配置示例：

```yaml
cameras:
  fisheye:
    usb_path: 1-10.1:1.0
    product: 'DECXIN  CAMERA: DECXIN  CAMERA'
    vendor: DECXIN_CAMERA
    vendor_id: 1bcf
    product_id: 2cd1
    serial: 01.00.00
```

说明：

- `fisheye` 是业务 alias，启动节点时通过 `camera_alias:=fisheye` 使用。
- `usb_path` 和物理 USB 口相关，更换 USB 口后可能变化。
- `product`、`vendor`、`vendor_id`、`product_id`、`serial` 来自 udev 信息，用于展示、诊断和辅助更新配置。
- `read_camera_node.py` 使用 `camera_alias` 读取 `cameras.yaml`，再自动查找当前可 capture 的 DECXIN 鱼眼 `/dev/videoX`。
- `cameras.yaml` 使用普通业务结构，不直接作为 ROS parameter YAML 传给节点。

## 启动相机节点

推荐使用 `read_camera_node.py`。该节点输入 `camera_alias`，程序内部读取 `config/cameras.yaml`，根据 alias 找到对应 `usb_path`，再扫描当前可 capture 的 DECXIN 鱼眼相机并解析实际 `/dev/videoX`。

直接运行：

```bash
ros2 run fisheye_ros2 read_camera_node.py --ros-args \
  -p camera_alias:=fisheye \
  -p camera_fps:=30 \
  -p camera_height:=480 \
  -p camera_width:=640 \
  -p camera_frame_id:=camera_fisheye \
  -p enable_fps_log:=false \
  -p reconnect_interval:=2.0
```

使用 launch：

```bash
ros2 launch fisheye_ros2 read_camera.launch.py camera_alias:=fisheye
```

排查帧率时，可开启发布端周期 FPS 日志：

```bash
ros2 launch fisheye_ros2 read_camera.launch.py \
  camera_alias:=fisheye \
  enable_fps_log:=true \
  reconnect_interval:=2.0
```

为什么这样设计：

- 用户只需要记住 `fisheye` 这样的业务 alias，不需要手动处理 `/dev/videoX` 变化。
- 同一个配置可被 `list`、`check`、`doctor`、`resolve` 和 `read_camera_node.py` 复用。
- 多相机时可以启动多个节点，每个节点传入不同 `camera_alias`。
- 配置中的相机在启动时未接入或运行中断开时，节点会根据稳定的 `usb_path` 周期性重新解析 alias，并在设备恢复后继续发布。

运行行为：

- 节点通过 V4L2 后端打开解析出的 `/dev/videoX`，并请求 MJPG、配置的分辨率和帧率。
- 图像和 camera info 发布器使用 `RELIABLE`、`VOLATILE`、深度 10 的 QoS。
- 连续 3 次读取帧失败后，节点会释放当前设备并进入重连流程。
- 打开、读帧失败、重连和 FPS 日志均包含 `usb_path`；打开成功日志还会显示实际设备和协商格式。

重复启动策略：

- 不同 alias 可以同时运行，用于多相机。
- 同一个 alias 已运行时，后启动的 `read_camera_node.py` 会检测到锁并退出，不会顶替前一个节点，也不会抢占同一个相机。
- 节点默认名带进程 ID，避免多个实例在 ROS graph 中使用完全相同的节点名。

## 节点参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `camera_alias` | `fisheye` | `config/cameras.yaml` 中的相机别名 |
| `camera_fps` | `30` | 相机采集帧率 |
| `camera_height` | `480` | 图像高度 |
| `camera_width` | `640` | 图像宽度 |
| `camera_frame_id` | alias 名称 | 相机 TF frame 前缀；launch 默认值为 `camera_fisheye` |
| `image_topic` | `/<alias>/color/image_raw` | 图像话题 |
| `camera_info_topic` | `/<alias>/color/camera_info` | 相机信息话题 |
| `enable_fps_log` | `false` | 开启发布端周期 FPS 日志；launch 已暴露该参数 |
| `fps_log_interval` | `1.0` | FPS 日志间隔，单位为秒，实际最小值为 `0.1` |
| `reconnect_interval` | `2.0` | 重新解析设备的重试间隔，单位为秒，实际最小值为 `0.1`；launch 已暴露该参数 |

## 发布话题和 TF

| 类型 | 名称 | 说明 |
| --- | --- | --- |
| Topic | `/<alias>/color/image_raw` | 彩色图像数据，消息类型 `sensor_msgs/msg/Image` |
| Topic | `/<alias>/color/camera_info` | 相机信息，消息类型 `sensor_msgs/msg/CameraInfo` |
| TF | `<camera_frame_id>` -> `<camera_frame_id>_color` | 相机颜色帧关系，由节点周期发布 |

## 常见问题

### `ros2 run` 找不到脚本

确认已经编译并 source 当前工作空间：

```bash
colcon build --packages-select fisheye_ros2
source install/setup.bash
```

### 节点启动后无法打开相机

如果 alias 存在于 `config/cameras.yaml`，节点会保持运行并按照 `reconnect_interval` 重试。可检查包含配置 `usb_path` 的 `reconnect attempt`、`camera not found` 和 `failed to open` 日志。

还应检查：

- `camera_alias` 是否存在于 `config/cameras.yaml`。
- 执行 `ros2 run fisheye_ros2 camera_scan.py resolve fisheye`，确认 alias 能解析到当前实际 `/dev/videoX`。
- 相机是否被其它程序占用。
- 相机是否支持当前设置的分辨率和帧率。
- 当前用户是否有访问 `/dev/videoX` 的权限。

设备重新出现在配置的 `usb_path` 后，节点会自动恢复发布。如果相机换到了其它物理 USB 口，需要先更新 `config/cameras.yaml`。

### `camera_alias` 找不到相机

检查：

- `config/cameras.yaml` 中是否存在该 alias。
- 执行 `ros2 run fisheye_ros2 camera_scan.py list`，确认对应 `USB Path` 当前是否在线。
- 如果相机换过 USB 口，执行 `camera_scan.py init` 选择新增或覆盖，或使用 `update` 修复 `usb_path`。

### 同一个 alias 重复启动

`read_camera_node.py` 会为每个 alias 创建运行锁。同一个 alias 已运行时，后启动的节点会退出，不会顶替前一个节点。不同 alias 可以同时运行。

### `/dev/videoX` 重启后变化

先使用扫描工具确认当前设备：

```bash
ros2 run fisheye_ros2 camera_scan.py list
```

如果需要记录稳定标识，可使用 `config/cameras.yaml` 中的 `usb_path` 和别名机制进行诊断和解析。

### 多个 DECXIN 鱼眼相机无法区分

如果多个 DECXIN 鱼眼相机型号相同且没有唯一序列号，仅依赖 `Product` 不可靠。建议固定 USB 物理接口，并使用 `USB Path` 区分。

## 维护说明

- 对外文档只描述安装、配置、运行和排障方式。
- 修改包名、入口脚本、launch 文件、参数、话题或配置字段后，应同步更新本 README。
