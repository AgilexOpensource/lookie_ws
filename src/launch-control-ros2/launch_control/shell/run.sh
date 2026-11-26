#!/bin/bash
echo "unset waiting: 10s..."
# sleep 10
export home=$(awk -F: '$3==1000{print $6}' /etc/passwd)
export user=$(awk -F: '$3==1000{print $1}' /etc/passwd)

echo "home: $home"
echo "HOME: $HOME"
echo "USER: $USER"
echo "user: $user"

export pkg_ws_path="/home/agilex/develop/launch_control/launch_control_ws"

if [ -z "$(ros2 pkg prefix launch_control 2>/dev/null)" ]; then
    if [ -f "$pkg_ws_path/install/setup.bash" ]; then
        echo "source $pkg_ws_path/install/setup.bash"
        # shellcheck disable=SC1091
        source "$pkg_ws_path/install/setup.bash"
    else
        echo "error: launch_control not found and $pkg_ws_path/install/setup.bash does not exist" >&2
        exit 1
    fi
fi

# pkg_share="$(ros2 pkg prefix launch_control 2>/dev/null)/share/launch_control"
# if [ -d "$pkg_share/config" ]; then
#     if [ ! -f "$home/extend_launch.sh" ]; then
#         cp "$pkg_share/config/extend_launch.sh" "$home/extend_launch.sh"
#         echo "created $home/extend_launch.sh"
#     fi
#     if [ ! -f "$home/auto_launch.sh" ]; then
#         cp "$pkg_share/config/auto_launch.sh" "$home/auto_launch.sh"
#         echo "created $home/auto_launch.sh"
#     fi
#     if [ ! -f "$home/robot_config.bash" ]; then
#         cp "$pkg_share/config/robot_config.bash" "$home/robot_config.bash"
#         echo "created $home/robot_config.bash"
#     fi
# fi

ros2 run launch_control launch_control.py
