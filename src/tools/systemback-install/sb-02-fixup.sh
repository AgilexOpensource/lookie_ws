#!/bin/bash
# ============================================================
#  Systemback 快速装机 · 第 2 步：安装后修复引导
#
#  在 Systemback 安装完成后、重启之前执行：
#      sudo bash sb-02-fixup.sh /dev/nvme0n1
#
#  ★ 自动探测：根 / ESP / swap 都现场扫描得出，不假定 p1/p2/p3，
#    分区数量和 ESP 位置随便。需要人工指定时见下面 SB_* 覆盖。
#
#  它会强制把系统纠正成可引导状态：
#    1. 卸载目标盘上所有分区
#    2. 找到真正装了系统的分区（不管 Systemback 怎么写的）
#    3. 把 ESP 分区强制做成 vfat 并挂上
#    4. 重写 /etc/fstab（UUID 全部纠正）
#    5. 清掉 Systemback 从 Live 环境带过来的 casper
#    6. 重装 GRUB + 重建 initrd + 生成 grub.cfg
#       （顺手把 T500 热重启缓解参数写进 /etc/default/grub，见附 E）
#    7. 重置机器身份（machine-id + SSH host key，批量部署必做）
#    8. 纠正 /etc/hosts 的 127.0.1.1
#    9. 补写 UEFI 启动项
#   10. 5 项校验（含"缓解参数真的进了 grub.cfg 吗"）
#
#  ★ 幂等：装对了重跑也没事；装错了它能救回来。
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
TGT=/mnt/sb-fixup

# ★ 本脚本不再假定 p1/p2/p3。
#   根分区、ESP、swap 全部靠 sb-lib.sh 现场探测，分区数量不限、
#   ESP 不一定是 p1。需要人工兜底时可用环境变量覆盖：
#       sudo SB_ROOT=/dev/nvme0n1p4 SB_ESP=/dev/nvme0n1p2 sb-02-fixup.sh /dev/nvme0n1

# ---------- 设备 → 它所属的整块磁盘 ----------
# 实现搬到 sb-lib.sh 的 sb_phys_disk（能穿透 dm/md 等映射设备）。
whole_disk() {
    sb_phys_disk "$1"
}

# ---------- 安全检查 ----------
echo "================ 安全检查 ================"
[ -b "$DISK" ] || { echo "!! $DISK 不存在"; exit 1; }
DISK=$(readlink -f "$DISK")
TRAN=$(lsblk -dno TRAN "$DISK")
RM=$(lsblk -dno RM "$DISK")
if [ "$TRAN" = "usb" ] || [ "$RM" = "1" ]; then
    echo "!! $DISK 是 U 盘 / 可移动设备，拒绝操作"; exit 1
fi
DTYPE=$(lsblk -dno TYPE "$DISK" 2>/dev/null)
if [ "$DTYPE" != "disk" ]; then
    echo "!! $DISK 不是整块磁盘（lsblk TYPE='$DTYPE'），请传整盘设备名"; exit 1
fi

# ★ 拒绝操作「当前正在运行的系统」所在的盘（会重写它的 ESP 和 fstab）
if [ "$(whole_disk "$(findmnt -n -o SOURCE -T / 2>/dev/null | head -1)" || true)" = "$DISK" ]; then
    echo "!! 拒绝操作：$DISK 上正运行着当前系统（/ 在它上面）"
    echo "!! 本脚本要在 Live 环境里运行，目标是未挂载的盘。"
    exit 1
fi
for sw in $(swapon --show=NAME --noheadings 2>/dev/null || true); do
    if [ "$(whole_disk "$sw" || true)" = "$DISK" ]; then
        echo "!! 拒绝操作：$DISK 上有正在使用的 swap（$sw）"; exit 1
    fi
done

echo "  目标: $DISK ($(lsblk -dno MODEL "$DISK" | tr -s ' '))  总线=$TRAN 可移动=$RM"

