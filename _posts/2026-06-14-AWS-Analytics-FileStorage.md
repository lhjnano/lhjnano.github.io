---
layout: post
title: "[AWS 8/16] 분석 & 파일 스토리지 — Redshift, Athena, EFS, FSx"
categories: [AWS, Analytics, Storage]
description: 데이터 웨어하우스(Redshift)와 서버리스 쿼리(Athena), 그리고 파일 스토리지(EFS/FSx)를 정리합니다.
keywords: [Redshift, Athena, EFS, FSx, AWS, 분석]
toc: true
toc_sticky: true
---

## Hook

> 페타바이트 데이터를 분석할 때 RDS로 충분할까? 서버 한 대 없이 S3만 쿼리할 수 있을까? 수천 대 EC2가 공유하는 파일 시스템은 어떻게 만들까?

OLTP에 익숙한 엔지니어가 분석 워크로드(OLAP)를 설계하려면 발상을 전환해야 합니다. 행 기반 저장이 아닌 **열 기반 저장**, 프로비저닝이 아닌 **서버리스**, 블록 스토리지가 아닌 **공유 파일 시스템**이 분석 아키텍처의 핵심입니다. 이 글에서는 AWS 분석 서비스(Redshift, Athena)와 파일 스토리지(EFS, FSx)를 정리합니다.

---

## TL;DR

- **Redshift** — 페타바이트 규모 MPP 데이터 웨어하우스, 열 단위 저장, 리더 노드 + 컴퓨팅 노드 구조
- **Athena** — 서버리스 S3 직접 쿼리, 스캔 TB당 $5, Parquet + 파티셔닝으로 95% 비용 절감
- **EFS** — NFS 기반 탄력적 파일 시스템, 다중 AZ, 4가지 스토리지 클래스
- **FSx** — Windows(SMB) · Lustre(HPC) · OpenZFS · ONTAP 4종 라인업으로 워크로드 맞춤 선택

---

## Part 1. 데이터 웨어하우스 & 분석 서비스

### 1. Data Warehouse 개념

데이터 웨어하우스(Data Warehouse, DW)는 기업의 다양한 소스에서 수집된 데이터를 **분석 목적**으로 저장하는 중앙 집중식 저장소입니다. 트랜잭션 처리(OLTP)가 아닌 **분석 질의(OLAP)** 에 최적화되어 있습니다.

**ETL 파이프라인**이 데이터를 소스에서 추출(Extract)하고, 분석에 적합한 형태로 변환(Transform)한 후, 데이터 웨어하우스에 적재(Load)합니다. AWS에서는 AWS Glue가 ETL 엔진 역할을 수행하며, Amazon QuickSight가 BI 도구로 제공됩니다.

### OLTP vs OLAP

분석 아키텍처를 이해하려면 먼저 두 패러다임의 차이를 명확히 해야 합니다.

| 항목 | OLTP (RDS) | OLAP (Redshift) |
|------|------------|-----------------|
| 목적 | 일일 트랜잭션 처리 | 대규모 데이터 분석 |
| 쿼리 유형 | 단순, 빈번한 읽기/쓰기 | 복잡, 대량 집계 |
| 데이터 모델 | 정규화 (3NF) | 비정규화 (Star Schema) |
| 행 수 | 수천~수백만 | 수억~수조 |
| 저장 방식 | 행 단위 (Row-based) | 열 단위 (Columnar) |

> OLTP는 "한 건을 빠르게" 처리하는 것이 목표이고, OLAP은 "수억 건을 한 번에 집계"하는 것이 목표입니다. 목적이 다르면 저장 방식도 달라야 합니다.

<br>

### 2. Redshift 아키텍처

Amazon Redshift는 PostgreSQL 기반의 관리형 데이터 웨어하우스로, 페타바이트 규모의 데이터를 분석할 수 있는 OLAP 엔진입니다. 핵심 특징은 다음과 같습니다.

