---
layout: post
title: "S3 Access Grants와 복제로 대규모 데이터 공유하기"
categories: [AWS, S3]
description: S3 Access Grants로 세분화된 권한 관리를, 교차 리전 복제로 글로벌 데이터 공유를 구현하는 방법을 정리합니다.
keywords: [S3, AccessGrants, CRR, SRR, 복제, 데이터공유]
toc: true
toc_sticky: true
---

## Hook

> 1,000명의 사용자에게 S3 권한을 일일이 IAM 정책으로 관리해야 한다면? Access Grants로 데이터 카탈로그 기반 권한 관리를, 복제로 글로벌 공유를 해결합니다.

기업 환경에서 데이터 접근 권한을 관리하는 일은 규모가 컨질수록 통제 불능 상태에 빠집니다. 버킷 정책이 수백 줄로 비대해지고, IAM 정책이 사용자 수만큼 증식합니다. 여기에 글로벌 팀이 더해지면, 지연 시간과 데이터 주권 문제까지 겹칩니다.

이 글에서는 두 가지 접근법을 정리합니다. **S3 Access Grants**로 대규모 권한 관리를 단순화하고, **복제(CRR/SRR)**로 데이터를 물리적으로 분산시켜 글로벌 공유와 재해 복구를 해결합니다.

---

## TL;DR

- **Access Grants**: IAM 정책 대신 데이터 카탈로그 기반으로 권한 부여 — 대규모 관리 간소화
- **CRR (Cross-Region Replication)**: 다른 리전으로 자동 복제 — 글로벌 접근 속도 향상
- **SRR (Same-Region Replication)**: 같은 리전 내 복제 — 계정 분리/백업
- **RTC (Replication Time Control)**: 15분 내 복제 보장 — 규정 준수용

---

## Part 1: S3 Access Grants

### 왜 필요한가?

기업 환경에서는 수백~수천 명의 직원이 S3 데이터에 접근해야 합니다. 전통적인 IAM 정책 방식은 사용자와 버킷 접두사 조합이 늘어날수록 정책이 폭발적으로 증가합니다. 버킷당 JSON 20KB 제한에 도달하기도 전에, 관리는 이미 통제 불능 상태가 됩니다.

![IAM 정책 한계와 Access Grants 해결](/assets/images/posts/s3-access-control-replication/07-01-11-왜-access-grants가-필요한가.svg)

| 문제 | IAM 정책의 한계 | Access Grants 해결 |
|------|----------------|---------------------|
| 권한 폭발 | 버킷/접두사별로 정책이 무한 증가 | Grant 하나로 디렉토리 수준 권한 부여 |
| 관리 복잡성 | IT 팀이 모든 정책을 수동 관리 | 셀프서비스 권한 위임 가능 |
| 디렉토리 연동 | IAM 사용자와 AD/LDAP 간 수동 매핑 | IAM Identity Center 자동 연동 |
| 감사 추적 | 여러 정책에 분산되어 추적 어려움 | 중앙 집중식 Grant 관리 + CloudTrail |
| 일시적 권한 | 정책은 영구적, 임시 권한 부여 복잡 | 임시 자격 증명(최대 1시간) 자동 발급 |

핵심은 **정책이 아니라 권한 부여(Grant)로 관리**하는 것입니다. Access Grants는 IAM 정책을 대체하는 것이 아니라, 정책 관리를 자동화하는 상위 레벨의 권한 부여 메커니즘입니다.

### 아키텍처

![Access Grants 전체 구조](/assets/images/posts/s3-access-control-replication/07-02-21-전체-아키텍처.svg)

전체 구조는 4개 핵심 컴포넌트로 이루어집니다.

| 컴포넌트 | 역할 |
|----------|------|
| **Instance** | Access Grants 인스턴스 — 계정 내 권한 관리의 최상위 컨테이너 |
| **Location** | 등록된 위치 — S3 버킷/접두사 경로를 권한 범위로 매핑 |
| **Grant** | 권한 부여 — 대상(사용자/그룹)에 READ/WRITE/READWRITE 권한 할당 |
| **Target** | S3 버킷 — 임시 자격 증명으로 접근하는 실제 데이터 저장소 |

![권한 요청 흐름](/assets/images/posts/s3-access-control-replication/07-03-22-권한-요청-흐름-request-flow.svg)

