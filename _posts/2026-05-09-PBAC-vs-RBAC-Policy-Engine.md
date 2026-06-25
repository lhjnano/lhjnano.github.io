---
layout: post
title: "[IAM & 보안 (2)] PBAC vs RBAC — 정책 기반 접근 제어 설계"
categories: [Security, IAM, Infrastructure]
description: "RBAC의 한계에서 출발해 PBAC의 정책 문서 구조, 평가 알고리즘, 와일드카드 매칭, 내장 정책 설계까지 단계적으로 살펴봅니다."
keywords: [PBAC, RBAC, Policy Engine, Access Control, Wildcard, Authorization]
toc: true
toc_sticky: true
---

## 들어가며

개발 초기에 설계자가 "관리자 역할 하나면 되지 않나요?"라고 물었습니다. 3개월 후, 요구사항 목록에는 "영업팀 사용자만 관리하는 헬프데스크", "DNS만 수정하는 네트워크팀", "업무 시간에만 변경 가능한 설정"이 줄지어 늘어 있었고, 관리자 역할 하나로는 도저히 커버할 수 없었습니다. 이 글은 그 과정에서 깨달은 것 — 역할 기반 접근 제어(RBAC)의 한계와 정책 기반 접근 제어(PBAC)가 가져다 주는 유연성 — 을 정리합니다.

---

## RBAC: 익숙한 출발점

가장 직관적인 접근 제어 모델은 "사용자에게 역할을 부여하고, 역할에 권한을 묶어두는" 것입니다. Active Directory의 보안 그룹, 리눅스의 `/etc/group`, 대부분의 사내 시스템이 이 방식으로 동작하므로, 누구나 쉽게 이해할 수 있습니다. RBAC는 작은 시스템에서는 완벽하게 작동하지만, 조직이 커질수록 한계가 명확해집니다.

아래 그림은 RBAC의 핵심 구조를 보여줍니다. 사용자가 역할에 연결되고, 역할이 고정된 권한 세트를 가진다는 점 — 그리고 역할 수만큼 권한 세트가 늘어난다는 점에 주목해 주세요.

```
    사용자                역할                  권한
   ┌─────┐            ┌──────────┐          ┌──────────────┐
   │ 홍길동 │──┐       │          │          │ users:CRUD   │
   └─────┘  ├──▶      │user_admin│────────▶ │ groups:Read  │
   ┌─────┐  │         │          │          │ dashboard:R  │
   │ 김철수 │──┘       └──────────┘          └──────────────┘

   특징: 역할 수만큼 권한 세트가 고정됨
```

이 모델의 장단점을 비교하면 한계가 더 또렷하게 보입니다. "역할 변경 시 코드 수정이 필요하다"는 단점이 왜 치명적인지, 그리고 "조건부 권한 불가"가 실무에서 어떤 문제를 일으키는지를 특히 살펴보시기 바랍니다.

| 장점 | 단점 |
|------|------|
| 이해하기 쉬움 | 역할 폭발 (역할이 계속 늘어남) |
| 구현이 간단함 | 세분화된 권한 제어 불가 |
| 감사가 명확함 | 역할 변경 시 코드 수정 필요 |
| 소규모 시스템에 적합 | 조건부 권한 불가 (시간/IP) |

> 핵심 통찰: RBAC의 진짜 문제는 "역할이 많아진다"가 아니라, **역할을 고쳤을 때마다 코드를 수정하고 재배포해야 한다는 점**입니다. 권한 정책과 애플리케이션 코드가 단단히 결합되어 있기 때문입니다.

그렇다면 권한을 코드에서 분리해, 파일만 고쳐도 즉시 반영되는 구조는 만들 수 없을까요? 정답이 바로 다음에 나올 PBAC입니다.

---

## PBAC: 정책으로 권한을 풀다

RBAC의 가장 큰 결함은 권한이 코드에 박혀 있다는 점이었습니다. PBAC(Policy-Based Access Control)는 이 문제를 "권한을 JSON 정책 문서로 옮기는" 방식으로 해결합니다. 정책 문서는 `Effect`(허용/거부), `Action`(무엇을), `Resource`(어디에), `Condition`(어떤 조건에서) 네 가지 요소로 구성되며, 파일 수정만으로 권한을 즉시 변경할 수 있습니다.

