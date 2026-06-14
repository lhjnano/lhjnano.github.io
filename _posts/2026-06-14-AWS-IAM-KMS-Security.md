---
layout: post
title: "[AWS 9/16] 보안 기초 — IAM 사용자 관리와 KMS 암호화"
categories: [AWS, Security]
description: AWS 보안의 근간인 IAM(사용자/역할/정책)과 KMS(키 관리, 봉투 암호화, CloudHSM)를 정리합니다.
keywords: [IAM, KMS, AWS, 보안, 암호화, CloudHSM]
toc: true
toc_sticky: true
---

## Hook

AWS 환경에서 "누가 무엇을 할 수 있는가"를 결정하는 것이 IAM이고, "데이터를 보이지 않게 만드는 것"이 암호화입니다. 루트 계정 Access Key를 코드에 박아두거나 KMS 없이 평문으로 저장하면 보안 사고는 시간문제입니다.

이 글에서는 IAM의 자격 증명(사용자/그룹/역할)과 정책 구조, 권한 평가 로직, 2026년 업데이트를 정리하고, 이어서 KMS의 키 유형, 봉투 암호화, 키 스토어(XKS/CloudHSM), 종합 암호화 전략까지 한 흐름으로 살펴봅니다.

---

## TL;DR

- **IAM은 인증과 권한 부여의 기반입니다** — 사용자/그룹/역할에 정책을 연결해 접근을 제어하는 글로벌 무료 서비스입니다
- **정책 평가는 "명시적 Deny가 최우선"입니다** — SCP ∩ Permission Boundary ∩ IAM 정책의 교집합이 최종 유효 권한입니다
- **Access Key 대신 IAM 역할을 사용합니다** — EC2/Lambda/ECS는 인스턴스/실행/태스크 역할로 임시 자격 증명을 받습니다
- **봉투 암호화가 AWS 암호화의 핵심입니다** — KMS 키로 데이터 키를 암호화하고, 데이터 키로 데이터를 암호화합니다
- **규제가 엄격하면 CloudHSM 또는 XKS를 선택합니다** — KMS는 FIPS Level 2, CloudHSM은 Level 3, XKS는 외부 HSM을 활용합니다

---

## 1. IAM 개요와 자격 증명

IAM(Identity and Access Management)은 AWS 리소스에 대한 액세스를 안전하게 제어하는 웹 서비스입니다. **인증(Authentication)**은 "당신은 누구인가"를, **권한 부여(Authorization)**는 "무엇을 할 수 있는가"를 결정합니다. 글로벌 서비스이며 추가 비용 없이 사용합니다.

### 사용자, 그룹, 역할

| 엔터티 | 자격 증명 | 용도 |
|--------|----------|------|
| **사용자** | 영구 (비밀번호 / Access Key) | 사람, 장기 애플리케이션 |
| **그룹** | 없음 (사용자 묶음) | 여러 사용자에 일관된 정책 적용 (중첩 불가) |
| **역할** | 임시 (STS 토큰) | AWS 서비스, 교차 계정, 임시 접근 |

권한은 `사용자 → 그룹 → 정책` 경로로 연결하는 것이 권장 패턴입니다. 역할은 신뢰 정책(Trust Policy)으로 "누가 이 역할을 수임할 수 있는가"를 정의합니다.

![IAM 역할의 신뢰 당사자 — 사용자, EC2, Lambda, 외부 IdP가 AssumeRole로 임시 자격 증명 획득](/assets/images/posts/aws-iam-kms/13-01-31-역할의-신뢰-당사자.svg)

역할은 IAM 사용자, AWS 서비스(EC2/Lambda), 외부 IdP(SAML/OIDC)가 수임할 수 있으며, 수임 시 STS가 발급한 임시 자격 증명으로 AWS 리소스에 접근합니다. **EC2에서는 Access Key를 직접 사용하지 말고 인스턴스 프로파일(역할)을 연결**해야 합니다.

---

## 2. IAM 정책과 권한 평가

IAM 정책은 JSON 형식으로 AWS 리소스에 대한 권한을 정의하며, 사용자/그룹/역할에 연결됩니다.

### 정책 유형

| 유형 | 관리 주체 | 특징 |
|------|----------|------|
| **AWS 관리형** | AWS | 사전 정의, 수정 불가 (예: `AmazonS3ReadOnlyAccess`) |
| **고객 관리형** | 사용자 | 직접 생성·관리, 세밀한 제어 가능 |
| **인라인** | — | 특정 엔터티에 1:1 포함, 상속 불가 |

