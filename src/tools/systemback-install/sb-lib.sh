#!/bin/bash
# ============================================================
#  Systemback 快速装机 · 共享探测库
#
#  被 sb-01-prepare.sh / sb-02-fixup.sh / sb-install.sh 三处 source。
#  目的：让脚本【不依赖固定的盘名和分区布局】—— 任意电脑都能用。
#
#  ★ 这里每一条探测原语都在真机上实测过，反面教材也记在注释里，
#    别用"看起来更直观"的写法替回去（有几个会静默失灵）。
#
#  依赖：lsblk / blkid / findmnt / mount / unsquashfs
# ============================================================

# GPT 分区类型 GUID（小写比较）
SB_GUID_ESP="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"     # EFI System
SB_GUID_SWAP="0657fd6d-a4ab-43c4-84e5-0933c84b4f4f"    # Linux swap
SB_GUID_LINUX="0fc63daf-8483-4772-8e79-3d69d8477de4"   # Linux filesystem

# ------------------------------------------------------------
# 固件模式：UEFI / BIOS
# ------------------------------------------------------------
sb_firmware() {
    if [ -d /sys/firmware/efi ]; then echo "UEFI"; else echo "BIOS"; fi
}

# ------------------------------------------------------------
# 设备 → 它所属的【物理整盘】
#   /dev/nvme0n1p3      -> /dev/nvme0n1
#   /dev/sda2           -> /dev/sda
#   /dev/mapper/ventoy  -> /dev/sda      ★ 关键：dm 节点要穿透
#
# 为什么必须穿透 dm：Live U 盘的 /cdrom 挂的是 /dev/mapper/ventoy，
# 【不是】分区。lsblk -s 对 dm 节点直接报 "not a block device"。
# 不穿透的话，"选唯一的内置盘"这类启发式可能选中正在运行的 U 盘并抹掉它。
#
# 实现走 /sys/class/block/<dev>/partition 和 .../slaves 递归。
# ------------------------------------------------------------
sb_phys_disk() {
    local dev="$1" mm
    [ -n "$dev" ] || return 1
    # 已经给了 maj:min 就直用
    case "$dev" in
        [0-9]*:[0-9]*) sb_phys_disk_mm "$dev"; return $? ;;
    esac
    # 从设备路径取 maj:min。
    # ★ 不能靠 readlink -f / basename 解析名字 —— 实测在 Live 环境里
    #   /dev/mapper/ventoy 这个【节点根本不存在】（/dev/mapper/ 下只有 control），
    #   但 findmnt 照样把 "/dev/mapper/ventoy" 当 SOURCE 报出来。
    #   对它调 lsblk 会得到 "not a block device"。只有 maj:min 是可靠的。
    # ★ 必须裁掉空白：lsblk 输出带尾随空格（"259:0  "），
    #   不裁的话 /sys/dev/block/259:0␣␣ 不存在，函数静默失败。
    mm=$(lsblk -dno MAJ:MIN "$dev" 2>/dev/null | head -1 | tr -d '[:space:]')
    [ -n "$mm" ] || return 1
    sb_phys_disk_mm "$mm"
}

# 从 maj:min 出发，沿 /sys 走到物理整盘
#   252:0 (dm-0) -> slaves sda1 -> sda
#   259:3 (nvme0n1p3) -> 上级 nvme0n1
sb_phys_disk_mm() {
    local mm="$1" b i=0
    mm=$(printf '%s' "$mm" | tr -d '[:space:]')
    [ -n "$mm" ] || return 1
    [ -e "/sys/dev/block/$mm" ] || return 1
    b=$(basename "$(readlink -f "/sys/dev/block/$mm")")
    while [ "$i" -lt 10 ]; do
        i=$((i + 1))
        if [ -e "/sys/class/block/$b/partition" ]; then
            # 是分区 → 上一级是它的整盘
            b=$(basename "$(dirname "$(readlink -f "/sys/class/block/$b")")")
        elif [ -d "/sys/class/block/$b/slaves" ] && [ -n "$(ls -A "/sys/class/block/$b/slaves" 2>/dev/null)" ]; then
            # 是 dm/md 之类的映射设备 → 跟随它的底层
            b=$(basename "$(ls "/sys/class/block/$b/slaves" 2>/dev/null | head -1)")
        else
            break
        fi
    done
    # 只认真实块设备，避免把 /cow 这类非块设备解析成 "/dev/cow"
    if [ -b "/dev/$b" ]; then echo "/dev/$b"; return 0; fi
    return 1
}

