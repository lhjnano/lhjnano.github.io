---
layout: post
title: "[AWS 14/16] 하이브리드 & 마이그레이션 — Storage Gateway, DataSync, Snow Family"
categories: [AWS, Migration, Storage]
description: 온프레미스와 AWS를 연결하는 하이브리드 스토리지(Storage Gateway, DataSync)와 대용량 데이터 마이그레이션(Snow Family)을 정리합니다.
keywords: [StorageGateway, DataSync, Snowball, AWS, 마이그레이션]
toc: true
toc_sticky: true
---

## Hook

> 클라우드로 전환하겠다고 결심했는데, 데이터센터에 쌓인 데이터가 페타바이트 단위라면 어떻게 옮길 수 있을까요? 1Gbps 회선으로 100PB를 보내려면 약 30년이 걸립니다. 반면 트럭 한 대가 그 데이터를 몇 주 안에 가져다 줍니다.

하이브리드 환경에서는 온프레미스와 AWS 사이의 연결이 관건입니다. 이 글에서는 기존 프로토콜을 그대로 유지하며 클라우드 스토리지를 활용하는 **Storage Gateway**, 온라인 전송을 자동화하는 **DataSync**, 그리고 물리적 디바이스로 대용량 데이터를 옮기는 **Snow Family**를 2026년 최신 기준으로 정리합니다.

---

## TL;DR

- **Storage Gateway는 프로토콜을 보존합니다** — File(NFS/SMB→S3), FSx(SMB→FSx), Volume(iSCSI→S3/EBS Snapshot), Tape(VTL→S3/Glacier) 네 가지 유형으로 기존 애플리케이션 변경 없이 클라우드 백엔드를 사용합니다
- **DataSync는 온라인 마이그레이션을 자동화합니다** — 에이전트당 최대 10Gbps, 증분 전송, 체크섬 검증, 일정 예약으로 파일 시스템 이관을 안정적으로 수행합니다
- **Snow Family는 물리적으로 데이터를 옮깁니다** — Snowcone(~14TB) · Snowball Edge(~100TB) · Snow Mobile(~100PB)로 네트워크 전송이 비현실적인 규모를 배송 기반으로 해결합니다
- **전략은 조합입니다** — 과거 데이터(Cold)는 Snow로 오프라인 이관하고, 활성 데이터(Hot)는 DataSync로 지속 동기화하며, 데이터베이스는 DMS CDC로 컷오버 다운타임을 최소화합니다

---

## Part 1: 하이브리드 스토리지 — Storage Gateway & DataSync

### Storage Gateway 개요

AWS Storage Gateway는 온프레미스 환경과 AWS 클라우드 스토리지를 연결하는 하이브리드 스토리지 서비스입니다. 온프레미스 애플리케이션이 기존 프로토콜(NFS, SMB, iSCSI)을 그대로 사용하면서 클라우드 스토리지를 백엔드로 활용합니다.

- **배포 형태**: VM(VMware ESXi, Hyper-V, KVM) 또는 EC2 인스턴스
- **지원 프로토콜**: NFS, SMB, iSCSI, VTL
- **클라우드 백엔드**: S3, EBS Snapshot, S3 Glacier
- **로컬 캐시**: SSD 캐시로 자주 접근하는 데이터의 빠른 액세스 제공
- **보안 전송**: AWS 네트워크를 통한 SSL/TLS 암호화
- **과금**: 클라우드 스토리지 사용량만큼 종량제

```
┌─────────────────────────────────────────────────────────┐
│                  온프레미스 데이터센터                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │   NFS    │  │   SMB    │  │  iSCSI   │              │
│  │ Client   │  │ Client   │  │ Client   │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│  ┌────▼──────────────▼──────────────▼──────┐            │
│  │         AWS Storage Gateway             │            │
│  │    ┌──────────────────────────┐         │            │
│  │    │   로컬 캐시 (SSD)        │         │            │
│  │    └──────────────────────────┘         │            │
│  └────────────────┬───────────────────────┘            │
│                    │ 암호화 전송 (SSL/TLS)               │
└────────────────────┼────────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │     AWS 클라우드      │
          │  ┌───────┐ ┌──────┐ │
          │  │  S3   │ │ EBS  │ │   ┌───────┐
          │  │Bucket │ │ Snap │ │   │Glacier│
          │  └───────┘ └──────┘ │   └───────┘
          └─────────────────────┘
```

### 게이트웨이 4가지 유형

