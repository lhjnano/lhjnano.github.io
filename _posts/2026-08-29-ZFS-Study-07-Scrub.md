---
layout: post
title: "ZFS 소스 학습 (7/8): Scrub - 검증이 본업인 배경 스캔"
categories: [Storage, Filesystem, OpenZFS]
description: "ZFS scrub은 resilver와 같은 기계를 돌린다? 콜백 공유부터 mintime 시간 배분, self-healing과 errlog까지 소스로 정리했습니다."
keywords: [ZFS, OpenZFS, scrub, self-healing, errlog, DTL_SCRUB, error scrub]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (7/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

이 글의 분기와 함수는 OpenZFS master 소스를 직접 읽어 확인했고, 인용은 `파일:라인` 형식입니다(dsl_scan.c:255, dsl_scan.c:1790, vdev.c:3379, dsl_scan.c:840). 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (6/8) ZIL, 크래시까지 유효한 약속 장부: [ZFS-Study-06-ZIL](/2026/08/29/ZFS-Study-06-ZIL/)

이전 편 (5/8) Resilver, 비어 있는 복제본을 메우는 복사: [ZFS-Study-05-Resilver](/2026/08/29/ZFS-Study-05-Resilver/)

## TL;DR

- scrub과 resilver는 **같은 콜백(`dsl_scan_scrub_cb`)을 공유**합니다. 하나의 스캔 기계가 검증 모드와 복사 모드를 함께 돌립니다.
- scrub의 본업은 **검증**입니다. 살아 있는 블록을 전부 읽어 체크섬과 대조하고, 틀어지면 self-healing으로 고치고, 못 고친 것은 장부에 남깁니다.
- scrub은 **손님 설계**입니다. txg마다 최소 시간(mintime)만큼만 보장받고, dirty 데이터가 쌓이거나 sync가 대기하면 즉시 발급을 끊습니다.
- 오류가 나도 **scrub은 재시작하지 않습니다.** 끝까지 순회하고 오류를 보고하는 것으로 끝냅니다. 오류 재검사는 다음 scrub 또는 error scrub(-e)의 몫입니다.
- 못 고친 구간은 **DTL_SCRUB** 장부에 남아 다음 복구 스캔의 입력이 됩니다.

## 같은 기계, 다른 본업

5편에서 resilver는 "비어 있는 복제본을 메우는 복사"가 목적이라고 했습니다. scrub의 목적은 복사가 아니라 검증입니다. 풀에 살아 있는 모든 블록을 읽어 체크섬과 대조하고, 어긋나면 고칠 수 있는 경로로 고치며, 최종적으로 못 고친 오류의 목록을 사용자에게 보고합니다.

흥미로운 사실은 이 둘이 같은 기계를 돌린다는 점입니다.

```c
/* dsl_scan.c:255: scrub과 resilver가 같은 콜백을 공유한다 */
scan_funcs[POOL_SCAN_SCRUB]    = dsl_scan_scrub_cb;
scan_funcs[POOL_SCAN_RESILVER] = dsl_scan_scrub_cb;
```

하나의 콜백이 두 모드를 모두 처리하고, 내부에서 지금 검증 중인지 복제 중인지를 스캔 상태로 구분합니다. 5편에서 본 순회, 발급, 완료 골격이 그대로 재사용되기 때문에, 이 글은 scrub 모드에 고유한 부분인 순회 대상, 시간 배분, 오류 처리의 갈림길에 집중합니다.

### 순회 대상과 checkpoint 제외

순회의 1차 대상은 5편과 같이 MOS와 데이터셋 트리를 따라가며 live 블록 포인터를 하나씩 콜백에 넘기는 구조입니다. scrub이 한 걸음 더 나아가는 지점은 검증 대상의 폭입니다. dedup이 활성화된 풀에서는 DDT 엔트리 자체도 검증 대상에 들어갑니다. `ddt_walk_init(spa, scn_max_txg)`(dsl_scan.c:746)로 DDT를 처음부터 끝까지 걷는 커서를 준비하고, 엔트리가 적힌 체크섬과 위치, 참조 카운트가 실제 디스크와 일치하는지까지 확인합니다.

주의할 제외 대상도 있습니다. 풀에 checkpoint가 존재하면 해당 블록은 scrub 순회에서 제외되고 사용자에게 경고가 출력됩니다(zpool_main.c:9453). 예전 시점으로 돌아가기 위한 보존 구간이므로 지금 상태를 검증해 봤자 의미가 없기 때문입니다. checkpoint가 있는 풀에서 scrub 리포트를 읽을 때는 이 경고 문구를 먼저 확인해야 합니다.

대상을 알았으니, 이 스캔이 얼마나 공격적으로 디스크를 읽는지가 다음 질문입니다.

## 시간 배분: mintime과 조건부 양보

scrub은 수 TB를 훑는 대형 워크로드지만, 풀의 주인은 언제나 foreground 쓰기입니다. 이 우선순위가 코드에 박혀 있는 곳이 두 층입니다.

첫째 층은 발급 큐입니다. 순회가 던진 블록은 `scan_io_queue`에 쌓이는데, 방문은 트리 순서대로 받되 발급은 디스크 오프셋 정렬로 합니다. 논리 순서와 물리 순서의 결합부입니다. 리프 vdev별 in-flight I/O량은 `zfs_scan_vdev_limit`(dsl_scan.c:5493+)으로 제한되어, 개별 디스크가 scrub에 잠식되지 않게 하는 1차 밸브 역할을 합니다.

둘째 층이 txg 단위의 시간 배분입니다. dsl_scan.c:1790의 판정식을 읽는 방향이 중요합니다.

```c
mintime = (RESILVER) ? zfs_resilver_min_time_ms : zfs_scrub_min_time_ms;

/* 참이면 scrub 발급을 멈추고 sync에게 길을 양보한다 */
scan_time > mintime &&
  (dp_dirty_total >= zfs_dirty_data_max * active_min%
   || txg_sync_waiting
   || sync_time >= zfs_txg_timeout)
```

mintime 이전에는 아무 조건도 검사하지 않습니다. `zfs_scrub_min_time_ms`만큼은 풀 상태와 무관하게 scrub이 일할 시간을 보장받습니다. mintime이 지난 뒤에는 세 가지 중 하나라도 걸리면 즉시 양보합니다. dirty 데이터가 상한의 일정 비율을 넘었거나, sync가 대기 중이거나, sync가 타임아웃을 노리고 있을 때입니다. 요컨대 scrub은 매 txg 최소한만큼은 반드시 일하고 나머지는 foreground의 형편을 보며 일하는 손님입니다.

아래 그림이 한 txg의 시간축을 펼친 것입니다. 위쪽 노란 블록은 foreground 쓰기, 아래쪽 파란 블록은 scrub 발급입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 300" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="한 txg 안의 scrub 시간 배분 타임라인. txg open부터 sync 마감까지 시간축에서, 위쪽 노란 블록은 foreground 쓰기가 전 구간에 유입되고, 아래쪽 파란 블록은 scrub 발급이 zfs_scrub_min_time_ms 동안은 무조건 보장된 뒤, dirty 데이터 상한 초과나 sync 대기 또는 sync 타임아웃 조건이 하나라도 걸리면 sync 마감선 앞에서 스스로 발급을 중단하고 길을 양보한다. 조건부 연장 구간은 점선 테두리로 구분된다.">
  <defs>
    <marker id="zs7-arr-gray" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="zs7-arr-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
  </defs>
  <text x="440" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">한 txg 안의 시간 배분: scrub은 손님 설계</text>

  <text x="80" y="70" font-size="12" font-weight="700" fill="#92400e">foreground 쓰기</text>
  <rect x="80" y="80" width="720" height="44" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="440" y="107" text-anchor="middle" font-size="11" fill="#92400e">dirty 데이터 유입 (txg에 계속 쌓임)</text>

  <text x="80" y="170" font-size="12" font-weight="700" fill="#2563eb">scrub 발급</text>
  <rect x="80" y="180" width="360" height="44" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.7"/>
  <text x="260" y="207" text-anchor="middle" font-size="11" font-weight="700" fill="#2563eb">mintime 보장 구간</text>
  <rect x="455" y="180" width="230" height="44" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.2" stroke-dasharray="5,4"/>
  <text x="570" y="207" text-anchor="middle" font-size="11" fill="#2563eb">조건부 연장</text>
  <rect x="700" y="180" width="100" height="44" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="750" y="200" text-anchor="middle" font-size="10" font-weight="700" fill="#dc2626">발급 중단</text>
  <text x="750" y="215" text-anchor="middle" font-size="9" fill="#dc2626">(양보)</text>

  <line x1="80" y1="240" x2="800" y2="240" stroke="#666666" stroke-width="1.2" marker-end="url(#zs7-arr-gray)"/>
  <text x="80" y="260" font-size="10" fill="#666666">txg open</text>
  <text x="440" y="260" text-anchor="middle" font-size="10" fill="#2563eb">mintime = zfs_scrub_min_time_ms</text>
  <text x="800" y="260" text-anchor="end" font-size="10" fill="#666666">txg sync 마감</text>

  <rect x="80" y="272" width="720" height="0" fill="none"/>
  <text x="440" y="288" text-anchor="middle" font-size="10" fill="#dc2626">양보 조건(dsl_scan.c:1790): dirty 상한 초과 · sync 대기 · sync 타임아웃 중 하나</text>
</svg>

mintime이 scrub의 권리라면 양보 조건은 scrub의 예의입니다. 이 설계가 3편의 txg 상태머신과 만나는 지점도 자연스럽습니다. scrub이 sync를 늘어지게 하는 주범이 되지 않도록 자기 발급을 스스로 끊는 것입니다. 그럼 스캔이 블록을 읽고 난 뒤에는 무슨 일이 벌어질까요.

## 오류 처리의 갈림길

콜백이 블록을 읽어 체크섬을 대조한 결과는 두 갈래로 나뉩니다. 일치하면 아무 일도 없이 순회가 계속됩니다. 불일치하면 4편 Read Path에서 본 self-healing 경로가 동원됩니다. mirror라면 반대편, raidz라면 패리티로 정상 복제본을 재구성하고, 확보한 정상 데이터로 원래 자리를 다시 씁니다. 재기록이 성공하면 수선 카운터만 남고 scrub은 계속 전진합니다.

문제는 모든 복제본이 다 틀렸거나 읽히지 않을 때입니다. 이 경우 세 곳에 흔적이 남습니다.

1. **scn_errors 카운터**: 스캔 오류 수. 완료 보고의 재료입니다.
2. **영구 에러 로그(errlog)**: 어느 파일의 어느 범위가 깨졌는지 기록합니다. `zpool status -v`의 목록이자 error scrub의 입력입니다.
3. **DTL_SCRUB 마킹**: 이번 scrub으로도 못 고친 txg 구간을 vdev 장부에 적습니다(vdev.c:3086).

DTL_SCRUB은 5편에서 본 DTL 장부 시스템의 세 번째 페이지입니다. scrub이 완료되면 "마지막 scrub 이후 못 고친 txg 구간"이 DTL_MISSING을 대체해 등재됩니다. 구현 디테일도 재미있습니다. vdev.c:3379의 refcnt 2 트릭은 교체 직후의 DTL_MISSING과 방금 끝난 scrub의 DTL_SCRUB이 같은 range 구조를 참조로 공유해, 장부를 복사하는 비용 없이 소유권만 넘깁니다. 이 장부는 이후 resilver가 재시도 목록으로 읽어 들이는 대상입니다.

여기서 5편과의 중요한 대비가 나옵니다. resilver는 오류가 쌓이면 스스로 재시작하지만(dsl_scan.c:708-719), **scrub은 재시작하지 않습니다.** 오류가 나도 끝까지 순회를 마치고 수집된 오류를 보고하는 것으로 종료합니다. 검증 스캔이 실패 블록에서 무한 루프에 빠지지 않게 하는 절제 장치입니다. 아래 그림이 블록 하나의 운명을 정리합니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="scrub 오류 처리 분기 플로우. 블록 읽기와 체크섬 검증에서 시작해, 체크섬이 맞으면 조용히 다음 블록으로 통과하고(초록), 불일치하면 mirror 반대편이나 raidz 패리티로 다른 복제본을 대조하는 self-healing 재구성을 시도하며(노랑), 성공하면 원위치 재기록 후 수선 카운터를 올리고 순회를 계속하고(초록), 실패하면 scn_errors 카운터 증가와 errlog 기록, DTL_SCRUB 장부 마킹이 남는다(빨강). 어느 갈래든 scrub은 멈추지 않으며 오류 재시작은 resilver 전용 동작이다.">
  <defs>
    <marker id="zs7-f-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
    <marker id="zs7-f-yellow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#fbbf24"/>
    </marker>
    <marker id="zs7-f-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">블록 하나의 운명: 검증, 수선, 또는 장부</text>

  <rect x="330" y="46" width="220" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="440" y="73" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">블록 읽기 + 체크섬 검증</text>
  <text x="440" y="94" text-anchor="middle" font-size="10" fill="#8b949e">dsl_scan_scrub_cb (live 블록 + DDT)</text>

  <line x1="440" y1="112" x2="440" y2="136" stroke="#666666" stroke-width="1.4" stroke-dasharray="4,3" opacity="0.6"/>
  <text x="470" y="128" font-size="10" fill="#666666">체크섬 결과</text>

  <rect x="60" y="146" width="200" height="66" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="160" y="173" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">일치</text>
  <text x="160" y="194" text-anchor="middle" font-size="10" fill="#16a34a">조용히 다음 블록</text>

  <rect x="340" y="146" width="200" height="66" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="440" y="173" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">불일치</text>
  <text x="440" y="194" text-anchor="middle" font-size="10" fill="#92400e">다른 복제본으로 재구성 시도</text>

  <line x1="330" y1="79" x2="260" y2="150" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs7-f-green)"/>
  <line x1="440" y1="112" x2="440" y2="140" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#zs7-f-yellow)"/>

  <rect x="340" y="250" width="200" height="66" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="440" y="277" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">self-healing (zio repair)</text>
  <text x="440" y="298" text-anchor="middle" font-size="10" fill="#92400e">mirror 반대편 · raidz 패리티</text>

  <line x1="440" y1="212" x2="440" y2="244" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#zs7-f-yellow)"/>

  <rect x="60" y="340" width="250" height="72" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="185" y="367" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">재구성 성공</text>
  <text x="185" y="388" text-anchor="middle" font-size="10" fill="#16a34a">원위치 재기록 · 수선 카운터++ · 계속</text>

  <rect x="560" y="340" width="260" height="72" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="690" y="363" text-anchor="middle" font-size="12" font-weight="700" fill="#dc2626">재구성 실패</text>
  <text x="690" y="382" text-anchor="middle" font-size="10" fill="#dc2626">scn_errors++ · errlog 기록</text>
  <text x="690" y="399" text-anchor="middle" font-size="10" fill="#dc2626">DTL_SCRUB 마킹 (vdev.c:3086)</text>

  <line x1="400" y1="316" x2="240" y2="334" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs7-f-green)"/>
  <line x1="480" y1="316" x2="640" y2="334" stroke="#dc2626" stroke-width="1.5" marker-end="url(#zs7-f-red)"/>

  <text x="440" y="424" text-anchor="middle" font-size="10" fill="#8b949e">어느 갈래든 scrub은 멈추지 않습니다. 재시작은 resilver 전용(dsl_scan.c:708-719)</text>
