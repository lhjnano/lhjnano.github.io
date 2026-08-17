---
layout: post
title: "Hono × Cloudflare Workers 개발자가 밟는 함정 6가지: parseBody부터 타입 시스템까지"
categories: [Cloudflare, Development]
description: "Hono와 Cloudflare Workers 조합에서 실제 프로덕션 코드로 검증한 함정 6가지를 코드로 정리했습니다."
keywords: [Hono, Cloudflare Workers, TypeScript, parseBody, FormData, SameSite]
toc: true
toc_sticky: true
---

업로드한 파일 세 개가 서버에 도착하는 순간 조용히 하나로 줄어든 적이 있나요? 두 달간 AI 프로젝트를 Hono와 Cloudflare Workers로 구축하며 밟은 함정 6가지를 코드와 함께 정리했습니다.

## TL;DR

- **`parseBody()`는 같은 키 폼 필드를 중복 제거 처리합니다.** 다중 파일은 `c.req.raw.formData()`로 받습니다.
- **미들웨어 헬퍼에 Hono 컨텍스트를 통째로 타이핑하지 않습니다.** 필요한 값만 매개변수로 넘깁니다.
- **Workers의 `FormDataEntryValue`에는 `File`이 없습니다.** `typeof value !== 'string'`으로 판별합니다.
- **`noUncheckedIndexedAccess` 아래에서 `pages[0]`는 `undefined`입니다.** 상류에서 조기 실패시킵니다.
- **SameSite 판정은 요청 헤더가 아니라 설정 기반입니다.** `FRONTEND_URL` 값 하나로 정합니다.
- **AI 출력을 정규화 없이 저장하지 않습니다.** 방어적 coerce와 타입 가드를 앞에 둡니다.

워커 테스트 함정(`vi.mock` silent failure 등)은 [이전 포스트](/2026/08/17/vitest-pool-workers-vi-mock-silent-failure/)가 다룹니다. 이 글은 런타임과 타입 쪽 함정을 다룹니다.

## 함정 1: parseBody()가 다중 파일을 지웁니다

다중 파일 업로드 폼을 처음 구현할 때 가장 먼저 도달하는 API가 `parseBody()`입니다. 편리합니다. 하지만 `files[]`처럼 같은 키로 여러 파일이 올라오면 상황이 달라집니다.

```ts
// ❌ files[] 중 마지막 파일 하나만 돌아옵니다
app.post('/upload', async (c) => {
  const body = await c.req.parseBody();

  // 3개를 올려도 body['files[]']는 파일 한 개입니다
  const file = body['files[]'] as File;
  await saveToR2(file);  // 나머지 2개는 이 시점에 이미 없습니다
  return c.json({ ok: true });
});
```

```ts
// ✅ 원시 FormData 이터레이션은 모든 엔트리를 보존합니다
app.post('/upload', async (c) => {
  const form = await c.req.raw.formData();
  const files: File[] = [];

  for (const [key, value] of form.entries()) {
    if (key === 'files[]' && typeof value !== 'string') {
      files.push(value);  // 3개가 3개 그대로 들어옵니다
    }
  }
  return saveAll(files);  // files.length === 3 이 보장됩니다
});
```

**원인**: `parseBody()`가 같은 키를 가진 폼 필드를 중복 제거 처리하며 마지막 값만 남깁니다. 에러가 없다는 점이 최악입니다. 요청은 성공하고 파일은 줄어듭니다.

**언제 터지나요?** 단일 파일 폼에서는 절대 터지지 않습니다. 배열 키(`files[]`)를 쓰는 순간부터 조용히 데이터가 사라집니다. 그래서 발견이 늦습니다.

> `parseBody()` 자체가 잘못된 코드가 아닙니다. 단일 키 폼에서는 정상 동작합니다. 함정은 다중 키에서만 열립니다.