# ---------- 1. 挂点腾空 ----------
echo
echo "================ 1. 卸载所有相关分区 ================"
swapoff -a 2>/dev/null || true
# ★ 枚举整盘所有分区，而不是死循环 p1..p8。
#   布局不一定是 3 个分区，分区数也不一定叫 p1/p2/p3。
for p in $(sb_list_partitions "$DISK"); do
    umount "$p" 2>/dev/null || true
done
umount -R "$TGT" 2>/dev/null || true     # 递归清掉上次中断留下的 dev/proc/sys/run 叠挂
umount "$TGT" 2>/dev/null || true
echo "  完成"

# ---------- 2. 找真正装了系统的分区 ----------
# ★ 判据【不能】要求 /etc/fstab 存在 —— 这是实机踩出来的坑。
#   Systemback 装到一半停住时（文件拷完了，还没写 fstab、没装 GRUB），
#   它会先把原 fstab 挪进 <.systemback/etc/fstab>，目标盘上反而【没有】fstab。
#   而这恰恰是最需要本脚本兜底的场景 —— 老判据会在这里直接放弃。
#   第 4 步本来就会按真实 UUID 重写一份 fstab，不依赖它先存在。
#   所以：「有 fstab」当加分项，不当门槛。
echo
echo "================ 2. 定位系统所在分区 ================"
ROOT_PART=""
ROOT_WHY=""
SB_FSTAB=""
BEST=0
mkdir -p "$TGT"

# ★ 候选来自【整盘的每一个分区】，不再假设 p1/p2/p3。
#   跳过 ESP 和 swap（它们不可能是根），数量不限。
#   也支持 SB_ROOT=/dev/xxx 直接指定、跳过扫描。
if [ -n "${SB_ROOT:-}" ]; then
    CANDS="$SB_ROOT"
    echo "  （SB_ROOT 指定：$SB_ROOT，跳过扫描）"
else
    ESP_HINT=$(sb_find_esp  "$DISK" 2>/dev/null || true)
    SWAP_HINT=$(sb_find_swap "$DISK" 2>/dev/null || true)
    CANDS=""
    for p in $(sb_list_partitions "$DISK"); do
        if [ "$p" = "$ESP_HINT" ] || [ "$p" = "$SWAP_HINT" ]; then
            continue
        fi
        CANDS="$CANDS $p"
    done
fi

for cand in $CANDS; do
    [ -b "$cand" ] || continue
    mount "$cand" "$TGT" 2>/dev/null || continue

    # 打分逻辑统一在 sb-lib.sh 的 sb_score_root（1=根目录结构+内核，+1 fstab，+1 hostname）
    score=$(sb_score_root "$TGT")
    why=""
    case "$score" in
        0) why="不像系统根" ;;
        1) why="有根目录结构 + 内核" ;;
        2) why="有根目录结构 + 内核 + fstab" ;;
        *) why="有根目录结构 + 内核 + fstab + hostname" ;;
    esac

    # 打分取最高；同分保留先遇到的（分区号小的优先）
    # ★ 顺手把 .systemback/etc/fstab 的内容抓出来 —— 必须在 umount 之前读
    if [ "$score" -gt 0 ] && [ "$score" -gt "$BEST" ]; then
        BEST=$score; ROOT_PART="$cand"; ROOT_WHY="$why"
        SB_FSTAB=""
        if [ -f "$TGT/.systemback/etc/fstab" ]; then
            SB_FSTAB=$(grep -v '^#' "$TGT/.systemback/etc/fstab" 2>/dev/null | grep -v '^$')
        fi
    fi

    umount "$TGT" 2>/dev/null || true
done

if [ -z "$ROOT_PART" ]; then
    echo "!! 在 $DISK 的所有分区里都找不到像系统根分区的分区"
    echo "!! 至少要同时满足：有 /usr/bin、有 /etc、有 /boot/vmlinuz*"
    echo "!! Systemback 安装可能没跑完，请先完成安装再执行本脚本"
    echo "!! 若确认某个分区就是根，可指定：sudo SB_ROOT=/dev/xxx bash $(basename "$0") $DISK"
    exit 1
