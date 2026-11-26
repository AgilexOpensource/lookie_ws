#!/bin/bash
# ============================================================
#  sb-install.sh 集成测试：状态判定 + 快路径决策
#
#  造两块 loop 盘，模拟真机上的两种状态，跑【真的 sb-install.sh】，
#  在确认提示处回答 NO（中止），只验证它的状态判定和分支选择：
#
#    A. 像 236 那样的半成品：分区齐全、系统文件全在、
#       但【没有 /etc/fstab】→ 应判为"已完整解压"→ 只修引导
#    B. 空盘 → 应判为"没有已安装的系统"→ 全新安装
#
#  用法: sudo bash /var/tmp/sb-sandbox/t2.sh
# ============================================================
set -u

DIR=/var/tmp/sb-sandbox
MNT=$DIR/mnt2
SRC=$DIR/squashfs-src
mkdir -p "$DIR" "$MNT" "$SRC"

PASS=0; FAIL=0
ok()  { echo "      ✓ $1"; PASS=$((PASS+1)); }
bad() { echo "      ✗ $1"; FAIL=$((FAIL+1)); }

# 造一个小金镜像（内容和"根分区"上的哨兵一致）
mkdir -p "$SRC"/usr/bin "$SRC"/usr/lib/systemd "$SRC"/usr/sbin "$SRC"/etc "$SRC"/boot
touch "$SRC"/usr/bin/bash "$SRC"/usr/lib/systemd/systemd \
      "$SRC"/usr/sbin/grub-install "$SRC"/etc/passwd "$SRC"/boot/vmlinuz-6.8.0-test
echo x > "$SRC"/usr/bin/bash
SQ=$DIR/golden.squashfs
rm -f "$SQ"
mksquashfs "$SRC" "$SQ" -noappend -quiet >/dev/null

########################################################################
# A. 半成品盘（模拟 236）
########################################################################
IMG=$DIR/caseA.img; rm -f "$IMG"; truncate -s 400M "$IMG"
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
sgdisk -n 1:2048:+64M -t 1:ef00 -c 1:EFI  "$LO" >/dev/null
sgdisk -n 2:0:+32M   -t 2:8200 -c 2:SWAP "$LO" >/dev/null
sgdisk -n 3:0:0      -t 3:8300 -c 3:ROOT "$LO" >/dev/null
losetup -d "$LO"
LO=$(losetup -f); losetup -P "$LO" "$IMG"
mkfs.vfat -F32 -n EFI "${LO}p1" >/dev/null
mkswap -L SWAP "${LO}p2" >/dev/null 2>&1
mkfs.ext4 -q -F "${LO}p3"
# 关掉 ext4 保留块，让 inode 数更接近真机
mount "${LO}p3" "$MNT"
cp -a "$SRC"/. "$MNT"/
umount "$MNT"
# ★ 故意不建 /etc/fstab —— 这正是 Systemback 装一半的特征

echo
echo "== A. 半成品盘（模拟 236：系统文件全在，但没有 /etc/fstab）=="
OUT=$(SB_ALLOW_LOOP=1 SB_SQUASHFS="$SQ" bash /home/agx/Desktop/sb-install.sh "$LO" <<< "NO" 2>&1 || true)
echo "$OUT" | sed -n '/目标盘现状/,$p' | head -30 | sed 's/^/    /'
if echo "$OUT" | grep -q '已完整解压过'; then
    ok "判为「已完整解压过」→ 走只修引导的快路径 ✓"
else
    bad "没判成已完整解压"
fi
if echo "$OUT" | grep -q '不清空、不重拷'; then ok "确认提示写明不会重拷 ✓"
else bad "确认提示没写明快路径"; fi
losetup -d "$LO"

########################################################################
# B. 空盘
########################################################################
IMG=$DIR/caseB.img; rm -f "$IMG"; truncate -s 300M "$IMG"
LO=$(losetup -f); losetup "$LO" "$IMG"
sgdisk -o "$LO" >/dev/null
losetup -d "$LO"; losetup "$LO" "$IMG"    # 重新 attach：detach 后 lsblk 认不出它是 loop

echo
echo "== B. 空盘（无分区）=="
OUT=$(SB_ALLOW_LOOP=1 SB_SQUASHFS="$SQ" bash /home/agx/Desktop/sb-install.sh "$LO" <<< "NO" 2>&1 || true)
echo "$OUT" | sed -n '/目标盘现状/,$p' | head -30 | sed 's/^/    /'
if echo "$OUT" | grep -q '没有探测到已安装的系统'; then
    ok "判为「没有已安装的系统」→ 走全新安装 ✓"
else
    bad "空盘判定错误"
fi
if echo "$OUT" | grep -q '即将【清空】'; then ok "确认提示写明会清空 ✓"
else bad "确认提示没说清空"; fi

########################################################################
# C. 中止必须真的生效
########################################################################
echo
echo "== C. 回答 NO 必须真的中止（不能往下走）=="
if echo "$OUT" | grep -q '已取消'; then ok "输 NO 已中止 ✓"; else bad "NO 没拦住"; fi
if echo "$OUT" | grep -q '第 1 步：分区'; then bad "中止后仍然继续执行了！"; else ok "中止后没有继续执行 ✓"; fi

echo
echo "############################################################"
echo "#  结果：通过 $PASS 项，失败 $FAIL 项"
echo "############################################################"
rm -f "$DIR"/caseA.img "$DIR"/caseB.img
[ "$FAIL" = "0" ] || exit 1