사용자가 데이터에 접근하면 Access Grants가 Grant를 확인하고, 임시 STS 자격 증명(최대 1시간)을 발급합니다. 이 자격 증명으로 S3 버킷에 접근하며, Grant 범위 밖 경로는 자동으로 거부됩니다.

### 설정 3단계

![설정 3단계 개요](/assets/images/posts/s3-access-control-replication/07-04-31-설정-단계-개요.svg)

설정은 인스턴스 생성, 위치 등록, Grant 생성의 3단계로 진행합니다.

```bash
# Step 1: Access Grants 인스턴스 생성
aws s3control create-access-grants-instance \
  --account-id 999999999999 \
  --identity-center-arn arn:aws:identitycenter:ap-northeast-2:999999999999:instance/ssoins-abc123

# Step 2: S3 위치 등록
aws s3control create-access-grants-location \
  --account-id 999999999999 \
  --location-scope "s3://company-data-bucket/analytics/" \
  --iam-role-arn arn:aws:iam::999999999999:role/S3AccessGrantsAnalyticsRole

# Step 3: Grant 생성 (디렉토리 그룹에 READWRITE 권한)
aws s3control create-access-grant \
  --account-id 999999999999 \
  --access-grants-location-id loc-abc123 \
  --permission READWRITE \
  --grantee '{"GranteeType":"DIRECTORY_GROUP","GranteeIdentifier":"DataScience-Team"}'
```

Grant 대상으로는 IAM 사용자, IAM 역할, 디렉토리 사용자(SSO), 디렉토리 그룹 중 선택할 수 있습니다. 권한은 `READ`, `WRITE`, `READWRITE` 세 가지입니다.

![자격 증명 유형](/assets/images/posts/s3-access-control-replication/07-05-41-iam-role-access-grants-자격-증명.svg)

<details>
<summary><b>전체 CLI 설정 코드 (인스턴스 + 위치 + Grant + 임시 자격 증명 발급)</b></summary>

```bash
# ── 1. Access Grants용 IAM 역할 생성 ──
aws iam create-role \
  --role-name S3AccessGrantsRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "access-grants.s3.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# 역할에 S3 접근 권한 부여
aws iam put-role-policy \
  --role-name S3AccessGrantsRole \
  --policy-name S3AccessPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject","s3:ListBucket","s3:PutObject","s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::company-data-bucket",
        "arn:aws:s3:::company-data-bucket/*"
      ]
    }]
  }'

# ── 2. Access Grants 인스턴스 생성 ──
aws s3control create-access-grants-instance \
  --account-id 999999999999 \
  --identity-center-arn arn:aws:identitycenter:ap-northeast-2:999999999999:instance/ssoins-abc123

# ── 3. 등록된 위치 생성 (버킷 전체 + 특정 접두사) ──
aws s3control create-access-grants-location \
  --account-id 999999999999 \
  --location-scope "s3://company-data-bucket/" \
  --iam-role-arn arn:aws:iam::999999999999:role/S3AccessGrantsRole

aws s3control create-access-grants-location \
  --account-id 999999999999 \
  --location-scope "s3://company-data-bucket/analytics/" \
  --iam-role-arn arn:aws:iam::999999999999:role/S3AccessGrantsAnalyticsRole

# ── 4. Grant 생성 (다양한 대상) ──
# 디렉토리 사용자에게 읽기 권한
aws s3control create-access-grant \
  --account-id 999999999999 \
  --access-grants-location-id loc-abc123 \
  --permission READ \
  --grantee '{"GranteeType":"DIRECTORY_USER","GranteeIdentifier":"alice@company.com"}'

# 디렉토리 그룹에 읽기/쓰기 권한
aws s3control create-access-grant \
  --account-id 999999999999 \
  --access-grants-location-id loc-def456 \
  --permission READWRITE \
  --grantee '{"GranteeType":"DIRECTORY_GROUP","GranteeIdentifier":"DataScience-Team"}'

# ── 5. 임시 자격 증명 발급 ──
aws s3control get-access-grant \
  --account-id 999999999999 \
  --grant-id grant-001
```

```python
# SDK로 임시 자격 증명 획득 후 S3 접근
import boto3

s3control = boto3.client('s3control')
response = s3control.get_access_grant(
    AccountId='999999999999',
    AccessGrantId='grant-001'
)

credentials = response['Credentials']
s3_client = boto3.client(
    's3',
    aws_access_key_id=credentials['AccessKeyId'],
    aws_secret_access_key=credentials['SecretAccessKey'],
    aws_session_token=credentials['SessionToken']
)

# Grant 범위 내 데이터 접근 (성공)
s3_client.get_object(Bucket='company-data-bucket', Key='analytics/sales_2025.csv')

# Grant 범위 밖 접근 시도 → AccessDenied (예상된 동작)
```

