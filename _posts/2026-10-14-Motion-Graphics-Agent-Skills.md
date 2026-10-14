---
layout: post
title: "모션그래픽 AI 에이전트 스킬 조사와 실측 배틀: 무료 생태계는 어디까지 될까"
categories: [AI, Tools]
description: "무료 모션그래픽 에이전트 스킬 10곳을 비교하고, 같은 과제를 moviepy·Manim·Remotion으로, 그리고 HyperFrames와 Revideo로 각각 만들어 실측했습니다. 어느 툴이 품질을 내고 대가는 무엇일까요?"
keywords: [모션그래픽, 에이전트 스킬, Remotion, Manim, HyperFrames, Revideo, motion graphics]
toc: true
toc_sticky: true
---

> 모션그래픽 AI 에이전트 스킬 생태계 조사(2026-10-14)와 실측 배틀 결과를 정리했습니다. 스타·포크 수는 조사 시점 GitHub API 기준 변동값입니다.

코딩 에이전트에 "모션그래픽 영상 만들어줘"라고 부탁하면 어느 정도 품질이 나올까요. 이 질문에 답하려고 무료(오픈소스) 스킬 생태계를 조사하고, 같은 과제를 여러 도구로 직접 만들어 비교해 봤습니다. 조사와 실측을 한 문서에 담은 기록입니다.

핵심은 두 가지였습니다. 첫째, SKILL.md 폴더 형식의 스킬들이 단순한 프롬프트 모음이 아니라 "렌더하고 프레임을 추출해 검증하고 수정하는 루프"와 모션 크래프트 규칙을 강제한다는 점. 둘째, 그 결과가 프롬프트 한 줄짜리 결과물과 전문가급 사이에서 어디쯤에 위치하는가입니다.

## TL;DR

- 무료 모션그래픽 에이전트 스킬 생태계가 성숙했다. 상위 리포 스타 총합 5,000+
- 스킬은 전부 SKILL.md 폴더 형식이라 Claude Code, Codex, Cursor, opencode와 호환된다
- 품질의 핵심은 검증 루프와 모션 규칙을 스킬이 강제하는 것이다
- 추천 3축은 규모(iart-ai), 품질 규칙(haidrrrry), 마케팅(charlie947)이다
- 2D 모션그래픽 전 경로에 GPU는 불필요하다. 병목은 CPU 시간과 RAM이다
- 실측 배틀 1탄: 품질은 Remotion+스킬(★5), 속도와 간결함은 Manim(웜 렌더 4.12s)
- 실측 배틀 2탄: 기술 설명 영상은 Revideo가 렌더 3.3배 빠르고 육안 품질도 우세

## 1. 생태계 조사: 무료 스킬 10곳 비교

조사 시점 2026-10-14, GitHub API 기준입니다. 라이선스가 커스텀 또는 미표기인 리포는 사용 전 원본 확인이 필요합니다.

| 리포 | 스타 | 라이선스 | 용도 |
|---|---|---|---|
| nateherkai/hyperframes-student-kit | 1,403 | 커스텀 | 영상 편집·쇼츠, 14스킬 + 406 모션그래픽 카드 |
| iart-ai/motion-skills | 804 | MIT | 54스킬/17팩. 키네틱 타이포부터 데이터 viz, WebGL, Manim까지 |
| Barty-Bart/motion-graphics | 660 | 커스텀 | Claude Code·Codex용 모션그래픽 스킬 |
| bangtutorial/bang-motion | 594 | MIT | 브라우저용. index.html 단일 출력 |
| haidrrrry/claude-remotion-skill | 418 | MIT | Remotion 기반 전문 모션 규칙 |
| Tejashmakwana/motionmaxxing | 408 | Apache-2.0 | AI 영상을 모션 디자이너 작품급으로 업그레이드 |
| charlie947/motion-graphics-skills | 269 | MIT | 런치영상 15스킬. brand-intake 워크플로 |
| Anil-matcha/vox-ai-motion-graphics-generator | 256 | 미표기 | Vox 스타일 페이퍼-콜라주 설명 영상 자동화 |
| makevoid/motion-graphics-music-video-skill | 153 | MIT | 음악 트랙 + 프롬프트로 뮤직비디오 |
| Miftahul-Islam-Efaz/Motion-graphics-skill | 95 | 미표기 | 기획부터 사운드 디자인까지 전체 파이프라인 |

