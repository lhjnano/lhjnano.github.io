---
layout: post
title: "[AWS 2/16] EC2 & EBS — AWS 컴퓨팅 완전 정복"
categories: [AWS, Compute]
description: EC2 인스턴스 유형, 구매 옵션, EBS 볼륨, 배치 그룹, Elastic IP, 수명주기까지 EC2 컴퓨팅의 모든 것을 정리합니다.
keywords: [EC2, EBS, AWS, 컴퓨팅, 인스턴스, AMI]
toc: true
toc_sticky: true
---

## Hook

> 클라우드에서 가상 서버 한 대를 띄우는 데 고려할 것이 왜 이렇게 많을까요? 인스턴스 유형만 수십 종, 구매 옵션 네 가지, 스토리지도 영구와 임시로 나뉩니다. 그럼에도 EC2는 AWS 컴퓨팅의 심장입니다.

EC2는 필요한 만큼 가상 서버를 프로비저닝하고 보안·네트워크·스토리지를 관리하는 서비스입니다. 이 글에서는 EC2의 핵심 구성 요소 — 인스턴스 유형, 구매 옵션, EBS, AMI, 배치 그룹, 수명주기, RAID — 를 2026년 최신 기준으로 정리합니다.

---

## TL;DR

- **인스턴스 선택**: 범용은 M/T 시리즈, 컴퓨팅은 C, 메모리는 R/X, GPU는 P/Inf/Trn, 스토리지는 I/D — Graviton 기반이 가성비 최고입니다
- **비용 최적화**: 프로덕션은 Savings Plans(최대 72% 할인), 배치/CI·CD는 스팟(최대 90% 할인)으로 조합합니다
- **스토리지 전략**: 영구 데이터는 gp3 EBS, 고성능 I/O는 인스턴스 스토어, 고가용성은 RAID 1을 사용합니다
- **배치 제어**: HPC는 Cluster, 분산 시스템은 Partition, 중요 인스턴스 격리는 Spread로 물리적 배치를 제어합니다

---

## Part 1: EC2 개요와 스토리지

### EC2 기본 아키텍처

EC2는 VPC 내 서브넷에 인스턴스를 프로비저닝하고, Internet Gateway를 통해 외부 통신을 수행합니다.

![Amazon EC2 기본 아키텍처](/assets/images/posts/aws-ec2-computing/02-01-amazon-elastic-cloud-compute-ec2.svg)

EC2의 기본 동작은 네 가지입니다.

| 동작 | 효과 | EBS | IP |
|------|------|-----|----|
| **Start** | 중지된 인스턴스를 실행 상태로 전환 | 유지 | 유지(재할당) |
| **Stop** | 일시 정지, 컴퓨팅 요금 미부과 | 유지 | 공인 IP 해제 |
| **Terminate** | 영구 삭제, 복구 불가 | 기본 삭제 | 해제 |
| **Reboot** | OS 재시작 | 유지 | 유지 |

### SSH 접속

EC2 인스턴스는 SSH(Linux) 또는 RDP(Windows)로 원격 접속합니다. 운영체제별 기본 사용자 이름이 다릅니다.

![SSH/RDP 접속 예시](/assets/images/posts/aws-ec2-computing/02-02-ssh-접속.svg)

- Amazon Linux/RHEL/Fedora: `ec2-user`
- Ubuntu: `ubuntu` · Debian: `admin` · CentOS: `centos`
- Windows: `Administrator` (RDP, 포트 3389)

```bash
# Linux SSH 접속
ssh -i my-key.pem ec2-user@ec2-xx-xx-xx-xx.region.compute.amazonaws.com
```

### EBS (Elastic Block Store)

EBS는 EC2에 연결하는 영구 블록 스토리지로, 인스턴스 수명과 무관하게 독립적으로 존재합니다. 네트워크 기반이며, 동일 AZ 내에서만 연결 가능하고, 스냅샷으로 S3에 백업합니다. 최대 64TB까지 지원합니다.

![EBS와 EC2의 관계](/assets/images/posts/aws-ec2-computing/02-03-2-ebs-elastic-block-store.svg)

#### 볼륨 유형

![EBS 볼륨 유형 비교](/assets/images/posts/aws-ec2-computing/02-04-볼륨-유형.svg)

| 유형 | 미디어 | 최대 성능 | 용도 |
|------|--------|----------|------|
| **gp3** ⭐ | SSD | 16,000 IOPS / 1,000MB/s | 대부분 워크로드, 부팅 볼륨 (2026 권장) |
| **io2 Block Express** | SSD | 256,000 IOPS / 4,000MB/s | 고성능 DB, 미션 크리티컬 (99.999% 내구성) |
| **st1** | HDD | 500MB/s | 빅데이터, 로그, DW |
| **sc1** | HDD | 250MB/s | 아카이브, 저빈도 데이터 |

