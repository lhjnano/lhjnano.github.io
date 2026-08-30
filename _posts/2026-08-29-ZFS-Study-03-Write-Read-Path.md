---
layout: post
title: "ZFS 소스 학습 (3/5): Write & Read Path - zfs_write()에서 zfs_read()까지"
categories: [Storage, Filesystem, OpenZFS]
description: "ZFS write(2)는 왜 반환돼도 디스크에 없고 read(2)는 왜 빠를까요? 쓰기의 두 막과 읽기의 두 갈래를 소스로 정리했습니다."
keywords: [ZFS, OpenZFS, write path, read path, txg, ZIL, ARC, dbuf, self-healing]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (3/5). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

이 글의 경로와 순서는 OpenZFS master 소스를 직접 읽어 확인했고, 인용은 `파일:라인` 형식입니다(zfs_vnops.c:615, dmu_tx.c:1249, dbuf.c:2330, dsl_pool.c:683, dbuf.c:1760, arc.c:5911). 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (2/5) 아키텍처, 다섯 층 레이어 케이크와 온디스크 체인: [ZFS-Study-02-Architecture](/2026/08/29/ZFS-Study-02-Architecture/)

ZFS에서 파일 한 번 쓰기는 두 막입니다. 앱이 기다리는 **막 1**은 호출 스레드가 rangelock부터 ARC 더티까지 가는 구간, **막 2**는 txg 스레드가 디스크로 옮기는 구간입니다. write(2)가 반환되는 순간 디스크에는 한 블록도 안 쓰였을 수 있습니다(sync=standard 기준). 읽기는 이야기가 짧지만 갈래가 둘입니다. 이 글에서 쓰기의 두 막을 내려간 뒤, 같은 체인을 거꾸로 올라가는 읽기까지 다룹니다.

## TL;DR

- 쓰기는 두 막. 막 1(동기)은 ARC 더티까지만
- assign이 백프레셔: dirty 한도 초과 시 대기
- fsync의 보험은 ZIL뿐 = 막 1의 유일한 디스크 I/O
- 읽기 판정은 dbuf 한 줄 비교(DB_CACHED?)
- 미스면 256비트 체크섬 검증 + self-healing

## 쓰기: zfs_write()에서 uberblock까지

### 쓰기는 왜 두 막으로 나뉘는가

