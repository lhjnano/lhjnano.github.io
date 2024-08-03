---
layout: post
title: Multifunction 네트워크 인터페이스 카드
categories: [Storage, Network]
description: SAN 과 Inifniband 의 차이점과 Multipath 설정방법에 대해서 설명합니다. 
keywords: Network, Storage, SAN, Infiniband
toc: true
toc_sticky: true
---


## SAN(Storage Area Network)

SAN은 고속 네트워크를 통해 스토리지 장치와 서버를 연결하는 기술입니다. 주로 데이터 센터에서 대규모 스토리지 시스템을 효율적으로 관리하고 데이터 전송 속도를 높이기 위해 사용됩니다.

<br>

### 주요 특징

* 스토리지 장치와 서버를 광케이블 또는 케이블로 연결하여 공유
* 대용량 스토리지를 관리

<br>

### 인터페이스 카드

- **HBA (Host Bus Adapter)**: 서버와 SAN 스위치를 연결하는 데 사용되는 카드입니다.
- **FC (Fibre Channel)**: 고속 데이터 전송을 위해 주로 사용되며, 16Gbps 또는 32Gbps의 전송 속도를 지원합니다.

<br>

### 제조사별 연결 방법

- **EMC**: EMC SAN 시스템은 주로 FC 기반의 HBA를 사용하며, EMC의 전용 스위치와 연결됩니다.
- **NetApp**: NetApp은 FC 및 iSCSI 기반의 SAN 솔루션을 제공하며, 다양한 HBA와 호환됩니다.
- **HPE**: HPE는 FC 및 FCoE(Fibre Channel over Ethernet) 기반의 SAN 시스템을 제공하며, HPE의 SAN 스위치와 연결할 수 있습니다.

<br>

### 제조사별 Multipath 설정 방법

Multipath 도구는 동일합니다. 

```bash
# Multipath 도구 설치 
sudo yum install device-mapper-multipath

# 제조사별 Multi 패스 설정
...

# Multipath 서비스 시작
sudo systemctl enable multipathd
sudo systemctl start multipathd
```

<br>

1. EMC 설정 파일

```bash
sudo cat << EOF > /etc/multipath.conf
devices {
    device {
        vendor "DGC"
        product ".*"
        product_blacklist "LUNZ"
        :
        path_checker emc_clariion   ### Rev 47 alua
        hardware_handler "1 alua"   ### modified for alua
        prio alua                   ### modified for alua
        :
    }
}
EOF


# 설정파일 설명
- vendor "DGC": 스토리지 장치의 벤더 이름을 지정합니다. 여기서 "DGC"는 EMC Clariion/VNX 스토리지 시스템을 의미합니다.
- product ".*": 스토리지 장치의 제품 이름을 지정합니다. ".*"는 모든 제품을 의미하며, 특정 제품을 지정하지 않습니다.
- product_blacklist "LUNZ": 특정 제품을 블랙리스트에 추가하여 multipath 설정에서 제외합니다. "LUNZ"는 EMC 스토리지의 기본 LUN을 의미합니다.
- path_checker emc_clariion: 경로 검사 방법을 지정합니다. "emc_clariion"은 EMC Clariion/VNX 스토리지 시스템에 특화된 경로 검사 방법입니다.
- hardware_handler "1 alua": 하드웨어 핸들러를 지정합니다. "1 alua"는 ALUA(Asymmetric Logical Unit Access) 모드를 사용하여 스토리지 장치와의 상호 작용을 관리합니다.
- prio alua: 경로 우선순위 설정을 지정합니다. "alua"는 ALUA를 사용하여 경로의 우선순위를 결정합니다.
```

<br>

2. NetApp 설정 파일

