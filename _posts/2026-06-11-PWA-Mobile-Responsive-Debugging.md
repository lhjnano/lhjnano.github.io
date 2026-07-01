---
layout: post
title: "PWA 모바일 반응형: 7번 핑퐁 끝에 배운 6가지 교훈"
categories: [PWA, CSS]
description: PWA 개발 중 겪은 반응형 디버깅의 핵심 교훈을 정리합니다. vw 단위, 인라인 스타일 함정, flexbox, 캐시 갱신까지 실전에서 배운 것들입니다.
keywords: [PWA, 반응형, CSS, mobile, vw, flexbox]
toc: true
toc_sticky: true
---

## Hook

"모바일에서 버튼이 안 보인다"는 피드백부터 시작된 반응형 디버깅. 7번의 수정-배포-확인 사이클 끝에 찾은 것은, 단위 선택과 CSS 우선순위라는 기본기였습니다.

## TL;DR

- **px 대신 vw**: `vw = preview_px / 375 × 100`
- **인라인 style이 CSS 클래스를 이긴다**: 1~3차 시도 실패의 근본 원인
- **flex:1은 양날의 검**: 남은 공간을 다 먹거나, 누락 시 0px
- **데스크탑 모드를 먼저 확인**: @media 규칙이 완전히 달라짐
- **SW 캐시는 이름 변경으로 갱신**: CSS 변경이 안 보이면 캐시 의심

## 어떤 상황이었나요?

PWA 피트니스 앱을 모바일 반응형으로 작업하면서, 디자인 프리뷰 7개 페이지를 SPA 단일 파일로 통합했습니다. CSS 클래스에서 인라인 스타일로 전환했다가, 다시 인라인+CSS 병행으로 회귀하는 과정이었습니다.

**타임라인:**

| 회차 | 시도 | 결과 | 원인 |
|---|---|---|---|
| 1차 | @media px→vw 변환 | 실패 | 인라인 style이 CSS 덮어씀 |
| 2차 | render() 인라인 px→vw | 실패 | 원인 파악 실패 |
| 3차 | preview px 복원 | 거부 | "왜 px인가" |
| 4차 | preview 비율 그대로 vw 변환 | 성공 | 비율 기반 변환 |
| 5차 | "세트 추가 버튼 안 보임" | 해결 | flex:1 누락 + 데스크탑 모드 |
| 6차 | "포즈 가이드 너무 밑에" | 해결 | flex:1이 공간 다 차지 |
| 7차 | "홈 글자 줄넘김" | 해결 | px 고정값 + 인라인 배치 |

## 교훈 1: 단위는 무조건 vw/vh

**현상:** 모바일에서 요소 크기가 기기마다 다르게 보입니다.

**원인:** `px`은 물리적 픽셀 기준이라, 갤럭시 S시리즈(1080px+)에서는 작게, iPhone SE(375px)에서는 크게 보입니다.

**해결:** 모든 크기를 `vw`로 변환합니다.

```css
/* ❌ */
font-size: 14px;

/* ✅ */
font-size: 3.7vw;
```

```css
.container {
  padding: 4vw;
}

@media (min-width: 600px) {
  .container {
    padding: 24px;
  }
}
```

예외: `@media (min-width: 600px)` 데스크탑 구간에서만 `px`을 허용합니다.

## 교훈 2: 인라인 style이 CSS를 덮어쓴다

**현상:** CSS 클래스에 반응형을 적용했지만 모바일에서 전혀 반영되지 않습니다.

**원인:** 이것이 1~3차 시도가 모두 실패한 근본 원인이었습니다. `style="width:136px"` 같은 인라인 스타일은 CSS 클래스보다 **항상** 우선순위가 높습니다. 아무리 `.card { width: 36vw !important; }`를 적어도 인라인이 이깁니다.

**해결:** render 함수에서 `style="..."` 인라인 사용을 최소화하고, 크기와 위치는 반드시 CSS 클래스로 제어합니다.

```javascript
// ❌
return `<div style="width:136px;height:40px;font-size:14px">...</div>`;

// ✅
return `<div class="card">...</div>`;
```

## 교훈 3: flex:1은 양날의 검

**현상 A:** flex:1이 남은 공간을 전부 차지해서 하위 요소가 화면 밑으로 밀려납니다.

**원인:** `.btn-complete-wrap { flex: 1 }`이 세로 공간을 전부 차지해, 포즈 가이드와 이전 세트가 보이지 않았습니다.

```css
/* ❌ */
.btn-complete-wrap { flex: 1; }
.center-area { justify-content: space-between; }

/* ✅ */
.btn-complete-wrap { }
.center-area { justify-content: flex-start; }
```

**현상 B:** 반대로 flex:1이 누락되면 버튼이 0px로 렌더링됩니다.

**원인:** `display:flex` 컨테이너 안의 버튼에 `flex:1`이 없으면 width가 0이 됩니다.

```css
/* ❌ */
.btn-outline { height: 15vw; }

/* ✅ */
.btn-outline { flex: 1; height: 15vw; }
```

## 교훈 4: "데스크탑 모드" 함정

**현상:** CSS를 수정했는데 모바일에서 전혀 반영되지 않습니다.

**원인:** 모바일 브라우저에서 "데스크탑 사이트 보기" 옵션이 켜져 있으면 User-Agent가 데스크탑으로 바뀌어, `@media (max-width: 599px)` 모바일 규칙이 전부 무시됩니다.

**디버깅 체크리스트:**

