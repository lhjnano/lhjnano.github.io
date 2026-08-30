---
layout: post
title: "ZFS 소스 학습 (2/5): 아키텍처 - ZPL에서 SPA까지 레이어 케이크"
categories: [Storage, Filesystem, OpenZFS]
description: ZFS는 파일 하나를 쓸 때 몇 개 계층을 지나 디스크에 닿을까? 레이어 케이크와 온디스크 체인을 소스 기준으로 정리했습니다.
keywords: [ZFS, OpenZFS, 아키텍처, DMU, SPA, uberblock, blkptr]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (2/5). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

이 글의 모든 구조는 OpenZFS master 소스를 직접 읽어 확인했고, 인용은 `파일:라인` 형식으로 남깁니다(zfs_vnops.c:615, dbuf.c:2330, arc.c:7114). 라인 번호는 커밋마다 흐르므로 함수명으로 grep하는 편이 안전합니다.

이전 편 (1/5) 바이트 지도, 바닥의 바이트를 봤으니 이제 계층을 오른다: [ZFS-Study-01-Byte-Map](/2026/08/29/ZFS-Study-01-Byte-Map/)

`echo hello > note.txt` 한 줄이면 ZFS 커널 코드의 다섯 개 층을 통과합니다. 그리고 write(2)가 반환하는 순간 디스크는 아직 아무것도 모르고 있습니다. 정작 커밋은 잠시 뒤, 디스크 양 끝 라벨 안쪽의 1KB 슬롯 하나가 덮어써지는 순간에 일어납니다. 이번 편에서는 계층 다섯 개, 디스크 체인 여섯 고리, 구조체 네 개만 기억하면 됩니다.

## TL;DR

- **ZFS는 5층 레이어 케이크.** ZPL이 POSIX 시맨틱을 접수하면 DMU가 트랜잭션으로 묶고, SPA가 공간을 내고, ZIO가 변환해 발급하며, vdev가 실제 디스크에 I/O를 날립니다.
- **온디스크의 모든 것은 하나의 CoW 트리.** uberblock → MOS → 데이터셋 → dnode → blkptr → 데이터 블록.
- **커밋은 uberblock 교체 한 번.** 데이터를 쓰는 행위가 아니라 포인터를 옮기는 행위입니다.
- **write(2)의 빠른 반환은 ARC까지만.** 디스크 반영은 txg(기본 5초) 싱크가 비동기로 처리합니다. fsync만 ZIL이 예외로 즉시 갑니다.
- **구조체 네 개**(blkptr, dnode, objset, uberblock)가 온디스크 포맷의 90%입니다.

## 레이어 케이크: 호출은 항상 한 층 아래로

