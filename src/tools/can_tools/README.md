# CAN 可用性进程

`can_supervisor.py` 是交给 launch control 管理的前台进程，进程 ID 建议为 `can_health`。
启动时先确认全部必需物理接口都存在，再只对不符合配置的接口执行一次 down、必要时改名、设置经典 CAN 波特率、up。
已经正常的接口不执行写操作。初始化成功后持续只读检查；任一必需接口缺失、改名、被重新创建、DOWN、波特率改变或进入 BUS-OFF/STOPPED/SLEEPING，进程退出。
客户修复供电、接线或配置后，在 rosboard 手动重启该进程。程序不会后台重试或自动重启。

## 配置与只读预检

Python 使用系统 `/usr/bin/python3`，当前验证版本为 3.10；仅用标准库，不依赖 ROS 或 pip。
系统查询和配置需要 iproute2。程序读的是 `can_bus.json`，不从硬件猜测每一路该叫什么名字、该用多少波特率。

例子：

- `0000:03:00.0 / 0x0` -> `can_chassis_imu`，500000。
- `0000:03:00.0 / 0x1` -> `can_chassis`，500000。
- `0000:30:00.0 / 0x0` -> `can_right_arm`，1000000。
- `0000:30:00.0 / 0x1` -> `can_torso`，1000000。
- `0000:31:00.0 / 0x0` -> `can_left_arm`，1000000。
- `0000:31:00.0 / 0x1` -> `can_head`，1000000。
- `1-9:1.0 / 0x0` -> `usb_can`，1000000。

`usb_can` 是后来按本机 USB 口补上的。换主板、换插槽或换 USB 口之后，这些地址会变，必须重新扫描再改配置。

### 这些值怎么得到

在工作区根目录执行。这条命令不需要 root，也不修改 CAN。它列出当前已经出现的物理 CAN，不要求配置里的设备都存在：

```bash
/usr/bin/python3 -I -u can_tools/can_supervisor.py --scan
```

每一项对应一块已经出现的 CAN 控制器。把扫描结果填进 `devices` 时这样对应：

- `identity` 的第一项写入 `bus_addr`。它是 sysfs 设备祖先里的 PCI 地址，例如 `0000:03:00.0`，或 USB 接口地址，例如 `1-9:1.0`。
- `identity` 的第二项写入 `dev_id`。它来自该网卡的 `dev_id` 文件，同一块多口卡上用它区分端口。程序会把十进制或十六进制字符串规范成 `0x` 开头的十六进制。
- 扫描里的 `name` 是内核当前的接口名，例如 `can0`。配置里的 `name` 是希望改成的目标名，例如 `can_chassis`，不是扫描名的原样复制。
- 扫描里的 `bitrate` 是当前波特率；还没配置时可能是 `null`。配置里的 `bitrate` 是准备设置的经典 CAN 波特率，单位是 bit/s。底盘两路沿用绑定脚本的 500000，其余沿用 1000000。
- `ifindex`、`flags`、`state`、`can_fd` 只描述当前状态，不写入配置。

同一块卡上的两个口会有相同的 `bus_addr` 和不同的 `dev_id`。程序不能从地址判断这个口接的是底盘还是手臂。目标名要按接线、原绑定脚本或逐口试通的结果人工指定。

另外两条只读命令：

```bash
/usr/bin/python3 -I -u can_tools/can_supervisor.py --check-config
/usr/bin/python3 -I -u can_tools/can_supervisor.py --dry-run
/bin/bash can_tools/install_can_tools.sh --check
```

`--check-config` 只检查 JSON 字段和取值，不看硬件。`--dry-run` 用 `bus_addr` 加 `dev_id` 核对机器上的接口，并打印要不要初始化；缺设备时返回 3，不执行配置命令。`install_can_tools.sh --check` 只检查源配置能被程序读过，不安装、不改 CAN。

### 参数含义

根上三个字段都必须有，不能多也不能少：

- `devices`：必需接口列表，不能为空。列出的每一路都会被监控。删掉一项就是不再要求这一路，应由管理员确认。
- `poll_interval`：`[READY]` 之后两次只读检查之间的等待秒数。必须是大于 0、不超过 60 的有限数字。当前文件是 `1.0`。
- `command_timeout`：每一条 `ip` 命令的超时秒数，范围与 `poll_interval` 相同。当前文件是 `3.0`。超时或查询失败退出 6。

`devices` 里每一项也正好四个字段：

- `bus_addr`：物理地址。PCI 写成 `0000:03:00.0` 这种四段地址；USB 写成 `1-9:1.0` 这种接口路径。大小写会转成小写再比较。
- `dev_id`：端口号字符串，写成十进制或 `0x` 十六进制。同一 `bus_addr` 下不能重复。
- `name`：激活后的接口名。以字母或下划线开头，后面可含字母、数字、下划线和 `.-`，总长不超过 15。名字不能和另一项重复。
- `bitrate`：经典 CAN 波特率，整数，范围是 1 到 1000000。不能写布尔值，也不能写 CAN FD 的数据段波特率。

