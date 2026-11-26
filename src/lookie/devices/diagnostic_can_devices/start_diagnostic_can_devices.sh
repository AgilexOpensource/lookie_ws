#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${ROS_SETUP_FILE:-/opt/ros/humble/setup.bash}"
if [[ -n "${ROS_WORKSPACE_SETUP:-}" ]]; then
    source "$ROS_WORKSPACE_SETUP"
fi

exec /usr/bin/python3 -u "$SCRIPT_DIR/diagnostic_can_devices_node.py" \
    --config "${CAN_DIAGNOSTICS_CONFIG:-$SCRIPT_DIR/can_devices.yaml}" "$@"
