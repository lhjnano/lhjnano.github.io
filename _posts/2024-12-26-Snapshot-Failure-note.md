---
layout: post
title: LVM 스냅샷 생성시 실패 사례 및 위험 관리
categories: [LVM, Snapshot]
description: LVM 스냅샷 생성시 실패 사례와 처리방법을 나열합니다.
keywords: LVM, Snapshot
toc: true
toc_sticky: true
---

## 이슈별 처리방법

| Thin Provisioning | File System(df -Th)                       | Physical Volume(pvdisplay -C -o name,mda_size,mda_free<br>)                                                                                                        | Volume Group (vgs)                                        | Data LV (lvs -a)                                                                                                                                               | MedataData LV (lvs -a)                                                                                                                                                          |
| ----------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full              | `fs_growfs -d {file system}`              | 1. add `LUN`<br>2. `pvcreate --metadatasize {size} {partition}`<br>3. remove some lv<br>4. `vgextend {vg} {newPV}`<br>5. `pvchange --metadataignore y {oldPV}`<br> | `vgextend {vg} {pv}`                                      | 1. `lvextend -L+{size} {vg}/{pool}`<br>2. `lvconvert --repair {vg}/{pool}`<br>3. if necessary `lvconvert --thinpool {vg}/{pool} --poolmetadata {vg}/{newMeta}` | 1. `lvextend --poolmetadatasize +{size} {vg}/{pool}`<br>2. `lvconvert --repair {vg}/{pool}`<br>3. if necessary `lvconvert --thinpool {vg}/{pool} --poolmetadata {vg}/{newMeta}` |
| Full threshold    |                                           |                                                                                                                                                                    |                                                           | `autoextend` or<br>`lvextend -L+{size} {vg}/{pool}`                                                                                                            | 1. `autoextend` or<br>`lvextend --poolmetadatasize +{size} {vg}/{pool}`<br>2. if necessary, check error                                                                         |
| Error             | `fsck {vg}` or<br>`xfs_repair -n {dm-lv}` |                                                                                                                                                                    | 1. `vgcfgrestore {vg_name}`<br>2. Check file system error | Check file system error                                                                                                                                        | 1. `lvconvert --repair {vg}/{pool}`<br>2. if necessary `lvconvert --thinpool {vg}/{pool} --poolmetadata {vg}/{newMeta}`                                                         |

#### Reached metadata threshold

```bash
[root@BearTest-1 ~]# lvcreate -s -n snap216 thinpool/thinvol
  WARNING: Remaining free space in metadata of thin pool thinpool/tp_thinpool is too low (76.46% >= 75.00%). Resize is recommended.
  Cannot create new thin volume, free space in thin pool thinpool/tp_thinpool reached threshold.

[root@BearTest-1 ~]# lvs -a -o+seg_monitor | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert Monitor
  [lvol0_pmspare]     thinpool  ewi-------  4.00m
  thinvol             thinpool  Vwi-aotz-- 30.00g tp_thinpool         3.90
  tp_thinpool         thinpool  twi-aotz-- 30.00g                     4.64   76.46                            monitored
  [tp_thinpool_tdata] thinpool  Twi-ao---- 30.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao----  4.00m
```

- The thin pool is monitored, but it is not to extend metadata lv
- It can be expanded directly

```bash
[root@BearTest-1 ~]# lvextend --poolmetadatasize +4M thinpool/tp_thinpool
  WARNING: Sum of all thin volume sizes (<6.33 TiB) exceeds the size of thin pools and the size of whole volume group (<50.00 GiB).
  Size of logical volume thinpool/tp_thinpool_tmeta changed from 4.00 MiB (1 extents) to 8.00 MiB (2 extents).
  Logical volume thinpool/tp_thinpool_tmeta successfully resized.

[root@BearTest-1 ~]# lvs -a -o+seg_monitor | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert Monitor
  [lvol0_pmspare]     thinpool  ewi-------  8.00m
  thinvol             thinpool  Vwi-aotz-- 30.00g tp_thinpool         3.90
  tp_thinpool         thinpool  twi-aotz-- 30.00g                     4.64   43.21                            monitored
  [tp_thinpool_tdata] thinpool  Twi-ao---- 30.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao----  8.00m

[root@BearTest-1 ~]# lvcreate -s -n snap216 thinpool/thinvol
  WARNING: Sum of all thin volume sizes (<6.36 TiB) exceeds the size of thin pool thinpool/tp_thinpool and the size of whole volume group (<50.00 GiB).
  Logical volume "snap216" created.
```

#### Thin volume: no space left

```bash
[root@BearTest-1 ~]# dd if=/dev/zero of=/root/thinmount/file100 bs=4096 count=100000;
dd: failed to open `/root/thinmount/file100': 장치에 남은 공간이 없음

