---
layout: post
title: "[IAM & 보안 (3)] OAuth2 & OIDC — 인가 코드 플로우와 토큰 교환"
categories: [Security, IAM, Infrastructure]
description: "OAuth2 인가 코드 플로우의 전체 과정과 Access Token, Refresh Token, ID Token의 차이를 설명합니다. OIDC Discovery 문서 구조도 다룹니다."
keywords: [OAuth2, OIDC, Authorization Code Flow, Access Token, Refresh Token, SSO]
toc: true
toc_sticky: true
---

## 들어가며

"구글로 로그인" 버튼을 클릭한 순간, 백그라운드에서는 정확히 무슨 일이 일어나는가? 사용자는 구글 비밀번호를 입력했을 뿐인데, 처음 보는 앱은 어떻게 그 사용자가 누구인지 알 수 있을까? 그 사이를 이어주는 보이지 않는 다리가 바로 OAuth2 인가 코드 플로우이며, 이 플로우의 각 단계를 하나씩 분해하면 토큰 보안의 전체 그림이 보입니다.

---

## OAuth2가 풀려는 문제: 위임

OAuth2가 등장하기 전, 제3자 앱이 사용자를 대신해 이메일을 읽으려면 한 가지 방법밖에 없었습니다. 사용자의 비밀번호를 받아 직접 로그인하는 것이었습니다. 이른바 "비밀번호 안티패턴"인데, 앱이 비밀번호를 저장하는 순간 그 앱이 털리면 사용자의 모든 계정이 함께 무너집니다.

OAuth2는 이 문제를 "위임(delegation)"으로 해결합니다. 사용자는 앱에게 비밀번호가 아니라 **제한된 권한을 담은 키**만 넘겨줍니다. 그 키는 정해진 범위(scope)에서만 동작하고, 언제든 철회할 수 있으며, 비밀번호는 오직 인증 서버만 압니다. 이 위임 모델을 이해하려면 먼저 등장하는 주인공들을 알아야 합니다.

---

## 등장인물: OAuth2 주요 용어

플로우를 이야기하기 전에, 그림에 등장하는 다섯 명의 주인공과 그들이 주고받는 두 가지 토큰을 정리하겠습니다. 아래 표를 읽을 때 한 가지에 집중해 주세요. "비밀번호"라는 단어가 어디에도 등장하지 않는다는 점입니다. 이것이 OAuth2가 안전한 이유의 핵심입니다.

| 용어 | 역할 | 이 글의 예시 |
|------|------|-------------|
| Resource Owner | 데이터의 주인 (사용자) | 홍길동 |
| Client | 접근을 원하는 애플리케이션 | "내 앱" |
| Authorization Server | 인가를 결정하고 토큰을 발급 | Google 인증 서버 |
| Resource Server | 보호된 데이터를 들고 있는 서버 | Gmail API |
| Access Token | 접근 권한을 증명하는 단기 키 | `eyJhbGciOi...` |
| Refresh Token | 새 Access Token을 받는 장기 키 | `1//0g-CJ...` |
| Scope | 접근 범위 | `read:user`, `write:repo` |

> 핵심 통찰: Client는 사용자의 비밀번호를 **절대** 만지지 않습니다. Client가 받는 것은 비밀번호가 아니라 "이 범위에서만, 이 시간 동안 유효한 키"입니다. 비밀번호와 키의 분리가 OAuth2 보안 모델의 출발점입니다.

용어를 익혔으니, 이제 이 주인공들이 실제로 어떤 순서로 만나고 무엇을 주고받는지(인가 코드 플로우)를 따라가 보겠습니다.

---

## 인가 코드 플로우: 왜 이 방식인가

OAuth2에는 여러 플로우가 정의되어 있지만, 오늘날 웹과 모바일에서 사실상 표준으로 쓰이는 것은 **인가 코드 플로우(Authorization Code Flow)** 한 가지입니다. 그 이유는 단순히 "안전해서"가 아니라, 한 가지 설계 원칙(토큰이 브라우저를 통과하지 않는다)을 지키기 때문입니다.

