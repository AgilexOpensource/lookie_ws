#!/bin/bash
# ============================================================
#  sb-lib.sh 探测原语 · 沙箱回归测试
#
#  用 loop 设备造出 6 种分区布局，验证「通用」是真的通用：
#    1. 标准三分区 GPT（ESP p1 / swap p2 / root p3，无 fstab）
#    2. ESP 在 p2、根在 p4  ← 老脚本（写死 p1/p3）必挂
#    3. 根在中间 p2、swap 在 p3
#    4. MBR 盘（0xef / 0x82 / 0x83）  ← GPT GUID 判据在这儿找不到东西
#    5. 空盘（无分区）  ← 必须干净地失败，不能瞎选
#    6. 五分区、ESP 在 p3、根在 p5
#
#  必须以 root 跑（mount 需要权限，否则会被 2>/dev/null 静默吞掉，
#  所有场景都会假报"没找到"）。
#
#  用法: sudo bash /var/tmp/sb-sandbox/t.sh
# ============================================================
set -u

LIB=/home/agx/Desktop/sb-lib.sh
DIR=/var/tmp/sb-sandbox
MNT=$DIR/mnt
mkdir -p "$DIR" "$MNT"

PASS=0; FAIL=0
ok()   { echo "      ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "      ✗ $1"; FAIL=$((FAIL+1)); }
chk()  { # chk <期望> <实得> <说明>
    if [ "$1" = "$2" ]; then ok "$3  ($2)"
    else bad "$3  期望='$1' 实得='$2'"; fi
}

[ -f "$LIB" ] || { echo "找不到 $LIB"; exit 1; }
. "$LIB"

# 造一个"像系统根"的分区内容
mkroot() {
    local m="$1" with_fstab="$2" with_hostname="$3"
    mkdir -p "$m/usr/bin" "$m/usr/lib/systemd" "$m/usr/sbin" "$m/etc" "$m/boot"
    touch "$m/usr/bin/bash" "$m/usr/lib/systemd/systemd" \
          "$m/usr/sbin/grub-install" "$m/etc/passwd" "$m/boot/vmlinuz-6.8.0-test"
    [ "$with_fstab" = "1" ]    && echo "UUID=x / ext4 defaults 0 1" > "$m/etc/fstab"
    [ "$with_hostname" = "1" ] && echo "agilex" > "$m/etc/hostname"
    return 0
}

# 造一个"普通数据分区"——只有 lost+found，绝不能被认成根
mkdata() { mkdir -p "$1/lost+found"; touch "$1/lost+found/x"; }

newimg() { # newimg <名字> <大小MB>
    local f="$DIR/$1.img"
    rm -f "$f"
    truncate -s "${2}M" "$f"
    echo "$f"
}

# 建分区表后重新挂 loop（带 -P 才能出分区节点）
reloop() { # reloop <loopdev> -> 新 loopdev（带分区）
    losetup -d "$1"
    local d; d=$(losetup -f)
    losetup -P "$d" "$IMG"
    echo "$d"
}

echo "############################################################"
echo "#  sb-lib.sh 探测原语 · 沙箱回归"
echo "############################################################"

########################################################################
# 场景 1：标准三分区 GPT，根上【没有】fstab（Systemback 装一半的典型样子）
########################################################################
echo
echo "== 场景 1：标准三分区 GPT（ESP p1 / swap p2 / root p3，root 无 fstab）=="
IMG=$(newimg s1 300)
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
sgdisk -n 1:2048:+64M -t 1:ef00 -c 1:EFI  "$LO" >/dev/null
sgdisk -n 2:0:+32M   -t 2:8200 -c 2:SWAP "$LO" >/dev/null
sgdisk -n 3:0:0      -t 3:8300 -c 3:ROOT "$LO" >/dev/null
LO=$(reloop "$LO"); P1="${LO}p1"; P2="${LO}p2"; P3="${LO}p3"; P4="${LO}p4"; P5="${LO}p5"
mkfs.vfat -F32 -n EFI "$P1" >/dev/null
mkswap -L SWAP "$P2" >/dev/null 2>&1
mkfs.ext4 -q -F "$P3"
mount "$P3" "$MNT"; mkroot "$MNT" 0 0; umount "$MNT"

chk 3  "$(sb_list_partitions "$LO" | wc -l)"           "分区枚举"
chk "$P1" "$(sb_find_esp  "$LO")"                      "ESP 探测"
chk "$P2" "$(sb_find_swap "$LO")"                      "swap 探测"
chk "$P3" "$(sb_find_root "$LO" "$MNT")"               "根探测"
mount "$P3" "$MNT"; chk 1 "$(sb_score_root "$MNT")" "判据分（无 fstab 应为 1）"; umount "$MNT"
losetup -d "$LO"

########################################################################
# 场景 2：ESP 在 p2、根在 p4 —— 老脚本写死 p1/p3 必挂
########################################################################
echo
echo "== 场景 2：ESP 在 p2、swap 在 p3、根在 p4（外加一个 p1 数据盘）=="
IMG=$(newimg s2 400)
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
sgdisk -n 1:2048:+40M -t 1:8300 -c 1:DATA "$LO" >/dev/null
sgdisk -n 2:0:+64M   -t 2:ef00 -c 2:EFI  "$LO" >/dev/null
sgdisk -n 3:0:+32M   -t 3:8200 -c 3:SWAP "$LO" >/dev/null
sgdisk -n 4:0:0      -t 4:8300 -c 4:ROOT "$LO" >/dev/null
LO=$(reloop "$LO"); P1="${LO}p1"; P2="${LO}p2"; P3="${LO}p3"; P4="${LO}p4"; P5="${LO}p5"
mkfs.ext4 -q -F "$P1"
mkfs.vfat -F32 -n EFI "$P2" >/dev/null
mkswap -L SWAP "$P3" >/dev/null 2>&1
mkfs.ext4 -q -F "$P4"
mount "$P1" "$MNT"; mkdata "$MNT"; umount "$MNT"
mount "$P4" "$MNT"; mkroot "$MNT" 1 1; umount "$MNT"

chk 4  "$(sb_list_partitions "$LO" | wc -l)"           "分区枚举"
chk "$P2" "$(sb_find_esp  "$LO")"                      "ESP 探测（在 p2，不是 p1）"
chk "$P3" "$(sb_find_swap "$LO")"                      "swap 探测"
chk "$P4" "$(sb_find_root "$LO" "$MNT")"               "根探测（在 p4，不是 p3）"
mount "$P4" "$MNT"; chk 3 "$(sb_score_root "$MNT")" "判据分（fstab+hostname 应为 3）"; umount "$MNT"
losetup -d "$LO"

########################################################################
# 场景 3：根在中间 p2、swap 在 p3、p4 是数据盘
########################################################################
echo
echo "== 场景 3：ESP p1 / 根 p2 / swap p3 / 数据 p4 =="
IMG=$(newimg s3 400)
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
sgdisk -n 1:2048:+64M -t 1:ef00 -c 1:EFI  "$LO" >/dev/null
sgdisk -n 2:0:+80M   -t 2:8300 -c 2:ROOT "$LO" >/dev/null
sgdisk -n 3:0:+32M   -t 3:8200 -c 3:SWAP "$LO" >/dev/null
sgdisk -n 4:0:0      -t 4:8300 -c 4:DATA "$LO" >/dev/null
LO=$(reloop "$LO"); P1="${LO}p1"; P2="${LO}p2"; P3="${LO}p3"; P4="${LO}p4"; P5="${LO}p5"
mkfs.vfat -F32 -n EFI "$P1" >/dev/null
mkfs.ext4 -q -F "$P2"
mkswap -L SWAP "$P3" >/dev/null 2>&1
mkfs.ext4 -q -F "$P4"
mount "$P2" "$MNT"; mkroot "$MNT" 1 0; umount "$MNT"
mount "$P4" "$MNT"; mkdata "$MNT"; umount "$MNT"

chk "$P1" "$(sb_find_esp  "$LO")"                      "ESP 探测"
chk "$P3" "$(sb_find_swap "$LO")"                      "swap 探测"
chk "$P2" "$(sb_find_root "$LO" "$MNT")"               "根探测（在 p2）"
mount "$P2" "$MNT"; chk 2 "$(sb_score_root "$MNT")" "判据分（有 fstab 无 hostname 应为 2）"; umount "$MNT"
losetup -d "$LO"

########################################################################
# 场景 4：MBR 盘 —— GPT GUID 判据在这儿一个都匹配不上
########################################################################
echo
echo "== 场景 4：MBR 盘（0xef / 0x82 / 0x83）=="
IMG=$(newimg s4 300)
LO=$(losetup -f); losetup "$LO" "$IMG"
sfdisk "$LO" >/dev/null <<'SFDISK'
label: dos
2048,131072,ef
133120,65536,82
198656,,83
SFDISK
LO=$(reloop "$LO"); P1="${LO}p1"; P2="${LO}p2"; P3="${LO}p3"; P4="${LO}p4"; P5="${LO}p5"
mkfs.vfat -F32 -n EFI "$P1" >/dev/null
mkswap -L SWAP "$P2" >/dev/null 2>&1
mkfs.ext4 -q -F "$P3"
mount "$P3" "$MNT"; mkroot "$MNT" 1 1; umount "$MNT"

chk 3  "$(sb_list_partitions "$LO" | wc -l)"           "分区枚举"
chk "0xef" "$(sb_parttype "$P1")"                      "MBR 类型读取"
chk "$P1" "$(sb_find_esp  "$LO")"                      "ESP 探测（MBR 0xef）"
chk "$P2" "$(sb_find_swap "$LO")"                      "swap 探测（MBR 0x82）"
chk "$P3" "$(sb_find_root "$LO" "$MNT")"               "根探测（MBR）"
losetup -d "$LO"

########################################################################
# 场景 5：空盘 —— 必须干净失败，不能瞎选一个
########################################################################
echo
echo "== 场景 5：空盘（无分区表内容）=="
IMG=$(newimg s5 200)
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
LO=$(reloop "$LO")

chk 0 "$(sb_list_partitions "$LO" | wc -l)"  "分区枚举应为 0"
if sb_find_esp "$LO" >/dev/null 2>&1; then bad "ESP 不该找到东西"; else ok "ESP 干净失败 ✓"; fi
if sb_find_swap "$LO" >/dev/null 2>&1; then bad "swap 不该找到东西"; else ok "swap 干净失败 ✓"; fi
R=$(sb_find_root "$LO" "$MNT" 2>/dev/null || true)
chk "" "$R" "根探测应为空"
losetup -d "$LO"

########################################################################
# 场景 6：五分区，ESP 在 p3、swap 在 p4、根在 p5
########################################################################
echo
echo "== 场景 6：五分区（ESP p3 / swap p4 / 根 p5）=="
IMG=$(newimg s6 500)
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
sgdisk -n 1:2048:+40M -t 1:8300 -c 1:D1   "$LO" >/dev/null
sgdisk -n 2:0:+40M   -t 2:8300 -c 2:D2   "$LO" >/dev/null
sgdisk -n 3:0:+64M   -t 3:ef00 -c 3:EFI  "$LO" >/dev/null
sgdisk -n 4:0:+32M   -t 4:8200 -c 4:SWAP "$LO" >/dev/null
sgdisk -n 5:0:0      -t 5:8300 -c 5:ROOT "$LO" >/dev/null
LO=$(reloop "$LO"); P1="${LO}p1"; P2="${LO}p2"; P3="${LO}p3"; P4="${LO}p4"; P5="${LO}p5"
for i in "$P1" "$P2"; do mkfs.ext4 -q -F "$i"; mount "$i" "$MNT"; mkdata "$MNT"; umount "$MNT"; done
mkfs.vfat -F32 -n EFI "$P3" >/dev/null
mkswap -L SWAP "$P4" >/dev/null 2>&1
mkfs.ext4 -q -F "$P5"
mount "$P5" "$MNT"; mkroot "$MNT" 1 1; umount "$MNT"

chk 5  "$(sb_list_partitions "$LO" | wc -l)"           "分区枚举"
chk "$P3" "$(sb_find_esp  "$LO")"                      "ESP 探测（在 p3）"
chk "$P4" "$(sb_find_swap "$LO")"                      "swap 探测（在 p4）"
chk "$P5" "$(sb_find_root "$LO" "$MNT")"               "根探测（在 p5）"
losetup -d "$LO"

########################################################################
# 附加：在本机（非 Live 环境）上跑，不能把本机盘当成候选
########################################################################
echo
echo "== 附加：本机不是 Live 环境时的行为 =="
LD=$(sb_live_disk 2>/dev/null || true)
if [ -z "$LD" ]; then ok "sb_live_disk 干净失败（本机无 /cdrom 挂载）✓"
else echo "      （本机 live_disk=$LD）"; fi
# 候选列表里绝不能出现正在运行的系统盘
LIVE_ROOT=$(sb_phys_disk_mm "$(lsblk -dno MAJ:MIN "$(findmnt -n -o SOURCE -T / | head -1)" | tr -d '[:space:]')" 2>/dev/null || true)
if [ -n "$LIVE_ROOT" ]; then
    if sb_candidate_disks | grep -qx "$LIVE_ROOT"; then
        bad "候选列表里出现了本机运行盘 $LIVE_ROOT"
    else
        ok "本机运行盘 $LIVE_ROOT 未进候选 ✓"
    fi
fi

echo
echo "############################################################"
echo "#  结果：通过 $PASS 项，失败 $FAIL 项"
echo "############################################################"
[ "$FAIL" = "0" ] || exit 1