이전 편의 CoW가 출발점입니다. 블록을 수정하면 간접 블록부터 dnode, objset, MOS까지 연쇄가 올라갑니다. 매 write마다 디스크까지 하면 쓰기 증폭이 재앙이라 수천에서 수백만 건을 txg로 묶어 연쇄를 공유합니다. 대가는 반환 시점의 내구성 보장이 ZIL 기록뿐이라는 점입니다. 아래 그림이 이 분리 전부입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 352" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="Write Path 2막 타임라인. 위 파란 밴드는 호출 스레드가 기다리는 막 1, 즉 동기 액트로 write(2) 진입과 rangelock 획득, dmu_tx 배정, dbuf_dirty의 ARC 기록을 지나 write(2)가 반환되고, fsync 계열이면 zil_commit이 이 막의 유일한 디스크 I/O로 추가된다. 가운데 점선 화살표는 txg 닫힘(기본 5초 또는 dirty 한도)이다. 아래 초록 밴드는 txg 동기화 스레드의 막 2, 즉 비동기 액트로 txg OPEN에서 더티를 축적하고 QUIESCING에서 새 assign을 차단하며 SYNCING에서 dsl_pool_sync와 zio로 디스크에 기록해 uberblock을 교체하면 커밋된다. 디스크 반영 시점은 앱이 제어하지 않는다.">
  <defs>
    <marker id="zs3-ar-blue" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#2563eb"/></marker>
    <marker id="zs3-ar-green" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#16a34a"/></marker>
    <marker id="zs3-ar-gray" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">Write Path 2막 타임라인: 앱이 기다리는 곳은 파란 막뿐</text>
  <rect x="30" y="42" width="700" height="126" rx="8" fill="#dbeafe" opacity="0.35"/>
  <text x="50" y="64" font-size="12.5" font-weight="700" fill="#2563eb">막 1 · 동기 액트 (호출 스레드가 기다리는 구간)</text>
  <rect x="52" y="76" width="145" height="65" rx="6" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="124.5" y="97" text-anchor="middle" font-size="11.5" font-weight="700" fill="#2563eb">write(2) 진입</text>
  <text x="124.5" y="113" text-anchor="middle" font-size="10" fill="#495057">zfs_write()</text>
  <text x="124.5" y="128" text-anchor="middle" font-size="10" fill="#495057">rangelock RL_WRITER</text>
  <rect x="219" y="76" width="145" height="65" rx="6" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="291.5" y="97" text-anchor="middle" font-size="11.5" font-weight="700" fill="#2563eb">dmu_tx 배정</text>
  <text x="291.5" y="113" text-anchor="middle" font-size="10" fill="#495057">hold로 범위 선언</text>
  <text x="291.5" y="128" text-anchor="middle" font-size="10" fill="#495057">assign으로 txg 예약</text>
  <rect x="386" y="76" width="145" height="65" rx="6" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="458.5" y="97" text-anchor="middle" font-size="11.5" font-weight="700" fill="#2563eb">dbuf_dirty()</text>
  <text x="458.5" y="113" text-anchor="middle" font-size="10" fill="#495057">ARC 버퍼에 복사</text>
  <text x="458.5" y="128" text-anchor="middle" font-size="10" fill="#495057">디스크 I/O 0회</text>
  <rect x="553" y="76" width="145" height="65" rx="6" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="625.5" y="97" text-anchor="middle" font-size="11.5" font-weight="700" fill="#2563eb">write(2) 반환</text>
  <text x="625.5" y="113" text-anchor="middle" font-size="10" fill="#495057">앱은 이제 복귀</text>
  <text x="625.5" y="128" text-anchor="middle" font-size="10" fill="#495057">나머지는 배경의 몫</text>
  <line x1="199" y1="108" x2="215" y2="108" stroke="#2563eb" stroke-width="1.5" marker-end="url(#zs3-ar-blue)"/>
  <line x1="366" y1="108" x2="382" y2="108" stroke="#2563eb" stroke-width="1.5" marker-end="url(#zs3-ar-blue)"/>
  <line x1="533" y1="108" x2="549" y2="108" stroke="#2563eb" stroke-width="1.5" marker-end="url(#zs3-ar-blue)"/>
  <text x="50" y="157" font-size="10.5" fill="#92400e">fsync/O_SYNC/sync=always면 여기에 zil_commit()까지 - 막 1의 유일한 디스크 I/O</text>
  <line x1="380" y1="168" x2="380" y2="206" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs3-ar-gray)"/>
  <text x="394" y="192" font-size="10.5" fill="#2c3e50">txg 닫힘 (zfs_txg_timeout 기본 5초 또는 dirty 한도)</text>
  <rect x="30" y="210" width="700" height="126" rx="8" fill="#dcfce7" opacity="0.35"/>
  <text x="50" y="232" font-size="12.5" font-weight="700" fill="#16a34a">막 2 · 비동기 액트 (txg 동기화 스레드가 처리)</text>
  <rect x="52" y="244" width="145" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="124.5" y="265" text-anchor="middle" font-size="11.5" font-weight="700" fill="#16a34a">txg OPEN</text>
  <text x="124.5" y="281" text-anchor="middle" font-size="10" fill="#495057">더티 계속 축적</text>
  <text x="124.5" y="296" text-anchor="middle" font-size="10" fill="#495057">막 1과 동시 진행</text>
  <rect x="219" y="244" width="145" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="291.5" y="265" text-anchor="middle" font-size="11.5" font-weight="700" fill="#16a34a">QUIESCING</text>
  <text x="291.5" y="281" text-anchor="middle" font-size="10" fill="#495057">새 assign 차단</text>
  <text x="291.5" y="296" text-anchor="middle" font-size="10" fill="#495057">기존 tx 마무리 대기</text>
  <rect x="386" y="244" width="145" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="458.5" y="265" text-anchor="middle" font-size="11.5" font-weight="700" fill="#16a34a">SYNCING</text>
  <text x="458.5" y="281" text-anchor="middle" font-size="10" fill="#495057">dsl_pool_sync()</text>
  <text x="458.5" y="296" text-anchor="middle" font-size="10" fill="#495057">arc_write → zio</text>
  <rect x="553" y="244" width="145" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="625.5" y="265" text-anchor="middle" font-size="11.5" font-weight="700" fill="#16a34a">디스크 + 커밋</text>
  <text x="625.5" y="281" text-anchor="middle" font-size="10" fill="#495057">zio 완료 확인</text>
  <text x="625.5" y="296" text-anchor="middle" font-size="10" fill="#495057">uberblock 교체</text>
  <line x1="199" y1="276" x2="215" y2="276" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs3-ar-green)"/>
  <line x1="366" y1="276" x2="382" y2="276" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs3-ar-green)"/>
  <line x1="533" y1="276" x2="549" y2="276" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs3-ar-green)"/>
  <text x="50" y="325" font-size="10.5" fill="#2c3e50">디스크 반영 시점은 앱이 제어하지 않습니다. 내구성 보험은 ZIL에 쓴 것뿐입니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - 두 막의 경계. 앱이 기다리는 곳은 파란 막 1뿐이고, 파란 막의 유일한 디스크 I/O는 fsync의 ZIL 기록</figcaption>
</figure>

그림의 경계선이 이번 편의 목차입니다.

