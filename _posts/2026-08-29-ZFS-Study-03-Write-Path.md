---
layout: post
title: "ZFS 소스 학습 (3/8): Write Path - zfs_write()에서 디스크까지"
categories: [Storage, Filesystem, OpenZFS]
description: "ZFS write(2)는 왜 디스크에 쓰지 않고 반환될까요? zfs_write()부터 uberblock 커밋까지 두 막으로 정리했습니다."
keywords: [ZFS, OpenZFS, write path, txg, ZIL, dmu_tx, uberblock]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (3/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

이 글의 경로와 순서는 OpenZFS master 소스를 직접 읽어 확인했고, 인용은 `파일:라인` 형식입니다(zfs_vnops.c:615, dmu_tx.c:1249, dbuf.c:2330, dsl_pool.c:683). 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (2/8) 아키텍처: [ZFS-Study-02-Architecture](/2026/08/29/ZFS-Study-02-Architecture/)

이전 편 (1/8) 바이트 지도: [ZFS-Study-01-Byte-Map](/2026/08/29/ZFS-Study-01-Byte-Map/)

ZFS에서 파일 한 번 쓰기는 두 막입니다. 앱이 기다리는 **막 1**은 호출 스레드가 rangelock부터 ARC 더티까지 가는 구간, **막 2**는 txg 스레드가 디스크로 옮기는 구간입니다. write(2)가 반환되는 순간 디스크에는 한 블록도 안 쓰였을 수 있습니다(sync=standard 기준).

## TL;DR

- 쓰기는 **두 막**입니다. 막 1은 호출 스레드가 rangelock과 dmu_tx assign, dbuf_dirty를 거쳐 ARC에 더티를 남기고 반환까지. 막 2는 txg 스레드가 디스크로 옮깁니다.
- **hold는 선언, assign은 자리 배정**입니다. dirty 총량이 `zfs_dirty_data_max`(RAM의 약 10%, 최소 128MB)에 닿으면 assign이 대기합니다. ZFS의 쓰기 백프레셔입니다.
- **fsync의 내구성 보험은 ZIL뿐**입니다. 막 1의 유일한 디스크 I/O이고 나머지는 txg를 기다립니다.
- txg는 **open, quiescing, syncing 세 상태가 동시 공존**하는 파이프라인이라 싱크 동안에도 쓰기가 멈추지 않습니다.
- 커밋은 uberblock 슬롯 **제자리 덮어쓰기 한 번**입니다(기본 5초 주기). 실패하면 풀이 suspend됩니다.

## 쓰기는 왜 두 막으로 나뉘는가

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

## 막 1: zfs_write()가 반환되기까지

### 진입과 rangelock

`zfs_write()`(zfs_vnops.c:615)는 `zfs_enter_verify_zp()` 검증 뒤 **rangelock**을 `RL_WRITER`로 잡습니다. inode가 아니라 파일 내 **범위 단위** 잠금이라 다른 구간에 쓰는 스레드는 기다리지 않습니다. 읽기는 `RL_READER`로 만납니다(다음 편).

### 블록 크기: recordsize는 천장이다

블록 크기는 "2배씩 성장"이 아니라 `MIN(recordsize, P2ROUNDUP(새 EOF, 512B))`로 새 파일 크기를 추적합니다. 낭비는 항상 511바이트 이하이고, 파일이 한 블록을 넘는 순간(`z_size > z_blksz`) 크기는 **영구 동결**됩니다. recordsize 변경이 소급 적용되지 않는 이유입니다. 파일 끝에 블록 크기만큼 쓰는 풀블록 쓰기는 `dmu_request_arcbuf()`로 **tx 열기 전에** ARC 버퍼에 복사해둡니다. 페이지폴트로 열린 txg를 붙잡는 일을 막기 위해서입니다.

### dbuf_dirty(): 더티의 실체

`dbuf_dirty()`(dbuf.c:2330)의 일은 네 가지입니다. dbuf 조회, 부분 쓰기면 이전 블록을 읽어 차 생성, dirty record 등록, ARC 버퍼로 복사. **디스크 작업은 전혀 없고** 새 데이터의 blkptr도 아직 없습니다(bp는 막 2에서 발급). 등록 순간 dnode에서 objset, dataset, pool로 **더티 연쇄**가 전파되고, 이 연쇄가 싱크 대상을 찾는 지도입니다. 이 더티는 트랜잭션 소유입니다.

## dmu_tx: hold는 선언이고 assign은 자리 배정이다

순서는 정해져 있습니다. `dmu_tx_create()` 생성, hold로 범위와 속성 선언, `dmu_tx_assign()` 배정, 쓰기와 `sa_update()`, `dmu_tx_commit()`입니다.

**hold는 예약 선언**입니다. 건드릴 범위와 속성을 미리 등록해, assign 전에 ENOSPC와 EDQUOT를 잡고 txg 끝까지 참조를 유지합니다.

**assign은 자리 배정이자 스로틀**입니다(dmu_tx.c:1249). dirty 총량이 `zfs_dirty_data_max`(기본 RAM의 약 10%, 최소 128MB)에 닿으면 ERESTART가 나고 `DMU_TX_WAIT` 호출자는 txg 싱크 후 다음 txg로 재시도합니다. ZFS의 쓰기 백프레셔이고, 정지 분석에서 봤던 `dmu_tx_assign` 스톨도 이 지점입니다.

assign을 마쳐도 디스크 I/O는 0개입니다. 예외는 fsync입니다.

## ZIL: fsync의 의미론

POSIX는 fsync 후 크래시 시 보존을 요구하지만, txg가 닫히지 않은 쓰기는 사라집니다. 이 간극을 메우는 것이 ZIL입니다(zil.c:3967). `zfs_log_write()`가 쓰기를 itx로 큐에 쌓고, fsync와 O_SYNC, `sync=always`일 때 `zil_commit()`이 itx를 lwb(기본 128KB)에 싣고 zio로 쓴 뒤 완료를 기다립니다. **막 1의 유일한 디스크 I/O**입니다. 크래시 후엔 안 쓰인 itx가 재생되고, 커밋된 ZIL은 `zil_sync()`가 무효화합니다.

감각: `logbias=latency`(기본)에서 8KB 동기 쓰기 1만 건은 ZIL에 약 80MB입니다. `logbias=throughput`이면 표시만 남습니다. slog 없는 풀에서 동기 쓰기가 느린 1순위 원인입니다.

막 1은 여기까지입니다.

## 막 2: txg 상태머신

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

## dsl_pool_sync(): 싱크는 정해진 순서로 흐른다

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

## zio 파이프라인과 uberblock 커밋

`arc_write()`(arc.c:7114)의 zio는 네 단계를 통과합니다. **transform**에서 압축과 암호화, 체크섬을 마치고, **ready 게이트**에서 압축 후 크기(psize)를 확정하고, **issue**에서 `zio_dva_allocate()`가 metaslab에 공간을 요청해(metaslab.c:5517) 자리를 확정하고, **vdev 계층**에서 mirror는 복제, raidz는 스트라이프로 분할해 leaf가 bio를 발급합니다. 핵심은 **압축 크기 확정 후 공간 할당** 순서이고, 쓰기는 항상 블록 전체를 새로 쓰므로 raidz는 read-modify-write 없이 항상 full-stripe입니다.

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

다음 편 (4/8) Read Path, zfs_read()에서 ARC 히트와 프리페치까지: [ZFS-Study-04-Read-Path](/2026/08/29/ZFS-Study-04-Read-Path/)
