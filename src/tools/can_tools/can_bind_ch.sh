#!/bin/bash
# ============================================================
# can_bind.sh - 扫描 / 绑定 / 重命名 / 启停 CAN 接口
#
# 用法:
#   ./can_bind.sh                                    # 默认: 重命名(如需) + up
#   ./can_bind.sh --up                               # 同默认
#   ./can_bind.sh --up canp0,can0 --bitrate 1000000  # 指定接口并统设波特率
#   ./can_bind.sh --bitrate 1000000                  # 等价于 --up --bitrate
#   ./can_bind.sh --down canp0,can0                  # 先重命名(如需)再 down
#   ./can_bind.sh --rename                           # 只重命名
#   ./can_bind.sh --scan                             # 枚举 CAN 设备（只读）
#   ./can_bind.sh --list                             # 查看状态与计划（只读）
#   ./can_bind.sh --help
#
# MAPPING 条目格式: "PCIe键=名称[:波特率]"
#   PCIe键 可以是:
#     "PCIe地址:dev_id"  多端口卡必须写完整键，如 "0000:03:00.0:0x0"
#     "PCIe地址"         仅当该 PCIe 地址下只有一个 CAN 端口时可用
#
#   示例:
#     "0000:03:00.0:0x0=canp0:1000000"
#     "0000:03:00.0:0x1=canp1"
#     "0000:40:00.0=can6:500000"        # 单端口卡，简化键
#
# 波特率解析顺序（--up 时）:
#   1) 命令行 --bitrate N
#   2) MAPPING 值中的 ":波特率"
#   3) 接口当前已配置的波特率（不重配，仅 up）
#   4) 都没有 → 提示并跳过
#
# 权限:
#   --scan / --list 只读；其余模式在真正改动接口时才用 sudo。
# ============================================================

set -euo pipefail

# ---------- 配置区 ----------
# 重要: MAPPING 是普通索引数组，每项是 "键=值" 字符串。
# 关联数组下标含 ':' 会在部分 bash 版本触发算术求值 bug，
# 所以这里刻意避开关联数组。
declare -a MAPPING=(
    "0000:03:00.0:0x0=can_chassis_imu:500000"
    "0000:03:00.0:0x1=can_chassis:500000"
    "0000:30:00.0:0x0=can_right_arm:1000000"
    "0000:30:00.0:0x1=can_torso:1000000"
    "0000:31:00.0:0x0=can_left_arm:1000000"
    "0000:31:00.0:0x1=can_head:1000000"
    # 单端口卡示例:
    # "0000:40:00.0=can0:500000"
)
# -----------------------------------

# ---------- 帮助 ----------
print_help() {
    sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'
}

# ---------- 参数解析 ----------
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
            [[ $# -lt 2 ]] && { echo "错误: --bitrate 需要参数" >&2; exit 2; }
            BITRATE_ARG="$2"; shift 2 ;;
        --bitrate=*)
            BITRATE_ARG="${1#*=}"; shift ;;
        -h|--help) print_help; exit 0 ;;
        *)
            echo "未知参数: $1 （--help 查看用法）" >&2; exit 2 ;;
    esac
done

if [[ -n "$BITRATE_ARG" && ! "$BITRATE_ARG" =~ ^[0-9]+$ ]]; then
    echo "错误: --bitrate 需要正整数，得到 '$BITRATE_ARG'" >&2
    exit 2
fi

if [[ "$MODE" == "down" && -n "$BITRATE_ARG" ]]; then
    echo "警告: --down 模式下忽略 --bitrate" >&2
    BITRATE_ARG=""
fi

# ---------- 按需提权 ----------
if [[ $EUID -eq 0 ]]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    SUDO=""
fi
can_elevate() { [[ $EUID -eq 0 ]] || [[ -n "$SUDO" ]]; }

# ---------- 工具 ----------
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
# MAPPING 查找（纯字符串扫描，不用关联数组）
# ============================================================

# 按精确键返回 MAPPING 中的值，找不到输出空
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

# 返回给定 PCIe 地址下 CAN 端口的数量
count_ports_on_pci() {
    local want="$1" n=0 line f2
    for line in "${IFACES[@]}"; do
        f2="${line#*|}"; f2="${f2%%|*}"
        [[ "$f2" == "$want" ]] && n=$((n + 1))
    done
    printf '%s' "$n"
}