정책의 핵심 요소는 5가지입니다. `Effect`(Allow/Deny), `Principal`(주체), `Action`(작업), `Resource`(ARN), `Condition`(조건)입니다.

<details>
<summary>IAM 정책 JSON 예시 — IP/리전 조건 포함</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": ["arn:aws:s3:::my-bucket/*"],
    "Condition": {
      "IpAddress": { "aws:SourceIp": ["10.0.0.0/8"] },
      "StringEquals": { "aws:RequestedRegion": ["ap-northeast-2"] }
    }
  }]
}
```

</details>

### 권한 평가 로직

정책 평가의 핵심 원칙은 **"기본 거부 + 명시적 Deny 최우선"**입니다. 모든 요청은 기본적으로 거부되며, Allow가 있어도 어디선가 Deny가 하나라도 있으면 거부됩니다.

![권한 평가 모델 — SCP ∩ Permission Boundary ∩ IAM 정책의 교집합이 최종 유효 권한](/assets/images/posts/aws-iam-kms/13-03-75-permission-boundary.svg)

최종 유효 권한은 세 가지 경계의 **교집합**입니다.

- **SCP (Service Control Policy)** — 조직 수준 최대 권한 경계
- **Permission Boundary** — 사용자/역할 단위 최대 권한 경계
- **IAM 정책** — 실제 권한 부여

`세션 정책`(AssumeRole 시 전달)을 추가하면 역할 정책과의 교집합으로 세션 권한이 더 좁아집니다. 위임된 권한이 지정된 경계를 넘지 못하도록 보장하는 구조입니다.

---

## 3. Access Key, MFA, IAM 2026 업데이트

### Access Key 관리

Access Key는 CLI/SDK/API 호출에 사용되는 장기 자격 증명입니다. 형식은 `AKIA...`로 시작하는 Access Key ID와 40자 Secret Access Key로 구성되며, 사용자당 최대 2개까지 생성할 수 있습니다.

- **절대 코드에 하드코딩하지 않습니다** → Secrets Manager 또는 IAM 역할 사용
- **90일 주기 정기 교체**, 미사용 키는 즉시 비활성화/삭제합니다
- EC2/Lambda/ECS에서는 Access Key 대신 역할을 연결합니다

### MFA (다중 인증)

MFA는 비밀번호 외에 추가 인증 수단을 요구해 보안을 강화합니다.

- **가상 MFA** — Google Authenticator, Authy 등 모바일 앱
- **하드웨어 MFA** — YubiKey 등 물리적 키 (FIDO2 지원)
- **FIDO2 보안 키** — 2026년 권장 방식, 피싱 방지 내장
- 루트 계정, IAM 사용자, Identity Center 사용자에 모두 적용합니다

### IAM Identity Center (구 AWS SSO)

조직 내 모든 계정과 애플리케이션에 대한 **중앙 집중식 액세스 관리** 서비스입니다.

![IAM Identity Center — 외부 IdP 연동으로 다중 계정 권한 세트 관리](/assets/images/posts/aws-iam-kms/13-02-71-iam-identity-center-구-aws-sso.svg)

외부 IdP(Microsoft Entra ID, Okta)와 SAML/OIDC로 연동하고, **권한 세트(Permission Sets)**로 계정별 RBAC를 정의합니다. 다중 계정 전략에서는 단일 위치에서 전체 접근을 관리합니다.

### 교차 계정 액세스

다중 계정 환경에서는 AssumeRole로 계정 간 안전하게 리소스에 접근합니다.

![교차 계정 액세스 — 개발/공유서비스/프로덕션 계정이 신뢰 관계로 역할 수임](/assets/images/posts/aws-iam-kms/13-04-91-교차-계정-액세스.svg)

프로덕션 계정의 역할은 **MFA 필수**로 설정해 추가 보안 계층을 둡니다. 계정 유형별 전략은 다음과 같습니다.

| 계정 | IAM 전략 | SCP |
|------|----------|-----|
| 관리 계정 | 엄격한 제한, MFA 필수 | 미적용 |
| 보안 계정 | 보안팀만 접근 | 보안 서비스만 허용 |
| 개발 계정 | 개발자 자유도 | 프로덕션 서비스 차단 |
| 프로덕션 | 최소 권한, MFA 필수 | 엄격한 SCP |

### 서비스 간 권한 위임

마이크로서비스 아키텍처에서는 각 서비스에 전용 역할을 부여해 권한을 분리합니다.

![서비스 간 권한 위임 — Lambda 실행 역할과 ECS 태스크 역할로 리소스 접근 분리](/assets/images/posts/aws-iam-kms/13-05-92-서비스-간-권한-위임.svg)

API Gateway → Lambda(실행 역할) → DynamoDB/S3/KMS, ECS Service(태스크 역할) → ECR/S3/Secrets Manager로 연결됩니다. **모든 서비스는 역할 기반으로 권한을 받고 Access Key를 사용하지 않습니다.**

---

## 4. KMS 개요와 키 유형

AWS KMS(Key Management Service)는 암호화 키의 생성, 저장, 관리, 감사를 통합 제공하는 완전 관리형 서비스입니다. S3, EBS, RDS, Lambda 등 대부분의 AWS 서비스와 통합되어 투명한 암호화를 제공합니다.

- **FIPS 140-2 Level 2** (기본), **Level 3** (CloudHSM)
- 키는 HSM 내에서만 존재하며 **절대 내보내지 않습니다**
- CloudTrail과 연동된 모든 키 사용 로깅

### KMS 키 유형

| 유형 | 관리 주체 | 키 교체 | 비용 |
|------|----------|---------|------|
| **AWS 관리형** (`aws/s3` 등) | AWS 서비스별 자동 | 연 1회 자동 | 무료 |
| **고객 관리형** | 사용자 직접 | 선택 (자동/수동) | 월 $1 + API |
| **AWS 소유 키** | AWS 완전 관리 | AWS 정책 | 무료 |

고객 관리형 키는 키 정책, 별칭, 태그, 교차 계정 공유, 7~30일 대기 후 삭제가 가능해 세밀한 제어가 필요한 아키텍처에 적합합니다.

### 데이터 키와 봉투 암호화

데이터 키는 실제 데이터를 암호화하는 대칭키로, KMS 키(`GenerateDataKey`)로 생성합니다. 일반 텍스트 키와 암호화된 키 두 가지를 반환하며, 평문 키는 메모리에서만 사용 후 즉시 폐기합니다.

![봉투 암호화 — KMS 키로 데이터 키를 암호화하고 데이터 키로 데이터를 암호화하는 이중 구조](/assets/images/posts/aws-iam-kms/14-01-4-봉투-암호화-envelope-encryption.svg)

봉투 암호화(Envelope Encryption)의 장점은 4가지입니다.

- **성능** — KMS에 모든 데이터를 보내지 않고 로컬에서 암/복호화
- **보안** — 데이터 키 수명이 짧고 KMS 키는 HSM에서 보호
- **확장성** — KMS API 호출 최소화 (데이터 키 재사용 가능)
- **키 회전** — KMS 키 교체 시 데이터 키만 재생성하면 됨

### 저장 중 암호화

![저장 중 암호화 — SSE-S3 / SSE-KMS / SSE-C 세 가지 방식](/assets/images/posts/aws-iam-kms/14-04-102-저장-중-암호화-encryption-at-rest.svg)

S3 서버 측 암호화 3가지 방식을 비교합니다.

| 방식 | 키 관리 | 특징 | 용도 |
|------|---------|------|------|
| **SSE-S3** | AWS 완전 관리 | AES-256, 기본값, 무료 | 일반 데이터 |
| **SSE-KMS** | KMS 고객 관리형 키 | CloudTrail 감사, 봉투 암호화 | 규정 준수, 감사 |
| **SSE-C** | 고객 제공 키 | AWS 미저장, 분실 시 복구 불가 | 최고 수준 제어 |

---

## 5. 키 스토어와 다중 리전

### 외부 키 스토어 (XKS)

XKS(External Key Store)는 KMS 키의 암호화 자료를 **온프레미스 외부 HSM**에 저장하는 기능입니다. "키가 클라우드를 떠나지 않아야 한다"는 규제를 충족합니다.

![외부 키 스토어(XKS) — AWS 서비스 → KMS → XKS Proxy → 온프레미스 HSM 통신 경로](/assets/images/posts/aws-iam-kms/14-02-81-외부-키-스토어-external-key-store-xks.svg)

통신 경로는 `KMS → XKS Proxy → 외부 HSM(Thales/Entrust)`입니다. 키 자료가 AWS 외부에 존재하므로 완전한 제어가 가능합니다.

### 다중 리전 키

여러 리전에서 동일한 KMS 키를 사용하는 기능입니다. 주요 키(Primary)와 복제 키(Replica)가 동일한 키 자료를 공유합니다.

![다중 리전 키 — 서울 주요 키를 도쿄에 복제, 리전 장애 시 복제본으로 복호화](/assets/images/posts/aws-iam-kms/14-03-85-다중-리전-키-multi-region-keys.svg)

재해 복구(DR) 시나리오에서 리전 장애가 발생해도 다른 리전의 복제 키로 동일 키 자료로 복호화할 수 있습니다. 교차 리전 암호화(한 리전 암호화, 다른 리전 복호화)에도 활용합니다.

### KMS vs CloudHSM

| 항목 | AWS KMS | CloudHSM |
|------|---------|----------|
| 관리 | 완전 관리형 | 사용자 관리 (HSM) |
| FIPS 등급 | Level 2 | Level 3 |
| 키 접근 | AWS가 HSM에서 관리 | 사용자만 접근 |
| API | KMS API | PKCS#11, JCE, CNG |
| 비용 | 낮음 | 높음 (HSM 시간당) |
| 적합 사례 | 일반 암호화 | 엄격한 규제 환경 |

2026년에는 **HMAC 키**(JWT 서명, 데이터 무결성 검증)와 **자동 키 교체**(연간, 키 ID 동일·백업 자료만 교체)도 지원합니다.

---

## 6. 종합 암호화 아키텍처

암호화는 데이터 상태에 따라 3단계로 설계합니다.

- **전송 중 (In Transit)** — TLS 1.3, VPC 엔드포인트, ACM 인증서 관리
- **저장 중 (At Rest)** — SSE-KMS / 고객 관리형 키, 봉투 암호화
- **사용 중 (In Use)** — AWS Nitro Enclaves (격리된 컴퓨팅 환경에서 복호화)

![종합 암호화 아키텍처 — 전송 중·저장 중·사용 중 암호화를 모두 적용한 설계](/assets/images/posts/aws-iam-kms/14-05-104-종합-암호화-아키텍처.svg)

종합 아키텍처는 클라이언트 → ALB/API Gateway(TLS) → Lambda/ECS(봉투 암호화) → DynamoDB/S3(SSE-KMS, 저장 중) → CloudHSM/Nitro Enclaves(사용 중)로 구성됩니다. 각 계층마다 암호화를 적용해 다층 방어를 완성합니다.

<details>
<summary>고객 관리형 KMS 키 정책 예시 — 서비스 접근 제한</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Enable IAM User Permissions",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::123456789012:root" },
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "Allow Lambda Decrypt",
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "*"
    }
  ]
}
```

</details>

---

## Takeaway

1. **IAM 역할 기반으로 권한을 부여합니다** — Access Key를 직접 사용하지 말고 EC2/Lambda/ECS에 역할을 연결해 임시 자격 증명을 받습니다. 루트 계정은 MFA 필수, 일상적으로 사용하지 않으며, IAM Identity Center로 다중 계정 접근을 중앙 관리합니다
2. **권한 평가는 교집합 + 명시적 Deny 최우선입니다** — SCP ∩ Permission Boundary ∩ IAM 정책(∩ 세션 정책)의 교집합이 최종 유효 권한입니다. 기본은 거부이므로, 최소 권한 원칙으로 필요한 만큼만 Allow를 부여하고 Access Analyzer로 미사용 권한을 지속 정리합니다
3. **봉투 암호화와 고객 관리형 키로 보안과 감사를 확보합니다** — KMS 키로 데이터 키를 암호화(봉투 암호화)해 성능과 보안의 균형을 잡고, 고객 관리형 키로 CloudTrail 감사 추적을 확보합니다. 규제가 엄격한 환경에서는 CloudHSM(Level 3) 또는 XKS(외부 HSM)로 키 제어권을 강화합니다

---

> **AWS 시리즈 9/16**
>
> | | |
> |---|---|
> | ← [분석 & 파일 스토리지 — Redshift, Athena, EFS, FSx]({% post_url 2026-06-14-AWS-Analytics-FileStorage %}) | |
> | | [인증 & 방화벽 — Cognito, ACM, Shield/WAF]({% post_url 2026-06-14-AWS-Auth-Firewall %}) → |