**File Gateway**는 NFS/SMB 프로토콜로 S3 객체를 저장·검색합니다. 파일은 S3 객체로 1:1 매핑되며, 디렉토리는 S3 접두사(Prefix)가 됩니다. 로컬 캐시 최대 64TB, POSIX(NFS)/ACL(SMB) 권한을 S3 메타데이터로 보존합니다. 파일 공유, 백업, 데이터 레이크 업로드에 적합합니다.

**FSx File Gateway**는 SMB 프로토콜로 Amazon FSx for Windows File Server에 접근합니다. 로컬 캐시 최대 32TB이며 AWS Managed AD와 통합되어 NTFS, Windows ACL, DFS 네임스페이스를 지원합니다. Windows 홈 디렉토리, CMS 마이그레이션에 적합합니다.

**Volume Gateway**는 iSCSI 프로토콜로 클라우드 기반 블록 스토리지에 접근합니다. S3를 백엔드로 사용하고 EBS Snapshot으로 증분 백업합니다. Cached Volume(최대 32TB/볼륨, 캐시 64TB)이 클라우드 중심 기본 권장이며, Stored Volume(최대 16TB/볼륨, 전체 로컬 보관)은 낮은 지연이 필수인 레거시에 적합합니다.

**Tape Gateway**는 VTL(Virtual Tape Library)로 물리적 테이프를 대체합니다. 가상 테이프 최대 15,000개(100GB~5TB/테이프, 총 최대 1PB), 백업 소프트웨어(Veeam, NetBackup, IBM Spectrum Protect)와 호환되며, 자주 접근 데이터는 S3, 아카이브는 Glacier Flexible Retrieval로 계층화합니다.

### Volume Gateway: Cached vs Stored

| 항목 | Cached Volume | Stored Volume |
|------|---------------|---------------|
| 기본 저장소 | AWS S3 (클라우드) | 온프레미스 로컬 디스크 |
| 로컬 캐시 | 최근 데이터만 | 전체 데이터 보관 |
| 볼륨 크기 | 최대 32TB/volume | 최대 16TB/volume |
| 지연 시간 | 캐시 히트 시 낮음 | 항상 낮음 (로컬) |
| 백업 | S3 → EBS Snapshot (증분) | 온프레미스 → EBS Snapshot (증분) |
| 권장 | ✅ 기본 (클라우드 중심) | 레거시 마이그레이션 |

### AWS DataSync — 온라인 마이그레이션

DataSync는 온프레미스 스토리지와 AWS 스토리지 간의 데이터 이동을 자동화하는 서비스입니다. 대용량 전송 시 네트워크 대역폭을 최적화하고 전송을 모니터링합니다.

- **DataSync Agent**: 온프레미스에 배포되는 에이전트 (VM 또는 EC2)
- **전송 속도**: 에이전트당 최대 10Gbps
- **증분 전송**: 마지막 동기화 이후 변경된 파일만 전송
- **무결성**: 전송 중 체크섬 검증
- **과금**: 전송된 데이터 GB당

소스는 온프레미스 NFS/SMB/HDFS, Azure Blob, Google Cloud Storage를 지원하고, 대상은 S3, EFS, FSx for Windows/Lustre/OpenZFS/ONTAP 등을 지원합니다.

```
┌─────────────────────────────────────────────────────────┐
│                   온프레미스 데이터센터                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  NFS 서버     │  │  SMB 서버     │  │  HDFS        │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│  ┌──────▼─────────────────▼─────────────────▼───────┐  │
│  │            DataSync Agent (VM)                   │  │
│  │  • 데이터 스캔 · 증분 변경 감지                    │  │
│  │  • 압축 & 암호화 · 대역폭 제한 설정                 │  │
│  └────────────────────────┬────────────────────────┘  │
└───────────────────────────┼────────────────────────────┘
                            │ TLS 암호화
                 ┌──────────▼──────────┐
                 │   AWS DataSync      │
                 │  전송 작업 관리 · 일정 │
                 │  대역폭 제한 · 무결성 │
                 └─────┬──┬──┬──┬─────┘
            ┌──────────┘  │  │  └──────────┐
            ▼             ▼  ▼             ▼
       ┌────────┐   ┌──────┐ ┌──────┐ ┌────────┐
       │  S3    │   │ EFS  │ │FSx Win│ │FSx Lust│
       └────────┘   └──────┘ └──────┘ └────────┘
```

### Storage Gateway 유형 선택 가이드