이전의 암시적 플로우(Implicit Flow)는 토큰을 브라우저의 URL 프래그먼트로 직접 보냈습니다. 편리했지만, 브라우저 히스토리, 확장 프로그램, 리퍼러 헤더 등을 통해 토큰이 유출될 위험이 컸습니다. 인가 코드 플로우는 이 문제를 두 단계로 나누어 해결합니다. 먼저 브라우저에는 **수명이 짧은 임시 코드**만 전달하고, 그 코드를 **Client 서버가 백채널로 직접 토큰으로 교환**합니다. 토큰은 공개된 브라우저를 한 번도 거치지 않습니다.

아래 다이어그램은 이 열두 단계의 전체 흐름입니다. 관찰할 핵심은 두 가지입니다. 첫째, 6단계까지는 "코드(code)"만 오가고 진짜 토큰은 등장하지 않는다는 점, 둘째, 7~8단계에서 토큰 교환이 Client 서버와 Authorization Server 사이의 **직접 통신**으로 일어난다는 점입니다. 이 이원화가 보안의 핵심입니다.

<img src="/assets/images/posts/oauth2-oidc/01-auth-code-flow.svg" alt="OAuth2 인가 코드 플로우 전체 시퀀스" width="100%" />

> 핵심 통찰: 브라우저에서 Client로 전달되는 단계는 **프론트채널**, Client에서 Auth Server로 토큰 교환이 일어나는 단계는 **백채널**입니다. 코드는 프론트채널을 타지만 수명이 1분 내외라 유출돼도 무의미하고, 토큰은 백채널에서만 오가므로 브라우저에 남지 않습니다. 하나의 흐름을 두 채널로 쪼개는 것이 인가 코드 플로우의 본질입니다.

### `state` 매개변수: 보이지 않는 방패

다이어그램에서 `state` 매개변수를 눈치챘을 것입니다. 단순한 식별자가 아니라 **CSRF 방어**의 핵심입니다. Client는 2단계에서 임의의 난수를 `state`에 담아 보내고, 6단계에서 돌아온 `state`가 같은지 확인합니다. 공격자가 피해자를 꼬아 자신의 인가 코드로 리다이렉트시키려 해도, `state`가 맞지 않으면 요청을 거부합니다.

플로우의 뼈대를 이해했다면, 이제 그 끝에서 얻어지는 토큰 두 종류가 왜 서로 다른 수명을 갖는지 살펴볼 차례입니다.

---

## 토큰의 두 얼굴: Access Token과 Refresh Token

토큰 교환이 끝나면 Client는 두 개의 토큰을 받습니다. 하나는 수명이 짧고, 하나는 깁니다. 이 차이는 우연이 아니라, 유출 시 피해를 최소화하려는 의도된 설계입니다.

### Access Token: 짧은 수명이 곧 보안이다

Access Token은 보호된 리소스에 접근할 때마다 실려 가는 실전용 키입니다. 수명은 보통 **15분에서 1시간**으로 짧게 설계됩니다. 왜 그렇게 짧을까요? 토큰이 탈취되었을 때, 공격자가 그 토큰으로 할 수 있는 일이 짧은 시간 안에 끝나야 하기 때문입니다. Access Token은 보통 JWT 형식이라 한 번 발급되면 서버가 철회하기 어렵습니다. 그래서 수명 자체를 짧게 잡아, 유출되더라도 "잠깐의 위험"으로 끝내는 것입니다.

### Refresh Token: 긴 수명, 그러나 불투명하게

Access Token이 만료되면, 사용자에게 다시 로그인을 시키는 것은 끔찍한 경험입니다. 대신 Refresh Token이 새 Access Token을 조용히 발급합니다. 수명은 **며칠에서 몇 주**로 깁니다. 하지만 여기에 트릭이 있습니다. Refresh Token은 JWT 구조가 아닌 **불투명(opaque)한 랜덤 문자열**이어야 합니다. 왜일까요? JWT는 누구나 내용을 읽을 수 있으므로, Refresh Token이 JWT라면 유출 시 사용자 정보까지 노출됩니다. 반면 불투명 문자열은 서버만 해석할 수 있어, 유출되어도 정보가 빠져나가지 않습니다.