두 경로의 차이를 그림으로 보면 다음과 같습니다. 입력은 완전히 같습니다. 경유하는 API 하나가 결과를 가립니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 430" role="img" aria-label="parseBody 경로와 raw.formData 경로의 다중 파일 처리 비교" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif">
  <defs>
    <marker id="hcg-arr-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
    <marker id="hcg-arr-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="190" y="30" text-anchor="middle" font-size="16" font-weight="700" fill="#dc2626">parseBody() 경로</text>
  <text x="610" y="30" text-anchor="middle" font-size="16" font-weight="700" fill="#16a34a">raw.formData() 이터레이션 경로</text>
  <line x1="400" y1="50" x2="400" y2="382" stroke="#ddd" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>
  <rect x="70" y="50" width="240" height="100" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="190" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#666">업로드된 폼 데이터 (files[])</text>
  <text x="190" y="94" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">resume.pdf</text>
  <text x="190" y="112" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">portfolio.pdf</text>
  <text x="190" y="130" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">cover-letter.pdf</text>
  <line x1="190" y1="150" x2="190" y2="174" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#hcg-arr-red)"/>
  <rect x="70" y="178" width="240" height="72" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="190" y="198" text-anchor="middle" font-size="12" font-weight="700" font-family="'Courier New',monospace" fill="#2563eb">parseBody()</text>
  <text x="190" y="216" text-anchor="middle" font-size="10" fill="#2c3e50">같은 키 폼 필드를</text>
  <text x="190" y="234" text-anchor="middle" font-size="10" fill="#2c3e50">중복 제거 처리합니다</text>
  <line x1="190" y1="250" x2="190" y2="274" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#hcg-arr-red)"/>
  <rect x="70" y="278" width="240" height="104" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="190" y="298" text-anchor="middle" font-size="12" font-weight="700" fill="#dc2626">반환 결과</text>
  <text x="190" y="316" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">cover-letter.pdf</text>
  <text x="190" y="334" text-anchor="middle" font-size="10" font-weight="700" fill="#dc2626">마지막 1개만 반환</text>
  <text x="190" y="352" text-anchor="middle" font-size="10" fill="#dc2626">앞의 2개는 사라짐</text>
  <rect x="490" y="50" width="240" height="100" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="610" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#666">업로드된 폼 데이터 (files[])</text>
  <text x="610" y="94" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">resume.pdf</text>
  <text x="610" y="112" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">portfolio.pdf</text>
  <text x="610" y="130" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">cover-letter.pdf</text>
  <line x1="610" y1="150" x2="610" y2="174" stroke="#16a34a" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#hcg-arr-green)"/>
  <rect x="490" y="178" width="240" height="72" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="610" y="198" text-anchor="middle" font-size="12" font-weight="700" font-family="'Courier New',monospace" fill="#2563eb">raw.formData()</text>
  <text x="610" y="216" text-anchor="middle" font-size="10" fill="#2c3e50">.entries() 이터레이션이</text>
  <text x="610" y="234" text-anchor="middle" font-size="10" fill="#2c3e50">모든 엔트리를 보존합니다</text>
  <line x1="610" y1="250" x2="610" y2="274" stroke="#16a34a" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#hcg-arr-green)"/>
  <rect x="490" y="278" width="240" height="104" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="610" y="298" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">반환 결과</text>
  <text x="610" y="316" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">resume.pdf</text>
  <text x="610" y="334" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">portfolio.pdf</text>
  <text x="610" y="352" text-anchor="middle" font-size="10" font-family="'Courier New',monospace" fill="#2c3e50">cover-letter.pdf</text>
  <text x="610" y="370" text-anchor="middle" font-size="10" font-weight="700" fill="#16a34a">3개 전부 반환</text>
  <text x="400" y="412" text-anchor="middle" font-size="11" fill="#2c3e50">입력은 같습니다. 경유하는 API 하나가 결과를 가립니다.</text>
</svg>

파일이 조용히 사라지는 함정은 눈에 잘 띄지 않았습니다. 다음 함정은 더 안 보입니다. 타입 선언 안에 숨습니다.

## 함정 2: 미들웨어 헬퍼를 Hono 컨텍스트로 타이핑하지 마세요