## 2. Top 3 상세 분석

### 2-1. iart-ai/motion-skills(규모 중시)

54개 스킬을 17팩으로 묶은 규모 최대 리포입니다. 렌더링은 Remotion과 Manim을 씁니다. tiktok-video(4), explainer(5), motion-design(9), web-animation(9), data-animation(3), webgl(3) 등 목적별 팩 구성이라 필요한 장르만 골라 설치할 수 있습니다.

검증 인프라가 핵심입니다. deliver-and-verify 루프로 프레임을 렌더하고 스크린샷을 떠서 확인하며, scripts/에 프레임 추출, 콘택트시트, MP4 프로브 도구가 딸려 있습니다. 설치는 한 줄입니다.

```bash
npx skills add iart-ai/
```

### 2-2. haidrrrry/claude-remotion-skill(품질 규칙 학습)

10가지 강제 규칙으로 전문가급 모션을 스킬이 보장하는 리포입니다. 규칙의 뼈대는 이렇습니다.

- 리니어 보간 금지. 스프링/베지어 + clamp만 허용
- 입장 애니메이션은 2~3개 속성을 동시에(fade + rise + scale)
- 스태거는 3~6프레임 오프셋, 퇴장은 입장보다 빠르게
- 5레이어 스택: bg mesh → 에셋 → 그래픽 → 그레이드 → 그레인 + 비네트
- 모든 스틸에 Ken Burns, 유휴 요소엔 sin파 미세동작
- fps 기반 타이밍(매직 넘버 금지), 단일 theme.ts
- 렌더 → 프레임 검사 → 수정 → 재렌더 강제

구성은 SKILL.md에 references/motion-patterns.md(17개 복붙 컴포넌트), design-rules.md, theme.ts가 따라옵니다. 프로필 프로모, 15.5초 제품 프로모, 120BPM 비트싱크 편집 같은 예제 4종도 포함돼 있습니다.

### 2-3. charlie947/motion-graphics-skills(마케팅 특화)

런치영상 특화 15스킬입니다. brand-intake 스킬이 brand.md와 MOTION.md를 먼저 생성하고, 이후 모든 스킬이 이 문서를 우선 참조하는 구조가 특징입니다. 스킬 목록은 brand-intake, launch-video, apple-launch-film, vox-explainer, animated-chart, milestone-reveal, title-sequence-3d, reel-export 등입니다.

하우스 룰이 흥미롭습니다. 승인된 목록 외 수치 창작 금지, 타이프라이터 텍스트와 글로우와 보라→파랑 배경 같은 "AI 냄새" 기본값 금지, 모션 온 트웅스(24fps 2프레임 홀드), 첫 3초 훅, 익스포트 전 미드샷 프레임 체크, 로고를 기억으로 재그리기 금지까지. 디테일한 금지 목록이 오히려 품질의 증명입니다.

## 3. 품질 평가: 어디까지 될까

### 잘 나오는 것

키네틱 타이포그래피, 로고 애니메이션, 브랜드 인트로는 ★5입니다. 결정론적 코드 렌더링이라 텍스트, 색, 타이밍이 정확하게 보장됩니다. 생성형 비디오 모델과의 차이가 여기서 드러납니다. 할루시네이션이 없고, 재렌더가 가능하고, 브랜드 통제가 됩니다.

