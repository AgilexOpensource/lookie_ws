#!/bin/bash
# ============================================================
#  Systemback 快速装机 · 第 1 步：分区 + 格式化
#
#  用法（在 Live 环境里执行）：
#      sudo bash sb-01-prepare.sh /dev/nvme0n1
#
#  ★ 必须显式指定目标整盘设备名，没有默认值。
#    （默认值 + 目标机系统盘恰好同名 = 一条 sudo 抹掉正在跑的系统）
#
#  布局：512M ESP(vfat) + 32G swap + 剩余全部 ext4 根
#
#  步骤：0 清场 → 1 重建分区表 → 2 建文件系统 → 3 给 Systemback 打 NVMe 补丁
#
#  ★ 步骤 3 说明：Systemback 1.8.402 的设备扫描写死了 /dev/sd* /dev/hd*
#    /dev/vd* /dev/mmcblk* 这四种命名，**不认识 nvme**（二进制里 "nvme"
#    出现 0 次）—— 所以 NVMe 目标盘在 GUI 里一条都看不到，和分区/文件
#    系统/挂载状态统统无关。
#
#    实测：给它造 /dev/sdX 符号链接【没用】。Systemback 会对每个 glob 出来
#    的名字调 readlink()，一旦发现是链接就换成解析出来的真名，照样回到
#    nvme0n1 —— 结果只能列出整盘一行，分区行永远不出现。
#
#    唯一管用的办法是把过滤器改掉：hd*（IDE 盘，2010 年后绝迹）改成 nv*。
#    等长替换（8→8 字节），文件大小不变，目标模式恰好 1 处。脚本自动做，
#    并先备份到 /var/tmp，随时可回滚。
#
#    ★ 补丁只活在本次 Live 会话（根是 overlay，重启即丢），
#      所以每次装机都要重跑本脚本。
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

# ---------- 参数：必须显式指定目标整盘 ----------
if [ -z "$1" ]; then
    echo "用法: sudo bash $(basename "$0") <整盘设备名>"
    echo "例如: sudo bash $(basename "$0") /dev/nvme0n1"
    echo
    echo "本机现有磁盘（TRAN=usb / RM=1 的是启动 U 盘，不要选）："
    lsblk -d -o NAME,SIZE,MODEL,TRAN,RM
    echo
    echo "!! 本脚本拒绝使用默认盘 —— 目标必须由你明确指定"
    exit 1
fi
DISK="$1"

# ★ 可用 SB_ESP_SIZE / SB_SWAP_SIZE 覆盖（盘小的机器要把 swap 调小）
ESP_SIZE="${SB_ESP_SIZE:-+512M}"
SWAP_SIZE="${SB_SWAP_SIZE:-+32G}"

# ---------- 分区名后缀：nvme0n1 -> p1，sda -> 1 ----------
case "$DISK" in
  *[0-9]) PART="${DISK}p" ;;
  *)      PART="${DISK}"  ;;
esac
P1="${PART}1"; P2="${PART}2"; P3="${PART}3"

# ---------- 设备 → 它所属的整块磁盘 ----------
# 实现搬到 sb-lib.sh 的 sb_phys_disk（能穿透 dm/md 等映射设备）。
# 这里保留同名薄封装，免得改动调用点。
whole_disk() {
    sb_phys_disk "$1"
}

# ---------- 安全检查 ----------
echo "================ 目标盘检查 ================"
[ -b "$DISK" ] || { echo "!! $DISK 不存在，中止"; exit 1; }
DISK=$(readlink -f "$DISK")

MODEL=$(lsblk -dno MODEL "$DISK" | tr -s ' ' | sed 's/ *$//')
TRAN=$(lsblk -dno TRAN "$DISK")
RM=$(lsblk -dno RM "$DISK")
echo "  设备 : $DISK"
echo "  型号 : $MODEL"
echo "  容量 : $(lsblk -dno SIZE "$DISK")"
echo "  总线 : $TRAN    可移动: $RM"

