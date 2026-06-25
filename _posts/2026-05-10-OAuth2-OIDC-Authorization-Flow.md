---
layout: post
title: "[IAM & 보안 (3)] OAuth2 & OIDC — 인가 코드 플로우와 토큰 교환"
categories: [Security, IAM, Infrastructure]
description: "OAuth2 인가 코드 플로우의 전체 과정과 Access Token, Refresh Token, ID Token의 차이를 설명합니다. OIDC Discovery 문서 구조도 다룹니다."
keywords: [OAuth2, OIDC, Authorization Code Flow, Access Token, Refresh Token, SSO]
toc: true
toc_sticky: true
---

## Hook

"구글로 로그인" 버튼을 클릭한 후, 백그라운드에서는 정확히 무슨 일이 일어날까요? 사용자는 비밀번호를 입력하지 않았는데, 앱은 사용자가 누구인지 어떻게 알 수 있을까요? 정답은 OAuth2 인가 코드 플로우입니다. 그리고 그 플로우의 각 단계를 이해하면 토큰 보안의 모든 것이 보입니다.

## TL;DR

- **OAuth2**는 "인가" 프로토콜 — "이 앱이 네 데이터에 접근할 수 있게 허락해줄래?"
- **OIDC**는 OAuth2 위에 "인증"을 추가 — "너가 누구인지 증명해줄래?"
- **인가 코드 플로우**: 사용자 동의 → 임시 코드 발급 → 코드를 토큰으로 교환
- **Access Token**은 15분, **Refresh Token**은 7일 — 짧은 수명이 보안의 핵심

> **이전 글**: [(2) PBAC vs RBAC]({% post_url 2026-05-09-PBAC-vs-RBAC-Policy-Engine %})

---

## Background: OAuth2 주요 용어

| 용어 | 설명 | 예시 |
|------|------|------|
| Resource Owner | 데이터의 주인 (사용자) | 홍길동 |
| Client | 접근을 원하는 애플리케이션 | "내 앱" |
| Authorization Server | 인가를 결정하는 서버 | Google 인증 서버 |
| Resource Server | 보호된 데이터가 있는 서버 | Gmail API |
| Access Token | 접근 권한을 증명하는 토큰 | `eyJhbGciOi...` |
| Refresh Token | 새 Access Token을 받는 토큰 | `1//0g-CJ...` |
| Scope | 접근 범위 | `read:user`, `write:repo` |

---

## Solution: 인가 코드 플로우

가장 안전하고 널리 사용되는 플로우입니다.

```
  ┌──────────┐                   ┌──────────┐              ┌──────────┐
  │  사용자   │                   │  Client   │              │  Auth    │
  │ (브라우저)│                   │  (내 앱)   │              │  Server  │
  └────┬─────┘                   └────┬─────┘              └────┬─────┘
       │                              │                         │
       │ 1. "로그인" 클릭              │                         │
       │─────────────────────────────▶│                         │
       │                              │                         │
       │ 2. 인가 페이지로 리다이렉트    │                         │
       │   (client_id, scope, redirect_uri)                      │
       │◀─────────────────────────────│                         │
       │                              │                         │
       │ 3. 인가 페이지 표시 + 로그인  │                         │
       │───────────────────────────────────────────────────────▶│
       │                              │                         │
       │ 4. "허용하시겠습니까?" (동의 화면)                      │
       │◀───────────────────────────────────────────────────────│
       │                              │                         │
       │ 5. 동의                       │                         │
       │───────────────────────────────────────────────────────▶│
       │                              │                         │
       │ 6. redirect_uri로 코드 전달   │                         │
       │   ?code=A1b2c3&state=xyz     │                         │
       │─────────────────────────────▶│                         │
       │                              │                         │
       │                              │ 7. 코드 → 토큰 교환       │
       │                              │   POST /token            │
       │                              │   {code, client_secret}  │
       │                              │────────────────────────▶│
       │                              │                         │
       │                              │ 8. Access + Refresh Token│
       │                              │◀────────────────────────│
       │                              │                         │
       │                              │ 9. API 호출              │
       │                              │   Authorization: Bearer  │
       │                              │────────────────────────▶│
       │                              │                         │
       │                              │ 10. 보호된 데이터 반환    │
       │                              │◀────────────────────────│
       │ 11. 로그인 완료               │                         │
       │◀─────────────────────────────│                         │
```

### 토큰 교환 코드

