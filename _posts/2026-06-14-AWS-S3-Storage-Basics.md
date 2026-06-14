---
layout: post
title: "[AWS 3/16] S3 객체 스토리지 기초 — 버킷부터 수명주기까지"
categories: [AWS, Storage]
description: S3의 기본 개념부터 스토리지 클래스, 버전 관리, 수명주기 규칙, 암호화, 복제, 성능 최적화까지 기초를 정리합니다.
keywords: [S3, AWS, 스토리지, 버킷, 수명주기, 암호화]
toc: true
toc_sticky: true
---

## Hook

S3는 "무제한으로 저장하고, 언제 어디서나 가져오는" 객체 스토리지입니다. 99.999999999%(11개의 9) 내구성, REST API 기반 접근, TB 단위 파일까지 한 번에 처리합니다. 하지만 버킷 이름 하나 잘못 짓거나 암호화를 켜지 않으면 하루 만에 문제가 시작됩니다.

이 글에서는 S3의 기초를 처음부터 끝까지 정리합니다. 버킷과 객체의 구조, 7가지 스토리지 클래스, 보안/암호화 기본, 버전 관리, Lifecycle 규칙, 복제, 이벤트 알림, 성능 최적화까지 한 흐름으로 살펴봅니다.

---

## TL;DR

- **객체 스토리지의 기본 단위는 Key-Value** — 버킷은 전역 유일 컨테이너, 객체는 Key(경로) + Value(데이터) + 메타데이터
- **스토리지 클래스로 비용을 최적화합니다** — 자주 쓰면 Standard, 가끔 쓰면 IA, 거의 안 쓰면 Glacier
- **보안은 다층 구조** — IAM → 버킷 정책 → Block Public Access → 암호화 순으로 쌓습니다
- **Lifecycle 규칙으로 자동화합니다** — 30일 후 IA, 90일 후 Glacier, 1년 후 Deep Archive로 자동 전환
- **버전 관리 + 복제로 데이터를 보호합니다** — 실수 삭제 복구와 재해 복구를 동시에 커버

---

## 1. S3 개요와 핵심 개념

### Amazon S3란?

Amazon S3는 HTTP 인터페이스를 통해 언제 어디서나 데이터를 저장하고 검색하는 객체 스토리지 서비스입니다. S3 자체는 글로벌 서비스이지만, 버킷은 특정 리전에 생성됩니다.

![S3 개요 — 글로벌 서비스와 리전 기반 버킷](/assets/images/posts/aws-s3-storage/03-01-amazon-simple-storage-service-s3.svg)

핵심 특징은 4가지입니다.

- **글로벌 서비스**: S3는 글로벌이지만, 데이터는 버킷이 생성된 리전에 저장됩니다
- **객체 스토리지**: 파일 시스템이 아닌 평면적(Flat) 주소 공간을 사용합니다
- **HTTP 인터페이스**: RESTful API(GET, PUT, DELETE)로 접근합니다
- **무제한 저장**: 객체 수와 총 용량에 제한이 없습니다
- **강력한 일관성**: 2020년 이후 모든 S3 작업에 Strong Read-after-write Consistency가 적용됩니다

### 버킷 (Bucket)

버킷은 객체를 저장하는 기본 컨테이너입니다. 버킷 이름은 모든 AWS 계정, 모든 리전에서 유일해야 합니다.

![버킷 명명 규칙 — 적합한 이름과 제약사항](/assets/images/posts/aws-s3-storage/03-02-2-버킷-bucket.svg)

버킷 이름 규칙은 다음과 같습니다.

| 항목 | 규칙 |
|------|------|
| 길이 | 3~63자 |
| 문자 | 소문자, 숫자, 하이픈(-) |
| 제약 | 하이픈으로 시작/끝 불가, IP 주소 형식 불가 |
| 접두사 | `xn--` 접두사 불가 (Punycode) |
| 계정당 한도 | 기본 100개, 최대 1,000개까지 증가 요청 가능 |

### 객체 (Object)

객체는 S3에 저장되는 기본 단위로, 데이터와 메타데이터로 구성됩니다.

![S3 Object 구조 — Key, Value, Version ID, Metadata, Tags](/assets/images/posts/aws-s3-storage/03-03-3-객체-object.svg)

객체는 5가지 요소로 구성됩니다.