# ★ 容量下限：本流程是 512M ESP + 32G swap，剩下给根。
#   不提前拦的话，sgdisk 会在第 2 个分区上报一句很难懂的错。
#   把 "+512M" / "+32G" 这种 sgdisk 写法换算成 MB
size_to_mb() {
    local v="$1" u n
    v="${v#+}"
    u="${v: -1}"
    n="${v%?}"
    case "$u" in
        [Mm]) echo $(( n )) ;;
        [Gg]) echo $(( n * 1024 )) ;;
        [Tt]) echo $(( n * 1024 * 1024 )) ;;
        *)    return 1 ;;
    esac
}
DSZ=$(lsblk -bdno SIZE "$DISK" 2>/dev/null | tr -d '[:space:]')
if [ -n "$DSZ" ]; then
    ESP_MB=$(size_to_mb "$ESP_SIZE"  || echo 512)
    SWAP_MB=$(size_to_mb "$SWAP_SIZE" || echo 32768)
    MIN=$(( (ESP_MB + SWAP_MB + 8192) * 1024 * 1024 ))   # 再留给根至少 8G
    if [ "$DSZ" -lt "$MIN" ]; then
        echo
        echo "!! $DISK 容量 $(numfmt --to=iec --suffix=B "$DSZ")，小于本流程要求的"
        echo "!! $(numfmt --to=iec --suffix=B "$MIN")（${ESP_MB}M ESP + ${SWAP_MB}M swap + 至少 8G 根）"
        echo "!! 盘太小，装不下 —— 金镜像解压后要 38G 左右。"
        echo "!! 确实要用它，可以把 swap 调小后重试："
        echo "!!   sudo SB_SWAP_SIZE=+8G bash $(basename "$0") $DISK"
        exit 1
    fi
fi

if [ "$TRAN" = "usb" ] || [ "$RM" = "1" ]; then
    echo "!! $DISK 是 U 盘 / 可移动设备，拒绝操作（这是启动盘）"
    exit 1
fi

DTYPE=$(lsblk -dno TYPE "$DISK" 2>/dev/null)
if [ "$DTYPE" != "disk" ]; then
    echo "!! $DISK 不是整块磁盘（lsblk TYPE='$DTYPE'）"
    echo "!! 请传整盘设备名，例如 /dev/nvme0n1 而不是 /dev/nvme0n1p1"
    exit 1
fi

# ---------- ★ 拒绝操作「当前正在运行的系统」所在的盘 ----------
LIVE=""
r=$(whole_disk "$(findmnt -n -o SOURCE -T / 2>/dev/null | head -1)" || true)
if [ -n "$r" ] && [ "$r" = "$DISK" ]; then LIVE="/"; fi

for m in /boot /boot/efi /usr; do
    s=$(findmnt -n -o SOURCE -T "$m" 2>/dev/null | head -1)
    if [ -n "$s" ]; then
        r=$(whole_disk "$s" || true)
        if [ "$r" = "$DISK" ]; then LIVE="$LIVE $m"; fi
    fi
done

for sw in $(swapon --show=NAME --noheadings 2>/dev/null || true); do
    r=$(whole_disk "$sw" || true)
    if [ "$r" = "$DISK" ]; then LIVE="$LIVE $sw(swap)"; fi
done

if [ -n "$LIVE" ]; then
    echo
    echo "!! 拒绝操作：$DISK 上正运行着当前系统（$LIVE）"
    echo "!! 你很可能在对着自己的系统盘跑这个脚本 —— 这是不可恢复的。"
    echo "!! 请从 Live U 盘启动后再执行，并确认目标盘未被挂载。"
    exit 1
fi

echo
echo "================ 系统里所有磁盘 ================"
lsblk -d -o NAME,SIZE,MODEL,TRAN,RM

echo
echo ">>> 即将【清空】$DISK 的全部分区！盘上现有内容："
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DISK" | sed 's/^/    /'
echo
echo ">>> 确认无误请输入大写 YES 再回车（其它任何输入都会中止）："
read -r ans || { echo "  已取消（无交互输入）"; exit 1; }
if [ "$ans" != "YES" ]; then echo "  已取消"; exit 1; fi