### 막 1: zfs_write()가 반환되기까지

#### 진입과 rangelock

`zfs_write()`(zfs_vnops.c:615)는 `zfs_enter_verify_zp()` 검증 뒤 **rangelock**을 `RL_WRITER`로 잡습니다. inode가 아니라 파일 내 **범위 단위** 잠금이라 다른 구간에 쓰는 스레드는 기다리지 않습니다. 읽기는 `RL_READER`로 만납니다(이 글의 읽기 절).

#### 블록 크기: recordsize는 천장이다

블록 크기는 "2배씩 성장"이 아니라 `MIN(recordsize, P2ROUNDUP(새 EOF, 512B))`로 새 파일 크기를 추적합니다. 낭비는 항상 511바이트 이하이고, 파일이 한 블록을 넘는 순간(`z_size > z_blksz`) 크기는 **영구 동결**됩니다. recordsize 변경이 소급 적용되지 않는 이유입니다. 파일 끝에 블록 크기만큼 쓰는 풀블록 쓰기는 `dmu_request_arcbuf()`로 **tx 열기 전에** ARC 버퍼에 복사해둡니다. 페이지폴트로 열린 txg를 붙잡는 일을 막기 위해서입니다.

#### dbuf_dirty(): 더티의 실체

`dbuf_dirty()`(dbuf.c:2330)의 일은 네 가지입니다. dbuf 조회, 부분 쓰기면 이전 블록을 읽어 차 생성, dirty record 등록, ARC 버퍼로 복사. **디스크 작업은 전혀 없고** 새 데이터의 blkptr도 아직 없습니다(bp는 막 2에서 발급). 등록 순간 dnode에서 objset, dataset, pool로 **더티 연쇄**가 전파되고, 이 연쇄가 싱크 대상을 찾는 지도입니다. 이 더티는 트랜잭션 소유입니다.

### dmu_tx: hold는 선언이고 assign은 자리 배정이다

순서는 정해져 있습니다. `dmu_tx_create()` 생성, hold로 범위와 속성 선언, `dmu_tx_assign()` 배정, 쓰기와 `sa_update()`, `dmu_tx_commit()`입니다.

**hold는 예약 선언**입니다. 건드릴 범위와 속성을 미리 등록해, assign 전에 ENOSPC와 EDQUOT를 잡고 txg 끝까지 참조를 유지합니다.

**assign은 자리 배정이자 스로틀**입니다(dmu_tx.c:1249). dirty 총량이 `zfs_dirty_data_max`(기본 RAM의 약 10%, 최소 128MB)에 닿으면 ERESTART가 나고 `DMU_TX_WAIT` 호출자는 txg 싱크 후 다음 txg로 재시도합니다. ZFS의 쓰기 백프레셔이고, 정지 분석에서 봤던 `dmu_tx_assign` 스톨도 이 지점입니다.

assign을 마쳐도 디스크 I/O는 0개입니다. 예외는 fsync입니다.

### ZIL: fsync의 의미론

POSIX는 fsync 후 크래시 시 보존을 요구하지만, txg가 닫히지 않은 쓰기는 사라집니다. 이 간극을 메우는 것이 ZIL입니다(zil.c:3967). `zfs_log_write()`가 쓰기를 itx로 큐에 쌓고, fsync와 O_SYNC, `sync=always`일 때 `zil_commit()`이 itx를 lwb(기본 128KB)에 싣고 zio로 쓴 뒤 완료를 기다립니다. **막 1의 유일한 디스크 I/O**입니다. 크래시 후엔 안 쓰인 itx가 재생되고, 커밋된 ZIL은 `zil_sync()`가 무효화합니다.

감각: `logbias=latency`(기본)에서 8KB 동기 쓰기 1만 건은 ZIL에 약 80MB입니다. `logbias=throughput`이면 표시만 남습니다. slog 없는 풀에서 동기 쓰기가 느린 1순위 원인입니다.

막 1은 여기까지입니다.

### 막 2: txg 상태머신

txg는 번호가 매겨진 쓰기 묶음이며 세 상태가 항상 **동시에** 존재합니다(enum은 spa.h:955).

| 상태 | 담당 | 하는 일 | 블로킹 여부 |
|---|---|---|---|
| OPEN | 모든 쓰기 스레드 | dmu_tx assign과 dbuf_dirty로 자유롭게 더티 축적 | 아니오 |
| QUIESCING | txg_quiesce_thread (txg.c:114) | 새 assign 차단. 잡고 있던 tx가 전부 commit될 때까지 대기 후 다음 txg를 OPEN | 닫히기 직전의 새 assign은 다음 txg로 |
| SYNCING | txg_sync_thread (txg.c:520) | 그 txg의 모든 더티를 디스크로. 완료 후 다음 quiesce 유도 | 동기 참여자(sync task 등)만 |