인증이나 소유권 검사 같은 헬퍼 함수를 만들 때 `Context`를 통째로 받고 싶어집니다. 그러다 실제 Hono 컨텍스트와 비슷한 수제 타입을 만들게 됩니다. 여기서부터 타입 체조가 시작됩니다.

```ts
// ❌ Hono 컨텍스트를 흉내 낸 수제 타입. 실제 Context 와 어긋납니다
function requireOwner(c: {
  env: { DB: D1Database };
  req: { param: (key: string) => string };
}) {
  return assertOwner(c.env.DB, c.req.param('id'));
}

app.get('/docs/:id', (c) => {
  return requireOwner(c);  // 제네릭마다 에러 메시지가 달라집니다
});
```

```ts
// ✅ 헬퍼는 필요한 값만 받습니다. 순수 함수가 됩니다
function assertOwner(db: D1Database, docId: string, userId: string) {
  return db
    .prepare('SELECT 1 FROM docs WHERE id = ? AND owner = ?')
    .bind(docId, userId)
    .first();
}

app.get('/docs/:id', async (c) => {
  const ok = await assertOwner(c.env.DB, c.req.param('id'), c.get('userId'));
  if (!ok) return c.text('Forbidden', 403);
  return c.text('OK');
});
```

**원인**: 수제 타입은 실제 `Context`의 모양과 어긋납니다. `Hono<Bindings>` 제네릭이 붙는 순간 호출부에서 불일치 에러가 반복됩니다.

**언제 터지나요?** 바인딩 타입을 정의하는 순간부터입니다. 헬퍼가 늘어날수록 수제 타입도 함께 늘어납니다. 값만 받는 헬퍼는 이 고리가 아예 없습니다.

프레임워크 타입은 밖에서 얇게 다루는 편이 안전합니다. 그런데 Cloudflare Workers의 타입 세계에는 더 깊은 구멍이 둘 있습니다.

## 타입 시스템이 파놓은 두 개의 구멍

런타임 버그보다 무서운 것은 타입이 만들어주는 안전 착각입니다. Workers의 타입 정의 두 곳에서 그 착각이 시작됩니다.

### 함정 3: FormDataEntryValue에 File이 없습니다

브라우저 예제 코드는 `instanceof File`을 흔히 씁니다. 그런데 Workers 타입 환경에서 `FormDataEntryValue`는 `File`을 참조하지 않습니다. 폼 값을 꺼낸 뒤의 판별법이 달라집니다.

```ts
// ❌ Workers 타입 환경에서 instanceof File 은 안전하지 않습니다
for (const [, value] of form.entries()) {
  if (value instanceof File) {  // 좁힘이 보장되지 않습니다
    await upload(value);
  }
}

// ✅ 문자열이 아니면 파일입니다. 별도 가드가 필요 없습니다
for (const [, value] of form.entries()) {
  if (typeof value !== 'string') {
    const file = value as File;  // 이 시점 value 는 파일입니다
    await upload(file);
  }
}
```

**원인**: Workers의 `FormDataEntryValue` 타입 선언에 `File` 클래스가 걸려 있지 않습니다. 브라우저 DOM 타입과 다른 지점입니다.

**언제 터지나요?** 브라우저 코드를 Workers로 가져올 때 터집니다. 컴파일은 되는데 좁힘이 되지 않거나 에러가 사라지지 않습니다.

값 판별 다음은 꺼낸 값 접근입니다. 배열의 첫 번째 원소는 배열이 보증해주지 않습니다.

### 함정 4: noUncheckedIndexedAccess 아래 pages[0]는 undefined입니다

외부 API 응답에서 첫 원소를 바로 꺼내는 코드는 흔합니다. `noUncheckedIndexedAccess`를 켜면 그 한 줄이 컴파일 에러가 됩니다.