# ---------- 步骤 0：清场 ----------
echo
echo "================ 步骤 0：清场 ================"
swapoff -a 2>/dev/null || true
for i in 1 2 3 4 5 6 7 8; do
    umount "${PART}${i}" 2>/dev/null || true
done
mount | grep -E "$(basename "$DISK")" || echo "  (无挂载，干净)"

# 关掉 GNOME 自动挂载（如果在桌面会话里）
if command -v gsettings >/dev/null 2>&1; then
    U=$(logname 2>/dev/null || echo "")
    if [ -n "$U" ]; then
        su - "$U" -c "gsettings set org.gnome.desktop.media-handling automount false" 2>/dev/null || true
        su - "$U" -c "gsettings set org.gnome.desktop.media-handling automount-open false" 2>/dev/null || true
    fi
fi

# ---------- 步骤 1：重建分区表 ----------
echo
echo "================ 步骤 1：重建分区表 ================"
sgdisk -Z "$DISK" >/dev/null
sgdisk -o  "$DISK" >/dev/null
sgdisk -n 1:2048:$ESP_SIZE -t 1:ef00 -c 1:"EFI"  "$DISK"
sgdisk -n 2:0:$SWAP_SIZE   -t 2:8200 -c 2:"SWAP" "$DISK"
sgdisk -n 3:0:0            -t 3:8300 -c 3:"ROOT" "$DISK"
partprobe "$DISK" 2>/dev/null || true
sleep 3

sgdisk -p "$DISK" | tail -5

# ---------- 步骤 2：建文件系统 ----------
echo
echo "================ 步骤 2：建文件系统 ================"
for x in "$P1" "$P2" "$P3"; do
    [ -b "$x" ] || { echo "!! $x 不存在，分区可能失败"; exit 1; }
    wipefs -a "$x" >/dev/null 2>&1 || true
done
sync

echo "--- ESP (vfat) ---"
mkfs.vfat -F 32 -n EFI "$P1"
echo "--- swap ---"
mkswap -L SWAP "$P2"
echo "--- root (ext4, 跳过全盘 TRIM) ---"
mkfs.ext4 -F -E nodiscard -L SB@ "$P3"
sync

# ---------- 步骤 3：给 Systemback 打 NVMe 补丁 ----------
# Systemback 1.8.402（2016 年编译）的设备扫描只 glob 这四种命名：
#     /dev/sd*   /dev/hd*   /dev/vd*   /dev/mmcblk*
# 实测 libsystemback.so.1.0.0 里 "nvme" 出现 0 次 —— NVMe 压根不在扫描范围内，
# 所以 GUI 的分区设置页里【一条 nvme 分区都不会出现】，和分区/文件系统/挂载状态无关。
#
# 造 /dev/sdX 符号链接【不管用】：Systemback 会对每个 glob 出来的名字调
# readlink()，是链接就换成解析出来的真名（nvme0n1），照样回到它不认识的名字上。
# 实测整份 strace 里 /dev/sdd1 出现 0 次 —— 只能列出整盘一行，分区行永远没有。
#
# 真正的办法：hd*（IDE 盘，2010 年后绝迹）占着槽位没用，改成 nv*。
# 等长替换，文件大小不变。改完 /dev/nvme0n1 是真实块设备节点，readlink() 返回
# EINVAL，名字原样保留，走的就是和 sda 完全一样的代码路径。
echo
echo "================ 步骤 3：给 Systemback 打 NVMe 补丁 ================"
SBLIB="/usr/lib/systemback/libsystemback.so.1.0.0"
SBBACK="/var/tmp/libsystemback.so.1.0.0.orig"

if [ ! -f "$SBLIB" ]; then
    echo "  !! 找不到 $SBLIB —— 这台机器装 systemback 了吗？"
    echo "  !! 没装的话 GUI 也打不开，先装 systemback 再重跑本脚本。"
