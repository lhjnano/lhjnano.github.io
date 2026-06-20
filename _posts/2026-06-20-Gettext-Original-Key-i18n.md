---
layout: post
title: "키 발명은 끝났다 — GNU gettext 원문 키 방식 (4)"
categories: [AI, Development, Governance]
description: JSON 키-값 i18n 방식의 키 발명 부담에서 벗어나, GNU gettext 원문 키 방식을 채택한 과정과 듀얼 모드 설계를 설명합니다.
keywords: [i18n, gettext, 국제화, 다국어, 번역]
toc: true
toc_sticky: true
---

## Hook

`t('ui.a_065')` — 이게 무슨 뜻인지 아시겠습니까? 코드를 읽는 개발자도, 번역하는 사람도, AI 에이전트도 이 키가 어떤 화면의 어떤 문구인지 알 수 없습니다. 매번 키-값 매핑 파일을 뒤져야 합니다.

이 글에서는 **키 발명 단계를 없앤** GNU gettext 원문 키 방식을 소개하고, 기존 구조적 키 296건을 0건으로 마이그레이션한 과정을 공유합니다.

## TL;DR

- **JSON 키 방식의 핵심 문제는 "키 발명"입니다** — 매 문자열마다 고유 키를 만들고 유지하고 매핑하는 순수 오버헤드
- **gettext 원문 키 방식**: 텍스트 자체가 키 — `t('운동이 저장되었습니다')`
- **듀얼 모드**로 기존 구조적 키와 gettext를 공존시켜 점진적 마이그레이션
- CI/CD가 **모든 사용자 문자열의 gettext 래핑을 강제**합니다

## Background: 두 가지 i18n 방식 비교

### JSON 키 방식 (기각)

```javascript
// 매번 키를 발명해야 함
t('workout.save.success')     // ← 이 키를 누가 만들었는가?
t('workout.delete.confirm')
t('ui.a_065')                  // ← 이건 뭘까요?
```

| 문제 | 설명 |
|---|---|
| **키 발명 오버헤드** | 매 문자열마다 고유 키 생성 |
| **키 드리프트** | 리팩터 시 키가 실제 문구와 불일치 |
| **미사용 키 감사** | 사용하지 않는 키를 수동으로 찾아야 함 |
| **가독성 최악** | `t('ui.a_065')`가 뭔지 알 수 없음 |
| **번역자 경험** | 키-값 테이블만 보고 번역해야 함 |

### gettext 원문 키 방식 (채택)

```javascript
// 키 발명 불필요 — 텍스트 자체가 키
t('운동이 저장되었습니다')      // 한국어 원문 = 키
t('Exercise saved')            // 영어 원문 = 키
```

| 장점 | 설명 |
|---|---|
| **키 발명 불필요** | 텍스트 자체가 키 |
| **키 드리프트 불가** | 텍스트가 바뀌면 자동으로 새 키 |
| **자동 미사용 감지** | `xgettext`가 소스에서 사용된 키만 추출 |
| **가독성** | 코드에서 바로 의미 파악 |
| **복수형/컨텍스트 내장** | `ngettext`, `pgettext` 지원 |

## Solution: gettext 핵심 규칙

### 규칙 1: 소스 언어가 키

프로젝트에 따라 소스 언어가 다릅니다:

| 프로젝트 유형 | 소스 언어 | 예시 |
|---|---|---|
| 글로벌 SaaS | 영어 | `t('Exercise saved')` |
| 한국어 우선 서비스 | 한국어 | `t('운동이 저장되었습니다')` |

### 규칙 2: 모든 사용자 대면 문자열에 gettext 필수

| 필수 | 제외 |
|---|---|
| UI 라벨/버튼/헤딩 | 내부 로그 |
| 폼 검증 메시지 | API 에러 `code` |
| 사용자 에러 메시지 | 기술 식별자 |
| 토스트 알림 | |
| 이메일 내용 | |

### 규칙 3: 문자열 결합 금지

```javascript
// ✗ 금지: 변수를 키에 결합
t(`${count}세트`)  // count마다 다른 키 → 번역 누락

// ✓ 올바름: placeholder 보간
t('{count} sets', { count: count })
```

### 규칙 4: 복수형은 ngettext

```javascript
// 영어: 1형/2형 (singular/plural)
// 한국어: 1형 (단일 형태)
// 아랍어: 6형 (0, 1, 2, 3-10, 11-99, 100+)

ngettext('{count} set', '{count} sets', count)
```

### 규칙 5: 컨텍스트는 pgettext