</details>

### 부서별 시나리오

![부서별 데이터 접근 권한 자동화](/assets/images/posts/s3-access-control-replication/07-06-51-시나리오-부서별-데이터-접근-권한-자동화.svg)

데이터 레이크 하나를 부서별 접두사로 분할하고, 각 디렉토리 그룹에 Grant를 매핑합니다. 예를 들어 `Sales-Team`은 `sales/`에 READ, `Sales-Managers`는 같은 경로에 READWRITE를 부여합니다. 관리자 권한과 일반 사용자 권한을 Grant 하나로 분리할 수 있습니다.

또한 EventBridge + Lambda로 IAM Identity Center 그룹 멤버십 변경을 감지하여, 신규 입사자에게 자동으로 Grant를 부여하고 퇴사자의 권한을 즉시 회수할 수 있습니다.

### 선택 가이드

![선택 가이드 다이어그램](/assets/images/posts/s3-access-control-replication/07-07-62-선택-가이드-다이어그램.svg)

| 상황 | 권장 방식 | 이유 |
|------|----------|------|
| 사내 50명 이상, AD/SSO 환경 | **Access Grants** + IAM Identity Center | 디렉토리 연동, 정책 폭발 방지 |
| 사내 50명 이하 | IAM 정책 (간단) | 관리 오버헤드 최소 |
| 특정 파트너 계정에 공유 | **Access Points** + 버킷 정책 | 접근 지점 분리 |
| 교차 계정 전체 버킷 공유 | 버킷 정책 | 단순 교차 계정 위임 |
| 공개 데이터 | 버킷 정책 (Public Read) | 인증 불필요 |
| 임시 파일 공유 | Pre-signed URL | 만료 시간 기반 일회성 |

| 비교 항목 | Access Grants | IAM 정책 | 버킷 정책 |
|----------|---------------|----------|-----------|
| 관리 주체 | 데이터 관리자 (셀프서비스) | IT 관리자 | 버킷 소유자 |
| 디렉토리 연동 | 지원 (AD/LDAP/SSO) | 미지원 | 미지원 |
| 임시 자격 증명 | 자동 발급 (최대 1시간) | 영구 정책 | 영구 정책 |
| 정책 크기 제한 | Grant당 독립 (사실상 무제한) | 10KB / 2KB | 20KB |
| 확장성 | 수천~수만 사용자 | 정책 수 폭발 | 버킷당 1개 |
| 비용 | Grant당 $0.003/월 | 무료 | 무료 |

> 50명 이상의 조직에서 AD/SSO를 사용한다면, Access Grants가 관리 복잡도를 극적으로 낮춰줍니다.

---

## Part 2: S3 복제로 데이터 공유

### 복제 vs 즉시 공유

데이터를 공유하는 방법은 크게 두 가지입니다. **In-place 공유**(Access Points, Access Grants, Data Exchange)는 데이터를 복사하지 않고 원본 위치에서 직접 접근합니다. **복제**는 물리적으로 데이터를 복사하여 별도 버킷에 배치합니다.

![복제 vs 즉시 공유](/assets/images/posts/s3-access-control-replication/08-01-12-복제-vs-in-place-공유.svg)

| 구분 | In-place 공유 | 복제 기반 공유 |
|------|--------------|----------------|
| 스토리지 비용 | 1배 (원본만) | 2배 (원본 + 복제본) |
| 데이터 일관성 | 강한 일관성 (직접 접근) | eventual (복제 지연) |
| 지연 시간 | 원본 리전 접근 (원격 시 지연) | 로컬 리전 접근 (최소화) |
| 원본 장애 | 접근 불가 | 복제본으로 접근 가능 |
| 독립적 관리 | 제공자 버킷에 종속 | 소비자가 자체 버킷에서 관리 |

복제는 데이터 주권, 지연 시간 최소화, 독립적 수명 주기 관리가 필요한 경우에 적합합니다.

### CRR: 교차 리전 복제

![교차 계정 복제 공유](/assets/images/posts/s3-access-control-replication/08-02-21-교차-계정-복제-공유.svg)