只支持经典 CAN。扫描结果里 `can_fd` 为真、控制器状态不在 `ERROR-ACTIVE`、`ERROR-WARNING`、`ERROR-PASSIVE`、`BUS-OFF`、`STOPPED`、`SLEEPING` 之中，或目标名已经被别的接口占用，程序都拒绝初始化。地址通过 sysfs 设备祖先和规范化的 `dev_id` 匹配，不看当前接口名是不是以 `can` 开头。

## 安装与权限

部署前，管理员应先找出并禁用确实会写 CAN 配置的旧开机绑定任务或定时任务，避免两个管理者竞争。
不要禁用现有只读 CAN 诊断节点。先停止 `can_health` 再更新程序或配置；安装时不会替换已经在运行的进程。

由管理员审查源文件后，在其终端执行：

```bash
sudo /bin/bash can_tools/install_can_tools.sh
```

代码安装到 `/opt/can-tools/can_supervisor.py`，配置安装到 `/etc/can-tools/can_bus.json`。
它们必须由 root 所有，文件和所有父目录不可由普通用户写入。安装器拒绝目标符号链接与不安全权限。源配置校验通过后直接替换已有的 `/etc/can-tools/can_bus.json`；原来已有文件时先打印替换提示。
程序没有独立 systemd 服务，安装器不会安装 sudoers、启动进程、修改 HOME 下的配置或触碰 CAN。
源配置有效不等于现场硬件映射正确，仍须运行已安装程序的 `--scan` 和 `--dry-run`。

launch control 仍然以普通用户运行，只允许其中一个固定的 CAN 管理命令以 root 执行，并且不需要输入密码。

不是让所有 Python 程序都获得管理员权限。

### 1. 先确认部署条件

示例要求以下文件已经部署到系统目录：

- 脚本：`/opt/can-tools/can_supervisor.py`
- 配置：`/etc/can-tools/can_bus.json`

这些文件及其父目录必须由 root 管理，普通用户不能修改。否则普通用户可以修改脚本，再借这条 sudo 规则执行任意管理员操作。

当前文件读取工具被钩子错误阻止，尚未核实项目安装脚本的具体步骤；下面说明的是文件部署完成后的 sudoers 配置，不会直接修改你的系统。

### 2. 确认运行用户

在运行 launch control 的账户下执行：

```bash
id -un
```

或者

```bash
whoami
```

如果输出是 `agilex`，下面不用修改；否则将规则中的 `agilex` 替换为实际用户名。

### 3. 由管理员添加规则

执行：

```bash
sudo visudo -f /etc/sudoers.d/can-tools
```

在打开的编辑器里写入这一整行：

```sudoers
agilex ALL=(root) NOPASSWD: /usr/bin/python3 -I -u /opt/can-tools/can_supervisor.py --config /etc/can-tools/can_bus.json
```

保存退出后检查：

```bash
sudo visudo -c -f /etc/sudoers.d/can-tools
```

或者

```bash
sudo visudo -c
```

检查应当显示解析成功；如果出现语法错误，先修正，不要继续。

各部分含义：

- `agilex`：允许执行的用户。
- `ALL`：适用主机。
- `(root)`：该命令以 root 身份执行。
- `NOPASSWD`：执行该命令不需要密码。
- 后面的完整命令：只允许这个路径和这组参数。
- `-I`：Python 隔离模式，减少环境变量和用户包的影响。
- `-u`：及时输出日志，避免缓冲。

### 4. 检查权限是否生效

以 launch control 用户执行：

```bash
sudo -l
```

确认列出了上面的固定命令。也要检查是否存在类似以下宽泛规则：

```sudoers
agilex ALL=(ALL) NOPASSWD: ALL
```

若存在，说明用户原本就有更大的免密权限；新增的固定规则不会收窄它，需要管理员另外审核。

部署和规则确认后，实际调用形式应为：

```bash
sudo -n /usr/bin/python3 -I -u /opt/can-tools/can_supervisor.py --config /etc/can-tools/can_bus.json
```

这里 `-n` 表示不弹出密码提示：权限不符合时直接报错，适合 launch control 调用。该命令可能实际配置 CAN 接口，应在允许调整接口时测试。

### 注意

- 不要用 `sudo` 启动整个 launch control。
- 不要给 `/usr/bin/python3` 设置 capabilities。
- 不要把规则改成允许任意 Python 脚本或带 `*` 的形式。
- launch control 调用的路径、参数和顺序应与规则一致。