ZFS는 엄격한 레이어드 아키텍처입니다. 각 층은 바로 아래 층의 API만 호출하고, 층을 건너뛰거나 거슬러 올라가지 않습니다. 이 규칙을 모르면 소스에서 길을 잃습니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 484" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="ZFS 레이어 케이크 구조도: 위에서부터 ZPL이 POSIX 파일 시맨틱으로 쓰기를 접수하고, DMU가 객체 단위 트랜잭션으로 블록을 더티로 만들며, SPA가 풀에서 공간을 할당하고, ZIO가 압축과 체크섬 변환을 거쳐 발급하면, vdev가 미러와 RAIDZ 논리로 실제 디스크에 I/O를 발급한다. 호출 방향은 항상 한 층 아래로만 향하고, ARC와 ZIL은 층이 아니라 옆에 붙는 횡단 서비스다.">
  <defs>
    <marker id="zs2-ar1" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">ZFS 레이어 케이크: 호출은 항상 한 층 아래로</text>
  <rect x="40" y="40" width="680" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="60" y="65" font-size="13" font-weight="700" fill="#2c3e50">ZPL (ZFS POSIX Layer) · zfs_vnops.c</text>
  <text x="60" y="86" font-size="11" fill="#666">이 파일의 이 오프셋에 이 바이트를 써라: POSIX 시맨틱, rangelock, fsync면 ZIL 로그</text>
  <line x1="380" y1="106" x2="380" y2="121" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar1)"/>
  <rect x="40" y="125" width="680" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="60" y="150" font-size="13" font-weight="700" fill="#2c3e50">DMU (Data Management Unit) · dmu.c · dbuf.c</text>
  <text x="60" y="171" font-size="11" fill="#666">이 object의 이 blkid를 더티로 만들어라: 객체 단위 트랜잭션(txg)과 CoW 보장</text>
  <line x1="380" y1="191" x2="380" y2="206" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar1)"/>
  <rect x="40" y="210" width="680" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="60" y="235" font-size="13" font-weight="700" fill="#2c3e50">SPA (Storage Pool Allocator) · spa.c · txg.c · metaslab.c</text>
  <text x="60" y="256" font-size="11" fill="#666">이 txg에 이 크기의 블록 자리를 내라: 풀 관리, 공간 할당, MOS 메타데이터</text>
  <line x1="380" y1="276" x2="380" y2="291" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar1)"/>
  <rect x="40" y="295" width="680" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="60" y="320" font-size="13" font-weight="700" fill="#2c3e50">ZIO (I/O 파이프라인) · zio.c · abd.c</text>
  <text x="60" y="341" font-size="11" fill="#666">이 블록을 압축해 체섬 달아 발급해라: 변환과 발급을 나눈 비동기 파이프라인</text>
  <line x1="380" y1="361" x2="380" y2="376" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar1)"/>
  <rect x="40" y="380" width="680" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="60" y="405" font-size="13" font-weight="700" fill="#2c3e50">vdev (가상 장치) · vdev_mirror.c · vdev_raidz.c</text>
  <text x="60" y="426" font-size="11" fill="#666">이 vdev의 이 오프셋에 I/O를 날려라: 미러와 RAIDZ 논리, 실제 디스크 I/O</text>
  <text x="380" y="466" text-anchor="middle" font-size="10.5" fill="#8b949e">ARC(통합 캐시)와 ZIL(쓰기 로그)은 층이 아니라 옆에 붙는 횡단 서비스입니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - 다섯 층의 질문. ZPL "어디에 써라" → DMU "더티로 만들어라" → SPA "자리를 내라" → ZIO "변환해 발급해라" → vdev "I/O를 날려라"</figcaption>
</figure>

각 층의 역할을 소스 위치와 함께 짚습니다.

- **ZPL (ZFS POSIX Layer):** 진입점 `zfs_write()`(zfs_vnops.c:615)가 rangelock(파일 구간 단위 잠금), 쿼터 체크, 블록 크기 결정을 맡습니다.
- **DMU (Data Management Unit):** 파일을 객체(object), 즉 블록 트리로 추상화하고 트랜잭션(txg)으로 CoW를 보장합니다.
- **SPA (Storage Pool Allocator):** 풀 관리, 공간 할당, 스냅샷과 클론 메타, scrub이 여기 삽니다.
- **ZIO:** 압축, 체크섬, 암호화 변환을 통과시키는 비동기 파이프라인입니다.
- **vdev (가상 장치):** 미러와 RAIDZ 논리를 담고 리프에서 실제 디스크 I/O를 발급합니다.

운영 체감 포인트 하나. ZPL 위의 Linux VFS에서 ZFS는 page cache를 쓰지 않고 자체 캐시인 ARC로 직접 처리합니다. 그래서 `free` 출력에서 ARC가 메모리를 잡아먹는 것처럼 보이는 일이 벌어집니다.

## 온디스크 체인: uberblock에서 데이터 블록까지