```ts
const pages = await fetchPages(env);

// ❌ 'pages[0]' is possibly 'undefined'
const pageId = pages[0].id;

// ❌ 방어 없는 non-null assertion 은 크래시를 숨길 뿐입니다
const risky = pages[0]!.id;

// ✅ 빈 배열은 상류에서 조기 실패시킵니다
if (pages.length === 0) {
  throw new Error('UPSTREAM_EMPTY');
}
const first = pages[0]!.id;  // 조건을 통과했으므로 안전합니다
```

**원인**: 이 옵션은 모든 인덱스 접근에 `| undefined`를 붙입니다. `!`를 곳곳에 흩뿌리는 대신 빈 배열을 먼저 차단하는 편이 낫습니다.

**언제 터지나요?** strict 옵션 세트를 도입하는 순간 기존 코드 곳곳에서 터집니다. 조기 실패 패턴을 정해두면 수정이 기계적으로 진행됩니다.

타입 이야기는 여기까지입니다. 이제 브라우저와 서버 사이, 쿠키 판정으로 향합니다.

## 함정 5: SameSite 판정을 요청 헤더로 하면 틀어집니다

cross-origin 여부를 `Origin` 헤더로 판단하는 코드는 프록시나 CDN 뒤에서 무너집니다. 판정 기준을 헤더가 아니라 설정으로 옮기면 문제가 사라집니다.

```ts
const API_ORIGIN = 'https://api.my-service.example';

// ❌ 요청 헤더 기반 판정. 프록시나 CDN 뒤에서 오답이 나옵니다
function isSameSiteBad(req: Request) {
  const origin = req.headers.get('Origin');
  return origin === null || origin.includes('workers.dev');  // 추측에 의존합니다
}

// ✅ 설정 기반 판정. 환경 변수 하나로 결정합니다
function isCrossOrigin(env: Env): boolean {
  // FRONTEND_URL 미설정 = 로컬 모드 = same-origin 입니다
  if (!env.FRONTEND_URL) return false;
  return new URL(env.FRONTEND_URL).origin !== API_ORIGIN;
}

// 판정 결과가 cross-origin 이면 SameSite=None; Secure 가 필요합니다
```

**원인**: 요청 헤더는 경로 중간에서 바뀔 수 있습니다. 설정값은 바뀌지 않습니다. 판정은 변하지 않는 쪽에 두는 편이 안전합니다.

**언제 터지나요?** 프로덕션이 CDN 뒤로 이동할 때 터집니다. 주의할 점이 하나 더 있습니다. 같은 판정을 쓰는 쿠키(`oauth_state` 등)까지 전부 함께 고쳐야 합니다. 세션 쿠키 하나만 고치면 리다이렉트 플로우에서만 깨지는 부분 버그가 됩니다.

쿠키 함정은 원인과 증상이 멀리 떨어져 있었습니다. 마지막 함정도 비슷합니다. 이번에는 출력 자체를 믿으면 안 되는 대상입니다.

## 함정 6: AI 출력을 정규화 없이 저장하지 마세요

LLM 라우트를 붙이면 응답 파싱 코드가 금방 늘어납니다. 모델은 스키마를 대체로 지키지만 가끔 어깁니다. 저장 직전의 정규화가 사실상 유일한 방어선입니다.

```ts
// ❌ AI 출력을 그대로 믿고 저장합니다
const parsed = extractJson(res.text) as QaPayload;
await env.DB.prepare('INSERT INTO qa (content_json) VALUES (?)')
  .bind(JSON.stringify(parsed))
  .run();  // 깨진 스키마가 그대로 영구 저장됩니다
```

```ts
// ✅ 저장 전에 방어적으로 정규화합니다
function normalizeQa(raw: unknown): QaItem[] {
  if (!Array.isArray(raw)) return [];  // 형태가 틀리면 빈 배열
  return raw.flatMap((item: any) => {
    if (typeof item?.question !== 'string') return [];  // 질문 없는 항목 제거
    return [{
      question: item.question,
      // 모델이 answer 대신 model_answer 로 주는 경우도 흡수합니다
      answer: item.answer ?? item.model_answer ?? '',
      category: CATEGORIES.includes(item.category) ? item.category : 'behavioral',
    }];
  });
}
```