实例使用 `/run/lock/can-health.lock` 排他锁，第二个活动实例立即退出 7。
锁只约束本程序，不能阻止旧脚本或其他 root 工具写接口。

## 卸载

先在 launch control 停止 `can_health`，确认 Python 已退出；再手工删除实际 HOME 下 `auto_launch.sh`、`extend_launch.sh` 的对应条目，避免卸载期间重新启动。
在实际 rosboard 机型配置中移除对应 action，并删除为本程序添加的那一行。编辑独立文件用 `sudo visudo -f /etc/sudoers.d/can-tools`，或者编辑主文件用 `sudo visudo`。卸载脚本不会猜测或自动修改这些外部配置。

```bash
/bin/bash can_tools/uninstall_can_tools.sh --dry-run
sudo /bin/bash can_tools/uninstall_can_tools.sh
```

默认只删除 `/opt/can-tools/can_supervisor.py`，配置文件留在 `/etc/can-tools/can_bus.json`。再次安装时，源配置校验通过后会替换这个文件。
确认不再需要配置时，先自行备份，再显式清除：

```bash
sudo /bin/bash can_tools/uninstall_can_tools.sh --purge --dry-run
sudo /bin/bash can_tools/uninstall_can_tools.sh --purge
```

脚本拒绝不安全权限、符号链接和仍被进程占用的实例锁，只删除固定安装文件，仅移除空目录，不递归删除其他文件。
已有 root 私有锁文件可能需要以管理员身份执行 `--dry-run` 才能检查；预览不会删除文件或创建锁。
卸载保留 `/run/lock/can-health.lock`，避免删除锁文件后不同进程锁住不同 inode。
真实卸载在锁不存在时安全创建锁并持有到文件删除完成。卸载不会操作 CAN、停止其他进程、删除诊断节点、日志或工作区源文件；重复卸载允许文件已经不存在。

## 接入 Launch Control

修改实际 launch control 运行用户 HOME 下的 `extend_launch.sh`，不是只修改仓库模板。
以下是一行配置，逗号分隔字段；它不是可执行 shell 脚本命令：

```text
"can_health", `/usr/bin/sudo -n /usr/bin/python3 -I -u /opt/can-tools/can_supervisor.py --config /etc/can-tools/can_bus.json`, true, false, true, false
```

六个字段依次为 ID、命令、保存日志、日志轮转、检查进程状态、强制 SIGKILL。
第五项必须为 `true`；设为 `false` 会导致 launch control 始终发布正常状态。
第六项保持 `false`，以允许 SIGINT/SIGTERM 正常结束。确认现场 sudo 的绝对路径是 `/usr/bin/sudo`。
命令最终被按空格拆为 argv 后直接 `Popen`，不要加入内部 shell 引号、环境变量、管道、重定向或 `&`。
反引号是现有配置格式的外层定界符，不是 shell 命令替换。

需要随 launch control 启动时，在该用户 HOME 下的 `auto_launch.sh` 添加：

```text
"can_health", "start"
```

auto_launch 在管理器启动时处理一次，不会因为子进程失败而持续重启它。
管理器自身重启或修改活动条目的配置可能重新启动子进程，因此也可能重新进行一次初始化。

## 接入 Rosboard

在 rosboard 用户 HOME 下的 `.rosboard.yaml` 确认 `deviceType` 与 `deviceProfilesFile`。
把下面条目合并进该机型的 `actions` 列表；不要覆盖完整配置，也不要让 action ID 重复。

```yaml
- id: can_health_restart
  label:
    zh-CN: CAN 状态 / 重启
    en: CAN Status / Restart
  handler: ros_launch
  confirm: true
  launch_id: can_health
  operation: restart
  ignore_launch_status: false
```

按现有 rosboard 配置加载流程重新加载或重启 rosboard。条目复用已有进程状态指示和重启确认流程。
退出后显示异常；客户修复故障并确认重启后重新执行预检和一次初始化。
前端只接收运行布尔值，具体设备、失败原因和退出码应在 launch control 保存的该子进程 stdout/stderr 日志中查看。

## 启动后的状态

日志出现 `[READY]` 之后，进程保持在前台。每一路必需 CAN 都已经是目标名称、UP、波特率与配置一致，控制器处于 `ERROR-ACTIVE`、`ERROR-WARNING` 或 `ERROR-PASSIVE`。之后只读检查，不再改接口。

启动按下面的顺序处理：

