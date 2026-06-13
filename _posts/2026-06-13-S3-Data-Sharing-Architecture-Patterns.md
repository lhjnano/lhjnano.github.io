---
layout: post
title: "S3 데이터 공유 아키텍처 — 6가지 패턴과 선택 가이드"
categories: [AWS, S3, Architecture]
description: S3 기반 데이터 공유 아키텍처의 6가지 패턴을 정리합니다. 데이터 레이크, 멀티 계정 허브, 연합 분석, 마켓플레이스, 글로벌 복제, 이벤트 기반 공유까지.
keywords: [S3, 아키텍처, 데이터레이크, LakeFormation, EventBridge, 데이터공유]
toc: true
toc_sticky: true
---

## Hook

> 조직 규모가 커지면 데이터 공유 방식도 달라져야 합니다. 소규모 팀의 버킷 공유부터 글로벌 연합 분석까지 — 상황에 맞는 6가지 아키텍처 패턴을 소개합니다.

팀 하나일 때는 버킷 정책 한 줄이면 충분합니다. 하지만 부서가 여러 개로 나뉘고, 계정이 분리되고, 규제가 걸리고, 글로벌 사용자가 붙기 시작하면 "데이터를 어떻게 공유할 것인가"는 완전히 다른 문제가 됩니다. 이 글에서는 S3를 중심으로 한 **6가지 데이터 공유 아키텍처 패턴**을 정리하고, 상황에 따라 어떤 패턴을 선택해야 하는지 가이드합니다.

---

## TL;DR

- **패턴 1: 데이터 레이크 공유** — 단일 S3 + Access Points + Lake Formation
- **패턴 2: 멀티 계정 데이터 허브** — Organizations + hub-and-spoke
- **패턴 3: 연합 데이터 분석** — Athena Federated Query로 이기종 분산 쿼리
- **패턴 4: 데이터 마켓플레이스** — AWS Data Exchange로 외부 데이터 거래
- **패턴 5: 글로벌 데이터 복제** — CRR + Multi-Region Access Points
- **패턴 6: 이벤트 기반 공유** — S3 + EventBridge + Lambda

---

## 왜 아키텍처 패턴이 필요한가

"그냥 버킷 권한 열어주면 안 되나?" — 작은 규모에서는 됩니다. 하지만 아래 상황이 하나라도 겹치면 패턴 없는 접근은 기술 부채가 됩니다.

- **계정이 여러 개** → 교차 계정 권한, 비용 추적, 보안 격리
- **데이터를 옮길 수 없음** → 규제, 데이터 주권, 복사 비용
- **외부 데이터가 필요함** → 날씨, 금융, 인구통계 등 서드파티 결합
- **글로벌 사용자** → 지연 시간, 재해 복구
- **실시간 반응** → 데이터 변경 즉시 처리

이 다섯 가지 압력이 어떻게 조합되느냐에 따라 적합한 패턴이 달라집니다. 먼저 전체를 한눈에 보고, 그 다음 하나씩 파겠습니다.

### 6가지 패턴 개요

![S3 데이터 공유 아키텍처 패턴 6종 카탈로그 — 단일 소스 공유부터 이벤트 기반 처리까지](/assets/images/posts/s3-architecture-patterns/12-01-diagram.svg)

| 패턴 | 복잡도 | 적합 규모 | 핵심 서비스 |
|------|--------|-----------|-------------|
| 1. 데이터 레이크 공유 | 낮음 | 소규모 팀/부서 | S3 + Access Points + Lake Formation |
| 2. 멀티 계정 데이터 허브 | 중간 | 중대형 기업 | Organizations + SCP + Access Points |
| 3. 연합 데이터 분석 | 높음 | 규제 산업 | Athena Federated Query / Redshift Spectrum |
| 4. 데이터 마켓플레이스 | 중간 | 데이터 비즈니스 | AWS Data Exchange |
| 5. 글로벌 데이터 복제 | 높음 | 글로벌 서비스 | CRR + Multi-Region Access Points |
| 6. 이벤트 기반 공유 | 중간 | 실시간 파이프라인 | S3 Events + EventBridge + Lambda |

