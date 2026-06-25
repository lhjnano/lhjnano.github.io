---
layout: post-nocompress
title: "ZFS CPU 성능 패턴 분석 — 정적 분석과 실측 벤치마크의 간극"
categories: [Linux, Performance, Filesystem]
description: OpenZFS 소스 코드를 정적 분석으로 2개 Critical 안티패턴을 발견했지만, 실측 벤치마크에서는 성능 차이가 없었습니다. 왜 그런지 분석합니다.
keywords: [ZFS, OpenZFS, 성능최적화, SIMD, LZ4, ZSTD, ARC, 벤치마크]
toc: true
toc_sticky: true
chartjs: true
---

## Hook

정적 분석은 강력합니다. 소스 코드만 보고 "이건 Critical 성능 버그다"라고 진단할 수 있으니까요. 하지만 코드에서 발견한 안티패턴이 항상 실제 성능 저하로 이어지는 것은 아닙니다.

OpenZFS 소스 코드를 Intel의 CPU 성능 패턴 카탈로그로 분석했더니 2개의 Critical 안티패턴이 나왔습니다. LZ4의 `restrict` 무효화와 ZSTD의 ASM 비활성화. "이거 고치면 5–20% 빨라지겠네?"라고 생각하기 쉽습니다. 그래서 실제로 벤치마크를 돌려봤습니다. 결과는 — **성능 차이 0%**. 컴파일러는 우리가 생각하는 것보다 훨씬 똑똑했습니다.

## TL;DR

- **정적 분석만으로 성능을 판단하면 안 됩니다** — LZ4 `restrict` 무효화는 코드상 Critical이지만, A/B 벤치마크 결과 처리량 차이 0%, CPI 동일
- **ZSTD ASM 비활성화는 의도적입니다** — 커널 빌드 호환성(objtool/ORC)과 데이터 손상 리스크를 고려한 설계 결정
- **체크섬 SIMD와 ARC는 모범 사례 수준** — BLAKE3 AVX2 2,635 MB/s 실측, false sharing 완벽 방지
- **최종 결론: OpenZFS는 현재 성능 관점에서 잘 최적화되어 있음**

## Background: 분석 대상과 방법

### 2단계 분석 절차

| 단계 | 방법 | 목적 |
|---|---|---|
| 1단계 | 정적 소스 코드 분석 | 패턴 카탈로그 기반 안티패턴 탐색 |
| 2단계 | 실측 벤치마크 | 발견된 안티패턴의 실제 성능 영향 정량화 |

정적 분석만으로는 "이론적으로 느릴 수 있다"는까지만 알 수 있습니다. 실제로 느린지, 얼마나 느린지는 반드시 실측해야 합니다.

### ZFS 핫 패스

```
┌─────────────────────────────────────────────────┐
│                  ZFS Hot Path                     │
├──────────┬──────────────┬────────────────────────┤
│ Checksum │ Compression  │   ARC Memory Mgmt      │
│ (Fletcher│ (LZ4 / ZSTD  │   (Cache + Lock +      │
│  /SHA/   │  /GZIP)      │    Per-CPU Stats)      │
│  BLAKE3) │              │                         │
└──────────┴──────────────┴────────────────────────┘
```

분석은 12가지 CPU 성능 안티패턴을 정의하는 패턴 카탈로그를 기준으로 진행했습니다.

## Solution: 영역별 분석 결과

### 1. 체크섬 SIMD — 실측으로 확인한 모범 사례

ZFS 내장 벤치마크 도구(`chksum_bench`)로 알고리즘별·SIMD 경로별 처리량을 측정했습니다. 아래 차트는 BLAKE3의 SIMD 구현별 성능 차이를 보여줍니다:

<div style="margin: 24px 0;">
  <canvas id="chart-blake3-simd" height="200"></canvas>
</div>

> BLAKE3 generic 166 MB/s → AVX2 2,635 MB/s = **15.9배 향상**. CPU 디스패치가 정상 동작하여 AVX2 경로가 자동 선택됩니다.

전체 알고리즘 비교 (4M 블록 기준):

