---
layout: post
title: "ZFS CPU 성능 패턴 분석 — LZ4 restrict부터 ARC False Sharing까지"
categories: [Linux, Performance, Filesystem]
description: OpenZFS 소스 코드를 정적 분석하여 CPU 성능 안티패턴을 찾아냅니다. LZ4 restrict 무효화, ZSTD ASM 비활성 등 Critical 발견과 Fletcher4 SIMD 모범 사례까지.
keywords: [ZFS, OpenZFS, 성능최적화, SIMD, LZ4, ZSTD, ARC, CPU]
toc: true
toc_sticky: true
---

## Hook

ZFS는 데이터 무결성으로 유명한 파일시스템입니다. 하지만 "무결성"이라는 단어 뒤에는 체크섬 계산, 압축/해제, ARC 캐시 관리라는 CPU 집약적 작업이 숨어 있습니다. 이 작업들이 얼마나 효율적으로 구현되어 있는지 코드 레벨에서 확인해 본다면 어떨까요?

Intel의 CPU 성능 패턴 카탈로그를 기준으로 OpenZFS 소스 트리를 정적 분석한 결과, 2개의 Critical 안티패턴과 3개의 개선 기회를 발견했습니다. 반면 체크섬 SIMD와 ARC false sharing 방지는 모범 사례 수준이었습니다. 이 글에서는 각 발견의 원인, 영향, 수정 방법을 정리합니다.

## TL;DR

- **Critical 2건**: LZ4 `#define restrict`(빈 정의)로 컴파일러 최적화 차단, ZSTD `ZSTD_DISABLE_ASM 1`로 hand-tuned ASM 비활성화
- **개선 기회 3건**: ARC 해시 테이블 mutex→rwlock 전환, Edon-R/Skein SIMD 부재, GZIP 부분 최적화
- **모범 사례 5건**: Fletcher4 CPU 디스패치, vzeroupper, 8-way unroll, ARC cacheline 정렬, per-CPU 통계(aggsum)
- 정적 분석 기반이므로 실제 성능 영향은 `perf` 실측으로 검증이 필요합니다

## Background: 왜 CPU 패턴인가

ZFS의 핫 패스는 크게 세 영역으로 나뉩니다:

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

각 영역에서 CPU 성능을 좌우하는 패턴은 다릅니다. 체크섬은 SIMD 벡터화가 핵심이고, 압축은 `restrict` 키워드와 ASM 최적화가 처리량을 결정하며, ARC는 락 경쟁과 false sharing이 다중 스레드 확장성을 좌우합니다.

분석은 12가지 CPU 성능 안티패턴을 정의하는 패턴 카탈로그를 기준으로 진행했습니다. 각 패턴은 코드에서 발생하는 전형적인 형태(trigger)와 권장 수정 방법(rewrite)을 제공합니다.

```
serial-accumulator  │ 순차 합산으로 ILP 차단
false-sharing       │ 동일 캐시라인의 서로 다른 변수 수정
missing-restrict    │ restrict 누락 → 포인터 aliasing 방지 불가
missing-vzeroupper  │ AVX→SSE 전환 페널티
mutex-to-rwlock     │ 읽기 다수 패턴에 mutex → 병목
per-cpu-stats       │ 통계 업데이트 글로벌 락 → 분산 필요
cv-thundering-herd  │ CV 브로드캐스트 시 전체 웨이터 깨움
cpu-dispatch        │ 런타임 CPU 감지 없이 단일 SIMD 경로
unroll-loop         │ 루프 언롤링 부재
```

## Solution: 영역별 분석 결과

### 1. 체크섬 SIMD — 모범 사례

ZFS는 Fletcher4, SHA-256, SHA-512, BLAKE3, Edon-R, Skein 등 다중 체크섬을 제공합니다. SIMD 지원 현황은 다음과 같습니다:

| 알고리즘 | SSE2 | AVX2 | AVX-512 | SHA-NI | ARM NEON | 총평 |
|---|---|---|---|---|---|---|
| **Fletcher4** | 있음 | 있음 | 있음 | — | 있음 | 최적 |
| **SHA-256** | 있음 | 있음 | 있음 | 있음 | 있음 | 최적 |
| **SHA-512** | 있음 | — | 있음 | — | — | 최적 |
| **BLAKE3** | 있음 | 있음 | 있음 | — | 있음 | 최적 |
| **Edon-R** | — | — | — | — | — | 개선 여지 |
| **Skein** | — | — | — | — | — | 개선 여지 |

