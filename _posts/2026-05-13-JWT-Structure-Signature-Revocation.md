---
layout: post
title: "[IAM & 보안 (6)] JWT 토큰 — 구조, 서명, 그리고 철회의 어려움"
categories: [Security, IAM, Infrastructure]
description: "JWT의 3부분 구조와 서명 알고리즘(HS256 vs RS256), JWT vs 세션의 차이, Refresh Token Rotation으로 철회 문제를 해결하는 방법을 설명합니다."
keywords: [JWT, JSON Web Token, HS256, RS256, Refresh Token, Token Revocation]
toc: true
toc_sticky: true
---

## Hook

JWT는 한 번 발급되면 만료될 때까지 유효합니다. "로그아웃" 버튼을 눌러도 서버에서 토큰을 무효화할 수 없습니다. 사용자가 비밀번호를 바꿔도, 관리자가 계정을 비활성화해도, 기존 토큰은 여전히 작동합니다. 이것이 JWT의 가장 큰 약점이자, 설계자가 반드시 해결해야 할 문제입니다.

## TL;DR

- JWT는 **Header.Payload.Signature** 3부분으로 구성됩니다
- **HS256**(대칭키)은 내부용, **RS256**(비대칭키)은 OIDC/외부 앱용
- JWT vs 세션: JWT는 stateless하지만 **철회가 어렵다**
- **Refresh Token Rotation**으로 철회 문제를 해결합니다

> **이전 글**: [(5) Kerberos & SSO]({% post_url 2026-05-12-Kerberos-SSO-SPNEGO %})

---

## Background: JWT의 구조

JWT는 점(`.`)으로 구분된 3개 부분으로 구성됩니다:

```
xxxxx.yyyyy.zzzzz
 │                 │                 │
 │                 │                 └─ Signature (서명)
 │                 │                    토큰이 변조되지 않았음을 증명
 │                 │
 │                 └─── Payload (페이로드)
 │                      사용자 정보 + 권한 + 만료 시간
 │
 └───────── Header (헤더)
             토큰 타입 + 서명 알고리즘
```

### 각 부분 디코딩

```json
// 1. Header
{ "alg": "HS256", "typ": "JWT" }

// 2. Payload
{
  "sub": "Administrator",
  "iat": 1781778642,          // 발급 시간
  "exp": 1781807442,          // 만료 시간 (8시간 후)
  "display_name": "Administrator",
  "role": "admin",
  "groups": ["Domain Admins", "Administrators"],
  "mfa_verified": true         // MFA 완료 여부
}

// 3. Signature
HMAC-SHA256(
  base64(header) + "." + base64(payload),
  secret_key
) = IEMU52xsyEtri_1mMG4PdQL9oq1x6YanwX1xrL4gOzA
```

### 서명 알고리즘

| 알고리즘 | 방식 | 키 | 용도 |
|---------|------|----|------|
| `HS256` | 대칭키 (HMAC) | 서버 비밀키 1개 | 내부 API |
| `RS256` | 비대칭키 (RSA) | 개인키(서명) + 공개키(검증) | OIDC, 외부 앱 |
| `ES256` | 타원곡선 (ECDSA) | 개인키 + 공개키 | 모바일, IoT |

---

## Solution: JWT vs 세션

| 특징 | 세션 (Session) | JWT (토큰) |
|------|---------------|------------|
| 저장 위치 | 서버 메모리/DB | 클라이언트 |
| 검증 방법 | 서버에 조회 | 서명 검증만 (조회 불필요) |
| 확장성 | 서버 간 세션 공유 필요 (Redis) | Stateless — 어느 서버든 검증 |
| 철회 | 서버에서 세션 삭제 → 즉시 | 어려움 (만료까지 대기 또는 블랙리스트) |
| 크기 | 작음 (세션 ID) | 큼 (JSON 데이터 포함) |

### JWT 인증 플로우