아래는 두 토큰이 실제로 어떻게 협력하는지 보여주는 교환 예시입니다. Access Token이 만료된 직후 Refresh Token이 어떻게 새 토큰을 가져오는지, 그리고 두 요청이 어떻게 다른지에 주목해 주세요.

```bash
# Access Token으로 보호된 API 호출 (15분 후 만료)
curl -H "Authorization: Bearer eyJhbG..." https://api.example.com/v1/users

# 만료 후: Refresh Token으로 갱신 (사용자는 모름)
curl -X POST https://auth.example.com/oauth/token \
  -d "grant_type=refresh_token" \
  -d "refresh_token=1//0g-CJ..." \
  -d "client_id=MY_APP" \
  -d "client_secret=SECRET"
# → 새 Access Token + 새 Refresh Token 반환
```

> 핵심 통찰: Access Token과 Refresh Token은 **서로 다른 위협 모델**에 대응합니다. Access Token은 "자주 쓰이므로 유출 확률이 높다, 그러니 수명을 짧게"로, Refresh Token은 "거의 쓰이지 않으므로 유출 확률이 낮다, 그러니 수명을 길게, 내용은 숨긴다"로 설계되었습니다. 위협에 따라 다르게 방어하는 것이 좋은 보안 설계입니다.

토큰의 수명 설계를 이해했다면, OAuth2가 아직 해결하지 못한 한 가지("사용자가 누구인지")를 짚고 넘어가야 합니다. 그 답이 OIDC입니다.

---

## OIDC: OAuth2에 인증을 더하다

OAuth2는 "접근 권한"을 주는 데 훌륭하지만, 한 가지 치명적인 빈칸이 있습니다. Client가 토큰을 받아도 **사용자가 누구인지는 알 수 없다**는 점입니다. Access Token은 "이 리소스에 접근할 수 있다"고만 말할 뿐, "홍길동님이 맞다"고 증명하지 않습니다. 그래서 예전에는 Client가 Access Token을 들고 별도의 사용자 정보 API를 호출하는 등 야매로 인증을 흉내 냈습니다.

OIDC(OpenID Connect)는 OAuth2 위에 얹히는 **인증 계층**입니다. 핵심은 `scope=openid`를 요청하면, 인가 코드 플로우의 결과로 Access Token과 함께 **ID Token**이 하나 더 내려온다는 것입니다. 이 한 장의 토큰이 사용자의 신원을 서명된 형태로 담고 있어, 별도 API 호출 없이 사용자를 인증할 수 있습니다.

아래 표는 OAuth2와 OIDC의 차이를 한눈에 보여줍니다. 가장 중요한 행은 "사용자 정보"입니다. OAuth2는 별도 API 호출이 필요하지만, OIDC는 ID Token 자체에 포함된다는 점이 실무에서 얼마나 큰 차이인지 생각해 보세요.

| 구분 | OAuth2 | OIDC |
|------|--------|------|
| 목적 | 인가 (Authorization) | 인증 + 인가 |
| 반환 토큰 | Access Token | ID Token + Access Token |
| 사용자 정보 | 별도 API 호출 필요 | ID Token에 포함 |
| 요청 scope | `read:user` 등 | `openid` 포함 |
| 표준 | RFC 6749 | OpenID Connect Core 1.0 |

> 핵심 통찰: OIDC는 OAuth2를 **대체**하는 것이 아니라 **위에 얹는** 것입니다. 인가 코드 플로우는 그대로 따르되, `openid` 스코프 하나를 추가하고 그 결과로 ID Token을 받는 차이입니다. 기존 OAuth2 시스템에 최소한의 변경만으로 인증을 얹을 수 있는 것이 OIDC가 널리 퍼진 이유입니다.

OIDC가 무엇을 추가하는지 알았으니, 이제 그 핵심 산물인 ID Token의 내부 구조를 들여다보겠습니다.

---

## ID Token의 구조: 서명된 신원 증명서

ID Token은 JWT 형식으로, 세 부분(헤더·페이로드·서명)으로 이루어집니다. 그중 페이로드에 담긴 클레임(claim)들이 사용자의 신원을 말해줍니다. 아래 JSON은 실제 ID Token의 페이로드 예시입니다. 읽으면서 두 그룹의 클레임을 구분해 주세요. 표준 클레임(`iss`, `sub`, `aud`, `exp`, `iat`)과, 그 아래 사용자 정보 클레임(`email`, `name`, `groups`)입니다.

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