타이머는 `zfs_txg_timeout`(기본 5초)과 dirty 총량 조기 닫힘 둘입니다. 핵심은 **quiesce가 open과 겹친다**는 설계로, 싱크 중인 txg(N-2) 위에 이미 열린 txg(N)가 있어 쓰기는 싱크를 기다리지 않습니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 300" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="txg 상태머신 순환도. 파란 OPEN 상태는 모든 쓰기 스레드가 dmu_tx assign과 dbuf_dirty로 더티를 축적하는 상태다. txg가 닫히면 노란 QUIESCING으로 넘어가 새 assign을 차단하고 남은 트랜잭션 커밋을 기다린 뒤 다음 txg를 연다. 초록 SYNCING에서는 dsl_pool_sync와 zio로 모든 더티를 디스크에 기록하고 uberblock을 커밋한다. 커밋이 끝난 txg는 역할을 마치고 다음 txg는 이미 열려 있어 쓰기는 싱크 동안에도 멈추지 않는다. 세 상태는 항상 동시에 존재한다.">
  <defs>
    <marker id="zs3-ar2" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">txg 상태머신: 세 상태가 항상 동시에 돈다</text>
  <text x="380" y="46" text-anchor="middle" font-size="11" fill="#8b949e">txg N은 OPEN, N-1은 QUIESCING, N-2는 SYNCING - 싱크 동안에도 쓰기는 멈추지 않습니다</text>
  <rect x="55" y="78" width="185" height="78" rx="6" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="147.5" y="102" text-anchor="middle" font-size="13" font-weight="700" fill="#2563eb">OPEN</text>
  <text x="147.5" y="121" text-anchor="middle" font-size="10.5" fill="#495057">모든 쓰기 스레드가 dmu_tx assign</text>
  <text x="147.5" y="137" text-anchor="middle" font-size="10.5" fill="#495057">dbuf_dirty로 더티 축적</text>
  <rect x="288" y="78" width="185" height="78" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="380.5" y="102" text-anchor="middle" font-size="13" font-weight="700" fill="#92400e">QUIESCING</text>
  <text x="380.5" y="121" text-anchor="middle" font-size="10.5" fill="#495057">새 assign 차단</text>
  <text x="380.5" y="137" text-anchor="middle" font-size="10.5" fill="#495057">남은 tx 커밋 대기 후 다음 txg OPEN</text>
  <rect x="521" y="78" width="185" height="78" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="613.5" y="102" text-anchor="middle" font-size="13" font-weight="700" fill="#16a34a">SYNCING</text>
  <text x="613.5" y="121" text-anchor="middle" font-size="10.5" fill="#495057">dsl_pool_sync → zio</text>
  <text x="613.5" y="137" text-anchor="middle" font-size="10.5" fill="#495057">완료 = uberblock 커밋</text>
  <line x1="242" y1="117" x2="284" y2="117" stroke="#666" stroke-width="1.5" marker-end="url(#zs3-ar2)"/>
  <text x="263" y="110" text-anchor="middle" font-size="10" fill="#8b949e">닫힘</text>
  <line x1="475" y1="117" x2="517" y2="117" stroke="#666" stroke-width="1.5" marker-end="url(#zs3-ar2)"/>
  <text x="496" y="110" text-anchor="middle" font-size="10" fill="#8b949e">싱크</text>
  <path d="M613,156 L613,196 L147,196 L147,162" fill="none" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs3-ar2)"/>
  <text x="380" y="188" text-anchor="middle" font-size="11" fill="#2c3e50">커밋 완료 - 다음 txg는 이미 열려 있다 (파이프라인)</text>
  <text x="380" y="232" text-anchor="middle" font-size="10.5" fill="#495057">쓰기 스레드는 SYNCING을 기다리지 않고 항상 열린 txg에 assign합니다.</text>
  <text x="380" y="250" text-anchor="middle" font-size="10.5" fill="#495057">관찰: /proc/spl/kstat/zfs/ 아래 txgs 통계에서 txg별 체류 시간과 기록량이 실시간으로 보입니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - 세 상태의 동시 공존. 싱크(N-2) 위에 이미 열린 txg(N)가 있어 쓰기는 멈추지 않는다</figcaption>
</figure>

SYNCING에 들어선 txg는 정해진 순서로 일합니다.

### dsl_pool_sync(): 싱크는 정해진 순서로 흐른다

SYNCING에 들어가면 `spa_sync()`이 `dsl_pool_sync()`(dsl_pool.c:683)를 호출합니다. 실제 순서의 요약입니다.

