#!/usr/bin/env bash
# ==============================================================================
#  一键检查脚本 check_env.sh —— Ubuntu 22.04 + ROS2 Humble + DL/机器人 环境自检
#  用法: bash check_env.sh [-v]
#  输出: [OK ]=通过  [缺 ]=缺失/不符  [~]=提示
# ==============================================================================
shopt -s expand_aliases
VERBOSE=0; [ "${1:-}" = "-v" ] && VERBOSE=1
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo -e "  \e[1;32m[OK ]\e[0m $*"; }
bad()  { FAIL=$((FAIL+1)); echo -e "  \e[1;31m[缺 ]\e[0m $*"; }
warnv(){ echo -e "  \e[1;33m[~]  \e[0m $*"; }
installed_version() {
  dpkg-query -W -f='${Status}\t${Version}\n' "$1" 2>/dev/null |
    awk -F '\t' '$1 == "install ok installed" { print $2; found=1 } END { exit !found }'
}
python_distribution_version() {
  python3 -c 'import importlib.metadata as m, sys; print(m.version(sys.argv[1]))' "$1" 2>/dev/null
}
echo "================= 环境自检 $(date '+%F %T') ================="
. /etc/os-release; echo "系统: $PRETTY_NAME | 内核: $(uname -r)"

# 引入 ROS/conda/CUDA 到 PATH(避免因环境未 source 而误报)
[ -d /opt/ros/humble ] && . /opt/ros/humble/setup.bash >/dev/null 2>&1
[ -d "$HOME/miniconda3" ] && export PATH="$HOME/miniconda3/bin:$PATH"
[ -d /usr/local/cuda/bin ] && export PATH="/usr/local/cuda/bin:$PATH"

echo "-- [1] NVIDIA 驱动 570.195.03 --"
grep -q "570.195.03" /proc/driver/nvidia/version 2>/dev/null && ok "驱动 570.195.03" || bad "未找到 570.195.03(查 /proc/driver/nvidia/version)"

echo "-- [2] CUDA 12.8 --"
if nvcc --version 2>/dev/null | grep -q "release 12.8"; then ok "CUDA $(nvcc --version | grep -oE 'release [0-9.]+' | head -1)"; else bad "nvcc 非 12.8 或缺失"; fi

echo "-- [3] ROS 2 Humble --"
if [ "${ROS_DISTRO:-}" = "humble" ]; then ok "ROS 2 Humble (\$ROS_DISTRO=humble)"
elif [ -d /opt/ros/humble ]; then ok "ROS 2 Humble (/opt/ros/humble 存在)"; else bad "未发现 /opt/ros/humble"; fi

echo "-- [4] Miniconda >= 25.3.1 --"
if command -v conda >/dev/null 2>&1; then
  CV="$(conda --version 2>/dev/null | awk '{print $2}')"
  if [ -n "$CV" ] && [ "$(printf '%s\n%s\n' "$CV" "25.3.1" | sort -V | tail -1)" = "$CV" ]; then ok "conda $CV (>=25.3.1)"
  else bad "conda $CV 过低(<25.3.1)"; fi
  conda config --show channels 2>/dev/null | grep -q conda-forge && ok "conda 频道含 conda-forge" || warnv "conda-forge 未配置"
  [ "$(conda config --show channel_priority 2>/dev/null | awk '{print $2}')" = "strict" ] && ok "channel_priority=strict" || warnv "channel_priority 非 strict"
else bad "conda 未安装(miniconda3)"; fi

echo "-- [5] librealsense 2.56.4 --"
LV="$(dpkg-query -W -f='${Version}' librealsense2 2>/dev/null)"
if [ -n "$LV" ] && printf '%s' "$LV" | grep -qE '(^|:)2\.56\.4([.+~-]|$)'; then
  ok "librealsense2 $LV (dpkg)"
elif RV="$(pkg-config --modversion realsense2 2>/dev/null)" && printf '%s' "$RV" | grep -qE '^2\.56\.4([.]|$)'; then
  ok "librealsense2 $RV (pkg-config 本地安装)"
elif command -v realsense-viewer >/dev/null 2>&1 && realsense-viewer --version 2>&1 | grep -qE '2\.56\.4([.]|$)'; then
  ok "librealsense2 2.56.4 (realsense-viewer 本地安装)"