| 알고리즘 / 구현 | 4K | 64K | 1M | 4M |
|---|---|---|---|---|
| **BLAKE3 AVX2** | **1,482** | **2,842** | 1,725 | **2,635** |
| BLAKE3 SSE4.1 | 1,315 | 1,237 | 1,070 | 1,426 |
| BLAKE3 generic | 147 | 180 | 171 | 166 |
| Edon-R generic | 1,149 | 1,200 | 1,221 | 832 |
| SHA-512 AVX2 | 558 | 606 | 502 | 521 |
| SHA-256 AVX2 | 337 | 407 | 372 | 380 |
| SHA-256 generic | 155 | 187 | 184 | 186 |
| Skein generic | 495 | 479 | 516 | 486 |

Fletcher4의 4가지 핵심 패턴도 모두 정상입니다:

| 패턴 | 상태 | 비고 |
|---|---|---|
| `cpu-dispatch` | 정상 | SSE2 → AVX2 → AVX-512 계층적 선택, tunable 지원 |
| `missing-vzeroupper` | 정상 | 모든 AVX 경로에 `vzeroupper` 포함 |
| `serial-accumulator` | 정상 | SIMD 벡터 연산으로 데이터 병렬성 확보 |
| `unroll-loop` | 정상 | AVX-512: 8-way unroll (32바이트/iteration) |

### 2. 압축 분석 — 정적 분석과 실측의 간극

#### LZ4 `#define restrict` — 정적 발견: Critical / 실측 결과: 영향 없음

정적 분석에서는 LZ4의 `restrict` 키워드가 빈 매크로로 정의되어 완전히 무효화된 것을 발견했습니다:

```c
// module/zfs/lz4.c:133, lz4_zfs.c:264
#ifndef restrict
#define restrict            // ← 빈 정의! C99 restrict 키워드 무효화
#endif
```

이론적으로는 컴파일러의 alias 분석이 차단되어 메모리 최적화, auto-vectorization, 레지스터 할당 최적화가 모두 무효가 됩니다. "5–20% 성능 저하 가능성"이라는 진단이 나옵니다.

**그래서 A/B 벤치마크를 실행했습니다.** ZFS master(2.4.99) 소스에서 Baseline(원본)과 Modified(`__restrict`)를 동일 CFLAGS로 컴파일하여 50,000회 반복 측정했습니다:

<div style="margin: 24px 0;">
  <canvas id="chart-lz4-ab" height="200"></canvas>
</div>

차트에서 명확히 보이듯, 두 선이 거의 겹칩니다. 블록 크기별 수치:

| 블록 크기 | Baseline (restrict 무효) | Modified (\_\_restrict) | 차이 |
|---|---|---|---|
| 4 KB | 2,152 MB/s | 1,800 MB/s | -16% (노이즈) |
| 16 KB | 1,955 MB/s | 2,005 MB/s | +3% |
| 64 KB | 1,966 MB/s | 1,979 MB/s | +1% |
| 128 KB | 1,923 MB/s | 1,965 MB/s | +2% |
| 1 MB | 1,764 MB/s | 1,731 MB/s | -2% |

perf stat 비교 (128K 블록, 20,000회):

| 지표 | Baseline | Modified | 해석 |
|---|---|---|---|
| Cycles | 4,154,688,592 | 4,274,588,145 | 차이 < 3% |
| Instructions | 16,738,276,481 | 16,740,225,792 | 거의 동일 |
| CPI (insn/cycle) | 4.03 | 3.92 | 노이즈 범위 |

**결론: 성능 차이 없음.** 이유는 세 가지입니다:

1. **GCC 11.4는 `restrict` 없이도 타입 기반 alias 분석으로 동일 코드를 생성합니다** — 명령어 수가 동일하다는 것이 이를 증명합니다
2. **LZ4 해제 경로는 메모리 바운드(CPI 4.0)입니다** — alias 분석이 개선할 수 있는 CPU 바운드 구간이 아닙니다
3. **4K 블록의 -16%는 측정 노이즈입니다** — 다른 블록 크기에서는 ±3% 이내

> 코드 품질 관점에서는 빈 매크로가 의도치 않은 것이 맞지만, 성능 개선 근거가 없으므로 upstream PR 제출은 의미가 없습니다.

