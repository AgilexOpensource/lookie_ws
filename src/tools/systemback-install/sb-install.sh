#!/bin/bash
# ============================================================
#  Systemback 快速装机 · 一键版（通用）
#
#  用法（从 sblive U 盘启动后执行）：
#      sudo bash sb-install.sh                 # 自动探测目标盘
#      sudo bash sb-install.sh /dev/nvme0n1    # 手工指定目标盘
#
#  ★ 通用：不假定盘名、不假定分区布局、分区数量随意、ESP 不一定是 p1。
#    目标盘自动探测（只有一个候选就自动选中，多个就列出来让人选），
#    但一定打印 型号/容量/总线/现有内容，并要求手输大写 YES。
#
#  ★ 只支持 UEFI 固件。Legacy BIOS 会直接报错退出（理由见下）。
#
#  做的事（按目标盘当前状态自动裁剪）：
#    1. 前置检查 + 固件检查
#    2. 探测目标盘状态
#         - 已经完整解压过 → 【跳过格式化和解压】，只修引导（约 2 分钟）
#         - 其它情况       → 分区 + 格式化 + 解金镜像 + 修引导
#    3. 调 sb-01-prepare.sh  分区 + 格式化
#    4. 解金镜像（unsquashfs）
#    5. 调 sb-02-fixup.sh    fstab + 清 casper + 重置机器身份 + GRUB + 校验
#
#  ★ 全程不用 Systemback GUI。
#    所以也不受它「设备扫描写死了 sd*/hd*/vd*/mmcblk*、不认 nvme」那个 bug
#    影响，连二进制补丁都不需要。少一个会坏的东西。
#
#  ★ 金镜像取自启动 U 盘：/cdrom/casper/filesystem.squashfs
#    这就是做 U 盘时系统里的那份文件系统，Systemback 自己装系统也是解它。
#
#  ★ 跑完【不自动重启】，看完校验结果自己决定。
#
#  环境变量覆盖（手工兜底用）：
#    SB_DISK=/dev/xxx       指定目标盘（等价于第一个参数）
#    SB_SQUASHFS=/path      指定金镜像
#    SB_UNSQUASH_OPTS=...   unsquashfs 额外参数（默认 -no-progress）
# ============================================================
set -e

# ---------- 载入共享探测库 ----------
SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$SELF_DIR/sb-lib.sh" ]; then
    # shellcheck source=sb-lib.sh
    . "$SELF_DIR/sb-lib.sh"
else
    echo "!! 找不到 $SELF_DIR/sb-lib.sh"
    echo "!! sb-lib.sh 是共享探测库，必须和本脚本放在同一个目录里。"
    echo "!! （三个脚本 + sb-lib.sh，一共 4 个文件要一起拷）"
    exit 1
fi

SB01="$SELF_DIR/sb-01-prepare.sh"
SB02="$SELF_DIR/sb-02-fixup.sh"
TGT=/mnt/sb-install
PROBE=/mnt/sb-probe

# ---------- 0. 前置检查：文件 + 工具 ----------
echo "================ 一键装机 · 前置检查 ================"

for f in "$SB01" "$SB02" "$SELF_DIR/sb-lib.sh"; do
    if [ ! -f "$f" ]; then
        echo "!! 找不到 $f"
        echo "!! 四个文件（sb-install.sh / sb-01-prepare.sh / sb-02-fixup.sh / sb-lib.sh）"
        echo "!! 必须放在同一个目录里。"
        exit 1
    fi
done
echo "  脚本四件套 ............... ✓"

MISSING=""
for t in sgdisk mkfs.vfat mkswap mkfs.ext4 unsquashfs wipefs partprobe; do
    command -v "$t" >/dev/null 2>&1 || MISSING="$MISSING $t"
done
if [ -n "$MISSING" ]; then
    echo "!! 缺少工具：$MISSING"
    echo "!! 装一下：sudo apt install -y gdisk dosfstools util-linux squashfs-tools"
    exit 1
fi
echo "  sgdisk / mkfs / unsquashfs ✓"