- **PostgreSQL 호환** — 표준 SQL, JDBC/ODBC 드라이버 지원
- **MPP (Massively Parallel Processing)** — 수십~수백 개 노드에서 병렬 처리
- **열 단위 저장** — 컬럼 기반 압축으로 I/O 최소화
- **페타바이트 확장** — 최대 16PB까지 확장 가능
- **VPC 내 배포** — 네트워크 격리 보안

Redshift는 **리더 노드(Leader Node)** 와 **컴퓨팅 노드(Compute Node)** 의 2계층 아키텍처를 사용합니다.

```
                 [클라이언트]
                 (SQL 클라이언트, BI 도구)
                      │ JDBC/ODBC
                ┌─────┴─────┐
                │ Leader    │  ← 쿼리 파싱, 실행 계획 수립
                │ Node      │  ← 결과 취합, 클라이언트 반환
                └─────┬─────┘
            ┌─────────┼─────────┐
            ↓         ↓         ↓
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │Compute   │ │Compute   │ │Compute   │
     │Node 1    │ │Node 2    │ │Node 3    │
     │┌────────┐│ │┌────────┐│ │┌────────┐│
     ││Slice 1 ││ ││Slice 1 ││ ││Slice 1 ││
     ││Slice 2 ││ ││Slice 2 ││ ││Slice 2 ││
     │└────────┘│ │└────────┘│ │└────────┘│
     └──────────┘ └──────────┘ └──────────┘
          AZ-a         AZ-b         AZ-c
```

- **리더 노드** — SQL 쿼리 수신 및 파싱, 실행 계획 생성·최적화, 컴퓨팅 노드에 작업 분배, 결과 취합 및 반환, 메타데이터 관리를 담당합니다.
- **컴퓨팅 노드** — 실제 데이터 저장 및 쿼리를 실행합니다. 각 노드는 2개 이상의 Slice로 분할되며, Slice가 쿼리 실행의 최소 병렬 단위가 됩니다. RA3, DC2, DS2 노드 타입을 제공합니다.

<details>
<summary><b>📖 열 단위 저장(Columnar Storage)의 원리 보기</b></summary>

행 단위가 아닌 열 단위로 데이터를 저장하여 분석 성능을 극대화합니다.

```
[행 단위 저장 - RDS]            [열 단위 저장 - Redshift]
| id | name  | age | city  |    id:   | 1 | 2 |
| 1  | Kim   | 30  | Seoul |    name: | Kim | Lee |
| 2  | Lee   | 25  | Busan |    age:  | 30 | 25 |
                                 city: | Seoul | Busan |
```

평균 나이를 구할 때 age 컬럼만 읽으면 되므로 I/O가 대폭 감소합니다. 동일 타입 데이터가 연속 배치되어 압축률도 높아지며, SUM·AVG·COUNT 등 집계 함수에 최적화됩니다.

</details>

<br>

### 3. Redshift 핵심 기능

**COPY / UNLOAD** 명령어로 S3와 대용량 데이터를 고속으로 주고받습니다. COPY는 S3·DynamoDB·EMR에서 병렬 적재하고, UNLOAD는 쿼리 결과를 S3로 병렬 내보냅니다. Enhanced VPC Routing을 활성화하면 이 트래픽이 VPC 내부 네트워크로 라우팅되어 보안 그룹과 NACL이 적용됩니다.

**WLM(Workload Management)** 은 동시 실행 쿼리를 큐 기반으로 관리합니다. ETL, BI 분석, 실시간, 대량 적재 큐를 분리하여 리소스를 효율적으로 분배하며, 자동 WLM 활성화 시 Redshift가 자동으로 리소스를 관리합니다.

**스냅샷** 은 자동(기본 8시간 간격, 보존 1~35일)과 수동(보존 무제한)으로 제공되며, 크로스 리전 복사로 재해 복구(DR)를 구현합니다.

<details>
<summary><b>📖 2026 Redshift 최신 기능 보기</b></summary>