ZFS 디스크의 모든 것은 **"블록 포인터(blkptr)로 연결된 CoW 트리"** 한 문장으로 요약됩니다. 부팅이든 읽기든 결국 이 체인을 타고 내려갑니다. 시작점은 1편에서 바이트 단위로 봤던 라벨 속 uberblock 슬롯 링입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 578" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="ZFS 온디스크 체인 도식: uberblock의 ub_rootbp가 MOS(objset 0)을 가리키고, MOS의 DSL 디렉터리가 데이터셋 objset을 가리키며, objset의 os_meta_dnode가 dnode를 가리키고, dnode의 dn_blkptr이 blkptr과 간접 블록을 거쳐 L0 데이터 블록에 닿는다. 각 화살표의 실체는 128바이트 blkptr이고, uberblock 슬롯 교체가 곧 커밋이다.">
  <defs>
    <marker id="zs2-ar2" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="22" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">온디스크 체인: uberblock에서 데이터 블록까지</text>
  <rect x="40" y="40" width="520" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="58" y="65" font-size="12.5" font-weight="700" fill="#92400e">uberblock (약 1KB 고정 슬롯, 라벨 안 순환 기록)</text>
  <text x="58" y="86" font-size="10.5" fill="#666">ub_rootbp + ub_txg. 체크섬 유효 슬롯 중 txg 최대가 현재 풀 상태</text>
  <line x1="300" y1="106" x2="300" y2="124" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar2)"/>
  <text x="316" y="120" font-size="10" fill="#8b949e">ub_rootbp</text>
  <rect x="40" y="129" width="520" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="58" y="154" font-size="12.5" font-weight="700" fill="#2c3e50">MOS (Meta Object Set, objset 0)</text>
  <text x="58" y="175" font-size="10.5" fill="#666">풀의 모든 메타데이터가 사는 곳. DSL 디렉터리가 각 데이터셋 objset을 등록</text>
  <line x1="300" y1="195" x2="300" y2="213" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar2)"/>
  <text x="316" y="209" font-size="10" fill="#8b949e">DSL 디렉터리</text>
  <rect x="40" y="218" width="520" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="58" y="243" font-size="12.5" font-weight="700" fill="#2c3e50">데이터셋 objset (파일시스템 · zvol)</text>
  <text x="58" y="264" font-size="10.5" fill="#666">os_meta_dnode가 object 번호를 dnode로 연결. ZIL 헤더와 쿼터 dnode도 안에</text>
  <line x1="300" y1="284" x2="300" y2="302" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar2)"/>
  <text x="316" y="298" font-size="10" fill="#8b949e">os_meta_dnode</text>
  <rect x="40" y="307" width="520" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="58" y="332" font-size="12.5" font-weight="700" fill="#2c3e50">dnode (파일 하나 = dnode 하나)</text>
  <text x="58" y="353" font-size="10.5" fill="#666">dn_blkptr[3]과 레벨·블록 크기 관리. 파일 크기는 SA bonus 버퍼에</text>
  <line x1="300" y1="373" x2="300" y2="391" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar2)"/>
  <text x="316" y="387" font-size="10" fill="#8b949e">dn_blkptr[]</text>
  <rect x="40" y="396" width="520" height="65" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="58" y="421" font-size="12.5" font-weight="700" fill="#2c3e50">blkptr (128바이트)</text>
  <text x="58" y="442" font-size="10.5" fill="#666">DVA 3개 + 256비트 체크섬 + birth txg + fill. 모든 화살표의 실체</text>
  <line x1="300" y1="462" x2="300" y2="480" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs2-ar2)"/>
  <text x="316" y="476" font-size="10" fill="#8b949e">DVA(vdev + 오프셋)</text>
  <rect x="40" y="485" width="520" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="58" y="510" font-size="12.5" font-weight="700" fill="#16a34a">데이터 블록 (L0, recordsize 기본 128KB)</text>
  <text x="58" y="531" font-size="10.5" fill="#666">수정은 항상 새 자리에 기록(CoW). 이전 블록은 다음 txg에서 회수 대상</text>
  <text x="380" y="566" text-anchor="middle" font-size="10.5" fill="#8b949e">모든 화살표의 실체가 blkptr이고, uberblock 슬롯 교체가 곧 커밋입니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - 여섯 고리의 체인. 모든 화살표의 실체가 128바이트 blkptr이고, 노란 uberblock 슬롯 교체가 곧 커밋</figcaption>
</figure>

### 커밋은 uberblock 교체 한 번이다

uberblock이 ZFS의 유일한 커밋 포인트입니다. 쓰기 전부가 디스크에 반영됐어도 uberblock이 갱신되지 않으면 그 txg는 존재하지 않았던 것이 됩니다. 반대로 uberblock이 먼저 갱신되면 안 되므로 싱크 순서는 항상 **데이터 → 메타데이터 → uberblock** 순서입니다.

왜 유일하게 제자리 덮어쓰기일까요? 모든 블록을 불변으로 만들면 "루트를 가리키는 포인터"도 불변 블록이어야 하고, 그러면 그 포인터를 가리키는 포인터가 또 필요합니다. 무한 회귀를 끊으려면 최상위 포인터 한 곳만 제자리 갱신을 허용하고, 대신 여러 슬롯에 순환 기록하며 안전장치를 겹칩니다. git이 불변 객체 위에서 브랜치 포인터만 옮기는 것과 같은 발상입니다.

