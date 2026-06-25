---
layout: post
title: "[IAM & 보안 (5)] Kerberos & SSO — 비밀번호 없이 인증하는 기술"
categories: [Security, IAM, Infrastructure]
description: "Kerberos 3단계 인증 플로우와 SPNEGO/Negotiate 인증을 설명합니다. 도메인 가입 PC에서 비밀번호 입력 없이 자동 로그인되는 원리를 다룹니다."
keywords: [Kerberos, SSO, SPNEGO, TGT, Active Directory, Negotiate]
toc: true
toc_sticky: true
---

## Hook

사용자가 아침에 PC를 켜고 도메인 계정으로 Windows에 로그인합니다. 그리고 브라우저로 사내 관리 시스템에 접속하면... 비밀번호를 물어보지 않고 바로 대시보드가 나옵니다. 마법이 아닙니다. 이것은 Windows가 로그인 시 이미 받아둔 Kerberos 티켓을 브라우저가 자동으로 사용하기 때문입니다. 네트워크로 비밀번호가 단 한 번도 전송되지 않습니다.

## TL;DR

- **SSO(Single Sign-On)**: 한 번 로그인하면 여러 서비스에 자동 인증
- **Kerberos 3단계**: AS Exchange → TGS Exchange → Client-Server Exchange
- 비밀번호는 네트워크로 **절대 전송되지 않습니다** — KDC가 비밀번호 해시로 티켓을 암호화
- **SPNEGO/Negotiate**: 브라우저가 HTTP 헤더에 Kerberos 티켓을 인코딩하여 전달

> **이전 글**: [(4) MFA & TOTP]({% post_url 2026-05-11-MFA-TOTP-RFC6238 %})

---

## Background: SSO가 없는 세계 vs 있는 세계

```
SSO가 없는 세계 (각 시스템마다 별도 로그인):

  사용자 → 메일: 아이디/비밀번호 ✓
         → 파일공유: 아이디/비밀번호 ✓
         → 웹관리: 아이디/비밀번호 ✓
         → CRM: 아이디/비밀번호 ✓
          
  문제: 매번 비밀번호 입력, 기억해야 할 비밀번호 많음

SSO가 있는 세계 (한 번만 로그인):

  사용자 → [한 번 로그인] → TGT(티켓) 획득
         → 메일: 자동 인증 (티켓 제시)
         → 파일공유: 자동 인증
         → 웹관리: 자동 인증
         → CRM: 자동 인증
          
  장점: 한 번만 로그인, 비밀번호 1개만 기억
```

### Kerberos 주요 용어

| 용어 | 설명 | 비유 |
|------|------|------|
| KDC (Key Distribution Center) | 인증 티켓을 발급하는 서버 | 놀이공원 매표소 |
| TGT (Ticket Granting Ticket) | 서비스 티켓을 받기 위한 마스터 티켓 | 놀이공원 입장권 |
| Service Ticket | 특정 서비스 접근용 티켓 | 놀이기구 탑승권 |
| Principal | 사용자/서비스 식별자 | 회원 번호 |
| Realm | Kerberos 도메인 (= AD 도메인) | EXAMPLE.LOCAL |
| Keytab | 서비스의 비밀키가 저장된 파일 | 서비스 전용 비밀번호 |
| SPN (Service Principal Name) | 서비스를 식별하는 고유 이름 | HTTP/ad-tool.internal |

---

## Solution: Kerberos 3단계 인증 플로우

```
  ┌──────────┐          ┌──────────┐          ┌──────────┐
  │  클라이언트 │          │   KDC    │          │  서비스   │
  │ (사용자 PC)│          │ (AD DC)  │          │(웹 관리)  │
  └────┬─────┘          └────┬─────┘          └────┬─────┘
       │                     │                     │
       │  ┌─── 단계 1: AS (Authentication Service) Exchange ──┐
       │  │ 1. "TGT 주세요"                                     │
       │  │───────────────────▶                                │
       │  │                        2. TGT 발급                   │
       │  │  TGT = KDC비밀키로 암호화된 티켓                      │
       │  │  Session Key (클라이언트-서비스 통신용)               │
       │  │◀───────────────────                                │
       │  └────────────────────────────────────────────────────┘
       │                     │                     │
       │  ┌─── 단계 2: TGS (Ticket Granting Service) Exchange ─┐
       │  │ 3. "이 TGT로 웹관리 서비스 티켓 주세요"              │
       │  │───────────────────▶                                │
       │  │                        4. 서비스 티켓 발급            │
       │  │  Service Ticket = 서비스 비밀키로 암호화               │
       │  │◀───────────────────                                │
       │  └────────────────────────────────────────────────────┘
       │                     │                     │
       │  ┌─── 단계 3: Client-Server Exchange ──────────────────┐
       │  │ 5. 서비스 티켓 제시                                  │
       │  │───────────────────────────────────────────────────▶│
       │  │                                          6. 티켓 검증 │
       │  │                                          (자기 비밀키로)│
       │  │                                          → 인증 성공! │
       │  │◀───────────────────────────────────────────────────│
       │  └────────────────────────────────────────────────────┘
```