if ! command -v efibootmgr >/dev/null 2>&1; then
    echo "  ⚠ 没有 efibootmgr —— 最后补写 UEFI 启动项那步会被跳过"
    echo "    （不影响安装，但可能需要在 BIOS 里手工把 NVMe 调到第一位）"
fi

# ---------- 1. 固件检查 ----------
# 目标系统只按 UEFI 方式装（grub-install --target=x86_64-efi）。
# 在 Legacy BIOS 下跑的话，装出来的系统根本起不来，而且不会报错 ——
# 所以这里必须【提前】硬拦住，别等到重启才发现。
echo
echo "================ 固件检查 ================"
FW=$(sb_firmware)
echo "  当前固件模式: $FW"
if [ "$FW" != "UEFI" ]; then
    cat << 'EOF'

!! 当前是 Legacy BIOS 模式，本脚本只支持 UEFI —— 已中止。

   原因：本流程固定按 UEFI 装（EFI 系统分区 + grub-install --target=x86_64-efi）。
        在 Legacy 下强行装，结果是一个既没有 MBR 引导代码、
        也没有可用 EFI 引导项的系统 —— 重启后【什么都起不来】。

   怎么改（在目标机上）：
     1. 重启，开机时按 Del / F2 / F12 进 BIOS 设置
     2. 关掉 CSM / Legacy Boot，把 Boot Mode 改成 UEFI Only
     3. 关掉 Secure Boot
     4. 启动顺序里选 UEFI 开头的那个 U 盘条目
        （★ 同一个 U 盘在列表里可能有两个条目，必须选带 "UEFI:" 前缀的）
     5. 存盘重启，再次从 U 盘进 Live 环境，重新跑本脚本

   验证方式：进 Live 后执行  ls /sys/firmware/efi
             有输出 = UEFI，报 "No such file" = 还是 Legacy

EOF
    exit 1
fi

# ---------- 2. 找金镜像 ----------
echo
echo "================ 金镜像 ================"
SQ="${SB_SQUASHFS:-}"
if [ -z "$SQ" ]; then
    SQ=$(sb_find_golden_image 2>/dev/null || true)
fi
if [ -z "$SQ" ] || [ ! -f "$SQ" ]; then
    echo "!! 找不到金镜像 filesystem.squashfs"
    echo "!! 正常情况下它应该在你启动 U 盘上的 /cdrom/casper/ 里。"
    echo "!! 确认你是从 sblive U 盘启动的（不是从硬盘启动）。"
    echo "!! 实在不行可以手工指定："
    echo "!!   sudo SB_SQUASHFS=/路径/filesystem.squashfs bash $0"
    exit 1
fi
SQ_SIZE=$(stat -c%s "$SQ")
echo "  $SQ"
echo "  $(numfmt --to=iec --suffix=B "$SQ_SIZE")"

# ---------- 3. 选定目标盘 ----------
echo
echo "================ 目标盘 ================"

# 校验：必须是整盘、不可移动、不是当前 Live 介质
# ★ 报错一律走 stderr —— stdout 是【返回值】（解析后的设备名），
#   混进提示文字会让调用方把错误信息当成盘名。
validate_disk() {
    local d="$1" dt tran rm live
    if [ ! -b "$d" ]; then echo "!! $d 不是块设备" >&2; return 1; fi
    d=$(readlink -f "$d")
    dt=$(lsblk -dno TYPE "$d" 2>/dev/null | tr -d '[:space:]')
    # ★ 仅用于沙箱回归测试：允许 loop 设备当目标盘。
    #   loop 设备不可能是真装机目标，所以这条不会削弱真机安全性。
    if [ "${SB_ALLOW_LOOP:-0}" = "1" ] && [ "$dt" = "loop" ]; then
        echo "$d"; return 0
    fi
    if [ "$dt" != "disk" ]; then
        echo "!! $d 不是整块磁盘（lsblk TYPE='$dt'），请传整盘设备名" >&2; return 1
    fi
    tran=$(lsblk -dno TRAN "$d" 2>/dev/null | tr -d '[:space:]')
    rm=$(lsblk -dno RM "$d" 2>/dev/null | tr -d '[:space:]')
    if [ "$tran" = "usb" ] || [ "$rm" = "1" ]; then
        echo "!! $d 是 U 盘 / 可移动设备，拒绝操作" >&2; return 1
    fi
    live=$(sb_live_disk 2>/dev/null || true)
    if [ -n "$live" ] && [ "$d" = "$live" ]; then
        echo "!! $d 是当前正在运行的 Live 介质，拒绝操作" >&2; return 1
    fi
    echo "$d"; return 0
}

