---
layout: post
title: Thin send recv 오픈 소스 분석
categories: [LVM, Thin, DR]
description: Thin send recv 오픈 소스를 분석합니다.
keywords: LVM, Thin, DR
toc: true
toc_sticky: true
---

### 오픈 소스 분석

오픈 소스인 [thin send/recv](https://github.com/LINBIT/thin-send-recv/tree/master) 를 통해서도 ZFS 의 send/recv 와 동일한 구성할 수 있습니다.

thin send/recv 에서는 다음과 같은 서비스를 제공합니다.

- send/recv 프로세스는 다음과 같이 동작할 수 있습니다.

```bash
$ thin_send ssd_vg/CentOS7.6 ssd_vg/li0 | ssh root@target-machine thin_recv kubuntu-vg/li0
```

- 또는 스트리밍을 socat 을 통해서 사용할 수 있습니다.

```bash
target-machine$ socat TCP-LISTEN:4321 STDOUT | zstd -d | thin_recv kubuntu-vg/li0

source-machine$ thin_send ssd_vg/CentOS7.6 ssd_vg/li0 | zstd | socat STDIN TCP:10.43.8.39:4321
```

### 소스 설명

1. `get_thin_pool_dm_path` : lvs 로 thin pool 의 device-mapper 경로 반환
2. `thin_send_diff` : 두 개의 스냅샷 간의 차이를 계산하고 전송
3. `get_snap_info` : lvs 로 `vg_name`, `lv_name`, `pool_lv`, `lv_dm_path`, `thin_id`, `attr` 필드 확인
4. `reserve_metadata_snap` : thin pool 의 device-mapper 경로에 대해 메타데이터 스냅을 예약
   1. dmsetup message <thin_pool_dm_path>-tpool 0 reserve_metadata_snap
   2. release 도 있음.
5. `parsediff` : 주어진 스트림에서 차이(diff) 정보를 파싱하고, 이를 처리하는 함수
   1. superblock > blocksize
   2. left_only 면 begin lengh 읽음
      1. send*header ( begin * block*size * 512 ~ length* block_size * 512, 1[CMD_UNMAP]), unmap++, chuck++
   3. rigth*only 또는 diff 면 send_chuck (infd, outfd, begin * blocksize _ 512 ~ length _ block*size * 512, each block_size \* 512 ), unmap++, chuck++
6. `send_header` : 주어진 파일 디스크립터(`out_fd`)로 헤더 정보를 전송하는 함수
   1. magic(64b), offset(64b), length(64b), cmd(32b)
7. `send_chuck` : send_header(CMD_DATA:0) + copy_data
8. `send_end_stream` : send_header + etc
9. `parse_dump` : 주어진 스트림에서 덤프(dump) 정보를 파싱하고, 이를 처리하는 함수
   1. superblock > block_size
   2. single_mapping : origin_block, length = 1
   3. range_mapping : origin_begin, length
   4. send*chuck (infd, outfd, begin * block*size * 512 ~ length _ block_size _ 512, each block_size \* 512)

### Send

---

다음의 결과를 가지고, 정보를 송출

```bash
# 스냅샷 차이 정보

$ lvs -o vg_name,lv_name,pool_lv,lv_dm_path,thin_id,attr
  VG     LV        Pool      DMPath                       ThId Attr
  ThinVP ThinSnap  tp_ThinVP /dev/mapper/ThinVP-ThinSnap     2 Vwi---tz-k
  ThinVP ThinSnap2 tp_ThinVP /dev/mapper/ThinVP-ThinSnap2    3 Vwi---tz-k
  ThinVP Thinvol   tp_ThinVP /dev/mapper/ThinVP-Thinvol      1 Vwi-aotz--
  ThinVP tp_ThinVP           /dev/mapper/ThinVP-tp_ThinVP      twi-aotz--
  centos root                /dev/mapper/centos-root           -wi-ao----
  centos swap                /dev/mapper/centos-swap           -wi-a-----

$ dmsetup message /dev/mapper/ThinVP-tp_ThinVP-tpool 0 reserve_metadata_snap

# 볼륨을 전송한다면 다음과 같이
# 1 : ThinVol 의 Thin ID
$ thin_dump -m --dev-id 1 /dev/mapper/ThinVP-tp_ThinVP_tmeta
<superblock uuid="" time="0" transaction="1" flags="0" version="2" data_block_size="128" nr_data_blocks="0">
  <device dev_id="1" mapped_blocks="177" transaction="0" creation_time="0" snap_time="0">
    <range_mapping origin_begin="0" data_begin="2" length="2" time="0"/>
    <single_mapping origin_block="20480" data_block="164" time="0"/>
    <single_mapping origin_block="40960" data_block="165" time="0"/>
    <single_mapping origin_block="61440" data_block="166" time="0"/>
    <single_mapping origin_block="81920" data_block="167" time="0"/>
    <single_mapping origin_block="102400" data_block="168" time="0"/>
    <single_mapping origin_block="122880" data_block="169" time="0"/>
    <single_mapping origin_block="143360" data_block="170" time="0"/>
    <single_mapping origin_block="163840" data_block="171" time="0"/>
    <range_mapping origin_begin="163841" data_begin="4" length="160" time="0"/>
    <single_mapping origin_block="184320" data_block="172" time="0"/>
    <single_mapping origin_block="204800" data_block="173" time="0"/>
    <single_mapping origin_block="225280" data_block="174" time="0"/>
    <single_mapping origin_block="245760" data_block="175" time="0"/>
    <single_mapping origin_block="266240" data_block="176" time="0"/>
    <single_mapping origin_block="286720" data_block="177" time="0"/>
    <single_mapping origin_block="307200" data_block="178" time="0"/>
  </device>
</superblock>


# 차이점을 전송한다면 다음과 같이
# 2 : ThinSnap 의 Thin ID
# 3 : ThinSnap2 의 Thin ID
$ thin_delta -m --snap1 2 --snap2 3 /dev/mapper/ThinVP-tp_ThinVP_tmeta

<superblock uuid="" time="2" transaction="3" data_block_size="128" nr_data_blocks="0">
  <diff left="2" right="3">
    <different begin="0" length="1"/>
    <same begin="1" length="1"/>
    <right_only begin="233" length="1"/>
    <same begin="51200" length="1"/>
    <same begin="102400" length="1"/>
    <same begin="153600" length="1"/>
    <same begin="204800" length="1"/>
    <same begin="256000" length="1"/>
    <same begin="307200" length="1"/>
    <same begin="358400" length="1"/>
    <same begin="409600" length="1"/>
    <different begin="409601" length="1"/>
    <same begin="409602" length="399"/>
    <same begin="460800" length="1"/>
    <same begin="512000" length="1"/>
    <same begin="563200" length="1"/>
    <same begin="614400" length="1"/>
    <same begin="665600" length="1"/>
    <same begin="716800" length="1"/>
    <same begin="768000" length="1"/>
    <same begin="819198" length="2"/>
  </diff>
</superblock>

$ dmsetup message /dev/mapper/ThinVP-tp_ThinVP-tpool 0 release_metadata_snap

# ThinSnap 의 device-mapper 를 통해서 위 정보의 위치 값을 전달


# --------------------------------------------------

# Thin Vol
$ dmsetup message /dev/mapper/ThinVP-tp_ThinVP-tpool 0 reserve_metadata_snap

$ thin_dump -m --dev-id 1 /dev/mapper/ThinVP-tp_ThinVP_tmeta

<superblock uuid="" time="2" transaction="3" flags="0" version="2" data_block_size="128" nr_data_blocks="0">
  <device dev_id="1" mapped_blocks="420" transaction="0" creation_time="0" snap_time="2">
    <single_mapping origin_block="0" data_block="422" time="2"/>
    <single_mapping origin_block="1" data_block="3" time="0"/>
    <single_mapping origin_block="233" data_block="421" time="1"/>
    <single_mapping origin_block="51200" data_block="404" time="0"/>
    <single_mapping origin_block="102400" data_block="405" time="0"/>
    <single_mapping origin_block="153600" data_block="406" time="0"/>
    <single_mapping origin_block="204800" data_block="407" time="0"/>
    <single_mapping origin_block="256000" data_block="408" time="0"/>
    <single_mapping origin_block="307200" data_block="409" time="0"/>
    <single_mapping origin_block="358400" data_block="410" time="0"/>
    <single_mapping origin_block="409600" data_block="411" time="0"/>
    <single_mapping origin_block="409601" data_block="423" time="2"/>
    <range_mapping origin_begin="409602" data_begin="5" length="399" time="0"/>
    <single_mapping origin_block="460800" data_block="412" time="0"/>
    <single_mapping origin_block="512000" data_block="413" time="0"/>
    <single_mapping origin_block="563200" data_block="414" time="0"/>
    <single_mapping origin_block="614400" data_block="415" time="0"/>
    <single_mapping origin_block="665600" data_block="416" time="0"/>
    <single_mapping origin_block="716800" data_block="417" time="0"/>
    <single_mapping origin_block="768000" data_block="418" time="0"/>
    <range_mapping origin_begin="819198" data_begin="0" length="2" time="0"/>
  </device>
</superblock>

$ dmsetup message /dev/mapper/ThinVP-tp_ThinVP-tpool 0 release_metadata_snap

# ThinVol 의 device-mapper 를 통해서 위 정보의 위치 값을 전달

# 데이터 전달시에는 SPICE_F_MOVE 및 POXIS_FADV_DONTNEED 를 통해서 전달
```

---

### 참조

- https://github.com/LINBIT/thin-send-recv