```c
tx = dmu_tx_create_assigned(dp, txg);    /* 싱크 컨텍스트 전용 tx */

/* (1) 블록 쓰기 전에 끝내야 할 early sync tasks */
while ((dst = txg_list_remove(&dp->dp_early_sync_tasks, txg)) != NULL)
        dsl_sync_task_sync(dst, tx);

/* (2) 더티 데이터셋 싱크: "매우 큰 zio 트리"(소스 주석 원문) */
rio = zio_root(spa, NULL, NULL, ZIO_FLAG_MUSTSUCCEED);
while ((ds = txg_list_remove(&dp->dp_dirty_datasets, txg)) != NULL)
        dsl_dataset_sync(ds, rio, tx);
VERIFY0(zio_wait(rio));                  /* 블록 발급 완료 대기 */

/* (3) 쿼터 정산: blk_fill/birth 기반 사용량을 dp_sync_taskq로 병렬 계산 */
/* (4) 2차 싱크: 정산 갱신이 다시 더티로 만든 데이터셋 재발급 */
/* (5) deadlist/livelist 동기화 뒤 spa_sync이 마무리:
       sync tasks → dirty dirs → metaslab space map → ZIL 헤더 → uberblock */
```

읽을 포인트는 셋입니다. **쿼터 정산이 데이터 이후**라는 점, 정산 갱신이 다시 더티를 만들어 (4)의 2차 싱크가 필요하다는 점, 그래서 쓰기 경로의 쿼터 사전 체크가 "대략적"일 수밖에 없다는 점입니다.

각 더티 dnode는 `dnode_sync()`를 지납니다. 교체된 이전 bp는 free 목록에 **예약**만 되고 회수는 다음 txg(단편화 시 두 txg), 스냅샷 참조 시엔 deadlist입니다. L0가 새로 쓰이면 L1부터 objset 블록까지 연쇄가 올라가고, 마지막에 `arc_write()`가 bp 발급을 시작합니다. 여기부터는 zio의 세계입니다.

### zio 파이프라인과 uberblock 커밋

`arc_write()`(arc.c:7114)의 zio는 네 단계를 통과합니다. **transform**에서 압축과 암호화, 체크섬을 마치고 **ready 게이트**에서 압축 후 크기(psize)를 확정합니다.

이어 **issue**에서 `zio_dva_allocate()`가 metaslab에 공간을 요청해(metaslab.c:5517) 자리를 확정하고, **vdev 계층**에서 mirror는 복제, raidz는 스트라이프로 분할합니다.

핵심은 **압축 크기 확정 후 공간 할당** 순서입니다. 쓰기는 항상 블록 전체를 새로 쓰므로 raidz는 read-modify-write 없이 항상 full-stripe입니다.

모든 zio 완료와 sync pass가 끝나면 `uberblock_sync()`가 라벨마다(최대 4개) 링의 다음 슬롯을 **제자리 덮어쓰기**합니다. 이 순간이 커밋입니다. 이전 txg의 세계는 그대로 남아 롤백이 가능하고, 이전 블록들은 다음 txg에 회수됩니다. 이 쓰기도 MUSTSUCCEED라 실패하면 풀이 suspend, 곧 "커밋 불능"입니다.

두 막 전체의 함수 체인을 표로 남깁니다.

| 함수 | 위치 | 역할 |
|---|---|---|
| **막 1 · 동기 액트 (호출 스레드)** | | |
| `zfs_write()` | zfs_vnops.c:615 | rangelock, 블록 크기 결정, 쿼터 사전 체크 |
| `zfs_log_write()` | zfs_vnops.c | fsync 대상 쓰기를 itx로 ZIL 큐에 적립 |
| `dmu_tx_create/hold/assign` | dmu_tx.c:1249 | txg 자리 예약, dirty 한도에서 스로틀 |
| `dbuf_dirty()` | dbuf.c:2330 | ARC 더티 등록, dnode→pool 연쇄 전파 |
| `zil_commit()` | zil.c:3967 | fsync의 유일한 디스크 I/O, 완료 대기 |
| **막 2 · 비동기 액트 (txg 동기화 스레드)** | | |
| `txg_quiesce_thread()` | txg.c:114 | OPEN을 QUIESCING으로, 다음 txg 개방 |
| `txg_sync_thread()` | txg.c:520 | SYNCING 진입, spa_sync() 호출 |
| `spa_sync()` → `dsl_pool_sync()` | dsl_pool.c:683 | 데이터 → 쿼터 정산 → 2차 싱크 → deadlist |
| `dnode_sync()` | dnode_sync.c | bp 교체 연쇄, 이전 bp는 free 예약 |
| `arc_write()` | arc.c:7114 | 더티 ARC 버퍼를 zio 트리로 발급 |
| `zio_write()` → `zio_dva_allocate()` | zio.c | transform → ready 게이트 → DVA 할당 |
| `metaslab_alloc_dva()` | metaslab.c:5517 | normal/special/dedup 클래스 자리 배정 |
| vdev mirror/raidz 계층 | vdev_*.c | 자식 zio 분할·복제, leaf에서 bio 발급 |
| `uberblock_sync()` | spa.c | 링 다음 슬롯 제자리 덮어쓰기 = 커밋 |

