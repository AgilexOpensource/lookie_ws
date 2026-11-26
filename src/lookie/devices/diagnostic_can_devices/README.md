# CAN 设备诊断节点

适用于本机 ROS 2 Humble / Ubuntu 22.04。脚本可直接运行，不要求创建 ROS 包或执行 colcon 构建。

## 工作方式

- 用 `ip -details -json link show` 读取实际接口类型、UP 状态、CAN 控制器状态和配置波特率。
- 每个有效 CAN 接口独立启动一个持续运行的 `canbusload <接口>@<波特率>` 进程，不使用终端重绘或颜色选项。
- `canbusload` 每秒输出一次统计。取最近两个完整的一秒帧数的平均值作为帧率，单位为 frames/s，而不是把两秒帧数相加当作帧率。
- 每 **2 秒**向 YAML 指定的话题发布一个 `diagnostic_msgs/msg/DiagnosticArray`。其 `status` 数组按 YAML 顺序包含所有配置接口，即使接口不存在也不会省略。
- `DiagnosticStatus.name` 和 `hardware_id` 均为对应的 CAN 接口名。
- `values` 包含预期/实际波特率、帧率下限、实测帧率、busload 百分比、采样数量及采样年龄等信息。
- 接口出现、恢复或重新创建后会自动重新采样；采样进程退出或超过 3.5 秒没有新样本会重启。节点退出时清理子进程。

状态规则：

- **OK (0)**：接口 UP，实际波特率等于配置值，最近两秒平均帧率 `>= min_fps`，且未处于已知异常 CAN 状态。
- **WARN (1)**：波特率正确但帧率不足，或者控制器处于 ERROR-WARNING / ERROR-PASSIVE。
- **ERROR (2)**：接口不存在、非物理 CAN、DOWN、波特率不符、BUS-OFF / STOPPED / SLEEPING，或者系统查询/采样进程失败。
- **STALE (3)**：尚未收集到两个完整样本，或最新样本超过 3.5 秒未更新。

注意：`canbusload` 显示的 `@500000` 是传入的统计参数，不能证明接口实际波特率正确。实际值以 `ip` 读取的控制器配置为准。节点只读，不设置接口、不修改波特率，也不主动发送 CAN 帧。busload 仅作为诊断信息，不作为 OK 判据。

帧率为整个接口的总帧率，包含 canbusload 能观测到的接收及本地发送回环帧，并非某个 CAN ID 的频率，也不能证明每个从设备都正常。此示例面向经典 CAN；不支持 vcan 或 CAN FD 数据相位波特率检查。

## YAML 配置

编辑同目录的 [can_devices.yaml](can_devices.yaml)：

```yaml
topic: /diagnostics
devices:
  - name: can_chassis_imu
    bitrate: 500000
    min_fps: 700
```

已提供全部六个接口。示例帧率下限分别为：IMU 700、底盘 200、右臂 2800、躯干 400、左臂 2700、头部 350 frames/s。这些值是根据给出的正常帧率留出余量的示例，不是硬件规格；请按不同工作模式的正常最低帧率调整。

`name`、`bitrate`、`min_fps` 必填；接口名不可重复。`min_fps` 为非负有限数值；设为 0 相当于不要求正帧率，但仍需要有效采样。配置只在启动时加载，修改后重启节点或服务。

## 手动运行

安装依赖（由管理员执行）：

```bash
sudo apt-get install can-utils iproute2 python3-yaml ros-humble-diagnostic-msgs ros-humble-rclpy
```

启动：

```bash
cd /home/agilex/develop/diagnostic_can_devices
bash start_diagnostic_can_devices.sh
```

也可在已加载 ROS 环境的终端直接指定配置：

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 diagnostic_can_devices_node.py --config /home/agilex/develop/diagnostic_can_devices/can_devices.yaml
```

使用系统 `/usr/bin/python3`，不要使用与 Humble Python 3.10 ABI 不兼容的虚拟环境。

另一个终端查看：

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo /diagnostics
ros2 topic hz /diagnostics
```

期望发布频率约 **0.5 Hz**。启动后需要几秒收集样本，短暂 STALE 属于正常行为。

ROS 参数可透传，例如更换节点名或话题：

```bash
bash start_diagnostic_can_devices.sh --ros-args -r __node:=can_health -r /diagnostics:=/can/diagnostics
```

## 开机自启

已提供 [diagnostic-can-devices.service](diagnostic-can-devices.service)。安装前核对 `User`、`WorkingDirectory` 和 `ExecStart`，示例已经采用当前用户名和目录。

**先核对 ROS 网络环境**：服务中的 `ROS_DOMAIN_ID=0` 必须与订阅端一致。若使用其他 DOMAIN_ID、RMW 实现、DDS 配置文件或 ROS 工作空间，请在服务中设置对应环境变量。服务不会自动继承交互式终端的环境或读取用户的 bashrc。

启动脚本支持环境变量 `ROS_SETUP_FILE`、`ROS_WORKSPACE_SETUP` 和 `CAN_DIAGNOSTICS_CONFIG`，分别用于 ROS 安装环境、额外工作空间环境、外部 YAML 路径。例如可在服务的 `[Service]` 中加入：

```ini
Environment=CAN_DIAGNOSTICS_CONFIG=/etc/can-diagnostics/devices.yaml
Environment=ROS_WORKSPACE_SETUP=/home/agilex/ros2_ws/install/setup.bash
```

仅设置实际存在的文件路径。若已有 CAN 初始化服务，可在 `[Unit]` 的 `After` 后追加其服务名，使诊断在初始化之后启动。即使 CAN 接口尚未出现，本节点也会发布 ERROR 并在后续自动检测恢复，不会主动初始化总线。

以下命令需要管理员权限，请手动执行：

```bash
cd /home/agilex/develop/diagnostic_can_devices
sudo install -m 644 diagnostic-can-devices.service /etc/systemd/system/diagnostic-can-devices.service
sudo systemctl daemon-reload
sudo systemctl enable --now diagnostic-can-devices.service
```

查看运行状态和日志：

```bash
systemctl status diagnostic-can-devices.service
journalctl -u diagnostic-can-devices.service -f
```

修改 YAML 后：

```bash
sudo systemctl restart diagnostic-can-devices.service
```

如果订阅端收不到消息，先检查日志、ROS_DOMAIN_ID、ROS_LOCALHOST_ONLY、RMW_IMPLEMENTATION 及 DDS 网络设置是否一致。服务默认以普通用户接收 SocketCAN 数据；若机器有额外安全策略，请按日志调整权限，不要默认改成 root。

## 测试

```bash
source /opt/ros/humble/setup.bash
cd /home/agilex/develop/diagnostic_can_devices
ROS_LOCALHOST_ONLY=1 /usr/bin/python3 -m unittest -v test_diagnostic_can_devices test_ros_diagnostics
```

离线测试覆盖输出解析、阈值边界、配置校验、接口/总线故障、采样过期、进程重试和清理；ROS 集成测试使用独立话题接收三条消息，检查接口列表、时间戳、两秒周期、话题重映射和正常退出。集成测试会启动真实采样节点，但不会配置总线或发送帧。