아래 다이어그램은 PBAC의 작동 흐름입니다. 사용자와 그룹이 정책 문서를 거쳐 평가 엔진으로 들어가고, 평가 엔진이 네 단계를 거쳐 최종 Allow/Deny를 결정한다는 점을 확인해 주세요. RBAC와 달리 권한이 "고정된 세트"가 아니라 "평가 결과"라는 것이 핵심 차이입니다.

```
    사용자           정책 문서                권한 평가 엔진
   ┌─────┐        ┌──────────────┐         ┌──────────────┐
   │ 홍길동 │──┐    │              │         │ 1. 정책 수집  │
   └─────┘  │    │ Effect: Allow │         │ 2. 패턴 매칭  │
            ├──▶ │ Action: users:*│──────▶ │ 3. 조건 확인  │──▶ Allow/Deny
   그룹:    │    │ Resource:ou=Sales│       │ 4. Deny 우선  │
   HelpDesk │    │              │         │              │
   └────────┘    └──────────────┘         └──────────────┘

   특징: 정책만 바꾸면 모든 권한이 즉시 변경됨
```

왜 JSON을 선택했을까요? 사람이 읽고 쓰기 쉬운 선언적 포맷이기 때문입니다. YAML보다 구조가 명확하고, XML보다 가볍습니다. 더 중요한 것은 "버전 관리가 가능하다"는 점입니다 — 정책 파일을 Git에 넣으면, 누가 언제 어떤 권한을 변경했는지 코드 리뷰처럼 추적할 수 있습니다.

### 정책 문서 구조

정책 문서는 하나의 파일 안에 여러 `statement`(명세)를 담을 수 있습니다. 각 statement는 독립적으로 평가되며, `sid`로 식별합니다. 아래 예시를 보면서 두 가지를 관찰해 주세요. 첫째, 하나의 정책이 "허용"과 "거부"를 동시에 가질 수 있다는 점, 둘째, `condition`이 IP 주소 제한처럼 구체적인 맥락을 표현한다는 점입니다.

<details markdown="1">
<summary>정책 문서 구조 (펼쳐보기)</summary>

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
</details>

> 핵심 통찰: 하나의 정책 안에서 Allow와 Deny를 함께 두는 것은 의도된 설계입니다. "기본은 허용하되, 특정 대상은 절대 거부한다"는 안전망을 한 파일에서 관리할 수 있기 때문입니다.

구조를 알았으니, 이제 이 정책들이 실제로 어떻게 평가되는지 — 즉 엔진의 내부 로직을 들여다볼 차례입니다.

---

## 정책 평가 알고리즘: 엔진의 내부

정책 문서가 아무리 잘 작성되어도, 평가 로직이 명확하지 않으면 결과를 예측할 수 없습니다. PBAC의 평가 알고리즘은 보안 원칙인 "기본 거부(Deny by Default)"에서 출발합니다. 아무 정책도 매칭되지 않으면 무조건 거부합니다 — 이것이 시스템의 첫 번째 방어선입니다.

아래 의사코드는 평가의 전체 흐름을 보여줍니다. 특히 주목할 부분은 세 군데입니다. 첫째, 1단계에서 사용자 정책과 그룹 정책, 시스템 기본 정책을 모두 수집한다는 점, 둘째, Deny를 만나는 순간 즉시 종료한다는 점, 셋째, Allow는 단지 "가능성"으로 기록만 해두고 최종 결정은 마지막에 내린다는 점입니다.

<details markdown="1">
<summary>정책 평가 알고리즘 의사코드 (펼쳐보기)</summary>

```
1. 정책 수집
   - 사용자에게 직접 연결된 정책
   - 사용자가 속한 그룹의 정책
   - 시스템 기본 정책

2. 기본 결정: DENY (모든 것은 기본적으로 거부)

3. 각 Statement 평가:
   for stmt in all_statements:
     action_match   = 패턴 매칭(request.action, stmt.action)
     resource_match = 패턴 매칭(request.resource, stmt.resource)
     condition_match = 조건 평가(stmt.condition)

     if action_match and resource_match:
       if condition_match:
         if stmt.effect == "Deny":  return DENY  ← 즉시 종료!
         if stmt.effect == "Allow": has_allow = True

4. 최종 결정:
   if has_allow: return ALLOW
   else:         return DENY
```
</details>