[root@BearTest-1 ~]# lvs -a -o+seg_monitor | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert Monitor
  [lvol0_pmspare]     thinpool  ewi------- 12.00m
  thinvol             thinpool  Vwi-aotz-- 30.00g tp_thinpool         100.00
  tp_thinpool         thinpool  twi-aotz-- 45.00g                     70.22  68.03                            monitored
  [tp_thinpool_tdata] thinpool  Twi-ao---- 45.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 12.00m
```

- Only Thin pool is autoextended and thin volume is not autoextended.
- You should directly expand the thin volume.

```bash
[root@BearTest-1 ~]# lvextend -L+50GiB thinpool/thinvol
  WARNING: Sum of all thin volume sizes (<12.71 TiB) exceeds the size of thin pool thinpool/tp_thinpool and the size of whole volume group (<50.00 GiB).
  Size of logical volume thinpool/thinvol changed from 30.00 GiB (7680 extents) to 80.00 GiB (20480 extents).
  Logical volume thinpool/thinvol successfully resized.

[root@BearTest-1 thinmount]# lvs -a | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert
  [lvol0_pmspare]     thinpool  ewi------- 12.00m
  thinvol             thinpool  Vwi-aotz-- 80.00g tp_thinpool         37.49
  tp_thinpool         thinpool  twi-aotz-- 45.00g                     70.22  68.03
  [tp_thinpool_tdata] thinpool  Twi-ao---- 45.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 12.00m

[root@BearTest-1 thinmount]# dd if=/dev/zero of=/root/thinmount/file79 bs=4096 count=100000;
dd: `/root/thinmount/file79'에 쓰는 도중 오류 발생: 장치에 남은 공간이 없음
52073+0 records in
52072+0 records out
213286912 bytes (213 MB) copied, 0.609096 s, 350 MB/s
```

- Even though I've expanded it, it says there's no room left
- Then let's check the capacity of the file system

```bash
[root@BearTest-1 ~]# df -Th
Filesystem                   Type            Size  Used Avail Use% Mounted on
devtmpfs                     devtmpfs        3.9G     0  3.9G   0% /dev
tmpfs                        tmpfs           3.9G   12K  3.9G   1% /dev/shm
tmpfs                        tmpfs           3.9G  1.2M  3.9G   1% /run
tmpfs                        tmpfs           3.9G     0  3.9G   0% /sys/fs/cgroup
/dev/mapper/anystor--e-root  xfs              44G  7.0G   37G  16% /
/dev/sda2                    xfs            1014M  148M  867M  15% /boot
/dev/sda1                    vfat            200M   12M  189M   6% /boot/efi
tmpfs                        tmpfs           783M     0  783M   0% /run/user/999
tmpfs                        tmpfs           783M     0  783M   0% /run/user/0
10.0.41.100:private.tcp      fuse.glusterfs   44G  7.5G   37G  17% /mnt/private
/dev/mapper/thinpool-thinvol xfs              30G   30G   20K 100% /root/thinmount
```

- The file system was out of capacity. Increase the capacity of the file system.

```bash
[root@BearTest-1 ~]# xfs_growfs -d /dev/mapper/thinpool-thinvol
meta-data=/dev/mapper/thinpool-thinvol isize=512    agcount=16, agsize=491520 blks
         =                       sectsz=512   attr=2, projid32bit=1
         =                       crc=1        finobt=0 spinodes=0
data     =                       bsize=4096   blocks=7864320, imaxpct=0
         =                       sunit=128    swidth=128 blks
naming   =version 2              bsize=8192   ascii-ci=0 ftype=1
log      =internal               bsize=4096   blocks=3840, version=2
         =                       sectsz=512   sunit=8 blks, lazy-count=1
realtime =none                   extsz=4096   blocks=0, rtextents=0
data blocks changed from 7864320 to 20971520

[root@BearTest-1 ~]# df -Th
Filesystem                   Type            Size  Used Avail Use% Mounted on
devtmpfs                     devtmpfs        3.9G     0  3.9G   0% /dev
tmpfs                        tmpfs           3.9G   12K  3.9G   1% /dev/shm
tmpfs                        tmpfs           3.9G  1.2M  3.9G   1% /run
tmpfs                        tmpfs           3.9G     0  3.9G   0% /sys/fs/cgroup
/dev/mapper/anystor--e-root  xfs              44G  7.1G   37G  17% /
/dev/sda2                    xfs            1014M  148M  867M  15% /boot
/dev/sda1                    vfat            200M   12M  189M   6% /boot/efi
tmpfs                        tmpfs           783M     0  783M   0% /run/user/999
tmpfs                        tmpfs           783M     0  783M   0% /run/user/0
10.0.41.100:private.tcp      fuse.glusterfs   44G  7.5G   37G  18% /mnt/private
/dev/mapper/thinpool-thinvol xfs              80G   30G   50G  38% /root/thinmount

[root@BearTest-1]# dd if=/dev/zero of=/root/thinmount/file80 bs=4096 count=100000;
100000+0 records in
100000+0 records out
409600000 bytes (410 MB) copied, 0.436089 s, 939 MB/s
```