데이터 시각화와 차트 애니메이션도 ★5입니다. 코드로 그리므로 숫자가 변형되지 않습니다. Vox 스타일 설명 영상, 제품 런치 필름, 릴스/쇼츠 변환, 웹 모션(GSAP/SVG/Lottie)은 검증된 템플릿이 존재하는 장르라 ★4 수준입니다.

### 안 되는 것

포토리랄리스틱 인물 얼굴은 코드로 불가능합니다. 이미지 모델이 필요한 영역이고, charlie947 README에도 공식 한계로 명시돼 있습니다. 실사 footage에 그래픽을 얹을 때도 Remotion은 얼굴이나 손의 위치를 모르므로 수동 픽셀 좌표와 스크럽 확인이 필요합니다.

### 현실적 기대치

rescroll.ai의 2026-10-03 실사용 후기가 좋은 보정 자료입니다. Remotion Agent Skills는 2026년 1월 출시 후 데모 약 1,300만 뷰의 바이럴을 기록했지만, 숙련 개발자도 talking-head 영상에 그래픽 하나 얹는 데 1시간 이상, 첫 시도엔 반나절이 걸렸습니다. Node.js, 터미널, 워드레벨 타임스탬프(Whisper), ms→프레임 변환, 헤드리스 Chrome 렌더(60초 1080×1920 = 1,800페이지 렌더) 같은 사전 지식이 전제되는 도구입니다.

결론을 옮기면 개발자이거나 코드가 가능한 모션 디자이너에게는 "만들어진 가장 강력한 영상 도구급", 비개발자 크리에이터에게는 진입장벽이 높습니다. 프롬프트 한 줄로 flat fades 수준이 아니라 전문가급 easing과 스태거와 그레이드가 나오는 이유가 스킬의 강제 규칙입니다. 스킬 없이는 결과가 초라해집니다.

### 라이선스 주의: "무료"의 조건

스킬 자체는 전부 무료(MIT, Apache-2.0)지만 Remotion 프레임워크는 개인 및 3인 이하 회사만 무료입니다. 4인 이상 기업은 $25/seat/월이므로 기업 사용 시 유료입니다. 완전 무료 대안으로는 Manim, Motion Canvas, HyperFrames, Revideo, MotionScript, Morphable이 있습니다.

## 4. 시작하는 방법과 GPU 문제

SKILL.md 폴더 형식은 opencode와도 호환됩니다. ~/.claude/skills/ 또는 ~/.config/opencode/skills/에 복사하면 됩니다. 요구 환경은 Node.js와 ffmpeg뿐입니다.

"GPU가 필요한가?"에 대한 답은 2D 모션그래픽 전 경로에서 불필요입니다. 렌더링 경로별로 정리하면 이렇습니다.

| 경로 | 렌더 방식 | GPU 필요 |
|---|---|---|
| Remotion | 헤드리스 Chrome 프레임 렌더 → ffmpeg 인코딩 | 불필요(CPU) |
| Manim(2D) | Cairo 라이브러리 렌더 | 불필요(CPU) |
| HyperFrames / Motion Canvas | 브라우저 + ffmpeg | 불필요(CPU) |
| WebGL/Three.js 3D | 소프트웨어 렌더링(SwiftShader) 폴백 존재 | 있으면 빠름 |
| 로컬 이미지 생성 AI | 로컬 추론 | 사실상 필수 |

테스트한 머신(NVIDIA GPU 없음, 8코어, RAM 7.8GB) 기준으로 병목은 GPU가 아니라 CPU 시간과 RAM이었습니다. 60초 1080×1920은 프레임 1,800회 렌더라 8코어로 수 분이 걸리는 계산이고, RAM이 빠듯하면 Remotion 동시 렌더 수를 2~4로 제한하는 것이 권장됩니다. 포토리얼 에셋만 로컬 생성이 불가능하니 클라우드 이미지 AI나 실사 촬영으로 대체하면 됩니다.