- **Redshift Serverless** — 클러스터 프로비저닝 없이 RPU(Redshift Processing Units) 단위로 자동 스케일링, 사용량 과금
- **Streaming Ingestion** — Kinesis Data Streams에서 실시간 데이터를 Materialized View로 직접 수집 (ETL 불필요)
- **AQUA(Advanced Query Accelerator)** — RA3 노드의 FPGA 기반 하드웨어 가속 캐시, 집계·필터링 최대 10배 향상
- **Redshift ML** — SQL 쿼리 내에서 머신러닝 모델 생성 및 추론 (SageMaker 통합)
- **Data Sharing** — 클러스터 간 데이터 복제 없이 실시간 공유, 읽기/쓰기 워크로드 분리
- **Data API** — JDBC/ODBC 연결 없이 HTTP API로 쿼리 실행, Lambda·Step Functions 통합

</details>

<br>

### 4. Redshift vs RDS 비교

분석 워크로드를 RDS로 처리하려다 보면 성능과 비용 양쪽에서 한계에 부딪힙니다. 두 서비스는 근본적으로 설계 철학이 다릅니다.

| 항목 | Redshift | RDS |
|------|----------|-----|
| 목적 | OLAP (분석) | OLTP (트랜잭션) |
| 저장 방식 | 열 단위 (Columnar) | 행 단위 (Row-based) |
| 확장 | 수십~수백 노드 (MPP) | 수직 확장 중심 |
| 데이터 크기 | 수 TB ~ 페타바이트 | 수 GB ~ 수 TB |
| 쿼리 유형 | 복잡한 집계, 대량 스캔 | 단순 CRUD, 인덱스 조회 |
| 압축 | 자동 컬럼 압축 | 제한적 |
| 인덱스 | Sort Key, Distribution Key | B-Tree, Hash 등 |
| 과금 | 노드 시간 기준 | 인스턴스 시간 기준 |

> 실무 팁: RDS에서 실행에 수십 분 걸리는 집계 쿼리를 Redshift에 넘기면 수초~수분으로 단축됩니다. 분석 전용 스토리지를 분리하면 트랜잭션 성능도 보호됩니다.

<br>

### 5. Athena — 서버리스 S3 쿼리

Amazon Athena는 **서버리스 대화형 SQL 쿼리** 서비스입니다. S3에 저장된 데이터를 직접 쿼리하며, 인프라 관리가 필요 없습니다.

```
[SQL 쿼리 실행]
    ↓
[Athena 엔진 (Presto)]
    ↓
[S3 데이터 읽기]
    ↓
[결과 반환 + S3에 결과 저장]
```

**핵심 특징**은 다음과 같습니다.

- **서버리스** — 프로비저닝, 설정, 관리 불필요
- **표준 SQL** — Presto 기반 ANSI SQL 지원
- **S3 직접 쿼리** — 데이터 이동 없이 S3에서 직접 분석
- **사용량 과금** — 스캔한 데이터 TB당 $5.00
- **Federated Query** — S3 외 데이터 소스(DynamoDB, RDS 등)도 쿼리 가능

**비용 최적화**가 Athena 운영의 핵심입니다. CSV 1TB를 그대로 쿼리하면 $5.00가 발생하지만, Parquet 변환 + 파티셔닝 + Snappy 압축을 적용하면 실제 스캔량이 약 50GB로 줄어 $0.25(95% 절감)가 됩니다.

| 최적화 전략 | 효과 |
|-------------|------|
| Parquet/ORC 변환 | CSV 대비 스캔량 50~85% 감소 |
| 파티셔닝 | WHERE 절로 불필요한 파티션 스킵 |
| Snappy/ZSTD 압축 | 데이터 크기 축소 |
| 컬럼 선택 | SELECT * 대신 필요 컬럼만 지정 |
| Materialized View | 자주 실행하는 쿼리 결과 캐싱 |

**활용 사례**는 시나리오에 따라 분기합니다.