else
    if python3 - "$SBLIB" "$SBBACK" <<'PYEOF'
import os, shutil, sys
lib, back = sys.argv[1], sys.argv[2]
old, new = b"/dev/hd*", b"/dev/nv*"
d = open(lib, "rb").read()

if d.count(new) == 1 and d.count(old) == 0:
    print("  已经打过了，跳过（幂等）")
    sys.exit(0)

if d.count(old) != 1:
    print("  !! 在库里找到 %d 处 %s，预期恰好 1 处" % (d.count(old), old.decode()))
    print("  !! 版本可能不是 1.8.402 —— 不动它，避免写坏。")
    sys.exit(1)

if len(old) != len(new):
    print("  !! 新旧字符串不等长，拒绝替换")
    sys.exit(1)

if not os.path.exists(back):
    shutil.copy2(lib, back)
    print("  已备份原文件 -> %s" % back)
else:
    print("  备份已存在，不覆盖 -> %s" % back)

open(lib, "wb").write(d.replace(old, new))

d2 = open(lib, "rb").read()
if len(d2) != len(d):
    print("  !! 文件大小变了（%d -> %d），异常！" % (len(d), len(d2)))
    sys.exit(1)
if d2.count(new) != 1 or d2.count(old) != 0:
    print("  !! 替换后自检不通过")
    sys.exit(1)

print("  OK  %s -> %s   文件大小不变: %d 字节" % (old.decode(), new.decode(), len(d2)))
PYEOF
    then
        if [ "${SB_NO_GUI_HINT:-0}" = "1" ]; then
            echo "  （备用）Systemback 也能认出 NVMe 了 —— 万一不走一键流程、回退用 GUI 也行"
        else
            echo "  Systemback 现在认识 NVMe 了：GUI 分区页会出现 $P1 / $P2 / $P3"
        fi
    else
        echo "  !! 补丁没打上 —— GUI 里将看不到 $DISK 的分区。"
        echo "  !! 回滚（如需）：sudo cp -a $SBBACK $SBLIB"
    fi
fi

# ---------- 结果 ----------
echo
echo "================ 完成 · 记下这些 UUID ================"
blkid "$P1" "$P2" "$P3"
echo
lsblk -f "$DISK"
echo
parted -s "$DISK" print

echo
if [ "${SB_NO_GUI_HINT:-0}" = "1" ]; then
    # 被 sb-install.sh 调用：后面由它解金镜像，不用提示 GUI 那套
    echo "  分区与格式化完成 —— 交回 sb-install.sh 继续"
else
cat << EOF
============================================================
 下一步：打开 Systemback 做安装

     sudo systemback

 点【系统安装 / System install】，分区设置页照这张表填
 （★ 全流程最容易错的地方）：

   分区              挂载点       文件系统    Format
   ----------------  -----------  ---------  --------
   $P1     /boot/efi    vfat       取消勾选
   $P2     SWAP         swap       取消勾选
   $P3     /            ext4       取消勾选

 ★ Systemback 里出现的就是上面这几个名字（步骤 3 的补丁打过之后）。
   整盘那一行 $DISK 也要在列表里，3 个子行挂在它下面。

 ★ 列表里 /dev/sd* 开头的（sda / sda1 / sda2）是启动 U 盘，别选它们。

 ★ p1 必须是 /boot/efi！设成别的（比如 /tmp）会装出一个
   没有 ESP、无法 UEFI 引导的系统，而且安装过程不报任何错。

 ★ 如果列表里【一条都没有】：补丁没打上（看步骤 3 的输出），
   或者 GUI 是在打补丁之前开的。先关掉重开 systemback；
   仍然没有就手工打一次补丁 —— 见文档 附 D.3。

 GRUB 安装选项选：EFI

 装完【不要重启】，先跑第 2 步脚本（引导安全网）：

     sudo bash sb-02-fixup.sh $DISK
============================================================
EOF
fi
