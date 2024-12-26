---
layout: post
title: 리눅스에서 Hardware Disk 정보 확인하는 방법
categories: [Disk]
description: Disk 정보를 확인할 수 있는 방법을 나열합니다.
keywords: Disk, Linux
toc: true
toc_sticky: true
---

### 디스크 정보 확인 방법

```bash
# udev 장치 관리 데몬 정보:
#   장치의 물리적 경로, UUID, ID, 모델명, 벤더 정보를 가져오는 데 유용
udevadm info /dev/vdb
P: /devices/pci0000:00/...
N: vdb
S: disk/by-id/...
E: DEVNAME=/dev/vdb
E: ID_MODEL=VIRTUAL_DISK

# 디스크의 상세 정보:
#  디스크의 하드웨어 수준 정보를 확인
hdparm -I /dev/vdb
/dev/vdb:
  ATA device, with non-removable media
    Model Number:       VIRTUAL_DISK
    Serial Number:      1234567890
    Firmware Revision:  1.0
    Transport:          Serial

# 블록 장치 목록 출력:
#   디스크의 고유 식별 정보 (WWN, UUID, SERIAL) 확인 가능
lsblk -d -o name,type,serial,uuid,wwn,vendor,model,label,kname
NAME TYPE SERIAL   UUID                                 WWN        VENDOR  MODEL         LABEL KNAME
vdb  disk ABC123  2fa1773c-8c51-4ac9-9dfb-37a41651d457 0x5000abcd VIRTUAL DISK          -     vdb

# 블록 장치의 UUID, 파일 시스템 타입, 라벨 정보 표시:
#   블록 장치의 UUID 및 파일 시스템 정보를 빠르게 확인
blkid -i /dev/vdb
/dev/vdb: UUID="2fa1773c-8c51-4ac9-9dfb-37a41651d457" TYPE="ext4" PARTUUID="abcd1234"

# 디스크 관련 하드웨어 정보 표시:
#   USB/SATA/IDE 등 인터페이스 정보까지 확인 가능
lshw -C disk
*-disk
     description: SCSI Disk
     product: VIRTUAL_DISK
     vendor: VENDOR_NAME
     physical id: 0.0.0
     bus info: scsi@0:0.0.0
     logical name: /dev/vdb
     size: 50GiB
     capabilities: partitioned

# 디스크 SMART(Self-Monitoring, Analysis, and Reporting Technology) 정보
#    에러율, 온도, 펌웨어 정보, 디스크 수명 관련 통계 제공
smartctl -x /dev/vdb
SMART overall-health self-assessment test result: PASSED
Vendor Specific SMART Attributes with Thresholds:
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate     0x000f   100   100   000    Pre-fail  Always       -       0

```

---

### 참조

- https://www.cyberciti.biz/faq/find-hard-disk-hardware-specs-on-linux/#google_vignette