fi
echo "  系统在 $ROOT_PART  ✓ ($ROOT_WHY)"

if [ "$BEST" = "1" ]; then
    echo
    echo "  ⚠ 该分区上没有 /etc/fstab —— 典型症状是 Systemback 装到一半停了"
    echo "    （拷完文件但没走到写 fstab / 装 GRUB 那步）。"
    echo "    原 fstab 若存在，应在 .systemback/etc/fstab；"
    echo "    第 4 步会按本机真实 UUID 重写一份，不影响继续。"
    if [ -n "$SB_FSTAB" ]; then
        echo "    检测到 .systemback/etc/fstab，里面是【源机器】的 UUID（仅供参考）："
        echo "$SB_FSTAB" | sed 's/^/      /'
    fi
fi

# ESP：优先用 SB_ESP 指定，否则自动探测（GUID ef00 / MBR 0xef / parted esp 标志 / vfat 兜底）
# ★ 不能假设 ESP 一定是 p1 —— 有些机器（尤其预装 Windows 的）ESP 在 p2。
if [ -n "${SB_ESP:-}" ]; then
    ESP_PART="$SB_ESP"
    echo "  （SB_ESP 指定 ESP：$ESP_PART）"
else
    ESP_PART=$(sb_find_esp "$DISK" 2>/dev/null || true)
fi
if [ -z "$ESP_PART" ]; then
    echo "!! 在 $DISK 上找不到 ESP（EFI 系统）分区"
    echo "!! 正常布局里应该有一个 EF00 / 0xef 类型的分区。"
    echo "!! 若要指定：sudo SB_ESP=/dev/xxx bash $(basename "$0") $DISK"
    exit 1
fi
if [ "$ESP_PART" = "$ROOT_PART" ]; then
    echo "!! ESP（$ESP_PART）和系统根是同一个分区，无法两用"
    echo "!! 分区布局不对，请重跑 sb-01-prepare.sh 重建"
    exit 1
fi
echo "  ESP 在 $ESP_PART  ✓"

# ---------- 3. 挂载 ----------
echo
echo "================ 3. 挂载 ================"
mount "$ROOT_PART" "$TGT"
mkdir -p "$TGT/boot/efi"

# ESP 必须是 vfat；不是就重建（里面本来就只该有引导文件）
ESP_FSTYPE=$(blkid -s TYPE -o value "$ESP_PART" 2>/dev/null || echo "")
if [ "$ESP_FSTYPE" != "vfat" ]; then
    echo "  $ESP_PART 当前是 '${ESP_FSTYPE:-空}'，重建为 vfat ESP ..."
    umount "$ESP_PART" 2>/dev/null || true
    wipefs -a "$ESP_PART" >/dev/null 2>&1 || true
    mkfs.vfat -F 32 -n EFI "$ESP_PART"
else
    echo "  $ESP_PART 已经是 vfat ✓"
fi
mount "$ESP_PART" "$TGT/boot/efi"

for d in dev proc sys run; do
    mkdir -p "$TGT/$d"
    mount --rbind "/$d" "$TGT/$d"          # ★ 必须 rbind，否则 efivarfs 传不进去
    mount --make-rslave "$TGT/$d"
done

ROOT_UUID=$(blkid -s UUID -o value "$ROOT_PART")
EFI_UUID=$(blkid -s UUID -o value "$ESP_PART")
# swap：优先 SB_SWAP，否则自动探测；没有 swap 分区就留空（fstab 里不写那行）
if [ -n "${SB_SWAP:-}" ]; then
    SWAP_PART="$SB_SWAP"
else
    SWAP_PART=$(sb_find_swap "$DISK" 2>/dev/null || true)