# 根据 (PCIe 地址, dev_id) 返回目标名称。
# 成功: "<名称>"；简化键歧义: "__AMBIGUOUS__"；无匹配: 空。
mapping_lookup_name() {
    local pci="$1" did="$2"
    local fullkey="${pci}:${did}"
    local entry k v name cnt

    # 第一遍: 精确完整键
    for entry in "${MAPPING[@]}"; do
        k="${entry%%=*}"
        v="${entry#*=}"
        if [[ "$k" == "$fullkey" ]]; then
            printf '%s' "${v%%:*}"
            return 0
        fi
    done

    # 第二遍: 纯 PCIe 简化键（要求该 PCIe 地址下端口唯一）
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

# 按名称返回 MAPPING 中配置的波特率，找不到输出空
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

# 列出 MAPPING 中所有目标名称，每行一个
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
    echo " 系统中所有 CAN 设备"
    echo "=============================================================="
    printf '%-12s %-14s %-6s %-12s %-8s %-8s %-4s\n' \
        "IFACE" "PCIe地址" "dev_id" "驱动" "Vendor" "Device" "UP"
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
    echo " 可粘贴的 MAPPING 条目（格式: \"键=值\"）"
    echo "=============================================================="
    for k in "${SCAN_KEYS[@]}"; do
        IFS='|' read -r pci did <<< "$k"
        full="$pci:$did"
        cur=$(mapping_get_value_by_key "$full")
        if [[ -n "$cur" ]]; then
            printf '    "%s=%s"   # 已在映射表\n' "$full" "$cur"
        else
            printf '    "%s="\n' "$full"
        fi
    done
    exit 0
fi

# ============================================================
# 计算重命名计划
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
        SKIPPED+=("$name|缺少 PCIe 地址或 dev_id"); continue
    fi
    target=$(mapping_lookup_name "$pci" "$did")
    if [[ "$target" == "__AMBIGUOUS__" ]]; then
        SKIPPED+=("$name|PCIe ($pci) 下有多个 CAN 端口，简化键有歧义，请改用 \"$pci:$did\"")
        continue
    fi
    if [[ -z "$target" ]]; then
        SKIPPED+=("$name|未在 MAPPING 中 (PCIe=$pci, dev_id=$did)"); continue
    fi
    [[ "$name" == "$target" ]] && continue
    prev="${TARGETS_USED[$target]:-}"
    if [[ -n "$prev" ]]; then
        SKIPPED+=("$name|目标名 $target 与 '$prev' 重复映射"); continue
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
        SKIPPED+=("$old|目标名 $new 被未计划改名的接口占用"); continue
    fi
    PLAN+=("$item")
done

# ============================================================
# --list
# ============================================================
if [[ "$MODE" == "list" ]]; then
    echo "当前 CAN 设备状态:"
    printf '  %-14s %-14s %-6s %-14s %-4s %-10s %-10s\n' \
        "IFACE" "PCIe地址" "dev_id" "目标名" "UP" "MAPPING" "当前bitrate"
    echo "  ------------------------------------------------------------------------"
    for line in "${IFACES[@]}"; do
        IFS='|' read -r name pci did _ _ _ up <<< "$line"
        target=$(mapping_lookup_name "$pci" "$did")
        [[ "$target" == "__AMBIGUOUS__" ]] && target="?歧义?"
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
        echo "无需重命名（所有接口已是目标名）。"
    else
        echo "重命名计划:"
        for item in "${PLAN[@]}"; do
            IFS='|' read -r old new pci did up <<< "$item"
            printf '  %-10s -> %-16s  (PCIe=%s, dev_id=%s)\n' "$old" "$new" "$pci" "$did"
        done
    fi
    if [[ ${#SKIPPED[@]} -gt 0 ]]; then
        echo
        echo "被跳过:"
        for s in "${SKIPPED[@]}"; do
            IFS='|' read -r n r <<< "$s"
            printf '  %-12s %s\n' "$n" "$r"
        done
    fi
    exit 0
fi

# ============================================================
# 执行重命名（--rename / --up / --down 都先做）
# ============================================================
rename_rc=0
if [[ ${#PLAN[@]} -gt 0 ]]; then
    if ! can_elevate; then
        echo "错误: 重命名需要 root 或 sudo 权限" >&2
        exit 1
    fi

    echo "将执行以下重命名:"
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
            echo "[失败] $old -> $tmp (临时名)" >&2
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
            echo "[失败] $tmp -> $new，尝试回滚" >&2
            if $SUDO ip link set "$tmp" name "$old" 2>/dev/null; then
                echo "       已回滚到 $old"
                [[ "$up" == "1" ]] && $SUDO ip link set "$old" up 2>/dev/null || true
            else
                echo "       [严重] 回滚失败，接口停留在 $tmp" >&2
            fi
            rename_rc=1
        fi
    done
    echo
fi

# ---------- 只重命名 ----------
if [[ "$MODE" == "rename" ]]; then
    echo "当前 CAN 接口:"
    ip -br link show | grep -E '^can' || true
    exit $rename_rc
fi

# ============================================================
# 解析 up/down 目标列表
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
        echo "错误: --down 需要 root 或 sudo 权限" >&2
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
        echo "以下接口不存在（请使用目标名）:" >&2
        for n in "${MISSING_IF[@]}"; do echo "  - $n" >&2; done
        rc=1
    fi
    exit $rc
fi

# ============================================================
# --up（默认）
# ============================================================
if [[ "$MODE" == "up" ]]; then
    if ! can_elevate; then
        echo "错误: --up 需要 root 或 sudo 权限" >&2
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
            # 已知道波特率 → down → 配置 → up
            $SUDO ip link set "$t" down 2>/dev/null || true
            if $SUDO ip link set "$t" type can bitrate "$br"; then
                $SUDO ip link set "$t" up
                echo "[UP]   $t (bitrate=$br)"
            else
                echo "[失败] $t: 设置 bitrate=$br 失败" >&2
                $SUDO ip link set "$t" type can bitrate "$br" || true
                rc=1
            fi
        else
            # 没有波特率 → 直接 up；若接口从未配过，内核会拒绝
            if $SUDO ip link set "$t" up 2>/dev/null; then
                cur=$(get_current_bitrate "$t")
                [[ -z "$cur" ]] && cur="?"
                echo "[UP]   $t (保持已有波特率=$cur)"
            else
                NEED_BITRATE+=("$t")
            fi
        fi
    done

    if [[ ${#MISSING_IF[@]} -gt 0 ]]; then
        echo >&2
        echo "以下接口不存在（请使用目标名）:" >&2
        for n in "${MISSING_IF[@]}"; do echo "  - $n" >&2; done
        rc=1
    fi

    if [[ ${#NEED_BITRATE[@]} -gt 0 ]]; then
        echo >&2
        echo "以下接口无法直接 up（通常是因为从未配置过波特率），" >&2
        echo "请在 MAPPING 值中加入 \":波特率\"，或用 --bitrate N 显式指定:" >&2
        for m in "${NEED_BITRATE[@]}"; do echo "  - $m" >&2; done
        rc=1
    fi

    exit $rc
fi