DISK=""
WANT="${1:-${SB_DISK:-}}"

if [ -n "$WANT" ]; then
    echo "  手工指定：$WANT"
    if ! DISK=$(validate_disk "$WANT"); then exit 1; fi
else
    # 自动探测：整盘 + 不可移动 + 不是 Live 介质
    CANDS=$(sb_candidate_disks 2>/dev/null || true)
    NCAND=$(echo "$CANDS" | grep -c . || true)
    if [ "$NCAND" = "0" ]; then
        echo "!! 没有探测到任何可用的目标盘。"
        echo "!! 本机所有磁盘："
        lsblk -d -o NAME,SIZE,MODEL,TRAN,RM | sed 's/^/      /'
        echo "!! 全部磁盘都被判为「U 盘 / 可移动 / Live 介质」了。"
        echo "!! 确认目标盘已插好，或用参数手工指定："
        echo "!!   sudo bash $0 /dev/nvme0n1"
        exit 1
    elif [ "$NCAND" = "1" ]; then
        DISK="$CANDS"
        echo "  自动探测到 1 个候选盘，已选中"
    else
        echo "  探测到多个候选盘，请选择（输编号）："
        echo
        i=0
        for d in $CANDS; do
            i=$((i + 1))
            printf "    %d) %-16s %-8s %s\n" "$i" "$d" \
                "$(lsblk -dno SIZE "$d" | tr -d '[:space:]')" \
                "$(lsblk -dno MODEL "$d" | tr -s ' ' | sed 's/ *$//')"
        done
        echo
        printf "  编号 [1-%d]: " "$i"
        read -r sel || { echo "  已取消（无交互输入）"; exit 1; }
        case "$sel" in
            ''|*[!0-9]*) echo "  !! 输入的不是数字，已取消"; exit 1 ;;
            *) if [ "$sel" -lt 1 ] || [ "$sel" -gt "$i" ]; then
                   echo "  !! 编号超出范围，已取消"; exit 1
               fi ;;
        esac
        DISK=$(echo "$CANDS" | sed -n "${sel}p")
    fi
fi

if [ -z "$DISK" ]; then echo "!! 没能确定目标盘"; exit 1; fi

MODEL=$(lsblk -dno MODEL "$DISK" | tr -s ' ' | sed 's/ *$//')
DISK_SIZE=$(lsblk -dno SIZE "$DISK" | tr -d '[:space:]')
TRAN=$(lsblk -dno TRAN "$DISK" | tr -d '[:space:]')

