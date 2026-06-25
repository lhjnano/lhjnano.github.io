---
layout: post
title: "GLM-5 API 429 에러 — 4일간의 삽질과 해결"
categories: [AI, API]
description: GLM-5 API에서 429 에러로 4일간 삽질한 끝에 찾은 올바른 엔드포인트와 JSON 파싱 복구 방법을 공유합니다.
keywords: [GLM-5, API, LLM, JSON, troubleshooting]
toc: true
toc_sticky: true
---

GLM-5 API를 호출했는데 429 에러만 돌아왔다. 크레딧 문제인 줄 알고 4일을 허비했다 — 원인은 단순히 엔드포인트 경로였다.

## TL;DR

- **잘못된 경로**: `/api/paas/v4/` → 429 `code:1113` 반환
- **올바른 경로**: `/api/coding/paas/v4/` → 별도 리소스 풀로 정상 작동합니다
- **max_tokens 필수**: 설정하지 않으면 응답이 중간에 잘립니다
- **JSON 파싱**: 4단계 복구 로직이 필수입니다 (줄바꿈 escape를 하지 않는 모델 특성)

## 어떤 문제가 있었나요?

GLM-5 API를 연동하면서 4일간 겪은 문제를 타임라인으로 정리합니다.

1. **Day 1** — API 호출 시 `429 code:1113 "余额不足"` 반환. "크레딧을 다 썼구나"라고 판단했지만, 실제로는 **엔드포인트 오류**였습니다.
2. **Day 2** — 다른 LLM으로 폴백 로직을 추가했습니다. 응답은 오지만 `JSON.parse()`가 실패합니다. 원인은 literal newline이 JSON 안에 들어있는 것.
3. **Day 4 오전** — `content.split('\n').join('\\n')`으로 급하게 수정했습니다. 결과: 구조적 줄바꿈까지 망가져서 파싱이 더 안 됩니다.
4. **Day 4 오후** — 문자열 내부만 escape하는 `fixControl()`을 구현하고 4단계 복구 파이프라인을 구축했습니다. JSON 파싱 성공.
5. **Day 4 저녁** — 응답이 중간에 잘리는 현상 발견. `max_tokens: 4096` 추가 후 전체 응답 수신 성공.
6. **Day 4 야간** — `/api/paas/v4` → `/api/coding/paas/v4`로 경로 변경. 429 에러가 사라지고 정상 응답을 확인했습니다.

혼란스러웠던 이유는 에러 메시지가 **"잔액 부족"**이었기 때문입니다. 실제 원인은 리소스 풀이 소진된 엔드포인트를 사용한 것이었습니다.

## 해결 1: 올바른 엔드포인트 찾기

두 경로의 차이는 `/coding/` 하나입니다.

```
❌ https://open.bigmodel.cn/api/paas/v4/chat/completions
   → 리소스 팩 소진 시 429 code:1113 "余额不足" 반환

✅ https://open.bigmodel.cn/api/coding/paas/v4/chat/completions
   → 별도 리소스 풀 사용, 정상 응답
```

`/api/coding/paas/v4`는 코딩용 엔드포인트지만, 분석·요약·창작 등 범용 프롬프트도 정상 처리됩니다. 공식 문서에서 이 구분이 명확히 표기되어 있지 않아 혼란이 발생했습니다.

TypeScript fetch 예시입니다.

```typescript
const response = await fetch(
  "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
  {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "glm-5",
      messages: [
        { role: "system", content: "JSON으로만 응답해." },
        { role: "user", content: prompt },
      ],
      temperature: 0.3,
      max_tokens: 4096,
    }),
  }
);
```

## 해결 2: JSON이 깨지는 문제

GLM-5는 thinking 모델이며 JSON 출력 시 다음 문제가 있습니다.

- **줄바꿈 escape 안 함** — 문자열 값 안에 literal newline을 넣습니다
- **`json 래핑** — JSON을 마크다운 코드블록으로 감싸서 반환할 수 있습니다
- **response_format 미지원** — 프롬프트로만 JSON을 강제해야 합니다

### 4단계 복구 로직

**1단계: 직접 파싱**

```typescript
try {
  return JSON.parse(content);
} catch {}
```

**2단계: 코드블록 추출**

```typescript
const match = content.match(/```(?:json)?\s*([\s\S]*?)```/);
if (match) {
  try { return JSON.parse(match[1].trim()); } catch {}
  try { return JSON.parse(fixControl(match[1].trim())); } catch {}
}
```

**3단계: 중괄호 추출 + 제어문자 수정**

```typescript
const first = content.indexOf("{");
const last = content.lastIndexOf("}");
if (first !== -1 && last > first) {
  const extracted = content.slice(first, last + 1);
  try { return JSON.parse(fixControl(extracted)); } catch {}
}
```

**4단계: trailing comma 제거 + 재시도**

```typescript
const repaired = extracted.replace(/,\s*([}\]])/g, "$1");
return JSON.parse(fixControl(repaired));
```

> **절대 하면 안 되는 것:**
>
> ```typescript
> // ❌ JSON 구조 자체가 망가짐!
> json.split("\n").join("\\n");
> ```
>
> 이 방식은 문자열 외부의 구조적 줄바꿈까지 escape해버립니다.
> `{"key": "value"}` → `{\n  "key": "value"\n}` 이 `\\n`으로 변환되어 파싱 불가 상태가 됩니다.

### fixControl 핵심 로직

문자열 **내부**의 제어문자만 escape하고, 문자열 **외부**의 구조적 줄바꿈은 유지합니다.

```typescript
function fixControl(json: string): string {
  let result = "", inStr = false, esc = false;
  for (const ch of json) {
    if (esc) { result += ch; esc = false; continue; }
    if (ch === "\\" && inStr) { result += ch; esc = true; continue; }
    if (ch === '"') { inStr = !inStr; result += ch; continue; }
    if (inStr) {
      if (ch === "\n") result += "\\n";
      else if (ch === "\r") result += "\\r";
      else if (ch === "\t") result += "\\t";
      else result += ch;
    } else {
      result += ch;
    }
  }
  return result;
}
```

따옴표 안팎을 `inStr` 플래그로 추적하여, 문자열 값 안의 `\n`, `\r`, `\t`만 escape합니다.

## 해결 3: max_tokens 설정

GLM-5는 thinking 모델이므로 `max_tokens`를 설정하지 않으면 기본값이 매우 작아 응답이 중간에 잘립니다.

```
max_tokens 미설정 → 응답이 반쯤 오다가 끊김
max_tokens: 4096  → 전체 응답 정상 수신
```

JSON 형식으로 긴 분석 결과를 받을 때 특히 치명적이므로 반드시 설정합니다.

## 파라미터 요약표

| 항목 | 값 | 비고 |
|------|-----|------|
| 엔드포인트 | `/api/coding/paas/v4/chat/completions` | `/api/paas/v4` 사용 금지 (429 발생) |
| 모델 | `glm-5` | thinking 모델 |
| temperature | `0.3` | 분석용. 창작은 0.7~0.8 |
| max_tokens | `4096` | 반드시 설정. 안 하면 응답 잘림 |
| 인증 | `Authorization: Bearer {key}` | OpenAI 호환 형식 |
| response_format | 미지원 | 프롬프트로 JSON 강제 |

## 전체 코드

<details><summary>📖 복사-붙여넣기용 완전 코드</summary>

```typescript
const GLM_API_URL =
  "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions";

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