읽기 전에는 write(2)가 반환하면 디스크에 있다고 믿었습니다. 지나고 보니 반환은 "ARC에 있음"이고, 디스크는 5초 뒤 uberblock 슬롯이 덮어써지는 순간의 일입니다. `/proc/spl/kstat/zfs/<pool>/txgs`를 열어두고 큰 파일을 복사하면 막 2가 한 줄씩 확인됩니다.

쓰기가 여덟 단계와 배경막까지 동원했다면 읽기의 사양은 한 문장입니다. 아무것도 변경하지 않는다(atime 제외). 대신 질문 하나가 전부를 갈라놓습니다. 이 블록이 캐시에 있는가. 있으면 디스크는 잠들어 있고, 없으면 zio 파이프라인이 깨어납니다.

## 읽기: zfs_read()와 캐시 3계층

### 히트와 미스: 쇠문은 dbuf 하나

읽기의 쇠문은 dbuf 하나입니다. read(2)가 zfs_read()로 진입해 dmu_buf_hold_array()가 블록 단위 dbuf를 확보하면 dbuf_read()가 상태를 봅니다. DB_CACHED면 ARC 버퍼를 바로 쓰고, 그 외면 zio를 발급합니다. 아래 그림이 읽기의 전부입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 556" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="ZFS 읽기 경로 플로우다. 앱의 read(2)가 zfs_read로 진입해 rangelock을 잡고, dmu_buf_hold_array가 (objset, object, level, blkid) 키로 dbuf를 확보하며, dbuf_read가 db_state가 DB_CACHED인지 판정한다. 히트면 초록 갈래로 ARC 버퍼를 arc_untransform로 압축 해제해 uiomove로 바로 복사해 반환한다(디스크 I/O 0회). 미스면 빨간 갈래로 DB_UNCACHED에서 arc_read가 zio read를 발급해 vdev를 거쳐 디스크에서 읽고, 256비트 체크섬 검증과 압축 해제를 거쳐 ARC에 적재한 뒤 DB_CACHED로 전이해 같은 방식으로 반환한다. 미스 사실은 dmu_zfetch에 보고되어 다음 블록을 미리 예약한다.">
  <defs>
    <marker id="zs4-ar" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
    <marker id="zs4-arh" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#16a34a"/></marker>
    <marker id="zs4-arm" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#dc2626"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">읽기 경로: 쇠문은 dbuf 하나, 갈래는 둘</text>
  <rect x="160" y="38" width="440" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="380" y="64" text-anchor="middle" font-size="12.5" font-weight="700" fill="#2c3e50">앱의 read(2) → zfs_read() 진입</text>
  <text x="380" y="85" text-anchor="middle" font-size="10.5" fill="#666">rangelock RL_READER 확보, EOF를 넘으면 즉시 0 반환</text>
  <line x1="380" y1="103" x2="380" y2="118" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-ar)"/>
  <rect x="160" y="121" width="440" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="380" y="147" text-anchor="middle" font-size="12.5" font-weight="700" fill="#2c3e50">dmu_buf_hold_array()</text>
  <text x="380" y="168" text-anchor="middle" font-size="10.5" fill="#666">(objset, object, level, blkid) 키로 dbuf 확보. 1MB 읽기는 128KB 블록 8개</text>
  <line x1="380" y1="186" x2="380" y2="201" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-ar)"/>
  <rect x="160" y="204" width="440" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="380" y="230" text-anchor="middle" font-size="12.5" font-weight="700" fill="#2c3e50">dbuf_read(): db_state == DB_CACHED ?</text>
  <text x="380" y="251" text-anchor="middle" font-size="10.5" fill="#666">이 한 줄 비교가 히트/미스 판정 (dbuf.c:1760)</text>
  <line x1="290" y1="269" x2="205" y2="283" stroke="#16a34a" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-arh)"/>
  <text x="216" y="270" font-size="10.5" font-weight="600" fill="#16a34a">히트</text>
  <line x1="470" y1="269" x2="555" y2="283" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-arm)"/>
  <text x="520" y="270" font-size="10.5" font-weight="600" fill="#dc2626">미스</text>
  <rect x="40" y="287" width="320" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="200" y="313" text-anchor="middle" font-size="12.5" font-weight="700" fill="#16a34a">ARC 버퍼 즉시 사용</text>
  <text x="200" y="334" text-anchor="middle" font-size="10.5" fill="#666">압축된 채 저장 → arc_untransform로 해제</text>
  <line x1="200" y1="352" x2="200" y2="366" stroke="#16a34a" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-arh)"/>
  <rect x="40" y="370" width="320" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="200" y="396" text-anchor="middle" font-size="12.5" font-weight="700" fill="#16a34a">uiomove로 사용자 버퍼에 복사</text>
  <text x="200" y="417" text-anchor="middle" font-size="10.5" fill="#666">디스크 I/O 0회로 반환. 끝</text>
  <rect x="400" y="287" width="320" height="65" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="560" y="313" text-anchor="middle" font-size="12.5" font-weight="700" fill="#dc2626">DB_UNCACHED → arc_read() 미스</text>
  <text x="560" y="334" text-anchor="middle" font-size="10.5" fill="#666">zio read 발급, vdev 하강(mirror 선택, RAIDZ 복구)</text>
  <line x1="560" y1="352" x2="560" y2="366" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-arm)"/>
  <rect x="400" y="370" width="320" height="65" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="560" y="396" text-anchor="middle" font-size="12.5" font-weight="700" fill="#dc2626">디스크 → 체크섬 검증 → 압축 해제</text>
  <text x="560" y="417" text-anchor="middle" font-size="10.5" fill="#666">256비트 체크섬 불일치면 self-healing 재구성</text>
  <line x1="560" y1="435" x2="560" y2="449" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs4-arm)"/>
  <rect x="400" y="453" width="320" height="65" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="560" y="479" text-anchor="middle" font-size="12.5" font-weight="700" fill="#dc2626">ARC 적재 → DB_CACHED 전이</text>
  <text x="560" y="500" text-anchor="middle" font-size="10.5" fill="#666">대기자를 깨우고 uiomove. 다음 읽기는 히트</text>
  <text x="380" y="546" text-anchor="middle" font-size="10.5" fill="#8b949e">미스였다는 사실은 dmu_zfetch에 보고되어 다음 블록을 미리 예약합니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - 읽기의 전부. 초록 히트 갈래는 디스크 I/O 0회, 빨강 미스 갈래는 체크섬 검증과 self-healing을 거쳐 합류</figcaption>