</svg>

실패가 스캔을 중단시키지 않고 장부로 넘어가는 구조. 이것이 검증 스캔의 절제입니다. 그런데 못 고친 블록을 다시 보고 싶을 때는 어떻게 할까요.

## 운영의 손잡이: pause, thorough, error scrub

scrub은 시간 단위로 걸리는 작업이라 운영상 통제 장치가 필요합니다. 세 가지가 있습니다.

**pause/resume**. `zpool scrub -p`와 `-s`의 입구는 `dsl_scrub_set_pause_resume`(dsl_scan.c:1373)이며 스캔 상태에 PAUSE를 새깁니다. 일시정지는 진행 중인 I/O를 날리는 게 아니라 txg 경계에서 추가 발급을 멈추는 것에 가깝습니다. 이미 발급된 I/O는 마무리되고 resume까지 새 발급이 없습니다.

**thorough 모드**. `DSF_SCRUB_THOROUGH`(dsl_scan.h:79, 값 1<<2)는 더 빠짐없이 훑으라는 스위치입니다. 플래그가 스캔 상태에 남아 있으므로 pause/resume 도중에도 이 scrub이 thorough였다는 사실이 유지됩니다.

**error scrub**. 2.2+의 제3 스캔 모드입니다. `POOL_SCAN_ERRORSCRUB`가 별도 타입으로 등록되고(dsl_scan.c:840), 검사 대상 수를 `spa_get_last_errlog_size()`(dsl_scan.c:855)로 정합니다. 즉 전체 블록이 아니라 영구 에러 로그에 남아 있는 블록만 골라 재검사합니다. `zpool scrub -e`로 시작하며 진행도는 별도 계열로 집계됩니다.