EBS의 핵심 특징은 다음과 같습니다.

- **다중 연결(Multi-Attach)**: io1/io2 볼륨은 최대 16개 인스턴스에 동시 연결 — Oracle RAC, GFS2 등 클러스터 파일 시스템에 활용
- **스냅샷**: S3에 증분 저장, 크로스 리전 복사, Archive로 75% 비용 절감, FSR로 즉시 전체 성능 볼륨 생성
- **암호화**: AES-256 + KMS 연동, Nitro 하드웨어 가속으로 성능 영향 최소

#### EBS vs 인스턴스 스토어

![EBS vs 인스턴스 스토어](/assets/images/posts/aws-ec2-computing/02-05-ebs-vs-인스턴스-스토어.svg)

| 항목 | EBS | 인스턴스 스토어 |
|------|-----|----------------|
| 영속성 | 영구 (독립적) | 임시 (인스턴스 수명 연결) |
| 중지/시작 | 데이터 유지 ✅ | 데이터 손실 ❌ |
| 분리 가능 | 예 | 아니오 |
| 스냅샷 | 지원 | 미지원 |
| 성능 | 네트워크 기반 | 물리 디스크 직접 (빠름) |
| 요금 | GB당 과금 | 인스턴스 요금에 포함 |

인스턴스 스토어는 버퍼·캐시·임시 데이터(scratch)에 적합하며, 데이터베이스나 영구 저장이 필요한 데이터에는 부적합합니다. 중지 불가 — 중지하면 데이터가 손실됩니다.

<details>
<summary><b>EBS 볼륨 생성 및 연결 CLI</b></summary>

```bash
# gp3 볼륨 생성 (3000 IOPS, 125MB/s)
aws ec2 create-volume \
  --availability-zone ap-northeast-2a \
  --volume-type gp3 \
  --size 100 \
  --iops 3000 \
  --throughput 125

# 인스턴스에 볼륨 연결
aws ec2 attach-volume \
  --volume-id vol-0abc123 \
  --instance-id i-0abc123 \
  --device /dev/sdb

# 스냅샷 생성
aws ec2 create-snapshot \
  --volume-id vol-0abc123 \
  --description "Daily backup"

# 크로스 리전 스냅샷 복사
aws ec2 copy-snapshot \
  --source-region ap-northeast-2 \
  --source-snapshot-id snap-0abc123 \
  --destination-region us-east-1 \
  --description "DR copy to us-east-1"
```

</details>

---

## Part 2: 인스턴스 유형과 구매 옵션

### 인스턴스 명명 규칙

![인스턴스 유형 명명 규칙](/assets/images/posts/aws-ec2-computing/02-06-4-인스턴스-유형-2026-업데이트.svg)

인스턴스 이름은 `패밀리 + 세대 + 속성 + 크기`로 구성됩니다. 예: `m7i.xlarge` → 범용(m) + 7세대 + Intel(i) + xlarge 크기.

### 인스턴스 패밀리

| 패밀리 | 분류 | 대표 유형 (2026) | 적합 워크로드 |
|--------|------|-----------------|--------------|
| **M / T** | 범용 | M7g, T4g | 웹 서버, 개발/테스트, 소규모 앱 |
| **C** | 컴퓨팅 최적화 | C7i, C7gn (200Gbps) | HPC, 게임 서버, 배치, ML 추론 |
| **R / X** | 메모리 최적화 | R8g (1.5TB), X2iezn (12TB) | 인메모리 DB, SAP HANA, 빅데이터 |
| **P / Inf / Trn** | 가속 컴퓨팅 | P5 (H100×8), Inf2, Trn1 | ML 훈련/추론, 병렬 컴퓨팅 |
| **I / D / H** | 스토리지 최적화 | I4i (750K IOPS), D3 (384TB) | NoSQL, DW, HDFS |

**AWS Graviton**은 AWS 자체 설계 ARM 프로세서로, x86 대비 최대 40% 향상된 가격/성능 비율을 제공합니다. Graviton4(2026 최신)는 더 큰 메모리 대역폭과 전력 효율을 갖추며, 지속 가능성에도 유리합니다.

### 구매 옵션 비교

![EC2 구매 옵션 비교](/assets/images/posts/aws-ec2-computing/02-07-5-ec2-구매-옵션-2026-업데이트.svg)

| 옵션 | 약정 | 할인율 | 유연성 | 중단 | 적합 용도 |
|------|------|--------|--------|------|----------|
| **온디맨드** | 없음 | 정가 | 최고 ⭐ | 없음 | 테스트, 단기 워크로드 |
| **Savings Plans** | 1/3년 | 최대 72% | 높음 | 없음 | 프로덕션 (Compute=EC2/Fargate/Lambda) |
| **예약(RI)** | 1/3년 | 최대 72% | 중간 | 없음 | 장기 예측 가능 (Standard/Convertible) |
| **스팟** | 없음 | 최대 90% | 낮음 | 있음 ⚠️ | 배치, CI/CD, 빅데이터 |