| 시나리오 | 권장 서비스 | 이유 |
|----------|------------|------|
| 파일 공유를 S3로 마이그레이션 | File Gateway | NFS/SMB로 S3 접근, 비용 절감 |
| Windows 홈 디렉토리 | FSx File Gateway | Windows AD 통합, SMB 프로토콜 |
| 블록 스토리지 백업 | Volume Gateway (Cached) | iSCSI + EBS Snapshot 백업 |
| 테이프 백업 교체 | Tape Gateway | 기존 백업 소프트웨어 호환 |
| 대용량 파일 시스템 이관 | DataSync | 자동화, 증분, 무결성 검증 |
| B2B 파일 교환 (SFTP) | Transfer Family | SFTP/FTPS 프로토콜 지원 |

### 하이브리드 아키텍처 패턴: 파일 공유 마이그레이션

```
[Phase 1: 분석]
온프레미스 NFS/SMB ──▶ DataSync Discovery ──▶ 마이그레이션 계획

[Phase 2: 데이터 이동]
온프레미스 NFS/SMB ──▶ DataSync ──▶ S3 / EFS / FSx

[Phase 3: 클라우드 우선]
온프레미스 Client ──▶ Storage Gateway(File) ──▶ S3 (백엔드)

[Phase 4: 완전 마이그레이션]
클라우드 EC2/ECS ──▶ EFS / FSx (직접 접근)
```

> **DataSync Discovery(2026)**: 마이그레이션 전 온프레미스 스토리지 인프라를 자동으로 분석하여 용량·성능·사용 패턴을 평가하고, AWS 스토리지 서비스 매핑과 비용·일정 추정 리포트를 제공합니다.

---

## Part 2: 대용량 마이그레이션 — Snow Family

### 왜 물리적 마이그레이션인가

대규모 데이터를 네트워크로 전송하면 시간과 비용이 기하급수적으로 증가합니다. 1Gbps 회선으로 100PB를 옮기려면 약 30년이 걸리지만, Snow Mobile은 수 주 내에 완료합니다. 데이터 규모가 커질수록 물리적 디바이스 배송이 네트워크 전송보다 빠르고 비용 효율적입니다.

| 데이터 크기 | 1Gbps 전송 | 10Gbps 전송 | Snowball Edge |
|------------|-----------|------------|---------------|
| 10TB | ~1일 | ~2.5시간 | ~1일 (배송 포함) |
| 100TB | ~12일 | ~1일 | ~1일 (배송 포함) |
| 1PB | ~120일 | ~12일 | ~1주 (병렬 전송) |
| 10PB | ~3년 | ~120일 | ~수주 (병렬 전송) |
| 100PB | ~30년 | ~3년 | Snow Mobile ~수주 |

```
        네트워크 전송 vs Snow Family
             │
 100PB ──────┤·····························
             │                             ·
 10PB  ──────┤····                         ·
             │    ·                        ·
 1PB   ──────┤····                        ·
             │                             ·
 100TB ──────┤····                        ·
             │    ·                        ·
 10TB  ──────┤····                        ·
             │                             ·
             └─────┬────────┬─────────────┬──
              1Gbps   10Gbps   Snowball    Snow
               전송     전송     Edge       Mobile
 ※ 네트워크는 대역폭에 비례, Snow는 배송 시간에 비례
```

### Snow Family 비교

| 항목 | Snowcone | Snowball Edge | Snow Mobile |
|------|---------|---------------|-------------|
| 형태 | 소형 휴대용 (2.1kg) | 서버 크기 케이스 | 트럭 (45피트 컨테이너) |
| 스토리지 | 8TB HDD / 14TB SSD | 최대 100TB(Storage) / 39.5TB(Compute) | 100PB |
| 컴퓨팅 | 2 vCPU, 4GB RAM | 최대 104 vCPU, 416GB RAM | 해당 없음 |
| 전송 방식 | 택배 배송 | 택배 배송 | AWS 전담 팀 운송 |
| 보안 | Tamper-evident, KMS | Tamper-evident, KMS | GPS 추적, 24시간 감시 |
| 적합 규모 | ~수 TB | ~수십 PB | ~수백 PB (EB급) |

### Snowball Edge — 두 가지 최적화

**Storage Optimized**은 페타바이트급 데이터 전송에 최적화됩니다. HDD 기반 80TB(사용 가능) S3 호환 스토리지, NFS 마운트 지원, vCPU 40개/80GB RAM, 옵션 NVIDIA V100 GPU를 갖춥니다. 대규모 데이터 마이그레이션과 콘텐츠 배포에 적합합니다.