```bash
sudo cat << EOF > /etc/multipath.conf
defaults {
        failback "immediate"
        find_multipaths "yes"
        path_grouping_policy "multibus"
        path_selector "round-robin 0"
        user_friendly_names "yes"
}
devices {
        device {
                vendor "NETAPP"
                product "LUN.*"
                path_checker "tur"
                features "3 queue_if_no_path pg_init_retries 50"
                hardware_handler "0"
                prio "ontap"
                rr_weight "uniform"
                rr_min_io 128
                flush_on_last_del "yes"
                dev_loss_tmo "infinity"
                retain_attached_hw_handler yes
                detect_prio yes
                user_friendly_names  "yes"
        }
}
EOF

# 설정파일 설명
- failback "immediate": 경로가 복구되면 즉시 원래의 활성 경로로 복귀합니다.
- find_multipaths "yes": multipath 장치 검색을 활성화합니다.
- path_grouping_policy "multibus": 경로 그룹화 정책을 "multibus"로 설정합니다. 이는 여러 경로를 그룹화하여 다중 경로로 사용할 수 있게 합니다.
- path_selector "round-robin 0": 경로 선택 방법을 라운드 로빈 방식으로 설정합니다.
- user_friendly_names "yes": 사용자 친화적인 이름을 사용합니다. 이는 장치 경로를 쉽게 식별할 수 있도록 합니다.
- vendor "NETAPP": 장치의 제조사를 NETAPP으로 지정합니다. 이는 특정 제조사에 대한 설정을 적용하는 데 사용됩니다.
- product "LUN.*": 모든 NETAPP LUN(Logical Unit Number) 제품에 대해 이 설정을 적용합니다. 특정 제품을 지정할 수도 있습니다.
- path_checker "tur": 경로의 유효성을 검사할 때 "tur" (Test Unit Ready) 검사기를 사용합니다. 이는 장치가 준비 상태인지 확인하는 데 사용됩니다.
- features "3 queue_if_no_path pg_init_retries 50":
    - queue_if_no_path: 경로가 없을 때 I/O를 대기열에 넣는 기능을 활성화합니다.
    - pg_init_retries 50: 경로 그룹 초기화를 50번 재시도합니다.
- hardware_handler "0": 기본 하드웨어 핸들러를 사용합니다. 이는 특정 하드웨어에 대한 특수 처리를 가능하게 합니다.
- prio "ontap": ONTAP 우선순위 설정을 사용합니다. 이는 다양한 경로의 우선순위를 관리하는 데 사용됩니다.
- rr_weight "uniform": 라운드 로빈 방식에서 모든 경로에 동일한 가중치를 부여합니다.
- rr_min_io 128: 라운드 로빈 방식에서 최소 I/O를 128로 설정합니다.
- flush_on_last_del "yes": 마지막 경로가 제거될 때 I/O를 플러시합니다.
- dev_loss_tmo "infinity": 장치 손실 시간 초과를 무한대로 설정합니다.
- retain_attached_hw_handler yes: 연결된 하드웨어 핸들러를 유지합니다.
- detect_prio yes: 경로 우선순위 감지를 활성화합니다.
```

<br>

3. HPE 설정 파일

```bash
# 설정파일은 product 별로 다를 수 있습니다.
sudo cat << EOF > /etc/multipath.conf
device {
		vendor "HP"
		product "MSA2[02]12fc|MSA2012i"
		getuid_callout "/sbin/scsi_id -g -u -s /block/%n"
		hardware_handler "0"
		path_selector "round-robin 0"
		path_grouping_policy multibus
		failback immediate
		rr_weight uniform
		rr_min_io 100
		no_path_retry 18
		path_checker tur
}
EOF

# 설정파일 설명 
- vendor "HP": 장치의 제조사를 HP로 지정합니다. 이는 특정 제조사에 대한 설정을 적용하는 데 사용됩니다.
- product "MSA2[02]12fc|MSA2012i": HP MSA2012fc 및 MSA2012i 제품에 대해 이 설정을 적용합니다.
- getuid_callout "/sbin/scsi_id -g -u -s /block/%n": SCSI 장치의 고유 ID를 가져오는 데 사용되는 명령어입니다. 이 설정은 각 장치를 고유하게 식별하는 데 사용됩니다.
- hardware_handler "0": 기본 하드웨어 핸들러를 사용합니다. 이는 특정 하드웨어에 대한 특수 처리를 가능하게 합니다.
- path_selector "round-robin 0": 경로 선택 방법을 라운드 로빈 방식으로 설정합니다. 이는 각 경로를 순환하면서 I/O를 배분하는 방식입니다.
- path_grouping_policy multibus: 경로 그룹화 정책을 "multibus"로 설정합니다. 이는 여러 경로를 그룹화하여 다중 경로로 사용할 수 있게 합니다.
- failback immediate: 경로가 복구되면 즉시 원래의 활성 경로로 복귀합니다.
- rr_weight uniform: 라운드 로빈 방식에서 모든 경로에 동일한 가중치를 부여합니다.
- rr_min_io 100: 라운드 로빈 방식에서 최소 I/O를 100으로 설정합니다.
- no_path_retry 18: 모든 경로가 실패한 경우 18번 재시도합니다.
- path_checker tur: 경로의 유효성을 검사할 때 "tur" (Test Unit Ready) 검사기를 사용합니다. 이는 장치가 준비 상태인지 확인하는 데 사용됩니다.
```

<br>

4. HITACHI Multipath 설정파일


