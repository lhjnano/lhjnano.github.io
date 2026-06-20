---
layout: post
title: "[S3 4/7] S3 보안 다층 방어 — 7계층 패턴과 실전 구현"
categories: [AWS, Security]
description: S3 데이터 보안을 위한 7계층 방어 모델을 정리합니다. 최소 권한 원칙, 버킷 정책 패턴, Block Public Access, 암호화, 감사/모니터링까지 실전 코드와 함께 소개합니다.
keywords: [S3, Security, CORS, IAM, 암호화, CloudTrail, KMS]
toc: true
toc_sticky: true
---

## Hook

S3 버킷 하나를 공개하면 하루 만에 수천 건의 무단 접근 시도가 시작됩니다. 보안은 단일 계층이 아니라 다층 방어로 설계해야 합니다.

한 계층이 뚫려도 다음 계층이 막아주는 구조가 되어야 합니다. 이 글에서는 S3 데이터 보안을 위한 7계층 방어 모델과 함께, 최소 권한 원칙, 버킷 정책 6가지 패턴, Block Public Access, SSE-KMS 암호화, CloudTrail 감사까지 실전 코드로 정리합니다.

---

## TL;DR

- **7계층 방어 모델** — 네트워크 → 액세스 → 권한 → 암호화 → 모니터링
- **최소 권한이 핵심** — 읽기 전용이면 읽기 전용만, 필요한 경로만
- **Block Public Access는 기본** — 실수로 공개되는 것을 원천 차단
- **암호화는 SSE-KMS 기본** — 키 제어권을 갖는 암호화
- **CloudTrail + Macie로 감사** — 누가 언제 무엇을 했는지 추적

---

## S3 보안 7계층 모델

S3 보안은 여러 레이어로 구성된 방어 심도(Defense in Depth) 모델로 설계합니다. 하나의 계층에 의존하면 단일 장애점이 됩니다.

![S3 보안 7계층 Defense in Depth 모델](/assets/images/posts/s3-security-patterns/11-01-1-s3-보안-모델-개요.svg)

7개 계층은 각각 독립적으로 작동하면서 상호 보완합니다.

| 계층 | 역할 | 핵심 서비스 |
|------|------|------------|
| Layer 1: IAM 인증 | 사용자/역할 기반 인증 기반 | IAM, STS, MFA |
| Layer 2: Block Public Access | 공개 접근 원천 차단 | S3 BPA |
| Layer 3: 네트워크 보안 | VPC/TLS/IP 제한 | VPC Endpoint, TLS |
| Layer 4: 버킷 정책 & ACL | 세밀한 접근 제어 | Bucket Policy, IAM 정책 |
| Layer 5: 공유 메커니즘 보안 | Pre-signed URL, Access Point | 만료 시간, AP 정책 |
| Layer 6: 데이터 보호 | 암호화, 버전관리, WORM | SSE-S3/KMS, Versioning |
| Layer 7: 모니터링 & 감사 | 추적 및 탐지 | CloudTrail, Macie, Config |

### 보안 결정 흐름

S3에 들어온 모든 요청은 정해진 순서로 평가됩니다. 이 흐름을 이해하면 정책이 왜 허용/거부되는지 알 수 있습니다.

![S3 보안 결정 흐름 — 요청부터 허용/거부까지](/assets/images/posts/s3-security-patterns/11-02-1-s3-보안-모델-개요.svg)

핵심 원칙은 **명시적 Deny > Block Public Access > 명시적 Allow > 기본 거부**입니다. 기본적으로 모든 S3 접근은 암시적으로 거부되며, 명시적 Allow가 있어야만 허용됩니다.

---

## 최소 권한 원칙

데이터 공유 시 필요한 최소한의 권한만 부여하는 것이 핵심입니다. "읽기만 주면 되는데 `s3:*`를 주는" 실수가 가장 흔한 보안 사고의 원인입니다.

![최소 권한 원칙 — 공유 시나리오별 권한 매트릭스](/assets/images/posts/s3-security-patterns/11-03-2-공유를-위한-최소-권한-원칙.svg)

### 공유 시나리오별 권한 매트릭스

