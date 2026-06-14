---
layout: post
title: "[S3 2/7] AWS 데이터 공유 서비스 3종 — Registry, Data Exchange, Access Points"
categories: [AWS, S3]
description: AWS에서 데이터를 공유하는 세 가지 핵심 서비스를 정리합니다. Registry of Open Data, AWS Data Exchange, S3 Access Points의 차이와 사용 시나리오를 다룹니다.
keywords: [S3, AWS, DataExchange, AccessPoints, OpenData]
toc: true
toc_sticky: true
---

## Hook

> 수백 개의 데이터셋을 외부 조직과 공유해야 한다면? AWS는 세 가지 방법을 제공합니다 — 공개 데이터 레지스트리, 마켓플레이스, 그리고 세밀한 접근 제어.

데이터를 공유하는 일은 기술적으로 간단해 보이지만, 규모가 컨질수록 인증·과금·권한 관리가 폭발적으로 복잡해집니다. AWS는 이 문제를 해결하기 위해 목적이 전혀 다른 세 가지 서비스를 제공합니다. 이 글에서는 **Registry of Open Data**, **AWS Data Exchange**, **S3 Access Points**를 비교하고, 각각 언제 써야 하는지 정리합니다.

---

## TL;DR

- **Registry of Open Data**: 공개 데이터셋을 무료로 호스팅 — 누구나 접근 가능
- **AWS Data Exchange**: 유료/무료 데이터를 구독 모델로 거래 — 결제 연동
- **S3 Access Points**: 버킷 하나에 여러 접근 정책을 분리 — 대규모 공유 관리
- 핵심 차이: **공개(Registry)** vs **상업(Data Exchange)** vs **내부 통제(Access Points)**

---

## 어떤 문제를 해결하나요?

데이터를 외부에 공유하려면 다음과 같은 질문에 직면합니다.

- "공개 데이터인가, 상업 데이터인가?"
- "누가 접근할 수 있어야 하는가?"
- "결제와 라이선스는 어떻게 관리하는가?"
- "버킷 정책이 수백 줄이 되면 어떡하지?"

AWS는 이 네 가지 질문에 대해 각각 다른 서비스로 대답합니다.

### 한눈에 보는 비교표

| 구분 | Registry of Open Data | AWS Data Exchange | S3 Access Points |
|------|-----------------------|-------------------|-------------------|
| **목적** | 공개 데이터셋 배포 | 상업적 데이터 거래 | 내부 접근 제어 분산 |
| **비용** | 무료 (다운로드만 과금) | 구독료 + Data Exchange 수수료 | S3 요금만 |
| **접근 방식** | `--no-sign-request` | 구독 후 S3 API 직접 호출 | Access Point ARN |
| **인증** | 불필요 (익명) | AWS 계정 + 구독 승인 | IAM + AP 정책 |
| **적합한 시나리오** | 연구·공공 데이터 | 금융·날씨·ML 데이터 판매 | 다수 팀/파트너 접근 관리 |

---

## 1. Registry of Open Data (공개 데이터)

### 무엇인가요?

AWS가 호스팅하는 공개 데이터셋 컬렉션입니다. 2026년 기준 **400개 이상**의 데이터셋이 등록되어 있으며, 누구나 무료로 접근할 수 있습니다. GitHub(`awslabs/open-data-registry`)에서 커뮤니티 기반으로 관리됩니다.

### 아키텍처

```
┌─────────────────────────────────────────────┐
│          Registry of Open Data on AWS        │
│           (registry.opendata.aws)            │
│                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐    │
│  │ NASA    │  │ NOAA    │  │ Common  │    │
│  │ Landsat │  │ Weather │  │ Crawl   │    │
│  └────┬────┘  └────┬────┘  └────┬────┘    │
│       │            │            │           │
│       ▼            ▼            ▼           │
│  ┌─────────────────────────────────────┐    │
│  │         Amazon S3 (공개 버킷)        │    │
│  │    s3://sentinel-s2-l1c/            │    │
│  │    s3://landsat-pds/                │    │
│  │    s3://commoncrawl/                │    │
│  └─────────────────────────────────────┘    │
│       ▲            ▲            ▲           │
│       │            │            │           │
│    ┌──┴──┐     ┌──┴──┐     ┌──┴──┐        │
│    │연구자│     │기업  │     │개발자│        │
│    └─────┘     └─────┘     └─────┘        │
└─────────────────────────────────────────────┘
```