> 팁: Savings Plans + 스팟 조합으로 최대 비용 절감이 가능합니다. 기본 부하분은 Savings Plans로, 가변 분산 작업은 스팟으로 처리합니다.

**Savings Plans**는 사용량(USD/시간)을 약정하는 유연한 모델입니다. Compute Savings Plans는 EC2/Fargate/Lambda에 자동 적용되며 인스턴스 패밀리·리전·OS 무관합니다. EC2 Instance Savings Plans는 특정 패밀리·리전에 약정하여 최대 할인율을 받습니다.

### 스팟 인스턴스

AWS 클러스러의 미사용 용량을 경매 방식으로 저렴하게 사용합니다. 스팟 가격이 입찰가를 초과하면 2분 전 알림 후 인스턴스가 중단됩니다.

![스팟 인스턴스 중단 흐름](/assets/images/posts/aws-ec2-computing/02-08-스팟-인스턴스-spot.svg)

적합 워크로드: 배치 작업, CI/CD, 빅데이터 분석, HPC, 컨테이너 워크로드. 부적합: 데이터베이스, 중요 서비스 등 중단 불가 워크로드. **Spot Fleet**으로 목표 용량을 자동 유지할 수 있습니다.

추가로 **ODCR(온디맨드 용량 예약)**로 특정 AZ의 용량을 보장하고, **Capacity Blocks for ML**로 미래 특정 기간의 GPU 용량(P5 등)을 예약할 수 있습니다.

---

## Part 3: AMI, 배치 그룹, 네트워크

### AMI (Amazon Machine Image)

AMI는 인스턴스 시작에 필요한 정보를 포함하는 템플릿입니다 — 운영체제, 애플리케이션 서버, 애플리케이션, 블록 디바이스 매핑.

![AMI 구조](/assets/images/posts/aws-ec2-computing/02-09-6-ami-amazon-machine-image.svg)

AMI는 세 가지 구성 요소로 이루어집니다.

1. **루트 볼륨 템플릿** — OS, 애플리케이션, 설정 포함
2. **권한(Launch Permissions)** — 비공개/공개/특정 계정 공유
3. **블록 디바이스 매핑** — 추가 EBS 볼륨 정보

- **EBS 지원 AMI**: 루트가 EBS 스냅샷 — 중지/시작 가능, 기본 권장
- **인스턴스 스토어 지원 AMI**: 루트가 인스턴스 스토어 템플릿 — 중지 불가
- **AWS 마켓플레이스 AMI**: 서드파티 소프트웨어 사전 설치 (Cisco, Fortinet 등)
- AMI는 다른 리전으로 복사, 특정 계정이나 Organization에 공유 가능합니다

### Elastic IP

Elastic IP는 계정에 할당된 고정 공인 IPv4 주소입니다. 동적 퍼블릭 IP가 재시작 시 변경되는 것을 방지합니다.

- 인스턴스에 연결된 경우 무료, **연결되지 않은 IP는 시간당 요금 부과** (유휴 IP 방지)
- 동일 리전 내 다른 인스턴스로 빠르게 재매핑 가능
- 계정당 기본 5개 할당 (증가 요청 가능)
- 가능하면 Route 53 DNS 사용을 권장 — Elastic IP는 보안상 꼭 필요한 경우만

### 배치 그룹 (Placement Groups)

EC2 인스턴스의 물리적 배치 전략을 제어합니다. 인스턴스 시작 시 지정해야 하며, 시작 후에는 변경할 수 없습니다.

![배치 그룹 유형 비교](/assets/images/posts/aws-ec2-computing/02-10-8-배치-그룹-placement-groups.svg)

| 유형 | 배치 | 특징 | 적합 |
|------|------|------|------|
| **Cluster** | 동일 랙 (단일 AZ) | 낮은 지연, 높은 처리량; 랙 장애 시 전체 영향 | HPC, 빅데이터 |
| **Partition** | 파티션별 격리 (최대 7) | 파티션 단위 장애 격리; 전원/네트워크 독립 | Hadoop, Kafka, EMR |
| **Spread** | 별도 하드웨어 랙 (7개/AZ) | 개별 인스턴스만 격리 ✅; 동시 장애 위험 최소 | 중요 인스턴스 격리 |

### ENA (Elastic Network Adapter)

ENA는 SR-IOV 기반 고성능 네트워크 인터페이스로, 대부분의 최신 인스턴스에서 지원합니다.

- 네트워크 성능: 최대 100Gbps (일반), 200Gbps (2026 특정 인스턴스)
- 저지연, 높은 패킷 처리 성능(PPS)
- **EFA (Elastic Fabric Adapter)**: HPC/ML 워크로드용 ENA 확장, OS 바이패스 지원