function fixControl(json: string): string {
  let result = "";
  let inString = false;
  let escape = false;

  for (let i = 0; i < json.length; i++) {
    const ch = json[i];

    if (escape) {
      result += ch;
      escape = false;
      continue;
    }

    if (ch === "\\") {
      result += ch;
      escape = true;
      continue;
    }

    if (ch === '"') {
      inString = !inString;
      result += ch;
      continue;
    }

    if (inString) {
      if (ch === "\n") result += "\\n";
      else if (ch === "\r") result += "\\r";
      else if (ch === "\t") result += "\\t";
      else result += ch;
    } else {
      result += ch;
    }
  }

  return result;
}

function extractJSON(content: string): any {
  try {
    return JSON.parse(content);
  } catch {}

  const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (codeBlockMatch) {
    try {
      return JSON.parse(codeBlockMatch[1].trim());
    } catch {
      try {
        return JSON.parse(fixControl(codeBlockMatch[1].trim()));
      } catch {}
    }
  }

  const braceStart = content.indexOf("{");
  const braceEnd = content.lastIndexOf("}");
  if (braceStart !== -1 && braceEnd !== -1) {
    const extracted = content.slice(braceStart, braceEnd + 1);
    try {
      return JSON.parse(fixControl(extracted));
    } catch {}

    const cleaned = extracted.replace(/,\s*([}\]])/g, "$1");
    try {
      return JSON.parse(fixControl(cleaned));
    } catch {}
  }

  throw new Error("JSON parsing failed: " + content.slice(0, 200));
}

async function callGLM(
  messages: ChatMessage[],
  apiKey: string = "YOUR_API_KEY"
): Promise<any> {
  const response = await fetch(GLM_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "glm-5",
      messages,
      temperature: 0.3,
      max_tokens: 4096,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`GLM API error ${response.status}: ${errorBody}`);
  }

  const data = await response.json();
  const content: string = data.choices[0].message.content;

  if (!content || content.trim() === "") {
    throw new Error("GLM returned empty content (thinking only, no output)");
  }

  return extractJSON(content);
}
```

</details>

## 마치며

가장 당황스러웠던 것은 에러 메시지가 "잔액 부족"이었다는 점입니다. 서버는 크레딧이 충분하다고 말하는데 API는 계속 429를 뱉었고, 나는 4일 동안 결제 문제를 의심하며 완전히 엉뚱한 곳을 파고 있었습니다. 결국 원인은 URL 경로 한 단계(`/coding/`)였습니다. 이 경험은 에러 메시지를 문자 그대로 믿는 것의 위험함을 뼈저리게 가르쳐 주었습니다. 시스템이 보내는 메시지는 원인이 아니라 증상일 뿐이며, 진짜 원인은 항상 한 단계 더 깊은 곳에 숨어 있다는 걸 깨달았습니다.

두 번째 교훈은 "급하게 고친 코드는 상황을 더 악화시킨다"는 것이었습니다. JSON 파싱 실패를 보자마자 `split('\n').join('\\n')`으로 덮어씌웠다가, 오히려 구조적 줄바꿈까지 망가뜨려 디버깅이 더 어려워졌습니다. 결국 따옴표 안팎을 구분하는 상태 머신(`fixControl`)을 구현해야 제대로 된 해결책이 나왔습니다. 겉으로는 비슷해 보이는 두 접근 사이에는, 실제로는 문제를 이해했는지의 여부라는 큰 차이가 있었습니다.

앞으로 어떤 LLM을 연동하든 가장 먼저 확인하는 것은 "이 모델은 응답을 어떻게 깨뜨리는가"가 될 것입니다. 그리고 응답 처리는 항상 방어적으로, 여러 단계의 복구 로직을 갖추는 습관을 들이려 합니다. 에러 메시지를 의심하고, 빠른 수정보다 정확한 이해를 택하는 태도야말로 이 4일이 남긴 가장 값진 자산입니다.
