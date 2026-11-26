#!/bin/bash
# ============================================================
# can_bind.sh - Scan / bind / rename / start-stop CAN interfaces
#
# Usage:
#   ./can_bind.sh                                    # default: rename (if needed) + up
#   ./can_bind.sh --up                               # same as default
#   ./can_bind.sh --up canp0,can0 --bitrate 1000000  # target interfaces, common bitrate
#   ./can_bind.sh --bitrate 1000000                  # same as --up --bitrate
#   ./can_bind.sh --down canp0,can0                  # rename (if needed) then down
#   ./can_bind.sh --rename                           # rename only
#   ./can_bind.sh --scan                             # enumerate CAN devices (read-only)
#   ./can_bind.sh --list                             # show status and rename plan (read-only)
#   ./can_bind.sh --help
#
# MAPPING entry format: "PCIe_key=name[:bitrate]"
#   PCIe_key may be:
#     "PCIe_addr:dev_id"  required for multi-port cards, e.g. "0000:03:00.0:0x0"
#     "PCIe_addr"         allowed only when the PCIe address has a single CAN port
#
#   Examples:
#     "0000:03:00.0:0x0=canp0:1000000"
#     "0000:03:00.0:0x1=canp1"
#     "0000:40:00.0=can6:500000"        # single-port card, shorthand key
#
# Bitrate resolution order (for --up):
#   1) command-line --bitrate N
#   2) ":bitrate" suffix in MAPPING
#   3) interface's current bitrate (leave as-is, just bring up)
#   4) none of the above -> warn and skip
#
# Privileges:
#   --scan / --list are read-only; other modes use sudo only when needed.
# ============================================================

set -euo pipefail

# ---------- Configuration ----------
# IMPORTANT: MAPPING is a plain indexed array of "key=value" strings.
# Associative arrays with keys containing ':' trigger arithmetic-evaluation
# bugs in some bash builds, so we deliberately avoid them.
declare -a MAPPING=(
    "0000:03:00.0:0x0=can_chassis_imu:500000"
    "0000:03:00.0:0x1=can_chassis:500000"
    "0000:30:00.0:0x0=can_right_arm:1000000"
    "0000:30:00.0:0x1=can_torso:1000000"
    "0000:31:00.0:0x0=can_left_arm:1000000"
    "0000:31:00.0:0x1=can_head:1000000"
    # Single-port card example:
    # "0000:40:00.0=can0:500000"
)
# -----------------------------------

# ---------- Help ----------
print_help() {
    sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'
}

# ---------- Argument parsing ----------
MODE="up"
BITRATE_ARG=""
UP_DOWN_NAMES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scan)   MODE="scan"; shift ;;
        --list)   MODE="list"; shift ;;
        --rename) MODE="rename"; shift ;;
        --up)
            MODE="up"; shift
            if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                UP_DOWN_NAMES="${UP_DOWN_NAMES:+$UP_DOWN_NAMES,}$1"; shift
            fi
            ;;
        --down)
            MODE="down"; shift
            if [[ $# -gt 0 && ! "$1" =~ ^-- ]]; then
                UP_DOWN_NAMES="${UP_DOWN_NAMES:+$UP_DOWN_NAMES,}$1"; shift
            fi
            ;;
        --bitrate)
            [[ $# -lt 2 ]] && { echo "Error: --bitrate requires an argument" >&2; exit 2; }
            BITRATE_ARG="$2"; shift 2 ;;
        --bitrate=*)
            BITRATE_ARG="${1#*=}"; shift ;;
        -h|--help) print_help; exit 0 ;;
        *)
            echo "Unknown argument: $1 (run --help for usage)" >&2; exit 2 ;;
    esac
done

if [[ -n "$BITRATE_ARG" && ! "$BITRATE_ARG" =~ ^[0-9]+$ ]]; then
    echo "Error: --bitrate requires a positive integer, got '$BITRATE_ARG'" >&2
    exit 2
fi

if [[ "$MODE" == "down" && -n "$BITRATE_ARG" ]]; then
    echo "Warning: --bitrate is ignored in --down mode" >&2
    BITRATE_ARG=""