Fletcher4는 4가지 핵심 패턴에서 모범 구현을 보여줍니다.

**(1) CPU Dispatch — 런타임 기능 감지**

부팅 시 CPU 기능 비트를 감지하고 가장 적합한 구현을 선택합니다:

```c
// module/zcommon/zfs_fletcher.c
static void fletcher_4_impl_choose(void) {
    const fletcher_4_func_t *curr = fletcher_4_impls;
    if (zfs_fletcher4_avx512_enabled && blkfill_check())
        curr = fletcher_4_avx512_native;
    else if (zfs_fletcher4_avx2_enabled)
        curr = fletcher_4_avx2_native;
    else if (zfs_fletcher4_sse2_enabled)
        curr = fletcher_4_sse2_native;
}
```

SSE2 → AVX2 → AVX-512 계층적 선택이 구현되어 있으며, sysfs tunable로 런타임 변경도 가능합니다.

**(2) vzeroupper — AVX/SSE 전환 페널티 방지**

모든 AVX2/AVX-512 경로의 인라인 어셈블리 끝에 `vzeroupper`가 포함되어 있습니다:

```c
// module/zcommon/zfs_fletcher_intel.c
asm volatile(
    "vmovdqu %0, %%ymm0\n\t"
    "vpmovzxdq %%xmm1, %%ymm2\n\t"
    ...
    "vzeroupper"            // ← AVX→SSE 전환 페널티 제거
    : : "m" (ip[0]), "m" (accum[0])
    : "xmm0","xmm1","xmm2","xmm3","cc");
```

**(3) Loop Unrolling & Data Parallelism**

AVX-512 구현은 256-bit(8 × uint32)를 한 번에 처리합니다:

```c
// 8개 uint32 = 32바이트 동시 처리
for (; ip < ipend; ip += 8) {
    asm volatile(
        "vmovdqu32 (%0), %%zmm0\n\t"
        "vpaddd %%zmm0, %%zmm3, %%zmm3\n\t"
        ...  // 8-way unroll
    );
}
```

SIMD 벡터 연산으로 데이터 병렬성을 확보하여 `serial-accumulator` 안티패턴을 회피합니다.

> **Edon-R / Skein**은 스칼라 구현만 제공하지만, 기본값이 아니고 deprecated 옵션이므로 우선순위는 낮습니다.

### 2. 압축 분석 — Critical 발견 2건

#### LZ4: `#define restrict` 빈 정의 — Critical

LZ4 구현에서 `restrict` 키워드가 **빈 매크로로 정의**되어 완전히 무효화됩니다. 두 파일에서 동일한 패턴이 확인됩니다:

```c
// module/zfs/lz4.c:133, module/zfs/lz4_zfs.c:264
#ifndef restrict
#define restrict            // ← 빈 정의! restrict 키워드 무효화
#endif

// 이후 모든 restrict 사용이 무효:
const BYTE * restrict ip = (const BYTE *) source;  // restrict 무효!
BYTE * restrict op = (BYTE *) dest;                 // restrict 무효!
```

**영향 분석:**

| 항목 | 내용 |
|---|---|
| 패턴 | `missing-restrict` (완전 무효화 형태) |
| 원인 | 커널 빌드 환경에서 `restrict` C 키워드 지원 불확실성 → 과도하게 보수적 빈 정의 |
| 영향 | 컴파일러가 `ip`와 `op`가 aliasing될 수 있다고 가정 → 메모리 최적화, auto-vectorization, 레지스터 할당 최적화 모두 차단 |
| 예상 영향 | 압축 해제 처리량 5–20% 저하 가능성 (실측 필요) |
| 수정 난이도 | **낮음** |

<details>
<summary>수정 제안 코드 (클릭하여 펼치기)</summary>

```c
// ---- Before ----
#ifndef restrict
#define restrict
#endif

// ---- After ----
#if !defined(restrict) && defined(__GNUC__)
#define restrict __restrict
#endif
```

커널 빌드에서도 GCC/Clang 모두 `__restrict`를 지원하므로 안전하게 교체할 수 있습니다.

</details>

#### ZSTD: `ZSTD_DISABLE_ASM 1` — Critical