#### 메타데이터가 16MiB 아래면 임계치 75% 적용으로 lvm 단에서 스냅샷 생성 안됌.

```bash
lvcreate -s -n snap400 thinpool/thinvol
  WARNING: Remaining free space in metadata of thin pool thinpool/tp_thinpool is too low (75.20% >= 75.00%). Resize is recommended.


cat /etc/lvm/lvm.conf
876 >---thin_pool_autoextend_threshold=80


[root@BearTest-1 ~]# lvs -a -o+seg_monitor | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert Monitor
  [lvol0_pmspare]     thinpool  ewi------- 12.00m
  thinvol             thinpool  Vwi-aotz-- 80.00g tp_thinpool         37.99
  tp_thinpool         thinpool  twi-aotz-- 48.00g                     66.76  75.20                            monitored
  [tp_thinpool_tdata] thinpool  Twi-ao---- 48.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 12.00m
```

- Ref: https://listman.redhat.com/archives/lvm-devel/2016-September/msg00048.html

```bash
[root@BearTest-1 ~]# lvs -a | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert
  root                anystor-e -wi-ao---- 43.80g
  swap                anystor-e -wi-ao----  5.00g
  [lvol0_pmspare]     thinpool  ewi------- 24.00m
  thinvol             thinpool  Vwi-aotz-- 80.00g tp_thinpool         37.99
  tp_thinpool         thinpool  twi-aotz-- 48.00g                     66.76  42.59
  [tp_thinpool_tdata] thinpool  Twi-ao---- 48.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 24.00m


lvcreate -s -n snap400 thinpool/thinvol
...
lvcreate -s -n snap930 thinpool/thinvol
  WARNING: Sum of all thin volume sizes (<51.74 TiB) exceeds the size of thin pool thinpool/tp_thinpool and the size of whole volume group (<50.00 GiB).
  Logical volume "snap930" created.


lvcreate -s -n snap931 thinpool/thinvol
  Cannot create new thin volume, free space in thin pool thinpool/tp_thinpool reached threshold.

[root@BearTest-1 ~]# lvs -a | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert
  root                anystor-e -wi-ao---- 43.80g
  swap                anystor-e -wi-ao----  5.00g
  [lvol0_pmspare]     thinpool  ewi------- 24.00m
  thinvol             thinpool  Vwi-aotz-- 80.00g tp_thinpool         37.99
  tp_thinpool         thinpool  twi-aotz-- 48.00g                     67.75  80.01
  [tp_thinpool_tdata] thinpool  Twi-ao---- 48.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 24.00m

// 시간이 지나고

[root@BearTest-1 ~]# lvs -a | grep -v snap
  LV                  VG        Attr       LSize  Pool        Origin  Data%  Meta%  Move Log Cpy%Sync Convert
  root                anystor-e -wi-ao---- 43.80g
  swap                anystor-e -wi-ao----  5.00g
  [lvol0_pmspare]     thinpool  ewi------- 36.00m
  thinvol             thinpool  Vwi-aotz-- 80.00g tp_thinpool         37.99
  tp_thinpool         thinpool  twi-aotz-- 48.00g                     67.77  57.06
  [tp_thinpool_tdata] thinpool  Twi-ao---- 48.00g
  [tp_thinpool_tmeta] thinpool  ewi-ao---- 36.00m



lvcreate -s -n snap1072 thinpool/thinvol
  WARNING: Sum of all thin volume sizes (<51.82 TiB) exceeds the size of thin pool thinpool/tp_thinpool and the size of whole volume group (<50.00 GiB).
  Logical volume "snap1072" created.
```

#### PV metadata: too large for circular buffer

- Ref: https://ibug.io/blog/2022/06/lvm-metadata-full/

