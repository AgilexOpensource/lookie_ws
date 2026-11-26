#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
VERSION = "ros2-20260920-1"

import copy
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time

import psutil
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from launch_control_msgs.msg import LaunchStatus
from launch_control_msgs.srv import LaunchNode
from launch_control_msgs.srv import SetEmpty

LAUNCH_LOG_NAME = "launch.log"
ROBOT_CONFIG_NAME = "robot_config.bash"
EXTEND_LAUNCH_CONFIG_NAME = "extend_launch.sh"
AUTO_LAUNCH_CONFIG_NAME = "auto_launch.sh"
LOG_DIR = ""
PROCESS_LOG_DIR = ""
DEFAULT_SHUTDOWN_TIMEOUT = 90
ROBOT_CONFIG_COMMAND_TIMEOUT = 10

# These must be established before Python/ROS initialization, not hot-reloaded.
STARTUP_ENV_KEYS = frozenset({
    "user", "USER", "home", "HOME", "LOGNAME", "PATH", "PYTHONPATH",
    "LD_LIBRARY_PATH", "AMENT_PREFIX_PATH", "CMAKE_PREFIX_PATH",
    "COLCON_PREFIX_PATH", "LAUNCH_CONTROL_WS", "LAUNCH_CONTROL_SETUP",
    "ROS_DOMAIN_ID", "ROS_LOCALHOST_ONLY", "RMW_IMPLEMENTATION",
    "ROS_DISCOVERY_SERVER", "ROS_AUTOMATIC_DISCOVERY_RANGE", "ROS_STATIC_PEERS",
    "CYCLONEDDS_URI", "FASTRTPS_DEFAULT_PROFILES_FILE", "FASTDDS_DEFAULT_PROFILES_FILE",
})

OP_TYPE = {
    "START": "start",
    "STOP": "stop",
    "RESTART": "restart",
}

LAUNCH_STATUS = {
    "KILL": -15,
    "EXIT": 0,
    "SLEEP": 1,
    "NOT_EXIST": 2,
    "RUN": None,
}


def bool2int2string(data):
    return str(int(data))


def bool2string(data):
    return "true" if data else "false"


def string2bool(data):
    return data in ("true", "True")


def rename_file(file_from, file_to):
    if not os.path.exists(file_from):
        return
    stat = os.stat(file_from)
    os.rename(file_from, file_to)
    os.utime(file_to, (stat.st_atime, stat.st_mtime))


def write_log(path, message):
    try:
        with open(path, "a") as fo:
            fo.write(f"{message}\n")
    except IOError:
        pass


def write_launch_log(message):
    write_log(os.path.join(LOG_DIR, LAUNCH_LOG_NAME), message)
    write_log(os.path.join(PROCESS_LOG_DIR, LAUNCH_LOG_NAME), message)


def write_launch_log_and_print(message):
    write_launch_log(message)
    print(message)

# def process_launch_result(success=True, message=""):
#     write_launch_log_and_print(f"[{success}] {message}\n")
#     return LaunchNode.Response(success=success, message=message)

def get_format_date_now(fmt="[%Y-%m-%d %H:%M:%S] "):
    return time.strftime(fmt, time.localtime())

# def get_environment_value(name="", default=None):
#     if name in os.environ:
#         return os.environ[name]
#     else:
#         return default

def run_shell_command(cmd="", enable_error_output=True):
    if not enable_error_output:
        cmd += " 2> /dev/null"
    return os.popen(cmd).read()

# def run_shell_command_in_child_process(cmd):
#     return subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()

def get_file_size(path):
    if os.path.exists(path):
        # Previous shell-based size lookup:
        return int(run_shell_command("du -sb " + path).split()[0])
        # return int(subprocess.check_output(["du", "-sb", "--", path], text=True).split()[0])
    print("cannot get '%s' size: No such file or directory" % path)
    return 0


def remove_multiple_chars(data="", chars_to_remove=""):
    for char in chars_to_remove:
        data = data.replace(char, "")
    return data


def delete_excess_space(data=""):
    return re.sub(r"\s+", " ", remove_multiple_chars(data, '"[]`').strip())


def fill_space(data="", num=79, delete_space=True):
    if len(data) > num or delete_space:
        data = data.replace(" ", "")
    if len(data) < num:
        return data + " " * (num - len(data))
    return data


def fill_title(title="", num=79, char="="):
    if len(title) > num:
        return title
    fill_len_total = num - len(title)
    fill_len_left = int(fill_len_total / 2)
    fill_len_right = fill_len_total - fill_len_left
    return fill_space(char * fill_len_left + title + char * fill_len_right, num, False) + "\n"


def create_dir(directory=""):
    if directory in ("", "/"):
        exit(-1)
    if not os.path.exists(directory) or not os.path.isdir(directory):
        try:
            if os.path.exists(directory):
                os.remove(directory)
            os.makedirs(directory)
        except IOError:
            print("cannot create directory: " + directory)
            exit(-2)


def is_new_command(cmd1_list=[""], cmd2_list=[""]):
    if len(cmd2_list) == 0:
        return False
    if len(cmd1_list) != len(cmd2_list):
        return True
    return cmd1_list != cmd2_list