### 대표 데이터셋

| 카테고리 | 대표 데이터셋 | 활용 예시 |
|----------|--------------|----------|
| 지구 관측 | Landsat, Sentinel-2, MODIS | 위성 영상, 지표면 변화 감지 |
| 생명 과학 | 1000 Genomes, TCGA, gnomAD | 유전체, 암 연구 |
| 기상/환경 | NOAA GOES, NEXRAD | 기상 관측, 기후 예측 |
| 자연어 처리 | Common Crawl, Wikipedia | LLM 사전 학습 |
| 공간 정보 | Terrain Tiles, OpenStreetMap | 지형, 지도 데이터 |

### AWS CLI로 접근하기

```bash
# 인증 없이 버킷 목록 확인
aws s3 ls s3://sentinel-s2-l1c/ --no-sign-request

# 데이터 다운로드
aws s3 cp s3://sentinel-s2-l1c/tiles/54/S/WE/2024/ ./data/ \
  --recursive --no-sign-request
```

핵심은 `--no-sign-request` 옵션입니다. AWS 계정 없이도 공개 데이터셋에 바로 접근할 수 있습니다.

---

## 2. AWS Data Exchange (데이터 마켓플레이스)

### 무엇인가요?

서드파티 데이터를 구독/판매하는 마켓플레이스입니다. 데이터 제공자는 자신의 S3 버킷에 데이터를 그대로 둔 채(**In-place 접근**) 구독자에게 직접 접근 권한을 부여합니다. 결제, 라이선스, 구독 관리를 AWS가 자동으로 처리합니다.

### 전통적 방식 vs Data Exchange

```
[전통] 복사 기반
제공자 S3 ──복사──► 구독자 S3 ──► 분석
  ❌ 데이터 중복, 스토리지 비용, 동기화 문제

[Data Exchange] 현재 위치 접근
제공자 S3 ──────직접 접근──────► 구독자 분석
  ✅ 복사 없음, 비용 절감, 항상 최신 데이터
```

### 작동 흐름

```
┌──────────────────┐                        ┌──────────────────┐
│   데이터 제공자    │                        │   데이터 구독자    │
│                  │     AWS Data Exchange  │                  │
│  S3 버킷         │     ┌──────────────┐   │  자체 버킷 불필요  │
│  ┌────────────┐  │     │ 구독 관리     │   │                  │
│  │dataset/    │◄─┼─────│ 라이선스 관리 │───┼─►Athena 직접 쿼리│
│  │  data.parq │  │     │ 결제/청구     │   │   EMR 처리       │
│  │  data.csv  │  │     │ 권한 부여/회수│   │   SageMaker ML   │
│  └────────────┘  │     └──────────────┘   │                  │
└──────────────────┘            │           └──────────────────┘
                        ┌───────┴────────┐
                        │  AWS Marketplace│
                        │  데이터 카탈로그  │
                        │  3,500+ 데이터셋 │
                        └────────────────┘
```

### 3단계 프로세스

1. **구독** — AWS Marketplace에서 데이터셋 검색 후 구독 신청 (유료/무료)
2. **전송** — 승인되면 S3 API로 제공자 버킷에 직접 접근 (복사 불필요)
3. **사용** — Athena, EMR, SageMaker 등에서 바로 분석

### 구독 라이프사이클

```
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ 1.검색  │─►│ 2.구독  │─►│ 3.승인  │─►│ 4.접근  │─►│ 5.갱신/ │
│카탈로그 │  │  신청   │  │  대기   │  │  활성   │  │  만료   │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘
  Marketplace  요금제 선택  제공자 승인  S3 API 접근  자동 권한회수
```

<details>
<summary><b>Data Exchange 데이터셋 생성 (전체 코드)</b></summary>

```bash
# 제공자: 데이터셋 등록
aws dataexchange create-data-set \
  --name "Weather Analytics Data" \
  --asset-type S3_DATA_ACCESS \
  --description "Daily weather data"

# 구독자: 데이터셋 검색
aws dataexchange list-data-sets

# 구독자: S3 데이터 직접 접근 (In-place)
aws s3 ls s3://dataprovider-bucket/dataset/ \
  --request-payer requester
```

</details>

