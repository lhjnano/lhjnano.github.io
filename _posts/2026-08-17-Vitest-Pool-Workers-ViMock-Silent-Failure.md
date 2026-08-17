---
layout: post
title: "vitest-pool-workers에서 vi.mock이 소리 없이 죽는 이유: workerd 경계와 테스트 전략 7가지"
categories: [Cloudflare, Testing]
description: vitest-pool-workers에서 vi.mock이 조용히 실패하는 원인과 workerd 경계 테스트 전략 7가지를 정리합니다.
keywords: [vitest-pool-workers, Cloudflare Workers, workerd, vi.mock, vi.stubGlobal, Miniflare]
toc: true
toc_sticky: true
---

테스트 코드에서 분명히 mock 했는데, 로그를 열어보니 진짜 외부 API로 요청이 나가 있었습니다. 에러 메시지 하나 없이 테스트가 조용히 오염되는 이 상황에서 저는 이틀을 날렸습니다.

## TL;DR

- `@cloudflare/vitest-pool-workers`에서 **`vi.mock`은 workerd 경계를 넘지 못합니다.** mock 팩토리가 아예 호출되지 않고 실패는 조용합니다.
- 워커 경계 밖으로 나가는 호출은 **`vi.stubGlobal('fetch', ...)`로 스텁**합니다.
- 정리는 `vi.restoreAllMocks()`만으로 부족합니다. **`vi.unstubAllGlobals()`가 필요**하고, 정리를 빠뜨리면 같은 파일의 다른 테스트가 오염됩니다.
- R2와 D1은 스텁하지 않고 **실제 Miniflare 에뮬레이터로 검증**합니다. 외부 의존성만 스텁하는 전략이 깔끔합니다.

요약이 바로 이해되지 않아도 괜찮습니다. 왜 이런 일이 벌어지는지 실패한 순서대로 보겠습니다.

## 배경: 조용한 테스트 오염과의 첫 만남

두 달간 진행한 두 개의 워커 프로젝트에서 Cloudflare Workers와 D1, R2를 조합해 API를 만들었습니다. 그중 채용 정보 수집 모듈은 외부 API를 호출해 데이터를 정규화해 저장하는 구조였습니다. 외부 호출이 있는 코드라 테스트가 필수였고, 실제 workerd 런타임에서 돌아가는 `@cloudflare/vitest-pool-workers`를 도입했습니다.

문제는 도입 직후 시작됐습니다. 수집 모듈 테스트만 실패하는 게 아니라 같은 파일의 다른 테스트까지 흔들렸습니다. 에러 메시지에는 정체불명의 타임아웃이 찍혔고, 네트워크 로그를 확인하자 실제 요청이 외부로 나가 있었습니다. 분명 mock을 등록했는데 말이죠.

이 글은 그 이틀의 디버깅을, AI 코딩 하네스가 축적한 구현 노트를 바탕으로 다시 정리한 것입니다. 첫 번째 시도부터 보겠습니다.

## 시도 1: 평소처럼 vi.mock 사용하기, ❌ 실패

Node 환경의 vitest에서 늘 쓰던 방식 그대로 시작했습니다.

```ts
// ❌ 소리 없이 실패하는 패턴
// mock 팩토리는 한 번도 호출되지 않습니다
vi.mock('../src/lib/collector', () => ({
  fetchListings: vi.fn(async () => fakeListings),  // 1. 가짜 데이터를 반환하도록 설계
}));

test('채용 목록을 정규화해 저장한다', async () => {
  const result = await runCollector(env);          // 2. 진짜 fetch가 외부로 나갑니다
  expect(result.length).toBeGreaterThan(0);        // 3. 타임아웃 또는 데이터 오염
});
```

mock이 적용됐다면 외부 요청은 일어나지 않았어야 합니다. 그런데 테스트를 돌릴 때마다 진짜 요청이 나갔고, mock 팩토리 안의 로그는 단 한 번도 찍히지 않았습니다. import 경로 오타도 의심했지만 원인은 아니었습니다.

답은 구조에 있었습니다. 테스트 러너는 Node.js 프로세스에서, 테스트 대상 워커 코드는 workerd 프로세스에서 동작합니다. `vi.mock`이 등록하는 모듈 레벨 모킹은 이 프로세스 경계를 넘지 못하고 Node에 갇힙니다. 반면 워커 코드가 호출하는 `fetch`는 workerd 안에서 실행되므로 진짜 요청이 외부로 나갑니다. 아래 다이어그램은 이 실패 흐름을 시간순으로 펼친 것입니다.