| 요소 | 설명 |
|------|------|
| **Key** | 버킷 내 객체의 전체 경로 (최대 1,024바이트). 예: `photos/2026/beach.jpg` |
| **Value** | 실제 데이터 (1바이트 ~ 5TB) |
| **Version ID** | 버전 관리 활성화 시 자동 생성되는 고유 식별자 |
| **Metadata** | 시스템 메타데이터(크기, 수정일시) + 사용자 정의(`x-amz-meta-*`) |
| **Tags** | 키-값 페어, 비용 추적 및 관리에 활용 |

**멀티파트 업로드**는 대용량 파일을 여러 파트로 나누어 업로드하는 기능입니다. 100MB 이상 파일에 권장하며, 5GB 초과 파일은 필수입니다. 파트 크기는 5MB~5GB, 최대 10,000개 파트까지 가능합니다. 실패한 파트만 재전송할 수 있어 네트워크 장애에 강합니다.

---

## 2. 스토리지 클래스 — 용도별 선택

S3는 데이터 액세스 패턴과 비용 요구사항에 따라 7가지 스토리지 클래스를 제공합니다.

![S3 스토리지 클래스 비교표 (2026)](/assets/images/posts/aws-s3-storage/03-04-4-스토리지-클래스-2026-업데이트.svg)

### 클래스 요약

| 클래스 | 액세스 빈도 | 검색 시간 | 최소 기간 | 용도 |
|--------|-----------|----------|----------|------|
| **Standard** ⭐ | 빈번함 | 즉시 (ms) | 없음 | 활성 데이터, 웹사이트 콘텐츠 |
| **Standard-IA** | 간헐적 (30일+) | 즉시 (ms) | 30일 | 백업, 재해 복구 |
| **One Zone-IA** | 간헐적 (30일+) | 즉시 (ms) | 30일 | 2차 백업, 재생성 가능 데이터 |
| **Intelligent-Tiering** | 자동 티어링 | 즉시 (ms) | 없음 | 액세스 패턴이 불확실한 데이터 |
| **Express One Zone** 🆕 | 빈번함 (고성능) | 즉시 (ms) | 없음 | AI/ML 데이터셋, 고성능 앱 |
| **Glacier Instant** | 드묾 | 밀리초 | 90일 | 빠른 검색이 필요한 아카이브 |
| **Glacier Flexible** | 드묾 | 3~5시간 | 90일 | 장기 아카이브 |
| **Glacier Deep Archive** | 극히 드묾 | 12~48시간 | 180일 | 극장기 아카이브 |

비용은 Standard > Standard-IA > One Zone-IA > Glacier Instant > Glacier Flexible > Deep Archive 순으로 저렴해집니다.

### Intelligent-Tiering 자동 티어링

액세스 패턴을 예측하기 어려울 때는 Intelligent-Tiering을 사용합니다. 액세스 빈도에 따라 자동으로 티어 간 이동하며, 검색 요금이 없습니다.

![Intelligent-Tiering 자동 티어링 흐름](/assets/images/posts/aws-s3-storage/03-05-s3-intelligent-tiering.svg)

객체가 30일 연속 미접근 시 Infrequent Access로, 90일 시 Archive Access로, 180일 시 Deep Archive Access로 자동 이동합니다. 다시 액세스가 발생하면 자동으로 Frequent Access 티어로 복귀합니다.

---

## 3. 보안 기초와 암호화

S3 보안은 여러 레이어로 구성된 다층 방어 모델로 설계합니다.

![S3 보안 레이어 — 6계층 구조](/assets/images/posts/aws-s3-storage/03-06-5-s3-보안.svg)

6개 보안 레이어는 다음과 같습니다.

1. **IAM 정책** — 사용자/역할 단위 접근 제어
2. **버킷 정책 (Bucket Policy)** — 버킷 단위 접근 제어, JSON 기반
3. **ACL** — 객체/버킷 단위 (⚠️ 권장하지 않음)
4. **S3 Object Ownership** — 버킷 소유자 강제 설정 (권장)
5. **암호화 (Encryption)** — 전송 중 암호화 + 저장 데이터 암호화
6. **S3 Object Lambda** — 데이터 처리 파이프라인

### 버킷 정책 (Bucket Policy)

버킷 정책은 JSON 기반으로 버킷과 객체에 대한 접근을 세밀하게 제어합니다. 다른 AWS 계정이나 퍼블릭 액세스를 제어할 때 사용합니다.

![버킷 정책 예시 — 주요 요소 구성](/assets/images/posts/aws-s3-storage/03-07-버킷-정책-bucket-policy.svg)

버킷 정책의 핵심 요소는 4가지입니다.