### 정전이 나도 절반만 반영된 상태는 없다

세 가지 시나리오 어느 쪽이어도 결과는 동일합니다. 새 블록 일부만 기록된 채 정전이면 uberblock은 직전 txg를 가리키므로 **이전 세계로 부팅**합니다. uberblock 슬롯 기록 도중이면 그 슬롯만 체크섬 불일치로 폐기됩니다. 기록 직후면 새 세계가 됩니다. 저널 파일시스템처럼 리플레이하는 대신, 메타데이터에 한해 "두 세계 중 하나를 선택"합니다. 리플레이가 필요한 유일한 영역은 fsync 의미론을 담당하는 ZIL뿐입니다.

## 핵심 자료구조 4개

이 네 개가 온디스크 포맷의 90%입니다. 전부 실제 헤더에서 가져온 요약입니다.

| 구조체 | 정의 위치 | 크기 | 기억할 필드 |
|---|---|---|---|
| blkptr_t | spa.h | 128바이트 | blk_dva[3](주소 3개), blk_birth(생성 txg), blk_cksum(256비트), blk_fill(하위 블록 수) |
| dnode_phys_t | dnode.h | 512바이트~16KB | dn_nlevels(트리 깊이), dn_nblkptr(인라인 bp, 기본 3), dn_datablkszsec(= recordsize), dn_maxblkid(EOF 판정) |
| objset_phys_t | dmu.h | 블록 1개 | os_meta_dnode(object 찾기의 루트), os_zil_header(ZIL도 objset 안에), userused dnode(쿼터 집계) |
| uberblock | uberblock_impl.h | 약 1KB 슬롯 | ub_rootbp(MOS 루트), ub_txg(커밋 번호), ub_mmp_*(이중 마운트 방지), ub_zec(끝 체크섬) |

주목할 디테일이 둘 있습니다. 첫째, DVA 하나는 16바이트에 "어떤 vdev의 어느 오프셋에 몇 바이트(asize)로 할당됐는가"를 비트패킹합니다. DVA가 3개인 이유는 미러와 copies=N 조합입니다. 둘째, 파일 크기는 dnode에 없습니다. 크기와 UID, mtime 같은 inode 속성은 bonus 버퍼의 SA(System Attribute)에 있고, dnode는 블록 트리의 뼈대만 담습니다.

<details>
<summary>📖 블록 트리 사다리와 용량 산수 보기</summary>

**3단계 사다리.** 파일 크기에 따라 트리는 세 단계로 자랍니다. 약 112바이트까지(압축 후)는 데이터가 blkptr 안에 통째로 들어가는 embedded bp라 메타 블록이 0개입니다. 직접 블록만 쓰는 단계(최대 3블록, recordsize 128KB 기준 384KB)도 간접 블록이 없습니다. 그 이상부터 "blkptr 배열만 담은 블록"인 간접 블록이 L1, L2 식으로 자랍니다. ext2의 direct/indirect pointer와 같은 발상이고, 차이는 blkptr이 주소가 아니라 체크섬과 birth txg까지 담는 128바이트라는 점과 깊이가 고정이 아니라 계속 자란다는 점뿐입니다.

**용량 산수.** 간접 블록 하나가 담는 포인터 수는 2^(간접블록크기로그 - 7)로, 16KB면 128개, 128KB면 1024개입니다. recordsize 128KB와 간접 블록 16KB 기준으로 nlevels 2는 약 48MB까지, 3은 약 6GB까지, 4에서 5로 100TB급까지 담습니다. 이 master부터 신규 오브젝트의 간접 블록 기본값이 128KB로 커졌습니다(dnode.c:83, DN_MAX_INDBLKSHIFT). 같은 레벨에서 8배 큰 파일을 담을 수 있게 된 셈입니다.

</details>

## 3대 추상화: ARC, dbuf, zio