| 시나리오 | 필요 권한 | 권장 방식 |
|----------|----------|----------|
| 읽기 전용 공유 | `s3:GetObject`, `s3:ListBucket` (특정 Prefix) | IAM 정책 + Prefix 제한 |
| 특정 파일 공유 (Pre-signed) | `s3:GetObject` (지정된 Key만) | Pre-signed URL + 시간 제한 |
| 분석용 공유 (Access Point) | `s3:GetObject`, `s3:ListBucket`, `s3:GetObjectAcl` | Access Point 정책 |
| 쓰기 포함 공유 (양방향) | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` | 지정된 Prefix만 |
| 구독 데이터 (Data Exchange) | `s3:GetObject`, `athena:StartQueryExecution`, `glue:Get*` | 구독한 데이터셋만 |

<details>
<summary>최소 권한 IAM 정책 예시 (읽기 전용 공유) — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListSpecificPrefix",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::shared-data-bucket",
            "Condition": {
                "StringLike": {
                    "s3:prefix": ["analytics/public/*"]
                }
            }
        },
        {
            "Sid": "ReadSpecificPrefix",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::shared-data-bucket/analytics/public/*"
        }
    ]
}
```

</details>

이 정책은 `analytics/public/` 경로 아래만 조회할 수 있으며, 다른 경로는 존재 자체를 알 수 없습니다.

---

## 버킷 정책 6가지 패턴

버킷 정책은 조건(Condition) 키를 조합해 세밀한 접근 제어를 구현합니다. 6가지 패턴을 상황에 맞게 선택하거나 조합합니다.

![버킷 정책 6가지 패턴 분류](/assets/images/posts/s3-security-patterns/11-04-3-버킷정책-패턴.svg)

### 패턴 1: 계정 기반 허용

특정 AWS 계정에만 읽기 권한을 부여합니다. `aws:PrincipalAccount` 조건 키로 계정을 식별합니다.

- **언제 쓰나** — 파트너사 계정, 자회사 계정과 데이터를 공유할 때
- **주의점** — 상대 계정의 IAM 정책도 별도로 허용해야 실제 접근 가능

<details>
<summary>패턴 1: 계정 기반 읽기 허용 정책 — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowSpecificAccountRead",
            "Effect": "Allow",
            "Principal": { "AWS": "arn:aws:iam::999999999999:root" },
            "Action": ["s3:GetObject", "s3:GetObjectVersion"],
            "Resource": "arn:aws:s3:::shared-data-bucket/*",
            "Condition": {
                "StringEquals": { "aws:PrincipalAccount": "999999999999" }
            }
        },
        {
            "Sid": "AllowSpecificAccountList",
            "Effect": "Allow",
            "Principal": { "AWS": "arn:aws:iam::999999999999:root" },
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::shared-data-bucket",
            "Condition": {
                "StringLike": { "s3:prefix": "shared/*" }
            }
        }
    ]
}
```

</details>

### 패턴 2: VPC 엔드포인트만 허용

특정 VPC에서만 접근을 허용합니다. `aws:SourceVpce` 조건 키로 특정 VPC 엔드포인트를 통한 요청만 허용합니다.

![VPC 엔드포인트 기반 접근 제어 구조](/assets/images/posts/s3-security-patterns/11-05-32-패턴-2-특정-vpc에서만-접근-허용.svg)

- **언제 쓰나** — 사내 네트워크나 특정 VPC 내 EC2/ECS만 접근해야 할 때
- **주의점** — Deny 문에 `aws:ViaAWSService: false`를 추가해 AWS 서비스(복제, Lambda 등)는 예외 처리해야 합니다

<details>
<summary>패턴 2: VPC 엔드포인트만 허용 + 외부 Deny — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowVPCAccessOnly",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject", "s3:GetObjectVersion"],
            "Resource": "arn:aws:s3:::shared-data-bucket/*",
            "Condition": {
                "StringEquals": { "aws:SourceVpce": "vpce-1a2b3c4d5e6f7g8h9" }
            }
        },
        {
            "Sid": "DenyNonVPCAccess",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": [
                "arn:aws:s3:::shared-data-bucket",
                "arn:aws:s3:::shared-data-bucket/*"
            ],
            "Condition": {
                "StringNotEquals": { "aws:SourceVpce": "vpce-1a2b3c4d5e6f7g8h9" },
                "Bool": { "aws:ViaAWSService": "false" }
            }
        }
    ]
}
```