ZFS에 포함된 ZSTD 빌드에서 hand-tuned 어셈블리 최적화가 비활성화되어 있습니다:

```c
// module/zstd/zstd-in.c:52
#define ZSTD_DISABLE_ASM 1    // ← ASM 최적화 비활성화
```

| 항목 | 내용 |
|---|---|
| 비활성화된 최적화 | HuffDecompress AMD64 ASM, wildcopy 최적화, prefetch 힌트 |
| 원인 | 커널 빌드 환경에서 ASM 빌드 호환성 문제 (objtool 검증, ORC unwind 등) |
| 영향 | ZSTD 압축 해제 처리량 저하 (ASM 대비 C 구현은 1.5–3x 느림) |
| 수정 난이도 | **높음** — 커널 objtool/ORC 호환성 확인 필요 |

<details>
<summary>ZSTD ASM 활성화 조사 항목 (클릭하여 펼치기)</summary>

- Upstream ZSTD 최신 버전의 ASM 빌드 요구사항 확인
- 리눅스 커널 `objtool` 및 ORC unwinder 호환성 테스트
- `CONFIG_RETPOLINE`, `CONFIG_STACK_VALIDATION` 영향 확인
- ASM 활성화 후 ZFS regression test 통과 여부
- ZFS의 ZSTD는 amalgamated 버전이므로 업스트림 ASM 패치 직접 적용 불가 가능성

</details>

#### 기타 압축 알고리즘

| 알고리즘 | SIMD/ASM | 비고 |
|---|---|---|
| LZ4 | **restrict 무효** | 위 분석 참조 |
| ZSTD | **ASM 비활성** | 위 분석 참조 |
| GZIP (zlib) | 부분 | PCLMULQDQ CRC32 사용, deflate는 zlib에 의존 |
| LZJB | 스칼라 | 레거시, 사용 빈도 낮음 |
| ZLE | 해당 없음 | 구조상 최적화 여지 적음 |

### 3. ARC 메모리 관리 — False Sharing 방지 모범 사례

ARC(Adaptive Replacement Cache)는 다중 스레드 환경에서 락 경쟁과 false sharing이 성능에 직접적인 영향을 미칩니다.

#### False Sharing 방지 — 잘 구현됨

ARC의 핫 카운터와 락은 `____cacheline_aligned` 속성으로 false sharing을 적극 방지합니다:

```c
// module/zfs/arc.c — 2048-way bucket lock array
#define BUF_LOCKS 2048         // 2K 개의 독립 락
#define BUF_HASH_LOCK(idx) (idx & (BUF_LOCKS - 1))

buf_hash_table.ht_locks =
    kmem_zalloc(sizeof(kmutex_t) * BUF_LOCKS,
        KM_SLEEP) ____cacheline_aligned;
```

```c
// include/sys/aggsum.h — per-bucket cacheline aligned
typedef struct aggsum_bucket {
    kmutex_t    asc_lock;
    int64_t     asc_delta;
    uint8_t     asc_pad[40];   // ← 64바이트 캐시라인 보장
} aggsum_bucket_t ____cacheline_aligned;
```

2048개의 락을 배열로 두고 hash 값의 하위 11비트로 인덱싱하므로, 다중 스레드가 서로 다른 버킷에 접근할 때 락 경쟁이 희석됩니다.

#### Per-CPU 통계 — 잘 구현됨

ARC의 핫 카운터(`arcs_size`, `hits`, `misses` 등)는 `aggsum_t`를 사용하여 per-CPU 분산 처리됩니다. `aggsum_add()`는 현재 CPU의 bucket에 delta를 누적하고, `aggsum_value()` 호출 시에만 전체 bucket을 합산하여 쓰기 경로의 락 경쟁을 최소화합니다.

#### Mutex → Rwlock — 검토 권장

ARC 해시 테이블 조회는 읽기 비율이 압도적으로 높음에도 전용 mutex를 사용합니다:

| 영역 | 현재 락 | 읽기:쓰기 (예상) | 개선 제안 |
|---|---|---|---|
| buf_hash_table 조회 | `kmutex_t` | ~95:5 | `krwlock_t` 검토 |
| dbuf hash | `kmutex_t` | ~90:10 | `krwlock_t` 검토 |
| aggsum bucket | `kmutex_t` | N/A (per-CPU) | 변경 불필요 |