#### ZSTD `ZSTD_DISABLE_ASM 1` — 의도적 비활성

```c
// module/zstd/zstd-in.c:52
#define ZSTD_DISABLE_ASM 1    // hand-tuned ASM 비활성
```

이것은 버그가 아닙니다. **의도적인 설계 결정입니다:**

- ZSTD가 ZFS에 통합된 시점(2019–2020)에서 커널 빌드 환경 제약으로 인해 비활성화
- objtool 스택 검증, ORC unwinder, retpoline 호환성 문제
- **파일시스템 압축 해제에서 ASM 버그 발생 시 데이터 손상 리스크**
- 2025년에도 여전히 비활성 상태 → 사유가 잔존하거나 우선순위가 낮음

비활성 상태에서의 실측 압축 해제 처리량:

<div style="margin: 24px 0;">
  <canvas id="chart-compression" height="180"></canvas>
</div>

| 알고리즘 | 평균 처리량 | 압축률 |
|---|---|---|
| **LZ4** | **2.6 GB/s** | 127x |
| ZSTD-3 | 1.5 GB/s | 49,933x |
| ZSTD-9 | 2.4 GB/s | 49,933x |
| ZSTD-19 | 2.4 GB/s | 49,933x |
| GZIP-6 | 1.5 GB/s | 252x |

> ZSTD 해제 처리량이 1.2–2.4 GB/s면 대부분의 스토리지 워크로드에서 디스크 I/O가 병목이지 압축 해제가 병목이 아닙니다.

### 3. ARC 메모리 관리 — False Sharing 완벽 방지

ARC의 핫 카운터와 락은 `____cacheline_aligned` 속성으로 false sharing을 적극 방지합니다:

```c
// module/zfs/arc.c
#define BUF_LOCKS 2048         // 2K 개의 독립 락
kmutex_t *ht_locks;            // ____cacheline_aligned

// include/sys/aggsum.h
typedef struct aggsum_bucket {
    kmutex_t    asc_lock;
    int64_t     asc_delta;
    uint8_t     asc_pad[40];   // 64바이트 캐시라인 보장
} ____cacheline_aligned;
```

실측 LZ4 perf stat에서 CPI 0.81, cache-miss 26.67% — 양호한 수준이며, cache-miss는 파일 읽기 경로의 특성상 예상 범위 내입니다.

| 패턴 | 상태 | 비고 |
|---|---|---|
| `false-sharing` | 방지됨 | cacheline\_aligned + 명시적 패딩 |
| `per-cpu-stats` | 방지됨 | `aggsum` per-CPU 분산 |
| `cv-thundering-herd` | 방지됨 | targeted signal 사용 |
| `mutex-to-rwlock` | 검토 대상 | 읽기 비율 ~95%인데 mutex 사용. 단, SPL rwlock 오버헤드로 실제 이득은 벤치마크 필요 |

## Result: 정적 분석 vs 실측 비교

| 패턴 | 대상 | 정적 분석 | 실측 결과 | 최종 판정 |
|---|---|---|---|---|
| `missing-restrict` | LZ4 압축/해제 | **Critical 발견** | **영향 없음** (Δ=0%) | 조치 불필요 |
| ZSTD ASM | ZSTD 해제 | **Critical 발견** | **의도적 비활성** | 조사만 |
| `serial-accumulator` | Fletcher4 | 없음 | chksum\_bench 확인 | 정상 |
| `false-sharing` | ARC 통계/락 | 없음 | CPI 0.81 측정 | 정상 |
| `missing-vzeroupper` | Fletcher4 AVX2/512 | 없음 | — | 정상 |
| `per-cpu-stats` | ARC 카운터 | 없음 | — | 정상 |
| `cpu-dispatch` | 체크섬 디스패치 | 없음 | chksum\_bench 확인 | 정상 |
| `mutex-to-rwlock` | ARC 해시 테이블 | 검토 대상 | 미측정 | 향후 과제 |

### 핵심 교훈: 정적 분석의 한계