**핵심**: 비밀번호는 네트워크로 절대 전송되지 않습니다. KDC는 사용자의 비밀번호 해시로 티켓을 암호화하므로, 올바른 비밀번호를 가진 사용자만 티켓을 복호화할 수 있습니다.

---

## Result: SPNEGO (Negotiate 인증)

브라우저가 Kerberos 티켓을 HTTP 헤더에 인코딩하여 서버에 전달하는 방식입니다.

```
브라우저                         웹 서버
    │                                  │
    │ 1. GET /dashboard                │
    │────────────────────────────────▶│
    │                                  │
    │ 2. 401 Unauthorized              │
    │    WWW-Authenticate: Negotiate   │
    │◀────────────────────────────────│
    │                                  │
    │ 3. KDC에 서비스 티켓 요청         │
    │──────────▶ KDC (AD DC)           │
    │           ◀──────────            │
    │    서비스 티켓 획득               │
    │                                  │
    │ 4. GET /dashboard                │
    │    Authorization: Negotiate      │
    │    <base64 Kerberos 티켓>        │
    │────────────────────────────────▶│
    │                                  │
    │                          5. 티켓 검증
    │                          (keytab + gssapi)
    │                          → 사용자: user@EXAMPLE.LOCAL
    │                                  │
    │ 6. 200 OK + JWT                  │
    │◀────────────────────────────────│
    │                                  │
    │ 로그인 화면 없이 자동 인증!       │
```

### 설정 방법

```bash
# 1. 서비스 주체 이름(SPN) 등록
ad-tool spn add HTTP/ad-tool.internal service_account

# 2. Keytab 추출
ad-tool domain exportkeytab /etc/krb5.keytab \
    --principal=HTTP/ad-tool.internal@EXAMPLE.LOCAL

# 3. 권한 설정
chmod 644 /etc/krb5.keytab

# 4. 환경설정
# KERBEROS_ENABLED=true
# KERBEROS_KEYTAB=/etc/krb5.keytab
# KERBEROS_SPN=HTTP/ad-tool.internal
```

<details markdown="1">
<summary>SSO 방식 비교 및 클라이언트 설정</summary>

| 방식 | 프로토콜 | 특징 | 적용 |
|------|---------|------|------|
| **Kerberos SSO** | Kerberos/SPNEGO | 도메인 가입 PC에서 자동 인증 | 사내망 |
| **OIDC SSO** | OAuth2 + OIDC | 웹 기반, 타 앱에 인증 위임 | 외부 앱 |
| **SAML SSO** | SAML 2.0 | XML 기반, 엔터프라이즈 표준 | 대기업 |

**도메인 가입 PC 클라이언트 설정:**

1. PC를 도메인에 가입 (이미 AD 사용자로 Windows 로그인)
2. 브라우저로 `http://ad-tool.internal` 접속
3. **비밀번호 입력 없이 자동으로 로그인됨**

Windows가 로그인 시 이미 KDC로부터 TGT를 받아두었고, 브라우저가 이 TGT를 사용하여 웹 서비스 티켓을 자동으로 획득하기 때문입니다.

- Windows: 자동 (Internet Explorer / Edge / Chrome)
- Firefox: `about:config` → `network.negotiate-auth.trusted-uris` = `internal`

</details>

---

## Takeaway

1. **비밀번호 없는 인증이 보안의 최고 수준이다** — Kerberos는 비밀번호를 네트워크로 전송하지 않으므로, 패킷 캡처로는 절대 탈취할 수 없습니다. 피싱 공격도 원천 차단됩니다
2. **TGT는 "열쇠 꾸러미"다** — TGT 하나만 있으면 모든 서비스 티켓을 받을 수 있습니다. TGT 만료 전까지는 재인증이 불필요하지만, 반대로 TGT 탈취는 전체 시스템 노출을 의미합니다
3. **SPNEGO는 HTTP 위에서 작동한다** — WebSocket이나 REST API가 아닌, 표준 HTTP `WWW-Authenticate` 헤더를 사용합니다. 기존 인프라를 변경하지 않고도 Kerberos를 도입할 수 있습니다

> **이전 글**: [(4) MFA & TOTP]({% post_url 2026-05-11-MFA-TOTP-RFC6238 %}) | **다음 글**: [(6) JWT 토큰]({% post_url 2026-05-13-JWT-Structure-Signature-Revocation %})