### Key Pair

EC2 접속을 위한 공개키/개인키 기반 SSH 인증 방식입니다.

![Key Pair 인증 흐름](/assets/images/posts/aws-ec2-computing/02-11-10-key-pair.svg)

- **공개키**: AWS에 저장, 인스턴스의 `~/.ssh/authorized_keys`에 배치
- **개인키**: 사용자가 보관, 다운로드 후 재다운로드 불가
- 키 형식: RSA(2048비트 이상) 또는 ED25519 (권장)
- Windows 인스턴스: RDP 암호 해독에 사용

---

## Part 4: 수명주기와 RAID

### EC2 수명주기

![EC2 인스턴스 수명주기](/assets/images/posts/aws-ec2-computing/02-12-11-ec2-상태-및-수명주기.svg)

| 상태 | 설명 | 요금 |
|------|------|------|
| **pending** | 준비 중 — AMI에서 EBS 생성, 네트워크 구성 | 컴퓨팅 부과 |
| **running** | 정상 실행 중 | 컴퓨팅 부과 |
| **stopping** | 정지 준비 중 | 컴퓨팅 부과 |
| **stopped** | 정지됨 | **EBS만 부과**, 컴퓨팅 미부과 |
| **shutting-down** | 종료 준비 중 | — |
| **terminated** | 영구 삭제, 복구 불가 | 미부과 |

**Hibernate(최대절전모드)**는 RAM 내용을 EBS 루트 볼륨에 저장 후 정지합니다. 재시작 시 부팅 없이 즉시 이전 상태로 복귀합니다. EBS 루트 볼륨이 암호화되어야 하고, RAM 크기를 수용할 수 있어야 하며, 최대 60일 절전 가능합니다.

### RAID 구성

여러 EBS 볼륨을 결합하여 성능 향상이나 데이터 중복을 달성합니다. Linux mdadm 등 소프트웨어 RAID를 사용하며, 동일 AZ 내 볼륨으로만 구성합니다.

![RAID 레벨 비교](/assets/images/posts/aws-ec2-computing/02-13-12-raid-구성.svg)

| 레벨 | 방식 | 효과 | 주의점 | 적합 |
|------|------|------|--------|------|
| **RAID 0** | 스트라이핑 | 성능 N배 향상 ⚡ | 볼륨 1개 장애 → 전체 손실 | DB 로그, 고성능 I/O |
| **RAID 1** | 미러링 | 내결함성, 내구성 2배 | 비용 2배 | 중복이 중요한 데이터 |
| **RAID 5/6** | 패리티 | — | ❌ EBS에서 권장하지 않음 (패리티 오버헤드) | 사용 금지 |

> EBS 환경에서는 패리티 연산 오버헤드로 인해 RAID 5/6 대신 **RAID 0(성능) 또는 RAID 1(내결함성)**을 사용합니다.

---

## 마치며

EC2를 처음 공부할 때는 인스턴스 타입만 고르면 끝인 줄 알았습니다. 하지만 M, C, R, I 같은 패밀리가 각각 워크로드의 성격에 맞춰 설계되어 있다는 점을 알고 나니, 인스턴스 선택이 곧 아키텍처 설계의 핵심이라는 걸 깨달았습니다. 특히 Graviton 기반 인스턴스가 ARM 아키텍처로 비용 대비 성능을 크게 끌어올리고 있다는 사실이 인상 깊었습니다.

비용 최적화 부분에서도 생각이 바뀌었습니다. Savings Plans와 스팟 인스턴스를 단순히 "할인"이라고 생각했는데, 실제로는 예측 가능한 프로덕션과 중단 허용 분산 작업이라는 서로 다른 워크로드 특성에 맞춘 전략이었습니다. 스토리지 역시 영구 데이터는 gp3 EBS, 고성능 I/O는 인스턴스 스토어, 내결함성은 RAID로 용도를 명확히 나누는 것이 중요했습니다.

컴퓨팅 자원을 용도에 맞게 조합하고, 배치 그룹으로 물리적 배치까지 제어할 수 있다는 점은 클라우드가 주는 자유도의 깊이를 다시금 체감하게 합니다. 앞으로 실제 워크로드에 직접 인스턴스를 띄워보며 성능과 비용의 균형을 찾아가 보고 싶습니다.

---

> **AWS 시리즈 2/16**
>
> | | |
> |---|---|
> | ← [AWS 클라우드 기초 — 핵심 개념과 글로벌 인프라]({% post_url 2026-05-22-AWS-Foundations-Core-Concepts %}) | |
> | | [S3 객체 스토리지 기초 — 버킷부터 수명주기까지]({% post_url 2026-05-24-AWS-S3-Storage-Basics %}) → |