| 요소 | 설명 |
|------|------|
| **Principal** | 권한을 부여할 대상 (사용자, 계정, `*`) |
| **Effect** | `Allow` 또는 `Deny` |
| **Action** | 허용/거부할 작업 (`s3:GetObject`, `s3:PutObject` 등) |
| **Resource** | 대상 버킷/객체 ARN |

**ACL은 권장하지 않습니다.** 대신 버킷 정책과 IAM 정책을 사용하고, S3 Object Ownership을 "버킷 소유자 강제"로 설정해 ACL을 비활성화합니다.

**S3 퍼블릭 액세스 차단**은 계정 및 버킷 수준에서 4가지 설정을 개별 제어합니다: 새 ACL 차단, 기존 ACL 차단, 새 버킷 정책 차단, 기존 버킷 정책 차단. 기본적으로 모두 활성화하는 것이 안전합니다.

### 암호화

S3 암호화는 전송 중 암호화와 저장 데이터 암호화로 나뉩니다.

![S3 암호화 방식 — SSE-S3, SSE-KMS, SSE-C, 클라이언트 측](/assets/images/posts/aws-s3-storage/03-10-8-s3-암호화.svg)

서버 측 암호화(SSE) 3가지 방식을 비교합니다.

| 방식 | 키 관리 | 특징 | 용도 |
|------|---------|------|------|
| **SSE-S3** ⭐ | AWS 완전 관리 | AES-256, 추가 비용 없음, 2026년 기본값 | 일반 데이터 |
| **SSE-KMS** | AWS KMS 고객 관리 키 | CloudTrail 감사 추적, Envelope Encryption | 규정 준수, 감사 필요 |
| **SSE-C** | 고객 제공 키 | AWS는 키 미저장, 키 분실 시 복구 불가 | 최고 수준 제어 |

**클라이언트 측 암호화**는 데이터를 S3에 업로드하기 전에 클라이언트에서 직접 암호화합니다. AWS Encryption SDK 또는 S3 Encryption Client를 사용합니다.

**전송 중 암호화**는 HTTPS(TLS)를 사용하며, 버킷 정책으로 `aws:SecureTransport` 조건을 통해 HTTP 요청을 거부할 수 있습니다.

---

## 4. 버전 관리와 수명주기

### 버전 관리 (Versioning)

버전 관리를 활성화하면 객체의 모든 버전이 보존되어 실수로 삭제하거나 덮어쓴 데이터를 복구할 수 있습니다.

![S3 버전 관리 동작 — 업로드와 삭제 마커](/assets/images/posts/aws-s3-storage/03-08-6-버전-관리-versioning.svg)

버전 관리의 핵심 동작은 다음과 같습니다.

- 같은 Key로 업로드하면 새 Version ID가 생성되고, 이전 버전은 보존됩니다
- GET 요청은 항상 최신 버전을 반환합니다
- **삭제 마커(Delete Marker)**: 삭제 시 실제 삭제가 아니라 삭제 마커가 추가되며, GET 시 404를 반환합니다
- 삭제 마커를 제거하면 이전 버전으로 복원할 수 있습니다
- 한 번 활성화하면 완전히 비활성화할 수 없고 일시 중지(MFA Delete 포함)만 가능합니다
- 모든 버전이 저장되므로 스토리지 비용이 증가합니다

### 수명 주기 관리 (Lifecycle)

S3 Lifecycle을 사용하면 객체의 수명 주기에 따라 자동으로 스토리지 클래스를 전환하거나 만료시킬 수 있습니다.

![Lifecycle 규칙 적용 예시 — 전환과 만료](/assets/images/posts/aws-s3-storage/03-09-7-수명-주기-관리-lifecycle.svg)

Lifecycle 규칙은 3가지 유형이 있습니다.

| 규칙 유형 | 설명 |
|----------|------|
| **전환 (Transition)** | 지정한 일수 이후 객체를 다른 스토리지 클래스로 자동 이동 |
| **만료 (Expiration)** | 지정한 일수 이후 객체를 자동 삭제 |
| **미완료 멀티파트 정리** | 완료되지 않은 업로드 자동 정리 |

전환 흐름의 대표적인 패턴은 다음과 같습니다.

```
Standard → (30일) → Standard-IA → (90일) → Glacier Instant
→ (365일) → Deep Archive → (7년) → 만료(삭제)
```

전환 규칙의 핵심 포인트:

- 각 전환에 최소 대기 일수가 존재합니다 (예: Standard → Standard-IA는 30일)
- 전환은 한 방향으로만 진행합니다 (더 저렴한 클래스로)
- 만료 규칙은 버전 관리 활성화 시 현재 버전에 삭제 마커를 추가하고, 비버전 관리 시 객체를 영구 삭제합니다