fi
SWAP_UUID=""
if [ -n "$SWAP_PART" ]; then
    SWAP_UUID=$(blkid -s UUID -o value "$SWAP_PART" 2>/dev/null || echo "")
    echo "  swap 在 $SWAP_PART  ✓"
else
    echo "  （没找到 swap 分区，fstab 里不写 swap 行）"
fi

# ---------- 4. 重写 fstab ----------
echo
echo "================ 4. 重写 /etc/fstab ================"
if [ -f "$TGT/etc/fstab" ]; then cp "$TGT/etc/fstab" "$TGT/etc/fstab.bak"; fi
{
    echo "# /etc/fstab"
    echo "UUID=$ROOT_UUID   /           ext4   noatime,errors=remount-ro   0   1"
    if [ -n "$SWAP_UUID" ]; then
        echo "UUID=$SWAP_UUID   none        swap   sw                          0   0"
    fi
    echo "UUID=$EFI_UUID    /boot/efi   vfat   umask=0077                  0   1"
} > "$TGT/etc/fstab"
grep -v '^#' "$TGT/etc/fstab" | grep -v '^$' | sed 's/^/  /'

# ---------- 5. 清掉 casper ----------
echo
echo "================ 5. 清除 casper（Live 环境残留）================"
rm -rf "$TGT/usr/share/initramfs-tools/hooks/casper"*
rm -rf "$TGT/usr/share/initramfs-tools/scripts/casper"*
rm -rf "$TGT/usr/share/initramfs-tools/conf.d/casper"*
rm -rf "$TGT/usr/share/casper"
rm -f  "$TGT/etc/casper.conf"
rm -f  "$TGT/etc/systemd/system/final.target.wants/casper.service"
rm -f  "$TGT/etc/systemd/system/multi-user.target.wants/casper-md5check.service"
LEFT=$(find "$TGT/etc" "$TGT/usr/share/initramfs-tools" -iname "*casper*" 2>/dev/null | wc -l)
echo "  剩余 casper 文件数: $LEFT"

# ---------- 6. 装 GRUB ----------
echo
echo "================ 6. 安装 GRUB 到 ESP ================"
chroot "$TGT" grub-install --target=x86_64-efi --efi-directory=/boot/efi \
       --bootloader-id=ubuntu --recheck --no-floppy "$DISK" 2>&1 | sed 's/^/  /'

# ---------- 7. 重建 initrd + 内核参数 + grub.cfg ----------
echo
echo "================ 7. 重建 initrd + 生成 grub.cfg ================"

# ★ T500 热重启缺陷的内核侧缓解（见文档附 E）。
#   必须赶在下面的 update-grub 【之前】写进 /etc/default/grub，
#   这样 update-grub 会直接把它烤进 grub.cfg，不用二次重跑。
#   ★ 每台装好的机器都自动带 —— 不用回头去重做金镜像 U 盘。
SB_GRUB_PARAMS="${SB_GRUB_PARAMS:-nvme_core.default_ps_max_latency_us=0 pcie_aspm=off}"
GRUBDEF="$TGT/etc/default/grub"
if [ -f "$GRUBDEF" ]; then
    CUR=$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"$/\1/p' "$GRUBDEF" | head -1)
    NEW="$CUR"
    for p in $SB_GRUB_PARAMS; do
        case " $NEW " in *" $p "*) ;; *) NEW="$NEW $p" ;; esac
    done
    NEW=$(printf '%s' "$NEW" | sed 's/^ *//; s/ *$//')
    if [ "$NEW" = "$CUR" ]; then
        echo "  内核参数已包含，无需改动："
    else
        # ★ 必须分两种情况：文件里【没有这一行】时，awk 只会原样复制，
        #   参数根本没写进去 —— 而且不报错。这是静默失败的经典样子。
        if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUBDEF"; then
            # 用 awk 整行替换，避免 sed 里 \ / " 的转义雷
            awk -v v="$NEW" '/^GRUB_CMDLINE_LINUX_DEFAULT=/{
                        print "GRUB_CMDLINE_LINUX_DEFAULT=\"" v "\""; next } { print }' \
                "$GRUBDEF" > "$GRUBDEF.tmp" && mv "$GRUBDEF.tmp" "$GRUBDEF"
        else
            printf 'GRUB_CMDLINE_LINUX_DEFAULT="%s"\n' "$NEW" >> "$GRUBDEF"
        fi
        echo "  已把 T500 热重启缓解参数写进 $GRUBDEF："
    fi
    grep '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUBDEF" | sed 's/^/    /'
    # 回读确认：写进去没写进去，以文件为准
    if [ -n "$SB_GRUB_PARAMS" ]; then
        for p in $SB_GRUB_PARAMS; do
            grep -q -- "$p" "$GRUBDEF" || {
                echo "  !! 参数 $p 没写进 $GRUBDEF，请把这段输出发出来"
                exit 1
            }
        done
    fi