fi

# ---------- Elevation on demand ----------
if [[ $EUID -eq 0 ]]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    SUDO=""
fi
can_elevate() { [[ $EUID -eq 0 ]] || [[ -n "$SUDO" ]]; }

# ---------- Utilities ----------
normalize_dev_id() { printf '0x%x\n' "$1" 2>/dev/null || echo "$1"; }

is_admin_up() {
    local f="/sys/class/net/$1/flags"
    [[ -f "$f" ]] || { echo 0; return; }
    local flags; flags=$(cat "$f")
    (( flags & 0x1 )) && echo 1 || echo 0
}

get_current_bitrate() {
    local iface="$1"
    ip -details link show "$iface" 2>/dev/null \
        | grep -oP 'bitrate \K[0-9]+' | head -1 || true
}

probe_iface() {
    local iface_path="$1"
    IFACE=$(basename "$iface_path")
    PCI_ADDR=""; DEV_ID=""; DRIVER="(none)"; VENDOR="?"; DEVICE="?"
    if [[ -L "$iface_path/device" ]]; then
        local real p b
        real=$(readlink -f "$iface_path/device")
        p="$real"
        while [[ "$p" != "/" ]]; do
            b=$(basename "$p")
            if [[ "$b" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$ ]]; then
                PCI_ADDR="$b"
                [[ -f "$p/vendor" ]] && VENDOR=$(cat "$p/vendor")
                [[ -f "$p/device" ]] && DEVICE=$(cat "$p/device")
                [[ -L "$p/driver" ]] && DRIVER=$(basename "$(readlink "$p/driver")")
                break
            fi
            p=$(dirname "$p")
        done
    fi
    if [[ -f "$iface_path/dev_id" ]]; then
        local raw; raw=$(cat "$iface_path/dev_id")
        [[ -n "$raw" ]] && DEV_ID=$(normalize_dev_id "$raw")
    fi
    ADMIN_UP=$(is_admin_up "$IFACE")
}

collect_all_can() {
    shopt -s nullglob
    local iface_path
    for iface_path in /sys/class/net/can*; do
        probe_iface "$iface_path"
        echo "$IFACE|$PCI_ADDR|$DEV_ID|$DRIVER|$VENDOR|$DEVICE|$ADMIN_UP"
    done
    shopt -u nullglob
}

declare -a IFACES=()
while IFS= read -r line; do IFACES+=("$line"); done < <(collect_all_can)

# ============================================================
# MAPPING lookups (implemented as string scans -- no assoc arrays)
# ============================================================

# Echo the full "value" stored for an exact MAPPING key, or empty.
mapping_get_value_by_key() {
    local want="$1" entry k v
    for entry in "${MAPPING[@]}"; do
        k="${entry%%=*}"
        v="${entry#*=}"
        if [[ "$k" == "$want" ]]; then
            printf '%s' "$v"
            return 0
        fi
    done
    printf ''
}

# Echo how many CAN ports share the given PCIe address.
count_ports_on_pci() {
    local want="$1" n=0 line f2
    for line in "${IFACES[@]}"; do
        f2="${line#*|}"; f2="${f2%%|*}"
        [[ "$f2" == "$want" ]] && n=$((n + 1))
    done
    printf '%s' "$n"
}

# Echo the target name for a given (PCIe addr, dev_id).
# Output: "<name>" on success, "__AMBIGUOUS__" if a shorthand key is ambiguous,
# empty string if no match.
mapping_lookup_name() {
    local pci="$1" did="$2"
    local fullkey="${pci}:${did}"
    local entry k v name cnt

    # Pass 1: exact full key
    for entry in "${MAPPING[@]}"; do
        k="${entry%%=*}"
        v="${entry#*=}"
        if [[ "$k" == "$fullkey" ]]; then
            printf '%s' "${v%%:*}"
            return 0
        fi
    done

    # Pass 2: PCIe-only shorthand key (must be unique on this PCIe addr)
    for entry in "${MAPPING[@]}"; do
        k="${entry%%=*}"
        v="${entry#*=}"
        if [[ "$k" == "$pci" ]]; then
            cnt=$(count_ports_on_pci "$pci")
            if [[ "$cnt" -gt 1 ]] 2>/dev/null; then
                printf '%s' "__AMBIGUOUS__"
                return 0
            fi
            printf '%s' "${v%%:*}"
            return 0
        fi
    done

    printf ''
}