---

## 패턴 1: 데이터 레이크 공유

하나의 S3 버킷을 중심으로 Access Points와 Lake Formation으로 권한을 관리하는 **가장 기본적인 패턴**입니다. "단일 소스, 다수 소비자" 구조입니다.

![데이터 레이크 공유 아키텍처 — S3 버킷의 raw/curated/analytics 계층을 Access Points와 Lake Formation으로 다수 소비자에게 공유](/assets/images/posts/s3-architecture-patterns/12-02-1-패턴-1-데이터-레이크-공유-아키텍처.svg)

### 어떻게 구성되나

데이터 레이크를 **계층(Raw → Curated → Analytics)** 으로 나누고, 각 계층마다 별도의 Access Point를 둡니다. Lake Formation이 테이블·컬럼 수준의 세분화된 권한을 부여합니다.

![데이터 레이크 계층 구조 상세 — raw/curated/analytics 폴더 구조와 계층별 Access Point 매핑](/assets/images/posts/s3-architecture-patterns/12-03-컴포넌트-상세.svg)

- `/raw/` — 원본 데이터, 변경 불가 (제한적 접근)
- `/curated/` — 정제된 분석용 데이터 (분석가)
- `/analytics/` — 집계 결과, 대시보드용 (QuickSight 연동)

**핵심 포인트**: 데이터를 복제하지 않고 단일 소스에서 다수 소비자에게 권한만 분배합니다.

<details>
<summary><b>📖 데이터 레이크 공유 설정 코드 보기</b></summary>

```python
import boto3

s3 = boto3.client('s3')
glue = boto3.client('glue')
lf = boto3.client('lakeformation')

# 1. 계층별 Access Point 생성
for layer in ['raw', 'curated', 'analytics']:
    s3.create_access_point(
        AccountId='123456789012',
        Bucket='data-lake-bucket',
        Name=f'{layer}-ap',
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': True,
            'IgnorePublicAcls': True,
            'BlockPublicPolicy': True,
            'RestrictPublicBuckets': True
        }
    )

# 2. Glue Data Catalog에 공유 데이터베이스 생성
glue.create_database(DatabaseInput={
    'Name': 'shared_data_lake',
    'Description': 'Shared data lake for cross-team analytics'
})

# 3. Lake Formation으로 소비자에게 권한 부여
lf.grant_permissions(
    Principal={'DataLakePrincipalIdentifier': 'arn:aws:iam::999999999999:role/AnalystRole'},
    Resource={'Database': {'Name': 'shared_data_lake'}},
    Permissions=['ALL'],
    PermissionsWithGrantOption=[]
)
```

</details>

### 장점 · 단점 · 적합 시나리오

- **장점**: 단일 데이터 소스로 일관성 보장, 비용 효율적(복제 불필요), 중앙 집중 관리
- **단점**: 단일 실패점(SPOF) 위험, 데이터 제공자 부하 집중
- **적합 시나리오**: 부서 간 데이터 공유, 데이터 레이크하우스, BI 대시보드

---

## 패턴 2: 멀티 계정 데이터 허브

AWS Organizations 환경에서 **중앙 데이터 계정을 허브로 두고, 각 팀 계정을 스포크로 연결**하는 hub-and-spoke 패턴입니다.

![멀티 계정 데이터 허브 아키텍처 — 중앙 데이터 계정이 hub가 되고 마케팅/엔지니어링/재무/ML 팀 계정이 spoke로 접근](/assets/images/posts/s3-architecture-patterns/12-04-2-패턴-2-멀티-계정-데이터-허브.svg)

### 어떻게 구성되나

중앙 데이터 계정에 `raw-data`, `analytics`, `Glue Catalog`를 두고, 팀마다 전용 Access Point를 생성합니다. Organizations의 SCP(Service Control Policy)로 허용 범위를 제한합니다.

**핵심 포인트**: 계정 분리로 보안 격리와 비용 추적이 명확해집니다. 재무 팀은 VPC 제한 Access Point로 네트워크 수준까지 격리할 수 있습니다.