왜 Deny를 만나면 즉시 종료할까요? 보안에서 "거부"는 절대적인 판단이어야 하기 때문입니다. 반면 Allow는 "이 정책이 허용한다"는 의미일 뿐, 다른 Deny가 없을 때만 유효합니다. 따라서 Allow는 잠정적으로 모아두고, Deny가 하나라도 있으면 그것이 최종 결과가 됩니다.

### 와일드카드 매칭: 유연성의 핵심

평가 알고리즘이 패턴 매칭에 의존한다면, 와일드카드(`*`)는 그 매칭의 핵심 도구입니다. `users:*`는 users로 시작하는 모든 작업을, `*:Read`는 모든 리소스의 Read 작업을 의미합니다. 이 단순한 규칙 하나로 수십 개의 권한을 한 줄로 표현할 수 있습니다.

아래 표는 와일드카드 패턴이 실제로 어떻게 매칭되는지 보여줍니다. 각 행에서 "매칭되는 예"와 "매칭되지 않는 예"를 비교하면서, `*`의 위치가 의미를 어떻게 바꾸는지 관찰해 주세요.

| 패턴 | 매칭되는 예 | 매칭되지 않는 예 |
|------|-----------|----------------|
| `*` | 모든 것 | — |
| `users:*` | users:Create, users:Delete | groups:Create |
| `users:Create` | users:Create | users:Update |
| `*:Read` | users:Read, groups:Read | users:Create |
| `ou=*,DC=example*` | ou=Sales,DC=example,DC=local | cn=Admin,cn=Users,... |

> 핵심 통찰: 와일드카드는 단순한 편의 기능이 아니라 **정책 수를 줄이는 설계 도구**입니다. `users:*` 하나로 여덟 개의 users 작업을 커버하므로, 정책 문서가 간결해지고 유지보수가 쉬워집니다.

알고리즘과 매칭 규칙을 이해했다면, 이제 실제 요청이 들어왔을 때 엔진이 어떻게 판단하는지 세 가지 시나리오로 확인해 보겠습니다.

---

## 실전 평가: 3가지 시나리오

이론은 실전에서 확인해야 비로소 완성됩니다. 다음 세 시나리오는 가장 자주 발생하는 평가 상황 — 단순 허용, 명시적 거부, 조건 불일치 — 를 다룹니다. 각 예시에서 "평가" 단계가 알고리즘의 어느 부분에 해당하는지 매칭해 보면 이해가 빠릅니다.

### 시나리오 1: 단순 허용

가장 기본적인 케이스입니다. 헬프데스크 사용자가 임시 OU에 사용자를 생성하려 할 때, 하나의 Allow 정책이 매칭되어 허용되는 과정을 봅니다. 어떤 조건도 걸려 있지 않으므로, 패턴 매칭만 통과하면 즉시 `has_allow`가 참이 됩니다.

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

### 시나리오 2: 명시적 거부

이번에는 같은 헬프데스크 사용자가 Administrator 계정을 삭제하려 하는 상황입니다. Allow 정책은 여전히 매칭되지만, 별도의 보안 정책이 Deny를 선언하고 있어 즉시 거부됩니다. Allow가 먼저 매칭되더라도 Deny가 우선한다는 점 — 알고리즘의 가장 중요한 규칙 — 을 확인해 주세요.

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

### 시나리오 3: 조건 불일치

세 번째는 조건(condition)이 결정을 좌우하는 경우입니다. DNS 관리자가 사내망이 아닌 IP에서 작업을 시도할 때, action과 resource는 매칭되지만 IP 조건이 맞지 않아 거부됩니다. 조건이 "추가 장벽"으로 작동하는 방식을 주의 깊게 보시기 바랍니다.

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

세 시나리오를 관통하는 교훈이 하나 있습니다. **Allow는 "들어갈 수 있는 문"이고, Deny와 Condition은 "그 문을 잠그는 자물쇠"라는 것입니다.** 이 감각을 익히면 복잡한 정책 조합도 머릿속에서 시뮬레이션할 수 있습니다.

---

## 내장 정책 설계: 네 가지 역할