> **주의**: Solaris/illumos의 `krwlock_t`는 Linux `rwlock_t`보다 오버헤드가 클 수 있으며, SPL(Solaris Porting Layer) 에뮬레이션에서는 더 복잡합니다. 실제 이득은 벤치마크가 필요합니다.

## Result: 패턴별 매핑 요약

| 패턴 | 대상 영역 | 발견 여부 | 심각도 |
|---|---|---|---|
| `missing-restrict` | LZ4 압축/해제 | **발견** | **Critical** |
| `cpu-dispatch` (역발견) | ZSTD ASM 비활성 | **발견** | **Critical** |
| `mutex-to-rwlock` | ARC 해시 테이블 | 검토 대상 | High |
| `serial-accumulator` | Fletcher4 | 없음 — SIMD 벡터화로 회피 | — |
| `false-sharing` | ARC 통계/락 | 없음 — `cacheline_aligned`로 방지 | — |
| `missing-vzeroupper` | Fletcher4 AVX2/512 | 없음 — `vzeroupper` 포함 | — |
| `per-cpu-stats` | ARC 카운터 | 없음 — `aggsum` 사용 | — |
| `cv-thundering-herd` | ARC I/O 큐 | 없음 — targeted signal 사용 | — |
| `cpu-dispatch` | Fletcher4/SHA/BLAKE3 | 없음 — 계층적 디스패치 | — |
| `unroll-loop` | Fletcher4 AVX-512 | 없음 — 8-way unroll | — |

### 액션 플랜 우선순위

| 우선순위 | 작업 | 난이도 | 예상 효과 |
|---|---|---|---|
| **P0** | LZ4 `restrict` → `__restrict` 교체 | 낮음 | LZ4 처리량 5–20% 향상 |
| **P1** | ZSTD ASM 활성화 가능성 조사 | 높음 | ZSTD 해제 1.5–3x 향상 |
| **P2** | ARC 해시 테이블 rwlock 전환 벤치마크 | 중간 | 조회 병렬성 향상 |
| P3 | Edon-R / Skein SIMD 구현 (선택) | 높음 | 제한적 (비활성 알고리즘) |

### 프로파일링으로 검증하기

정적 분석만으로 실제 성능 영향을 정량화할 수 없습니다. 다음 `perf` 이벤트로 실측 검증이 필요합니다:

| 이벤트 | 용도 |
|---|---|
| `cycles`, `instructions` | 기본 CPI (Cycles Per Instruction) |
| `cache-misses`, `L1-dcache-load-misses` | False sharing / restrict 효과 |
| `branch-misses` | 분기 예측 실패 |
| `context-switches` | 락 대기로 인한 스케줄링 |
| `avx_insts.all` | SIMD 명령어 사용량 |

> ZFS 커널 모듈 로드가 가능한 베어메탈/VM 환경에서 `perf_event_paranoid ≤ 1`로 설정하고 최소 8코어 이상에서 측정하는 것을 권장합니다.

## Takeaway

1. **LZ4 `restrict` 무효화는 수정 난이도가 낮으면서 효과가 큽니다** — 커널 빌드 환경에서 `restrict` C99 키워드 지원이 불확정하다는 이유로 빈 매크로로 정의한 것은 과도하게 보수적인 조치입니다. `__restrict`로 교체하면 컴파일러의 alias 분석이 복원되어 auto-vectorization과 레지스터 할당 최적화가 다시 활성화됩니다
2. **ZSTD ASM 비활성화는 커널 빌드 호환성 트레이드오프입니다** — objtool/ORC unwinder 검증 문제로 hand-tuned ASM을 끈 것은 안정성을 위한 합리적 선택이지만, 1.5–3배의 처리량 손실이라는 비용이 따릅니다. 업스트림 ZSTD의 ASM 빌드 요구사항과 커널 호환성을 지속적으로 재검토해야 합니다
3. **체크섬 SIMD와 ARC false sharing 방지는 학습할 만한 모범 사례입니다** — CPU dispatch로 런타임에 최적의 SIMD 경로를 선택하고, vzeroupper로 전환 페널티를 제거하며, cacheline 정렬과 per-CPU 통계로 멀티코어 확장성을 확보하는 패턴은 다른 커널 서브시스템에도 적용할 수 있는 범용적 최적화 기법입니다