각 표준 클레임이 왜 필요한지가 ID Token 검증의 핵심입니다. `iss`(발급자)는 "누가 서명했는가"를, `aud`(수신자)는 "이 토큰이 우리 앱을 위한 것이 맞는가"를, `exp`(만료 시각)는 "아직 유효한가"를 각각 검증합니다. 이 세 가지만 꼼꼼히 확인해도, 재전송 공격과 토큰 오용의 대부분을 막을 수 있습니다.

> 핵심 통찰: ID Token의 진짜 가치는 "내용을 읽을 수 있다"가 아니라 **"서명으로 위변조를 잡을 수 있다"**는 점입니다. 악의자가 `role`을 `super_admin`으로 바꿔치기해도, 서명이 맞지 않아 즉시 거부됩니다. 신뢰는 내용이 아니라 서명에서 옵니다.

ID Token을 검증하려면 발급자의 공개키가 필요합니다. 그리고 그 공개키의 위치를 알려주는 것이 바로 다음에 볼 Discovery 문서입니다.

---

## Discovery 문서: 자동 연동의 기반

OIDC Provider를 새 앱에 연동할 때, 예전에는 인가 엔드포인트 URL, 토큰 엔드포인트 URL, 공개키 위치를 하나하나 문서에서 찾아 설정 파일에 적었습니다. Provider가 바뀔 때마다, 버전이 올라갈 때마다 이 작업을 반복했습니다. OIDC Discovery는 이 수동 작업을 끝냅니다.

표준화된 단일 URL(`/.well-known/openid-configuration`)에 접속하면, Provider가 지원하는 모든 엔드포인트와 공개키 위치, 알고리즘이 JSON으로 내려옵니다. Client는 이 문서 하나만 읽으면 모든 설정을 자동으로 발견합니다. 아래는 그 문서의 예시입니다. 읽으면서 각 필드가 앞서 본 흐름의 어디와 연결되는지 매핑해 보세요. `authorization_endpoint`는 플로우의 2단계, `token_endpoint`는 7단계, `jwks_uri`는 ID Token 서명 검증에 쓰입니다.

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

Discovery가 알려주는 엔드포인트들이 각자 어떤 역할을 하는지 정리하면 아래와 같습니다. 각 엔드포인트가 흐름의 어느 단계에 쓰이는지 함께 표시했으니, 위 시퀀스 다이어그램과 대응시켜 보시기 바랍니다.

| 엔드포인트 | 메서드 | 역할 | 플로우 단계 |
|-----------|--------|------|-----------|
| `/.well-known/openid-configuration` | GET | 검색 문서 (모든 URL + 공개키) | 연동 시작 |
| `/oauth/authorize` | GET | 인가 엔드포인트 (로그인 + 동의) | 2~6단계 |
| `/oauth/token` | POST | 토큰 교환 | 7단계 |
| `/oauth/userinfo` | GET | 사용자 정보 (ID Token 보충용) | 토큰 획득 후 |
| `/oauth/certs` | GET | JWKS (토큰 검증용 공개키) | ID Token 검증 |

> 핵심 통찰: Discovery 문서는 단순한 편의 기능이 아니라 **"수동 설정 URL 나열"을 구식으로 만든 설계 결정**입니다. Provider가 변경되거나 공개키가 회전(key rotation)되어도, Client는 코드를 고칠 필요 없이 이 문서를 다시 읽기만 하면 됩니다. 자동 발견 가능성(discoverability)이야말로 OIDC가 표준으로 자리 잡은 실질적 이유입니다.

이제 모든 조각(플로우, 토큰, ID Token, Discovery)이 갖춰졌습니다. 마지막으로 이것들이 실제 외부 앱 SSO 시나리오에서 어떻게 하나로 맞물려 돌아가는지 확인하겠습니다.

---

## 실전: 외부 앱 SSO 시나리오