else
    echo "  ⚠ 目标盘上没有 /etc/default/grub —— 跳过内核参数（不影响安装）"
fi

chroot "$TGT" update-initramfs -u -k all 2>&1 | tail -5 | sed 's/^/  /'
chroot "$TGT" update-grub 2>&1 | tail -8 | sed 's/^/  /'

# ---------- 8. 重置机器身份 ----------
# 金镜像是整批复制的。machine-id 和 SSH host key 如果原样带过去，
# 所有机器会共用同一个 ID 和同一把 host key —— 批量部署的经典坑。
# hostname 不动（保持金镜像里的名字）。
echo
echo "================ 8. 重置机器身份（machine-id + SSH host key）================"

if [ -f "$TGT/etc/machine-id" ]; then
    : > "$TGT/etc/machine-id"          # 清空 → 首次启动时 systemd 自动生成新的
    echo "  /etc/machine-id 已清空（首次启动重新生成）"
else
    echo "  (没有 /etc/machine-id，跳过)"
fi

if [ -L "$TGT/var/lib/dbus/machine-id" ]; then
    echo "  /var/lib/dbus/machine-id 是指向 /etc/machine-id 的链接，自动跟着变 ✓"
elif [ -f "$TGT/var/lib/dbus/machine-id" ]; then
    : > "$TGT/var/lib/dbus/machine-id"
    echo "  /var/lib/dbus/machine-id 已清空"
fi

NKEY=$(ls "$TGT"/etc/ssh/ssh_host_*_key 2>/dev/null | wc -l)
if [ "$NKEY" != "0" ]; then
    rm -f "$TGT"/etc/ssh/ssh_host_*
    echo "  已删除金镜像里的 $NKEY 把 host key，重新生成中 ..."
    if chroot "$TGT" ssh-keygen -A 2>&1 | sed 's/^/    /'; then
        echo "  新 host key 指纹（每台机器都不同）："
        for k in "$TGT"/etc/ssh/ssh_host_*_key.pub; do
            [ -f "$k" ] && ssh-keygen -lf "$k" 2>/dev/null | sed 's/^/    /'
        done
    else
        echo "  !! ssh-keygen -A 失败 —— 首次启动时 sshd 可能起不来"
    fi
else
    echo "  (金镜像里没有 host key，跳过)"
fi