<details>
<summary>Lifecycle 규칙 JSON 예시 — 전체 보기</summary>

```json
{
  "Rules": [
    {
      "ID": "logs-lifecycle",
      "Filter": { "Prefix": "logs/" },
      "Status": "Enabled",
      "Transitions": [
        { "Days": 30, "StorageClass": "STANDARD_IA" },
        { "Days": 90, "StorageClass": "GLACIER_IR" },
        { "Days": 365, "StorageClass": "DEEP_ARCHIVE" }
      ],
      "Expiration": { "Days": 2555 }
    }
  ]
}
```

</details>

---

## 5. 복제와 이벤트 알림

### S3 복제 (Replication)

S3 복제는 버킷 간에 객체를 자동으로 복제하는 기능입니다.

![S3 복제 유형 — CRR과 SRR](/assets/images/posts/aws-s3-storage/03-11-9-s3-복제-2026-업데이트.svg)

복제는 목적에 따라 2가지로 나뉩니다.

| 유형 | 설명 | 용도 |
|------|------|------|
| **CRR** (Cross-Region) | 서로 다른 리전 간 복제 | 재해 복구, 지연시간 감소, 규정 준수 |
| **SRR** (Same-Region) | 같은 리전 내 버킷 간 복제 | 로그 집계, 다른 계정 간 데이터 공유 |

복제 요구사항은 다음과 같습니다.

- 소스 및 대상 버킷 모두 **버전 관리가 활성화**되어야 합니다
- IAM 역할에 S3 복제 권한이 부여되어야 합니다
- 소스와 대상 버킷은 서로 다른 AWS 계정일 수 있습니다
- 기존 객체는 자동 복제되지 않습니다 (S3 Batch Replication으로 마이그레이션)
- 삭제 마커 복제는 선택적으로 활성화 가능합니다

**S3 Replication Time Control (RTC)**는 복제 완료 시간을 15분 이내(99.99%)로 보장하는 기능으로, 규정 준수 요구사항이 엄격한 워크로드에 적합합니다.

### 이벤트 알림 (Event Notifications)

S3 버킷에서 특정 이벤트가 발생할 때 알림을 받을 수 있습니다.

![S3 이벤트 알림 아키텍처](/assets/images/posts/aws-s3-storage/03-12-10-s3-event-notifications.svg)

주요 이벤트 유형은 다음과 같습니다.

| 이벤트 카테고리 | 예시 |
|----------------|------|
| **객체 생성** | `s3:ObjectCreated:Put`, `Post`, `Copy`, `CompleteMultipartUpload` |
| **객체 삭제** | `s3:ObjectRemoved:Delete`, `DeleteMarkerCreated` |
| **객체 복원** | `s3:ObjectRestore:Post`, `Completed` |
| **복제** | `s3:Replication:OperationFailed` 등 |
| **태그 변경** | `s3:ObjectTagging:Put`, `Delete` |

이벤트를 전달받을 수 있는 대상은 4가지입니다.

| 대상 | 특징 |
|------|------|
| **SNS Topic** | 이메일, SMS, HTTP 엔드포인트로 알림 발송 |
| **SQS Queue** | 이벤트를 큐에 저장하여 비동기 처리 |
| **AWS Lambda** | 이벤트 트리거로 함수 실행 (이미지 리사이징, 썸네일 생성) |
| **Amazon EventBridge** | 고급 이벤트 필터링, 다수 서비스로 라우팅, 아카이브 및 재생 |

EventBridge로 전송하면 객체 크기, 키 접두사, 메타데이터 기반의 고급 필터링과 이벤트 아카이브/재생이 가능해집니다.

---

## 6. 성능 최적화

S3는 대규모 데이터 처리를 위한 다양한 성능 최적화 기능을 제공합니다.

![S3 성능 최적화 기법 — 멀티파트, Transfer Acceleration, 접두사 분산](/assets/images/posts/aws-s3-storage/03-13-11-s3-성능-최적화.svg)

### 핵심 최적화 기법

**1. 멀티파트 업로드**

100MB 이상 파일은 멀티파트 업로드를 사용합니다. 파일을 여러 파트로 분할해 병렬 업로드하므로 네트워크 대역폭을 최대한 활용하고, 실패한 파트만 재전송할 수 있습니다.

**2. S3 Transfer Acceleration**