else
  bad "librealsense2 2.56.4 缺失/不符(包版本=$LV, pkg-config版本=$(pkg-config --modversion realsense2 2>/dev/null || echo 未找到))"
fi

echo "-- [6] ROS 依赖 (nav2/slam_toolbox/cartographer/fast_lio) --"
PKGS="$(ros2 pkg list 2>/dev/null)"
for kw in nav2_bringup nav2_amcl nav2_map_server slam_toolbox cartographer; do
  printf '%s' "$PKGS" | grep -qiE "$kw" && ok "ROS 包: $kw" || bad "ROS 包缺失: $kw"
done
printf '%s' "$PKGS" | grep -qi "fast_lio" && ok "fast_lio(非常规已装)" || warnv "fast_lio 未装(apt 无此包, 需源码编译——预期)"

echo "-- [6a] ROS desktop 之外的依赖 --"
for p in ros-humble-diagnostic-updater ros-humble-xacro; do
  if VV="$(installed_version "$p")"; then ok "$p $VV"; else bad "$p 缺失(需额外安装)"; fi
done

echo "-- [6b] ROS 图像与插件依赖 --"
for p in ros-humble-cv-bridge ros-humble-image-transport ros-humble-pluginlib; do
  if VV="$(installed_version "$p")"; then ok "$p $VV"; else bad "$p 缺失"; fi
done

echo "-- [6c] ROS GPS 消息依赖 --"
if VV="$(installed_version ros-humble-gps-msgs)"; then ok "ros-humble-gps-msgs $VV"; else bad "ros-humble-gps-msgs 缺失"; fi

echo "-- [7] 基础工具 --"
for c in git cmake gparted htop cutecom byobu openssh-server wireshark; do
  if VV="$(installed_version "$c")"; then ok "$c $VV"; else bad "$c 缺失"; fi
done

echo "-- [7a] CAN 与网络工具 --"
for p in can-utils iproute2 net-tools; do
  if VV="$(installed_version "$p")"; then ok "$p $VV"; else bad "$p 缺失"; fi
done

echo "-- [7b] Python 依赖 --"
for p in python-can pytest; do
  if VV="$(python_distribution_version "$p")"; then ok "$p $VV (python3)"; else bad "$p 未安装到当前 python3 环境"; fi
done
if VV="$(installed_version python3-yaml)"; then ok "python3-yaml $VV"; else bad "python3-yaml 缺失"; fi

echo "-- [8] 远控/备份 --"
if VV="$(installed_version nomachine)"; then ok "nomachine $VV"; else warnv "nomachine 未装(或非关键跳过)"; fi
SUNLOGIN_FOUND=0
for p in sunlogin sunloginclient sunloginenterprise awesun awesuncli awesunhost; do
  if VV="$(installed_version "$p")"; then
    ok "向日葵 ($p) $VV"
    SUNLOGIN_FOUND=1
    break
  fi
done
[ "$SUNLOGIN_FOUND" -eq 1 ] || warnv "向日葵 未装(或非 dpkg 安装)"
dpkg-query -W -f='${Version}' systemback >/dev/null 2>&1 && ok "systemback" || warnv "systemback 未装(官方源已移除)"

echo "-- [9] GStreamer / VA-API 依赖 --"
for p in libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev gstreamer1.0-plugins-base gstreamer1.0-vaapi pkg-config intel-media-va-driver vainfo gstreamer1.0-tools; do
  if VV="$(installed_version "$p")"; then ok "$p $VV"; else bad "$p 缺失"; fi
done
if VV="$(installed_version intel-gpu-tools)"; then
  if command -v intel_gpu_top >/dev/null 2>&1; then ok "intel_gpu_top (intel-gpu-tools) $VV"
  else bad "intel-gpu-tools $VV 已安装，但 intel_gpu_top 命令不可用(PATH)"; fi
elif command -v intel_gpu_top >/dev/null 2>&1; then
  ok "intel_gpu_top (非 dpkg 安装)"
else
  bad "intel_gpu_top 缺失(安装包: intel-gpu-tools)"
fi

echo "======================================================"
echo "结果: 通过 $PASS 项 / 异常 $FAIL 项"
[ "$FAIL" -eq 0 ] && echo -e "\e[1;32m全部关键项通过 ✔\e[0m" || echo -e "\e[1;31m有 $FAIL 项未通过(见上方[缺])\e[0m"
echo "(提示: conda/ros 请在交互终端先 source ~/.bashrc)"
exit 0
