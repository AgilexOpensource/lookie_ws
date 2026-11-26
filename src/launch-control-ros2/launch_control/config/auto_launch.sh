### Commands sent to /launch_control when the node starts. Applied once.
### Retry fields apply only to start and restart.

# Field 1: process id or built-in id                         (required)
# Field 2: operation: start | stop | restart                 (required)
# Field 3: watch process state before retry                  (optional, default true)
# Field 4: retry count, -1 infinite, 0 none                  (optional, default 0)
# Field 5: seconds between retries                           (required when count is not 0)
# -------------------------------------------------------------------------------
### 在launch_control启动时调用/launch_control服务的配置文件。	--- 生效一次
### 需要将改该文件放在$HOME目录下
### 重试字段只对 start 和 restart 生效。是否检测运行状态与 extend_launch.sh 的参数 5 不是同一个开关。

# 参数 1: 操作id或扩展子进程id		(必填)
# 参数 2: 需要执行的操作类型		(必填)
# 参数 3: 重试前是否检测运行状态		(可不填，默认 true)
# 参数 4: 重试次数，-1 无限，0 不重试	(可不填，默认 0)
# 参数 5: 每次重试间隔秒数		(次数不是 0 时必填)
# -------------------------------------------------------------------------------
# Examples:
# "demo_talker", "start", true, 3, 5
# "demo_listener", "start", false, -1, 10
# "demo_once", "start"
# "close_all", "start"