</details>

### 패턴 3: IP 기반 허용

특정 IP 범위에서만 접근을 허용합니다. `aws:SourceIp`와 `NotIpAddress`를 조합해 허용 IP 외 요청을 명시적으로 차단합니다.

- **언제 쓰나** — 사무실 고정 IP, VPN 대역만 허용할 때
- **주의점** — VPC 엔드포인트를 통한 내부 트래픽은 공인 IP가 없으므로 패턴 2와 병행 필요

<details>
<summary>패턴 3: IP 기반 접근 제한 정책 — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowOfficeIPOnly",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::shared-data-bucket",
                "arn:aws:s3:::shared-data-bucket/*"
            ],
            "Condition": {
                "IpAddress": {
                    "aws:SourceIp": ["203.0.113.0/24", "198.51.100.0/24"]
                }
            }
        },
        {
            "Sid": "DenyAllOtherIPs",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": [
                "arn:aws:s3:::shared-data-bucket",
                "arn:aws:s3:::shared-data-bucket/*"
            ],
            "Condition": {
                "NotIpAddress": {
                    "aws:SourceIp": ["203.0.113.0/24", "198.51.100.0/24"]
                },
                "Bool": { "aws:ViaAWSService": "false" }
            }
        }
    ]
}
```

</details>

### 패턴 4: 시간 기반 허용

업무 시간에만 접근을 허용합니다. `aws:CurrentTime`과 `DateGreaterThan`/`DateLessThan`으로 시간 범위를 지정합니다.

- **언제 쓰나** — 야간/주말 자동화 작업을 차단하거나, 임시 접근 기간을 설정할 때
- **주의점** — KST가 아닌 UTC 기준이므로 변환 필요 (KST 09:00-18:00 = UTC 00:00-09:00)

<details>
<summary>패턴 4: 시간 기반 접근 제한 정책 — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowBusinessHoursOnly",
            "Effect": "Allow",
            "Principal": { "AWS": "arn:aws:iam::999999999999:root" },
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::shared-data-bucket",
                "arn:aws:s3:::shared-data-bucket/*"
            ],
            "Condition": {
                "DateGreaterThan": { "aws:CurrentTime": "2026-01-01T00:00:00Z" },
                "DateLessThan": { "aws:CurrentTime": "2026-12-31T23:59:59Z" }
            }
        }
    ]
}
```

</details>

### 패턴 5: 태그 기반 허용

리소스 태그나 보안 주체 태그로 접근을 제어합니다. ABAC(Attribute-Based Access Control) 방식으로, 환경(`env=prod`)이나 부서(`team=data`) 태그로 분류합니다.

- **언제 쓰나** — 개발/운영 환경 분리, 부서별 데이터 접근 제어
- **장점** — 새 리소스 추가 시 정책 변경 없이 태그만 부여하면 됨

### 패턴 6: 복합 조건

위 패턴들을 `AND`로 조합합니다. 예를 들어 "특정 역할 + 특정 VPC + TLS 전송"을 모두 만족해야 허용합니다.

<details>
<summary>패턴 6: 복합 조건 (역할 + VPC + TLS + Prefix) — 전체 보기</summary>

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CompoundConditionAccess",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::999999999999:role/DataAnalystRole"
            },
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::shared-data-bucket",
                "arn:aws:s3:::shared-data-bucket/analytics/*"
            ],
            "Condition": {
                "Bool": { "aws:SecureTransport": "true" },
                "StringEquals": { "aws:SourceVpce": "vpce-1a2b3c4d5e6f7g8h9" },
                "StringLike": { "s3:prefix": "analytics/*" },
                "NumericLessThan": { "s3:max-keys": "1000" }
            }
        }
    ]
}
```

</details>

---

## Block Public Access

S3 Block Public Access는 의도치 않은 공개 접근을 방지하는 계정/버킷 수준의 안전망입니다. 실수로 공개 ACL이나 정책을 설정해도 접근을 원천 차단합니다.

![Block Public Access 설정 계층](/assets/images/posts/s3-security-patterns/11-06-4-s3-block-public-access-설정.svg)

### 4가지 설정 항목

| 설정 | 역할 |
|------|------|
| `BlockPublicAcls` | ACL을 통한 공개 접근 차단 |
| `IgnorePublicAcls` | 기존 공개 ACL 무시 |
| `BlockPublicPolicy` | 공개 버킷 정책 적용 차단 |
| `RestrictPublicBuckets` | 공개 정책이 있는 버킷 제한 |

### 적용 계층

Block Public Access는 4개 수준에서 적용할 수 있으며, **상위 수준이 하위 수준보다 우선**합니다.

| 수준 | 범위 | 권장 |
|------|------|------|
| **Account** | 계정 내 모든 버킷 | 무조건 켜기 |
| **Bucket** | 개별 버킷 | 기본값 유지 |
| **Organization** | 조직 전체 (SCP) | 조직 규칙으로 강제 |
| **Region** | 리전별 | 리전 격리 시 활용 |

```bash
# 계정 수준 Block Public Access 활성화
aws s3control put-public-access-block \
    --account-id 123456789012 \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,\