<details>
<summary><b>📖 Organizations SCP + 버킷 정책 예시 보기</b></summary>

```python
import boto3, json

s3 = boto3.client('s3')
org = boto3.client('organizations')
org_id = org['Organization']['Id']

# 조직 내 MarketingDataRole만 marketing/ 접근 허용
bucket_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "AllowOrgMarketingAccess",
        "Effect": "Allow",
        "Principal": "*",
        "Action": ["s3:GetObject", "s3:ListBucket"],
        "Resource": [
            "arn:aws:s3:::central-data-hub",
            "arn:aws:s3:::central-data-hub/marketing/*"
        ],
        "Condition": {
            "StringEquals": {"aws:PrincipalOrgID": org_id},
            "ArnLike": {"aws:PrincipalArn": "arn:aws:iam::*:role/MarketingDataRole"}
        }
    }]
}
s3.put_bucket_policy(Bucket='central-data-hub', Policy=json.dumps(bucket_policy))
```

</details>

### 장점 · 단점 · 적합 시나리오

- **장점**: 계정 분리로 보안 격리, 팀별 비용 추적, 감사 추적 용이
- **단점**: 다계정 관리 복잡도, Access Point 수 증가, 초기 설정 공수
- **적합 시나리오**: 중대형 기업, 규제 산업, 멀티 팀 환경, 데이터 거버넌스 필수

---

## 패턴 3: 연합 데이터 분석 (Federated Analytics)

데이터는 각 부서 계정에 그대로 두고, **쿼리 결과만 공유**하는 분산형 패턴입니다. 데이터를 복사하지 않습니다.

![연합 데이터 분석 아키텍처 — 부서 A/B/C가 각자 S3에 데이터를 보유하고 Athena Federated Query로 교차 쿼리, 결과만 중앙 버킷에 저장](/assets/images/posts/s3-architecture-patterns/12-05-3-패턴-3-연합-데이터-분석-federated-analytics.svg)

### 어떻게 구성되나

각 부서는 자신의 S3 버킷에 Access Point만 열어둡니다. 중앙의 **Athena Federated Query** 또는 **Redshift Spectrum**이 여러 계정의 데이터를 조인하고, 결과만 별도 버킷에 저장합니다.

```sql
-- 부서 A의 판매 데이터와 부서 B의 고객 데이터를 조인
-- 데이터는 각자의 S3 버킷에 있음 (이동 없음)
SELECT a.product_id, a.sale_amount, b.customer_segment
FROM department_a.sales a
JOIN department_b.customers b
  ON a.customer_id = b.customer_id
WHERE a.sale_date >= DATE '2025-01-01';
```

**핵심 포인트**: 데이터 주권이 중요하거나 복사가 규제상 불가능한 환경에서 유일한 선택지입니다. 쿼리 성능 오버헤드가 있는 대신, 스토리지 비용과 컴플라이언스 리스크를 줄입니다.

- **적합 시나리오**: 규제 산업(금융/의료), 국가 간 데이터 처리 제한, M&A 후 시스템 통합 전
- **비용**: Athena $5/TB 스캔 + 교차 계정 데이터 전송비

---

## 패턴 4: 데이터 마켓플레이스

AWS Data Exchange를 기반으로 **외부 데이터를 구독하고 유통**하는 패턴입니다. 날씨, 금융, 인구통계 같은 서드파티 데이터를 결합할 때 사용합니다.

![데이터 마켓플레이스 아키텍처 — 데이터 제공자가 Data Exchange에 데이터셋 등록, 소비자가 구독하면 S3에 자동 배포 및 Glue Catalog 등록](/assets/images/posts/s3-architecture-patterns/12-06-4-패턴-4-데이터-마켓플레이스.svg)

### 어떻게 구성되나

제공자가 데이터셋을 Data Exchange에 등록하면, 소비자는 카탈로그에서 탐색·구독합니다. 구독이 완료되면 데이터가 소비자의 S3로 자동 복제되고 Glue Catalog에 테이블이 등록됩니다.

