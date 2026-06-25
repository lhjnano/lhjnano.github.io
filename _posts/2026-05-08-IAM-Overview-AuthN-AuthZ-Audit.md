---
layout: post
title: "[IAM & 보안 (1)] IAM이란 무엇인가 — 인증·인가·감사 3대 요소"
categories: [Security, IAM, Infrastructure]
description: "IAM(Identity and Access Management)의 핵심인 인증, 인가, 감사를 설명하고, 접근 제어 모델이 DAC에서 PBAC로 발전해 온 과정을 정리합니다."
keywords: [IAM, Authentication, Authorization, Audit, RBAC, PBAC, AWS IAM]
toc: true
toc_sticky: true
---

## Hook

"비밀번호만 있으면 안 되나요?" — 책상에 앉아 있던 주니어 개발자가 물었습니다. 맞습니다. 사용자가 10명이면 비밀번호로 충분합니다. 하지만 사용자가 1,000명이 되고, 권한 조합이 50가지가 넘고, "영업팀은 자기 팀 사용자만 관리할 수 있어야 해" 같은 요구사항이 들어오면 이야기가 달라집니다.

## TL;DR

- IAM은 **인증(AuthN)**, **인가(AuthZ)**, **감사(Audit)** 3대 요소로 구성됩니다
- 접근 제어 모델은 **DAC → MAC → RBAC → PBAC**로 발전했습니다
- AWS IAM이 사실상의 표준이며, **정책 기반(PBAC)** 접근 제어를 사용합니다
- 정책 평가 3원칙: 기본 거부, 명시적 거부 우선, 허용 합산

---

## Background: IAM의 3대 핵심 요소

IAM(Identity and Access Management)은 "누가(Who), 무엇을(What), 어떻게(How), 언제(When) 접근할 수 있는가"를 정의하는 프레임워크입니다.

```
┌──────────────────────────────────────────────────────────────┐
│                       IAM (Identity & Access Management)      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  인증 (AuthN) │  │  인가 (AuthZ) │  │  감사 (Audit) │        │
│  │              │  │              │  │              │        │
│  │ "너 누구야?"  │  │ "뭘 할 수 있어?"│  │ "뭘 했어?"   │        │
│  │              │  │              │  │              │        │
│  │ · 비밀번호    │  │ · 권한 정책    │  │ · 접근 로그   │        │
│  │ · MFA        │  │ · 역할 (Role) │  │ · 변경 이력   │        │
│  │ · SSO        │  │ · 범위 (Scope)│  │ · 컴플라이언스│        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│          │                │                │                  │
│          └────────────────┼────────────────┘                  │
│                           ▼                                    │
│              ┌─────────────────────┐                          │
│              │  Identity Store     │                          │
│              │  (AD / LDAP / DB)   │                          │
│              └─────────────────────┘                          │
└──────────────────────────────────────────────────────────────┘
```

### 인증 (Authentication, AuthN)

"너가 너라고 주장하는 사람이 맞는가?"를 검증하는 과정입니다.

- **비밀번호**: 가장 기본적인 방식 (지식 기반 — "something you know")
- **MFA**: 비밀번호 + OTP/지문/인증서 (2개 이상 조합)
- **SSO**: 한 번 로그인하면 여러 시스템에 자동 인증
- **인증서 (x509)**: 스마트카드, PKI 기반 (소유 기반 — "something you have")

### 인가 (Authorization, AuthZ)

"인증된 사용자가 어떤 작업을 할 수 있는가?"를 결정합니다.

- **RBAC**: 역할 기반 — "Help Desk 역할이면 사용자 관리 가능"
- **PBAC**: 정책 기반 — "정책 문서에 명시된 권한만 허용" (AWS IAM 방식)
- **ABAC**: 속성 기반 — "IP가 사내망이고 업무 시간이면 허용"

### 감사 (Audit)

"누가 언제 무엇을 했는가?"를 기록하고 추적합니다.

- **접근 로그**: 로그인 성공/실패, API 호출 기록
- **변경 이력**: 생성/수정/삭제 작업의 before/after
- **컴플라이언스**: SOC2, ISO 27001, GDPR 등 규제 대응

---

## Solution: 인증 vs 인가, 그리고 접근 제어 모델

### 인증 vs 인가 — 명확한 차이

| 구분 | 인증 (Authentication) | 인가 (Authorization) |
|------|----------------------|---------------------|
| 질문 | "너 누구야?" | "뭘 할 수 있어?" |
| 영어 | Auth**N** (N = Noun) | Auth**Z** (Z = Authorization) |
| 실패 시 | 401 Unauthorized | 403 Forbidden |
| 시점 | 요청 시작 시 1회 | 모든 요청마다 평가 |
| 수명 | 세션/토큰 만료 시까지 | 정책 변경 시 즉시 반영 |