BlockPublicPolicy=true,RestrictPublicBuckets=true
```

> **원칙**: 계정 수준에서 4가지 설정 모두 활성화 → 공개 데이터셋이 필요한 경우에만 버킷 수준에서 선택적 해제. 공개 버킷은 전용 계정에서 격리 운영하는 것이 안전합니다.

---

## 암호화와 공유

S3 암호화 방식에 따라 데이터 공유 방법이 달라집니다. 어떤 암호화를 썼느냐에 따라 소비자가 추가 권한이 필요할 수 있습니다.

![S3 암호화 방식 비교와 공유 영향](/assets/images/posts/s3-security-patterns/11-07-5-암호화와-공유.svg)

### 암호화 방식 비교

| 방식 | 키 관리 | 공유 영향 | 권장 용도 |
|------|---------|----------|----------|
| **SSE-S3** | AWS 완전 관리 | 없음 (소비자 추가 권한 불필요) | 공유 데이터 기본 암호화 |
| **SSE-KMS** | 고객 관리 CMK | 소비자 KMS 권한 필요 ⚠️ | 민감 데이터 공유 |
| **SSE-C** | 고객 제공 키 | 키를 소비자에게 별도 전달 | 최고 수준 제어 필요 시 |
| **CSE** | 클라이언트 | 복호화 키 별도 채널 공유 | 엄격한 규제 요건 |

### SSE-KMS 공유 흐름

SSE-KMS로 암호화된 데이터를 타 계정과 공유하려면, KMS 키 정책에 소비자 계정을 명시적으로 허용해야 합니다. 소비자 측 IAM 정책에도 KMS 사용 권한이 필요합니다.

![SSE-KMS 공유 흐름 — 5단계](/assets/images/posts/s3-security-patterns/11-08-51-sse-kms로-암호화된-데이터-공유하기.svg)

공유 흐름은 5단계로 진행됩니다.

1. **제공자 → KMS**: 키 정책에 소비자 계정 추가
2. **소비자 IAM**: `kms:Decrypt` 권한 추가
3. **소비자 → S3**: `GetObject` 요청
4. **S3 → KMS**: 데이터 키 복호화
5. **S3 → 소비자**: 복호화된 데이터 반환

<details>
<summary>KMS 키 정책: 소비자 계정 복호화 허용 — 전체 보기</summary>

```json
{
    "Sid": "AllowConsumerAccountToDecrypt",
    "Effect": "Allow",
    "Principal": {
        "AWS": "arn:aws:iam::999999999999:root"
    },
    "Action": [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey"
    ],
    "Resource": "*"
}
```

소비자 IAM 정책에는 `kms:Decrypt`와 `s3:GetObject`를 함께 부여해야 합니다. KMS 권한이 없으면 객체를 받아도 복호화하지 못해 AccessDenied가 발생합니다.

</details>

---

## 감사 및 모니터링

데이터 공유 환경에서 접근 감사와 모니터링은 필수입니다. 누가 언제 무엇에 접근했는지 추적할 수 있어야 사고 발생 시 대응할 수 있습니다.

![S3 감사 및 모니터링 아키텍처](/assets/images/posts/s3-security-patterns/11-09-6-감사-및-모니터링.svg)

### 3종 감사 도구

| 도구 | 추적 대상 | 특징 |
|------|----------|------|
| **CloudTrail** | 모든 S3 API 이벤트 | 데이터 이벤트(GetObject 등) + 관리 이벤트(CreateBucket 등) |
| **S3 Access Logs** | 모든 요청 상세 로그 | 요청자 IP, 시간, 응답 코드, 바이트 수 |
| **Amazon Macie** | 민감 데이터 자동 탐지 | PII, PHI 식별, 공유 전/후 노출 방지 |

추가로 **AWS Config**로 버킷 설정 변경 추적과 암호화/공개 설정 규칙 준수 여부를 모니터링합니다.

### Athena로 access log 쿼리하기

CloudTrail 로그는 Athena로 직접 쿼리해 의심스러운 접근을 탐지할 수 있습니다. 아래 쿼리는 외부 계정의 GetObject/ListBucket 접근을 시간순으로 조회합니다.

<details>
<summary>Athena로 CloudTrail 로그 쿼리 (외부 계정 접근 탐지) — 전체 보기</summary>

```sql
SELECT
    eventtime,
    useridentity.arn AS requester,
    eventname,
    requestparameters,
    sourceipaddress,
    awsregion