# ------------------------------------------------------------
# 整盘的【所有】分区（任意个数、任意命名）
#   nvme0n1 -> nvme0n1p1..pN     sda -> sda1..N     mmcblk0 -> mmcblk0p1..N
#
# ★ 必须按 TYPE=="part" 过滤。Live 机器上有 17 个 loop 设备（snap 挂载的），
#   不过滤就会把它们全当成目标盘的分区。
# ------------------------------------------------------------
sb_list_partitions() {
    lsblk -rpno NAME,TYPE "$1" 2>/dev/null | awk '$2=="part"{print $1}'
}

# ------------------------------------------------------------
# 单个分区的 GPT 类型（小写）。MBR 盘返回 "0xNN"。
#
# ★ 必须用 lsblk 的 PARTTYPE。
#   blkid -o value -s PART_ENTRY_TYPE 在本批机器上【返回空】—— 看着能用，
#   实际静默失灵，用它写出来的判据会让所有分区都匹配不上。
# ★ 必须加 -r。不加的话 lsblk 会打印树形字符（├─ / └─）污染字段。
# ------------------------------------------------------------
sb_parttype() {
    lsblk -rno PARTTYPE "$1" 2>/dev/null | head -1 | tr 'A-Z' 'a-z'
}

sb_fstype() {
    blkid -s TYPE -o value "$1" 2>/dev/null | head -1
}

# ------------------------------------------------------------
# 找 ESP（EFI 系统分区）
# 判据依次：GPT 类型 EF00 → MBR 类型 0xef → parted 的 boot,esp 标志 → vfat 兜底
# ------------------------------------------------------------
sb_find_esp() {
    local disk="$1" p t
    for p in $(sb_list_partitions "$disk"); do
        t=$(sb_parttype "$p")
        case "$t" in
            "$SB_GUID_ESP"|0xef) echo "$p"; return 0 ;;
        esac
    done
    # 兜底 1：GPT 类型字段缺失时看 parted 标志
    if command -v parted >/dev/null 2>&1; then
        local n
        n=$(parted -sm "$disk" unit s print 2>/dev/null \
            | awk -F: '$NF ~ /esp/ {print $1; exit}')
        if [ -n "$n" ]; then echo "${disk}${n}"; return 0; fi
    fi
    # 兜底 2：vfat 且不是任何已知的非 ESP 类型
    for p in $(sb_list_partitions "$disk"); do
        [ "$(sb_fstype "$p")" = "vfat" ] && { echo "$p"; return 0; }
    done
    return 1
}

# ------------------------------------------------------------
# 找 swap
# ★ 不能拿 swapon --show 当数据源 —— 装机时目标盘的 swap 根本没启用，永远是空的。
# ------------------------------------------------------------
sb_find_swap() {
    local disk="$1" p t
    for p in $(sb_list_partitions "$disk"); do
        t=$(sb_parttype "$p")
        case "$t" in
            "$SB_GUID_SWAP"|0x82) echo "$p"; return 0 ;;
        esac
    done
    for p in $(sb_list_partitions "$disk"); do
        [ "$(sb_fstype "$p")" = "swap" ] && { echo "$p"; return 0; }
    done
    return 1
}