**Compute Optimized**은 고성능 컴퓨팅 워크로드에 최적화됩니다. vCPU 104개/416GB RAM, 옵션 NVIDIA A100 GPU(1~4개), 39.5TB NVMe SSD, 28TB S3 호환 스토리지를 갖춥니다. ML 추론, 엣지 컴퓨팅, 동영상 처리에 적합합니다.

두 유형 모두 **S3 호환 엔드포인트**(`s3api`/CLI/SDK 호환), **NFS 마운트 포인트**, **Lambda@Edge 및 EC2(sbe 인스턴스) 실행 환경**을 제공하여 오프라인 환경에서도 데이터 처리가 가능합니다.

```
[전송 워크플로우]
1. AWS 콘솔에서 Snowball 주문
2. 물리적 디바이스 배송 수령
3. 로컬 네트워크에 연결 (RJ45/SFP+/QSFP+)
4. 데이터 복사 (S3 CLI / NFS / AWS OpsHub)
5. AWS로 디바이스 반송
6. AWS에서 S3 버킷으로 데이터 자동 업로드
7. 데이터 검증 후 디바이스 안전 삭제
```

### Snowcone

소형 휴대용 디바이스(약 22.5×15×8.5cm, 2.1kg)로 가장 작은 Snow Family 제품입니다. 8TB HDD 또는 14TB SSD, 2 vCPU/4GB RAM, 1Gbps/10Gbps 네트워크(RJ45/SFP+), AC 전원 또는 USB-C 배터리로 동작합니다. 배낭에 넣어 이동 가능하며 극한 환경(온도, 진동)에서도 동작합니다. 소규모 데이터 전송, 엣지 컴퓨팅, IoT 데이터 수집에 적합합니다.

### AWS Snow Mobile

엑사바이트급 데이터 전송을 위한 트럭 규모의 이동식 스토리지 디바이스입니다. 45피트 해운 컨테이너에 최대 100PB 용량, 최대 1Tbps 전송 속도를 갖춥니다. GPS 추적, 24시간 비디오 감시, 경보 시스템, AWS KMS 기반 256비트 암호화로 보안을 보장하며 AWS 전담 보안 팀이 배송·수거합니다. 데이터센터 전체 마이그레이션, 미디어 라이브러리, 위성 이미지 보관에 적합합니다.

### 엣지 컴퓨팅 & OpsHub

Snow Family 디바이스에서 **EC2 인스턴스(sbe 타입), Lambda 함수, IoT Greengrass, Docker 컨테이너**를 실행하여 데이터 전송과 엣지 컴퓨팅을 동시에 수행할 수 있습니다. **AWS OpsHub for Snow Family**는 GUI 데스크톱 앱으로 디바이스 잠금 해제, 드래그앤드롭 파일 전송, EC2/Lambda 관리, 다중 디바이스 클러스터 구성을 지원합니다. 네트워크 연결 시 AWS와 자동 동기화됩니다.

---

## Part 3: 마이그레이션 전략 — 온라인 vs 오프라인

데이터 크기, 네트워크 대역폭, 시간 제약에 따라 온라인과 오프라인 전략을 조합해야 합니다.

### 결정 트리

```
┌──────────────────────────────────────────────────┐
│          데이터 마이그레이션 결정 트리              │
│                                                  │
│  데이터 크기?                                      │
│  ├── < 10TB → 네트워크 전송                       │
│  │   ├── 빠른 링크 (≥1Gbps) → Direct Connect     │
│  │   └── 느린 링크 → S3 Transfer Acceleration    │
│  │                                                │
│  ├── 10TB ~ 100TB → DataSync / Snowcone          │
│  │   ├── 파일 시스템 → DataSync                   │
│  │   └── 오프라인 → Snowcone (여러 대)            │
│  │                                                │
│  ├── 100TB ~ 10PB → Snowball Edge                │
│  │   ├── 병렬 전송 (여러 대 동시 사용)             │
│  │   └── Direct Connect (시간 여유 시)             │
│  │                                                │
│  └── > 10PB → Snow Mobile                        │
│      └── AWS 영업팀 문의                           │
│                                                  │
│  데이터 유형?                                      │
│  ├── 파일/객체 → S3 / EFS / DataSync              │
│  ├── 데이터베이스 → AWS DMS                        │
│  ├── 서버 전체 → AWS MGN (리호스팅)               │
│  └── 블록 스토리지 → Volume Gateway + DataSync    │
└──────────────────────────────────────────────────┘
```