```javascript
// 같은 단어, 다른 의미
pgettext('verb', 'Open')    // 동사: 열기
pgettext('adj', 'Open')     // 형용사: 열린
```

## 듀얼 모드 설계

기존 구조적 키를 사용하던 프로젝트에서 gettext로 전환할 때, **하나의 `t()` 함수로 두 방식을 공존**시킵니다:

```
t('ui.a_065')                    → 점이 있음 → 구조적 키 조회
t('운동이 저장되었습니다')        → 점이 없음 → gettext 원문 키
```

<details markdown="1">
<summary>t() 듀얼 모드 분기 로직</summary>

```javascript
function t(path) {
  // 점 포함 → 구조적 키 (기존 방식)
  if (path.includes('.')) {
    return lookupStructuralKey(path);
  }
  
  // 점 없음 → gettext 원문 키
  if (locale === 'ko') {
    return path;  // 원문 그대로 반환 (원문 = 키 = 한국어)
  }
  
  // 다른 언어 → 번역 조회, 없으면 원문 fallback
  return translations[locale]._gettext[path] || path;
}
```

**올바른 사용:**
```javascript
showToast(t('운동이 저장되었습니다'))
button.innerHTML = t('확인')
```

**금지:**
```javascript
showToast('운동이 저장되었습니다')   // 하드코딩
t('ui.a_001')                        // 의미 없는 키
t(`${count}세트`)                    // 변수를 키에
```
</details>

## CI/CD 강제 규칙

| 위반 | 결과 |
|---|---|
| 사용자 문자열 gettext 래핑 안 함 | **PR 차단** |
| .po 구문 오류 | **커밋 차단** |
| .pot 미갱신 | **머지 차단** |
| fuzzy 항목 | 경고 (머지 허용) |
| 컴파일 실패 | **배포 차단** |

### 지원 언어 및 폴백

```
지원: en(소스), ko, ja, zh-CN, zh-TW, es, fr, de, pt-BR, ar(RTL)

폴백 체인:
  ja-JP → ja → en → raw msgid
```

모든 서비스는 **영어 번역 필수 출시**입니다.

## Result: 마이그레이션 결과

피트니스 PWA에서 구조적 키를 gettext 원문 키로 전환한 결과:

| 단계 | 구조적 키 잔여 |
|---|---|
| 마이그레이션 전 | **296건** |
| A-1~A-7 자동화 스크립트 실행 후 | **0건** (주석 3건만 잔여, 화면 미노출) |

자동화 스크립트(`migrate-i18n-*.js`, `convert-gettext.js`)로 **413건을 일괄 교체**했습니다. 이후 번역은 `en.js`의 `_gettext` 객체만 편집하면 됩니다.

## Takeaway

1. **"키 발명"은 순수 오버헤드입니다** — `t('workout.save.success')`에서 `workout.save.success`라는 키를 누가 만들었는지는 중요하지 않습니다. 중요한 것은 "운동이 저장되었습니다"라는 메시지 자체입니다. 키 발명 단계를 없애면 개발자는 메시지에만 집중하고, 번역자는 실제 텍스트를 보고 번역할 수 있습니다. gettext 방식은 이 간단한 원리를 40년 전부터实践해왔습니다

2. **듀얼 모드로 점진적 전환이 가능합니다** — 한 번에 모든 키를 바꾸는 것은 위험합니다. 점(`.`) 유무로 구조적 키와 gettext를 분기하는 듀얼 모드를 만들면, 새 코드는 gettext를 쓰고 기존 코드는 점진적으로 전환할 수 있습니다. 296건의 구조적 키를 자동화 스크립트로 0건으로 만드는 데 며칠이면 충분했습니다

3. **gettext는 AI 에이전트에게도 유리합니다** — `t('ui.a_065')`를 본 AI 에이전트는 이 키가 무슨 의미인지 알 수 없어 매번 매핑 파일을 조회해야 합니다. 반면 `t('운동이 저장되었습니다')`는 자명합니다. AI 에이전트가 컨텍스트를 적게 소비하고 더 정확한 코드를 생성할 수 있는 구조적 이점이 있습니다

---

| ← 이전 | 시리즈: AI 주도 개발 거버넌스 | 다음 → |
|---|---|---|
| **[(3) 모놀리식 HTML 분할]({% post_url 2026-06-20-Monolithic-HTML-Splitting-AI-Context %})** | **(4) gettext 원문 키** | **[(5) 레이어드 테스팅]({% post_url 2026-06-20-Layered-Testing-E2E-Last %})** |
