---
layout: post
title: "Cloudflare Pages OAuth 로그인 — 9번의 실패와 교훈"
categories: [Cloudflare, OAuth]
description: Cloudflare Pages에서 Google·Kakao OAuth 로그인을 구현하며 겪은 9건의 이슈와 해결 과정을 공유합니다.
keywords: [Cloudflare, OAuth, Google, Kakao, JWT, 트러블슈팅]
toc: true
toc_sticky: true
---

## Hook

OAuth 로그인을 붙이려다 보니 302 리다이렉트, 쿠키 누락, 한글 깨짐, 아키텍처 변경까지 — 총 9번의 삽질 끝에 찾은 정답입니다.

## TL;DR

- **302 + Set-Cookie는 Pages에서 불안정** → 200 HTML + JS 리다이렉트로 대체합니다
- **다중 Set-Cookie는 `Headers.append()` 필수** → 생성자는 쉼표로 병합합니다
- **SPA에서는 localStorage가 쿠키보다 안정적** → Pages Functions의 쿠키 처리 한계 때문입니다
- **Secrets는 Dashboard 등록 후 재배포 필수** → env가 즉시 반영되지 않습니다
- **프론트엔드와 API는 같은 도메인에** → Pages Functions로 통합합니다

## 인증 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│               my-app.pages.dev (Cloudflare Pages)         │
│                                                           │
│  index.html (SPA)        functions/api/auth/[[route]].js  │
│  ┌────────────────┐      ┌────────────────────────────┐   │
│  │  loginGoogle() │─────▶│  GET /api/auth/google      │   │
│  │  loginKakao()  │─────▶│  GET /api/auth/kakao       │   │
│  │                │◀─────│  GET /api/auth/*/callback   │   │
│  │  localStorage  │      │    → 200 HTML 응답          │   │
│  │  user, token   │      │    → JS localStorage 저장   │   │
│  └────────────────┘      │    → /?auth=success 이동    │   │
│                          │  JWT HMAC-SHA256            │   │
│                          │  D1: users, sessions        │   │
│                          └────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

1. SPA에서 Google/Kakao 로그인 버튼 클릭 → Pages Function이 OAuth Provider로 리다이렉트합니다
2. Provider 인증 완료 → Callback Function이 D1에 사용자를 저장하고 JWT를 생성합니다
3. 200 HTML 응답에 사용자 정보를 포함해 반환 → JS가 localStorage에 저장합니다
4. 이후 API 요청 시 `Authorization: Bearer <JWT>` 헤더를 사용합니다

## 이슈 요약표

| # | 이슈 | 원인 | 해결 |
|---|------|------|------|
| 1 | Set-Cookie 다중 값 병합 | `Headers` 생성자 동일 키 병합 | `Headers.append()` 사용 |
| 2 | 302에서 Set-Cookie 누락 | CDN 프록시 쿠키 제거 | 200 HTML + JS 리다이렉트 |
| 3 | 쿠키 방식 전면 실패 | Pages Functions 쿠키 불안정 | localStorage 직접 저장 |
| 4 | 로그인 후 수동 새로고침 필요 | `init()` auth 파라미터 미확인 | URL 파라미터 우선 체크 |
| 5 | 한글 이름 깨짐 | 이중 encodeURIComponent | JSON↔URI 인코딩 체인 정리 |
| 6 | D1 바인딩 인식 불가 | wrangler.toml 설정 누락 | `[[d1_databases]]` 추가 |
| 7 | Secrets 접근 불가 | Dashboard Encrypt 등록 필요 | Dashboard 등록 후 재배포 |
| 8 | Worker → Pages Functions 이관 | 크로스 도메인 CORS·SameSite | Pages Functions로 통합 |
| 9 | render() 빈 문자열 덮어쓰기 | 재귀 render 후 return '' | 반환값 체크 후 innerHTML |

## Issue #1: Set-Cookie 다중 값이 단일 헤더로 병합됨

**현상**: 두 개의 쿠키를 설정했으나 브라우저에는 하나만 도달합니다.
**원인**: `new Headers({})` 생성자가 동일 키를 쉼표로 병합합니다.
**해결**: `Headers.append()`를 사용하면 개별 엔트리로 추가됩니다.

```js
const headers = new Headers();
headers.append('Set-Cookie', 'access_token=xxx; Path=/; HttpOnly; SameSite=Lax');
headers.append('Set-Cookie', 'refresh_token=yyy; Path=/; HttpOnly; SameSite=Lax');
```

## Issue #2: 302 리다이렉트에서 Set-Cookie 누락

**현상**: 302 응답의 `Set-Cookie`가 브라우저에 도달하지 않습니다.
**원인**: Cloudflare CDN 프록시가 302 응답의 쿠키를 제거합니다.
**해결**: 200 상태 코드로 HTML을 반환하고 JS로 리다이렉트합니다.

```js
return new Response(`<!DOCTYPE html><html><body>
<script>window.location.href = '/?auth=success';</script>
<p>로그인 중...</p></body></html>`, {
  status: 200,
  headers: { 'Content-Type': 'text/html; charset=utf-8' },
});
```

## Issue #3: 쿠키 방식 전면 폐기 → localStorage 직접 저장

**현상**: HttpOnly 쿠키는 SPA에서 읽을 수 없고, Pages Functions의 쿠키 읽기도 간헐적입니다.
**원인**: Pages Functions Edge Runtime의 쿠키 처리에 복합적 한계가 있습니다.
**해결**: 쿠키를 포기하고 콜백 HTML에서 localStorage에 직접 저장합니다.

```js
const userData = encodeURIComponent(JSON.stringify({
  id: user.id, name: user.name, email: user.email, provider: 'google',
}));
const html = `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
var u = JSON.parse(decodeURIComponent('${userData}'));
localStorage.setItem('user', JSON.stringify(u));
window.location.href = '/?auth=success';
</script></body></html>`;
return new Response(html, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
```

## Issue #4: OAuth 로그인 후 수동 새로고침 필요

**현상**: `/?auth=success` 리다이렉트 후 랜딩 페이지가 표시되어 F5를 눌러야 합니다.
**원인**: `init()`가 `auth` 파라미터를 확인하기 전에 렌더링을 완료해버립니다.
**해결**: `init()` 최상단에서 URL 파라미터를 먼저 확인합니다.

```js
function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('auth') === 'success') {
    currentPage = 'login';
    render();
    return;
  }
  render();
}
```

## Issue #5: 한글 이름 깨짐 (Mojibake)

**현상**: Google 계정의 한글 이름이 깨져서 저장됩니다.
**원인**: `encodeURIComponent` 이중 인코딩으로 UTF-8 처리가 어긋납니다.
**해결**: JSON → encodeURIComponent → 전송 → decodeURIComponent → JSON.parse 체인을 일관되게 적용합니다.

```js
const userData = encodeURIComponent(JSON.stringify({ name: user.name }));
// HTML에 삽입: var u = JSON.parse(decodeURIComponent('${userData}'));
```

## Issue #6: D1 바인딩 인식 불가

**현상**: `env.DB`가 `undefined`이며 `Cannot read properties of undefined` 에러가 발생합니다.
**원인**: Pages Functions는 Worker와 달리 `wrangler.toml`에 명시적 D1 바인딩이 필요합니다.
**해결**: `wrangler.toml`에 바인딩을 추가합니다.

```toml
[[d1_databases]]
binding = "DB"
database_name = "my-app-db"
database_id = "your-db-id"
```

## Issue #7: Secrets 환경변수 접근 불가

**현상**: `env.JWT_SECRET`, `env.GOOGLE_CLIENT_SECRET`이 `undefined`입니다.
**원인**: Secrets는 `wrangler.toml [vars]`가 아닌 Dashboard에서 암호화 등록해야 합니다.
**해결**: Dashboard에서 Encrypt 옵션으로 등록 후 **재배포**합니다.

```bash
wrangler pages secret put JWT_SECRET --project-name my-app
wrangler pages secret put GOOGLE_CLIENT_SECRET --project-name my-app
```

> Secrets 변경 후 기존 배포에는 자동 반영되지 않습니다. 재배포가 필수입니다.

## 아키텍처 이관 이야기 (Issue #8)

이것이 가장 극적인 삽질이었습니다. 처음에는 인증 API를 별도 Worker(`my-api.workers.dev`)에 배포했습니다. 프론트엔드(`my-app.pages.dev`)와 도메인이 다르니 **CORS 에러**가 발생하고, 쿠키는 **SameSite 정책**에 막히고, OAuth Redirect URI는 **두 도메인을 관리**해야 하고 — 하나를 고치면 다른 게 터지는 악순환이었습니다.

결국 전부 갈아엎고 **Pages Functions**로 통합했습니다.

```
Before:  my-app.pages.dev → my-api.workers.dev (CORS, SameSite, 이중 배포)
After:   my-app.pages.dev/api/* (동일 도메인, CORS 불필요)
```

```
my-app/
├── index.html
└── functions/
    └── api/
        └── auth/
            └── [[route]].js
```

이관 후 CORS, 쿠키, 배포 복잡성 문제가 모두 해결되었습니다.

## Issue #9: render() 빈 문자열 덮어쓰기

**현상**: OAuth 로그인 완료 후 빈 화면이 표시됩니다.
**원인**: `renderLogin()`이 내부에서 `render()`를 호출한 뒤 `return ''` → 바깥 `render()`가 빈 문자열로 innerHTML을 덮어씁니다.
**해결**: 반환값을 체크해 빈 문자열이면 innerHTML 대입을 스킵합니다.

```js
function render() {
  let html = '';
  switch (currentPage) {
    case 'login': html = renderLogin(); break;
  }
  if (html) document.getElementById('app').innerHTML = html;
}
```

## 마치며

이삽질을 겪기 전까지는 "OAuth는 쿠키로 처리하는 게 정석"이라고 굳게 믿고 있었습니다. HttpOnly 쿠키가 가장 안전하다는 교과서적 지식을 들고 Cloudflare Pages에 적용하려다 보니, 302 리다이렉트에서 쿠키가 사라지고, SPA에서는 HttpOnly 쿠키를 읽지도 못하는 모순이 연달아 터져 나왔습니다. 아홉 번의 실패를 돌아보면 결국 한 가지를 깨닫게 됩니다. 정답은 어디에도 고정되어 있지 않으며, 플랫폼이 어떤 방식을 잘 지원하고 어떤 방식을 방해하는지를 먼저 파악하는 것이 진짜 아키텍처 설계입니다. 교과서가 말하는 '모범 사례'보다 내가 발 딛고 있는 런타임의 한계가 훨씬 중요했습니다.

가장 인상적이었던 순간은 Issue #8이었습니다. 별도 Worker 도메인으로 쪼개놓고 CORS, SameSite, 이중 Redirect URI를 양파 깎듯 벗겨가며 고치던 것이, 결국 하나의 도메인으로 합치는 순간 모두 해결되었습니다. 복잡성의 원인을 제거하면 버그도 함께 사라진다는 사실을 몸으로 배웠습니다. 인증 시스템을 설계할 때 "이 정도 쿠키 처리는 되겠지"라는 가정을 이제는 절대 하지 않습니다.

앞으로 새로운 엣지 플랫폼에 인증을 붙일 일이 생기면, 가장 먼저 확인하는 것은 해당 런타임의 Set-Cookie 동작 방식과 캐시 동작 방식이 될 것입니다. 그리고 가능하면 프론트엔드와 API를 같은 도메인 안에 두는 구조에서 시작하려 합니다. 이 글이 같은 늪에서 헤매는 누군가에게 조금이나마 지름길이 되기를 바랍니다.