# /etc/hosts 里的 127.0.1.1 必须和 /etc/hostname 完全一致（含大小写）。
# ★ 实机踩到过：hostname 是 agilex，hosts 里却写着 Agilex。
#   sudo 会因此解析不到本机主机名，报 "unable to resolve host" 并卡顿；
#   有些程序（如某些 JDK/ROS 节点）也会拿它当本机标识，行为诡异。
HN=$(cat "$TGT/etc/hostname" 2>/dev/null | head -1 | tr -d '[:space:]')
if [ -n "$HN" ] && [ -f "$TGT/etc/hosts" ]; then
    CUR=$(grep -E '^127\.0\.1\.1[[:space:]]' "$TGT/etc/hosts" 2>/dev/null | head -1 | awk '{print $2}')
    if [ "$CUR" = "$HN" ]; then
        echo "  /etc/hosts 的 127.0.1.1 已是 $HN ✓"
    else
        echo "  /etc/hosts 的 127.0.1.1 是 '${CUR:-无}'，改成 '$HN' ..."
        # 删掉所有 127.0.1.1 行，再补一行正确的
        grep -v -E '^127\.0\.1\.1[[:space:]]' "$TGT/etc/hosts" > "$TGT/etc/hosts.tmp" 2>/dev/null || true
        echo "127.0.1.1	$HN" >> "$TGT/etc/hosts.tmp"
        mv "$TGT/etc/hosts.tmp" "$TGT/etc/hosts"
        grep -E '^127\.0\.1\.1' "$TGT/etc/hosts" | sed 's/^/    /'
    fi
fi

# ---------- 9. 打扫 ----------
echo
echo "================ 9. 卸载 ================"
for d in run sys proc dev; do umount -R "$TGT/$d" 2>/dev/null || true; done
umount "$TGT/boot/efi" 2>/dev/null || true
umount "$TGT" 2>/dev/null || true
sync

# ---------- 10. UEFI 启动项 ----------
echo
echo "================ 10. 补写 UEFI 启动项 ================"
ESP_PARTUUID=$(blkid -s PARTUUID -o value "$ESP_PART")
# ★ 分区号必须是【这台机器上这个 ESP 的真实分区号】，不能写死 1。
#   取法：/sys 里那个 partition 文件是权威的，到处都有。
#   ★ 别用 `lsblk -o PARTN` —— util-linux 2.37.2 上它是「unknown column」，
#     报错被 2>/dev/null 吞掉后 ESP_NUM 为空，这一步就静默不做了。
ESP_NUM=""
_syspart="/sys/class/block/$(basename "$ESP_PART")/partition"
if [ -r "$_syspart" ]; then
    ESP_NUM=$(cat "$_syspart" 2>/dev/null | tr -d '[:space:]')
fi
if [ -z "$ESP_NUM" ]; then
    # 兜底：从设备名里剥出分区号（sda1 -> 1，nvme0n1p1 -> 1）
    ESP_NUM="${ESP_PART#"$DISK"}"
    ESP_NUM="${ESP_NUM#p}"
fi
case "$ESP_NUM" in ''|*[!0-9]*) ESP_NUM="" ;; esac

if [ -z "$ESP_NUM" ]; then
    echo "  !! 取不到 $ESP_PART 的分区号，跳过 UEFI 启动项"
elif efibootmgr -v 2>/dev/null | grep -qi "$ESP_PARTUUID"; then
    echo "  已存在指向本 ESP 的启动项（PARTUUID=$ESP_PARTUUID），跳过"
else
    echo "  未找到指向本 ESP 的启动项，创建中（$DISK 第 $ESP_NUM 分区）..."
    efibootmgr -c -d "$DISK" -p "$ESP_NUM" -L ubuntu -l '\EFI\ubuntu\shimx64.efi' 2>&1 | sed 's/^/  /' || \
        echo "  (创建失败，继续)"
fi

# ★ 提示：可能有指向【别的盘】同名 ubuntu 条目（换机重装常见），BIOS 菜单里会重复
STALE=$(efibootmgr -v 2>/dev/null | grep -i '\EFI\\ubuntu\\shimx64.efi' | grep -vi "$ESP_PARTUUID" || true)
if [ -n "$STALE" ]; then
    echo
    echo "  ⚠ 发现指向【其它 ESP】的同名 ubuntu 启动项，BIOS 菜单里会多出一条："
    echo "$STALE" | sed 's/^/      /'
    echo "    想清掉的话：sudo efibootmgr -b XXXX -B   （XXXX 是上面行首的编号）"
