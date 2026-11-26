# launch_control ROS 2 进程管理器

## 概述

`launch_control` 通过用户目录中的配置文件注册子进程，提供 ROS 2 服务用于启动、停止、重启，并发布运行状态。适用于统一管理相机、机械臂及数据采集等程序。

本目录包含两个包：

- `launch_control`：进程管理节点、启动入口、配置模板及 systemd 服务模板。
- `launch_control_msgs`：进程控制服务与状态消息接口。

## 目录

- [环境要求](#环境要求)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [服务与状态话题](#服务与状态话题)
- [日志](#日志)
- [开机启动](#开机启动)
- [常见问题](#常见问题)

## 环境要求

- Linux、Python 3、ROS 2；以下命令以本机 ROS 2 Humble 为例。
- `colcon`、`ament_cmake`、`rclpy`、`launch_ros`、ROS 接口生成工具及 Python `psutil`。
- 被管理程序及其依赖需要另外安装或编译，并在启动管理器前加载对应环境。

本文命令中的工作空间路径仅为示例，执行时进入自己的工作空间。新生成的 service 和 run.sh 会在编译时填入安装路径，无需手动修改服务文件。

## 目录结构

```text
launch-control-ros2/
├── README.md
├── launch_control/
│   ├── scripts/launch_control.py
│   ├── launch/launch_control.launch.py
│   ├── config/
│   │   ├── robot_config.bash
│   │   ├── extend_launch.sh
│   │   └── auto_launch.sh
│   ├── shell/run.sh
│   └── service/
│       ├── launch_control.service
│       └── launch_control.env.service
└── launch_control_msgs/
    ├── msg/LaunchStatus.msg
    └── srv/
        ├── LaunchNode.srv
        └── SetEmpty.srv
```

## 快速开始

### 1. 安装依赖并编译

在已安装 ROS 2 Humble 和已初始化 rosdep 的环境中执行：

```bash
source /opt/ros/humble/setup.bash
cd /home/agilex/develop/launch_control/launch_control_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select launch_control_msgs launch_control
source install/setup.bash
```

### 2. 初始化用户配置

节点从运行用户的 home 目录读取配置，不直接读取包内模板。以下命令保留已有同名文件：

```bash
LAUNCH_CONTROL_SHARE="$(ros2 pkg prefix launch_control)/share/launch_control"
cp -n "$LAUNCH_CONTROL_SHARE/config/robot_config.bash" "$HOME/robot_config.bash"
cp -n "$LAUNCH_CONTROL_SHARE/config/extend_launch.sh" "$HOME/extend_launch.sh"
cp -n "$LAUNCH_CONTROL_SHARE/config/auto_launch.sh" "$HOME/auto_launch.sh"
```

在 `~/extend_launch.sh` 中添加一个不依赖硬件的演示进程：

```text
"demo_sleep", `/usr/bin/sleep 3600`, true, true, false
```

注册配置不会自动启动进程。如需管理器启动时自动运行，在 `~/auto_launch.sh` 中添加：

```text
"demo_sleep", "start"
```

### 3. 启动管理器

```bash
ros2 launch launch_control launch_control.launch.py
```

也可以直接运行，二者任选其一：

```bash
ros2 run launch_control launch_control.py
```

默认节点名为 `launch_control_node`。当前没有自定义 ROS 配置参数，配置通过下文三个文件完成。同一环境中只启动一个管理器，避免同名服务和日志目录冲突。

### 4. 验证并控制进程

新开终端并加载环境：

```bash
source /opt/ros/humble/setup.bash
source /home/agilex/develop/launch_control/launch_control_ws/install/setup.bash
ros2 service call /get_all_info launch_control_msgs/srv/SetEmpty '{}'
ros2 topic echo /launch_status
```

退出 `echo` 后可手动启动、停止演示进程；若已配置自动启动，再次 `start` 会返回已运行：

```bash
ros2 service call /launch_control launch_control_msgs/srv/LaunchNode \
  '{launch_id: demo_sleep, launch_op: start}'
ros2 service call /launch_control launch_control_msgs/srv/LaunchNode \
  '{launch_id: demo_sleep, launch_op: stop}'
```

## 配置说明

### `~/extend_launch.sh`：注册子进程

每行格式如下，虽然扩展名是 `.sh`，但这是管理器解析的数据文件，不能作为 shell 脚本执行或 source：

```text
"进程ID", `命令 参数`, 保存日志, 轮换日志, 检查运行状态, 关闭等待秒数
```

- 第 1 项：唯一进程 ID，建议使用小写字母、数字和下划线，服务调用时必须匹配。不要使用内置 ID `close_all`。
- 第 2 项：可执行命令及参数。
- 第 3 项：是否将标准输出和错误输出保存到文件，默认 `true`；`false` 时继承管理器输出。
- 第 4 项：每次重新启动是否保留上一份日志，默认 `false`。设为 `true` 后旧日志加数字后缀；`false` 会覆盖本次管理器会话内该进程的同名日志。第 3 项为 `false` 时不启用轮换。
- 第 5 项：是否检查运行状态（`check_status`），默认 `true`。设为 `false` 时，两个状态话题均将该条目报告为 `true`；实际启动、停止和异常退出检查仍依据真实进程状态。这只屏蔽话题上报，不决定自启要不要再拉起，组合后的行为见「功能边界与风险」。
- 第 6 项：停止时 `SIGTERM` 阶段的最长等待秒数（`shutdown_timeout`），可不填或留空，默认 `90`。先向该进程所在会话发送 `SIGTERM`，等待这段时间；仍未退出则发送 `SIGKILL`，再等待同样长的时间。值为 `0` 时，`SIGTERM` 阶段不等待，随即强杀，强杀阶段最多再等 90 秒。必须是大于等于 0 的有限数字。写成 `true`、`false` 或其他非法值时，这一整行不会注册，终端和 `launch.log` 会记录 `invalid shutdown timeout`。后面还有字段时，空着的第 6 项也要保留逗号，否则后一项会占到第 6 项的位置。

布尔值推荐统一写为 `true` 或 `false`。例如，已安装相应演示包时可注册：

```text
"demo_talker", `ros2 run demo_nodes_cpp talker`, true, true, true, 90
"demo_listener", `ros2 run demo_nodes_py listener`, true, false, true
```

只写前五项时，第 6 项按 90 秒处理。原先第 6 项写成 `true` 或 `false` 的行需要改成秒数，否则该行不会注册。需要停止后马上强杀时写 `0`，例如：

```text
"open_piper", `/bin/bash /绝对路径/start_piper.sh`, true, false, true, 0
```

解析器按逗号分字段、按空格分命令参数，并移除双引号、反引号和方括号；`#` 后的内容视为注释。它不执行 shell 展开，不支持直接在命令中使用 `$VAR`、`~`、管道、重定向、`&&` 或需要引号保护的空格参数。复杂启动过程应写成独立脚本，再注册 `/bin/bash /绝对路径/start_camera.sh`。

配置约每秒检查一次修改时间。新增条目会注册；修改正在运行条目的命令或选项会停止并重新启动该进程。删除或注释条目不会注销已加载的进程：先调用 `stop`，再修改配置并重启管理器，才能完全移除。

### `~/robot_config.bash`：子进程环境变量

```bash
export ROBOT="333"
export RCUTILS_LOGGING_USE_STDOUT=1
export PREFIX=$(ros2 pkg prefix demo_nodes_cpp)/share
export AAABBB=$ROS_VERSION/config/1.yaml
```

管理器约每秒检查文件，并在处理控制请求前重新检查。新启动的子进程继承更新后的环境，已运行的进程需要重启。

此文件由简单解析器读取，不是完整 Bash，不要在这里写 `source`。没有 `$` 的普通值仍是 `export KEY=value`。值里的 `$ROS_VERSION` 和 `${ROS_VERSION}` 会从当前环境替换，名字到 `/` 这类非名字字符为止，只替换一层。双引号里的引用会展开。整段单引号不展开，按去掉外层单引号后的字面量保存。`$$`、单独的 `$` 和反引号保持原样。变量未设置时，这一行不写入，旧值保留，终端和 `launch.log` 会记下这个名字。

值里的 `$(命令)` 会用 `sh -c` 执行，把标准输出去掉末尾换行后填回原处，前后可以有其它文字。命令继承管理器当前环境，同一文件里更早写成功的变量可以被后面的命令或 `$变量` 用到。退出码不是 0、超时或 `$()` 没有闭合时，这一行不写入，已经存在的旧值保留，并记录原因。单次命令最长等待 10 秒。这条命令跑在配置热读取的循环里，慢命令会挡住配置重读和控制请求。

删除配置行不会清除已载入的环境变量，需要重启管理器。ROS 工作空间环境应在启动管理器前 source，或由子进程的独立启动脚本加载。

身份/目录变量（`user/USER/home/HOME/LOGNAME`）、路径变量（`PATH/PYTHONPATH/LD_LIBRARY_PATH/AMENT_PREFIX_PATH/CMAKE_PREFIX_PATH/COLCON_PREFIX_PATH`）、工作空间变量（`LAUNCH_CONTROL_WS/LAUNCH_CONTROL_SETUP`）和已列入代码 `STARTUP_ENV_KEYS` 的 ROS/DDS 初始化变量不允许从此文件加载，发现后记录提示并跳过。它们必须在启动前配置，变更后重启管理器，避免管理器与子进程使用不一致的环境。普通业务变量仍按原规则更新；删除行仍需重启才能清除旧值。

### `~/auto_launch.sh`：启动时执行操作

```text
"demo_talker", "start", true, 3, 5
"demo_listener", "start", false, -1, 10
"demo_once", "start"
```

每行是进程 ID 和操作，支持 `start`、`stop`、`restart`。管理器启动时按文件顺序执行一次，这一次不计入重试。运行期间修改该文件不会重新执行；它也不等待前一个业务节点就绪。

后三个字段可选，只对 `start` 和 `restart` 生效：

- 第 3 项：是否检测运行状态，默认 `true`。这不是 `extend_launch.sh` 的第 5 项。extend 的 `check_status` 只决定状态话题在 `false` 时是否恒报 true，不决定要不要拉起。两种开关叠在一起时的反复启动和阻塞见「功能边界与风险」。
- 第 4 项：重试次数，默认 `0`。`-1` 表示无限重试，`0` 表示不重试，正整数表示最多重试这么多次。小于 `-1` 视为非法。
- 第 5 项：每次重试的间隔秒数。次数不是 `0` 时必填，且必须是大于 0 的有限数字。次数为 `0` 时忽略这一项。

检测为 `true` 时，进程在运行就不再重试，也不计次。进程停止或启动失败后，先等待间隔，再执行 `start` 并计一次。之后如果再次停止，再等一个间隔。已经用掉的次数不会因为进程恢复运行而清零。

检测为 `false` 时，不看进程当前是在运行还是已停止，每个间隔都重试一次。已经在运行时先停止再启动；没有在运行时直接启动。每一次都计次。

次数用完后保留最后一次操作的结果，不再拉起。`-1` 不会因次数停止。`stop`、`close_all` 和其它操作没有重试逻辑，多写的重试字段会被忽略，命令只执行一次。`stop` 在当时没有正在运行的进程时不会等待，也不会把进程拉起。重试字段非法时仍执行这一次操作，并按不重试处理。手动 `start` 或 `restart` 不会重新启用已被取消的重试。细节见「功能边界与风险」。

重试会在终端和 `launch.log` 记录当前次数和配置的总次数，例如 `[retry] [demo_talker] 1/3`。无限次记为 `[retry] [demo_talker] 4/-1`。次数用尽记为 `[retry] [demo_talker] reached 3/3`，被手动停止取消记为 `[retry] [demo_talker] cancelled`。

## 功能边界与风险

### 在运行是什么意思

管理器把“在运行”定义成子进程还没有退出：系统调用 `poll()` 仍为空。业务节点是否就绪、硬件是否就绪、启动阶段是否结束，都不在这个判断里。

- `start` 返回成功只表示创建了子进程。
- 进程自己退出就视为停止，退出码是 0 也一样。管理器没有启动宽限时间，也不会把“还在初始化”当成一种单独状态。
- `extend_launch.sh` 第 5 项 `check_status` 为 `false` 时，`/launch_status` 和 `/launch_diagnostic` 里该条目固定报 `true`。真实的启动、停止和退出判断不变；`/get_extend_launch_run_id` 仍按真实进程回报。这种固定上报就是状态被屏蔽。

### 自启各操作有什么逻辑

自启行在管理器启动时按文件顺序执行一次。重试只加在 `start` 和 `restart` 上。`stop`、`close_all` 以及其它操作没有重试逻辑：重试字段忽略，按对应的普通控制执行一次后就结束。运行期间修改 `auto_launch.sh` 不会重新加载。

- `stop`，且当时没有正在运行的进程：不发停止信号，不等待退出，也不占用热读取那条循环，更不会把这个进程拉起。ID 已注册时结果为失败，消息是进程未在运行；ID 未注册时结果为失败，消息是没有这个功能。这一行不建立重试。若文件中更早的一行已经为该 ID 留下重试，这一次 `stop` 会把它取消。
- `stop`，且进程正在运行：停止该进程，并取消它尚未用完的重试。这一行不建立新的重试。
- `start` 或 `restart`，第 3 项为 `true`：进程还在就不再拉起，也不计次。进程若在启动过程中自行超时并退出，先等间隔，再 `start`，并计一次。后来又跑起来不会把已用次数清零。`check_status` 为 `false` 挡不住这次重试，两个状态话题却继续显示在运行。次数为 `-1` 时会一直这样做，直到 `stop`、`close_all` 或管理器退出。
- `start` 或 `restart`，第 3 项为 `false`：不看进程是否还在。间隔一到，正在启动或已经在运行都会先停止再启动。间隔短于业务自己的启动时间时，还没起来的进程会被这次停止打断。
- 启动后父进程马上退出的一次性脚本，以及父进程退出后把工作留在后台的命令，都会被当成已停止。配了重试就会再拉起一份，后台那一份可能还在。
- 手动 `start` 或 `restart` 不会重新打开已经被取消的重试。`close_all` 的 `start` 只是普通的全部停止，并因此取消各 ID 尚未用完的重试，没有按间隔再拉起。

### 停止和重试会堵住哪些功能

`stop`、`restart`，以及自启第 3 项为 `false` 时的重试，都在同一条后台循环、同一把锁里等待进程退出。默认先等最多 90 秒 `SIGTERM`，再等最多 90 秒 `SIGKILL`。等待期间：

- `extend_launch.sh` 和 `robot_config.bash` 的热读取不会进行。
- `/launch_status` 和 `/launch_diagnostic` 不会更新。
- 其它启动、停止、重启请求要等这次关闭结束。

自启第 3 项为 `true` 且进程已经退出时，重试只是创建新进程，通常不会长时间占住这条循环。已经在运行、并且不是这次要停止的业务进程，不会因为这把锁而暂停。

这些进程边界仍然有效：修改正在运行条目的命令或选项会先停再起；删除或注释配置行不会注销已加载进程；`robot_config.bash` 的更新不会进入已经在跑的进程。

## 服务与状态话题

### 控制单个进程

`/launch_control` 类型为 `launch_control_msgs/srv/LaunchNode`，请求包含字符串 `launch_id`、`launch_op`，响应包含布尔值 `success` 和字符串 `message`。

```bash
ros2 service call /launch_control launch_control_msgs/srv/LaunchNode \
  '{launch_id: demo_sleep, launch_op: restart}'
```

- `start`：启动未运行的进程，已运行时返回 `success: false`。
- `stop`：停止运行中的进程，未运行时返回 `success: false`。
- `restart`：先停止，再等待约 3 秒后启动。

启动成功仅表示创建了子进程，不代表业务节点或硬件已经就绪。子进程之后退出会被记录并发布为未运行。只有 `auto_launch.sh` 里为该次自动 `start` 或 `restart` 配置了非 0 重试次数时，管理器才会按该规则再拉起；未配置重试的条目，以及手动启动的进程，退出后不会自动重启。

### 停止所有受管理进程

内置 `close_all` 使用 `start` 操作触发，管理器本身继续运行：

```bash
ros2 service call /launch_control launch_control_msgs/srv/LaunchNode \
  '{launch_id: close_all, launch_op: start}'
```

需要结束管理器时，建议先执行该命令，再在前台按 `Ctrl+C` 或停止 systemd 服务。

### 查询配置和运行状态

以下服务均使用空请求，返回 `success` 和文本 `message`：

```bash
# 所有已注册进程及其配置
ros2 service call /get_extend_launch_info launch_control_msgs/srv/SetEmpty '{}'

# 正在运行的进程 ID；没有运行进程时 success 为 false
ros2 service call /get_extend_launch_run_id launch_control_msgs/srv/SetEmpty '{}'

# 配置与运行 ID 的汇总
ros2 service call /get_all_info launch_control_msgs/srv/SetEmpty '{}'
```

`/launch_status` 类型为 `launch_control_msgs/msg/LaunchStatus`，约每秒发布一次，处理控制请求后也会发布：

```text
string[] launch_id_list
bool[] launch_status
```

两个数组按下标对应，`true` 表示子进程仍在运行，不代表业务健康检查通过。`check_status` 为 `false` 时该值固定为 `true`，见「功能边界与风险」。

同时发布 `/launch_diagnostic`，类型为 `diagnostic_msgs/msg/DiagnosticArray`，发布时机与 `/launch_status` 相同：

- `header.stamp` 使用节点 ROS 时钟记录本次采样时间，`header.frame_id` 保持默认空字符串。
- 每个 launch 对应一个 `DiagnosticStatus`，`name` 为 launch ID。
- `values` 仅包含一项：`key` 为 `launch_status`，`value` 为字符串 `"true"` 或 `"false"`，不包含 PID。
- `level`、`message`、`hardware_id` 保持默认值；默认 `level=0` 不表示业务健康检查通过。
- 没有已注册 launch 时，仍发布带时间戳、`status` 为空数组的消息。

```bash
ros2 topic echo /launch_diagnostic
```

## 日志

日志根目录为运行用户的 `~/.agilex/log/`：

- `launch.log`：管理器跨会话的操作日志。
- `YYYY-MM-DD_HH-MM-SS/launch.log`：本次管理器会话日志。
- 同目录的 `<进程ID>-stdout.log`、`<进程ID>-stderr.log`：启用文件日志的子进程输出。
- `latest`：指向最近一次会话目录的软链接。

```bash
tail -f ~/.agilex/log/latest/launch.log
tail -f ~/.agilex/log/latest/demo_sleep-stderr.log
```

管理器启动时会清理超过约 31 天的旧日志目录和根目录旧文件，并处理根目录超过 100 MiB 的日志文件；这不是对子目录内所有日志的实时大小限制，需要按实际输出量关注磁盘空间。

## 开机启动

推荐部署 **编译后生成的 service**，它直接调用安装后的 `run.sh`。源码中的两份旧 service 和 `shell/run.sh` 保留供对照，不用于下面的新部署流程。

### 编译时生成路径和运行用户

以普通用户进入工作空间，执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select launch_control_msgs launch_control
source install/setup.bash
```

CMake 配置阶段生成入口，colcon 安装阶段将其安装到：

- `<包安装前缀>/lib/launch_control/run.sh`
- `<包安装前缀>/share/launch_control/service/generated/launch_control.service`

service 的 `User=` 默认是首次配置时执行编译的用户。不要使用 `sudo colcon build`，否则默认用户可能成为 root。用户名和 setup 路径保存在 CMake 缓存中；切换构建用户、安装布局或路径后，应清理缓存重新配置，或显式传入参数：

```bash
colcon build --packages-select launch_control_msgs launch_control --cmake-clean-cache \
  --cmake-args -DLAUNCH_CONTROL_SERVICE_USER=agilex
```

默认支持 colcon 普通隔离安装（`install/launch_control`）和 `--merge-install`（`install`）：按安装前缀最后一级是否为包名识别布局。非标准目录或合并安装目录恰好叫 `launch_control` 时，必须显式指定工作空间 setup：

```bash
colcon build --packages-select launch_control_msgs launch_control --cmake-args \
  -DLAUNCH_CONTROL_SERVICE_USER=agilex \
  -DLAUNCH_CONTROL_SETUP=/absolute/workspace/install/setup.bash
```

`setup.bash` 在整个构建结束后生成，因此 CMake 不要求它在首次配置时已存在；入口会在启动时检查。生成文件使用绝对路径，移动工作空间后必须重新构建并重新拷贝 service。特殊路径字符会在配置阶段被拒绝；建议使用常规目录名。

入口每次加载指定 setup，并检查 `ros2 pkg prefix launch_control` 是否匹配编译时的安装前缀，发现其他同名部署时直接报错。默认通过 `ros2 run` 启动，支持显式 `run` 和 `launch` 两种模式：

```bash
LAUNCH_CONTROL_PREFIX="$(ros2 pkg prefix launch_control)"
# 默认模式，也支持直接追加 --ros-args 等节点参数
"$LAUNCH_CONTROL_PREFIX/lib/launch_control/run.sh"
"$LAUNCH_CONTROL_PREFIX/lib/launch_control/run.sh" run --ros-args -r __node:=launch_control_node
# launch 模式：参数原样转交 ros2 launch；此命令只展示参数，不启动节点
"$LAUNCH_CONTROL_PREFIX/lib/launch_control/run.sh" launch --show-args
```

不带 `--show-args` 时，launch 模式启动包内 `launch_control.launch.py`。两种模式均不创建或覆盖小写 `user/home`，由 Python 原有逻辑选择环境变量。业务工作空间仍需在各业务启动脚本中加载。

### 配置目录与兼容行为

正常使用普通用户运行且不覆盖身份变量时，从服务运行用户的主目录读取三个配置文件，日志写入其 `.agilex/log/`。systemd 的 `User=` 确定实际身份，`USER/HOME` 由运行环境提供，入口不再自行设置小写变量。

Python 保留原来的选择顺序：小写 `user/home` 优先，其次为非 root 的 `USER/HOME`，最后回退到 `agilex` 和 `/home/agilex`。因此不建议使用 root 启动。选中的 home 必须为已存在的非空绝对目录。节点初始化后仍按旧逻辑同步大小写变量。日志不再自动执行 `chown 1000:1000`；旧日志权限不匹配时需在部署阶段处理。

已有小写环境变量 `home`、`user` 继续兼容， 优先级保持不变，Python 识别逻辑未修改。但正常部署无需设置 `USER/user/HOME/home`。建议 `/etc/default/launch_control` 仅配置启动前需要的 ROS/业务环境，例如：

```ini
# home=/home/agilex
# user=agilex
ROS_DOMAIN_ID=0
```

此文件是 systemd 的环境赋值文件，不是 Bash 脚本，不写 `export` 或 `source`。修改它后重启服务才生效。若显式覆盖 `home`，它还会改变子进程继承的 HOME，但不会改变 `WorkingDirectory=~` 对应的实际用户主目录；业务命令应使用绝对路径。

这些变量不会改变进程的实际系统身份；身份由 service 的 `User=` 决定。生成入口不使用 `LAUNCH_CONTROL_WS` 切换路径，变更路径需重新生成。保留的旧 `.env.service` 仍使用原来的工作空间覆盖方式。

仅切换实际运行用户无需重新编译。使用 `sudo systemctl edit launch_control.service` 添加：

```ini
[Service]
User=robot
```

然后执行 `sudo systemctl daemon-reload` 和 `sudo systemctl restart launch_control.service`。新账号必须能访问当前安装路径，并已准备配置和设备权限；清除环境文件中不再需要的旧用户/目录覆盖。运行身份变化不会自动切换到另一份程序。

如需服务改用 launch 模式，同样通过 drop-in 覆盖 `ExecStart`（替换为生成 service 中的真实路径）：

```ini
[Service]
ExecStart=
ExecStart="/absolute/install/launch_control/lib/launch_control/run.sh" launch
```

旧两份 service 仅保留作参考：它们仍指向安装位置的 run.sh，该位置已更新为新入口，所以旧文件不代表旧行为快照。尤其旧普通 service 未指定 `User`，不要用于新的部署。

编译不会自动创建或覆盖用户配置。请在服务运行用户的终端中初始化（若指定了 `home`，将下面的 `$HOME` 换成该目录）：

```bash
source install/setup.bash
LAUNCH_CONTROL_PREFIX="$(ros2 pkg prefix launch_control)"
cp -n "$LAUNCH_CONTROL_PREFIX/share/launch_control/config/robot_config.bash" "$HOME/robot_config.bash"
cp -n "$LAUNCH_CONTROL_PREFIX/share/launch_control/config/extend_launch.sh" "$HOME/extend_launch.sh"
cp -n "$LAUNCH_CONTROL_PREFIX/share/launch_control/config/auto_launch.sh" "$HOME/auto_launch.sh"
```

### 拷贝生成的服务并启用自启

先完成配置和前台验证，停止前台管理器，避免同时运行两个实例：

```bash
source install/setup.bash
LAUNCH_CONTROL_PREFIX="$(ros2 pkg prefix launch_control)"
cat "$LAUNCH_CONTROL_PREFIX/share/launch_control/service/generated/launch_control.service"
sudo install -m 644 \
  "$LAUNCH_CONTROL_PREFIX/share/launch_control/service/generated/launch_control.service" \
  /etc/systemd/system/launch_control.service
sudo systemctl daemon-reload
sudo systemctl enable --now launch_control.service
systemctl status launch_control.service
journalctl -u launch_control.service -f
```

若服务已经运行，更新部署后还需 `sudo systemctl restart launch_control.service`；`enable --now` 不会重启已运行的实例。`Restart=always` 仅重启管理器，不负责重启单独退出的业务子进程。

停止并取消自启：

```bash
sudo systemctl disable --now launch_control.service
```

## 常见问题

### 找不到包、脚本或接口

确认编译了两个包，并在每个操作终端加载 `launch_control_ws/install/setup.bash`。使用以下命令确认实际加载的包：

```bash
ros2 pkg prefix launch_control
ros2 interface show launch_control_msgs/srv/LaunchNode
```

本独立版本使用 `launch_control_msgs`。

### 提示找不到配置或没有注册进程

确认三个文件位于实际运行用户的 home，而不是仅修改源码中的模板。直接运行节点时，小写环境变量 `home`、`user` 优先于 `HOME`、`USER`；root 环境默认回退至 `/home/agilex` 和 `agilex`。启动日志会打印实际日志目录，可据此判断目录是否正确。

### 服务一直等待或看不到状态

确认管理器仍在运行、客户端已加载接口包，并与管理器使用相同的 ROS 通信环境（如 `ROS_DOMAIN_ID`）。检查 `ros2 service list` 和管理器日志。

### 启动成功但进程很快退出

查看该进程的 stderr/stdout 日志。常见原因包括业务包未安装、未 source 业务工作空间、可执行文件路径不正确、硬件缺失，以及把 shell 表达式直接写进命令字段。先在相同环境中单独验证业务命令，再注册到管理器。

### 修改配置后行为没有变化

`extend_launch.sh` 和 `robot_config.bash` 约每秒重读；`auto_launch.sh` 仅启动时读取。删除已注册条目不会自动停止或注销进程，环境变量更新也不会改变已运行进程的环境，详见配置说明。

### 停止请求长时间没有返回

停止时先向子进程会话发送 `SIGTERM`，并等待第 6 项配置的秒数，默认 90 秒。到时仍未退出则发送 `SIGKILL`，再等待同样长的时间。第 6 项为 `0` 时跳过第一段等待并直接强杀，强杀阶段最多再等 90 秒。停止服务调用在等待期间会阻塞。两个阶段结束后仍有进程存活时，本次停止失败，错误信息中包含剩余进程号。

## 维护说明

修改入口、配置解析规则、消息类型或服务名称后，应同步更新本文档。本文依据当前源码描述行为；部署时应结合实际业务节点验证启动、停止及日志输出。