- **ARC: 캐시가 아니라 메모리 저장소.** 읽기 캐시와 "아직 디스크에 안 쓴 더티 데이터의 보관소"를 겸합니다. 쓰기에서는 `dbuf_dirty()`가 ARC 버퍼에 데이터를 쓰고 dirty로 마킹만 합니다. write(2)가 반환된 시점에는 디스크가 아니라 ARC가 사실상의 저장소입니다.
- **dbuf: ARC 앞단의 인덱스.** (objset, object, level, blkid) 네 키로 관리되는 블록 버퍼입니다. 데이터 자체는 없고 "이 블록의 논리적 상태 + ARC 버퍼 포인터"만 담습니다. 상태는 UNCACHED → READ → CACHED로 흐르고 쓰기 중에는 FILL을 지나갑니다.
- **zio: 변환과 발급을 나눈 파이프라인.** 부모-자식 트리를 이루고 압축, 체크섬, 암호화 변환을 통과한 뒤 ready 게이트를 지나 DVA 할당과 vdev 분해가 이뤄집니다. 핵심은 "무엇을 쓸지(변환)"와 "어디에 쓸지(할당)"의 분리입니다. 미러와 RAIDZ도 zio 입장에선 자식 zio를 만드는 것뿐입니다.

## Write와 Read, 한눈에

쓰기는 여덟 단계로 요약됩니다. `zfs_write()`가 rangelock을 잡고(1), dmu_tx가 txg를 배정하며(2), `dbuf_dirty()`가 ARC에 더티 버퍼를 만드는 곳까지가 사용자에게 보이는 반환입니다(3). 이후는 배경입니다. txg가 마감되면(기본 5초 또는 dirty 한도) `dsl_pool_sync()`가 CoW 연쇄를 일으켜(4-5) `arc_write()`에서 zio 파이프라인으로 압축과 체크섬을 거쳐 새 자리에 기록하고(6-7), uberblock 슬롯이 교체되는 순간 커밋됩니다(8).

읽기는 더 짧습니다. `zfs_read()`에서 `dbuf_read()` 상태머신까지 내려가 ARC에 있으면 즉시 반환하고(I/O 0회), 미스면 zio read로 디스크에서 가져와 체크섬을 검증하고 압축을 푼 뒤 ARC에 적재합니다. 미스였다면 다음 블록을 예측하는 프리페치(dmu_zfetch)도 함께 발동합니다.

소스를 읽기 전에는 "커밋은 데이터를 디스크에 쓰는 행위"라고 알고 있었습니다. 읽고 나니 "커밋은 포인터를 옮기는 행위"가 되었습니다. 이 관점 전환 하나로 스냅샷, scrub, send/recv가 전부 "트리를 공유하거나 순회하는 방식"으로 재해석됩니다. 반환(3)과 커밋(8) 사이의 간극이 다음 편의 주제입니다.

<details>
<summary>📖 시리즈 용어 사전 (12단어)</summary>

| 용어 | 뜻 |
|---|---|
| txg | transaction group. 쓰기를 모아 커밋하는 단위. 기본 5초 또는 용량 압박으로 닫히고 open, quiescing, syncing 3상태가 항상 공존 |
| blkid | 파일(객체) 내 블록 번호. 오프셋 나누기 블록 크기. L0은 데이터, L1 이상은 간접 |
| bp / DVA | blkptr은 어디에, 어떤 체크섬으로, 어느 txg에 태어났는지. DVA는 그 안의 개별 주소(vdev + 오프셋 + asize) |
| MOS | Meta Object Set. 풀 메타데이터의 루트. objset 0 |
| objset | 데이터셋 하나. 메타 dnode와 ZIL 헤더, 쿼터 dnode 포함 |
| dbuf | DMU 블록 버퍼. (objset, object, level, blkid) 키. 데이터는 ARC에 있고 dbuf는 상태와 포인터만 |
| ZIL | intent log. fsync 의미론을 위해 txg 커밋 전에 먼저 기록하는 쓰기 로그 |
| SA | System Attributes. inode 속성을 bonus 버퍼에 담는 가변 포맷 |
| ZAP | 디렉터리 엔트리용 해시 테이블 |
| gang block | 연속 공간 확보 실패 시 조립식으로 묶는 블록. 단편화 경고 신호 |
| fill | blkptr의 하위 트리 블록 수. destroy 시 회수량 계산에 사용 |
| BP_IS_HOLE | bp가 비어 있다는 뜻. sparse 영역이며 읽으면 0으로 채움 |

</details>

다음 편 (3/5) Write & Read Path, 쓰기의 두 막과 읽기의 두 갈래: [ZFS-Study-03-Write-Read-Path](/2026/08/29/ZFS-Study-03-Write-Read-Path/)