fi

# ---------- 11. 最终校验 ----------
echo
echo "================ 11. 最终校验 ================"
FAIL=0

echo -n "  [1] initrd 无 casper ........ "
mount "$ROOT_PART" "$TGT"
mkdir -p "$TGT/boot/efi"
mount "$ESP_PART" "$TGT/boot/efi"
CAS=0; NINIT=0
for ir in "$TGT"/boot/initrd.img-*; do
    [ -f "$ir" ] || continue
    NINIT=$((NINIT + 1))
    if lsinitramfs "$ir" 2>/dev/null | grep -qi casper; then CAS=1; fi
done
if [ "$NINIT" = "0" ]; then
    echo "✗ 没找到 initrd"; FAIL=1
elif [ "$CAS" = "1" ]; then
    echo "✗ 仍有残留"; FAIL=1
else
    echo "✓ ($NINIT 个 initrd)"
fi

echo -n "  [2] grub.cfg 指向正确 root ... "
if grep -q "$ROOT_UUID" "$TGT/boot/grub/grub.cfg"; then
    echo "✓"
else
    echo "✗ 没找到 $ROOT_UUID"; FAIL=1
fi

echo -n "  [3] ESP 里有引导文件 ........ "
if [ -f "$TGT/boot/efi/EFI/ubuntu/shimx64.efi" ] && [ -f "$TGT/boot/efi/EFI/BOOT/BOOTX64.EFI" ]; then
    echo "✓"
else
    echo "✗ 缺文件"; FAIL=1
fi

echo -n "  [4] fstab 有 /boot/efi ...... "
if grep -q "/boot/efi" "$TGT/etc/fstab"; then
    echo "✓"
else
    echo "✗"; FAIL=1
fi

# 内核参数是不是真的烤进 grub.cfg 了 —— 只改 /etc/default/grub 不算数，
# update-grub 没跑成功的话 grub.cfg 里什么都没有。
echo -n "  [5] T500 缓解参数进了 grub.cfg "
NGP=0
for p in $SB_GRUB_PARAMS; do
    grep -q -- "$p" "$TGT/boot/grub/grub.cfg" && NGP=$((NGP + 1))
done
NSHOULD=$(printf '%s\n' $SB_GRUB_PARAMS | grep -c . || true)
if [ "$NSHOULD" = "0" ]; then
    echo "— （SB_GRUB_PARAMS 为空，本项跳过）"
elif [ "$NGP" = "$NSHOULD" ]; then
    echo "✓ ($NGP/$NSHOULD)"
else
    echo "✗ 只找到 $NGP/$NSHOULD 个"; FAIL=1
fi

umount "$TGT/boot/efi" 2>/dev/null || true
umount "$TGT" 2>/dev/null || true

echo
echo "  UEFI 启动项："
efibootmgr -v 2>/dev/null | sed 's/^/    /'

echo
if [ "$FAIL" = "0" ]; then
    cat << 'EOF'
============================================================
 ✅ 全部检查通过 —— 引导已经修好了
============================================================

 ★ 关机/重启这一步【不要用 reboot】：这台机器的 Crucial T500
   有已知固件缺陷，软重启后 BIOS 认不到盘，会看起来像"装坏了"。

   正确做法：长按电源键（或直接拔电）彻底断电，等 5 秒，
   再开机，并从 BIOS 启动顺序里选 NVMe。详见文档「附 E」。

   （本次已经把那两个缓解参数写进了 grub.cfg，校验项 [5] 就是查这个 ——
     它能保证【以后再重启】不容易再犯；但【这一次】从 Live 环境发起的
     重启仍受 Live 内核状态影响，所以还是断电最稳。）
============================================================
EOF
else
    cat << 'EOF'
============================================================
 ⚠️ 有检查项未通过，请把上面的输出发给维护者
============================================================
EOF
    exit 1
fi