정적 분석은 "이론적으로 문제가 될 수 있는 코드 패턴"을 찾아줍니다. 하지만 실제 성능 영향은 다음 요소들에 의해 좌우됩니다:

1. **컴파일러의 독립적 최적화** — GCC는 `restrict` 없이도 타입 기반 alias 분석으로 동일한 최적화를 수행합니다. 정적 분석 도구는 이를 알지 못합니다
2. **워크로드의 병목 위치** — LZ4 해제는 메모리 바운드(CPI 4.0)이므로, alias 분석 개선으로 도움받을 수 없습니다. CPU 바운드 코드에서는 다를 수 있습니다
3. **의도적 설계 결정** — ZSTD ASM 비활성화는 "고쳐야 할 버그"가 아니라 데이터 무결성과 빌드 호환성을 위한 트레이드오프입니다

### 남은 과제 (선택적)

| 과제 | 우선순위 | 설명 |
|---|---|---|
| ARC 해시 테이블 rwlock 전환 | 중간 | 읽기 95% 패턴에 mutex 사용. 단, SPL rwlock 오버헤드 측정 선행 필요 |
| ZSTD ASM 활성화 가능성 | 낮음 | objtool 호환성 확인 + 데이터 무결성 검증 필요 |

> upstream PR 존재 여부(2026-06-16 확인): LZ4 restrict 수정 PR 없음(성능 효과 없음), ZSTD ASM 활성화 PR 없음(커널 빌드 호환성 문제), 체크섬 SIMD 개선은 PR #12918(BLAKE3 + chksum\_bench)로 이미 머지됨.

## 마치며

정적 분석을 마친 직후에는 확신에 차 있었습니다. LZ4의 `restrict` 무효화는 코드상으로 완벽한 Critical 안티패턴이었고, ZSTD ASM 비활성화 역시 "왜 이걸 안 켜놓지?"라는 의문을 품기에 충분했습니다. "이걸 고치면 5–20%는 빨라지겠네"라며 upstream PR까지 머릿속으로 그리고 있었습니다. 그런데 막상 A/B 벤치마크를 돌려보니 두 선이 겹칠 정도로 성능 차이가 0%였습니다. 컴파일러가 내가 간과한 타입 기반 alias 분석으로 이미 동일한 최적화를 수행하고 있었고, LZ4 해제 경로는 애초에 메모리 바운드라 CPU 최적화가 의미가 없었습니다. 코드만 보고 내린 판단이 얼마나 쉽게 무너지는지 뼈저리게 느꼈습니다.

이 경험은 "비활성화"와 "최적화 누락"이 전혀 다른 것이라는 통찰로 이어졌습니다. ZSTD ASM이 꺼져 있는 것은 누군가의 실수가 아니라, objtool 호환성과 파일시스템 데이터 손상 리스크를 무게 달아본 끝에 내린 의도적 결정이었습니다. 업스트림 벤치마크가 "ASM을 켜면 1.5–3배 빠르다"고 외치더라도, 파일시스템 컨텍스트에서의 ASM 버그는 곧 데이터 손상이라는 치명적 결과로 이어집니다. 빠름과 안전함 사이의 트레이드오프를 코드 한 줄만으로는 읽어낼 수 없다는 것을, 이 사례가 분명하게 보여주었습니다.

반면 OpenZFS의 체크섬과 ARC 구현은 정말 배울 점이 많았습니다. 런타임 CPU 디스패치로 최적 SIMD 경로를 선택하고, `vzeroupper`로 전환 페널티를 제거하며, cacheline 정렬과 per-CPU 통계로 멀티코어 확장성을 확보하는 패턴은 다른 커널 서브시스템에도 그대로 적용할 수 있는 범용적 기법이었습니다. BLAKE3 AVX2 2,635 MB/s와 CPI 0.81이라는 수치가 이를 증명합니다. 앞으로는 코드에서 발견한 안티패턴을 결론이 아니라 가설로 대하고, 반드시 실측으로 검증한 뒤에야 비로소 판단하려 합니다. 정적 분석은 질문을 던지는 도구이지, 답을 주는 도구가 아니라는 것을 이 프로젝트가 가르쳐 주었습니다.