## 5. 사용 시나리오 6종

테스트 머신 기준으로 실행 가능한 시나리오 여섯 가지입니다. 난이도는 ★(쉬움)부터 ★★★(첫 도전)까지입니다.

| 시나리오 | 스킬 | 난이도 | 예상 시간 |
|---|---|---|---|
| 3초 로고 스팅 | haidrrrry | ★ | 렌더 1~2분 |
| Vox 스타일 설명 영상 30~60초 | iart-ai / charlie947 | ★★ | 검증 루프 포함 30분~1시간 |
| 차트 애니메이션 8~15초 루프 | iart-ai / charlie947 | ★ | 렌더 2~5분 |
| 쇼츠/릴스 변환 1080×1920 | iart-ai / charlie947 | ★★★ | 첫 회차 1시간~반나절 |
| 모션그래픽 뮤직비디오 | makevoid | ★★ | 3분 트랙 렌더 10~20분 |
| Lower Thirds 방송 오버레이 | iart-ai | ★ | 렌더 1~3분 |

프롬프트 작성 팁이 몇 가지 있습니다. 수치가 들어가는 콘텐츠는 "사실은 이 목록에서만 사용"이라고 목록을 주고, 차트는 "값은 절대 반올림하지 마"라고 못박습니다. 이징은 반드시 명시합니다. 비워 두면 도구마다 다른 곡선이 들어갑니다.

권장 진행 경로는 로고 스팅으로 스킬을 검증하고, 차트로 정확성을 확인한 뒤 목적에 맞는 본편으로 확장하는 순서입니다.

## 6. 실측 배틀 1탄: 같은 과제, 3개 도구

과제는 "SALES MILESTONE" 키네틱 타이포와 0→10,000 카운트업, 5.0초, 1920×1080, 30fps, 무음으로 동일했습니다. moviepy 1.0.3(PIL 프레임 드로잉), Manim CE v0.22(conda-forge env), Remotion v4 + haidrrrry 스킬 10규칙 세 벌로 각각 만들어 비교했습니다. 렌더 재측정은 순차 격리 실행 기준입니다.

| 항목 | moviepy | Manim | Remotion (+스킬) |
|---|---|---|---|
| 설치 | pip 사용자 사이트(약 10s) | conda-forge 72초 우회 필수 | npm 3.5s(캐시 히트) |
| 코드 줄수 | 79줄 | 42줄(최소) | 364줄(최대) |
| 렌더 1차/재측정 | 23.2s / 13.0s | 7.32s / 4.12s(최저) | 52.5s / 26.0s(최대) |
| 파일 크기 | 163.6K(최소) | 290K | 1.01MB(최대) |
| 비트레이트 | 268 kb/s | 476 kb/s | 1,686 kb/s(2위의 3.5배) |
| 이징 | easeOutCubic 직접 구현 | ease_out_cubic | spring(감쇠 30, 강성 60) |
| 텍스트 렌더 | PIL 비트맵(약간 소프트) | Pango 벡터(가장 선명) | 브라우저(탭룰러 넘버) |
| 품질 총평 | ★2.5 | ★3.5 | ★5 |

### 결과물

<figure>
  <video controls muted loop preload="metadata" style="width:100%;max-width:640px">
    <source src="/assets/videos/posts/motion-battle/battle1-remotion.mp4" type="video/mp4"/>
  </video>
  <figcaption>Remotion + haidrrrry 스킬. 364줄, 렌더 52.5s, 품질 총평 ★5</figcaption>
</figure>

<figure>
  <video controls muted loop preload="metadata" style="width:100%;max-width:640px">
    <source src="/assets/videos/posts/motion-battle/battle1-manim.mp4" type="video/mp4"/>
  </video>
  <figcaption>Manim CE v0.22. 42줄, 웜 렌더 4.12s, 품질 총평 ★3.5</figcaption>
</figure>

