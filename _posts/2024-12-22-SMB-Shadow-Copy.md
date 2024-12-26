---
layout: post
title: Shadow copy 스냅샷 생성 및 지정
categories: [SMB, Shadow Copy]
description: Shadow Copy 를 생성하는 스크립트를 제공합니다.
keywords: SMB, vfs, ShadowCopy, Snapshot
toc: true
toc_sticky: true
---

### Shadow Copy 스냅샷 생성 및 지정

#### linux share snapshot

```bash
# share.conf
vfs objects = shadow_copy2
shadow:snapdir = /export/TEST/snapshots
shadow:localtime = yes
```

#### 실제 스냅샷 생성 및 마운트

```bash
lvcreate -L2000M -s -n TEST-SanpTest-GMT-2023.11.08-10.12.00 /dev/mapper/TEST-SanpTest
mkdir -p /export/TEST/snapshots/@GMT-2023.11.08-10.12.00
mount /dev/TEST/TEST-SanpTest-GMT-2023.11.08-10.12.00 /export/TEST/snapshots/@GMT-2023.11.08-10.12.00 -o ro,nouuid
# xfs 만 nouuid
```

### 생성 스크립트

```sh
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en

Root=/dev
Vol=TEST
Share=SanpTest

VolumeDevice=${Root}/${Vol}/${Share}
SnapDate=$(date -u +%Y.%m.%d-%H.%M).00
SnapSize=2000
SnapShot=${VolumeDevice}-GMT-${SnapDate}

ShadowPath=/export/TEST/snapshots
ShadowName=@GMT-${SnapDate}
ShadowFile=${ShadowPath}/${ShadowName}

lvcreate -L${SnapSize}M -s -n ${SnapShot##*/} ${VolumeDevice}
mkdir -p ${ShadowFile}
mount /dev/TEST/${SnapShot##*/} ${ShadowFile} -o ro,nouuid
```