</figure>

두 갈래의 반환점은 같은 uiomove이고 차이는 디스크 I/O 0회 여부뿐입니다. 판정이 짧으니 진입부가 눈에 듭니다. 읽기에서 ZIL이 나옵니다.

### zfs_read() 진입: 읽기인데 zil_commit가 나온다

zfs_read() (zfs_vnops.c:319)는 진입 검증 후 rangelock을 RL_READER로 잡고 EOF를 넘으면 0을 반환한 뒤 dmu에 넘깁니다. 그 사이 네 가지가 흥미롭습니다.

첫째, 읽기인데 zil_commit를 밟습니다. 리눅스는 read에 FRSYNC 플래그가 실려 올 수 있어 직전 동기 쓰기의 반영 보장을 위해 ZIL 커밋을 기다립니다. 읽기에서 ZIL이 나오는 몇 안 되는 지점입니다. 둘째, rangelock READER는 같은 범위의 WRITER와 충돌합니다(앞 절의 쓰기와 대칭). 셋째, O_DIRECT면 DMU_UNCACHEDIO가 붙어 ARC를 우회합니다(2.4 정식화). 넷째, 프리페치가 기본 켜짐(DMU_READ_PREFETCH)이고 대용량 read는 내부 상한 때문에 청크로 나뉩니다.

#### dmu_buf_hold_array(): 오프셋을 블록 배열로

dmu_buf_hold_array() (dmu.c:244 계열)는 오프셋을 블록으로 분해합니다. recordsize 128KB 풀의 1MB 읽기는 dbuf 8개입니다. 각 dbuf는 (objset, object, level=0, blkid) 키로 해시에서 찾습니다.

L0 bp를 알려면 간접블록 하강이 필요한데 dbuf_hold_level()이 재귀로 처리하고, 간접블록은 재사용이 잦아 메타데이터 전용 dbuf cache에 남습니다. 마운트 직후 첫 읽기가 느린 이유가 이 사다리를 통째로 읽어야 하기 때문입니다. 이제 각 dbuf가 dbuf_read()를 만납니다. 여기가 이번 편의 심장입니다.

### dbuf_read(): 다섯 상태의 문지기

dbuf_read() (dbuf.c:1760)의 판정은 `miss = (db->db_state != DB_CACHED)` 한 줄입니다. 다른 스레드가 읽는 중(DB_READ)이거나 채우는 중(DB_FILL)이면 cv_wait로 기다렸다가 다시 판정합니다. 상태 전이를 표로 남깁니다.

| 상태 | 의미 | 들어오는 길 | 나가는 길 |
|---|---|---|---|
| DB_UNCACHED | ARC 버퍼 없는 초기 상태 | dbuf 생성 직후, I/O 실패 복귀 | dbuf_read_impl()이 DB_READ로 |
| DB_READ | 디스크 읽기 진행 중 | arc_read 발급 직전 | 완료 콜백이 DB_CACHED로, 실패면 UNCACHED 복귀 |
| DB_CACHED | ARC 버퍼 연결됨, 읽기 가능 | READ 또는 FILL 완료 | 캐시 축출 시 UNCACHED로 |
| DB_FILL | 쓰기가 버퍼를 채우는 중(3편) | 쓰기 경로의 dbuf_will_dirty 계열 | 채우기 끝나면 CACHED(dirty) |
| DB_NOFILL | HOLE이라 읽을 블록 없음 | BP_IS_HOLE 판정 | I/O 없이 0으로 채움 |

