# HiPNUC(hi04) serial ros2 package

## 原始工程

This repository is extracted from

`examples/ROS2/hipnuc_ws/src/`

Original repository:

<https://github.com/hipnuc/products.git>

commit: [5a43802](https://github.com/hipnuc/products/commit/5a4380272cd70402e7f8928b05a6af4bfa659807)

## 依赖安装

需要gps-msgs包，本文在humble下编译通过

```bash
sudo apt install ros-$ROS_DISTRO-gps-msgs
```

## USB规则

`src/hi04_serial_ros2/hipnuc_imu/config/head_imu.rules`路径下有将串口模块绑定在指定usbpath上的规则，另起了别名

## 启动读取

默认读取串口名为`/dev/head_imu`

```bash
ros2 launch hipnuc_imu run_imu.launch.py
```

## 问题解决

编译会出现：

```bash
--- stderr: hipnuc_imu_can                                                                        
/home/agilex/hi04_serial_ws/src/hi04_serial_ros2/hipnuc_imu_can/src/imu_node_can.cpp: In member function ‘void hipnuc_driver::CanImuPublisher::read_loop()’:
/home/agilex/hi04_serial_ws/src/hi04_serial_ros2/hipnuc_imu_can/src/imu_node_can.cpp:325:35: warning: comparison of integer expressions of different signedness: ‘canid_t’ {aka ‘unsigned int’} and ‘int’ [-Wsign-compare]
  325 |         if ((frame.can_id & 0x7f) != node_id)
      |             ~~~~~~~~~~~~~~~~~~~~~~^~~~~~~~~~
---
Finished <<< hipnuc_imu_can [6.82s]
Finished <<< hipnuc_imu [7.21s]                                                                
--- stderr: hipnuc_gnss                              
/home/agilex/hi04_serial_ws/src/hi04_serial_ros2/hipnuc_gnss/src/ins_module.cpp:35:21: warning: ‘raw’ defined but not used [-Wunused-variable]
   35 | static hipnuc_raw_t raw;
      |                     ^~~
---
Finished <<< hipnuc_gnss [8.11s]
```

只是warn，可以忽略

### 串口 IMU 的 TF 发布

`hipnuc_imu` 支持以下启动参数，也可以在 `hipnuc_config.yaml` 的
`IMU_publisher.ros__parameters` 中设置：

```yaml
publish_tf: false
tf_parent_frame: "world"
tf_child_frame_id: ""  # 未设置或为空时使用 frame_id
```

启用示例：

```bash
ros2 launch hipnuc_imu run_imu.launch.py publish_tf:=true tf_parent_frame:=world
```

启用后在 `/tf` 发布 `tf_parent_frame -> tf_child_frame_id`。`tf_child_frame_id`
必须为字符串，未设置或为空时沿用 `frame_id`；有效名称不能为空、以 `/` 开头或包含空白字符，
启用 TF 时不能与父坐标系相同。此参数只影响 TF，不改变 IMU 消息的 `frame_id`。
例如 `frame_id:=imu_head_link tf_child_frame_id:=imu_head` 可分别设置消息和 TF 坐标系。
旋转取自 IMU 四元数（归一化后广播），平移为零，时间戳与 IMU
消息一致；即使 `imu_switch` 关闭，TF 仍可独立发布。无效四元数不发布 TF。
这些参数与现有参数一样在节点启动时读取，修改后需重启。

`tf_parent_frame` 应对应设备姿态的实际参考坐标系；修改名称不会转换姿态数据。
此功能不提供位置估计，也不代表 `base_link` 到 IMU 的固定安装变换。
若其他节点已发布同一子坐标系的 TF，请避免重复发布。

动态 TF 使用标准 `/tf`，静态安装变换使用 `/tf_static`。通常不需要改话题名；
需要隔离 TF 时，可以用 ROS remapping，并同步配置 TF 接收端。例如直接运行节点：

```bash
ros2 run hipnuc_imu talker --ros-args -p publish_tf:=true -p tf_parent_frame:=world -p frame_id:=imu_head_link -r /tf:=/imu_tf
```

### 串口断线检测与重连（hipnuc_imu）

驱动始终打开配置中的 `serial_port`，每次重连重新解析该路径。推荐用 udev rules
提供固定名称（例如 `/dev/head_imu`）。如果配置的是 `/dev/ttyUSB0`，
拔插后变成 `/dev/ttyUSB1`，驱动会对原路径报错并重试，不自动搜索其他设备。
路径被其他设备复用时不能仅凭路径识别物理设备，因此固定名称更可靠。

参数可通过 `run_imu.launch.py` 或 YAML 配置：

- `wait_for_device_timeout`：首次启动等待有效 IMU 数据的总时限，单位秒，
  默认 `-1.0` 无限等待；`0.0` 立即超时退出，正数到期报错退出。
  首次等待独立于断线后的重试次数。
- `reconnect_timeout`：每次尝试前的等待时间，单位秒，默认 `6.0`，必须大于零。
  断线后的第一次重试也等待此间隔；首次启动立即尝试打开。
- `reconnect_attempts`：每次断线后的重试上限，默认 `-1` 无限重试；
  `0` 断线即退出，不尝试重新打开；`3` 最多重新打开三次，
  全部失败后报错并以状态码 1 退出。收到有效 IMU 帧后清零，下次断线重新计数。
- `data_timeout`：连续收不到有效 IMU 帧的超时，单位秒，默认 `2.0`，
  必须大于零，应大于设备正常输出间隔。无数据或持续无效数据均触发报错和断线处理。

串口挂断、读错误和流结束会立即触发断线处理；静默停止输出由 `data_timeout`
检测。仅打开串口不算连接成功，必须收到有效的 0x83 或 0x91 IMU 帧。
重连打开后无有效数据也算该次失败，不会清零重试次数。
超时使用单调时钟，不受 ROS 仿真时间影响。Ctrl-C 可中断等待。

示例：

```bash
ros2 launch hipnuc_imu run_imu.launch.py serial_port:=/dev/head_imu \
  wait_for_device_timeout:=30.0 reconnect_timeout:=1.0 reconnect_attempts:=3 data_timeout:=2.0
```

### IMU 安装角校准（0_1_0a1）

新增参数追加在原有 `data_timeout` 参数之后，启动时读取，修改后需重启：

```yaml
imu_install_roll_deg: 0.0
imu_install_pitch_deg: 0.0
imu_install_yaw_deg: 0.0
```

三个参数分别为施加到输出姿态的 roll、pitch、yaw 校准角，单位为度。
正值遵循右手定则，校准旋转相对传感器局部坐标轴，
旋转顺序为 `R = Rz(yaw) * Ry(pitch) * Rx(roll)`。
参数名和排列位置保持不变；节点及 YAML 默认全零，参数必须为有限数值。

姿态按 `q_world_output = q_world_sensor * q_calibration` 旋转；
角速度、加速度和磁场按 `v_output = inverse(R) * v_sensor` 转换，
保证向量与校准后的输出坐标系一致。
例如原始姿态为零，设置 `imu_install_yaw_deg:=90.0` 后，输出 yaw 为 +90°；
传感器 X 方向向量在该输出坐标系中为 -Y 方向。
组合旋转使用四元数相乘，并非将三个欧拉角分别相加。
这属于固定旋转校准，不是自动将每次启动时的朝向归零。

注意：此定义与此前“安装角取逆补偿”的定义不同；单轴旧配置若要保持相同效果，
需要反转角度符号。多轴配置需要求原旋转的逆并重新分解 RPY，不能简单全部取负。

IMU、欧拉角、磁场话题及姿态 TF 同步校准，欧拉角话题仍使用弧度。
`frame_id` 应填写校准后的输出坐标系名称；TF 子坐标系应表示同一物理坐标系。
本功能仅处理旋转，不补偿安装位置偏移。

```bash
ros2 launch hipnuc_imu run_imu.launch.py \
  imu_install_roll_deg:=0.0 imu_install_pitch_deg:=0.0 imu_install_yaw_deg:=90.0
```

上面的 `imu_install_*_deg` 在 ROS 发布前旋转数据，不写设备。下面的 `installation` 把安装方向写入设备，不在 ROS 端再转一次。两套默认都不改变数据；同时启用会叠加。

### 串口安装配置和校准服务

安装配置在设备内部执行。默认 `installation: ""`
不发送任何启动配置命令，保持原有数据读取行为。请先用 `LOG VERSION`
确认固件与厂家手册版本：旧版 HI04 使用矩阵，新版使用方向编码，不能混用。

```yaml
IMU_publisher:
  ros__parameters:
    installation: ""  # 已配置设备时保持为空
    # 旧版默认方向: "1,0,0,0,1,0,0,0,1"
    # 新版默认方向: "24"
    command_timeout_ms: 2000
    calibration_save: false
```

通过 `config_file:=/绝对路径/config.yaml` 加载，或传入启动参数，例如：

```bash
ros2 launch hipnuc_imu run_imu.launch.py installation:="24"
```

矩阵和方向编码模式都会先查询 `LOG USRCONFIG` 的 `URFR=`。矩阵按数值比较
（容差 1e-5），一致时跳过设置、保存和重启，可每次启动保留相同安装参数。
不一致时依次设置、`SAVECONFIG`、`REBOOT`，等待 3 秒后重新查询核验。
查询失败或缺少 URFR 字段时停止配置，不盲写，也不根据矩阵格式推断查询能力。
实机 HI04M3 APP_VER=167 已确认支持矩阵格式的 URFR 读回。
安装写入仍要求明确应答；无应答时不继续保存/重启，也不把超时认作成功。
设备重启会重新建立 6 轴航向零点。启动配置期间不发布数据，并暂停 `data_timeout`。
若这期间串口掉线，马上重新打开，不等待 `reconnect_timeout`；打开失败则隔 200 ms 再试。
安装配置只在本次节点启动时做一次，之后的断线重连不再写安装参数。
失败后禁用数据发布和校准，检查日志并重启节点。重启耗时超过 3 秒的设备需要适配等待时间。

节点名默认为 `IMU_publisher`，提供以下 `std_srvs/srv/Trigger` 服务：

```bash
# 1：航向复位，将当前 yaw 设为零（CONFIG ATT RST 1）
ros2 service call /IMU_publisher/reset_yaw std_srvs/srv/Trigger '{}'
# 2：设置相对零点，将当前 pitch/roll 设为零（CONFIG ATT RST 2）
# 先让头部处于规定的参考姿态并保持静止
ros2 service call /IMU_publisher/calibrate_level std_srvs/srv/Trigger '{}'
# 3：自动校平，仅适用于接近水平的小偏差（CONFIG ATT RST 3，约 ±5°）
ros2 service call /IMU_publisher/auto_level std_srvs/srv/Trigger '{}'
# 5：取消水平校平，清除相对俯仰/横滚零点（CONFIG ATT RST 5）
ros2 service call /IMU_publisher/clear_level std_srvs/srv/Trigger '{}'
# 手动保存当前设备配置到 Flash（SAVECONFIG），不重启设备
ros2 service call /IMU_publisher/save_config std_srvs/srv/Trigger '{}'
```

以上 1、2、3、5 是独立操作的命令编号，不是需要依次执行的校准步骤。
通常先调用 `calibrate_level`，确认效果后调用 `save_config`；不必同时调用其他校平服务。
`reset_heading` 已更名为 `reset_yaw`，调用方需要同步更新。
`calibration_save` 默认 false，校平后不自动保存；可手动调用 `save_config`，
或者设置 `calibration_save:=true`，在 2/3/5 成功后自动发送 `SAVECONFIG`。
`save_config` 保存设备当前所有可持久化配置，不仅是水平校准；它不会让不支持
掉电保持的航向复位变为永久零点。掉电保持效果需用实际固件断电重启验证。
服务成功表示收到设备 `OK`（及按需保存的 `OK`），不是独立测量验证；节点不自动检查
机器人是否静止、头部是否回零。仍需实机检查角度及四元数/TF 是否一起更新。
保存失败会明确报告“校准已执行但保存失败”，不会尝试撤销校准。

同一个串口接收线程分离二进制帧与 ASCII 应答，service 等待命令结果；不要另开
串口工具抢读。超时后设备状态可能不确定，命令通道保持禁用，需检查设备后调用 `reset_command_channel` 或重启节点，
防止迟到应答误确认下一条指令。CRC 失败的帧不再发布。

协议参考：

[>= v1.7.1](https://download.hipnuc.com/legacy/imu_cum_cn_150_170.pdf)

[v1.55 ~ v1.7.0](https://download.hipnuc.com/products/imu/cum.html)。

#### 安装配置超时的诊断

不要通过交替尝试安装格式判断固件版本：超时并不证明设备未执行命令。
先不传 `installation` 启动（若使用 YAML，也应清空该字段），再执行只读查询：

```bash
ros2 launch hipnuc_imu run_imu.launch.py publish_tf:=true magnetic_switch:=true
# 另一个终端，source 同一工作区后
ros2 service call /IMU_publisher/get_version std_srvs/srv/Trigger '{}'
# 仅适用于支持 USRCONFIG 查询的固件
ros2 service call /IMU_publisher/get_configuration std_srvs/srv/Trigger '{}'
```

日志包含 `Serial TX`、命令名、实际写入字节数、期间收到的字节/有效 IMU 帧数量、
完整及未结束的 ASCII 应答。解析支持 CR/LF/CRLF、首尾空白、`ERR`/`ERROR` 及其
冒号或空格分隔的错误详情；二进制帧不作为 ASCII 应答处理。
如果持续收到 IMU 帧但 ASCII 为空，应进一步检查设备 RX 接线、命令接口和固件支持，
不能仅凭能接收数据认定双向通信正常。只读查询超时也会锁定命令通道，需恢复命令通道或重启节点后重试。

启动安装查询会先等待至多 `command_timeout_ms`，争取接收 5 个完整 IMU 帧以同步解析器。
已收到 OK 但缺少 URFR 的只读查询最多重试 3 次，间隔 200 ms；超时不自动重试，
不对安装写入、校平或保存命令自动重试。

### 解除串口命令超时锁定

```bash
ros2 service call /IMU_publisher/reset_command_channel std_srvs/srv/Trigger '{}'
```

此服务只清除节点内部命令锁定，不发送设备命令、不重启、不保存、不重试先前操作。
恢复时接收线程继续读取 IMU 数据并丢弃未请求的应答，等待连续 `command_timeout_ms`
没有 ASCII 输入后解除锁定；最多等待该时间的 3 倍，未稳定则保持锁定并返回失败。
已解锁时直接成功。此前命令是否执行仍未知，可恢复后通过只读查询检查设备状态。
无事务编号的串口协议不能完全排除更晚到达的应答，因此该接口不保证物理链路已经恢复。
启动安装验证失败导致的数据发布禁用不会被此服务解除，仍需检查配置并重启节点。

### 跳过命令执行校验

新增参数 `command_verification` 默认 true，启动时读取，置 false 示例：

```bash
ros2 launch hipnuc_imu run_imu.launch.py publish_tf:=true magnetic_switch:=true command_verification:=false
```

关闭后，设置、校平、保存命令仅检查是否完整写入串口，不等待 OK/ERR；每次写入后
间隔 200 ms。service 的 success 仅表示写入成功，message 会注明执行结果未验证。
串口写入失败仍返回失败；本地安装参数合法性检查不受影响。
只读 `get_version` 和 `get_configuration` 仍等待应答，以返回设备真实信息。

关闭校验且 installation 非空时，不查询比较安装参数，也不做重启后读回；每次启动
直接发送安装设置、保存、重启。因此已设置好安装方式时，可将 installation 留空，
避免每次保存和重启。命令间隔不保证设备处理完成或所有迟到应答已消失；持久化效果
仍需实机确认。默认开启校验时保持原有行为。
