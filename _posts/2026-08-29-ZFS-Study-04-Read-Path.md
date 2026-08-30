---
layout: post
title: "ZFS 소스 학습 (4/8): Read Path - zfs_read()와 캐시 3계층"
categories: [Storage, Filesystem, OpenZFS]
description: ZFS read(2)는 캐시와 디스크 중 어디를 먼저 볼까? zfs_read부터 dbuf, ARC, zio까지 소스로 추적했습니다.
keywords: [ZFS, OpenZFS, Read Path, ARC, dbuf, L2ARC, zfs_read]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (4/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

모든 경로는 OpenZFS master 소스를 직접 읽어 확인했고 인용은 파일:라인입니다(zfs_vnops.c:319, dmu.c:244, dbuf.c:1760, arc.c:5911). 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (3/8) Write Path, 더티 데이터가 디스크로 내려가는 여덟 단계: [ZFS-Study-03-Write-Path](/2026/08/29/ZFS-Study-03-Write-Path/)

이전 편 (2/8) 아키텍처, 다섯 층 레이어 케이크와 온디스크 체인: [ZFS-Study-02-Architecture](/2026/08/29/ZFS-Study-02-Architecture/)

쓰기가 여덟 단계와 배경막까지 동원했다면 읽기의 사양은 한 문장입니다. 아무것도 변경하지 않는다(atime 제외). 대신 질문 하나가 전부를 갈라놓습니다. 이 블록이 캐시에 있는가. 있으면 디스크는 잠들어 있고, 없으면 zio 파이프라인이 깨어납니다.

## TL;DR

- 읽기는 **요청 스레드 안에서** 끝까지 처리됩니다. 쓰기의 txg 싱크 같은 배경막이 없고 개별 zio만 비동기입니다.
- 히트/미스 판정은 dbuf.c:1760의 **한 줄 비교** `miss = (db->db_state != DB_CACHED)`입니다.
- 히트여도 ARC가 블록을 **압축된 채** 저장하므로 압축 해제가 일어납니다.
- 미스면 zio read가 디스크에서 가져와 **256비트 체크섬**을 검증하고 불일치하면 재구성으로 스스로 고칩니다(self-healing).
- 방금 쓴 데이터의 읽기는 디스크를 타지 않습니다. dirty bp를 먼저 보고 ARC가 쓰기 캐시를 겸하기 때문입니다.

## 히트와 미스: 쇠문은 dbuf 하나

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
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - 읽기의 전부. 초록 히트 갈래는 디스크 I/O 0회, 빨강 미스 갈래는 체크섬 검증과 self-healing을 거쳐 합류</figcaption>
</figure>

두 갈래의 반환점은 같은 uiomove이고 차이는 디스크 I/O 0회 여부뿐입니다. 판정이 짧으니 진입부가 오히려 놀랍습니다. 읽기에서 ZIL이 나오거든요.

## zfs_read() 진입: 읽기인데 zil_commit가 나온다

zfs_read() (zfs_vnops.c:319)는 진입 검증 후 rangelock을 RL_READER로 잡고 EOF를 넘으면 0을 반환한 뒤 dmu에 넘깁니다. 그 사이 네 가지가 흥미롭습니다.

첫째, 읽기인데 zil_commit를 밟습니다. 리눅스는 read에 FRSYNC 플래그가 실려 올 수 있어 직전 동기 쓰기의 반영 보장을 위해 ZIL 커밋을 기다립니다. 읽기에서 ZIL이 나오는 몇 안 되는 지점입니다. 둘째, rangelock READER는 같은 범위의 WRITER와 충돌합니다(3편과 대칭). 셋째, O_DIRECT면 DMU_UNCACHEDIO가 붙어 ARC를 우회합니다(2.4 정식화). 넷째, 프리페치가 기본 켜짐(DMU_READ_PREFETCH)이고 대용량 read는 내부 상한 때문에 청크로 나뉩니다.

### dmu_buf_hold_array(): 오프셋을 블록 배열로

dmu_buf_hold_array() (dmu.c:244 계열)는 오프셋을 블록으로 분해합니다. recordsize 128KB 풀의 1MB 읽기는 dbuf 8개입니다. 각 dbuf는 (objset, object, level=0, blkid) 키로 해시에서 찾습니다.

L0 bp를 알려면 간접블록 하강이 필요한데 dbuf_hold_level()이 재귀로 처리하고, 간접블록은 재사용이 잦아 메타데이터 전용 dbuf cache에 남습니다. 마운트 직후 첫 읽기가 느린 이유가 이 사다리를 통째로 읽어야 하기 때문입니다. 이제 각 dbuf가 dbuf_read()를 만납니다. 여기가 이번 편의 심장입니다.

## dbuf_read(): 다섯 상태의 문지기

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

## ARC 조회와 미스의 zio 파이프라인

arc_read() (arc.c:5911)의 첫 단추는 해시 조회 buf_find()입니다. 키가 blkptr 전체(체크섬 포함)라서 한 번 적재된 블록은 다시 읽을 이유가 없습니다. 1차 해시에 없으면 L2ARC 헤더를 확인하지만, L2ARC는 ARC에서 쫓겨난 블록의 섀도 복사본일 뿐 여기도 미스면 디스크로 직행합니다.

디스크 미스는 zio read 파이프라인입니다. 발급 단계에서 vdev 트리를 내려가 mirror는 건강한 자식 하나를 골라 읽고 RAIDZ는 short-stripe면 패리티로 복구합니다. 완료 단계에서 256비트 체크섬을 검증하며 불일치하면 재구성해 원본을 교체합니다(self-healing). zpool status -v의 오류 카운터가 여기서 올라갑니다. 이후 압축을 풀고(psize에서 lsize로) ARC에 적재하면 dbuf는 DB_CACHED로 전이합니다.

쓰기와 읽기는 ARC에서 만납니다. 3편의 더티 데이터도 ARC에 있으므로 방금 쓴 데이터의 읽기는 dirty bp와 ARC 히트로 끝납니다. 쓰기 캐시와 읽기 캐시가 같다는 말의 실체입니다. 그런데 미스라는 사실 자체가 다음 읽기를 준비하는 입력이 됩니다.

## 프리페치: 미스가 다음 읽기를 예약한다

dbuf_read()의 마지막은 dmu_zfetch() 보고입니다. dnode마다 순차성을 추적하는 stream이 있어 연속성이 확인되면(기본 8블록 학습) 다음 블록들을 arc_read_prefetch로 예약합니다. 프리페치 블록은 전용 리스트에 들어가 안 쓰이면 빨리 버려져 캐시 오염을 막습니다. miss 여부를 함께 넘기는 이유가 핵심입니다. 미스면 순차 읽기 진행 중일 확률이 높으니까요.

## 캐시 3계층 총정리

데이터를 찾는 순서를 매체별로 정리하면 한 표로 끝납니다.

| 계층 | 매체 | 조회 시점 | 지연 수준 | 이 글에서의 역할 |
|---|---|---|---|---|
| ARC | RAM | 1순위: buf_find() 해시, 키는 bp 전체 | 마이크로초 | 압축된 채 저장해 RAM을 아끼고 쓰기 캐시를 겸함. 크기는 zfs_arc_max |
| L2ARC | SSD | 2순위: ARC 미스 후 L2 헤더 확인 | 서브밀리초 | ARC에서 쫓겨난 블록의 섀도 복사본. 여기도 미스면 디스크로 직행 |
| 디스크 | HDD/NVMe | 마지막: zio read 파이프라인 | 밀리초 이상 | 체크섬 검증과 self-healing, 압축 해제 후 ARC 적재. 느릴수록 zfetch 가치가 커짐 |

메타데이터에는 칸이 둘 더 있습니다. 간접블록과 dnode의 dbuf cache, HOLE을 0으로 채우는 NOFILL입니다. 관찰은 arcstat와 /proc/spl/kstat/zfs/dbufstats가 첫 지점입니다.

읽기 전에는 캐시가 압축을 푼 상태를 담는다고 상상했는데, 압축된 채를 담고 히트 시점에 푸는 것이 정답이었습니다.

다음 편 (5/8) Resilver, 죽은 디스크를 갈아끼운 뒤 데이터를 다시 채우는 경로: [ZFS-Study-05-Resilver](/2026/08/29/ZFS-Study-05-Resilver/)