cv_wait의 묘미는 병합입니다. 같은 블록의 동시 미스가 I/O 하나로 합쳐집니다.

히트 갈래도 공짜는 아닙니다. ARC는 블록을 압축된 채 저장하므로 히트 시점에 arc_untransform()로 압축 해제와 복호화를 합니다. 미스 갈래에서는 dmu_buf_get_bp_from_dbuf()가 dirty record의 bp를 먼저 봅니다. 방금 쓴 블록은 아직 디스크 bp가 없으므로 이 우선순위가 write-then-read 일관성을 지킵니다. HOLE이면 zio조차 만들지 않습니다. 이제 ARC로 내려갑니다.

### ARC 조회와 미스의 zio 파이프라인

arc_read() (arc.c:5911)의 첫 단추는 해시 조회 buf_find()입니다. 키가 blkptr 전체(체크섬 포함)라서 한 번 적재된 블록은 다시 읽을 이유가 없습니다. 1차 해시에 없으면 L2ARC 헤더를 확인하지만, L2ARC는 ARC에서 쫓겨난 블록의 섀도 복사본일 뿐 여기도 미스면 디스크로 직행합니다.

디스크 미스는 zio read 파이프라인입니다. 발급 단계에서 vdev 트리를 내려가 mirror는 건강한 자식 하나를 골라 읽고 RAIDZ는 short-stripe면 패리티로 복구합니다. 완료 단계에서 256비트 체크섬을 검증하며 불일치하면 재구성해 원본을 교체합니다(self-healing). zpool status -v의 오류 카운터가 여기서 올라갑니다. 이후 압축을 풀고(psize에서 lsize로) ARC에 적재하면 dbuf는 DB_CACHED로 전이합니다.

쓰기와 읽기는 ARC에서 만납니다. 3편의 더티 데이터도 ARC에 있으므로 방금 쓴 데이터의 읽기는 dirty bp와 ARC 히트로 끝납니다. 쓰기 캐시와 읽기 캐시가 같다는 말의 실체입니다. 그런데 미스라는 사실 자체가 다음 읽기를 준비하는 입력이 됩니다.

### 프리페치: 미스가 다음 읽기를 예약한다

dbuf_read()의 마지막은 dmu_zfetch() 보고입니다. dnode마다 순차성을 추적하는 stream이 있어 연속성이 확인되면(기본 8블록 학습) 다음 블록들을 arc_read_prefetch로 예약합니다. 프리페치 블록은 전용 리스트에 들어가 안 쓰이면 빨리 버려져 캐시 오염을 막습니다. miss 여부를 함께 넘기는 이유가 핵심입니다. 미스면 순차 읽기 진행 중일 확률이 높으니까요.

### 캐시 3계층 총정리

데이터를 찾는 순서를 매체별로 정리하면 한 표로 끝납니다.

| 계층 | 매체 | 조회 시점 | 지연 수준 | 이 글에서의 역할 |
|---|---|---|---|---|
| ARC | RAM | 1순위: buf_find() 해시, 키는 bp 전체 | 마이크로초 | 압축된 채 저장해 RAM을 아끼고 쓰기 캐시를 겸함. 크기는 zfs_arc_max |
| L2ARC | SSD | 2순위: ARC 미스 후 L2 헤더 확인 | 서브밀리초 | ARC에서 쫓겨난 블록의 섀도 복사본. 여기도 미스면 디스크로 직행 |
| 디스크 | HDD/NVMe | 마지막: zio read 파이프라인 | 밀리초 이상 | 체크섬 검증과 self-healing, 압축 해제 후 ARC 적재. 느릴수록 zfetch 가치가 커짐 |

메타데이터에는 칸이 둘 더 있습니다. 간접블록과 dnode의 dbuf cache, HOLE을 0으로 채우는 NOFILL입니다. 관찰은 arcstat와 /proc/spl/kstat/zfs/dbufstats가 첫 지점입니다.

읽기 전에는 캐시가 압축을 푼 상태를 담는다고 상상했는데, 압축된 채를 담고 히트 시점에 푸는 것이 정답이었습니다.

다음 편 (4/5) ZIL·Resilver·Scrub, fsync의 약속 장부와 자가복구의 두 스캔: [ZFS-Study-04-ZIL-Resilver-Scrub](/2026/08/29/ZFS-Study-04-ZIL-Resilver-Scrub/)