1. 시크릿 모드로 접속했는가? → localStorage 없어서 로그인 안 됨
2. "데스크탑 사이트 보기"가 켜져 있는가? → @media 모바일 규칙 무시
3. Service Worker 캐시가 갱신되었는가? → 구버전 서빙 가능
4. 브라우저 확장 프로그램이 CSS를 덮어쓰고 있지 않은가?

## 교훈 5: 캐시 갱신은 SW 이름 변경

**현상:** CSS를 변경해도 모바일에 반영되지 않습니다.

**원인:** 브라우저가 Service Worker 캐시에서 구버전을 서빙하고 있습니다.

**해결:** 캐시 이름만 바꿔도 `activate` 이벤트에서 이전 캐시를 삭제하고 새로 받아옵니다.

<details markdown="1">
<summary>교훈 5: 캐시 갱신은 SW 이름 변경</summary>

```javascript
// sw.js
const CACHE_NAME = 'my-pwa-v6';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([
        '/',
        '/index.html',
        '/styles.css',
        '/app.js'
      ]);
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
});
```
</details>

## 교훈 6: 긴 텍스트는 세로 리스트로

**현상:** 좁은 화면에서 텍스트가 줄바꿈되어 가독성이 떨어집니다.

**원인:** 긴 텍스트를 `<p>` 태그에 인라인으로 배치하면 줄넘김이 발생합니다.

**해결:** `<ul>` 불릿 리스트로 세로 배치합니다.

```html
<!-- ❌ -->
<p>레그 — 스쿼트, RDL, 레그 컬, 레그 익스텐션</p>

<!-- ✅ -->
<ul>
  <li>스쿼트</li>
  <li>RDL</li>
  <li>레그 컬</li>
  <li>레그 익스텐션</li>
</ul>
```

## vw 변환 치트시트

디자인 프리뷰(375px 기준)에서 자주 쓰는 크기 변환표입니다.

| preview px | vw (375기준) | 비고 |
|---|---|---|
| 12px | 3.2vw | 보조 텍스트 |
| 14px | 3.7vw | 본문 |
| 20px | 5.3vw | 입력폼 |
| 56px | 15vw | 버튼 높이 |
| 136px | 36vw | 세트 완료 링 |

```css
.text-secondary { font-size: 3.2vw; }
.text-body      { font-size: 3.7vw; }
.input-field    { height: 5.3vw; }
.btn-primary    { height: 15vw; }
```

## 추가 버그 수정 요약

반응형 작업 외에 사용자 피드백 기반으로 수정한 9건입니다.

| # | 이슈 | 해결 |
|---|---|---|
| 1 | 개인정보처리방침 클릭 불가 | SPA privacy 페이지 추가, 데드링크 제거 |
| 2 | 앱 설치(A2HS) 안됨 | manifest link + SW register 추가 |
| 3 | 갤러리 다중 삭제 불가 | 편집 모드 + 체크박스 일괄 삭제 |
| 4 | 타임스탬프 사진 위 표시 안됨 | 날짜 오버레이 + 공유 시 캔버스 워터마크 |
| 5 | 바디 포토 날짜 UTC로 엉뚱함 | 로컬 타임존 기준으로 변경 |
| 6 | 식단 탭 UX 불편 | 빠른 추가 모드 + 즐겨찾기 원클릭 |
| 7 | 세트 자동세팅 안됨 + 모바일 작음 | 변수명 수정 + 반응형 확대 |
| 8 | 루틴 아이콘 큼 + 가이드 미동작 | 아이콘 축소 + 가이드 인라인 표시 |
| 9 | 내 몸의 변화에 촬영 없음 | 카메라 버튼 + 바디탭 연동 추가 |

## 마치며

"모바일에서 버튼이 안 보인다"는 피드백을 받았을 때, 저는 당연히 복잡한 렌더링 로직의 버그를 의심했습니다. render 함수를 뜯어고치고, 상태 관리를 추적하고, 이벤트 흐름을 따라갔습니다. 그런데 일곱 번의 수정-배포-확인 사이클을 거치고 나서야 깨달았습니다. 진짜 원인은 단위 선택(`px` 대신 `vw`)과 CSS 우선순위(인라인이 클래스를 이긴다는 사실)라는, 가장 기본적인 것이었습니다. 화려한 디버깅 도구보다 CSS 명세서 한 페이지가 문제를 풀어주는 모순적인 상황에 웃음이 나왔습니다.

이 경험에서 가장 크게 배운 점은, "안 된다"는 보고가 들어왔을 때 코드부터 의심하기 전에 환경을 먼저 확인해야 한다는 것입니다. 모바일 브라우저의 "데스크탑 사이트 보기" 옵션이 켜져 있으면 `@media` 규칙이 전부 무시되고, Service Worker 캐시가 구버전을 서빙하면 아무리 코드를 고쳐도 반영되지 않습니다. 캐시가 의심될 때 가장 확실한 해결책이 캐시 이름을 바꾸는 것이라는, 우습게 들리지만 가장 실용적인 방법도 이 과정에서 익혔습니다.

앞으로 반응형 작업을 할 때는 단위 변환표를 먼저 만들고, 인라인 스타일은 최소화하며, "데스크탑 모드"와 캐시부터 확인하는 체크리스트를 습관화하려 합니다. 화려한 기법보다 기본기를 다지는 것이 가장 빠른 길이라는, 다소 고전적이지만 변하지 않는 진리를 모바일 디버깅이 다시 한번 일깨워 주었습니다.