<script type="application/json" id="chart-data">
[
  {
    "id": "chart-blake3-simd",
    "type": "bar",
    "data": {
      "labels": ["generic (스칼라)", "SSE2", "SSE4.1", "AVX2"],
      "datasets": [{
        "label": "BLAKE3 처리량 (MB/s, 4M 블록)",
        "data": [166, 1167, 1426, 2635],
        "backgroundColor": [
          "rgba(139,148,158,0.7)",
          "rgba(188,140,255,0.7)",
          "rgba(63,185,80,0.7)",
          "rgba(88,166,255,0.8)"
        ],
        "borderColor": [
          "rgba(139,148,158,1)",
          "rgba(188,140,255,1)",
          "rgba(63,185,80,1)",
          "rgba(88,166,255,1)"
        ],
        "borderWidth": 1.5,
        "borderRadius": 6
      }]
    },
    "options": {
      "plugins": {
        "legend": { "display": false },
        "title": { "display": true, "text": "BLAKE3 SIMD 가속 효과 — generic 대비 AVX2가 15.9배 빠름" }
      },
      "scales": {
        "y": { "beginAtZero": true, "title": { "display": true, "text": "처리량 (MB/s)" } },
        "x": { "grid": { "display": false } }
      }
    }
  },
  {
    "id": "chart-lz4-ab",
    "type": "line",
    "data": {
      "labels": ["4 KB", "16 KB", "64 KB", "128 KB", "1 MB"],
      "datasets": [
        {
          "label": "Baseline (restrict 무효)",
          "data": [2152, 1955, 1966, 1923, 1764],
          "borderColor": "rgba(248,81,73,0.9)",
          "backgroundColor": "rgba(248,81,73,0.1)",
          "borderWidth": 2.5,
          "tension": 0.3,
          "pointRadius": 5,
          "pointBackgroundColor": "rgba(248,81,73,1)",
          "fill": true
        },
        {
          "label": "Modified (__restrict)",
          "data": [1800, 2005, 1979, 1965, 1731],
          "borderColor": "rgba(88,166,255,0.9)",
          "backgroundColor": "rgba(88,166,255,0.1)",
          "borderWidth": 2.5,
          "tension": 0.3,
          "pointRadius": 5,
          "pointBackgroundColor": "rgba(88,166,255,1)",
          "fill": true
        }
      ]
    },
    "options": {
      "plugins": {
        "title": { "display": true, "text": "LZ4 restrict A/B 벤치마크 — 두 선이 겹침 = 성능 차이 없음" }
      },
      "scales": {
        "y": { "min": 1500, "max": 2300, "title": { "display": true, "text": "처리량 (MB/s)" } },
        "x": { "title": { "display": true, "text": "블록 크기" } }
      }
    }
  },
  {
    "id": "chart-compression",
    "type": "bar",
    "data": {
      "labels": ["LZ4", "ZSTD-3", "ZSTD-9", "ZSTD-19", "GZIP-6"],
      "datasets": [{
        "label": "압축 해제 처리량 (GB/s)",
        "data": [2.6, 1.5, 2.4, 2.4, 1.5],
        "backgroundColor": [
          "rgba(63,185,80,0.7)",
          "rgba(88,166,255,0.6)",
          "rgba(88,166,255,0.6)",
          "rgba(88,166,255,0.6)",
          "rgba(210,153,34,0.6)"
        ],
        "borderColor": [
          "rgba(63,185,80,1)",
          "rgba(88,166,255,1)",
          "rgba(88,166,255,1)",
          "rgba(88,166,255,1)",
          "rgba(210,153,34,1)"
        ],
        "borderWidth": 1.5,
        "borderRadius": 6
      }]
    },
    "options": {
      "indexAxis": "y",
      "plugins": {
        "legend": { "display": false },
        "title": { "display": true, "text": "압축 알고리즘별 해제 처리량 (1GB 압축 가능 데이터)" }
      },
      "scales": {
        "x": { "beginAtZero": true, "title": { "display": true, "text": "처리량 (GB/s)" } },
        "y": { "grid": { "display": false } }
      }
    }
  }
]
</script>