CRR(Cross-Region Replication)은 한 리전의 버킷 객체를 다른 리전의 버킷으로 자동 복제합니다. 주요 사용 사례는 다음과 같습니다.

- **글로벌 진출**: 사용자와 가까운 리전에 복제본 배치로 지연 시간 최소화
- **재해 복구**: 원본 리전 장애 시 복제본으로 서비스 연속성 확보
- **규정 준수**: 특정 국가 리전에만 데이터 저장하는 데이터 주권 요구사항

![멀티 리전 글로벌 공유](/assets/images/posts/s3-access-control-replication/08-03-22-멀티-리전-글로벌-공유.svg)

CRR을 **Multi-Region Access Points**와 조합하면, 단일 글로벌 엔드포인트 하나로 모든 리전 복제본에 자동 라우팅할 수 있습니다. 한국 사용자는 서울 복제본, 일본 사용자는 도쿄 복제본으로 접근되며, 한 리전 장애 시 자동 장애 조치됩니다.

![CRR 설정 전제 조건](/assets/images/posts/s3-access-control-replication/08-04-31-crr-설정-전제-조건.svg)

CRR 설정 전에 반드시 확인해야 할 전제 조건입니다.

- 원본 및 대상 버킷의 **버전 관리 활성화** 필수
- 원본과 대상이 **서로 다른 리전**에 위치
- 복제용 **IAM 역할** 생성 필요
- 교차 계정 시 대상 버킷의 **버킷 정책**으로 복제 권한 부여
- **기존 객체는 자동 복제되지 않음** — 신규 객체만 복제, 기존은 Batch Replication 필요

```bash
# 소스: 서울 → 대상: 도쿄 CRR 설정
aws s3api put-bucket-replication \
  --bucket source-bucket-seoul \
  --replication-configuration '{
    "Role": "arn:aws:iam::999999999999:role/S3ReplicationRole",
    "Rules": [{
      "ID": "ReplicateAllToTokyo", "Status": "Enabled", "Priority": 1,
      "Filter": {"Prefix": ""},
      "Destination": {"Bucket": "arn:aws:s3:::dest-bucket-tokyo"},
      "DeleteMarkerReplication": {"Status": "Enabled"}
    }]
  }'
```

<details>
<summary><b>CRR 전체 설정 코드 (버킷 생성 + IAM 역할 + 복제 규칙)</b></summary>

```bash
# ── Step 1: 대상 버킷 생성 및 버전 관리 (도쿄) ──
aws s3 mb s3://dest-bucket-tokyo --region ap-northeast-1
aws s3api put-bucket-versioning \
  --bucket dest-bucket-tokyo \
  --versioning-configuration Status=Enabled

# ── Step 2: 복제용 IAM 역할 생성 ──
aws iam create-role \
  --role-name S3ReplicationRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "s3.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# 역할에 복제 권한 부여
aws iam put-role-policy \
  --role-name S3ReplicationRole \
  --policy-name S3ReplicationPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {"Effect": "Allow",
       "Action": ["s3:GetObjectVersionForReplication","s3:GetObjectVersionAcl","s3:GetObjectVersionTagging"],
       "Resource": "arn:aws:s3:::source-bucket-seoul/*"},
      {"Effect": "Allow",
       "Action": ["s3:ReplicateObject","s3:ReplicateDelete","s3:ReplicateTags"],
       "Resource": "arn:aws:s3:::dest-bucket-tokyo/*"}
    ]
  }'

# ── Step 3: 소스 버킷 버전 관리 활성화 ──
aws s3api put-bucket-versioning \
  --bucket source-bucket-seoul \
  --versioning-configuration Status=Enabled

# ── Step 4: 복제 규칙 설정 ──
aws s3api put-bucket-replication \
  --bucket source-bucket-seoul \
  --replication-configuration '{
    "Role": "arn:aws:iam::999999999999:role/S3ReplicationRole",
    "Rules": [{
      "ID": "ReplicateAllToTokyo", "Status": "Enabled", "Priority": 1,
      "Filter": {"Prefix": ""},
      "Destination": {
        "Bucket": "arn:aws:s3:::dest-bucket-tokyo",
        "StorageClass": "STANDARD"
      },
      "DeleteMarkerReplication": {"Status": "Enabled"}
    }]
  }'

# ── Step 5: 복제 테스트 ──
aws s3 cp test-data.csv s3://source-bucket-seoul/data/test-data.csv
aws s3 ls s3://dest-bucket-tokyo/data/
```

