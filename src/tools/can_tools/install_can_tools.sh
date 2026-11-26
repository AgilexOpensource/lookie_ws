#!/bin/bash
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mode=${1:-install}
if [[ $# -gt 1 || ( "$mode" != install && "$mode" != --check && "$mode" != --help ) ]]; then
    printf 'Usage: %s [--check|--help]\n' "$0" >&2
    exit 2
fi
if [[ "$mode" == --help ]]; then
    printf 'Usage: %s [--check|--help]\n' "$0"
    printf 'Default: install code/config as root and replace an existing config. No CAN or service changes.\n'
    exit 0
fi
if [[ ! -x /usr/bin/python3 ]]; then
    printf 'Required: /usr/bin/python3\n' >&2
    exit 1
fi
/usr/bin/python3 -I -u "$source_dir/can_supervisor.py" --check-config --config "$source_dir/can_bus.json"
if [[ "$mode" == --check ]]; then
    printf 'Source configuration valid. No installation or CAN changes performed.\n'
    exit 0
fi
if [[ $EUID -ne 0 ]]; then
    printf 'Installation requires root; ask an administrator to review and run this script.\n' >&2
    exit 1
fi
if [[ ! -x /usr/sbin/ip && ! -x /sbin/ip && ! -x /usr/bin/ip && ! -x /bin/ip ]]; then
    printf 'Required: system iproute2. Install it before deploying.\n' >&2
    exit 1
fi

check_trusted() {
    local path=$1 owner permissions
    if [[ -L "$path" ]]; then
        printf 'Refusing symlink: %s\n' "$path" >&2
        exit 1
    fi
    owner=$(stat -c %u -- "$path")
    permissions=$(stat -c %a -- "$path")
    if [[ "$owner" != 0 ]] || (( (8#$permissions & 8#022) != 0 )); then
        printf 'Refusing non-root-owned or writable path: %s\n' "$path" >&2
        exit 1
    fi
}

for parent in /opt /etc; do
    check_trusted "$parent"
done
for directory in /opt/can-tools /etc/can-tools; do
    if [[ -e "$directory" || -L "$directory" ]]; then
        check_trusted "$directory"
        if [[ ! -d "$directory" ]]; then
            printf 'Not a directory: %s\n' "$directory" >&2
            exit 1
        fi
    else
        install -d -o root -g root -m 0755 -- "$directory"
    fi
done
for target in /opt/can-tools/can_supervisor.py /etc/can-tools/can_bus.json; do
    if [[ -e "$target" || -L "$target" ]]; then
        check_trusted "$target"
        if [[ ! -f "$target" ]]; then
            printf 'Not a regular file: %s\n' "$target" >&2
            exit 1
        fi
    fi
done
if [[ -e /etc/can-tools/can_bus.json ]]; then
    printf 'Replacing existing /etc/can-tools/can_bus.json\n'
fi
install -o root -g root -m 0644 -- "$source_dir/can_bus.json" /etc/can-tools/can_bus.json
temporary=$(mktemp /opt/can-tools/.can_supervisor.XXXXXXXX)
trap 'rm -f -- "$temporary"' EXIT
install -o root -g root -m 0644 -- "$source_dir/can_supervisor.py" "$temporary"
mv -Tf -- "$temporary" /opt/can-tools/can_supervisor.py
printf 'Installed code and configuration. No CAN interfaces, services, sudoers or launch configs changed.\n'
printf 'Next: follow can_tools/README.md to approve the fixed command and register can_health.\n'