class Rate:
    def __init__(self, rate):
        self.sleep_time = 1.0 / rate
        self.start_time = time.time()

    def sleep(self):
        if self.start_time + self.sleep_time > time.time():
            time.sleep(self.start_time + self.sleep_time - time.time())
            self.start_time += self.sleep_time
        else:
            self.start_time = time.time()


class ConfigInfo:
    def __init__(self):
        self.config_exist = True
        self.last_config_time = 0


_ROBOT_CONFIG_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def set_robot_config_value(holder, key, value, description, first_log):
    if key in holder.robot_config_dict and value != holder.robot_config_dict[key]:
        if first_log:
            first_log = False
            write_launch_log_and_print(get_format_date_now())
        write_launch_log_and_print(
            " ~ $%s: '%s' --> '%s'" % (
                key,
                holder.robot_config_dict[key],
                value,
            )
        )
    holder.robot_config_dict[key] = value
    holder.robot_config_description_dict[key] = description
    os.environ[key] = value
    return first_log


def parse_robot_config_command_assignment(text):
    # 值里含有 $ 时展开命令替换和变量引用。其它行继续用原来的按空格切分。
    match = _ROBOT_CONFIG_ASSIGNMENT.match(text.strip())
    if match is None or "$" not in match.group(2):
        return None
    return match.group(1), match.group(2)


def _matching_command_substitution(text, start):
    index = start + 2
    depth = 1
    quote = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 2:index], index + 1
        index += 1
    return None


