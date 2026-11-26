# hi04_ros

`hi04_ros` 是 HI04 CANopen TPDO 传感器的 ROS 2 驱动包。节点通过
SocketCAN 读取 CAN 总线数据，解析 HI04 上报的 TPDO 帧，并发布加速度、
角速度、欧拉角、四元数、气压、倾角和组合 IMU 话题。

包目录名称为 `HI04_ros/`，ROS 包名称为 `hi04_ros`。

## 功能

- 通过 `python-can` 连接 SocketCAN 总线。
- 按 CANopen `node_id` 过滤 HI04 TPDO 报文。
- 发布原始加速度、角速度、欧拉角、四元数、气压和倾角数据。
- 可选发布组合 `sensor_msgs/Imu` 数据。
- 可选发布从 `tf_parent_frame` 到 `frame_id` 的 TF。
- 所有运行参数集中在 `config/hi04.yaml` 中配置。
- 发布话题名称也可在 YAML 文件中修改。

## 目录结构

```text
HI04_ros/
├── config/
│   └── hi04.yaml              # 节点参数和话题名称配置
├── hi04_ros/
│   ├── hi04_node.py           # ROS 2 节点入口
│   └── protocol.py            # HI04 CANopen TPDO 解析逻辑
├── launch/
│   └── hi04.launch.py         # 默认启动文件
├── test/
│   └── test_hi04_parser.py    # 协议解析单元测试
├── package.xml
├── setup.py
└── README.md
```

## 依赖

- ROS 2 Humble 或兼容版本
- `rclpy`
- `geometry_msgs`
- `sensor_msgs`
- `tf2_ros`
- `python3-can`
- Linux SocketCAN

如果系统没有安装 `python-can`，可使用系统包或 pip 安装：

```bash
sudo apt install python3-can
```

## 编译

在工作空间根目录执行：

```bash
cd /home/agilex/ros2_project/mini_cobot
colcon build --packages-select hi04_ros
source install/setup.bash
```

## CAN 设备准备

启动节点前先打开 CAN 口，例如 `can0`、500 kbit/s：

```bash
sudo ip link set can0 up type can bitrate 500000
```