### 온라인 마이그레이션 서비스

| 서비스 | 설명 | 적합한 규모 |
|--------|------|------------|
| AWS Direct Connect | 전용 사설 네트워크 (1~100Gbps) | 지속적 전송, 대역폭 보장 |
| AWS VPN | IPsec VPN 터널 (Site-to-Site) | 소규모, 보안 연결 |
| S3 Transfer Acceleration | CloudFront 엣지 기반 S3 전송 가속 | 글로벌 S3 업로드 |
| AWS DataSync | 자동화된 데이터 동기화 | 파일 시스템 마이그레이션 |
| S3 멀티파트 업로드 | 대용량 객체 분할 병렬 업로드 | 대용량 파일 |

### 하이브리드 마이그레이션 (온라인 + 오프라인 조합)

```
┌─────────────────────────────────────────────────────────┐
│                  하이브리드 마이그레이션                    │
│                                                         │
│  [오프라인] Snowball Edge                                │
│  ┌─────────────────────────────────────────┐            │
│  │  과거 데이터 (Cold Data): 50TB           │            │
│  │  → Snowball Edge #1 (100TB)             │            │
│  │  → AWS로 반송 → S3 Glacier              │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  [온라인] DataSync                                       │
│  ┌─────────────────────────────────────────┐            │
│  │  활성 데이터 (Hot Data): 지속적 동기화     │            │
│  │  → DataSync Agent → S3 Standard          │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  [전환] DMS + Lambda                                     │
│  ┌─────────────────────────────────────────┐            │
│  │  데이터베이스: DMS CDC (최종 동기화)       │            │
│  │  컷오버: DNS 전환 (Route 53)             │            │
│  │  다운타임: < 30분                        │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  [검증] 데이터 무결성 · 성능 테스트 · 롤백 계획            │
└─────────────────────────────────────────────────────────┘
```

### 데이터센터 전체 마이그레이션 3단계

- **Phase 1 — 평가 (2~4주)**: AWS Migration Evaluator로 온프레미스 인프라 인벤토리, TCO 비용 분석, 마이그레이션 우선순위 결정
- **Phase 2 — 마이그레이션 (수주~수개월)**: 서버는 MGN으로 리호스팅 후 테스트→컷오버, DB는 DMS로 동종(복제)/이기종(SCT 변환 + CDC 동기화), 데이터는 규모에 따라 DataSync·Snowball Edge·Snow Mobile 조합
- **Phase 3 — 최적화 (지속)**: Right Sizing, Savings Plans, 서버리스·컨테이너로 아키텍처 현대화, FinOps 실천

---

## Takeaway

1. **Storage Gateway로 프로토콜을 보존하며 하이브리드를 구현합니다** — File(NFS/SMB→S3), FSx(SMB→FSx for Windows), Volume(iSCSI→S3/EBS Snapshot), Tape(VTL→S3/Glacier) 중 시나리오에 맞는 유형을 선택하여 기존 애플리케이션 변경 없이 클라우드 스토리지를 활용하고 로컬 SSD 캐시로 성능을 확보합니다
2. **데이터 규모에 따라 DataSync와 Snow Family를 나눕니다** — 온라인 파일 이관(에이전트당 10Gbps, 증분, 무결성 검증)은 DataSync로, 수십~수백 PB 물리 이관은 Snowball Edge/Snow Mobile로 처리하며 두 방식의 전환점은 대역폭 대비 배송 시간의 역전 지점입니다
3. **진짜 비용 절감은 온·오프라인 조합에서 나옵니다** — Cold 데이터는 Snow로 오프라인 이관, Hot 데이터는 DataSync로 지속 동기화, 데이터베이스는 DMS CDC로 컷오버 다운타임을 30분 미만으로 줄이는 하이브리드 전략이 대규모 마이그레이션의 정답입니다

---

> **AWS 시리즈 14/16**
>
> | | |
> |---|---|
> | ← [서버리스 — Lambda & API Gateway]({% post_url 2026-06-03-AWS-Serverless-Lambda-APIGateway %}) | |
> | | [AI & ML — Bedrock, SageMaker, Amazon Q]({% post_url 2026-06-05-AWS-AI-ML-Bedrock-SageMaker %}) → |