# ------------------------------------------------------------
# 这个分区像个"系统根"吗？打分
#   0 = 不像
#   1 = 有 /usr/bin + /etc + 内核
#   2 = 再加 /etc/fstab
#   3 = 再加 /etc/hostname
#
# ★ 判据【不能】要求 /etc/fstab 存在。Systemback 装到一半停住时会把原 fstab
#   挪进 .systemback/etc/fstab，目标盘上反而没有 —— 而那恰恰是最需要被救的场景。
#   调用方记得先 mount 再调本函数。
# ------------------------------------------------------------
sb_score_root() {
    local mnt="$1" s=0
    if [ -d "$mnt/usr/bin" ] && [ -d "$mnt/etc" ] \
       && { ls "$mnt"/boot/vmlinuz* >/dev/null 2>&1 || [ -e "$mnt/boot/vmlinuz" ]; }; then
        s=1
    else
        echo 0; return 0
    fi
    [ -f "$mnt/etc/fstab" ]    && s=$((s + 1))
    [ -f "$mnt/etc/hostname" ] && s=$((s + 1))
    echo "$s"
}

# ------------------------------------------------------------
# 找系统根分区：扫整盘所有分区（跳过 ESP 和 swap），按上面的分数取最高
# 同分时保留先遇到的（分区号小的优先）
# 回显设备名；找不到返回 1
# ------------------------------------------------------------
sb_find_root() {
    local disk="$1" mnt="$2"
    local p esp best="" bestscore=0 sc
    esp=$(sb_find_esp "$disk" 2>/dev/null || true)
    for p in $(sb_list_partitions "$disk"); do
        [ -n "$esp" ] && [ "$p" = "$esp" ] && continue
        case "$(sb_parttype "$p")" in "$SB_GUID_SWAP"|0x82) continue ;; esac
        [ "$(sb_fstype "$p")" = "swap" ] && continue
        [ -b "$p" ] || continue
        mount "$p" "$mnt" 2>/dev/null || continue
        sc=$(sb_score_root "$mnt")
        umount "$mnt" 2>/dev/null || true
        if [ "$sc" -gt "$bestscore" ]; then bestscore="$sc"; best="$p"; fi
    done
    [ -n "$best" ] && { echo "$best"; return 0; }
    return 1
}

# ------------------------------------------------------------
# 当前正在运行的 Live 介质所在的【物理整盘】
# 用来把它从候选目标里排除掉 —— 万一选错就是把正在跑的 U 盘抹了
# ------------------------------------------------------------
sb_live_disk() {
    local src m d
    for m in /cdrom /rofs /lib/live/mount/medium /isodevice /run/live/medium; do
        # ★ 必须确认它【真的是个挂载点】。
        #   普通 Ubuntu 上 /cdrom 是 casper 建的一个【空目录】，不是挂载点。
        #   此时 findmnt --target /cdrom 会一路回溯到 / 所在的文件系统，
        #   返回本机根盘 —— 于是 sb_candidate_disks 会把真正的目标盘当成
        #   "Live 介质"排除掉，候选列表变空。
        #   （--target 对不存在的路径会报错，但对存在的普通目录会静默回溯。）
        [ -d "$m" ] || continue
        mountpoint -q "$m" || continue
        # ★ 这里必须用 MAJ:MIN 而不是 SOURCE。
        #   /cdrom 的 SOURCE 是 "/dev/mapper/ventoy"，但那个节点在 Live 环境里
        #   根本不存在（/dev/mapper/ 下只有 control），拿它去 lsblk 会得到
        #   "not a block device"。maj:min 是唯一始终可靠的标识。
        src=$(findmnt -n -o MAJ:MIN --mountpoint "$m" 2>/dev/null | head -1 | tr -d '[:space:]')
        [ -n "$src" ] || continue
        d=$(sb_phys_disk_mm "$src") || continue
        # ★ 还要跳过 loop/ram —— /rofs 是 squashfs 的 loop 映射，
        #   它不是"介质"本身。真正的介质是 /cdrom 背后的 USB 整盘。
        case "$d" in /dev/loop*|/dev/ram*|/dev/zram*) continue ;; esac
        echo "$d"; return 0
    done
    return 1
}

