---
layout: post
title: "[IAM & 보안 (2)] PBAC vs RBAC — 정책 기반 접근 제어 설계"
categories: [Security, IAM, Infrastructure]
description: "RBAC와 PBAC의 차이를 설명하고, 정책 평가 알고리즘의 동작 원리와 와일드카드 매칭, 내장 정책 설계를 다룹니다."
keywords: [PBAC, RBAC, Policy Engine, Access Control, Wildcard, Authorization]
toc: true
toc_sticky: true
---

## Hook

"관리자 역할 하나면 되지 않나요?" — 개발 초기에 설계자가 던진 질문이었습니다. 3개월 후, 요구사항 목록에는 "영업팀 사용자만 관리하는 헬프데스크", "DNS만 수정하는 네트워크팀", "업무 시간에만 변경 가능한 설정"이 줄지어 있었습니다. 관리자 역할 하나로는 도저히 커버할 수 없었습니다.

## TL;DR

- RBAC는 역할 단위로 권한을 고정하지만, **정책 변경마다 코드 수정이 필요**합니다
- PBAC는 JSON 정책 문서로 권한을 정의하여, **파일 수정만으로 권한을 즉시 변경**합니다
- 정책 평가는 **기본 거부 → 패턴 매칭 → 조건 확인 → Deny 우선 → Allow 합산** 순서로 동작합니다
- 와일드카드(`*`)를 활용한 Action/Resource 매칭이 PBAC의 유연성 핵심입니다

> **이전 글**: [(1) IAM이란 무엇인가]({% post_url 2026-05-08-IAM-Overview-AuthN-AuthZ-Audit %})

---

## Background: RBAC (Role-Based Access Control)

사용자를 미리 정의된 "역할(Role)"에 할당하고, 각 역할에 고정된 권한을 부여합니다.

```
    사용자                역할                  권한
   ┌─────┐             ┌──────────┐          ┌──────────────┐
   │ 홍길동 │──┐        │          │          │ users:CRUD   │
   └─────┘  ├──▶       │ user_admin│────────▶│ groups:Read  │
   ┌─────┐  │          │          │          │ dashboard:R  │
   │ 김철수 │──┘        └──────────┘          └──────────────┘

   특징: 역할 수만큼 권한 세트가 고정됨
   문제: "영업팀 OU만 관리" 같은 세분화 불가능
```

| 장점 | 단점 |
|------|------|
| 이해하기 쉬움 | 역할 폭발 (역할이 계속 늘어남) |
| 구현이 간단함 | 세분화된 권한 제어 불가 |
| 감사가 명확함 | 역할 변경 시 코드 수정 필요 |
| 소규모 시스템에 적합 | 조건부 권한 불가 (시간/IP) |

---

## Solution: PBAC (Policy-Based Access Control)

정책(Policy)이라는 JSON 문서로 권한을 정의합니다. 각 정책은 Effect, Action, Resource, Condition으로 구성됩니다.

```
    사용자           정책 문서                권한 평가
   ┌─────┐        ┌──────────────┐         ┌──────────────┐
   │ 홍길동 │──┐    │              │         │              │
   └─────┘  │    │ Effect: Allow │         │ 1. 정책 수집  │
            ├──▶ │ Action: users:*│──────▶ │ 2. 패턴 매칭  │──▶ Allow/Deny
   그룹:    │    │ Resource: ou=Sales│      │ 3. 조건 확인  │
   Help Desk│    │              │         │ 4. Deny 우선  │
   └────────┘    └──────────────┘         └──────────────┘

   특징: 정책만 바꾸면 모든 권한이 즉시 변경됨
```

### 정책 문서 구조

```json
{
  "version": "2026-06-20",
  "statement": [
    {
      "sid": "AllowUserManagement",
      "effect": "Allow",
      "action": [
        "users:List", "users:Read", "users:Create",
        "users:Update", "users:ResetPassword"
      ],
      "resource": "ou=Sales,DC=example,DC=local",
      "condition": {
        "ipAddress": { "ad:SourceIp": ["192.168.0.0/16"] }
      }
    },
    {
      "sid": "DenyDeleteAdmin",
      "effect": "Deny",
      "action": ["users:Delete"],
      "resource": "cn=Administrator,cn=Users,*"
    }
  ]
}
```

### 정책 평가 알고리즘

```
1. 정책 수집
   - 사용자에게 직접 연결된 정책
   - 사용자가 속한 그룹의 정책
   - 시스템 기본 정책

2. 기본 결정: DENY (모든 것은 기본적으로 거부)

3. 각 Statement 평가:
   for stmt in all_statements:
     action_match = 패턴 매칭(action, stmt.action)
     resource_match = 패턴 매칭(resource, stmt.resource)
     condition_match = 조건 평가(stmt.condition)

     if action_match and resource_match:
       if condition_match:
         if stmt.effect == "Deny":  return DENY  ← 즉시 종료!
         if stmt.effect == "Allow": has_allow = True

4. 최종 결정:
   if has_allow: return ALLOW
   else:         return DENY
```

### 와일드카드 매칭