1. 读取配置，确认当前用户是 root，并独占 `/run/lock/can-health.lock`。第二个实例退出 7。
2. 用 `ip -details -json link show` 读取网卡，再沿 sysfs 用物理地址和 `dev_id` 匹配。不依赖当前接口名是不是 `can*`。
3. 有一路对不上就整组停止，退出 3，不执行任何 `ip link set`。已经对上的接口会标明 `identified; not activated`，或 `identified; already available; unchanged`。
4. 全部对上之后，按配置顺序只处理不符合的接口：先 `down`，名字不对再改名，然后设置经典 CAN 波特率，再 `up`。已经符合的接口记为 `already available; unchanged`。每条写命令前都会再核对身份和 `ifindex`。
5. 某一路写到一半失败就停止，退出 4。已经 `up` 成功的记为 `activated`，当前这路记为 `activation incomplete`，后面的记为 `not reached; not activated`。已经改过名时，会尝试改回旧名并保持 down。
6. 全部处理完再读一遍。仍然全部符合后，先打印 JSON 里的 `poll_interval` 和 `command_timeout`，再按配置顺序列出每一路的 `name`、`bus_addr`、`dev_id`、`bitrate`。本来就符合的结果是 `already available; unchanged`，这次写入成功的结果是 `activated`。然后打印 `[READY]`，表示这些 CAN 接口已按预期激活。launch control 只看进程是否还在，`[READY]` 之前页面也可能显示正在运行。

`[READY]` 之后按 `poll_interval` 只读检查，当前配置是 1 秒。某一路缺失、改名、被重建、DOWN、波特率改变，或进入 BUS-OFF、STOPPED、SLEEPING，进程退出 5，不会自动修复。`ERROR-WARNING` 和 `ERROR-PASSIVE` 只在状态变化时告警，进程继续。收到 SIGINT 或 SIGTERM 时退出 0，不会把正常接口 down 掉。

## 状态边界与退出码

- `0`：SIGINT/SIGTERM 正常停止，或只读检查成功。对 launch control 而言，退出 0 仍是已停止。
- `2`：配置读取/校验失败或 CLI 参数错误。
- `3`：初始化前必需硬件缺失、重复、目标名称冲突或不支持的 CAN 状态/模式；未执行初始化写入。失败日志按配置顺序列出每一路：缺失、冲突或不受支持的接口保留原失败说明；已识别但本次没有写入的接口标明 `identified; not activated`；已经符合配置的接口标明 `identified; already available; unchanged`。
- `4`：初始化命令、写入前身份检查或初始化后验证失败；可能已部分修改接口。改名后的命令失败会尝试安全恢复旧名并保持 DOWN，不保证恢复完整配置。失败日志保留原始错误，并逐路标明 `activated`、`activation incomplete`（含旧名是否已恢复）、`already available; unchanged` 或 `not reached; not activated`。
- `5`：初始化成功后的必需接口不可用或 ifindex 改变；不会自动修复。
- `6`：ip 执行超时/查询失败、sysfs 不一致、JSON 异常或其他工具错误。
- `7`：权限不足、锁不安全或已有活动实例。sudo 自身失败时可能返回自己的退出码。

ERROR-WARNING/ERROR-PASSIVE 只在状态变化时告警，不退出、不重置。运行期每次只读轮询检查全部必需接口。
每条 ip 命令有超时。停止信号到来后不再发起新写命令；正在执行的命令可能完成或等到超时。
程序退出不会主动 down 正常接口。
如果初始化中途失败，应人工检查接口残留状态后再启动。
写入前重新验证身份可缩小拔插竞争窗口，但不能原子地阻止另一个管理者同时改接口。

launch control 的状态表示进程存活，不是就绪：`Popen` 成功到初始化完成之间可能短暂显示正常。
真正完成初始化的标志是日志中的 `[READY]`，现有前端没有单独的 readiness 状态。
默认故障检测等待约一个轮询周期，再经过管理器约 1 Hz 状态发布及网络传输；超时故障还受查询超时影响。
轮询间隔内的短暂故障可能漏检，内核或其他程序已有的自动恢复策略也不由本工具控制。
进程卡死、状态消息断流、管理器/浏览器失联不能仅靠这个布尔值可靠检测，现有界面没有完整陈旧状态保证。

## 验证

```bash
/usr/bin/python3 -m unittest discover -s can_tools -p 'test_can_supervisor.py' -v
/bin/bash -n can_tools/install_can_tools.sh
/bin/bash -n can_tools/uninstall_can_tools.sh
```

测试使用模拟观察、临时 sysfs、模拟 ip 命令和当前进程信号，不修改实际网络。
现场验收应在安全停机、禁止运动条件下验证：正常启动、缺一个适配器启动、运行中掉线、接口 DOWN/BUS-OFF、错误波特率、人工修复重启，以及页面状态和日志。
只有明确支持热插拔的适配器才可在运行中拔插；不得热拔不支持热插拔的 PCIe 卡。重新激活前还须确认控制端断线保护、旧指令超时与重新授权机制，避免恢复连接后执行旧指令。
还须确认 launch control 经 sudo 的信号能到达 Python 并退出、停止时接口不被 down、旧写入任务不再竞争。
这些真实硬件与部署集成验证不能由离线测试替代。