지금까지 배운 요소들이 실제 환경에서 어떻게 협력하는지, 사내 인증 서버를 OIDC Provider로 삼아 외부 모니터링 앱에 SSO를 연동하는 시나리오로 마무리하겠습니다. 아래 흐름에서 특히 주목할 점은 7단계입니다. 외부 앱이 ID Token을 받은 직후, 자체 비밀번호 검증 없이 **공개키로 서명만 검증**하여 사용자를 인증합니다. 외부 앱은 사용자 비밀번호를 한 번도 만지지 않습니다.

이 시나리오는 위에서 본 인가 코드 플로우와 구조가 같지만, 한 가지 결정적 차이가 있습니다. 외부 앱이 `scope=openid`를 포함하여 요청하면, 토큰 교환 결과로 Access Token과 함께 **ID Token**이 내려옵니다. 외부 앱은 이 ID Token의 서명을 공개키로 검증하는 것만으로 사용자를 인증합니다.

```
외부 모니터링 앱 → 인증 서버 (OIDC Provider)
  1. 인가 요청: scope=openid+profile (← openid가 OIDC 활성화 키)
  2. 로그인 화면 → 사용자 LDAP 인증
  3. Authorization Code 발급 (임시 코드)
  4. 토큰 교환: POST /oauth/token (백채널)
  5. ID Token + Access Token 반환
  6. ID Token 검증 (공개키로 서명 확인: iss, aud, exp)
     → 사용자 인증 완료! 비밀번호 검증 불필요
  7. Access Token으로 API 호출
```

외부 앱은 사용자 비밀번호를 알 필요 없이, 인증 서버가 발급하고 서명한 ID Token으로 사용자를 인증합니다. 신뢰의 부담이 외부 앱에서 인증 서버로 옮겨갔고, 이것이 **SSO(Single Sign-On)**의 본질입니다. 한 번 로그인으로 여러 앱에 신원이 전파되되, 각 앱은 비밀번호를 절대 다루지 않습니다.

---

## 마치며

이 글을 쓰면서 다시 한번 느낀 것은, OAuth2와 OIDC의 아름다움이 "복잡함"이 아니라 **"채널의 분리"**에 있다는 점입니다. 인가 코드 플로우는 단일한 흐름을 브라우저가 지나는 프론트채널과 서버끼리만 통신하는 백채널로 쪼개버립니다. 그 결과 토큰은 공개된 브라우저에 한 번도 노출되지 않고, 임시 코드만 노출되며, 그 코드마저 1분이면 죽습니다. 보안이 "더 많은 암호화"가 아니라 "정보의 경로를 설계하는 일"이라는 사실을 이 플로우는 여실히 보여줍니다.

그리고 Access Token과 Refresh Token의 수명 차이는, 좋은 보안 설계가 결국 **위협 모델에 대한 대응**이라는 교훈을 줍니다. Access Token은 자주 쓰여 유출 위험이 크니 짧게, Refresh Token은 드물게 쓰여 위험이 작으니 길되 내용은 숨깁니다. 같은 "토큰"이라는 이름 아래 각자 다른 위협에 다른 방어를 적용하는 것입니다. 이 원칙은 토큰을 넘어, 인프라의 모든 비밀값 설계(API 키, 서비스 계정, 임시 자격 증명)에 그대로 적용됩니다.

마지막으로 하나 덧붙이자면, OIDC Discovery 문서가 보여주는 **자동 발견 가능성**의 철학을 잊지 않기를 바랍니다. 수동으로 URL을 설정 파일에 적던 시대는 끝났습니다. Provider가 바뀌어도, 공개키가 회전되어도, Client는 `/.well-known/openid-configuration` 하나를 다시 읽을 뿐입니다. "연동의 어려움"을 표준화된 발견 메커니즘으로 녹여낸 이 접근은, 다음 글에서 다룰 MFA와 TOTP가 신뢰를 강화하는 방식과도 맥이 닿습니다. 보안의 본질은 결국 "어떻게 신뢰를 설정하고, 그 신뢰를 검증 가능하게 유지하는가"에 있습니다.

---

> **이전 글**: [(2) PBAC vs RBAC]({% post_url 2026-06-19-PBAC-vs-RBAC-Policy-Engine %}) | **다음 글**: [(4) MFA & TOTP]({% post_url 2026-06-21-MFA-TOTP-RFC6238 %})