역할이 선명합니다. scrub이 실패 블록을 errlog에 기록해 두면, error scrub은 그 장부를 입력으로 삼아 정말 고쳐졌는지를 최소 비용으로 확인합니다. 검증(full scrub)에서 기록(errlog)을 거쳐 선별 재검증(error scrub)으로 이어지는 루프의 마지막 조각입니다.

## 관찰 포인트와 튜닝

진행 상태는 `spa_scan_get_stats`(spa_misc.c:2849)가 pss_* 필드로 노출하고 `zpool status`의 scan: 행이 그 사용자 인터페이스입니다.

| 필드/항목 | 확인 방법 | 포인트 |
|---|---|---|
| pss_state, pss_start_time, pss_end_time | zpool status의 scan: 행 | 스캔 여부와 시각. scrub/resilver 구분은 pss_func |
| pss_to_examine / pss_examined | zpool status 진행률 | 완료 직후 100%에 못 미치면 checkpoint 등 제외 대상 의심 |
| pss_error_scrub_* 계열 | zpool scrub -e 진행 중 | 일반 scrub 통계와 섞이지 않는지 확인 |
| zpool status -v | 완료 후 | errlog의 사용자 모습. 파일/범위 목록 |

튜닝 파라미터의 감각도 정리해 둡니다.