</details>

### SRR: 같은 리전 복제

![SRR 특징 및 적합 시나리오](/assets/images/posts/s3-access-control-replication/08-05-41-srr-특징-및-적합-시나리오.svg)

SRR(Same-Region Replication)은 같은 리전 내에서 객체를 복제합니다. 리전 간 데이터 전송비가 발생하지 않는다는 것이 핵심 장점입니다.

| 사용 사례 | 설명 |
|-----------|------|
| 교차 계정 공유 (동일 리전) | 전송비 없이 소비자에게 독립 버킷 제공 |
| 실운영-개발 환경 분리 | 운영 데이터를 개발 버킷에 안전하게 복사 |
| 로그 집계 | 여러 앱의 로그 버킷을 중앙 버킷에 집계 |
| Read replica | 읽기 부하 분산을 위한 복제본 생성 |

### RTC: 복제 시간 보장

![RTC 개요](/assets/images/posts/s3-access-control-replication/08-06-51-rtc-개요.svg)

일반 S3 복제는 SLA가 없어, 복제 완료까지 수 초에서 수 시간이 걸릴 수 있습니다. **S3 RTC(Replication Time Control)**는 복제 완료 시간을 15분 이내로 보장합니다. 전체 객체의 **99.99%**가 15분 내에 복제됩니다.

| 특징 | 일반 복제 | S3 RTC |
|------|----------|--------|
| 복제 SLA | 없음 (Best Effort) | 15분 이내 (99.99%) |
| 복제 지연 메트릭 | 기본 CloudWatch | RTC 전용 메트릭 |
| 적합 시나리오 | 일반 데이터 공유, 백업 | 규정 준수, 재해 복구, 실시간 분석 |
| 추가 비용 | 없음 | GB당 추가 요금 |

RTC는 복제 규칙에 `ReplicationTime`과 `Metrics` 옵션을 추가하여 활성화합니다. 지연 15분 초과 시 CloudWatch 알람으로 SNS 알림을 발송하도록 설정할 수 있습니다.

### 복제 방식 선택 기준

![복제 선택 기준 플로우차트](/assets/images/posts/s3-access-control-replication/08-07-61-선택-기준-플로우차트.svg)

선택의 핵심 질문은 "데이터 이동이 필요한가?"입니다. 물리적 복사가 필요하면 복제를, 원본 위치 접근이면 In-place 공유를 선택합니다.

![하이브리드 조합 패턴](/assets/images/posts/s3-access-control-replication/08-08-63-하이브리드-조합-패턴.svg)

실제 환경에서는 여러 방식을 조합해서 사용합니다. 예를 들어 일본 소비자에게는 CRR로 도쿄 복제본을 제공하고(지연 최소화), 파트너사에는 Access Points로 In-place 접근을 허용하며(비용 최소화), 유료 고객에게는 Data Exchange로 상업적 거래를 처리합니다.

| 목적 | 방식 | 비용 | 복잡도 |
|------|------|------|--------|
| 글로벌 지연 최소화 | CRR + Multi-Region AP | 높음 (전송비 + 스토리지 2배) | 중간 |
| 계정 분리 (동일 리전) | SRR | 낮음 (전송비 없음, 스토리지 2배) | 낮음 |
| 재해 복구 | CRR (다른 리전) | 중간 | 중간 |
| 규정 준수 (15분 보장) | CRR + RTC | 높음 (RTC 추가 요금) | 중간 |
| 기존 객체 마이그레이션 | Batch Replication | 1회성 | 낮음 |
| 단순 읽기 공유 (비용 최소) | Access Points (In-place) | 최소 (스토리지 1배) | 낮음 |
| 상업적 데이터 판매 | Data Exchange (In-place) | 스토리지 1배 + 수수료 | 높음 |

---

## Takeaway

1. **대규모 권한 관리는 Access Grants** — IAM 정책 대신 데이터 카탈로그 기반으로 관리하면 정책 폭발을 막고 셀프서비스 위임이 가능합니다
2. **글로벌 공유는 CRR, 계정 분리는 SRR** — 목적에 따라 복제 방식을 선택하면 지연 시간과 비용을 모두 최적화할 수 있습니다
3. **복제 시간이 중요하면 RTC 활성화** — 15분 내 99.99% 복제 보장으로 규정 준수와 실시간 분석 요구사항을 충족합니다