흐름은 단순합니다: **데이터셋 등록 → 카탈로그 탐색 → 구독/결제 → 자산 배포(S3 직접 또는 API)**.

**핵심 포인트**: 결제, 라이선스, 업데이트 자동 배포를 AWS가 처리합니다. 데이터 비즈니스를 하거나 외부 데이터를 결합해야 할 때 적합합니다.

- **장점**: 상업적 데이터 유통 인프라 제공, 결제/라이선스 자동 관리, 자동 업데이트 배포
- **단점**: Data Exchange 수수료, 제공자/소비자 모두 AWS 필요
- **적합 시나리오**: 데이터 비즈니스, 서드파티 데이터 결합(금융·날씨·인구통계), 파트너 데이터 교환

---

## 패턴 5: 글로벌 데이터 복제

CRR(Cross-Region Replication)과 **Multi-Region Access Points**로 여러 리전에 데이터를 복제하고, 사용자와 가장 가까운 리전으로 라우팅하는 패턴입니다.

![글로벌 데이터 복제 공유 아키텍처 — 서울 원본 버킷을 CRR로 도쿄/버지니아에 복제하고 Multi-Region Access Point가 가장 가까운 리전으로 자동 라우팅](/assets/images/posts/s3-architecture-patterns/12-07-5-패턴-5-글로벌-데이터-복제-공유.svg)

### 어떻게 구성되나

원본 버킷(예: 서울)에서 CRR 규칙으로 도쿄·버지니아 버킷에 복제본을 만듭니다. 그 위에 Multi-Region Access Point를 올리면, 소비자는 **단일 글로벌 ARN**으로 접근하고 지연 시간이 가장 낮은 리전이 자동 선택됩니다.

**핵심 포인트**: 글로벌 저지연 접근과 재해 복구가 동시에 해결됩니다. 단, 스토리지 비용이 2~3배로 늘고 복제 지연(초 단위)이 발생합니다.

- **장점**: 글로벌 저지연 접근, 재해 복구 내장, 지역별 규제 준수, 자동 장애 조치
- **단점**: 복제 스토리지 비용(2~3배), 복제 지연, 데이터 일관성 관리 복잡
- **적합 시나리오**: 글로벌 서비스, CDN 원본, 다국가 데이터 공유, 재해 복구

---

## 패턴 6: 이벤트 기반 공유

S3 이벤트를 **EventBridge로 라우팅**하여, 데이터가 변경될 때마다 자동으로 알림·처리하는 패턴입니다.

![이벤트 기반 데이터 공유 아키텍처 — S3 객체 생성/삭제 이벤트가 EventBridge 규칙으로 분기되어 Lambda/Step Functions/SNS로 자동 처리](/assets/images/posts/s3-architecture-patterns/12-08-6-패턴-6-s3-eventbridge-이벤트-기반-공유.svg)

### 어떻게 구성되나

S3 버킷의 이벤트 알림을 EventBridge로 보내면, 규칙(Rule)이 이벤트를 분류하여 Lambda, Step Functions, SNS 등으로 전달합니다. 신규 데이터 → Lambda 검증, 수정 → Step Functions ETL, 삭제 → SNS 알림 식으로 목적별 라우팅이 가능합니다.

**핵심 포인트**: 느슨한 결합(loose coupling)으로 실시간 파이프라인을 구성합니다. 데이터 제공자는 버킷에 올리기만 하면 되고, 소비자는 이벤트를 구독만 하면 됩니다.

<details>
<summary><b>📖 EventBridge Rule + Lambda 타겟 예시 보기</b></summary>