# ---------- 4. 探测目标盘当前状态 ----------
# 决定是"只修引导"还是"从头装"，避免把已经拷好的 38G 白白重拷一遍。
echo
echo "================ 目标盘现状 ================"
echo "  设备 : $DISK"
echo "  型号 : ${MODEL:-（未知）}"
echo "  容量 : $DISK_SIZE"
echo "  总线 : $TRAN"
echo
echo "  盘上现有分区："
# ★ 不要用 PARTTYPENAME：util-linux 2.34 里是【未知列】，
#   报错却返回 0，被 2>/dev/null 吞掉后整个列表变空 —— 静默失灵。
#   而且操作员正靠这个列表确认"选对盘了没"，空了等于没有护栏。
LISTING=$(lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DISK" 2>/dev/null || true)
if [ -z "$LISTING" ]; then
    # 再兜一层：万一某个列名在这台机器上不被支持
    LISTING=$(lsblk -o NAME,SIZE "$DISK" 2>/dev/null || true)
fi
echo "${LISTING:-      （读不出分区信息，请人工确认：lsblk $DISK）}" | sed 's/^/      /'

ROOT_D=""
COMPLETE=0
SCORE=0
mkdir -p "$PROBE"
ROOT_D=$(sb_find_root "$DISK" "$PROBE" 2>/dev/null || true)
if [ -n "$ROOT_D" ]; then
    if mount "$ROOT_D" "$PROBE" 2>/dev/null; then
        SCORE=$(sb_score_root "$PROBE")
        if sb_extract_complete "$PROBE" "$SQ"; then COMPLETE=1; fi
        umount "$PROBE" 2>/dev/null || true
    else
        echo "  ⚠ $ROOT_D 挂不上，当作没有系统处理"
        ROOT_D=""
    fi
fi

NEED_PREP=1
NEED_EXTRACT=1
if [ -n "$ROOT_D" ] && [ "$COMPLETE" = "1" ]; then
    NEED_PREP=0
    NEED_EXTRACT=0
fi

ESP_D=$(sb_find_esp  "$DISK" 2>/dev/null || true)
SWAP_D=$(sb_find_swap "$DISK" 2>/dev/null || true)
echo "  探测结果："
echo "      ESP  : ${ESP_D:-（无）}"
echo "      swap : ${SWAP_D:-（无）}"
echo "      根   : ${ROOT_D:-（无）}"

echo
if [ "$NEED_PREP" = "0" ]; then
    echo "  状态 : 【已完整解压过】$ROOT_D 上有完整的系统（判据分 $SCORE）"
    echo "         → 跳过 分区/格式化/解压，只做修引导（约 2 分钟）"
elif [ -n "$ROOT_D" ]; then
    echo "  状态 : $ROOT_D 上有系统，但【解压不完整】（判据分 $SCORE）"
    echo "         → 会重新分区、格式化，整份重装"
else
    echo "  状态 : 没有探测到已安装的系统"
    echo "         → 会分区、格式化，整份重装"
fi

# ---------- 5. 强确认 ----------
echo
echo "############################################################"
if [ "$NEED_PREP" = "1" ]; then
    echo "#  ⚠ 即将【清空】$DISK 的全部分区，并把金镜像整份解上去"
else
    echo "#  ✓ $DISK 上已有完整系统，本次【不清空、不重拷】，只修引导"
fi
echo "############################################################"
echo
echo "  目标盘 : $DISK"
echo "  型号   : ${MODEL:-（未知）}"
echo "  容量   : $DISK_SIZE"
echo "  总线   : $TRAN"
echo "  根分区 : ${ROOT_D:-（本次会新建）}"
echo "  金镜像 : $SQ"
echo
echo ">>> 确认无误请输入大写 YES 再回车（其它任何输入都会中止）："
read -r ans || { echo "  已取消（无交互输入）"; exit 1; }
if [ "$ans" != "YES" ]; then echo "  已取消"; exit 1; fi

# ---------- 6. 分区 + 格式化 ----------
if [ "$NEED_PREP" = "1" ]; then
    echo
    echo "############################################################"
    echo "#  第 1 步：分区 + 格式化（sb-01-prepare.sh）"
    echo "############################################################"
    SB_NO_GUI_HINT=1 bash "$SB01" "$DISK"

    # sb-01 会自己再问一次 YES 并重跑它那套安全检查 —— 这是故意的：
    # 那套护栏（拒绝 U 盘 / 拒绝运行中的系统盘）比这里的更细，不能绕过。

    # 分区建好后重新定位根（刚格式化、还是空的，靠"ext4 且非 ESP/swap"判据）
    ESP_D=$(sb_find_esp  "$DISK" 2>/dev/null || true)
    SWAP_D=$(sb_find_swap "$DISK" 2>/dev/null || true)
    ROOT_D=""
    for p in $(sb_list_partitions "$DISK"); do
        if [ "$p" = "$ESP_D" ] || [ "$p" = "$SWAP_D" ]; then continue; fi
        if [ "$(sb_fstype "$p")" = "ext4" ]; then ROOT_D="$p"; break; fi
    done
    if [ -z "$ROOT_D" ]; then
        echo "!! 分区完成了，但找不到 ext4 根分区 —— 分区可能没成功"
        lsblk -f "$DISK" | sed 's/^/      /'
        exit 1
    fi
    echo
    echo "  根分区：$ROOT_D"
fi

# ---------- 7. 解金镜像 ----------
if [ "$NEED_EXTRACT" = "1" ]; then
    echo
    echo "############################################################"
    echo "#  第 2 步：把金镜像解到 $ROOT_D"
    echo "############################################################"

    if mountpoint -q "$TGT"; then umount -R "$TGT" 2>/dev/null || true; fi
    mkdir -p "$TGT"
    mount "$ROOT_D" "$TGT"

    # 目标盘上刚建好的 ext4 只有 lost+found，-f 让 unsquashfs 直接往里写
    echo
    echo "  开始解压（$(numfmt --to=iec --suffix=B "$SQ_SIZE") 的 squashfs，"
    echo "  大概要 10~25 分钟，看盘的速度）。进度由 unsquashfs 自己打印："
    echo
    T0=$(date +%s)
    # shellcheck disable=SC2086
    unsquashfs -f -d "$TGT" ${SB_UNSQUASH_OPTS:--no-progress} "$SQ"
    T1=$(date +%s)
    echo
    echo "  解压完成，用时 $(( (T1 - T0) / 60 )) 分 $(( (T1 - T0) % 60 )) 秒"

    echo
    echo "  已落到目标盘上的顶层目录："
    ls -1 "$TGT" | head -30 | sed 's/^/      /'
    echo "      ... 共 $(ls -1 "$TGT" | wc -l) 项"

    # 完整性自检：哨兵文件 + inode 数比对
    if ! sb_extract_complete "$TGT" "$SQ"; then
        echo
        echo "!! 解压结果不完整（哨兵文件缺失 或 inode 数对不上）—— 先别重启"
        echo "!! 请把上面的输出发出来"
        umount "$TGT" 2>/dev/null || true
        exit 1
    fi
    echo "  完整性自检 ............... ✓"

    # 落一个自己的标记，下次再跑本脚本可以秒判"已完整"
    touch "$TGT/.sb-extract-done"

    sync
    umount "$TGT"
    echo "  已卸载 $TGT"
else
    echo
    echo "############################################################"
    echo "#  第 2 步：跳过解压（$ROOT_D 上已有完整系统）"
    echo "############################################################"
fi

# ---------- 8. 修引导 + 重置机器身份 ----------
echo
echo "############################################################"
echo "#  第 3 步：修引导（sb-02-fixup.sh）"
echo "############################################################"
echo "#  fstab 改成真 UUID、清 casper、重置 machine-id 和 SSH host key、"
echo "#  装 GRUB、重建 initrd、把 T500 缓解参数写进 grub.cfg、"
echo "#  写 UEFI 启动项，最后 5 项校验。"
echo "#  （会自己再问一次确认，它也有自己那套安全检查）"
echo
bash "$SB02" "$DISK"

# ---------- 收尾 ----------
echo
cat << EOF
############################################################
#  一键装机完成
############################################################

 目标盘     : $DISK
 根分区     : $ROOT_D
 金镜像     : $SQ
 本次动作   : $(if [ "$NEED_PREP" = "1" ]; then echo "重新分区 + 格式化 + 解压 + 修引导"; else echo "仅修引导（保留了盘上已有系统）"; fi)

############################################################
#  ⚠ 关机/重启【不要用 reboot】
############################################################

 这块 Crucial T500（CT2000T500SSD8，固件 P8CR004）有已知固件缺陷：
 **软重启后 BIOS 认不到盘** —— 会看起来像"装坏了"，其实是盘没被识别。

 请这样做：
     1. 长按电源键 5 秒关机（或直接拔电）
     2. 等 5 秒以上，再开机
     3. 进 BIOS，把 NVMe 调到启动顺序第一位（或开机时按启动菜单键选它）
     4. 拔掉 U 盘

 ★ 刚才的修复已经把缓解参数（nvme_core.default_ps_max_latency_us=0
   pcie_aspm=off）写进了目标系统的 grub.cfg —— 校验项 [5] 就是查这个。
   它能保证【以后每次开机】都不容易再犯。

 ★ 但【这一次】是从 Live 环境发起的重启，走的是 Live 内核的状态，
   那些参数还管不着。所以这一次务必断电，别敲 reboot。

 详见文档「附 E」。

 ★ 第一次开机时系统会自动生成新的 machine-id —— 这是正常的。
EOF