```
  클라이언트                         서버
     │                              │
     │ 1. POST /auth/login          │
     │    {username, password}      │
     │─────────────────────────────▶│
     │                              │
     │                    2. LDAP bind 인증
     │                    3. JWT 생성 (secret_key로 서명)
     │                              │
     │ 4. JWT 반환                  │
     │◀─────────────────────────────│
     │                              │
     │ 5. localStorage에 저장       │
     │    또는 HttpOnly 쿠키        │
     │                              │
     │ 6. 모든 API 요청에 헤더 포함 │
     │    GET /api/v1/users         │
     │    Authorization: Bearer eyJ │
     │─────────────────────────────▶│
     │                              │
     │                    7. JWT 검증
     │                    · 서명 확인
     │                    · 만료 시간 확인
     │                    · 권한 확인 (PBAC)
     │                              │
     │ 8. 200 OK + 데이터           │
     │◀─────────────────────────────│
```

---

## Result: Refresh Token Rotation으로 철회 해결

JWT의 단점 — 철회가 어렵다 — 를 해결하기 위해 **Access Token(15분) + Refresh Token(7일)** 이원화 전략을 사용합니다.

```
  Refresh Token Rotation (회전):

  시간 T0:     RT-1 발급
  시간 T0+15m: Access Token 만료
               → RT-1로 갱신 요청
               → RT-1 폐기, RT-2 발급 + 새 Access Token
  
  시간 T0+30m: Access Token 만료
               → RT-2로 갱신 요청
               → RT-2 폐기, RT-3 발급 + 새 Access Token
  
  만약 해커가 RT-1을 가로챈다면:
  → RT-1로 갱신 시도 → 이미 폐기됨 → 거부
  → 정당한 사용자의 RT-2도 폐기 (재사용 감지) → 강제 재로그인
```

### 개선된 토큰 정책

```yaml
Access Token:
  alg: HS256 (내부) / RS256 (OIDC)
  expiry: 15분
  claims: sub, role, groups, mfa_verified, permissions

Refresh Token:
  type: 불투명 문자열 (JWT 아님)
  expiry: 7일
  rotation: 사용 시마다 새 토큰 발급 (이전 토큰 폐기)
  storage: DB refresh_tokens 테이블
  revoke: 로그아웃 시 폐기

로그아웃:
  → Refresh Token 폐기
  → Access Token은 15분 후 자연 만료
```

<details markdown="1">
<summary>JWT 보안 주의사항 5가지</summary>

1. **민감한 정보 넣지 않기**: Payload는 Base64 인코딩일 뿐, 암호화가 아닙니다. 누구나 디코딩 가능
2. **HTTPS 필수**: 토큰이 가로채이지 않도록 항상 HTTPS 사용
3. **짧은 만료 시간**: Access Token은 15분 이내
4. **비밀키 안전 보관**: 환경변수로 관리, 코드에 하드코딩 금지
5. **alg: "none" 공격 주의**: 서명 없는 토큰 거부 (라이브러리가 처리)

</details>

---

## Takeaway

1. **JWT Payload는 암호화가 아니다** — Base64 인코딩일 뿐이므로 누구나 디코딩할 수 있습니다. 주민등록번호, 비밀번호 힌트 등 민감 정보를 절대 넣으면 안 됩니다
2. **Refresh Token Rotation은 "재사용 감지"를 제공한다** — 폐기된 토큰이 사용되면, 현재 유효한 토큰까지 폐기하여 강제 재로그인을 유도합니다. 이것이 토큰 탈취에 대한 실시간 대응입니다
3. **로그아웃은 "15분 보안 창"이다** — Refresh Token을 폐기해도 Access Token은 15분간 유효합니다. 즉시 철회가 필요하다면 블랙리스트(Redis)를 도입해야 하지만, 대부분의 경우 15분 창이 허용 가능한 트레이드오프입니다

> **이전 글**: [(5) Kerberos & SSO]({% post_url 2026-05-12-Kerberos-SSO-SPNEGO %}) | **처음으로**: [(1) IAM이란 무엇인가]({% post_url 2026-05-08-IAM-Overview-AuthN-AuthZ-Audit %})