> **vi.mock이 소리 없이 죽는 이유**: 테스트 러너(Node)와 테스트 대상(workerd)이 서로 다른 프로세스
> 경계에 있어서, 모듈 레벨 모킹이 전달되지 않기 때문입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 460" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="vi.mock은 Node 프로세스에 갇히고 workerd의 fetch는 외부 API로 나가는 실패 흐름 시퀀스 다이어그램">
  <defs>
    <marker id="vpw-arrow-blue" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#2563eb"/>
    </marker>
    <marker id="vpw-arrow-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
    <marker id="vpw-arrow-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="430" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">vi.mock은 Node에 갇히고, fetch는 workerd를 빠져나간다</text>
  <rect x="35" y="45" width="150" height="50" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="110" y="66" text-anchor="middle" font-size="13" font-weight="700" fill="#2563eb">테스트 러너</text>
  <text x="110" y="83" text-anchor="middle" font-size="10" fill="#2563eb">Node.js 프로세스</text>
  <rect x="355" y="45" width="150" height="50" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="430" y="66" text-anchor="middle" font-size="13" font-weight="700" fill="#16a34a">테스트 대상 워커</text>
  <text x="430" y="83" text-anchor="middle" font-size="10" fill="#16a34a">workerd 프로세스</text>
  <rect x="675" y="45" width="150" height="50" rx="8" fill="#ede9fe" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="750" y="66" text-anchor="middle" font-size="13" font-weight="700" fill="#7c3aed">외부 API</text>
  <text x="750" y="83" text-anchor="middle" font-size="10" fill="#7c3aed">실제 외부 서비스</text>
  <line x1="110" y1="95" x2="110" y2="440" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="430" y1="95" x2="430" y2="440" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="750" y1="95" x2="750" y2="440" stroke="#ddd" stroke-dasharray="4,4"/>
  <circle cx="110" cy="130" r="12" fill="#dc2626"/>
  <text x="110" y="134" text-anchor="middle" font-size="11" font-weight="700" fill="white">1</text>
  <rect x="140" y="115" width="200" height="32" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="240" y="135" text-anchor="middle" font-size="11" fill="#2c3e50">vi.mock() 등록, 전달 안 됨</text>
  <circle cx="110" cy="185" r="12" fill="#2563eb"/>
  <text x="110" y="189" text-anchor="middle" font-size="11" font-weight="700" fill="white">2</text>
  <line x1="125" y1="185" x2="415" y2="185" stroke="#2563eb" stroke-width="1.5" marker-end="url(#vpw-arrow-blue)"/>
  <text x="270" y="179" text-anchor="middle" font-size="10" fill="#2c3e50">테스트 대상 모듈 실행</text>
  <circle cx="430" cy="240" r="12" fill="#dc2626"/>
  <text x="430" y="244" text-anchor="middle" font-size="11" font-weight="700" fill="white">3</text>
  <line x1="445" y1="240" x2="735" y2="240" stroke="#dc2626" stroke-width="1.5" marker-end="url(#vpw-arrow-red)"/>
  <text x="590" y="234" text-anchor="middle" font-size="10" fill="#2c3e50">fetch() 실제 요청 발생</text>
  <circle cx="750" cy="295" r="12" fill="#16a34a"/>
  <text x="750" y="299" text-anchor="middle" font-size="11" font-weight="700" fill="white">4</text>
  <line x1="735" y1="295" x2="445" y2="295" stroke="#16a34a" stroke-width="1.5" marker-end="url(#vpw-arrow-green)"/>
  <text x="590" y="289" text-anchor="middle" font-size="10" fill="#2c3e50">실제 응답 또는 타임아웃</text>
  <circle cx="430" cy="350" r="12" fill="#dc2626"/>
  <text x="430" y="354" text-anchor="middle" font-size="11" font-weight="700" fill="white">5</text>
  <line x1="445" y1="350" x2="125" y2="350" stroke="#dc2626" stroke-width="1.5" marker-end="url(#vpw-arrow-red)"/>
  <text x="285" y="344" text-anchor="middle" font-size="10" fill="#2c3e50">mock 미적용 결과 반환, 조용한 실패</text>
  <rect x="190" y="380" width="480" height="48" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="430" y="399" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">해결: 모듈 모킹 대신 vi.stubGlobal('fetch')로 전역 fetch 스텁</text>
  <text x="430" y="417" text-anchor="middle" font-size="10" fill="#92400e">afterEach에서 vi.unstubAllGlobals()로 정리까지 마칩니다</text>