<figure>
  <video controls muted loop preload="metadata" style="width:100%;max-width:640px">
    <source src="/assets/videos/posts/motion-battle/battle1-moviepy.mp4" type="video/mp4"/>
  </video>
  <figcaption>moviepy 1.0.3. 79줄, 최소 파일 크기 163.6K, 품질 총평 ★2.5</figcaption>
</figure>

### 프레임 비교에서 드러난 것

t=0.5s에서 Remotion만 글자별 스태거 등장과 그레이딩이 진행 중이었습니다. PIL 정량 분석으로 코너 색이 4개 모두 달랐는데(#0b1321~#060f1e), 그라디언트의 실증입니다.

<figure>
  <img src="/assets/images/posts/motion-battle/compare_t0.5.jpg" alt="t=0.5초 3도구 정지 프레임 비교: moviepy는 타이틀 페이드인 중, Manim은 타이틀과 0 즉시 표시, Remotion은 글자별 스태거와 그라디언트 진행 중" loading="lazy"/>
  <figcaption>t=0.5s. Remotion만 스태거 등장과 그레이딩이 진행 중이다</figcaption>
</figure>

가장 흥미로운 지점은 t=2.5s입니다. 동일 스펙인데 카운트 값이 8,750(moviepy, Manim)과 9,999(Remotion)로 갈렸습니다. 스프링 이징의 조기 수렴(약 2.83s 도달) 때문인데, 이징을 비워 두거나 통일하지 않으면 프레임에 직접 노출된다는 경고 사례입니다.

<figure>
  <img src="/assets/images/posts/motion-battle/compare_t2.5.jpg" alt="t=2.5초 3도구 카운트 값 비교: 8,750과 8,750과 9,999로 이징 곡선 차이가 노출" loading="lazy"/>
  <figcaption>t=2.5s. 동일 스펙인데 카운트 값이 갈린다(아래 설명)</figcaption>
</figure>

t=4.2s 강조 연출은 격차가 극대화됐습니다. Remotion은 색 전환과 숫자 글로우와 비네트, Manim은 전체 블록 착색(강조색 픽셀 6,618로 최다), moviepy는 숫자만 색 전환(5,038)이었습니다.

<figure>
  <img src="/assets/images/posts/motion-battle/compare_t4.2.jpg" alt="t=4.2초 강조 연출 비교: Remotion은 글로우와 비네트, Manim은 전체 색 전환, moviepy는 숫자만 색 전환" loading="lazy"/>
  <figcaption>t=4.2s. 강조 연출의 격차가 극대화되는 순간</figcaption>
</figure>

### 도구별 총평

moviepy는 인코딩 프레임워크일 뿐입니다. 카운트업, 이징, 텍스트 등 모션 로직을 전부 직접 구현해야 하고, ImageMagick이 없으면 TextClip조차 불가해 PIL 프레임 드로잉 우회가 사실상 표준 경로입니다. 기존 파이썬 파이프라인과의 조립에는 유리합니다.

Manim은 속도와 간결함이 최강입니다. 42줄에 웜 렌더 4.12s라 반복 수정 사이클에 가장 유리하고 Pango 벡터 텍스트가 가장 선명합니다. 대가는 설치의 번거로움입니다. manimpango Linux 휠 부재로 pip 경로가 막히니 conda-forge 환경 구성이 필수입니다.

Remotion + 스킬은 품질이 압도적입니다. 스태거, 글로우, 비네트, 탭룰러 넘버가 프레임에 명확히 각인되고 비트레이트 1,686 kb/s가 시각 밀도를 수치로 증명합니다. 대가는 렌더 52.5s와 364줄, 1.01MB, React 숙련 전제, 기업 라이선스입니다.

### 핵심 발견 4가지

1. moviepy는 조립용이다. 모션 로직은 전부 자체 구현해야 한다
2. Manim이 가장 빠르고 짧지만 pip 차단으로 conda 우회가 필수다
3. Remotion+스킬은 품질 압도적이나 렌더·코드량·라이선스 비용이 최대다
4. 셋 다 ffmpeg에 의존한다. 내장 바이너리 심링크 하나로 전부 해결된다

측정 한계도 남깁니다. 재측정값은 웜 캐시 기준이고 1차 렌더는 병렬 태스크 환경의 원값이라 경합 오염이 가능합니다. 단일 클립, 단일 과제 기준이므로 일반화에는 주의가 필요하고, ffmpeg은 imageio-ffmpeg 내장 v7.0.2(시스템 ffmpeg 아님)라 프리셋 차이가 비트레이트에 영향을 줄 수 있습니다.

## 7. 배틀에서 얻은 제작 가이드라인

### 도구 선택 결정

| 만들고 싶은 것 | 선택 | 실측 근거 |
|---|---|---|
| 숫자 카운트업, 수학/개념 설명 | Manim | 재측정 4.12s, 42줄, Pango 선명도 |
| 브랜드 품질, 마케팅 데모 | Remotion + 스킬 | 품질 ★5. 대가는 렌더 52.5s, 364줄 |
| 단순 조립, 파이썬 통합 | moviepy | pip 즉시 설치, 최소 파일 크기 |

### 기획 템플릿

배틀의 공통 스펙이 그대로 재사용 가능한 템플릿입니다. 핵심은 스토리보드 4단계 구조, 수치로 못박은 출력 사양, 이징 명시 셋입니다.

```text
과제: "SALES MILESTONE" 키네틱 타이포 + 0→10,000 카운트업
스토리보드 4단계(총 5.0초): 입장 20% 타이틀 / 전개 60% 카운트업
  / 강조 10% 도달 순간 / 퇴장 10% 페이드아웃
출력 사양: 1920×1080 · 30fps · 5.0초 · 무음 · 배경 #0d1117(hex 명시)
이징: 반드시 명시(예: easeOutCubic / spring). 비워 두면 도구마다 다르다
```

### 품질 루프

세 도구 모두에 렌더 → 프레임 추출 → 검사 → 수정 루프를 적용해 유효성을 확인했습니다. 실제로 사용한 검사 지점은 이렇습니다.

- 프레임 추출: ffmpeg로 t=0.5 / 2.5 / 4.2초 3시점 정지 프레임 덤프
- 검사: 정지 프레임 비교 + PIL 정량 분석(엣지 밀도, 코너 색, 강조색 픽셀 수)
- 보정: 종료 직후 시각으로 seek하면 빈 출력이 나온다. 종료 이전 시점으로 잡을 것

### 환경 함정 5종과 우회로

sudo 불가 환경에서 실제로 만난 함정들입니다.

| 함정 | 증상 | 우회로 |
|---|---|---|
| ffmpeg이 PATH에 없음 | 렌더·프레임 덤프 전부 차단 | imageio-ffmpeg 내장 바이너리 심링크 |
| ImageMagick 부재 | moviepy TextClip 불가 | PIL로 프레임 생성 후 ImageSequenceClip |
| manimpango Linux 휠 부재 | pip으로 Manim 설치 차단 | micromamba conda-forge 환경(72초) |
| conda × 사용자 site 충돌 | click 등 버전 충돌로 실행 실패 | PYTHONNOUSERSITE=1 지정 |
| Chrome Headless Shell 다운로드 | 네트워크 실패·시간 왜곡 리스크 | 기존 chromium을 browserExecutable로 재활용 |

## 8. 실측 배틀 2탄: HyperFrames vs Revideo

1탄의 교훈을 바탕으로 이번엔 42.0초짜리 "딥러닝 최적화" 설명 영상에 도전했습니다. 스터디 노트에서 스토리를 추출·각색했고, 씬 5개와 누적 타이밍, 카피, 수식, 옵티마이저 궤적 좌표, Dropout 고정 마스크까지 명시한 스토리보드 계약서를 먼저 작성해 양 툴이 동일 스펙으로 제작했습니다.

대상은 HyperFrames(heygen-com, ★63,175, Apache-2.0, HTML 저작)와 Revideo(midrender, ★4,106, MIT, Motion Canvas 포크 TS 제너레이터)입니다.

| 씬 | 내용 | 길이 |
|---|---|---|
| S1 | 오프닝 | 6s |
| S2 | SGD의 한계, 등고선 지그재그 | 8s |
| S3 | Momentum/RMSProp/Adam 3색 궤적 레이스 + 갱신식 카드 | 12s |
| S4 | Dropout, L1/L2 | 10s |
| S5 | 요약 3줄 + 엔딩 | 6s |

### 결과 비교

| 항목 | HyperFrames | Revideo |
|---|---|---|
| 설치 | init 21.5s + npm 39.6s | scaffolder 인터랙티브 전용이라 템플릿 직접 다운로드(33.1s) |
| 렌더링 | headless Chromium 스크린샷 + FFmpeg | WASM 익스포터(씬 구동엔 Puppeteer 필요) |
| 순차 재렌더 | 1m46s | 31.7s(3.3배 빠름) |
| 최종 길이 | 42.000s | 42.033s |
| 파일 크기 · 비트레이트 | 3.97MB · 756kb/s | 2.85MB · 543kb/s |
| 프레임 PNG 밀도 | 445~582KB(그레이드·비네트·그레인) | 75~336KB(플랫 벡터) |
| 스타일 | 영화적 질감·텍스처 | 깔끔한 기술 다이어그램 |

### 결과물

<figure>
  <video controls muted loop preload="metadata" style="width:100%;max-width:640px">
    <source src="/assets/videos/posts/motion-battle/battle2-revideo.mp4" type="video/mp4"/>
  </video>
  <figcaption>Revideo. 순차 재렌더 31.7s, 육안 평가 우세</figcaption>
</figure>

<figure>
  <video controls muted loop preload="metadata" style="width:100%;max-width:640px">
    <source src="/assets/videos/posts/motion-battle/battle2-hyperframes.mp4" type="video/mp4"/>
  </video>
  <figcaption>HyperFrames. 순차 재렌더 1m46s, 영화적 질감</figcaption>
</figure>

양쪽 모두 계약을 완수했습니다. 최종 길이 42.000s와 42.033s로 누적 타이밍 계약도 충족했고, 스타일만 정확히 갈렸습니다.

<figure>
  <img src="/assets/images/posts/motion-battle/battle2-compare-t20.jpg" alt="t=20초 좌 HyperFrames 우 Revideo 정지 프레임 비교: 옵티마이저 3색 궤적 레이스 장면" loading="lazy"/>
  <figcaption>t=20s. 좌 HyperFrames(영화적 질감) 우 Revideo(플랫 벡터). S3 옵티마이저 궤적 레이스 장면</figcaption>
</figure>

<figure>
  <img src="/assets/images/posts/motion-battle/battle2-compare-t39.jpg" alt="t=39초 좌 HyperFrames 우 Revideo 정지 프레임 비교: 요약 3줄 엔딩 장면" loading="lazy"/>
  <figcaption>t=39s. 요약 엔딩 장면의 스타일 대비</figcaption>
</figure>

### 실전 함정 6종

1. Revideo scaffolder는 플래그·stdin 미지원이다. 템플릿 직접 다운로드가 우회로다
2. WASM 익스포터여도 PUPPETEER_EXECUTABLE_PATH 미설정 시 renderVideo가 즉시 실패한다
3. Revideo 프로젝트 기본값이 1080×1080이다. 1920×1080 수동 수정 필수다
4. all() 지속시간은 포함 제너레이터의 max다. 순차 for-loop에 waitFor를 넣으면 늘어난다
5. HyperFrames는 FFprobe가 별도로 필요하다. imageio-ffmpeg 번들엔 없다
6. HyperFrames의 GSAP은 CDN 로드다. 오프라인 렌더 시 로컬 vendor 전환이 필요하다

함정 4의 실측 디테일이 인상적입니다. S1의 1.05s 스태거가 순차 루프에서 3.30s로 늘어나 전체가 44.27s가 되는 버그였고, 병렬 all(...delayed()) 구조로 바꿔 42.03s에 맞췄습니다.
6. HyperFrames의 GSAP은 CDN 로드다. 오프라인 렌더 시 로컬 vendor 전환이 필요하다

함정 4의 실측 디테일이 인상적입니다. S1의 1.05s 스태거가 순차 루프에서 3.30s로 늘어나 전체가 44.27s가 되는 버그였고, 병렬 all(...delayed()) 구조로 바꿔 42.03s에 맞췄습니다.

### 육안 평가와 시사점

결과 영상을 직접 시청한 최종 판정은 "둘 다 손 봐야 하지만 Revideo가 훨씬 낫다"였습니다. 정량 지표(프레임 밀도, 비트레이트)와 무관하게 육안 체감 품질은 Revideo 우세였고, 추정 근거는 세 가지입니다. WebGL/WASM 벡터 직접 렌더링 대 스크린샷 캡처의 미세 소프트니스 차이, 기술 설명 콘텐츠엔 깔끔한 벡터 다이어그램 스타일이 적합하고 그레인·비네트는 오히려 방해라는 점, 그리고 렌더 3.3배 속도가 이터레이션 체감으로 직결된다는 점입니다.

시사점은 장르에 따라 최적 툴이 갈린다는 것입니다. 기술과 교육 설명엔 Revideo, 마케팅과 시네마틱엔 스킬 규칙이 붙은 React·HTML 계열(Remotion, HyperFrames)이 맞습니다. 프레임 밀도 같은 정량 지표는 텍스처 정보량이지 지각 품질이 아니라는 것도 실증됐습니다. 두 툴 모두 완전 무료(MIT/Apache)라 Remotion의 라이선스 이슈도 없습니다.

측정 한계는 웜 캐시 순차 측정, software GPU 환경, 단일 과제·단일 클립 기준이라는 점입니다.

## 마무리: 핵심 요점

1. 무료 스킬 생태계는 성숙했다. 3축은 규모, 품질 규칙, 마케팅이다
2. 품질의 원천은 프롬프트가 아니라 검증 루프와 강제 규칙이다
3. GPU는 2D 모션그래픽에 불필요하다. 병목은 CPU 시간과 RAM이다
4. 배틀 1탄: 품질은 Remotion+스킬, 속도와 간결함은 Manim, moviepy는 조립용이다
5. 배틀 2탄: 기술 설명엔 Revideo(3.3배 빠름), 시네마틱엔 HyperFrames다
6. 정량 지표와 육안 품질은 다르다. 장르에 맞는 툴을 고르는 것이 이긴다

## 출처

모든 링크는 조사 시점(2026-10-14) 기준 유효합니다.

- github.com/iart-ai/motion-skills (README 원문 확인)
- github.com/haidrrrry/claude-remotion-skill (README 원문 확인)
- github.com/charlie947/motion-graphics-skills (README 원문 확인)
- 비교표 전체 리포: nateherkai/hyperframes-student-kit, Barty-Bart/motion-graphics,
  bangtutorial/bang-motion, Tejashmakwana/motionmaxxing 외
- remotion.dev/docs/ai/claude-code-plugin (공식 문서)
- rescroll.ai/blog/claude-code-remotion-motion-graphics-2026 (2026-10-03, 실사용 후기)
- motionscript.dev, morphable.video
- autoae.online/blog/open-source-remotion-alternatives-2026
- 스타·포크 수: GitHub API (2026-10-14 조회)