# Echo the bitrate configured in MAPPING for the given name, or empty.
mapping_lookup_bitrate() {
    local want="$1" entry v nm
    for entry in "${MAPPING[@]}"; do
        v="${entry#*=}"
        if [[ "$v" == *:* ]]; then
            nm="${v%%:*}"
            if [[ "$nm" == "$want" ]]; then
                printf '%s' "${v##*:}"
                return 0
            fi
        fi
    done
    printf ''
}

# Echo all target names from MAPPING, one per line.
mapping_all_names() {
    local entry v
    for entry in "${MAPPING[@]}"; do
        v="${entry#*=}"
        printf '%s\n' "${v%%:*}"
    done
}

# ============================================================
# --scan
# ============================================================
if [[ "$MODE" == "scan" ]]; then
    echo "=============================================================="
    echo " CAN devices found in system"
    echo "=============================================================="
    printf '%-12s %-14s %-6s %-12s %-8s %-8s %-4s\n' \
        "IFACE" "PCIe_addr" "dev_id" "driver" "Vendor" "Device" "UP"
    echo "--------------------------------------------------------------"

    declare -a SCAN_KEYS=()
    for line in "${IFACES[@]}"; do
        IFS='|' read -r name pci did drv ven dev up <<< "$line"
        printf '%-12s %-14s %-6s %-12s %-8s %-8s %-4s\n' \
            "$name" "${pci:-?}" "${did:-?}" "$drv" "$ven" "$dev" \
            "$([[ "$up" == 1 ]] && echo yes || echo no)"
        if [[ -n "$pci" && -n "$did" ]]; then
            SCAN_KEYS+=("$pci|$did")
        fi
    done

    echo
    echo "=============================================================="
    echo " Copy-pasteable MAPPING entries (format: \"key=value\")"
    echo "=============================================================="
    for k in "${SCAN_KEYS[@]}"; do
        IFS='|' read -r pci did <<< "$k"
        full="$pci:$did"
        cur=$(mapping_get_value_by_key "$full")
        if [[ -n "$cur" ]]; then
            printf '    "%s=%s"   # already in MAPPING\n' "$full" "$cur"
        else
            printf '    "%s="\n' "$full"
        fi
    done
    exit 0
fi

# ============================================================
# Build rename plan
# ============================================================
declare -a PLAN_RAW=()
declare -a PLAN=()
declare -a SKIPPED=()
declare -A TARGETS_USED=()
declare -A CURRENT_NAMES=()
declare -A WILL_RELEASE=()

for line in "${IFACES[@]}"; do
    IFS='|' read -r name _ <<< "$line"
    CURRENT_NAMES["$name"]=1
done

for line in "${IFACES[@]}"; do
    IFS='|' read -r name pci did _ _ _ up <<< "$line"
    if [[ -z "$pci" || -z "$did" ]]; then
        SKIPPED+=("$name|missing PCIe address or dev_id"); continue
    fi
    target=$(mapping_lookup_name "$pci" "$did")
    if [[ "$target" == "__AMBIGUOUS__" ]]; then
        SKIPPED+=("$name|PCIe ($pci) has multiple CAN ports; shorthand key is ambiguous, use \"$pci:$did\"")
        continue
    fi
    if [[ -z "$target" ]]; then
        SKIPPED+=("$name|not in MAPPING (PCIe=$pci, dev_id=$did)"); continue
    fi
    [[ "$name" == "$target" ]] && continue
    prev="${TARGETS_USED[$target]:-}"
    if [[ -n "$prev" ]]; then
        SKIPPED+=("$name|target name $target already mapped from '$prev'"); continue
    fi
    TARGETS_USED["$target"]="$name"
    PLAN_RAW+=("$name|$target|$pci|$did|$up")
done

for item in "${PLAN_RAW[@]}"; do
    IFS='|' read -r old _ <<< "$item"
    WILL_RELEASE["$old"]=1