# ------------------------------------------------------------
# 候选目标盘：整盘 + 不可移动 + 不是 Live 介质 + 不是 loop/zram 之类
#             + 不是【当前正在运行的系统】所在的盘
#
# ★ 最后那条是兜底：本脚本本该在 Live 环境跑，那儿 / 是 overlay，
#   解析不出块设备，这条自然不生效。但万一有人在装好的系统上直接跑，
#   没有这条就会把运行中的系统盘当成"唯一候选"选出来。
# ------------------------------------------------------------
sb_candidate_disks() {
    local live rootd d rootmm
    live=$(sb_live_disk 2>/dev/null || true)
    # 当前 / 所在的物理盘（Live 环境下是 overlay，解析失败 → 为空，不排除任何东西）
    rootmm=$(findmnt -n -o MAJ:MIN --target / 2>/dev/null | head -1 | tr -d '[:space:]')
    rootd=""
    [ -n "$rootmm" ] && rootd=$(sb_phys_disk_mm "$rootmm" 2>/dev/null || true)
    while read -r d; do
        [ -n "$d" ] || continue
        case "$d" in /dev/loop*|/dev/ram*|/dev/zram*|/dev/sr*) continue ;; esac
        [ -n "$live" ]  && [ "$d" = "$live" ]  && continue
        [ -n "$rootd" ] && [ "$d" = "$rootd" ] && continue
        echo "$d"
    done < <(lsblk -dpno NAME,TYPE,RM 2>/dev/null | awk '$2=="disk" && $3=="0"{print $1}')
}

# ------------------------------------------------------------
# 找金镜像 filesystem.squashfs
# ------------------------------------------------------------
sb_find_golden_image() {
    local c m
    for c in /cdrom/casper/filesystem.squashfs \
             /lib/live/mount/medium/live/filesystem.squashfs \
             /run/live/medium/live/filesystem.squashfs \
             /isodevice/casper/filesystem.squashfs; do
        [ -f "$c" ] && { echo "$c"; return 0; }
    done
    # 兜底：在已知的 Live 介质挂载点下有界搜索
    for m in /cdrom /lib/live/mount/medium /run/live/medium /isodevice /media; do
        [ -d "$m" ] || continue
        c=$(find "$m" -maxdepth 4 -name filesystem.squashfs -type f 2>/dev/null | head -1)
        [ -n "$c" ] && { echo "$c"; return 0; }
    done
    return 1
}

# ------------------------------------------------------------
# 目标盘上的系统是否【已经完整解压】
# 判据：sentinel 文件 + inode 数比对（O(1)，不用遍历 46 万项）
#
# 为什么需要它：装到一半的机器（文件拷完但没落地）和装完的机器，
# 修复动作是一样的，但【重拷 38G 要 20 分钟】。能跳过就跳过。
# ------------------------------------------------------------
sb_extract_complete() {
    local mnt="$1" sq="$2" f want got
    # 1) 哨兵：只有解压完成才会同时存在的路径
    for f in usr/bin/bash usr/lib/systemd/systemd etc/passwd usr/sbin/grub-install; do
        [ -e "$mnt/$f" ] || return 1
    done
    ls "$mnt"/boot/vmlinuz* >/dev/null 2>&1 || [ -e "$mnt/boot/vmlinuz" ] || return 1

    # 2) 我们自己写的 marker（解压成功时落下），有就秒过
    [ -f "$mnt/.sb-extract-done" ] && return 0

    # 3) inode 数比对
    [ -f "$sq" ] || return 0        # 拿不到金镜像就信哨兵
    want=$(unsquashfs -s "$sq" 2>/dev/null | awk '/Number of inodes/{print $4}')
    [ -n "$want" ] || return 0
    # ★ 注意：df 的 -i 和 --output 是【互斥】的，不能写成 `df -i --output=iused`
    #   （会报错，got 为空，于是这一整段静默失效、只剩哨兵在起作用）。
    got=$(df --output=iused "$mnt" 2>/dev/null | tail -1 | tr -d ' ')
    [ -n "$got" ] || return 0
    # 实测 df -i 会比 squashfs 的 inode 数略高（保留 inode），所以留 0.1% 余量
    [ "$got" -ge $((want - want / 1000)) ]
}