실제 시스템에서는 사용자가 정책을 처음부터 짜는 경우보다, 미리 정의된 내장 정책(built-in policy)을 선택하는 경우가 많습니다. 이 시스템에서는 네 가지 역할 — Super Admin, User Admin, Auditor, Viewer — 을 내장 정책으로 제공합니다. 각 정책이 와일드카드와 Deny를 어떻게 조합하는지 살펴보면, 앞서 배운 원칙들이 실무에 어떻게 적용되는지 알 수 있습니다.

아래 접기 블록에는 네 정책의 JSON이 담겨 있습니다. 주목할 점은 User Admin 정책이 `users:*`로 광범위한 허용을 주면서도, Administrator 삭제만은 명시적으로 Deny하고 있다는 것입니다. "기본은 넓게, 예외는 좁게"라는 설계 원칙의 좋은 예입니다.

<details markdown="1">
<summary>내장 정책 4종 전체 코드 (펼쳐보기)</summary>

**Super Admin** — 모든 것을 허용합니다. 비상 복구용으로만 사용해야 하며, 일상 작업에 쓰면 감사 의미가 사라집니다.
```json
{ "statement": [{ "effect": "Allow", "action": "*", "resource": "*" }] }
```

**User Admin (Help Desk)** — 사용자 관리를 광범위하게 허용하되, Administrator 삭제만 예외로 둡니다.
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

**Auditor (Read-Only)** — 모든 리소스의 조회(List/Read)만 허용합니다. `*:Read` 와일드카드가 핵심입니다.
```json
{ "statement": [{
  "effect": "Allow", "action": ["*:List", "*:Read", "logs:Read"], "resource": "*"
}] }
```

**Viewer (Dashboard Only)** — 대시보드와 도메인 정보 조회만 허용하는 최소 권한 정책입니다.
```json
{ "statement": [{
  "effect": "Allow", "action": ["dashboard:Read", "domain:Read"], "resource": "*"
}] }
```
</details>

이 네 정책을 뒷받침하는 것이 `resource:action` 형식의 작업 분류 체계입니다. 리소스마다 어떤 작업이 정의되어 있는지 한눈에 볼 수 있어, 새 정책을 설계할 때 어느 action을 쓸지 빠르게 결정할 수 있습니다.

<details markdown="1">
<summary>Action 분류 체계 전체 표 (펼쳐보기)</summary>

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

## 마치며

PBAC를 도입하고 나서 가장 크게 달라진 점은, 권한 변경이 더 이상 "개발자에게 부탁하는 일"이 아니라 "정책 파일을 고치는 일"이 되었다는 것입니다. 운영 담당자가 Git에 PR을 올리고, 리뷰어가 확인하고, 머지하면 즉시 반영됩니다. 코드를 재배포할 필요도, 서비스를 재시작할 필요도 없습니다. 이 변화는 단순한 편의를 넘어, 보안 변경 이력이 투명하게 남는다는 감사(audit) 측면의 이점까지 가져다주었습니다.

물론 PBAC가 만능은 아닙니다. 정책 문서가 많아지면 오히려 "이 사용자가 결국 뭘 할 수 있는지" 파악하기 어려워질 수 있고, 와일드카드를 과도하게 쓰면 의도치 않은 권한 확장이 발생할 수 있습니다. 그래서 정기적으로 "유효 권한(effective permission) 검증"을 수행하고, Deny 정책으로 안전망을 항상 걸어두는 습관이 필요합니다. 설계의 자유도가 높아질수록 그에 걸맞은 운영 규율도 따라와야 한다는 것을, 이 프로젝트는 분명하게 가르쳐 주었습니다.

마지막으로 하나 덧붙이자면, 정책 평가에서 Deny는 "즉시 종료"라는 점을 절대 잊지 마시기 바랍니다. Allow가 수백 개 있어도 Deny 하나가 모든 것을 취소합니다. 이 원칙 하나만 기억해도, 대부분의 보안 사고를 코드 한 줄 없이 막을 수 있습니다. 다음 글에서는 이 권한 모델이 외부 시스템과 어떻게 연동하는지 — OAuth2와 OIDC의 인가 흐름 — 를 다룹니다.

---

> **이전 글**: [(1) IAM이란 무엇인가]({% post_url 2026-05-08-IAM-Overview-AuthN-AuthZ-Audit %}) | **다음 글**: [(3) OAuth2 & OIDC]({% post_url 2026-05-10-OAuth2-OIDC-Authorization-Flow %})
