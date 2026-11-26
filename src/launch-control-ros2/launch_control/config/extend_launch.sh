### Register launch_control subprocesses. Changes take effect immediately.

## Auto-start entries can be listed in ~/auto_launch.sh.

# Field 1: process id                          (required)
# Field 2: command to run                      (required)
# Field 3: save stdout/stderr logs             (optional, default true)
# Field 4: rotate logs on each restart         (optional, default false)
# Field 5: check process status                (optional, default true)
# Field 6: seconds to wait before SIGKILL    (optional, default 90; 0 kills immediately)
# -------------------------------------------------------------------------------
### 注册launch_control的扩展子进程参数配置文件。	--- 实时生效
### 需要将改该文件放在$HOME目录下

## 可以在~/auto_launch.sh中配置程序自动启动需要的扩展子进程。

# 参数 1: 注册的扩展子进程id		(必填)
# 参数 2: 扩展子进程运行的命令		(必填)
# 参数 3: 是否保存扩展子进程输出日志	(可不填，默认 true)
# 参数 4: 日志是否叠加存储		(可不填，默认 false, 参数3为 'false' 时本参数值为false)
# 参数 5: 是否检查进程运行状态		(可不填，默认 true；false 时发布状态恒为 true)
# 参数 6: 停止时等待退出的秒数		(可不填或留空，默认 90；0 表示直接强杀)
# -------------------------------------------------------------------------------
# Examples:
# "demo_talker", `ros2 run demo_nodes_cpp talker`
# "demo_listener", `ros2 run demo_nodes_py listener`, true, false

# "open_piper", `/bin/bash /absolute/path/start_piper.sh`, true, false, true, 0