FROM cloudtrail_logs
WHERE eventsource = 's3.amazonaws.com'
  AND (
    eventname = 'GetObject'
    OR eventname = 'ListBucket'
  )
  AND useridentity.accountid != '123456789012'
  AND eventtime >= '2026-06-01T00:00:00Z'
ORDER BY eventtime DESC;
```

</details>

이 쿼리를 정기 실행하도록 예약하고, 결과를 알림(SNS/Slack)으로 연동하면 비인가 접근을 실시간으로 감지할 수 있습니다.

---

## 보안 체크리스트

![S3 보안 모범 사례 체크리스트 10가지](/assets/images/posts/s3-security-patterns/11-10-7-보안-모범-사례-체크리스트.svg)

| # | 항목 | 확인 방법 | 위험도 |
|---|------|-----------|--------|
| 1 | Block Public Access | `s3-bucket-level-public-access-prohibited` Config 규칙 | 🔴 High |
| 2 | 최소 권한 원칙 | IAM Access Analyzer 검토 | 🔴 High |
| 3 | 암호화 적용 | `aws s3api get-bucket-encryption` | 🟠 Medium |
| 4 | 버전 관리 활성화 | `aws s3api get-bucket-versioning` | 🟡 Low |
| 5 | MFA Delete | 버킷 버전 관리 설정 확인 | 🟠 Medium |
| 6 | Access Point 활용 | Access Point 정책 검토 | 🟡 Low |
| 7 | Pre-signed URL 만료 시간 | URL 생성 코드 리뷰 (1시간 이내) | 🟠 Medium |
| 8 | CloudTrail 데이터 이벤트 | CloudTrail 이벤트 기록 확인 | 🔴 High |
| 9 | 정기 보안 평가 | Macie 발견 결과 + Config Rules | 🟠 Medium |
| 10 | IAM 역할 분리 | 관리/소비/감사 역할 분리 | 🔴 High |

---

## Takeaway

1. **보안은 하나의 계층으로 충분하지 않다** — 7계층 다층 방어가 기본입니다. 한 계층이 뚫려도 다음 계층이 막아주도록 설계해야 합니다
2. **Block Public Access는 무조건 켜세요** — 계정 수준에서 4가지 설정 모두 활성화하면 실수로 인한 유출을 원천 차단합니다
3. **SSE-KMS + CloudTrail + Macie 3종 세트** — 암호화, 감사, 민감 정보 탐지를 한 번에 갖추면 사고 예방과 추적이 모두 가능합니다

---

> **S3 시리즈 4/7**
>
> | | |
> |---|---|
> | ← [S3 Access Grants와 복제로 대규모 데이터 공유하기]({% post_url 2026-05-17-S3-Access-Grants-and-Replication %}) | |
> | | [S3 데이터 공유 아키텍처 — 6가지 패턴과 선택 가이드]({% post_url 2026-05-19-S3-Data-Sharing-Architecture-Patterns %}) → |