done

for item in "${PLAN_RAW[@]}"; do
    IFS='|' read -r old new pci did up <<< "$item"
    if [[ -n "${CURRENT_NAMES[$new]:-}" && -z "${WILL_RELEASE[$new]:-}" ]]; then
        SKIPPED+=("$old|target name $new is held by an interface not scheduled to rename"); continue
    fi
    PLAN+=("$item")
done

# ============================================================
# --list
# ============================================================
if [[ "$MODE" == "list" ]]; then
    echo "Current CAN device status:"
    printf '  %-14s %-14s %-6s %-14s %-4s %-10s %-10s\n' \
        "IFACE" "PCIe_addr" "dev_id" "target" "UP" "MAPPING" "cur_bitrate"
    echo "  ------------------------------------------------------------------------"
    for line in "${IFACES[@]}"; do
        IFS='|' read -r name pci did _ _ _ up <<< "$line"
        target=$(mapping_lookup_name "$pci" "$did")
        [[ "$target" == "__AMBIGUOUS__" ]] && target="?ambiguous?"
        [[ -z "$target" ]] && target="?"
        br_cfg=$(mapping_lookup_bitrate "$target")
        [[ -z "$br_cfg" ]] && br_cfg="-"
        br_cur=$(get_current_bitrate "$name")
        [[ -z "$br_cur" ]] && br_cur="-"
        printf '  %-14s %-14s %-6s %-14s %-4s %-10s %-10s\n' \
            "$name" "${pci:-?}" "${did:-?}" "$target" \
            "$([[ "$up" == 1 ]] && echo yes || echo no)" \
            "$br_cfg" "$br_cur"
    done

    echo
    if [[ ${#PLAN[@]} -eq 0 ]]; then
        echo "No renames needed (all interfaces already use target names)."
    else
        echo "Rename plan:"
        for item in "${PLAN[@]}"; do
            IFS='|' read -r old new pci did up <<< "$item"
            printf '  %-10s -> %-16s  (PCIe=%s, dev_id=%s)\n' "$old" "$new" "$pci" "$did"
        done
    fi
    if [[ ${#SKIPPED[@]} -gt 0 ]]; then
        echo
        echo "Skipped:"
        for s in "${SKIPPED[@]}"; do
            IFS='|' read -r n r <<< "$s"
            printf '  %-12s %s\n' "$n" "$r"
        done
    fi
    exit 0
fi

# ============================================================
# Perform rename (before --rename / --up / --down)
# ============================================================
rename_rc=0
if [[ ${#PLAN[@]} -gt 0 ]]; then
    if ! can_elevate; then
        echo "Error: renaming requires root or sudo" >&2
        exit 1
    fi

    echo "Will perform the following renames:"
    for item in "${PLAN[@]}"; do
        IFS='|' read -r old new pci did up <<< "$item"
        printf '  %-10s -> %-16s  (PCIe=%s, dev_id=%s)\n' "$old" "$new" "$pci" "$did"
    done
    echo

    declare -a STAGE1=()
    i=0
    for item in "${PLAN[@]}"; do
        IFS='|' read -r old new pci did up <<< "$item"
        tmp="tmp_$$_$i"; i=$((i+1))
        $SUDO ip link set "$old" down 2>/dev/null || true
        if $SUDO ip link set "$old" name "$tmp"; then
            STAGE1+=("$old|$tmp|$new|$up|$pci|$did")
        else
            echo "[FAIL] $old -> $tmp (temporary name)" >&2
            [[ "$up" == "1" ]] && $SUDO ip link set "$old" up 2>/dev/null || true
            rename_rc=1
        fi
    done

    for r in "${STAGE1[@]}"; do
        IFS='|' read -r old tmp new up pci did <<< "$r"
        if $SUDO ip link set "$tmp" name "$new"; then
            echo "[OK]   $old -> $new"
            [[ "$up" == "1" ]] && $SUDO ip link set "$new" up 2>/dev/null || true
        else
            echo "[FAIL] $tmp -> $new, attempting rollback" >&2
            if $SUDO ip link set "$tmp" name "$old" 2>/dev/null; then
                echo "       rolled back to $old"
                [[ "$up" == "1" ]] && $SUDO ip link set "$old" up 2>/dev/null || true
            else
                echo "       [FATAL] rollback failed, interface left as $tmp" >&2
            fi
            rename_rc=1
        fi
    done
    echo
fi

# ---------- rename only ----------
if [[ "$MODE" == "rename" ]]; then
    echo "Current CAN interfaces:"
    ip -br link show | grep -E '^can' || true
    exit $rename_rc
fi

# ============================================================
# Resolve up/down target list
# ============================================================
declare -a TARGETS=()
if [[ -n "$UP_DOWN_NAMES" ]]; then
    IFS=',' read -ra TARGETS <<< "$UP_DOWN_NAMES"
    for i in "${!TARGETS[@]}"; do
        TARGETS[$i]="${TARGETS[$i]// /}"
    done
else
    while IFS= read -r n; do
        [[ -n "$n" ]] && TARGETS+=("$n")
    done < <(mapping_all_names)
fi

# ============================================================
# --down
# ============================================================
if [[ "$MODE" == "down" ]]; then
    if ! can_elevate; then
        echo "Error: --down requires root or sudo" >&2
        exit 1
    fi

    rc=$rename_rc
    declare -a MISSING_IF=()
    for t in "${TARGETS[@]}"; do
        [[ -z "$t" ]] && continue
        if [[ ! -e "/sys/class/net/$t" ]]; then
            MISSING_IF+=("$t"); continue
        fi
        $SUDO ip link set "$t" down
        echo "[DOWN] $t"
    done

    if [[ ${#MISSING_IF[@]} -gt 0 ]]; then
        echo >&2
        echo "The following interfaces do not exist (use target names):" >&2
        for n in "${MISSING_IF[@]}"; do echo "  - $n" >&2; done
        rc=1
    fi
    exit $rc
fi

# ============================================================
# --up (default)
# ============================================================
if [[ "$MODE" == "up" ]]; then
    if ! can_elevate; then
        echo "Error: --up requires root or sudo" >&2
        exit 1
    fi

    rc=$rename_rc
    declare -a MISSING_IF=()
    declare -a NEED_BITRATE=()

    for t in "${TARGETS[@]}"; do
        [[ -z "$t" ]] && continue
        if [[ ! -e "/sys/class/net/$t" ]]; then
            MISSING_IF+=("$t"); continue
        fi

        br=""
        if [[ -n "$BITRATE_ARG" ]]; then
            br="$BITRATE_ARG"
        else
            br=$(mapping_lookup_bitrate "$t")
        fi

        if [[ -n "$br" ]]; then
            $SUDO ip link set "$t" down 2>/dev/null || true
            if $SUDO ip link set "$t" type can bitrate "$br"; then
                $SUDO ip link set "$t" up
                echo "[UP]   $t (bitrate=$br)"
            else
                echo "[FAIL] $t: could not set bitrate=$br" >&2
                $SUDO ip link set "$t" type can bitrate "$br" || true
                rc=1
            fi
        else
            if $SUDO ip link set "$t" up 2>/dev/null; then
                cur=$(get_current_bitrate "$t")
                [[ -z "$cur" ]] && cur="?"
                echo "[UP]   $t (keeping existing bitrate=$cur)"
            else
                NEED_BITRATE+=("$t")
            fi
        fi
    done

    if [[ ${#MISSING_IF[@]} -gt 0 ]]; then
        echo >&2
        echo "The following interfaces do not exist (use target names):" >&2
        for n in "${MISSING_IF[@]}"; do echo "  - $n" >&2; done
        rc=1
    fi

    if [[ ${#NEED_BITRATE[@]} -gt 0 ]]; then
        echo >&2
        echo "The following interfaces could not be brought up directly" >&2
        echo "(usually because no bitrate has ever been configured)." >&2
        echo "Please add \":bitrate\" in MAPPING, or pass --bitrate N:" >&2
        for m in "${NEED_BITRATE[@]}"; do echo "  - $m" >&2; done
        rc=1
    fi

    exit $rc
fi