如果 CAN 口已经打开但参数不一致，可先关闭再重新配置：

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 500000
```

## 启动

默认启动会加载安装目录中的 `config/hi04.yaml`：

```bash
ros2 launch hi04_ros hi04.launch.py
```

也可以指定其他 YAML 参数文件：

```bash
ros2 launch hi04_ros hi04.launch.py params_file:=/absolute/path/to/hi04.yaml
```

如需修改节点名：

```bash
ros2 launch hi04_ros hi04.launch.py node_name:=hi04_node
```

## 参数配置

参数集中在：

```text
HI04_ros/config/hi04.yaml
```

当前配置示例：

```yaml
/**:
  ros__parameters:
    port_name: ""
    channel: "can0"
    can_interface: "socketcan"
    node_id: 8
    frame_id: "hi04_link"
    quaternion_order: "wxyz"
    normalize_quaternion: true
    publish_imu: true
    publish_tf: false
    tf_parent_frame: "world"
    acceleration_topic: "/acceleration_msg"
    angular_velocity_topic: "/angular_velocity_dps"
    euler_topic: "/euler_deg"
    quaternion_topic: "/quaternion"
    pressure_topic: "/pressure"
    inclinometer_topic: "/inclinometer_deg"
    imu_topic: "/imu"
```

修改源码目录中的 YAML 后，如果使用 `ros2 launch hi04_ros hi04.launch.py`
启动安装后的包，需要重新编译并 source：

```bash
colcon build --packages-select hi04_ros
source install/setup.bash
```

如果不想重新编译，可以把自定义 YAML 放到任意位置，然后通过
`params_file:=/absolute/path/to/hi04.yaml` 指定。

## 参数说明

| 参数名 | 类型 | 说明 |
| --- | --- | --- |
| `port_name` | string | 兼容旧参数名。非空时优先作为 CAN 通道名使用。 |
| `channel` | string | CAN 通道名，例如 `can0`。当 `port_name` 为空时使用。 |
| `can_interface` | string | `python-can` 接口类型，SocketCAN 通常为 `socketcan`。 |
| `node_id` | int | CANopen 节点 ID，范围为 1 到 127。 |
| `frame_id` | string | ROS 消息 `header.frame_id`，也是 TF 子坐标系。 |
| `quaternion_order` | string | HI04 TPDO4 中四元数字段顺序，常用 `wxyz` 或 `xyzw`。 |
| `normalize_quaternion` | bool | 是否归一化四元数输出。 |
| `publish_imu` | bool | 是否发布组合后的 `sensor_msgs/Imu`。 |
| `publish_tf` | bool | 是否发布 TF。 |
| `tf_parent_frame` | string | TF 父坐标系。 |
| `acceleration_topic` | string | 加速度话题名。 |
| `angular_velocity_topic` | string | 角速度话题名。 |
| `euler_topic` | string | 欧拉角话题名。 |
| `quaternion_topic` | string | 四元数话题名。 |
| `pressure_topic` | string | 气压话题名。 |
| `inclinometer_topic` | string | 倾角话题名。 |
| `imu_topic` | string | 组合 IMU 话题名。 |

话题名可以写成全局话题，例如 `/imu`，也可以写成私有话题，例如 `~/imu`。
如果写成 `~/imu`，默认节点名为 `hi04_node` 时实际话题为 `/hi04_node/imu`。

## 发布话题

话题名称由 YAML 中的 topic 参数决定。按当前 `config/hi04.yaml`，默认发布：

| 话题 | 消息类型 | 数据内容 |
| --- | --- | --- |
| `/acceleration_msg` | `geometry_msgs/msg/Vector3Stamped` | TPDO1 原始加速度，单位 mG。 |
| `/angular_velocity_dps` | `geometry_msgs/msg/Vector3Stamped` | TPDO2 角速度，单位 deg/s。 |
| `/euler_deg` | `geometry_msgs/msg/Vector3Stamped` | TPDO3 欧拉角 roll、pitch、yaw，单位 degree。 |
| `/quaternion` | `geometry_msgs/msg/QuaternionStamped` | TPDO4 四元数，ROS 顺序为 x、y、z、w。 |
| `/pressure` | `sensor_msgs/msg/FluidPressure` | TPDO6 气压，单位 Pa。 |
| `/inclinometer_deg` | `geometry_msgs/msg/Vector3Stamped` | TPDO7 X/Y 倾角，单位 degree。 |
| `/imu` | `sensor_msgs/msg/Imu` | 组合 IMU，包含加速度、角速度和四元数姿态。 |

查看话题：

```bash
ros2 topic list
```

查看 IMU 数据：

```bash
ros2 topic echo /imu
```

## TF 和 RViz

如需发布 TF，在 `config/hi04.yaml` 中设置：

```yaml
publish_tf: true
tf_parent_frame: "world"
frame_id: "hi04_link"
```

然后启动：

```bash
ros2 launch hi04_ros hi04.launch.py
```

TF 发布关系为：

```text
tf_parent_frame -> frame_id
```

平移量为 0，旋转量来自 HI04 TPDO4 四元数。RViz 中可将 Fixed Frame 设置为
`world`，并添加 TF 显示。

## 数据说明

- TPDO1 加速度原始话题发布 mG 数据。
- 组合 IMU 中的线加速度会转换为 m/s^2。
- TPDO2 角速度原始话题发布 deg/s 数据。
- 组合 IMU 中的角速度会转换为 rad/s。
- TPDO4 四元数会转换为 ROS 使用的 x、y、z、w 顺序。
- `normalize_quaternion: true` 时会对四元数归一化。

## 测试

在包目录中运行协议解析测试：

```bash
cd /home/agilex/ros2_project/mini_cobot/src/HI04_ros
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q test/test_hi04_parser.py
```

## 常见问题

如果启动时报 CAN 口打开失败，检查 CAN 口是否存在并已启动：

```bash
ip link show can0
```

如果收不到话题数据，检查：

- HI04 是否在总线上发送数据。
- `node_id` 是否与设备实际 CANopen 节点 ID 一致。
- `channel` 或 `port_name` 是否指向正确 CAN 口。
- CAN 波特率是否与设备一致。
- 话题名是否在 YAML 中被改成了其他名称。

如果 TF 不显示，检查：

- `publish_tf` 是否为 `true`。
- `tf_parent_frame` 是否非空。
- `tf_parent_frame` 和 `frame_id` 是否不同。
- 是否已经收到四元数 TPDO4 数据。