def _stop_robot_config_process(process):
    try:
        process.kill()
    except (PermissionError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def _run_robot_config_command(script, env, timeout):
    process = subprocess.Popen(
        ["sh", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_robot_config_process(process)
        return None, f"command substitution timed out after {timeout:g}s"
    if process.returncode != 0:
        detail = (stderr or "").strip() or f"exit {process.returncode}"
        return None, f"command substitution failed: {detail}"
    return (stdout or "").rstrip("\n"), None


def _lookup_robot_config_name(name, env):
    if name not in env:
        return None, f"unset variable {name}"
    return env[name], None


def _read_robot_config_reference(value, index, env):
    if value.startswith("$$", index):
        return "$$", index + 2, None
    if value.startswith("${", index):
        closing = value.find("}", index + 2)
        if closing < 0:
            return None, index, "unclosed variable reference"
        name = value[index + 2:closing]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            return None, index, "unclosed variable reference"
        output, error = _lookup_robot_config_name(name, env)
        return output, closing + 1, error
    match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[index + 1:])
    if match is None:
        return "$", index + 1, None
    output, error = _lookup_robot_config_name(match.group(0), env)
    return output, index + 1 + len(match.group(0)), error


def expand_robot_config_substitutions(value, env=None, timeout=ROBOT_CONFIG_COMMAND_TIMEOUT):
    # 整段单引号按字面量保存，不执行其中的 $()。
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'" and "'" not in value[1:-1]:
        return value[1:-1], None
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"' and value.count('"') % 2 == 0:
        value = value[1:-1]
    command_env = os.environ if env is None else env
    parts = []
    index = 0
    single_quoted = False
    while index < len(value):
        if single_quoted:
            if value[index] == "'":
                single_quoted = False
            else:
                parts.append(value[index])
            index += 1
            continue
        if value[index] == "'":
            single_quoted = True
            index += 1
            continue
        if value[index] == '"':
            index += 1
            continue
        if value.startswith("$(", index):
            found = _matching_command_substitution(value, index)
            if found is None:
                return None, "unclosed command substitution"
            output, error = _run_robot_config_command(found[0], command_env, timeout)
            if error is not None:
                return None, error
            parts.append(output)
            index = found[1]
            continue
        if value[index] == "$":
            output, index, error = _read_robot_config_reference(value, index, command_env)
            if error is not None:
                return None, error
            parts.append(output)
            continue
        parts.append(value[index])
        index += 1
    if single_quoted:
        return None, "unclosed single quote"
    return "".join(parts), None


def parse_shutdown_timeout(value):
    timeout = float(value)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("shutdown timeout must be a non-negative finite number")
    return timeout


_AUTO_RETRY_BOOLS = {"true": True, "True": True, "false": False, "False": False}
_AUTO_RETRY_OPS = frozenset(("start", "restart"))


def parse_auto_launch_retry(fields):
    # 返回 (check_running, retry_limit, interval, error)。非法时次数按 0 处理。
    check_running = True
    if len(fields) > 2 and fields[2] != "":
        if fields[2] not in _AUTO_RETRY_BOOLS:
            return True, 0, None, f"invalid auto retry check '{fields[2]}'"
        check_running = _AUTO_RETRY_BOOLS[fields[2]]
    retry_limit = 0
    if len(fields) > 3 and fields[3] != "":
        if re.fullmatch(r"-?\d+", fields[3]) is None:
            return check_running, 0, None, f"invalid auto retry count '{fields[3]}'"
        retry_limit = int(fields[3])
        if retry_limit < -1:
            return check_running, 0, None, f"invalid auto retry count '{fields[3]}'"
    if retry_limit == 0:
        return check_running, 0, None, None
    if len(fields) < 5 or fields[4] == "":
        return check_running, 0, None, "auto retry interval is required"
    try:
        interval = float(fields[4])
    except ValueError:
        return check_running, 0, None, f"invalid auto retry interval '{fields[4]}'"
    if not math.isfinite(interval) or interval <= 0:
        return check_running, 0, None, f"invalid auto retry interval '{fields[4]}'"
    return check_running, retry_limit, interval, None


def parse_auto_launch_line(fields, close_all_id="close_all"):
    launch_id = fields[0]
    op_type = fields[1]
    parsed = {"launch_id": launch_id, "op": op_type, "retry": None, "message": None}
    if op_type not in _AUTO_RETRY_OPS or launch_id == close_all_id:
        if len(fields) > 2:
            parsed["message"] = f"ignore auto retry fields for '{launch_id}' {op_type}"
        return parsed
    check_running, retry_limit, interval, error = parse_auto_launch_retry(fields)
    if error:
        parsed["message"] = f"invalid auto retry for '{launch_id}': {error}"
        return parsed
    if retry_limit != 0:
        parsed["retry"] = (check_running, retry_limit, interval)
    return parsed


class AutoRetryPolicy:
    def __init__(self, launch_id, check_running, retry_limit, interval, started_at):
        self.launch_id = launch_id
        self.check_running = check_running
        self.retry_limit = retry_limit
        self.interval = interval
        self.used = 0
        self.armed = True
        # 检测模式下等进程停下再计时；不检测时从首次操作后开始按间隔重试。
        self.next_at = None if check_running else started_at + interval


def advance_auto_retry(policy, process, now):
    if not policy.armed:
        return
    if policy.check_running:
        if process.is_run():
            policy.next_at = None
            return
        if policy.next_at is None:
            policy.next_at = now + policy.interval
            return
        if now < policy.next_at:
            return
        policy.next_at = None
        _perform_auto_retry(policy, process, restart_running=False)
        return
    if now < policy.next_at:
        return
    _perform_auto_retry(policy, process, restart_running=True)
    if policy.armed:
        policy.next_at = now + policy.interval


def _perform_auto_retry(policy, process, restart_running):
    policy.used += 1
    write_launch_log_and_print(
        f"[retry] [{policy.launch_id}] {policy.used}/{policy.retry_limit}"
    )
    if restart_running and process.is_run():
        process.stop()
    process.launch()
    if policy.retry_limit >= 0 and policy.used >= policy.retry_limit:
        policy.armed = False
        write_launch_log_and_print(
            f"[retry] [{policy.launch_id}] reached {policy.used}/{policy.retry_limit}"
        )


class LaunchProcess:
    def __init__(self, log_name="default", cmd_raw=None,
                 enable_output=True, multi_log_mode=False, check_status=True,
                 shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT, re_init=False):
        self.cmd_raw = self.cmd = cmd_raw
        self.args = None
        self.log_name = log_name
        self.stdout_log_path = self.errout_log_path = None
        self.stdoutput_fp = self.erroutput_fp = None
        self.exist = False
        self.load = False
        self.file_name = ""
        self.run = False
        self.enable_output = enable_output
        self.multi_log_mode = enable_output and multi_log_mode
        self.check_status = check_status
        self.shutdown_timeout = parse_shutdown_timeout(shutdown_timeout)
        if not re_init:
            self.log_num = 0

    def __del__(self):
        if self.is_run() or self.run:
            try:
                self.shutdown()
                write_launch_log_and_print(" - close " + self.log_name)
            except Exception as e:
                print(e)

    def update_full_cmd(self):
        self.cmd = self.cmd_raw + self.args

    def set_cmd_raw(self, cmd):
        self.cmd_raw = cmd
        self.update_full_cmd()

    def get_cmd_raw(self):
        return self.cmd_raw

    def set_enable_output(self, data):
        self.enable_output = data

    def get_enable_output(self):
        return self.enable_output

    def set_multi_log_mode(self, data):
        self.multi_log_mode = data

    def get_multi_log_mode(self):
        return self.multi_log_mode

    def set_check_status(self, data):
        self.check_status = data

    def get_check_status(self):
        return self.check_status

    def get_shutdown_timeout(self):
        return self.shutdown_timeout

    def set_args(self, args):
        self.args = args
        self.update_full_cmd()

    def add_args(self, args):
        self.args += args
        self.update_full_cmd()

    def change_launch_config(self, log_name="default", cmd_raw=None,
                             enable_output=True, multi_log_mode=False, check_status=True,
                             shutdown_timeout=DEFAULT_SHUTDOWN_TIMEOUT):
        self.__init__(log_name, cmd_raw, enable_output, multi_log_mode,
                      check_status, shutdown_timeout, re_init=True)

    def get_launch_config(self):
        return (
            self.log_name + ", "
            + str(self.get_cmd_raw()) + ", "
            + bool2string(self.get_enable_output()) + ", "
            + bool2string(self.get_multi_log_mode()) + ", "
            + bool2string(self.get_check_status()) + ", "
            + format(self.get_shutdown_timeout(), "g")
        )

    def set_file_name(self, arg):
        self.file_name = arg

    def get_file_name(self):
        return self.file_name

    def get_stdout(self):
        if self.exist:
            with open(self.stdout_log_path, "r") as fp:
                return fp.read()
        return self.log_name + " doesn't exist."

    def get_errout(self):
        if self.exist:
            if self.enable_output:
                with open(self.errout_log_path, "r") as fp:
                    return fp.read()
            return self.log_name + "is null"
        return self.log_name + " doesn't exist."

    def launch(self):
        if self.is_not_run() and not self.load:
            self.load = True
            try:
                if self.enable_output:
                    self.stdout_log_path = PROCESS_LOG_DIR + "/" + self.log_name + "-stdout.log"
                    self.errout_log_path = PROCESS_LOG_DIR + "/" + self.log_name + "-stderr.log"
                if self.multi_log_mode:
                    if self.log_num > 0:
                        rename_file(self.stdout_log_path, self.stdout_log_path + "." + str(self.log_num))
                        rename_file(self.errout_log_path, self.errout_log_path + "." + str(self.log_num))
                    self.log_num += 1
                if self.stdout_log_path is not None:
                    self.stdoutput_fp = open(self.stdout_log_path, "w+")
                if self.errout_log_path is not None:
                    self.erroutput_fp = open(self.errout_log_path, "w+")
                self.child = subprocess.Popen(
                    self.cmd,
                    stdin=None,
                    stdout=self.stdoutput_fp,
                    stderr=self.erroutput_fp,
                    universal_newlines=True,
                    start_new_session=True,
                )
            except (OSError, ValueError) as exc:
                self.reset()
                write_launch_log_and_print(f"start '{self.log_name}' failed: {exc}")
                return False
            self.exist = True
            self.run = True
            self.load = False
            return True
        return False

    def status(self):
        if self.exist:
            return self.child.poll()
        return LAUNCH_STATUS["NOT_EXIST"]

    def is_run(self):
        return self.status() == LAUNCH_STATUS["RUN"]

    def is_not_run(self):
        return self.status() != LAUNCH_STATUS["RUN"]

    def error(self):
        return self.is_not_run() and self.run

    def reset(self):
        self.load = False
        self.run = False
        if self.stdoutput_fp is not None:
            self.stdoutput_fp.close()
        if self.erroutput_fp is not None:
            self.erroutput_fp.close()

    def shutdown(self):
        # 默认通过 SIGTERM 关闭程序并等待退出，等待超时则强杀。
        # 最长等待时间为 0 时，直接进行强杀。
        kill_timeout = self.shutdown_timeout or DEFAULT_SHUTDOWN_TIMEOUT
        try:
            parent_process = psutil.Process(self.child.pid)
            processes = parent_process.children(recursive=True) + [parent_process]
        except psutil.NoSuchProcess:
            self.child.wait(timeout=kill_timeout)
            self.reset()
            return True

        def get_alive():
            self.child.poll()
            # 仅在本次关闭期间补充同一会话的进程，覆盖关闭时新建的子进程。
            for process in psutil.process_iter():
                try:
                    if os.getsid(process.pid) == self.child.pid and process not in processes:
                        processes.append(process)
                except (psutil.NoSuchProcess, ProcessLookupError):
                    pass
            alive = []
            for process in processes:
                try:
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        alive.append(process)
                except psutil.NoSuchProcess:
                    pass
            return alive

        # 配置时间分别用于两个信号阶段，各阶段独立计时。
        stages = [(signal.SIGTERM, self.shutdown_timeout), (signal.SIGKILL, kill_timeout)]

        for sig, timeout in stages:
            alive = get_alive()
            if not alive:
                break
            # 独立进程组统一收信号，另行通知创建了其他进程组的子进程。
            try:
                os.killpg(self.child.pid, sig)
            except ProcessLookupError:
                pass
            for process in reversed(alive):
                try:
                    if os.getpgid(process.pid) != self.child.pid:
                        process.send_signal(sig)
                except (psutil.NoSuchProcess, ProcessLookupError):
                    pass
            deadline = time.monotonic() + timeout
            while get_alive() and time.monotonic() < deadline:
                time.sleep(0.1)

        alive = get_alive()
        if alive:
            raise RuntimeError(
                f"{self.log_name} shutdown failed, remaining pids: {[process.pid for process in alive]}"
            )
        self.child.wait(timeout=kill_timeout)
        self.reset()
        return True

    def start(self):
        if self.is_not_run():
            self.launch()

    def stop(self):
        if self.is_run():
            self.shutdown()


class LaunchControlRosNode(Node):
    def __del__(self):
        del self.extend_launch_dict

    def __init__(self):
        super().__init__("launch_control_node")
        self.user = self.home = ""
        self.robot_config_info = ConfigInfo()
        self.extend_launch_config_info = ConfigInfo()
        self.default_id_type = {"CLOSE_ALL": "close_all"}
        self.extend_id_type = {}
        self.extend_launch_dict = {}
        self.info_dict = {}
        self.robot_config_dict = {}
        self.robot_config_description_dict = {}
        self.id_type = copy.deepcopy(self.default_id_type)
        self.id_type.update(self.extend_id_type)
        self.robot_config_key_list = list(self.robot_config_dict.keys())
        self.launch_lock = threading.RLock()
        self.auto_retry_policies = {}

        self.init_home_env()
        self.init_log()
        self.init_ros()
        self.load_config()
        self.thread = threading.Thread(target=self.process)
        self.thread.start()

    def init_ros(self):
        self.launch_status_pub = self.create_publisher(LaunchStatus, "/launch_status", 10)
        self.launch_diagnostic_pub = self.create_publisher(DiagnosticArray, "/launch_diagnostic", 10)
        self.launch_node_srv = self.create_service(LaunchNode, "/launch_control", self.handle_launch)
        self.get_extend_launch_info_srv = self.create_service(
            SetEmpty, "/get_extend_launch_info", self.handle_get_extend_launch_info
        )
        self.get_extend_launch_run_id_srv = self.create_service(
            SetEmpty, "/get_extend_launch_run_id", self.handle_get_extend_launch_run_id
        )
        self.get_all_info_srv = self.create_service(
            SetEmpty, "/get_all_info", self.handle_get_all_info
        )

    def init_home_env(self):
        if "user" in os.environ:
            self.user = os.environ["user"]
        elif "USER" in os.environ and os.environ["USER"] != "root":
            self.user = os.environ["USER"]
        else:
            self.user = "agilex"
        os.environ["user"] = os.environ["USER"] = self.user

        if "home" in os.environ:
            self.home = os.environ["home"]
        elif "HOME" in os.environ and os.environ["HOME"] != "/root":
            self.home = os.environ["HOME"]
        else:
            self.home = "/home/agilex"
        # Preserve legacy precedence/fallbacks, but reject unusable directories.
        if not self.home or not os.path.isabs(self.home) or not os.path.isdir(self.home):
            raise ValueError("home/HOME must select an existing absolute directory: " + repr(self.home))
        os.environ["home"] = os.environ["HOME"] = self.home

    def init_log(self):
        start_time = time.localtime()
        start_time_sec = int(time.mktime(start_time))

        global LOG_DIR, PROCESS_LOG_DIR
        LOG_DIR = os.path.join(self.home, ".agilex/log")
        # Previous ownership override (kept for comparison):
        # run_shell_command(f"chown -R 1000:1000 {LOG_DIR}", False)
        # Logs belong to the runtime account; migrate old logs at deployment.
        process_log_dir_name = time.strftime("%Y-%m-%d_%H-%M-%S", start_time)
        PROCESS_LOG_DIR = os.path.join(LOG_DIR, process_log_dir_name)
        print(f"log_dir: {PROCESS_LOG_DIR}")
        create_dir(LOG_DIR)
        create_dir(PROCESS_LOG_DIR)
        latest_path = os.path.join(LOG_DIR, "latest")
        if os.path.islink(latest_path):
            os.remove(latest_path)
        # Previous shell-based link creation:
        # 如果创建符号链接有问题，使用该行代码替换下面的os.symlink()，但是需要注意，ln命令在不同的系统上可能有不同的行为。
        # run_shell_command("ln -s '" + PROCESS_LOG_DIR + "' " + latest_path)
        os.symlink(PROCESS_LOG_DIR, latest_path)
        launch_log_path = LOG_DIR + "/" + LAUNCH_LOG_NAME
        if os.path.exists(launch_log_path):
            if get_file_size(launch_log_path) > 100 * 1024 * 1024:
                os.remove(launch_log_path)
                print("remove %s" % launch_log_path)
        files = os.listdir(LOG_DIR)
        launch_log_message = time.strftime("\n[%Y-%m-%d %H:%M:%S] ", start_time) + "-------- start --------\n" + \
                             " * version: [" + VERSION + "]\n"
        launch_log_message_len = len(launch_log_message)
        time_level = 31 * 24 * 60 * 60
        size_level = 100 * 1024 * 1024
        for file in files:
            file_path = LOG_DIR + "/" + file
            if file_path == launch_log_path:
                continue
            file_time_sec = int(os.stat(file_path).st_mtime)
            if os.path.isfile(file_path):
                if start_time_sec - file_time_sec > time_level:
                    message = "[too old] remove " + file_path
                    launch_log_message += "\n" + message
                    os.remove(file_path)
                elif get_file_size(file_path) > size_level:
                    message = "[too large] remove " + file_path
                    launch_log_message += "\n" + message
                    os.remove(file_path)
            else:
                if start_time_sec - file_time_sec > time_level:
                    shutil.rmtree(file_path, True)
                    message = "[too old] remove directory: " + file_path
                    launch_log_message += "\n" + message
        if launch_log_message_len != len(launch_log_message):
            launch_log_message += "\n"
        write_launch_log_and_print(launch_log_message)

    def load_config(self):
        self.load_robot_config()
        print(self.robot_config_dict, "\n")
        self.load_extend_launch_config()
        self.load_auto_launch_config()

    def load_robot_config(self):
        file_name = os.path.join(self.home, ROBOT_CONFIG_NAME)
        if not os.path.exists(file_name):
            if self.robot_config_info.config_exist:
                print("can't find " + file_name)
                self.robot_config_info.config_exist = False
            return
        if not self.robot_config_info.config_exist:
            print("find " + file_name)
            self.robot_config_info.config_exist = True
        if self.robot_config_info.last_config_time == os.stat(file_name).st_mtime:
            return
        print("*** load robot config ***")
        self.robot_config_info.last_config_time = os.stat(file_name).st_mtime

        try:
            with open(file_name, "r") as fo:
                data = fo.read()
        except IOError:
            print("open robot config fail")
            return
        data_list = data.split("\n")
        first_log = True
        for i in range(0, len(data_list)):
            if len(data_list[i]) > 0 and data_list[i][0] != "#":
                des_list = data_list[i].split(" #")
                if len(des_list) == 2:
                    robot_config_description = " #" + des_list[1]
                else:
                    robot_config_description = ""
                # 修复了一个bug：如果配置文件中有一行只有空格/多个空格/空格加注释#，
                # 那么des_list[0]会是空字符串，rstrip(" ")之后还是空字符串，
                # 这样就会导致后续的line_list[0]和line_list[1]访问越界。
                # 现在加了一个判断，如果des_list[0]是空字符串，就直接continue跳过这一行。
                des_list[0] = des_list[0].rstrip(" ")
                if not des_list[0]:
                    continue
                command_assignment = parse_robot_config_command_assignment(des_list[0])
                if command_assignment is not None:
                    key, raw_value = command_assignment
                    if key in STARTUP_ENV_KEYS:
                        write_launch_log_and_print(
                            "Ignoring startup-only variable " + key
                            + " in robot_config.bash; configure it before startup and restart the manager."
                        )
                        continue
                    value, error = expand_robot_config_substitutions(raw_value)
                    if error is not None:
                        write_launch_log_and_print(
                            f"invalid robot config value for '{key}': {error}"
                        )
                        continue
                    first_log = set_robot_config_value(
                        self, key, value, robot_config_description, first_log
                    )
                    continue
                line = des_list[0][des_list[0].rfind(" ") + 1:]
                line_list = line.split("=")
                if len(line_list) == 2:
                    line_list[1] = line_list[1].replace('"', "")
                    if line_list[0] in STARTUP_ENV_KEYS:
                        write_launch_log_and_print(
                            "Ignoring startup-only variable " + line_list[0]
                            + " in robot_config.bash; configure it before startup and restart the manager."
                        )
                        continue
                    first_log = set_robot_config_value(
                        self, line_list[0], line_list[1], robot_config_description, first_log
                    )
        write_launch_log_and_print("")

    def load_extend_launch_config(self):
        file_name = os.path.join(self.home, EXTEND_LAUNCH_CONFIG_NAME)
        if not os.path.exists(file_name):
            if self.extend_launch_config_info.config_exist:
                print("can't find " + file_name)
                self.extend_launch_config_info.config_exist = False
            return
        if not self.extend_launch_config_info.config_exist:
            print("find " + file_name)
            self.extend_launch_config_info.config_exist = True
        if self.extend_launch_config_info.last_config_time == os.stat(file_name).st_mtime:
            return
        print("*** load extend launch config ***\n")
        self.extend_launch_config_info.last_config_time = os.stat(file_name).st_mtime
        try:
            with open(file_name, "r") as fo:
                data = fo.read()
        except IOError:
            print("open extend launch config fail")
            return
        data_list = data.split("\n")
        for i in range(len(data_list)):
            line = data_list[i]
            pos = line.find("#")
            if pos >= 0:
                line = line[0: pos]
            line_list = line.split(",")
            if len(line_list) < 2:
                continue
            # analyze extend launch info
            for j in range(len(line_list)):
                line_list[j] = delete_excess_space(line_list[j])
            launch_id = line_list[0]
            cmd_list = str(line_list[1]).split(" ")
            enable_output = True
            if len(line_list) > 2:
                enable_output = string2bool(line_list[2])
            multi_log_mode = False
            if len(line_list) > 3:
                multi_log_mode = enable_output and string2bool(line_list[3])
            check_status = string2bool(line_list[4]) if len(line_list) > 4 else True
            try:
                if len(line_list) > 5 and line_list[5]:
                    shutdown_timeout = parse_shutdown_timeout(line_list[5])
                else:
                    shutdown_timeout = DEFAULT_SHUTDOWN_TIMEOUT
            except ValueError as error:
                write_launch_log_and_print(f"invalid shutdown timeout for '{launch_id}': {error}")
                continue

            if self.add_extend_id(launch_id):
                if launch_id not in self.extend_launch_dict:
                    self.extend_launch_dict[launch_id] = LaunchProcess(
                        launch_id, cmd_list, enable_output, multi_log_mode, check_status, shutdown_timeout
                    )
                else:
                    flag1 = is_new_command(self.extend_launch_dict[launch_id].get_cmd_raw(), cmd_list)
                    flag2 = self.extend_launch_dict[launch_id].get_enable_output() != enable_output
                    flag3 = self.extend_launch_dict[launch_id].get_multi_log_mode() != multi_log_mode
                    flag4 = self.extend_launch_dict[launch_id].get_check_status() != check_status
                    flag5 = self.extend_launch_dict[launch_id].get_shutdown_timeout() != shutdown_timeout
                    if flag1 or flag2 or flag3 or flag4 or flag5:
                        msg = (
                            "change from: " + self.extend_launch_dict[launch_id].get_launch_config() + "\n"
                            + bool2int2string(flag1) + bool2int2string(flag2)
                            + bool2int2string(flag3) + bool2int2string(flag4) + bool2int2string(flag5)
                        )
                        run_flag = self.extend_launch_dict[launch_id].is_run()
                        if run_flag:
                            self.extend_launch_dict[launch_id].shutdown()
                        self.extend_launch_dict[launch_id].change_launch_config(
                            launch_id, cmd_list, enable_output, multi_log_mode, check_status, shutdown_timeout
                        )
                        msg += "      to: " + self.extend_launch_dict[launch_id].get_launch_config()
                        if run_flag:
                            self.extend_launch_dict[launch_id].launch()
                            write_launch_log_and_print(
                                get_format_date_now() + "[~] restart " + launch_id + " \n"
                            )

    def load_auto_launch_config(self):
        file_name = os.path.join(self.home, AUTO_LAUNCH_CONFIG_NAME)
        print("*** load auto launch config ***\n")
        try:
            with open(file_name, "r") as fo:
                data = fo.read()
        except IOError:
            print("open auto launch config fail")
            return
        data_list = data.split("\n")
        for i in range(len(data_list)):
            line = data_list[i]
            pos = line.find("#")
            if pos >= 0:
                line = line[0: pos]
            line_list = line.split(",")
            if len(line_list) < 2:
                continue
            # analyze auto launch info
            for j in range(len(line_list)):
                line_list[j] = delete_excess_space(line_list[j])
            id_type = line_list[0]
            op_type = line_list[1]
            if op_type == "":
                continue
            parsed = parse_auto_launch_line(line_list, self.id_type["CLOSE_ALL"])
            if parsed["message"]:
                write_launch_log_and_print(parsed["message"])
            self.send_launch_command(parsed["launch_id"], parsed["op"])
            if parsed["retry"] is None:
                self.auto_retry_policies.pop(parsed["launch_id"], None)
                continue
            check_running, retry_limit, interval = parsed["retry"]
            self.auto_retry_policies[parsed["launch_id"]] = AutoRetryPolicy(
                parsed["launch_id"], check_running, retry_limit, interval, time.monotonic()
            )

    def add_extend_id(self, id_type=""):
        if len(id_type) == 0:
            return False
        if id_type not in self.extend_id_type:
            self.extend_id_type[id_type.upper()] = id_type.lower()
            self.id_type.update(self.extend_id_type)
        return True

    def get_extend_launch_info_message(self, res_dw=None):
        res_dw = res_dw if res_dw is not None else {"success": True, "message": ""}
        title = " extend launch info "
        res_dw["message"] += fill_title(title, 77)
        for key in self.extend_launch_dict:
            res_dw["message"] += "* " + fill_space(
                str(self.extend_launch_dict[key].get_launch_config()), 75, False
            ) + "\n"

    def get_extend_launch_run_id_message(self, res_dw=None):
        res_dw = res_dw if res_dw is not None else {"success": True, "message": ""}
        title = " extend launch run id "
        res_dw["message"] += fill_title(title, 77)
        for key in self.extend_launch_dict:
            if self.extend_launch_dict[key].is_run():
                res_dw["success"] = True
                res_dw["message"] += "* '" + fill_space(key + "'", 74, False) + "\n"

    def handle_get_extend_launch_info(self, req, res: SetEmpty.Response):
        res_dw = {"success": True, "message": " " * 79 + "\n"}
        self.get_extend_launch_info_message(res_dw)
        res.success, res.message = res_dw["success"], res_dw["message"]
        res.message += "-" * 77 + "\n"
        return res

    def handle_get_extend_launch_run_id(self, req, res: SetEmpty.Response):
        res_dw = {"success": False, "message": " " * 79 + "\n"}
        self.get_extend_launch_run_id_message(res_dw)
        res.success, res.message = res_dw["success"], res_dw["message"]
        res.message += "-" * 77 + "\n"
        return res

    def handle_get_all_info(self, req, res: SetEmpty.Response):
        res_dw = {"success": True, "message": " " * 79 + "\n"}
        self.get_extend_launch_info_message(res_dw)
        self.get_extend_launch_run_id_message(res_dw)
        res.success, res.message = True, res_dw["message"]
        res.message += "-" * 77 + "\n"
        return res

    def send_launch_command(self, id_type="", op_type=""):
        req = LaunchNode.Request()
        req.launch_id, req.launch_op = id_type, op_type
        self.handle_launch(req, LaunchNode.Response())

    def handle_launch(self, req: LaunchNode.Request, res: LaunchNode.Response):
        with self.launch_lock:
            return self._handle_launch(req, res)

    def _handle_launch(self, req: LaunchNode.Request, res: LaunchNode.Response):
        data_time = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
        self.launch_message = f"{data_time} [{req.launch_id}] [{req.launch_op}]"
        write_launch_log_and_print(self.launch_message)
        self.load_robot_config()

        if req.launch_id in self.extend_launch_dict:
            if req.launch_op == OP_TYPE["START"]:
                if self.extend_launch_dict[req.launch_id].is_not_run():
                    res.success = self.extend_launch_dict[req.launch_id].launch()
                    res.message = "Todo1" if res.success else f"start '{req.launch_id}' failed."
                else:
                    res.success = False
                    res.message = "Todo3"
            elif req.launch_op == OP_TYPE["STOP"]:
                self.cancel_auto_retry(req.launch_id)
                if self.extend_launch_dict[req.launch_id].is_run():
                    self.extend_launch_dict[req.launch_id].shutdown()
                    res.success = True
                    res.message = "Todo1"
                else:
                    res.success = False
                    res.message = "Todo2"
            elif req.launch_op == OP_TYPE["RESTART"]:
                self.extend_launch_dict[req.launch_id].stop()
                time.sleep(3)
                res.success = self.extend_launch_dict[req.launch_id].launch()
                res.message = "Todo1" if res.success else f"restart '{req.launch_id}' failed."
            else:
                res.success = False
                res.message = "Todo4"

        elif req.launch_id == self.id_type["CLOSE_ALL"]:
            if req.launch_op == OP_TYPE["START"]:
                for launch_id in list(self.auto_retry_policies):
                    self.cancel_auto_retry(launch_id)
                for launch_id in self.extend_launch_dict.keys():
                    self.extend_launch_dict[launch_id].stop()
                res.success = True
                res.message = "Todo1"
            else:
                res.success = False
                res.message = "Todo4"
        else:
            res.success = False
            res.message = f"no '{req.launch_id}' function"

        if res.message == "Todo1":
            res.message = f"{req.launch_op} '{req.launch_id}' success."
        elif res.message == "Todo2":
            res.message = f"'{req.launch_id}' process isn't running."
        elif res.message == "Todo3":
            res.message = f"another '{req.launch_id}' process is running."
        elif res.message == "Todo4":
            res.message = f"'{req.launch_id}' process doesn't have '{req.launch_op}' operation."

        write_launch_log_and_print(f"[{res.success}] {res.message}\n")
        self.publish_status()
        return res

    def cancel_auto_retry(self, launch_id):
        policy = self.auto_retry_policies.get(launch_id)
        if policy is None or not policy.armed:
            return
        policy.armed = False
        write_launch_log_and_print(f"[retry] [{launch_id}] cancelled")

    def tick_auto_retry(self, now=None):
        if now is None:
            now = time.monotonic()
        for policy in self.auto_retry_policies.values():
            process = self.extend_launch_dict.get(policy.launch_id)
            if process is None:
                continue
            advance_auto_retry(policy, process, now)

    def check_launch_error(self):
        data_time = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
        dead_launch_id_msg = ""
        for key in self.extend_launch_dict.keys():
            if self.extend_launch_dict[key].error():
                dead_launch_id_msg += f" - {key}\n"
                self.extend_launch_dict[key].reset()
        if dead_launch_id_msg != "":
            write_launch_log_and_print(f"{data_time} error launch id:\n{dead_launch_id_msg}")

    def publish_status(self):
        msg = LaunchStatus()
        diagnostic_msg = DiagnosticArray()
        diagnostic_msg.header.stamp = self.get_clock().now().to_msg()
        for launch_id in self.extend_launch_dict.keys():
            process = self.extend_launch_dict[launch_id]
            running = process.is_run() or not process.get_check_status()
            msg.launch_id_list.append(launch_id)
            msg.launch_status.append(running)
            diagnostic_msg.status.append(
                DiagnosticStatus(
                    name=launch_id,
                    values=[KeyValue(key="launch_status", value="true" if running else "false")],
                )
            )
        self.launch_status_pub.publish(msg)
        self.launch_diagnostic_pub.publish(diagnostic_msg)

    def process(self):
        loop_rate = Rate(1)
        while rclpy.ok():
            loop_rate.sleep()
            if not rclpy.ok():
                return
            with self.launch_lock:
                self.check_launch_error()
                self.tick_auto_retry()
                self.publish_status()
                self.load_robot_config()
                self.load_extend_launch_config()


def main(args=None):
    rclpy.init(args=args)
    node = LaunchControlRosNode()
    try:
        rclpy.spin(node)
    except ExternalShutdownException:
        print("[launch_control] receive external shutdown signal, exiting...")
    except KeyboardInterrupt:
        print("[launch_control] receive keyboard interrupt, exiting...")
        pass
    finally:
        print("[launch_control] will shutdown node and rclpy...")
        node.destroy_node()
        if rclpy.ok():
            print("[launch_control] shutdown rclpy.")
            rclpy.shutdown()

if __name__ == "__main__":
    main()