```python
import boto3, json

events = boto3.client('events')

# 신규 데이터 이벤트 규칙 생성
events.put_rule(
    Name='s3-new-data-available',
    EventPattern=json.dumps({
        "source": ["aws.s3"],
        "detail-type": ["Object Created"],
        "detail": {
            "bucket": {"name": ["shared-data-bucket"]},
            "object": {"key": [{"prefix": "shared/"}]}
        }
    })
)

# Lambda 함수를 타겟으로 등록
events.put_targets(
    Rule='s3-new-data-available',
    Targets=[{
        'Id': 'NotifyConsumers',
        'Arn': 'arn:aws:lambda:ap-northeast-2:123456789012:function:notify-consumers',
        'InputTransformer': {
            'InputPathsMap': {
                'bucket': '$.detail.bucket.name',
                'key': '$.detail.object.key',
                'size': '$.detail.object.size'
            },
            'InputTemplate': '{"bucket":"<bucket>","key":"<key>","size":"<size>"}'
        }
    }]
)
```

</details>

### 장점 · 단점 · 적합 시나리오

- **장점**: 실시간 반응, 느슨한 결합, 자동 확장, 마이크로서비스와 자연스러운 통합
- **단점**: 이벤트 순서 보장 복잡, 디버깅 어려움, 이벤트 스토리지 추가 비용
- **적합 시나리오**: 실시간 데이터 파이프라인, CDC(변경 데이터 캡처), 자동화된 ETL, 협업 워크플로우

---

## 패턴 비교 및 선택 가이드

6가지 패턴을 복잡도, 보안, 비용, 지연, 확장성 기준으로 비교한 매트릭스입니다.

![아키텍처 패턴 비교 매트릭스 — 6개 패턴을 복잡도/데이터 위치/보안/비용/지연/확장성/권장 대상 기준으로 비교](/assets/images/posts/s3-architecture-patterns/12-09-7-패턴-비교-총정리.svg)

### 의사결정 트리

![아키텍처 패턴 선택 의사결정 트리 — 상업적/글로벌/데이터 이동/실시간/멀티 팀 여부에 따라 패턴을 추천](/assets/images/posts/s3-architecture-patterns/12-10-패턴-선택-의사결정-트리.svg)

의사결정 흐름은 이렇습니다:

1. **데이터를 판매하나?** → Yes: **패턴 4** (마켓플레이스)
2. **글로벌 서비스인가?** → Yes: **패턴 5** (글로벌 복제)
3. **데이터 이동이 불가한가?** → Yes: **패턴 3** (연합 분석)
4. **실시간 처리가 필요한가?** → Yes: **패턴 6** (이벤트 기반)
5. **멀티 팀/부서인가?** → Yes: **패턴 2** (멀티 계정 허브) / No: **패턴 1** (데이터 레이크 공유)

### 상황별 추천 패턴

| 조직 규모 | 데이터 민감도 | 글로벌 필요성 | 추천 패턴 |
|-----------|---------------|---------------|-----------|
| 소규모 팀 | 낮음~중간 | 없음 | **패턴 1** 데이터 레이크 공유 |
| 중대형 기업 | 높음 | 없음 | **패턴 2** 멀티 계정 허브 |
| 규제 산업 | 매우 높음 | 국내 한정 | **패턴 3** 연합 분석 |
| 데이터 비즈니스 | 중간 | 있음 | **패턴 4** 마켓플레이스 |
| 글로벌 서비스 | 높음 | 필수 | **패턴 5** 글로벌 복제 |
| 실시간 파이프라인 | 중간 | 있음 | **패턴 6** 이벤트 기반 |

> 패턴은 단독으로만 쓰이지 않습니다. 패턴 2(멀티 계정 허브)를 기본으로 두고, 그 위에 패턴 6(이벤트)을 얹고, 외부 데이터는 패턴 4로 가져오는 조합이 흔합니다.

---

## Takeaway

1. **소규모는 데이터 레이크 공유(패턴 1), 대규모는 멀티 계정 허브(패턴 2)** — 조직 규모에 따라 기본 패턴을 선택합니다
2. **데이터 이동이 불가하면 연합 분석(패턴 3)** — 복사 없이 쿼리만 수행하여 데이터 주권을 보존합니다
3. **이벤트 기반 공유(패턴 6)는 실시간 파이프라인의 핵심** — EventBridge로 모든 트리거를 연결하여 느슨한 결합을 만듭니다