| 시나리오 | 추천 도구 | 이유 |
|----------|-----------|------|
| 빠른 Ad-hoc 분석 | Athena | 설정 없이 즉시 SQL 실행 |
| 대시보드 정기 갱신 | Athena + QuickSight | 저비용, 서버리스 |
| 페타바이트 복잡 조인 | Redshift | MPP 고성능 처리 |
| 실시간 데이터 분석 | Redshift Streaming | Kinesis 직접 수집 |
| 여러 소스 연합 쿼리 | Athena Federation | 다양한 소스 통합 |
| 비정형 로그 분석 | Athena | S3 로그 직접 쿼리 |

> 경험칙: "빠르게 봐야 하는데 데이터를 옮길 수 없다" → Athena. "복잡한 조인과 ML이 필요하다" → Redshift. 두 서비스는 경쟁이 아니라 데이터 레이크 아키텍처에서 **보완적**으로 사용됩니다.

<br>

---

## Part 2. 파일 스토리지 — EFS & FSx

### 6. EFS (Elastic File System) 개요

Amazon EFS는 AWS 클라우드에서 NFS v4.0/v4.1 프로토콜을 지원하는 **확장 가능한 탄력적 파일 시스템**입니다. VPC 내에 생성되며, 수천 개의 EC2 인스턴스가 동시에 마운트할 수 있고, 용량이 자동으로 확장 및 축소됩니다.

- NFS v4.0/v4.1 프로토콜 지원
- 수천 개 EC2 인스턴스 동시 마운트 가능
- 용량 자동 확장/축소 (Auto Scaling)
- 사용량 기반 과금
- POSIX 호환 파일 시스템

<br>

### 7. EFS 가용성 및 내구성

EFS는 다중 AZ(Multi-AZ) 배포를 통해 고가용성을 제공합니다. 파일 시스템은 여러 가용 영역에 걸쳐 데이터를 복제하며, VPN이나 Direct Connect를 통해 온프레미스 환경에서도 접근할 수 있습니다.

![EFS 가용성 및 내구성 아키텍처 — 온프레미스에서 VPN/DX로 VPC 접근, 3개 AZ 마운트 타겟(ENI)이 다중 AZ 복제 EFS 파일 시스템으로 연결](/assets/images/posts/aws-analytics-filestorage/12-01-2-efs-가용성-및-내구성.svg)

- **다중 AZ 배포** — 모든 AZ에 마운트 타겟 생성 권장
- **온프레미스 접근** — IPSEC VPN 또는 Direct Connect 필요
- **내구성** — 99.999999999% (11-nines) 보장
- **백업** — AWS Backup과 통합된 자동 백업 지원

<br>

### 8. EFS 스토리지 클래스 & 수명 주기

EFS는 액세스 빈도와 가용성 요구사항에 따라 4가지 스토리지 클래스를 제공합니다.

| 스토리지 클래스 | 가용성 | 용도 | 비용 |
|------------------|--------|------|------|
| **Standard** | 다중 AZ | 자주 접근하는 데이터 | 표준 |
| **Standard-IA** | 다중 AZ | 접근 빈도가 낮은 데이터 | 저렴 (저장비용 ↓, 접근비용 ↑) |
| **One Zone** | 단일 AZ | 자주 접근, AZ 장애 허용 | 표준 대비 47% 저렴 |
| **One Zone-IA** | 단일 AZ | 접근 빈도 낮음, AZ 장애 허용 | 최저 비용 |

**수명 주기 관리(Lifecycle Management)** 를 활성화하면 지정된 기간(7·14·30·60·90·180·270·365일) 동안 접근되지 않은 파일을 자동으로 Infrequent Access 클래스로 이동합니다. 파일에 다시 접근하면 자동으로 표준 클래스로 복귀하며, IA 클래스로 최대 92% 비용 절감이 가능합니다.