| 파라미터 | 역할 | 감각 |
|---|---|---|
| zfs_scan_vdev_limit | 리프 vdev별 in-flight 한도 | foreground 지연이 심하면 낮춰 볼 1차 밸브 |
| zfs_scrub_min_time_ms | txg당 최소 작동 시간 | 늘리면 scrub이 빨라지는 대신 foreground가 늘어짐 |
| zfs_no_scrub_io / zfs_no_scrub_prefetch | 발급 차단(디버그용) | 운영 토글이 아닌 동작 검증용 |
| zfs_scan_suspend_progress | 진행 의도적 정지(테스트용) | 통계 경로를 고정 상태에서 관찰하는 후크 |

scrub 주기의 관례는 월 1회 전체 scrub이 출발점이고, 대량 쓰기나 디스크 교체, S.M.A.R.T. 이상 징후 뒤에 추가로 돌립니다. 이 글의 내용을 더하면 운용법이 정확해집니다. 오류가 잡힌 뒤에는 전체 재실행 대신 error scrub으로 정정 확인부터 하고, checkpoint가 있는 풀에서는 해석 전에 경고를 먼저 봅니다. scrub은 돌려서 끝이 아니라 순회, 오류 보고, 선별 재검증의 사이클로 다루는 것이 코드가 설계한 사용법입니다.

5편을 쓸 때는 resilver와 scrub이 비슷한 것 아닌가 했는데, 소스를 읽고 보면 같은 기계에 정반대의 철학이었습니다. resilver가 실패하면 몇 번이든 다시 시작하는 집념의 스캔이라면, scrub은 실패를 장부에 적고 끝까지 앞으로만 가는 절제의 스캔입니다. 재시작하지 않는 이유를 질문하다 보니 DTL 장부의 세 페이지와 errlog, error scrub까지가 하나의 순환 구조로 이어졌습니다. 검증은 고침이 아니라 측정이고, 측정의 결과는 다음 복구의 입력이 된다는 설계였습니다.

다음 편 (8/8, 마지막) zresmon, 시리즈의 관찰 포인트를 도구로 만든 이야기는 준비 중입니다.
