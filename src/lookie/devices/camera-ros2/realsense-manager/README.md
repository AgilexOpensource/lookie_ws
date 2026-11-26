# RealSense Manager

[![Ubuntu 22.04](https://img.shields.io/badge/Ubuntu-22.04-E95420?logo=ubuntu&logoColor=white)](https://releases.ubuntu.com/22.04/) [![librealsense v2.56.4](https://img.shields.io/badge/librealsense-v2.56.4-0071C5)](https://github.com/IntelRealSense/librealsense/releases/tag/v2.56.4) [![realsense-ros 4.56.4](https://img.shields.io/badge/realsense--ros-4.56.4-22314E?logo=ros&logoColor=white)](https://github.com/IntelRealSense/realsense-ros/releases/tag/4.56.4)

`realsense-manager` 为多台 Intel RealSense 相机提供持久化 alias 配置、设备枚举、序列号绑定、USB 位置绑定、参数管理以及 YAML 驱动的多相机启动功能。

该目录包含两个 ROS 2 包：

| 包 | 功能 |
|---|---|
| `realsense_manager_msgs` | Manager 使用的消息与服务接口 |
| `realsense_manager` | Python Manager 节点、YAML 存储和 launch 文件 |

**注意：运行本功能包前，ROS 2 环境必须能够通过 ament 索引找到已安装的 `realsense2_camera` 包（通常需要先 source 对应工作空间的 `install/setup.bash`）。**

## 功能概览

- 使用一个 YAML 文件管理全部相机 alias。
- alias 可以先创建，序列号保持为空，之后再进行绑定。
- 支持手动通过 alias 和序列号绑定相机。
- 支持按照预定义 USB 拓扑位置批量绑定相机。
- 通过 `rs-enumerate-devices -S` 查询当前连接的 RealSense 设备。
- 设备查询结果和 alias 查询结果通过 Topic 发布快照。
- alias CRUD、绑定和参数修改通过 Service 完成。
- 支持普通 ROS 2 Node 和 LifecycleNode 两种 Manager 模式。
- 使用相同的 `USE_LIFECYCLE_NODE` 编译选项选择 Manager 和相机节点模式。
- 根据 YAML 动态创建多个 `realsense2_camera_node`。

## 目录结构

```text
realsense-manager/
├── README.md
├── realsense_manager_msgs/
│   ├── msg/
│   └── srv/
└── realsense_manager/
    ├── config/
    ├── launch/
    ├── realsense_manager/
    ├── scripts/
    └── test/
```

## 编译

进入工作空间：

```bash
cd /home/agilex/develop/camera_ros_rs/rs2_master
source /opt/ros/humble/setup.bash
```

启用 Lifecycle：

```bash
colcon build \
  --packages-up-to realsense_manager \
  --cmake-clean-cache \
  --cmake-args -DUSE_LIFECYCLE_NODE=ON
```

关闭 Lifecycle：

```bash
colcon build \
  --packages-up-to realsense_manager \
  --cmake-clean-cache \
  --cmake-args -DUSE_LIFECYCLE_NODE=OFF
```

加载编译结果：

```bash
source install/setup.bash
```

`--packages-up-to realsense_manager` 会同时编译 Manager、接口包和工作空间内的 RealSense 相机依赖。应使用同一次构建统一设置 `USE_LIFECYCLE_NODE`，避免 Manager launch 认为相机是 LifecycleNode，但实际相机二进制是普通 Node。

## 配置文件

Manager 默认使用：

```text
~/.config/realsense_manager/cameras.yaml
```

如果文件不存在，Manager 会自动创建：

```yaml
schema_version: 1
revision: 0
cameras: {}
```

完整示例：

```yaml
schema_version: 1
revision: 5
cameras:
  front:
    enabled: true
    expected_usb_path: 2-3.2
    parameters:
      serial_no: '260422273840'
      camera_name: camera_front
      camera_namespace: ''
      enable_color: true
      enable_depth: true
      depth_module.color_profile: 848x480x30
      depth_module.depth_profile: 848x480x30
      align_depth.enable: true
      pointcloud.enable: false

  left:
    enabled: true
    expected_usb_path: 2-4.2
    parameters:
      serial_no: null
      camera_name: camera_left
      camera_namespace: ''
```

### 顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | integer | 配置格式版本，当前版本为 `1` |
| `revision` | integer | 配置修订号，每次成功写入后加一 |
| `cameras` | mapping | 以 alias 为键的相机配置集合 |

### Alias 字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `enabled` | boolean | multi-camera launch 是否创建该相机节点 |
| `expected_usb_path` | string/null | 预期 USB 拓扑 ID，例如 `2-3.2` |
| `parameters` | mapping | 传给 `rs_launch.py` 和 `realsense2_camera_node` 的参数 |

`serial_no`、`camera_name` 和 `camera_namespace` 都位于 `parameters` 中：

```yaml
parameters:
  serial_no: '260422273840'
  camera_name: camera_front
  camera_namespace: ''
```

`camera_name` 不仅决定 ROS 节点名，也会被 RealSense 驱动用于生成 TF frame ID，例如 `camera_front_link` 和 `camera_front_depth_frame`。因此该字段必须作为参数传入驱动，不能只设置 launch 的节点名称。

所有 alias 的 `camera_name` 必须全局唯一，即使它们位于不同 ROS namespace。原因是 TF frame ID 不受 ROS namespace 隔离，重复名称仍会产生 TF 冲突。Manager 会在创建、修改、通用参数写入和读取 YAML 时检查唯一性；managed multi-camera launch 也会在创建任何节点前拒绝重复名称。

序列号应保存为字符串，防止 YAML 将纯数字序列号转换为整数：

```yaml
parameters:
  serial_no: '260422273840'
```

未绑定时使用 YAML 空值：

```yaml
parameters:
  serial_no: null
```

不要使用字符串 `"none"` 表示空值。

### 原子写入

所有 Service 修改都由 `ConfigStore` 写入临时文件，然后通过 `os.replace()` 原子替换正式 YAML。这样可以避免进程中止或系统掉电发生在写入中间时留下半个 YAML 文件。

## 启动 Manager

使用默认配置文件：

```bash
ros2 launch realsense_manager realsense_manager.launch.py
```

指定配置文件：

```bash
ros2 launch realsense_manager realsense_manager.launch.py \
  config_file:=/home/agilex/camera_config/cameras.yaml
```

指定设备枚举超时：

```bash
ros2 launch realsense_manager realsense_manager.launch.py \
  enumerate_timeout:=15.0
```

启动日志会打印包版本，例如 `RealSense Manager v0.1.0 (realsense_manager_msgs v0.1.0)`。也可以用 ROS 指令查询已安装版本：

```bash
ros2 pkg xml realsense_manager -t version
ros2 pkg xml realsense_manager_msgs -t version
```

### Launch 参数

| 参数 | 默认值 | 含义 |
|---|---|---|
| `config_file` | `~/.config/realsense_manager/cameras.yaml` | 可写的持久化配置路径 |
| `enumerate_timeout` | `10.0` | `rs-enumerate-devices -S` 最长等待秒数 |

## Lifecycle 模式

当 `USE_LIFECYCLE_NODE=ON` 时，Manager 启动后处于 `unconfigured`：

```bash
ros2 lifecycle get /realsense_manager
```

先配置，再激活：

```bash
ros2 lifecycle set /realsense_manager configure
ros2 lifecycle set /realsense_manager activate
```

状态行为：

| 状态/转换 | 行为 |
|---|---|
| `unconfigured` | 仅 Lifecycle 标准服务可用，Manager 业务服务尚未创建 |
| `configure` | 打开 YAML，创建 Publisher 和业务 Service |
| `inactive` | 业务 Service 已存在，但调用会返回 `Manager is not active` |
| `activate` | 允许查询、CRUD、绑定和参数设置 |
| `deactivate` | 保留接口，但拒绝业务操作 |
| `cleanup` | 销毁 Manager Publisher、Service 和内存缓存 |

当 `USE_LIFECYCLE_NODE=OFF` 时，普通 Manager Node 启动后立即可用，不需要执行状态切换。

## Topic 总览

Manager 节点名称默认为 `/realsense_manager`。

| Topic | 类型 | 发布时机 |
|---|---|---|
| `/realsense_manager/device_inventory` | `realsense_manager_msgs/msg/DeviceInventory` | 每次成功调用 `query_devices` 发布一次 |
| `/realsense_manager/alias_inventory` | `realsense_manager_msgs/msg/AliasInventory` | 每次调用 `query_aliases` 发布一次查询结果 |
| `/realsense_manager/events` | `realsense_manager_msgs/msg/ManagerEvent` | CRUD、绑定和参数修改后发布一次 |

`device_inventory` 和 `alias_inventory` 使用 Reliable + Transient Local QoS，深度为 1。`events` 使用深度为 20 的普通事件队列。

建议先启动 Topic 订阅，再调用查询 Service：

```bash
ros2 topic echo /realsense_manager/device_inventory
```

另一个终端执行：

```bash
ros2 service call /realsense_manager/query_devices \
  realsense_manager_msgs/srv/QueryDevices \
  "{request_id: device_query_001}"
```

### DeviceInventory

```text
std_msgs/Header header
string request_id
Device[] devices
```

| 字段 | 含义 |
|---|---|
| `header.stamp` | Manager 发布快照的 ROS 时间 |
| `request_id` | Service 请求携带的关联 ID；请求为空时自动生成 UUID |
| `devices` | 本次系统设备枚举得到的全部 RealSense 相机 |

### Device

`Device` 将 librealsense 枚举信息和 Manager 派生的绑定状态分离：

```text
DeviceInfo info
DeviceStatus status
```

### DeviceInfo

`DeviceInfo` 字段主要对应 `rs-enumerate-devices -S` 的 `Device info` 输出。

| 字段 | 来源或含义 |
|---|---|
| `name` | `Name`，设备型号名称 |
| `serial_number` | `Serial Number` |
| `firmware_version` | `Firmware Version` |
| `recommended_firmware_version` | `Recommended Firmware Version` |
| `physical_port` | `Physical Port` 完整 sysfs 路径 |
| `usb_path` | 从 `physical_port` 提取的稳定 USB 拓扑 ID |
| `debug_op_code` | `Debug Op Code` |
| `advanced_mode` | `Advanced Mode` 是否为 `YES` |
| `product_id` | `Product Id` |
| `camera_locked` | `Camera Locked` 是否为 `YES` |
| `usb_type_descriptor` | 当前 USB 协商类型，例如 `2.1`、`3.2` |
| `product_line` | `Product Line` |
| `asic_serial_number` | `Asic Serial Number` |
| `firmware_update_id` | `Firmware Update Id` |
| `dfu_device_path` | `Dfu Device Path` |
| `connection_type` | `Connection Type` |

### DeviceStatus

```text
bool is_binded
string alias
```

| 字段 | 含义 |
|---|---|
| `is_binded` | `info.serial_number` 是否已存在于 YAML alias 中 |
| `alias` | 已绑定时对应的 alias；未绑定时为空字符串 |

接口字段使用了 `is_binded` 名称以匹配当前消息定义，其语义是“是否已经绑定”。

Topic 输出结构示例：

```yaml
devices:
- info:
    name: Intel RealSense D405
    serial_number: '230322271721'
    physical_port: /sys/devices/...
    usb_path: 2-4.2
    usb_type_descriptor: '3.2'
    connection_type: USB
  status:
    is_binded: true
    alias: head
```

### AliasInventory

```text
std_msgs/Header header
string request_id
uint64 config_revision
AliasCamera[] cameras
```

| 字段 | 含义 |
|---|---|
| `header.stamp` | 快照发布时间 |
| `request_id` | 与 `query_aliases` 请求关联的 ID |
| `config_revision` | 读取 YAML 时的修订号 |
| `cameras` | YAML 中符合查询条件的 alias 记录 |

### AliasCamera

`AliasCamera` 将持久化配置和运行时状态分离：

```text
AliasConfig config
AliasStatus status
```

### AliasConfig

```text
string alias
bool enabled
string expected_usb_path
rcl_interfaces/Parameter[] parameters
```

| 字段 | 含义 |
|---|---|
| `alias` | 逻辑相机别名，例如 `front` |
| `enabled` | multi-camera launch 是否应创建该节点 |
| `expected_usb_path` | YAML 中持久化的预期 USB 拓扑位置 |
| `parameters` | 完整 YAML parameters 转换得到的 `rcl_interfaces/Parameter[]` |

`serial_no`、`camera_name` 和 `camera_namespace` 只存在于 `config.parameters`，不再作为 `AliasCamera` 顶层字段重复发布。

### AliasStatus

```text
uint8 RUNTIME_UNKNOWN=0
uint8 RUNTIME_STOPPED=1
uint8 RUNTIME_RUNNING=2

bool is_binded
bool device_present
string current_usb_path
bool usb_path_matches
uint8 runtime_state
```

| 字段 | 含义 |
|---|---|
| `is_binded` | `config.parameters` 中的 `serial_no` 是否非空 |
| `device_present` | 最近一次设备枚举缓存中是否存在该序列号 |
| `current_usb_path` | 最近一次设备枚举记录的实际 USB 拓扑位置 |
| `usb_path_matches` | 实际 USB 位置是否与预期位置相同 |
| `runtime_state` | 相机 ROS 节点运行状态，当前版本固定为 `RUNTIME_UNKNOWN` |

运行状态常量：

| 常量 | 值 | 含义 |
|---|---:|---|
| `RUNTIME_UNKNOWN` | 0 | 尚未实现可靠的相机节点运行检测 |
| `RUNTIME_STOPPED` | 1 | 预留：节点已停止 |
| `RUNTIME_RUNNING` | 2 | 预留：节点运行中 |

`device_present`、`current_usb_path` 和 `usb_path_matches` 使用 Manager 内存中的最近一次设备枚举结果。`query_aliases` 本身不会执行 `rs-enumerate-devices`。如需最新在线状态，应先调用 `query_devices`，再调用 `query_aliases`。

Topic 输出结构示例：

```yaml
cameras:
- config:
    alias: head
    enabled: true
    expected_usb_path: 2-4.2
    parameters:
    - name: serial_no
      value:
        type: 4
        string_value: '230322271721'
    - name: camera_name
      value:
        type: 4
        string_value: camera_head
  status:
    is_binded: true
    device_present: true
    current_usb_path: 2-4.2
    usb_path_matches: true
    runtime_state: 0
```

`ParameterValue` 是固定字段 ROS 消息，`ros2 topic echo` 会同时显示 `bool_value`、`integer_value`、`string_value` 等所有候选字段。只有 `type` 对应的字段有效，其余默认值应忽略。

### ManagerEvent

```text
std_msgs/Header header
string operation
string alias
bool success
string message
uint64 config_revision
```

| 字段 | 含义 |
|---|---|
| `operation` | 操作名称，例如 `create_alias`、`bind_by_usb` |
| `alias` | 操作目标 alias；批量操作可能为空 |
| `success` | 操作是否成功 |
| `message` | 结果或错误原因 |
| `config_revision` | 操作结束后的 YAML 修订号 |

## Service 总览

| Service | 类型 | 功能 |
|---|---|---|
| `/realsense_manager/query_devices` | `QueryDevices` | 枚举系统 RealSense 设备并发布设备 Topic |
| `/realsense_manager/query_aliases` | `QueryAliases` | 读取 YAML alias 并发布 alias Topic |
| `/realsense_manager/create_alias` | `CreateAlias` | 新增 alias |
| `/realsense_manager/delete_alias` | `DeleteAlias` | 删除 alias |
| `/realsense_manager/rename_alias` | `RenameAlias` | 修改 alias 键名 |
| `/realsense_manager/update_alias` | `UpdateAlias` | 修改节点名、命名空间和启用状态 |
| `/realsense_manager/bind_camera` | `BindCamera` | 手动绑定 alias 与序列号 |
| `/realsense_manager/unbind_camera` | `UnbindCamera` | 清除 alias 的序列号 |
| `/realsense_manager/set_expected_usb_path` | `SetExpectedUsbPath` | 设置或清除预期 USB 位置 |
| `/realsense_manager/bind_by_usb` | `BindByUsb` | 根据预期 USB 位置批量绑定当前设备 |
| `/realsense_manager/set_camera_parameters` | `SetCameraParameters` | 写入任意类型化 RealSense 参数 |
| `/realsense_manager/set_camera_profile` | `SetCameraProfile` | 可选定制接口，默认不注册 |

## 查询服务

### query_devices

接口：

```text
string request_id
---
bool success
string message
string request_id
uint32 device_count
```

执行过程：

1. 运行 `rs-enumerate-devices -S`。
2. 解析每个 `Device info` 块。
3. 从 Physical Port 提取稳定 USB 拓扑 ID。
4. 读取 YAML，检查每个设备序列号是否已绑定。
5. 更新 Manager 的设备缓存。
6. 发布一次 `device_inventory`。

调用：

```bash
ros2 service call /realsense_manager/query_devices \
  realsense_manager_msgs/srv/QueryDevices \
  "{request_id: device_query_001}"
```

`request_id` 可以为空。为空时 Manager 会生成 UUID，并在 Service 响应和 Topic 中返回相同 ID。

失败情况包括：

- 找不到 `rs-enumerate-devices`。
- 命令执行超时。
- 命令返回非零退出码。
- YAML 无法读取。

### query_aliases

接口：

```text
string alias
string request_id
---
bool success
string message
string request_id
uint32 alias_count
uint64 config_revision
```

`alias` 为空时查询全部 alias；非空时只查询指定 alias。

查询全部：

```bash
ros2 service call /realsense_manager/query_aliases \
  realsense_manager_msgs/srv/QueryAliases \
  "{alias: '', request_id: alias_query_all}"
```

查询单个 alias：

```bash
ros2 service call /realsense_manager/query_aliases \
  realsense_manager_msgs/srv/QueryAliases \
  "{alias: front, request_id: alias_query_front}"
```

查询不存在的 alias 时返回失败。Topic 只包含本次查询选中的记录。

## Alias CRUD 服务

### create_alias

接口：

```text
string alias
string camera_name
string camera_namespace
---
bool success
string message
uint64 config_revision
```

创建后的默认字段：

```yaml
enabled: true
expected_usb_path: null
parameters:
  serial_no: null
  camera_name: camera_front
  camera_namespace: ''
```

alias 必须以字母开头，只能包含字母、数字和下划线。`camera_name` 为空时自动使用 `camera_<alias>`。`camera_name` 只能包含字母、数字和下划线，不能以数字开头，并且不能与任何已有 alias 的 `camera_name` 重复。

```bash
ros2 service call /realsense_manager/create_alias \
  realsense_manager_msgs/srv/CreateAlias \
  "{alias: front, camera_name: camera_front, camera_namespace: ''}"
```

### delete_alias

接口：

```text
string alias
---
bool success
string message
uint64 config_revision
```

```bash
ros2 service call /realsense_manager/delete_alias \
  realsense_manager_msgs/srv/DeleteAlias \
  "{alias: front}"
```

该操作删除完整 alias 配置，包括绑定序列号、USB 位置和参数。它不会立即停止已经运行的相机节点，需重新启动 multi-camera launch。

### rename_alias

接口：

```text
string alias
string new_alias
---
bool success
string message
uint64 config_revision
```

```bash
ros2 service call /realsense_manager/rename_alias \
  realsense_manager_msgs/srv/RenameAlias \
  "{alias: front, new_alias: camera_front_slot}"
```

该操作只修改 YAML 中的 alias 键名，不自动修改 `camera_name`，其余配置保持不变。

### update_alias

接口：

```text
string alias
string camera_name
string camera_namespace
bool enabled
---
bool success
string message
uint64 config_revision
```

```bash
ros2 service call /realsense_manager/update_alias \
  realsense_manager_msgs/srv/UpdateAlias \
  "{alias: front, camera_name: camera_front, camera_namespace: robot1, enabled: true}"
```

`camera_name` 不能为空。`camera_namespace` 可以为空。该服务一次覆盖这三个字段，因此调用时必须提供希望保留的当前值。

`enabled: false` 表示下次启动 `managed_multi_camera.launch.py` 时跳过该 alias，不代表立即停止当前节点。

## 绑定服务

### bind_camera

接口：

```text
string alias
string serial_number
bool require_present
---
bool success
string message
uint64 config_revision
```

允许离线记录序列号：

```bash
ros2 service call /realsense_manager/bind_camera \
  realsense_manager_msgs/srv/BindCamera \
  "{alias: front, serial_number: '260422273840', require_present: false}"
```

要求设备当前在线：

```bash
ros2 service call /realsense_manager/bind_camera \
  realsense_manager_msgs/srv/BindCamera \
  "{alias: front, serial_number: '260422273840', require_present: true}"
```

当 `require_present=true` 时，Manager 会重新执行设备枚举。一个序列号不能同时绑定到两个 alias。

### unbind_camera

接口：

```text
string alias
---
bool success
string message
uint64 config_revision
```

```bash
ros2 service call /realsense_manager/unbind_camera \
  realsense_manager_msgs/srv/UnbindCamera \
  "{alias: front}"
```

解绑后 YAML 中变为：

```yaml
parameters:
  serial_no: null
```

预期 USB 位置和相机参数不会被清除。

### set_expected_usb_path

接口：

```text
string alias
string usb_path
---
bool success
string message
uint64 config_revision
```

设置稳定 USB 拓扑 ID：

```bash
ros2 service call /realsense_manager/set_expected_usb_path \
  realsense_manager_msgs/srv/SetExpectedUsbPath \
  "{alias: front, usb_path: '2-3.2'}"
```

也可以传入完整 Physical Port，Manager 会提取最后一个稳定拓扑 ID：

```bash
ros2 service call /realsense_manager/set_expected_usb_path \
  realsense_manager_msgs/srv/SetExpectedUsbPath \
  "{alias: front, usb_path: '/sys/devices/pci0000:00/usb2/2-3/2-3.2/2-3.2:1.0/video4linux/video10'}"
```

传入空字符串可以清除预期位置：

```bash
ros2 service call /realsense_manager/set_expected_usb_path \
  realsense_manager_msgs/srv/SetExpectedUsbPath \
  "{alias: front, usb_path: ''}"
```

同一个 USB 拓扑 ID 不能分配给两个不同 alias。

### bind_by_usb

接口：

```text
bool overwrite_existing
---
bool success
string message
uint32 bound_count
uint32 skipped_count
uint64 config_revision
```

```bash
ros2 service call /realsense_manager/bind_by_usb \
  realsense_manager_msgs/srv/BindByUsb \
  "{overwrite_existing: false}"
```

执行过程：

1. 执行 `rs-enumerate-devices -S` 获取当前设备。
2. 提取每台设备的稳定 USB 拓扑 ID。
3. 遍历全部 alias。
4. 使用 `expected_usb_path` 查找当前位置上的设备。
5. 将找到的序列号写入 alias 的 `serial_no`。

跳过情况包括：

- alias 没有设置 `expected_usb_path`。
- 预期 USB 位置当前没有相机。
- alias 已绑定且 `overwrite_existing=false`。
- 目标序列号已经属于其他 alias。

`overwrite_existing=true` 允许更新 alias 现有序列号，但仍不会允许同一个序列号属于两个 alias。

## 参数服务

参数服务当前只更新 YAML，不直接调用已经运行的相机节点参数服务。因此成功响应中的 `restart_required` 为 `true`，重新启动 `managed_multi_camera.launch.py` 后生效。

### set_camera_parameters

通用类型化参数接口：

```text
string alias
rcl_interfaces/Parameter[] parameters
---
bool success
string message
uint64 config_revision
bool restart_required
```

它支持 ROS 参数原生类型，不需要为每个 RealSense 参数新增一个 Service。

ROS 参数类型值：

| `type` | 类型 |
|---:|---|
| 1 | bool |
| 2 | integer |
| 3 | double |
| 4 | string |
| 5 | byte array |
| 6 | bool array |
| 7 | integer array |
| 8 | double array |
| 9 | string array |

一次启用彩色、深度、点云和深度对齐，并设置彩色、深度 profile：

```bash
ros2 service call /realsense_manager/set_camera_parameters \
  realsense_manager_msgs/srv/SetCameraParameters \
  "{alias: front, parameters: [
    {name: enable_color, value: {type: 1, bool_value: true}},
    {name: enable_depth, value: {type: 1, bool_value: true}},
    {name: pointcloud.enable, value: {type: 1, bool_value: true}},
    {name: rgb_camera.color_profile, value: {type: 4, string_value: '848x480x30'}},
    {name: depth_module.color_profile, value: {type: 4, string_value: '848x480x30'}},
    {name: depth_module.depth_profile, value: {type: 4, string_value: '848x480x30'}},
    {name: align_depth.enable, value: {type: 1, bool_value: true}}
  ]}"
```

布尔参数必须使用 `type: 1` 和 `bool_value`，不能写成字符串 `'true'`。profile 参数必须使用 `type: 4` 和 `string_value`。当前驱动同时接受 `848x480x30` 和 `848,480,30`，推荐使用文档中更常见的 `宽x高xFPS` 格式。

`rgb_camera.color_profile` 主要用于 D435i 等具有独立 RGB Camera 模块的型号；D405 彩色流通常使用 `depth_module.color_profile`。没有对应传感器的型号通常不会声明该参数，因此通用配置中可以同时保存两项；按型号删除无关参数会让配置和诊断输出更清晰。

该接口验证参数具有名称和 ROS 类型，但不会提前验证参数是否被具体 RealSense 型号支持。最终支持情况由启动后的 `realsense2_camera_node` 判断。

通用参数服务实现位于：

```text
realsense_manager/realsense_manager/generic_parameter_services.py
```

### set_camera_profile

常用分辨率便捷接口。当前保留接口和实现作为维护示例，但 Manager 默认不注册该 Service；直接调用时会等待不存在的服务。

```text
string alias
string parameter_name
uint32 width
uint32 height
uint32 fps
---
bool success
string message
uint64 config_revision
bool restart_required
```

D435i 深度：

```bash
ros2 service call /realsense_manager/set_camera_profile \
  realsense_manager_msgs/srv/SetCameraProfile \
  "{alias: front, parameter_name: depth_module.depth_profile, width: 848, height: 480, fps: 30}"
```

D435i 彩色：

```bash
ros2 service call /realsense_manager/set_camera_profile \
  realsense_manager_msgs/srv/SetCameraProfile \
  "{alias: front, parameter_name: rgb_camera.color_profile, width: 848, height: 480, fps: 30}"
```

D405 彩色：

```bash
ros2 service call /realsense_manager/set_camera_profile \
  realsense_manager_msgs/srv/SetCameraProfile \
  "{alias: front, parameter_name: depth_module.color_profile, width: 848, height: 480, fps: 30}"
```

该服务要求 `parameter_name` 以 `_profile` 结尾，并要求宽、高、FPS 大于零。它会写入：

```yaml
depth_module.depth_profile: 848x480x30
```

它不会提前检查该 profile 是否被当前相机型号支持。

独立常用参数服务实现位于：

```text
realsense_manager/realsense_manager/common_parameter_services.py
```

Manager 当前只实例化 `GenericParameterServices`。`CommonParameterServices` 默认停用，运行时服务列表中不会出现 `/realsense_manager/set_camera_profile`。

## 定制参数 Service 维护

### 启用现有 set_camera_profile

`SetCameraProfile.srv`、ROSIDL CMake 配置和 `CommonParameterServices` 实现已经保留。启用时修改：

```text
realsense_manager/realsense_manager/manager_core.py
```

在 import 区域增加：

```python
from .common_parameter_services import CommonParameterServices
```

在 `ManagerCore.configure()` 的 `_parameter_service_groups` 中增加实例：

```python
self._parameter_service_groups = [
    GenericParameterServices(self),
    CommonParameterServices(self),
]
```

重新编译并重启 Manager：

```bash
colcon build --packages-select realsense_manager_msgs realsense_manager
source install/setup.bash
```

确认服务：

```bash
ros2 service list -t | grep set_camera_profile
```

### 新增其他定制参数 Service

例如增加曝光设置服务 `SetCameraExposure`。

第一步，在接口包中新建：

```text
realsense_manager_msgs/srv/SetCameraExposure.srv
```

示例接口：

```text
string alias
string module_name
int64 exposure
---
bool success
string message
uint64 config_revision
bool restart_required
```

第二步，在以下文件的 `rosidl_generate_interfaces()` 中注册接口：

```text
realsense_manager_msgs/CMakeLists.txt
```

增加：

```cmake
"srv/SetCameraExposure.srv"
```

第三步，新建定制服务实现，例如：

```text
realsense_manager/realsense_manager/exposure_parameter_services.py
```

基础结构：

```python
from realsense_manager_msgs.srv import SetCameraExposure


class ExposureParameterServices:
    def __init__(self, core):
        self._core = core
        self._service = core.node.create_service(
            SetCameraExposure,
            '~/set_camera_exposure',
            self._set_exposure,
        )

    def destroy(self):
        self._core.node.destroy_service(self._service)

    def _set_exposure(self, request, response):
        if not self._core.require_active(response):
            return response
        try:
            parameter_name = f'{request.module_name}.exposure'
            revision = self._core.store.set_parameters(
                request.alias, {parameter_name: request.exposure})
            response.success = True
            response.message = (
                f'Set {parameter_name}={request.exposure}; '
                'restart launch to apply')
            response.config_revision = revision
            response.restart_required = True
        except (RuntimeError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.config_revision = self._core.revision()
            response.restart_required = False
        self._core.publish_event(
            'set_camera_exposure', request.alias, response.success,
            response.message, response.config_revision)
        return response
```

第四步，在 `manager_core.py` 导入并注册：

```python
from .exposure_parameter_services import ExposureParameterServices
```

```python
self._parameter_service_groups = [
    GenericParameterServices(self),
    ExposureParameterServices(self),
]
```

所有定制服务组必须实现 `destroy()`，因为 Lifecycle `cleanup` 会遍历 `_parameter_service_groups` 并销毁服务。

参数最终应通过：

```python
self._core.store.set_parameters(alias, parameters)
```

写入 YAML，避免定制 Service 绕开修订号、原子写入和通用校验。操作结束后应调用 `publish_event()` 发布统一的 Manager 事件。

## 启动配置中的多台相机

```bash
ros2 launch realsense_manager managed_multi_camera.launch.py
```

指定配置文件：

```bash
ros2 launch realsense_manager managed_multi_camera.launch.py \
  config_file:=/home/agilex/camera_config/cameras.yaml \
  log_level:=info
```

### Multi-camera Launch 参数

| 参数 | 默认值 | 含义 |
|---|---|---|
| `config_file` | `~/.config/realsense_manager/cameras.yaml` | Manager 生成的总配置 |
| `log_level` | `info` | RealSense 节点日志等级 |

launch 遍历 `cameras`，只启动同时满足以下条件的 alias：

- `enabled: true`
- `serial_no` 非空

以下字段用于创建节点：

| YAML 字段 | 节点用途 |
|---|---|
| `parameters.serial_no` | 作为 RealSense `serial_no` 参数 |
| `parameters.camera_name` | 节点名称，同时传给驱动生成唯一 TF frame ID |
| `parameters.camera_namespace` | 节点命名空间 |
| `parameters` 中的其他字段 | 其余 RealSense 参数 |

`managed_multi_camera.launch.py` 为每个 alias 包含一次官方 `rs_launch.py`，每台相机作为独立的 `realsense2_camera_node` 进程启动。Manager launch 读取 `rs_launch.configurable_parameters`，将 alias 的 `parameters` 展开成 launch arguments。

如果 YAML 包含未在 `rs_launch.configurable_parameters` 中声明的参数，managed launch 会在启动任何相机前报错并列出未知参数，避免配置被静默忽略。需要使用新的驱动参数时，应先将该参数加入官方 `rs_launch.py` 的 `configurable_parameters`。

独立节点模式会为传入 `rs_launch.py` 的纯数字序列号临时增加 `_` 前缀，避免 ROS 2 将序列号推断成 integer；驱动读取后自动移除。YAML 中保存不带 `_` 的原始序列号。

`expected_usb_path` 只用于绑定和状态检查，不限制相机节点启动。已绑定序列号的相机即使换到其他 USB 接口，仍可按序列号启动，但 `usb_path_matches` 会变成 `false`。

### 单相机独立容器

Manager 包中的 `rs_container_launch.py` 可以单独启动一台组件化相机，官方 `realsense2_camera` 包不需要增加或修改 launch 文件：

```bash
ros2 launch realsense_manager rs_container_launch.py \
  container_name:=camera_head_container \
  camera_name:=camera_head \
  camera_namespace:='' \
  serial_no:=230322271721 \
  enable_color:=true \
  enable_depth:=true \
  intra_process_comms:=false
```

该文件不导入或修改官方 `rs_launch.py`。它按照相同结构独立定义 `configurable_parameters`、参数声明、YAML 读取和 `launch_setup()`，区别仅在于最终创建 `ComposableNodeContainer` 和 `ComposableNode`。

维护时，如果官方 `rs_launch.py` 增加、删除或修改参数，需要将对应条目同步到 Manager 包 `rs_container_launch.py` 的 `configurable_parameters`。多相机容器 launch 读取的是 `rs_container_launch.configurable_parameters`，因此只需维护这个单相机容器参数表。

`rs_container_launch.py` 使用 `ParameterValue(..., value_type=str)` 传递 `serial_no`，因此纯数字序列号不会被 ROS 2 推断为 integer。

### 多相机独立容器

保留独立节点启动方式的同时，Manager 额外提供：

```bash
ros2 launch realsense_manager managed_multi_camera_containers.launch.py \
  config_file:=/home/agilex/camera_config/cameras.yaml \
  log_level:=info \
  intra_process_comms:=false
```

参数：

| 参数 | 默认值 | 含义 |
|---|---|---|
| `config_file` | `~/.config/realsense_manager/cameras.yaml` | Manager 生成的总配置 |
| `log_level` | `info` | 容器和相机日志等级 |
| `intra_process_comms` | `false` | 是否为每个相机组件启用进程内通信 |

进程结构：

```text
camera_head_container process
└── camera_head component

camera_left_container process
└── camera_left component
```

每台相机一个容器与每台相机一个独立节点在进程隔离上基本一致：两种方式都是一台相机对应一个 OS 进程。区别如下：

| 项目 | 独立节点 | 单相机独立容器 |
|---|---|---|
| 进程可执行文件 | `realsense2_camera_node` | `component_container_mt` |
| 相机实现 | 直接构造节点 | 动态加载 `RealSenseNodeFactory` 组件 |
| 外部 Topic/Service | 正常发布 | 与独立节点相同 |
| 单独运行性能 | 基本相同 | 多一层组件容器管理，开销很小 |
| 后续加入同进程算法 | 不支持 | 可以继续加载其他 Component |
| intra-process | 不适用 | 同容器内发布者和订阅者可使用 |
| 故障隔离 | 每台相机一个进程 | 每台相机一个容器进程，隔离程度相近 |

只有相机组件、没有同容器消费组件时，开启 intra-process 不会减少相机到外部进程的 DDS 传输。默认保持 `false`，使发布器行为尽量接近普通独立节点。设置为 `true` 后，驱动会选择原生图像 Publisher，不使用 `image_transport` 压缩插件。

### Lifecycle 相机

Lifecycle 模式下，launch 创建相机后停在 `unconfigured`。例如 alias 的 `camera_name` 为 `camera_front` 且 namespace 为空：

```bash
ros2 lifecycle get /camera_front
ros2 lifecycle set /camera_front configure
ros2 lifecycle set /camera_front activate
```

设置 namespace 后，Lifecycle 节点路径包含 namespace。例如：

```yaml
parameters:
  camera_name: camera_front
  camera_namespace: robot1
```

对应节点：

```text
/robot1/camera_front
```

### 配置修改的生效范围

| 操作 | YAML 立即更新 | 当前相机进程立即变化 | 重启 launch 后生效 |
|---|---:|---:|---:|
| 创建 alias | 是 | 否 | 是 |
| 删除 alias | 是 | 否 | 是 |
| 重命名 alias | 是 | 否 | 是 |
| 修改节点名/namespace | 是 | 否 | 是 |
| 修改 `enabled` | 是 | 否 | 是 |
| 绑定/解绑序列号 | 是 | 否 | 是 |
| 设置 USB 位置 | 是 | 否 | 仅影响绑定和状态判断 |
| 设置相机参数 | 是 | 否 | 是 |

当前版本不负责运行时创建、销毁或重启相机进程。

## USB 位置策略

完整 Physical Port 可能类似：

```text
/sys/devices/pci0000:00/0000:00:14.0/usb2/2-3/2-3.2/2-3.2:1.0/video4linux/video10
```

其中 `video10` 和接口后缀可能变化。Manager 提取：

```text
2-3.2
```

作为稳定 USB 拓扑 ID。

`expected_usb_path` 表示工控机设计中约定的物理位置，不会在相机换插后自动更新。这样可以同时保留：

- 预期安装位置 `expected_usb_path`
- 当前实际位置 `current_usb_path`
- 位置是否正确 `usb_path_matches`

如果换插是有意的，应显式调用 `set_expected_usb_path` 更新预期值；如果换插是误操作，状态 Topic 可以检测出来。

## 错误处理

所有修改 Service 都返回：

- `success`：是否成功。
- `message`：成功说明或具体错误。
- `config_revision`：操作结束后的配置版本。

常见错误：

- Manager LifecycleNode 尚未激活。
- alias 不存在或重复。
- alias 名称格式无效。
- 序列号已经属于其他 alias。
- USB 路径已经属于其他 alias。
- 参数名称为空或参数类型为 `NOT_SET`。
- YAML 格式无效或不可写。
- `rs-enumerate-devices` 不存在、超时或执行失败。

失败操作不会覆盖正式 YAML 文件。

## 测试

```bash
cd /home/agilex/develop/camera_ros_rs/rs2_master
colcon test --packages-select realsense_manager realsense_manager_msgs
colcon test-result --verbose
```

代码风格检查：

```bash
cd /home/agilex/develop/camera_ros_rs/rs2_master/src/realsense-manager/realsense_manager
ament_flake8 --linelength 100 realsense_manager test launch
```