| 패턴 | 매칭되는 예 | 매칭되지 않는 예 |
|------|-----------|----------------|
| `*` | 모든 것 | — |
| `users:*` | users:Create, users:Delete | groups:Create |
| `users:Create` | users:Create | users:Update |
| `*:Read` | users:Read, groups:Read | users:Create |
| `ou=*,DC=example*` | ou=Sales,DC=example,DC=local | cn=Admin,cn=Users,... |

---

## Result: 3가지 평가 예시

### 예시 1: 단순 허용

```
요청: user=helpdesk01  action=users:Create  resource=ou=Temp,...

정책 (Help Desk 그룹):
  { effect: "Allow", action: ["users:*"], resource: "*" }

평가:
  1. 정책 수집: Help Desk 정책
  2. 기본: DENY
  3. statement 평가:
     - action "users:Create" matches "users:*" ✓
     - resource matches "*" ✓
     - effect "Allow" → has_allow = True
  4. 결과: ALLOW ✓
```

### 예시 2: 명시적 거부

```
요청: user=helpdesk01  action=users:Delete  resource=cn=Administrator,...

정책들:
  (1) Help Desk: { effect: "Allow", action: ["users:*"], resource: "*" }
  (2) 보안 정책: { effect: "Deny", action: ["users:Delete"],
                   resource: "cn=Administrator,cn=Users,*" }

평가:
  1. 정책 수집: (1), (2)
  2. 기본: DENY
  3. statement 평가:
     (1) action matches, resource matches, Allow → has_allow = True
     (2) action matches, resource matches, Deny → return DENY!
  4. 결과: DENY (명시적 거부가 우선) ✗
```

### 예시 3: 조건 불일치

```
요청: user=dnsadmin  action=dns:AddRecord  resource=example.local  ip=10.0.0.5

정책:
  { effect: "Allow", action: ["dns:*"], resource: "*",
    condition: { "ipAddress": { "ad:SourceIp": ["192.168.0.0/16"] } } }

평가:
  3. statement 평가:
     - action "dns:AddRecord" matches "dns:*" ✓
     - resource matches "*" ✓
     - condition: 10.0.0.5 NOT in 192.168.0.0/16 → 조건 불일치!
     - → 스킵
  4. 결과: DENY (조건 미충족) ✗
```

<details markdown="1">
<summary>내장 정책 4종 전체 코드</summary>

**Super Admin:**
```json
{ "statement": [{ "effect": "Allow", "action": "*", "resource": "*" }] }
```

**User Admin (Help Desk):**
```json
{ "statement": [
  { "effect": "Allow",
    "action": ["users:*", "groups:List", "groups:Read",
               "groups:AddMember", "groups:RemoveMember", "dashboard:Read"],
    "resource": "*" },
  { "effect": "Deny", "action": ["users:Delete"],
    "resource": "cn=Administrator,cn=Users,*" }
] }
```

**Auditor (Read-Only):**
```json
{ "statement": [{
  "effect": "Allow", "action": ["*:List", "*:Read", "logs:Read"], "resource": "*"
}] }
```

**Viewer (Dashboard Only):**
```json
{ "statement": [{
  "effect": "Allow", "action": ["dashboard:Read", "domain:Read"], "resource": "*"
}] }
```

</details>

<details markdown="1">
<summary>Action 분류 체계 전체 표</summary>

| 리소스 | 작업들 |
|--------|--------|
| `users` | List, Read, Create, Update, Delete, ResetPassword, SetStatus, Unlock |
| `groups` | List, Read, Create, Update, Delete, AddMember, RemoveMember |
| `computers` | List, Read, SetStatus, Reset, Delete |
| `ous` | List, Read, Create, Update, Delete, LinkGPO, UnlinkGPO |
| `gpos` | List, Read, Create, Delete, SetStatus, Link, Unlink |
| `dns` | ListZones, ListRecords, AddRecord, DeleteRecord |
| `policies` | Read, Update |
| `domain` | Read, GetInfo, GetFsmo, GetHealth |
| `logs` | Read |
| `settings` | Read, Update |
| `iam` | ListPolicies, CreatePolicy, AttachPolicy, DetachPolicy |

</details>

---

## Takeaway

1. **정책 평가에서 Deny는 "즉시 종료"다** — Allow가 수백 개 있어도 Deny 하나가 모든 것을 취소한다. 이것이 보안의 최후 방어선이다
2. **조건(condition)은 "언제, 어디서"를 담당한다** — IP 제한, 시간 제한, MFA 여부를 정책에 넣으면 코드 한 줄 없이 동적 권한 제어가 가능하다
3. **Action 분류 체계(`resource:action`)는 설계의 핵심이다** — 이 패턴을 따르면 와일드카드로 세밀한 권한 제어가 가능하고, 감사 로그도 읽기 쉬워진다

> **이전 글**: [(1) IAM이란 무엇인가]({% post_url 2026-05-08-IAM-Overview-AuthN-AuthZ-Audit %}) | **다음 글**: [(3) OAuth2 & OIDC]({% post_url 2026-05-10-OAuth2-OIDC-Authorization-Flow %})