</svg>

다이어그램의 3번 화살표가 이 함정의 핵심입니다. mock은 Node에만 남았고, workerd는 모른 채 진짜 fetch를 밖으로 보냈습니다. 원인이 명확해졌으니 다음 시도는 모듈 모킹을 버리고 전역으로 옮겨갔습니다.

## 시도 2: vi.stubGlobal 도입, 그리고 정리 실패, ❌ 실패

모듈 대신 전역을 스텁했습니다. 전역 객체 자체를 교체하는 방식이라 workerd 안에서 실행되는 fetch 호출에도 효과가 있습니다.

```ts
// ✅ 워커 경계 밖으로 나가는 호출은 전역 fetch를 스텁합니다
vi.stubGlobal('fetch', vi.fn(async (url) => {
  // 1. 외부 API의 응답 형태를 그대로 흉내 냅니다
  return new Response(JSON.stringify(fakeItems));
}));
```

이번에는 테스트가 통과했습니다. 그런데 기쁨은 잠시였습니다. 같은 파일의 다른 테스트가 깨지기 시작했습니다. 원인은 정리였습니다. 저는 익숙한 복원 함수만 호출했습니다.

```ts
// ❌ restoreAllMocks만으로는 전역 스텁이 정리되지 않습니다
afterEach(() => {
  vi.restoreAllMocks();   // 1. 일반 mock은 복원되지만 stubGlobal은 그대로입니다
});

// ✅ 전역 스텁은 별도 해제가 필요합니다
afterEach(() => {
  vi.restoreAllMocks();   // 1. 일반 mock 복원
  vi.unstubAllGlobals();  // 2. stubGlobal 해제, 이 호출이 빠져 있었습니다
});
```

정리를 빠뜨리면 오염된 전역 fetch가 다음 테스트로 그대로 넘어갑니다. `unstubAllGlobals`까지 넣고 나서야 파일 전체가 안정됐습니다. 그러고 보니 남은 질문이 하나 있었습니다. 무엇을 스텁하고 무엇을 진짜로 검증할 것인가.

## 시도 3: 경계 기반 테스트 전략 7가지 정립, ✅ 성공

실마리는 뜻밖의 곳에서 나왔습니다. Miniflare의 에뮬레이팅 R2는 get과 put 모두 인프로세스로 동작해 global fetch를 거치지 않는다는 사실입니다. 그래서 fetch 스텁은 외부 HTTP 호출만 가로채고 R2 테스트를 깨뜨리지 않습니다. 이 특성 위에 전략을 세웠습니다.

1. **`vi.mock` 대신 `vi.stubGlobal('fetch')`를 씁니다.** 워커 경계를 넘는 외부 호출만 정확히 가로챕니다.
2. **`afterEach`에서 `vi.unstubAllGlobals()`를 호출합니다.** 전역 스텁 오염을 차단합니다.
3. **R2와 D1은 스텁하지 않고 실제 에뮬레이터로 검증합니다.** 외부 의존성만 스텁하는 경계가 명확해집니다.
4. **R2 실측 테스트는 `rBuckets` 선언으로 시작합니다.** 업로드 검증은 메모리 재사용이 아니라 버킷에서 다시 읽습니다.
5. **런타임과 테스트의 바인딩 세트를 항상 대조합니다.** 한쪽에만 있는 바인딩은 테스트에서만 undefined가 됩니다. 주석 처리된 바인딩은 명시적 캐스팅으로 표시합니다.
6. **셋업 데이터는 API를 거치지 않고 D1에 직접 삽입합니다.** 피험 API의 구현 변경이 테스트로 연쇄 붕괴되지 않습니다.
7. **순수 함수 모듈은 node 환경에서 돌립니다.** `environmentMatchGlobs`로 lib 디렉터리만 node 환경에 둡니다.