```bash
sudo cat << EOF > /etc/multipath.conf
device {
		vendor "HITACHI"
		product "OPEN-.*"             ###
		path_grouping_policy multibus
		getuid_callout "/lib/udev/scsi_id --whitelisted --device=/dev/%n"
		path_selector "round-robin 0"
		path_checker tur
		features "0"
		hardware_handler "0"
		prio const
		rr_weight uniform
		no_path_retry 6
		rr_min_io 1000
		rr_min_io_rq 1
}
EOF

# 설정파일 설명
- vendor "HITACHI": 장치의 제조사를 HITACHI로 지정합니다. 이는 특정 제조사에 대한 설정을 적용하는 데 사용됩니다.
- product "OPEN-.*": "OPEN-"으로 시작하는 모든 HITACHI 제품에 대해 이 설정을 적용합니다. 특정 제품을 지정할 수도 있습니다.
- path_grouping_policy multibus: 경로 그룹화 정책을 "multibus"로 설정합니다. 이는 여러 경로를 그룹화하여 다중 경로로 사용할 수 있게 합니다.
- getuid_callout "/lib/udev/scsi_id --whitelisted --device=/dev/%n": SCSI 장치의 고유 ID를 가져오는 데 사용되는 명령어입니다. 이 설정은 각 장치를 고유하게 식별하는 데 사용됩니다.
- path_selector "round-robin 0": 경로 선택 방법을 라운드 로빈 방식으로 설정합니다. 이는 각 경로를 순환하면서 I/O를 배분하는 방식입니다.
- path_checker tur: 경로의 유효성을 검사할 때 "tur" (Test Unit Ready) 검사기를 사용합니다. 이는 장치가 준비 상태인지 확인하는 데 사용됩니다.
- features "0": 특정 기능을 비활성화합니다. 이 경우, 추가적인 기능은 사용되지 않습니다.
- hardware_handler "0": 기본 하드웨어 핸들러를 사용합니다. 이는 특정 하드웨어에 대한 특수 처리를 가능하게 합니다.
- prio const: 경로 우선순위를 일정하게 유지합니다.
- rr_weight uniform: 라운드 로빈 방식에서 모든 경로에 동일한 가중치를 부여합니다.
- no_path_retry 6: 모든 경로가 실패한 경우 6번 재시도합니다.
- rr_min_io 1000: 라운드 로빈 방식에서 최소 I/O를 1000으로 설정합니다.
- rr_min_io_rq 1: 각 I/O 요청마다 최소 1개의 I/O를 처리합니다.
```


<br>
<br>


## Infiniband

Infiniband는 고성능 컴퓨팅 환경에서 주로 사용되는 고속 인터커넥트 기술입니다. 주로 슈퍼컴퓨터, 데이터 센터 및 고성능 컴퓨팅 클러스터에서 사용됩니다.

<br>

### 주요 특징

- **고속 데이터 전송**: 최대 200Gbps의 데이터 전송 속도를 지원합니다.
- **저지연**: 매우 낮은 레이턴시를 제공하여 실시간 데이터 처리가 가능합니다.
- **확장성**: 수천 개의 노드를 연결할 수 있는 확장성을 제공합니다.
- **QoS (Quality of Service)**: 네트워크 트래픽을 효율적으로 관리하여 높은 품질의 서비스를 제공합니다.

<br>

### 인터페이스 카드

- **HCA (Host Channel Adapter)**: 서버와 Infiniband 스위치를 연결하는 데 사용되는 카드입니다.
- **Infiniband Adapters**: Mellanox, Intel 등의 제조사에서 다양한 속도와 기능을 제공하는 어댑터를 생산합니다.

<br>

### 설정 방법

OpenSM은 Infiniband 네트워크에서 Subnet Manager(SM) 역할을 하는 오픈 소스 소프트웨어입니다. Subnet Manager는 Infiniband 패브릭 내의 모든 장치와 연결을 관리하고, 경로를 설정하며, 네트워크의 상태를 모니터링하는 중요한 구성 요소입니다.

<br>

1. **OpenSM 설치**:
    
```bash
sudo yum install opensm
```

<br>

2. **OpenSM 서비스 시작**:
    
```bash
sudo systemctl enable opensm
sudo systemctl start opensm
```

<br>

3. **설정 파일 수정 (필요한 경우)**:

기본 설정 파일은 `/etc/rdma/opensm.conf`에 위치해 있습니다. 필요에 따라 이 파일을 수정하여 네트워크 환경에 맞게 설정할 수 있습니다.
    
```bash
# OpenSM 설정 파일
sudo vi /etc/rdma/opensm.conf

# OpenSM 추가 옵션
OPENSM_OPTIONS="-l /var/log/opensm.log"

# Subnet Manager 우선순위 (기본값: 8)
SM_PRIORITY=8

# 관리할 HCA의 GUID (ibstat 을 통해서 Active 되어 있는 Port GUID 정보를 확인할 수 있습니다.)
GUID="0x0011750000584d00"

# 관리할 포트
PORTS="1,2"

# 시스템 재부팅 시 OpenSM 서비스 자동 시작 (기본값: yes)
RESTART_ON_REBOOT=yes
```

<br>

## 참고

---

1. EMC Multipath 설정 파일 : https://access.redhat.com/solutions/139193
1. Netapp Multipath 설정 파일 : https://access.redhat.com/solutions/2061463
1. HPE Multipath 설정 파일 : https://community.hpe.com/t5/msa-storage/msa2040-multipath-config/td-p/7026677
1. HITACHI Multipath 설정 파일 : https://access.redhat.com/solutions/2598221