### 접근 제어 모델 발전사

```
DAC (1980년대)         MAC (1980년대)         RBAC (1990년대)        PBAC (2010년대)
━━━━━━━━━━━━━━━       ━━━━━━━━━━━━━━━       ━━━━━━━━━━━━━━━       ━━━━━━━━━━━━━━━
임의 접근 제어          강제 접근 제어          역할 기반 접근 제어      정책 기반 접근 제어

소유자가 권한 부여       시스템이 강제 분류      역할별 권한 그룹화      정책 문서로 세밀 제어
("파일 주인이 결정")    ("기밀/대외비 분류")   ("관리자/사용자")     ("AWS IAM")

유연하지만 위험         보수적, 관리 힘듦       중간 수준 유연성        최고 수준 유연성
```

**RBAC의 한계**: 역할이 4개(super_admin, user_admin, auditor, viewer)면 충분할 것 같지만, 현실에서는 "영업팀 OU의 사용자만 관리할 수 있는 헬프데스크" 같은 요구사항이 생깁니다. RBAC로는 이를 표현할 수 없습니다.

| 요구사항 | RBAC | PBAC |
|---------|------|------|
| "Help Desk 팀은 사용자를 관리할 수 있다" | O | O |
| "Help Desk는 관리자 계정을 삭제할 수 없다" | X (코드 수정) | O (정책에 Deny 추가) |
| "영업팀 OU의 사용자만 관리" | X | O (resource 패턴) |
| "업무 시간에만 DNS 수정 허용" | X | O (condition) |
| "특정 IP 대역에서만 관리 기능 허용" | X | O (condition) |

---

## Result: 정책 평가 3원칙

AWS IAM 모델의 핵심인 정책 평가 규칙을 소개합니다. 이 규칙은 PBAC를 채택하는 모든 시스템이 동일하게 적용합니다.

**핵심 3원칙:**

1. **기본 거부 (Default Deny)**: 명시적으로 허용하지 않으면 모두 거부
2. **명시적 거부 우선 (Explicit Deny wins)**: 하나라도 Deny가 있으면 무조건 거부
3. **허용 합산 (Allow accumulation)**: 여러 정책의 Allow가 합산됨

정책 평가 예시:

```json
// 정책 1: Help Desk (그룹 정책)
{ "effect": "Allow", "action": ["users:*"], "resource": "*" }

// 정책 2: 보안 강화 (사용자 정책)
{ "effect": "Deny", "action": ["users:Delete"],
  "resource": "cn=Administrator,*" }

// 요청: "users:Delete" on "cn=Administrator,..."
// 평가: 정책1 Allow 매칭 → 정책2 Deny 매칭 → 결과: DENY
```

<details markdown="1">
<summary>AWS IAM 구성요소 전체 다이어그램</summary>

```
┌─────────────────────────────────────────────────────────────┐
│                     AWS IAM 구성요소                         │
│                                                             │
│  Principal (주체)                                           │
│  ├── User    — 사람                                        │
│  ├── Group   — 사용자 그룹 (Admins, Developers)             │
│  └── Role    — 임시 역할                                    │
│                                                             │
│  Policy (정책) — JSON 문서                                  │
│  {                                                          │
│    "Effect": "Allow",                                      │
│    "Action": ["s3:GetObject", "s3:ListBucket"],             │
│    "Resource": "arn:aws:s3:::my-bucket/*",                  │
│    "Condition": {"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}}│
│  }                                                          │
│                                                             │
│  Permission (권한) = Policy + Resource + Condition           │
└─────────────────────────────────────────────────────────────┘
```

</details>

---

## Takeaway

1. **인증과 인가는 다르다** — 401(Unauthorized)은 사실 인증 실패이고, 403(Forbidden)이 인가 실패다. HTTP 상태 코드 이름이 역사적 실수라서 헷갈리기 쉽다
2. **RBAC에서 PBAC로의 전환은 코드 수정 없는 권한 변경을 가능하게 한다** — 정책 JSON 파일만 바꾸면 모든 권한이 즉시 변경된다
3. **명시적 거부가 최우선이다** — Allow를 아무리 많이 줘도, 하나의 Deny가 모든 것을 덮어쓴다. 보안 설계에서 Deny를 적극 활용해야 한다

> **다음 글**: [IAM & 보안 (2) PBAC vs RBAC — 정책 기반 접근 제어 설계]({% post_url 2026-05-09-PBAC-vs-RBAC-Policy-Engine %})