> 2026년 추가된 **Intelligent-Tiering** 모드는 접근 패턴을 학습하여 자동으로 최적의 클래스를 선택합니다.

<br>

### 9. EFS 성능 모드

EFS는 처리량(Throughput) 모드와 성능(Performance) 모드를 각각 선택합니다.

**처리량 모드**:

| 모드 | 특징 | 적합한 워크로드 |
|------|------|-----------------|
| **Bursting** | 저장 용량에 비례한 기본 처리량, 버스트 크레딧 누적 | 일반 웹 서버, CMS |
| **Elastic** | 워크로드에 따라 자동 스케일 업/다운 | 예측 불가능한 워크로드, 빅데이터 |
| **Provisioned** | 고정 처리량 보장 (최대 1GiB/s) | 일정한 높은 처리량 필요 |

**성능 모드** (생성 후 변경 불가):

- **General Purpose(기본값)** — 낮은 지연, 파일 작업 API 최적화. 웹 서버, CMS, 홈 디렉토리에 권장
- **MAX I/O** — 매우 높은 병렬 처리량. 빅데이터 분석, 미디어 처리, 병렬 과학 계산에 적합

> Elastic 모드는 2026년 기준 대부분의 프로덕션 워크로드에 권장됩니다. 처리량 예측이 어려운 마이크로서비스 아키텍처에서 특히 유용합니다.

<br>

### 10. FSx 파일 시스템 라인업

Amazon FSx는 서드파티 파일 시스템을 AWS에서 완전 관리형 서비스로 제공합니다. 4가지 라인업으로 워크로드에 맞춰 선택합니다.

- **FSx for Windows File Server** — SMB, Active Directory 통합
- **FSx for Lustre** — Linux HPC, S3 통합
- **FSx for OpenZFS** — ZFS 기반, 고성능
- **FSx for NetApp ONTAP** — ONTAP 기반, 다중 프로토콜

#### FSx for Windows File Server

Windows 환경에 최적화된 완전 관리형 파일 스토리지로, SMB 2.0/3.0/3.1.1을 지원하고 AWS Managed Microsoft AD와 통합됩니다.

![FSx for Windows File Server 아키텍처 — Windows EC2가 SMB로 FSx에 연결, AD 통합·DFS 네임스페이스·Shadow Copy·Multi-AZ 고가용성 지원](/assets/images/posts/aws-analytics-filestorage/12-02-9-fsx-for-windows-file-server.svg)

DFS 네임스페이스, VSS 기반 Shadow Copy, 데이터 중복 제거를 지원하며 Single-AZ 또는 Multi-AZ 배포가 가능합니다.

#### FSx for Lustre

고성능 컴퓨팅(HPC) 워크로드에 최적화된 Linux 파일 시스템으로, S3 버킷을 파일 시스템으로 직접 마운트할 수 있습니다.

![FSx for Lustre HPC 아키텍처 — S3 원본 데이터를 FSx for Lustre(Scratch/Persistent)로 연결, HPC 클러스터 병렬 처리 후 결과를 S3로 자동 내보내기](/assets/images/posts/aws-analytics-filestorage/12-03-10-fsx-for-lustre.svg)

최대 12GB/s/TiB 처리량과 서브밀리초 지연을 제공하며, **Scratch**(임시 저장, 버스트 성능)와 **Persistent**(장기 저장, 데이터 자동 복제) 배포 유형을 선택할 수 있습니다.

#### FSx for OpenZFS & ONTAP

- **OpenZFS** — 스냅샷, 복제, 압축, 데이터 검증 내장. 최대 1,000,000 IOPS, NFS v3/v4 지원. 증분 스냅샷에서 즉시 클론 생성 가능
- **NetApp ONTAP** — NFS, SMB, iSCSI 동시 지원(다중 프로토콜). SnapMirror, FlexClone, 중복 제거 제공. 온프레미스 ONTAP과 하이브리드 복제 가능