이외에도 정해둔 패턴이 세 개 있습니다.

- **JSON 추출기는 객체와 배열을 분리합니다.** 배열 응답을 객체 추출기에 넣으면 조용히 실패합니다.
- **폴백 `{}`을 쓰더라도 원문 텍스트를 요약으로 승격하지 않습니다.** 승격하면 쓰레기 요약이 저장됩니다.
- **파싱 실패 시 `[]`를 반환하고 상류에서 명시적으로 throw 합니다.** `undefined` 크래시를 원천 차단합니다.

**언제 터지나요?** 데모에서는 잘 돌아갑니다. 모델 버전이 바뀌거나 프롬프트가 살짝 수정될 때 터집니다. 정규화가 없다면 그 순간 저장소가 오염됩니다.

### 그 밖의 작은 함정

여섯 함정 외에 짧지만 기억할 것들이 네 개 있습니다.

- **`executionCtx.waitUntil()`은 제네릭과 무관합니다.** `Hono<Bindings>` 어떤 제네릭 아래에서도 `c.executionCtx.waitUntil()`은 항상 `ExecutionContext`를 노출합니다. 타입 때문에 비동기 전환을 미룰 이유가 없습니다.
- **라우트는 리터럴 먼저, 파라미터는 나중입니다.** Hono는 리터럴 경로를 우선 매칭합니다. 메서드가 다르면 충돌도 없습니다. 이 규칙 하나로 등록 순서 고민이 사라집니다.
- **`verbatimModuleSyntax`는 `import type`을 강제합니다.** 타입에만 쓰는 심볼은 반드시 `import type`으로 가져옵니다. `globals: true`여도 `describe` 같은 vitest 임포트는 값 임포트로 씁니다.
- **익명 타입은 네임드 인터페이스로 리프팅합니다.** 인라인 타입은 `noUnusedLocals`에 걸릴 수 있습니다. 공개 타입은 `export type`으로만 노출합니다.

함정은 여럿이지만 지키면 되는 규칙은 다섯으로 압축됩니다. 표로 정리합니다.

## 다섯 금칙 요약

두 달의 기록을 금칙 다섯 줄로 압축했습니다. 표의 2번과 3번은 워커 테스트 영역입니다.

| # | 금칙 | 지킬 것 |
|---|------|---------|
| 1 | `parseBody()`로 다중 파일 받기 | `c.req.raw.formData()` 이터레이션 사용 |
| 2 | workerd 테스트에서 `vi.mock` 사용 | `vi.stubGlobal('fetch')` + `vi.unstubAllGlobals()` |
| 3 | 테스트 바인딩 대조 없이 넘기기 | `wrangler.toml`과 `vitest.config.ts`를 항상 대조 |
| 4 | SameSite를 요청 헤더로 판정 | 설정(`FRONTEND_URL`) 기반 판정, 같은 판정을 쓰는 쿠키 전부 수정 |
| 5 | AI 출력을 정규화 없이 저장 | 방어적 coerce와 타입 가드를 저장 직전에 배치 |

다섯 규칙을 다시 한 줄로 줄이면 경계에서 검증한다가 됩니다. 마지막으로 이 글의 교훈을 정리합니다.

## Takeaway

1. **편의 API보다 원시 규약을 먼저 봅니다.** `parseBody()` 사건의 교훈입니다. 편의 함수는 규약 문서와 함께 씁니다.
2. **타입의 안전 착각을 경계합니다.** `File`과 `pages[0]`는 타입이 보증해주지 않는 것들입니다.
3. **외부 입력은 전부 의심합니다.** 브라우저 폼, 요청 헤더, AI 출력은 같은 부류입니다.

이 함정들의 공통점은 실패가 조용하다는 것입니다. 파일이 줄어도 에러는 없고, 쿠키가 누락돼도 서버는 200을 돌려줍니다. 그래서 저는 이제 저장과 판정 직전에 검증 코드를 습관처럼 붙입니다. 편의를 조금 포기하면 디버깅 하루를 돌려받습니다.