### Data Exchange vs 직접 버킷 공유

| 특징 | AWS Data Exchange | 직접 버킷 정책 공유 |
|------|-------------------|---------------------|
| 데이터 복사 | 불필요 (In-place) | 불필요 |
| 결제/청구 | AWS가 자동 처리 | 직접 구현 필요 |
| 라이선스 관리 | 서비스 내장 | 직접 관리 |
| 구독 관리 | 자동 (시작/종료/갱신) | 수동 정책 업데이트 |
| 데이터 카탈로그 | AWS Marketplace 노출 | 별도 홍보 필요 |
| 권한 회수 | 구독 만료시 자동 | 수동 정책 제거 |
| 적합한 시나리오 | 상업적 데이터 판매 | 파트너 간 무료 공유 |

---

## 3. S3 Access Points (세밀한 접근 제어)

### 무엇인가요?

하나의 버킷에 여러 접근 지점(Access Point)을 생성하여, 각 애플리케이션이나 팀에 맞춤형 정책을 적용하는 기능입니다. 버킷 정책이 수백 줄로 비대해지는 문제를 해결합니다.

### 왜 필요한가?

```
[기존] 복잡한 단일 버킷 정책
┌─────────────────────────────────────┐
│ 버킷 정책 (수백 줄)                  │
│  IF 사용자 == TeamA → /team-a/ 접근 │
│  IF 사용자 == TeamB → /team-b/ 접근 │
│  IF 사용자 == Public → /public/ 읽기│
│  IF VPC == prod → 쓰기 허용         │
│  ... (규칙이 계속 증가)              │
│  ❌ 관리 어려움, 실수 위험            │
└─────────────────────────────────────┘
              │  ▼ 개선
[Access Points] 정책 분산 관리
┌──────────┐ ┌──────────┐ ┌──────────┐
│ AP 정책 A│ │ AP 정책 B│ │ AP 정책 C│
│ TeamA용  │ │ TeamB용  │ │ Public용 │
│ 깔끔! ✅ │ │ 깔끔! ✅ │ │ 깔끔! ✅ │
└──────────┘ └──────────┘ └──────────┘
```

### 아키텍처

```
┌───────────────────────────────────────────────────┐
│                  하나의 S3 버킷                      │
│                   "shared-data"                     │
│                                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ /team-a/│  │ /team-b/│  │ /public/│           │
│  │ data... │  │ data... │  │ data... │           │
│  └────┬────┘  └────┬────┘  └────┬────┘           │
└───────┼─────────────┼─────────────┼───────────────┘
        │             │             │
 ┌──────┴──────┐ ┌───┴───────┐ ┌──┴──────────┐
 │ Access Point│ │Access Point│ │Access Point │
 │ "team-a-ap" │ │"team-b-ap" │ │"public-ap"  │
 │ 권한: 읽기/쓰기│ │권한: 읽기만│ │권한: 공개읽기│
 │ VPC: vpc-a  │ │VPC: vpc-b │ │VPC: 제한없음 │
 └──────┬──────┘ └───┬───────┘ └──┬──────────┘
        │             │             │
 ┌──────┴──────┐ ┌───┴───────┐ ┌──┴──────────┐
 │   Team A   │ │  Team B   │ │  전 세계     │
 │  애플리케이션│ │ 데이터분석│ │   사용자     │
 └────────────┘ └───────────┘ └─────────────┘
```

### 이중 정책 평가

Access Point를 통한 요청은 **Access Point 정책**과 **버킷 정책**이 모두 평가됩니다. 두 정책이 모두 허용해야 최종적으로 접근이 허용됩니다.

```
요청 수신
   │  ▼
┌──────────────────────┐
│ 1. Access Point 정책  │
│    평가               │
│  Deny? ──YES──► ❌ 거부│
│    │   NO (Allow)     │
└──────┬───────────────┘
       │  ▼
┌──────────────────────┐
│ 2. 버킷 정책 평가     │
│  Deny? ──YES──► ❌ 거부│
│    │   NO (Allow)     │
└──────┬───────────────┘
       │  ▼
    ✅ 허용
```

<details>
<summary><b>Access Point 생성 + 정책 설정 (전체 코드)</b></summary>