```bash
[root@localhost ~]# lvcreate -s -n snap1400 pizza/chicken
  WARNING: Sum of all thin volume sizes (<14.68 TiB) exceeds the size of thin pool pizza/tp_pizza and the size of whole volume group (199.98 GiB).
  WARNING: You have not turned on protection against thin pools running out of space.
  WARNING: Set activation/thin_pool_autoextend_threshold below 100 to trigger automatic extension of thin pools before they get full.
  VG pizza metadata on /dev/sdc (521866 bytes) too large for circular buffer (1043968 bytes with 521901 used)
  Failed to write VG pizza.



[root@localhost ~]# pvdisplay -C -o name,mda_size,mda_free
  PV         PMdaSize  PMdaFree
  /dev/sdb    1020.00k   509.50k
  /dev/sdc    1020.00k        0
  /dev/sdd    1020.00k        0
  /dev/sde    1020.00k        0
  /dev/sdf    1020.00k        0
[root@localhost ~]# vgdisplay -C -o name,mda_size,mda_free
  VG    VMdaSize  VMdaFree
  pizza  1020.00k        0
```

<code style="color:white; background:#994444;">
<span>
Cause: The MDA of PV is fixed at the time of creation.
</span>
</code>

- Add additional PV to the VG to free up metadata space.
- follow next step:

1. Add new LUN or HDD
2. Remove any extra LVs to allow for additional metadata.(In my case, remove the extra snapshot)

```bash
[root@localhost ~]# lvremove pizza/snap_1400
...

[root@localhost ~]# pvdisplay -C -o name,mda_size,mda_free
  PV         PMdaSize  PMdaFree
  /dev/sdb    1020.00k   509.50k
  /dev/sdc    1020.00k    34.00k
  /dev/sdd    1020.00k    34.00k
  /dev/sde    1020.00k    34.00k
  /dev/sdf    1020.00k    34.00k
```

3. Change new block device to PV and add to VG

```bash
[root@localhost ~]# pvcreate --metadatasize 64m /dev/sdg
  Physical volume "/dev/sdg" successfully created.

[root@localhost ~]# vgextend pizza /dev/sdg
  Volume group "pizza" successfully extended
```

<code style="color:white; background:#994444;">
<span>
LVMs essentially store identical copies of metadata on all PVs belonging to the same VG, requiring guidance to prevent them from being stored on older PVs
</span>
</code>

```bash
[root@localhost ~]# pvdisplay -C -o name,mda_size,mda_free
  PV         PMdaSize  PMdaFree
  /dev/sdb    1020.00k   509.50k
  /dev/sdc    1020.00k    34.00k
  /dev/sdd    1020.00k    34.00k
  /dev/sde    1020.00k    34.00k
  /dev/sdf    1020.00k    34.00k
  /dev/sdg     <65.00m    32.03m

[root@localhost ~]# pvchange --metadataignore y /dev/sdc
  Physical volume "/dev/sdc" changed
  1 physical volume changed / 0 physical volumes not changed
[root@localhost ~]# pvchange --metadataignore y /dev/sdd
  Physical volume "/dev/sdd" changed
  1 physical volume changed / 0 physical volumes not changed
[root@localhost ~]# pvchange --metadataignore y /dev/sde
  Physical volume "/dev/sde" changed
  1 physical volume changed / 0 physical volumes not changed
[root@localhost ~]# pvchange --metadataignore y /dev/sdf
  Physical volume "/dev/sdf" changed
  1 physical volume changed / 0 physical volumes not changed
[root@localhost ~]# pvdisplay -C -o name,mda_size,mda_free
  PV         PMdaSize  PMdaFree
  /dev/sdb    1020.00k   509.50k
  /dev/sdc    1020.00k        0
  /dev/sdd    1020.00k        0
  /dev/sde    1020.00k        0
  /dev/sdf    1020.00k        0
  /dev/sdg     <65.00m    32.03m

```

- Than you can create more snapshots

```bash
[root@localhost ~]# lvcreate -s -n snap1400 pizza/chicken
  WARNING: Sum of all thin volume sizes (<15.11 TiB) exceeds the size of thin pool pizza/tp_pizza and the size of whole volume group (<249.92 GiB).
  WARNING: You have not turned on protection against thin pools running out of space.
  WARNING: Set activation/thin_pool_autoextend_threshold below 100 to trigger automatic extension of thin pools before they get full.
  Logical volume "snap1400" created.

[root@localhost ~]# pvs -o +pv_mda_size,pv_mda_free
  PV         VG    Fmt  Attr PSize   PFree   PMdaSize  PMdaFree
  /dev/sdb         lvm2 ---   50.00g  50.00g  1020.00k   509.50k
  /dev/sdc   pizza lvm2 a--  <50.00g  39.96g  1020.00k        0
  /dev/sdd   pizza lvm2 a--  <50.00g <50.00g  1020.00k        0
  /dev/sde   pizza lvm2 a--  <50.00g <50.00g  1020.00k        0
  /dev/sdf   pizza lvm2 a--  <50.00g  49.96g  1020.00k        0
  /dev/sdg   pizza lvm2 a--   49.93g  49.93g   <65.00m    31.94m

```