```bash
# Access Token (JWT 형식 — 15분 만료)
curl -H "Authorization: Bearer eyJhbG..." /api/v1/users

# 만료 후 Refresh Token으로 갱신
POST /oauth/token
{ "grant_type": "refresh_token", "refresh_token": "1//0g-CJ..." }
→ 새 Access Token 반환
```

---

## Result: OIDC (OpenID Connect)

OAuth2만으로는 부족합니다. OAuth2는 "접근 권한"을 주지만 "사용자가 누구인지"는 알려주지 않습니다. OIDC는 OAuth2에 **ID Token**을 추가하여 인증을 제공합니다.

| 구분 | OAuth2 | OIDC |
|------|--------|------|
| 목적 | 인가 (Authorization) | 인증 + 인가 |
| 반환 토큰 | Access Token | ID Token + Access Token |
| 사용자 정보 | 별도 API 호출 필요 | ID Token에 포함 |
| 표준 | RFC 6749 | OpenID Connect Core 1.0 |

### ID Token 구조

```json
{
  "iss": "https://ad-tool.internal",
  "sub": "S-1-5-21-xxx",
  "aud": "external-app-client-id",
  "exp": 1718889000,
  "iat": 1718888100,
  "email": "user@example.local",
  "name": "홍길동",
  "groups": ["Domain Admins", "Help Desk"],
  "role": "super_admin"
}
```

### OIDC 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/.well-known/openid-configuration` | GET | 검색 문서 (모든 URL + 공개키) |
| `/oauth/authorize` | GET | 인가 엔드포인트 (로그인 + 동의) |
| `/oauth/token` | POST | 토큰 교환 |
| `/oauth/userinfo` | GET | 사용자 정보 |
| `/oauth/certs` | GET | JWKS (토큰 검증용 공개키) |

### Discovery 문서

```json
{
  "issuer": "https://ad-tool.internal",
  "authorization_endpoint": "https://ad-tool.internal/oauth/authorize",
  "token_endpoint": "https://ad-tool.internal/oauth/token",
  "userinfo_endpoint": "https://ad-tool.internal/oauth/userinfo",
  "jwks_uri": "https://ad-tool.internal/oauth/certs",
  "response_types_supported": ["code", "token", "id_token"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "id_token_signing_alg_values_supported": ["RS256"],
  "scopes_supported": ["openid", "profile", "email", "groups"]
}
```

<details markdown="1">
<summary>외부 앱 SSO 시나리오 전체 플로우</summary>

```
외부 모니터링 앱              인증 서버 (OIDC Provider)
    │                                     │
    │  1. 인가 요청                         │
    │  GET /oauth/authorize?              │
    │    client_id=monitor&               │
    │    redirect_uri=...&                 │
    │    scope=openid+profile              │
    │────────────────────────────────────▶│
    │                                     │
    │  2. 로그인 화면                       │
    │◀────────────────────────────────────│
    │                                     │
    │  3. 사용자 인증 (LDAP)               │
    │────────────────────────────────────▶│
    │                                     │
    │  4. Authorization Code              │
    │◀────────────────────────────────────│
    │                                     │
    │  5. 토큰 교환                         │
    │  POST /oauth/token                  │
    │────────────────────────────────────▶│
    │                                     │
    │  6. ID Token + Access Token         │
    │◀────────────────────────────────────│
    │                                     │
    │  7. ID Token 검증 (공개키로)          │
    │     → 사용자 확인 완료!               │
```

외부 앱은 사용자 비밀번호를 알 필요 없이, 인증 서버가 발급한 ID Token으로 사용자를 인증합니다. 이것이 **SSO(Single Sign-On)**의 핵심입니다.

</details>

---

## Takeaway

1. **인가 코드 플로우에서 토큰은 브라우저를 거치지 않는다** — 코드(임시)는 브라우저→Client로, 토큰은 Client→Auth Server 직접 통신으로 받습니다. 이원화가 보안의 핵심입니다
2. **Refresh Token은 불투명(opaque) 문자열이어야 한다** — JWT 구조가 아니라 서버만 해석할 수 있는 랜덤 문자열이어야, 유출되어도 정보가 노출되지 않습니다
3. **OIDC Discovery 문서는 "자동 연동"의 기반** — `/.well-known/openid-configuration` 하나로 외부 앱이 모든 엔드포인트를 자동 발견합니다. 수동 설정 URL 나열은 구식입니다

> **이전 글**: [(2) PBAC vs RBAC]({% post_url 2026-05-09-PBAC-vs-RBAC-Policy-Engine %}) | **다음 글**: [(4) MFA & TOTP]({% post_url 2026-05-11-MFA-TOTP-RFC6238 %})