```bash
# Access Point 생성
aws s3control create-access-point \
  --name "team-a-ap" \
  --bucket "shared-data" \
  --account-id "123456789012"

# Access Point 전용 정책 설정
aws s3control put-access-point-policy \
  --name "team-a-ap" \
  --account-id "123456789012" \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:ap-northeast-2:123456789012:accesspoint/team-a-ap/object/*"
      ]
    }]
  }'

# Access Point를 통해 객체 접근
aws s3 cp data.csv \
  s3://arn:aws:s3:ap-northeast-2:123456789012:accesspoint/team-a-ap/data.csv
```

</details>

### VPC Access Point (프라이빗 네트워크)

VPC 제한 Access Point를 생성하면, 지정된 VPC에서만 접근할 수 있습니다. 외부 인터넷이나 다른 VPC의 요청은 자동으로 차단됩니다.

```
┌──────────────┐         ┌──────────────┐
│  사내 VPC    │ ──✅──► │ Access Point │ ──► S3 버킷
│  vpc-0abc... │         │ "internal-ap"│
└──────────────┘         └──────────────┘
┌──────────────┐         ┌──────────────┐
│  외부 인터넷  │ ──❌──► │ Access Point │ 접근 거부!
│  (다른 VPC)  │         │ "internal-ap"│
└──────────────┘         └──────────────┘
```

<details>
<summary><b>VPC 제한 Access Point 생성</b></summary>

```bash
aws s3control create-access-point \
  --name "internal-ap" \
  --bucket "shared-data" \
  --account-id "123456789012" \
  --vpc-configuration VpcId=vpc-0abc123def456
```

</details>

### Best Practices

| 실천 항목 | 설명 |
|-----------|------|
| 정책 분산 | 팀/앱마다 별도 Access Point 사용 — 버킷 정책은 최소화 |
| VPC 제한 | 민감 데이터는 VPC 전용 AP로 인터넷 차단 |
| Prefix 격리 | 각 AP에 다른 prefix 매핑 — `/team-a/`, `/team-b/` |
| 버킷 정책 위임 | 버킷 정책에서 AP 통과를 명시적 허용 |
| Multi-Region AP | 글로벌 서비스시 자동 장애조치 + 지연시간 최적화 |

---

## 언제 무엇을 쓸까?

| 상황 | 추천 서비스 | 이유 |
|------|------------|------|
| 공개 연구·공공 데이터를 무료로 배포 | **Registry of Open Data** | 인증·결제 불필요, 커뮤니티 카탈로그 노출 |
| 상업 데이터를 유료로 판매 | **AWS Data Exchange** | 결제·라이선스·구독을 AWS가 자동 처리 |
| 다수 내부 팀의 버킷 접근을 관리 | **S3 Access Points** | 버킷 정책 분산으로 관리 복잡도 해결 |
| 파트너사와 VPC 내에서 안전하게 공유 | **Access Points + VPC** | 네트워크 수준 접근 제어 |
| 글로벌 다중 리전 데이터 공유 | **Multi-Region Access Points** | 단일 글로벌 엔드포인트 + 자동 장애조치 |

```
┌─────────────────────────────────────────────┐
│           어떤 방식을 선택할까?               │
│                                              │
│  상업적 데이터 판매?  ──YES──► Data Exchange  │
│        │                                     │
│       NO → 다수 구독자? ──YES──► Data Exchange│
│        │                                     │
│       NO → 공개 데이터?  ──YES──► Registry    │
│        │                                     │
│       NO → 내부 다수 팀?  ──YES──► Access Pts │
└─────────────────────────────────────────────┘
```

---

## Takeaway

1. **공개 데이터는 Registry of Open Data** — 무료 호스팅, `--no-sign-request`로 누구나 접근
2. **상업 데이터는 Data Exchange** — 결제·라이선스·전송을 한 번에, 데이터 복사 없이 In-place 접근
3. **대규모 내부 공유는 Access Points** — 버킷 정책을 분산시켜 관리 복잡도를 해결

---

> **S3 시리즈 2/7**
>
> | | |
> |---|---|
> | ← [S3 프로토콜과 API — 개요부터 실전 활용까지]({% post_url 2026-06-13-S3-Protocol-and-API-Deep-Dive %}) | |
> | | [S3 Access Grants와 복제로 대규모 데이터 공유하기]({% post_url 2026-06-13-S3-Access-Grants-and-Replication %}) → |
