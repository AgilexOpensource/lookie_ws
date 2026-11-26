#!/bin/bash
set -euo pipefail

check_trusted() {
    local path=$1 owner permissions
    if [[ -L "$path" ]]; then
        printf 'Refusing symlink: %s\n' "$path" >&2
        return 1
    fi
    owner=$(stat -c %u -- "$path")
    permissions=$(stat -c %a -- "$path")
    if [[ "$owner" != 0 ]] || (( (8#$permissions & 8#022) != 0 )); then
        printf 'Refusing non-root-owned or writable path: %s\n' "$path" >&2
        return 1
    fi
}

check_file() {
    local path=$1
    if [[ -e "$path" || -L "$path" ]]; then
        check_trusted "$path" || return 1
        if [[ ! -f "$path" ]]; then
            printf 'Not a regular file: %s\n' "$path" >&2
            return 1
        fi
    fi
}

remove_file() {
    local path=$1 dry_run=$2
    check_file "$path" || return 1
    if [[ ! -e "$path" ]]; then
        printf 'Already absent: %s\n' "$path"
    elif [[ "$dry_run" == true ]]; then
        printf 'Would remove: %s\n' "$path"
    else
        rm -f -- "$path"
        printf 'Removed: %s\n' "$path"
    fi
}

remove_empty_directory() {
    local path=$1 dry_run=$2
    if [[ ! -d "$path" || -L "$path" ]]; then
        return 0
    fi
    if [[ "$dry_run" == true ]]; then
        printf 'Would remove directory only if empty: %s\n' "$path"
    elif ! rmdir -- "$path" 2>/dev/null; then
        printf 'Kept directory (not empty or not removable): %s\n' "$path"
    fi
}

acquire_instance_lock() {
    local lock=$1 dry_run=$2
    UNINSTALL_LOCK_FD=
    if [[ "$dry_run" == false && ! -e "$lock" && ! -L "$lock" ]]; then
        if ! (umask 077; set -o noclobber; : > "$lock"); then
            printf 'Cannot create instance lock safely; retry after inspection\n' >&2
            return 1
        fi
    fi
    if [[ -e "$lock" || -L "$lock" ]]; then
        check_file "$lock" || return 1
        command -v flock > /dev/null || { printf 'Required: util-linux flock\n' >&2; return 1; }
        if ! exec {UNINSTALL_LOCK_FD}< "$lock"; then
            printf 'Cannot inspect instance lock; run dry-run as administrator\n' >&2
            return 1
        fi
        if ! flock -n -x "$UNINSTALL_LOCK_FD"; then
            printf 'can_health is running; stop it before uninstalling\n' >&2
            exec {UNINSTALL_LOCK_FD}<&-
            return 1
        fi
    fi
}

main() {
    local purge=false dry_run=false argument parent directory
    local program=/opt/can-tools/can_supervisor.py
    local config=/etc/can-tools/can_bus.json
    local lock=/run/lock/can-health.lock
    for argument in "$@"; do
        case "$argument" in
            --purge) purge=true ;;
            --dry-run) dry_run=true ;;
            --help)
                printf 'Usage: %s [--purge] [--dry-run]\n' "$0"
                printf 'Default: remove installed program, preserve config. --purge also removes config.\n'
                printf 'Stop can_health and remove its launch/auto-start registration before uninstalling.\n'
                return 0 ;;
            *) printf 'Unknown argument: %s\n' "$argument" >&2; return 2 ;;
        esac
    done
    if [[ "$dry_run" == false && $EUID -ne 0 ]]; then
        printf 'Uninstall requires root; ask an administrator to run this script.\n' >&2
        return 1
    fi
    for parent in /opt /etc; do
        check_trusted "$parent" || return 1
    done
    for directory in /opt/can-tools /etc/can-tools; do
        if [[ -e "$directory" || -L "$directory" ]]; then
            check_trusted "$directory" || return 1
            if [[ ! -d "$directory" ]]; then
                printf 'Not a directory: %s\n' "$directory" >&2
                return 1
            fi
        fi
    done
    check_file "$program" || return 1
    if [[ "$purge" == true ]]; then
        check_file "$config" || return 1
    fi
    if [[ ! -d /run/lock || -L /run/lock || -L /run ]]; then
        printf 'Unsafe or unavailable runtime lock directory\n' >&2
        return 1
    fi
    acquire_instance_lock "$lock" "$dry_run" || return 1
    remove_file "$program" "$dry_run" || return 1
    remove_empty_directory /opt/can-tools "$dry_run"
    if [[ "$purge" == true ]]; then
        remove_file "$config" "$dry_run" || return 1
        remove_empty_directory /etc/can-tools "$dry_run"
    else
        printf 'Preserved configuration: %s\n' "$config"
    fi
    if [[ -n "${UNINSTALL_LOCK_FD:-}" ]]; then
        exec {UNINSTALL_LOCK_FD}<&-
    fi
    printf 'No CAN, service, sudoers, launch configuration or source workspace changes performed.\n'
    printf 'Instance lock file retained to avoid splitting locks between processes.\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