| 항목 | Windows | Lustre | OpenZFS | ONTAP |
|------|---------|--------|---------|-------|
| 프로토콜 | SMB | POSIX/NFS | NFS v3/v4 | NFS, SMB, iSCSI |
| OS | Windows | Linux | Linux | 다중 |
| 주요 용도 | 엔터프라이즈 | HPC | 고성능 Linux | 하이브리드/마이그레이션 |
| S3 통합 | ❌ | ✅ | ❌ | ❌ |
| AD 통합 | ✅ | ❌ | ❌ | ✅ |

<br>

### 11. 아키텍처 패턴

#### 패턴 1: 파일 공유 아키텍처

여러 EC2 인스턴스에서 공유 파일 시스템이 필요한 웹 애플리케이션입니다. ALB 뒤의 웹 서버들이 EFS에 `/var/www/html`을 마운트하여 공유 콘텐츠와 세션 데이터를 사용합니다.

![파일 공유 아키텍처 — ALB가 3대 EC2 웹 서버에 트래픽 분산, 모든 서버가 EFS /var/www/html을 공유 마운트](/assets/images/posts/aws-analytics-filestorage/12-04-131-파일-공유-아키텍처.svg)

#### 패턴 2: HPC 데이터 파이프라인

S3와 FSx for Lustre를 결합한 고성능 데이터 처리 파이프라인입니다.

![HPC 데이터 파이프라인 아키텍처 — 데이터 소스→S3→FSx for Lustre→HPC 클러스터→결과 S3, Step Functions가 분석/시각화 단계를 오케스트레이션](/assets/images/posts/aws-analytics-filestorage/12-05-132-hpc-데이터-파이프라인-아키텍처.svg)

#### 패턴 3: 마이그레이션 아키텍처

온프레미스 파일 서버를 AWS로 마이그레이션하는 아키텍처입니다.

![마이그레이션 아키텍처 — 온프레미스(Windows/ONTAP/NFS)를 DataSync·SnapMirror로 FSx for Windows·ONTAP·EFS/OpenZFS로 이관](/assets/images/posts/aws-analytics-filestorage/12-06-133-마이그레이션-아키텍처.svg)

- **AWS DataSync** — 온프레미스 ↔ AWS 간 자동화된 데이터 전송
- **Transfer Family** — FTP/FTPS/SFTP 프로토콜 파일 전송
- **SnapMirror** — ONTAP 간 증분 복제 (FSx for ONTAP)

> 선택 가이드: Linux NFS → **EFS** 또는 **OpenZFS**, Windows SMB → **FSx for Windows**, HPC/빅데이터 → **FSx for Lustre**, 다중 프로토콜/하이브리드 → **FSx for ONTAP**

---

## Takeaway

1. **분석은 OLAP, 트랜잭션은 OLTP로 분리합니다** — Redshift(열 단위 저장, MPP)로 페타바이트 분석을, RDS로 트랜잭션을 담당하여 워크로드를 격리하면 양쪽 성능이 모두 보호됩니다
2. **Athena는 Parquet + 파티셔닝이 필수입니다** — 서버리스의 편리함 뒤에는 스캔량 과금이 숨어 있으므로, CSV를 Parquet으로 변환하고 파티션을 설계하면 비용을 95%까지 줄일 수 있습니다
3. **파일 스토리지는 워크로드 프로토콜로 선택합니다** — Linux(NFS)는 EFS, Windows(SMB)는 FSx for Windows, HPC는 FSx for Lustre, 다중 프로토콜은 FSx for ONTAP으로 매핑하면 아키텍처가 자연스럽게 정립됩니다

---

> **AWS 시리즈 8/16**
>
> | | |
> |---|---|
> | ← [데이터베이스 & 캐시 — RDS, Aurora, ElastiCache]({% post_url 2026-06-14-AWS-Database-Cache %}) | |
> | | [보안 기초 — IAM 사용자 관리와 KMS 암호화]({% post_url 2026-06-14-AWS-IAM-KMS-Security %}) → |