CloudFront의 글로벌 엣지 로케이션을 활용해 장거리 대규모 데이터 전송을 가속합니다. 가까운 엣지에서 수신한 후 AWS 백본망을 통해 빠르게 전송하므로, 최대 50배 빠른 전송이 가능합니다.

**3. 키 이름 접두사 분산**

S3는 키 이름의 접두사를 기반으로 데이터를 파티션에 분산시킵니다. 순차적인 키 이름(예: 타임스탬프 기반)은 동일 파티션에 집중되어 처리량이 제한될 수 있습니다.

```python
import hashlib

def make_key(original: str) -> str:
    prefix = hashlib.sha256(original.encode()).hexdigest()[:2]
    return f"{prefix}/{original}"

# Before: photos/2026/01/img1.jpg (병목)
# After:  a1/photos/2026/01/img1.jpg (분산)
```

해시 기반 접두사(앞 2자리)를 사용하면 256개 파티션으로 분산되어 초당 수천 건의 요청을 처리할 수 있습니다. S3 Express One Zone을 사용하면 이 제한이 완화됩니다.

### 추가 성능 팁

| 기법 | 효과 |
|------|------|
| **Range GET** | 대용량 객체의 특정 바이트 범위만 다운로드 |
| **S3 Select** | 서버 측에서 CSV/JSON/Parquet 필터링하여 필요한 데이터만 검색 |
| **S3 Batch Operations** | 대량의 객체에 일괄 작업 (복사, 태그 지정, 암호화) |
| **버전 관리 최적화** | LIST 요청 시 버전이 많으면 성능 저하 — Lifecycle로 이전 버전 정리 |

---

## Takeaway

1. **객체 스토리지의 기본은 Key-Value 구조입니다** — 버킷(전역 유일) 안에 객체(Key + Value + Metadata)가 저장되며, 평면적 주소 공간과 REST API로 접근합니다. 이 구조를 이해하면 나머지는 자연스럽게 따라옵니다
2. **스토리지 클래스와 Lifecycle로 비용을 최적화합니다** — 데이터 액세스 패턴에 맞춰 Standard, IA, Glacier를 선택하고, Lifecycle 규칙으로 자동 전환하면 운영 개입 없이 비용을 절감할 수 있습니다
3. **보안은 다층 방어로 설계합니다** — IAM 정책, 버킷 정책, Block Public Access, 암호화(SSE-S3/SSE-KMS)를 겹겹이 쌓고, 버전 관리와 복제로 데이터 보호까지 갖추면 안전한 스토리지 환경이 완성됩니다

---

## 심화 학습 — Advanced S3 시리즈

이 글에서 다룬 S3 기초를 바탕으로, 더 깊은 주제를 다루는 심화 포스트를 참고하세요.

| 포스트 | 주제 |
|--------|------|
| [S3 프로토콜과 API 심층 분석]({% post_url 2026-06-13-S3-Protocol-and-API-Deep-Dive %}) | REST API 구조, HTTP 헤더, 서명 버전, 멀티파트 업로드 내부 동작 |
| [S3 데이터 공유 서비스]({% post_url 2026-06-13-S3-Data-Sharing-Services %}) | Access Point, Pre-signed URL, S3 Access Points, DataSync |
| [S3 Access Grants와 복제]({% post_url 2026-06-13-S3-Access-Grants-and-Replication %}) | Access Grants, SRR/CRR 상세 구성, Batch Replication |
| [S3 보안 다층 방어 패턴]({% post_url 2026-06-13-S3-Security-Patterns %}) | 7계층 방어 모델, 버킷 정책 6가지 패턴, CloudTrail 감사 |
| [S3 아키텍처 패턴]({% post_url 2026-06-13-S3-Data-Sharing-Architecture-Patterns %}) | 데이터 레이크, 정적 웹 호스팅, CDN 통합 아키텍처 |
| [S3 2026 신기능]({% post_url 2026-06-13-S3-New-Features-2026 %}) | Express One Zone, Directory Bucket, S3 Tables 등 최신 기능 |
| [VersityGW 온프레미스 S3]({% post_url 2026-06-13-VersityGW-On-Premises-S3 %}) | 온프레미스 환경에서 S3 호환 스토리지 구축 |

---

> **AWS 시리즈 3/16**
>
> | | |
> |---|---|
> | ← [EC2 & EBS — AWS 컴퓨팅 완전 정복]({% post_url 2026-06-14-AWS-EC2-Computing %}) | |
> | | [VPC 네트워킹 — 서브넷부터 Transit Gateway까지]({% post_url 2026-06-14-AWS-VPC-Networking %}) → |