7번 설정은 한 줄이면 충분합니다. `environmentMatchGlobs: [['**/lib/**', 'node']]`처럼 선언하면 lib 디렉터리의 순수 함수는 node 환경에서 실행됩니다. `fetch`와 `setTimeout`은 양쪽 환경에 모두 있어서 대부분 수정 없이 동작합니다.

설정과 셋업의 핵심 두 가지는 코드로 남깁니다. 먼저 R2 버킷 선언입니다.

```ts
// vitest.config.ts
export default defineWorkersConfig({
  test: {
    miniflare: {
      rBuckets: ['R2'],   // 1. 에뮬레이팅 R2 버킷 바인딩을 선언합니다
    },
  },
});
```

버킷에서 다시 읽는 검증은 `env.R2.get`으로 합니다. 업로드가 실제로 저장됐는지 확인할 수 있습니다. 다음은 D1 직접 삽입 셋업입니다.

```ts
// ✅ 셋업 데이터가 피험 API를 거치지 않습니다
await env.DB.prepare(
  'INSERT INTO sources (id, memo) VALUES (?, ?)'  // 1. 최소한의 행만 직접 삽입합니다
).bind(testId, memo).run();
// 2. API의 내부 매핑이 바뀌어도 이 셋업은 영향을 받지 않습니다
```

일곱 가지를 모두 적용한 뒤 테스트는 실패하더라도 명확하게 실패하게 됐습니다. 변화를 표로 정리했습니다.

## 결과: Before와 After

| 항목 | Before | After |
|------|--------|-------|
| 외부 호출 처리 | `vi.mock` 등록이 무시되고 진짜 요청 발생 | `vi.stubGlobal('fetch')`로 스텁 |
| 테스트 정리 | `restoreAllMocks`만 호출, 전역 오염 | `unstubAllGlobals`까지 확실한 정리 |
| 스토리지 검증 | 인메모리 mock으로 형식적 확인 | 실제 에뮬레이터(R2, D1)로 검증 |
| 셋업 방식 | 피험 API 호출에 의존 | D1 직접 삽입으로 연쇄 붕괴 제거 |
| 실패 양상 | 조용한 실패, 원인 추적에 이틀 | 경계 위반이 즉시 명시적으로 드러남 |

마지막으로 원래 노트의 다섯 금칙 중 테스트와 직결되는 세 가지를 표로 남깁니다.

| 금칙 | 이유 | 올바른 대안 |
|------|------|-------------|
| workerd 테스트에서 `vi.mock` 금지 | 모듈 모킹이 Node 프로세스에 갇혀 전달되지 않습니다 | `vi.stubGlobal('fetch')` 사용 |
| 전역 스텁 정리 누락 금지 | 오염된 전역을 다른 테스트가 물려받습니다 | `afterEach`에서 `vi.unstubAllGlobals()` |
| 바인딩 세트 대조 생략 금지 | 누락된 바인딩은 테스트에서만 undefined가 됩니다 | 런타임 설정과 테스트 설정을 항상 대조 |

표는 단순하지만 여기에 닿기까지의 과정은 단순하지 않았습니다.

## 마치며

처음에는 제가 mock을 잘못 쓴 줄 알았습니다. 경로 오타를 고치고 팩토리를 다시 쓰고 버전까지 바꿔봤습니다. 그러나 문제는 테스트 코드가 아니라 러너와 런타임이 다른 프로세스라는 구조 자체에 있었습니다. 도구의 동작 모델을 이해하기 전에는 코드를 고쳐도 같은 자리를 맴돌 뿐이었습니다.

silent failure가 최악인 이유는 조용하다는 것 자체입니다. 명시적으로 실패하는 테스트는 스택 트레이스가 디버깅의 출발점이 됩니다. 그러나 조용한 실패는 가설을 하나씩 지워나갈 수밖에 없습니다. "이미 mock 했는데 왜 진짜 요청이 나가지?"라는 질문이 마침내 구조를 의심하게 했습니다.

이 글의 원료는 두 프로젝트 동안 AI 코딩 하네스가 축적한 구현 노트입니다. 돌아보니 함정은 반복되었고, 반복된 함정은 패턴이 됐고, 패턴은 전략이 됐습니다. 경계를 이해하고 나면 무엇을 스텁하고 무엇을 실제로 검증할지는 자연스럽게 따라왔습니다. 여러분의 워커 테스트도 조용한 실패를 만나면, 먼저 프로세스 경계를 의심해 보시길 바랍니다.
