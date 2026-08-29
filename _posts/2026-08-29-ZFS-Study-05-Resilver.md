---
layout: post
title: "ZFS 소스 학습 (5/8): Resilver - DTL 장부와 자가복구"
categories: [Storage, Filesystem, OpenZFS]
description: 미러 디스크를 교체하면 ZFS는 어디부터 다시 채울까? DTL 장부와 healing·sequential 두 복구 경로를 소스로 추적했습니다.
keywords: [ZFS, OpenZFS, Resilver, DTL, vdev_rebuild, dsl_scan, mirror]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (5/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

인용은 OpenZFS master 직독 파일:라인입니다(vdev.h:44, dsl_scan.c:255, vdev_rebuild.c:1028)이고 관찰 근거는 ZFS 풀 상태 45케이스 실측(zresmon)입니다. 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (4/8) Read Path, 캐시 3계층: [ZFS-Study-04-Read-Path](/2026/08/29/ZFS-Study-04-Read-Path/)

이전 편 (1/8) 바이트 지도: [ZFS-Study-01-Byte-Map](/2026/08/29/ZFS-Study-01-Byte-Map/). 1편의 바이트 지도를 봤다면 resilver가 어디를 고치는지 바로 보입니다. 복사는 원래 DVA 오프셋 그대로 돌아가니까요.

## Hook: 디스크 교체는 사고가 아니라 절차다

미러나 raidz에서 디스크 한 장이 죽는 일은 예정된 이벤트입니다. 교체 디스크를 꽂으면 resilver가 장부를 펴고 그 만큼만 다시 씁니다. 질문은 무엇을, 얼마나, 어디부터 다시 쓰는가이고 답은 DTL 장부와 두 경로에 있습니다.

## TL;DR

- resilver와 scrub은 **같은 스캔 기계**입니다. 콜백까지 동일하고(dsl_scan.c:255) 차이는 질문, 즉 "모든 복제본이 정상인가" 대 "이 디스크의 빈 구멍을 언제 메우나"입니다.
- 장부 DTL은 블록 목록이 아니라 **txg 구간**이고 판정은 blk_birth와의 비교 한 줄로 끝납니다.
- healing은 **메타 트리를 순회**해 필요한 블록만 복사하고(raidz 포함) sequential(2.0+)은 mirror에서 **디스크를 순차 복사**해 헤드가 한 방향으로만 움직입니다.
- 완료는 장부 정리(excise)입니다. 실패 흔적이 남으면 재시작하며 진실은 %가 아니라 DTL에 있습니다.

## 같은 기계, 다른 질문: resilver 대 scrub

스캔 종류별 콜백 테이블에서 둘은 같은 함수를 가리킵니다.

```c
static scan_cb_t *scan_funcs[POOL_SCAN_FUNCS] = {
	NULL,
	dsl_scan_scrub_cb,	/* POOL_SCAN_SCRUB   */
	dsl_scan_scrub_cb,	/* POOL_SCAN_RESILVER - 같은 콜백! */
};
```

차이는 질문에 있습니다. scrub은 검증이, resilver는 복사가 본업입니다.

> **resilver는 전통 RAID의 재구성과 다릅니다.** 속해야 하는 live 블록만 찾아 복사합니다. dead 블록과 빈 공간은 건드리지 않으므로 거의 빈 16TB 풀은 실제 데이터량만큼만 복사되고, 진행률의 초반 급상승도 이 구조의 부작용입니다.

"있어야 하는데 없는 블록"을 누가 아는가. 다음 절의 장부가 답입니다.

## DTL: 어디가 비었는지의 장부

vdev마다 잃은 데이터를 range_tree로 들고 있고 운영상 의미 있는 세 종류입니다(vdev.h:44).

| 종류 | 뜻 | 운영에서의 의미 |
|---|---|---|
| DTL_MISSING | 이 구간 데이터의 복제본이 하나도 없음(0%) | 위험 상태. resilver의 1차 대상이며 zpool status의 DEGRADED 표기의 실체 |
| DTL_PARTIAL | 복제본은 있으나 일부 vdev에 없음(100% 미만) | resilver가 MISSING과 함께 메움. 상태 표시로는 잘 드러나지 않음 |
| DTL_SCRUB | scrub·resilver 중 끝내 복구 못 한 흔적 | 다음 스캔의 재시도 목록 |

네 번째 DTL_OUTAGE는 detach용 임시 장부로 평소 비어 있습니다. 핵심은 단위입니다. DTL은 "블록 12345가 없다"가 아니라 "txg 100~250에 쓴 데이터가 없다"고 적습니다. 블록 포인터가 태어난 txg(blk_birth)를 달고 있으니 birth가 구간 안인가만 보면 되고 시간 구간 하나로 수천 블록을 대신하니 장부가 작습니다.

장부는 이탈 순간부터 쌓입니다. 죽은 순간의 txg부터 DTL_MISSING에 구간이 자라고, 죽어 있던 동안의 쓰기가 없으니 돌아와도 그대로입니다. 풀이 통째로 죽어 있었다면 import 시 마지막 정상 txg부터 깔립니다. 아래 그림이 장부의 일생입니다.
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 512" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="DTL 장부의 일생을 시간순으로 보여주는 다이어그램. t0 정상 운영에서는 DTL이 비어 있고 txg 0부터 99까지 복제본이 온전하다. t1 txg 100에 미러 한쪽 디스크가 이탈하면 이탈 순간의 txg부터 DTL_MISSING 구간이 자라기 시작한다. t2 txg 250에 디스크가 복귀하면 resilver가 시작되는데 재접속이면 이탈 구간 100~250만, 새 디스크 교체면 전 구간으로 장부가 확대된다. t3 복구 진행 중에는 blk_birth가 100~250 안에 드는 live 블록만 선별해 복사하며 초록 구간이 자라고 200~250 빨간 구간이 잔여로 남는다. t4 완료하면 vdev_dtl_reassess가 구간을 excise해 장부가 비고, 오류 흔적이 남으면 scn_errors 0 초과 조건으로 재시작한다.">
  <defs>
    <marker id="zs5-ar" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">DTL 장부의 일생: 장애 순간부터 excise까지</text>

  <rect x="40" y="38" width="680" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="58" font-size="12.5" font-weight="700" fill="#2c3e50">t0 · 정상 운영 (txg ~99)</text>
  <text x="56" y="76" font-size="10.5" fill="#666">DTL 비어 있음 - 모든 쓰기가 살아 있는 멤버 전부에 동시 기록</text>
  <rect x="100" y="84" width="228" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <text x="214" y="95.5" text-anchor="middle" font-size="9.5" fill="#16a34a">복제본 온전</text>
  <line x1="328" y1="92" x2="700" y2="92" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>
  <line x1="380" y1="109" x2="380" y2="120" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ar)"/>

  <rect x="40" y="122" width="680" height="70" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="56" y="142" font-size="12.5" font-weight="700" fill="#dc2626">t1 · txg 100: 미러 한쪽 디스크 이탈</text>
  <text x="56" y="160" font-size="10.5" fill="#666">이탈 순간의 txg부터 DTL_MISSING에 구간이 자라기 시작: [txg 100 ~ 현재)</text>
  <rect x="100" y="168" width="228" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <rect x="331" y="168" width="115" height="16" fill="#fef2f2" stroke="#dc2626" stroke-width="1"/>
  <line x1="446" y1="176" x2="700" y2="176" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>
  <text x="454" y="179" font-size="9.5" fill="#8b949e">계속 자람</text>
  <line x1="380" y1="193" x2="380" y2="204" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ar)"/>

  <rect x="40" y="206" width="680" height="70" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="56" y="226" font-size="12.5" font-weight="700" fill="#92400e">t2 · txg 250: 디스크 복귀(교체·재접속), resilver 시작</text>
  <text x="56" y="244" font-size="10.5" fill="#666">재접속은 이탈 구간 [100,250)만, 새 디스크 교체는 전 구간 [0,무한)으로 장부 확대</text>
  <rect x="100" y="252" width="228" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <rect x="331" y="252" width="346" height="16" fill="#fef2f2" stroke="#dc2626" stroke-width="1"/>
  <text x="504" y="263.5" text-anchor="middle" font-size="9.5" fill="#dc2626">DTL_MISSING [txg 100 ~ 250)</text>
  <line x1="677" y1="246" x2="677" y2="274" stroke="#fbbf24" stroke-width="3"/>
  <text x="677" y="242" text-anchor="middle" font-size="9.5" fill="#92400e">복귀 시점</text>
  <line x1="380" y1="277" x2="380" y2="288" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ar)"/>

  <rect x="40" y="290" width="680" height="70" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="56" y="310" font-size="12.5" font-weight="700" fill="#16a34a">t3 · 복구 진행: 스캔이 구간을 메운다</text>
  <text x="56" y="328" font-size="10.5" fill="#666">blk_birth가 [100,250) 안에 드는 live 블록만 선별해 복사 - 나머지는 만나도 스킵</text>
  <rect x="100" y="336" width="228" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <rect x="331" y="336" width="228" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <text x="445" y="347.5" text-anchor="middle" font-size="9.5" fill="#16a34a">메워짐 (txg 100~199)</text>
  <rect x="559" y="336" width="118" height="16" fill="#fef2f2" stroke="#dc2626" stroke-width="1"/>
  <text x="618" y="347.5" text-anchor="middle" font-size="9.5" fill="#dc2626">잔여</text>
  <line x1="380" y1="361" x2="380" y2="372" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ar)"/>

  <rect x="40" y="374" width="680" height="70" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="56" y="394" font-size="12.5" font-weight="700" fill="#16a34a">t4 · 완료: vdev_dtl_reassess가 구간을 잘라낸다 (excise)</text>
  <text x="56" y="412" font-size="10.5" fill="#666">장부가 비면 끝 - 오류 흔적이 남으면 재시작 (scn_errors &gt; 0, dsl_scan.c:708)</text>
  <rect x="100" y="420" width="577" height="16" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <text x="388" y="431.5" text-anchor="middle" font-size="9.5" fill="#16a34a">DTL 비어 있음 - 복제 완전</text>

  <g font-size="10" fill="#666">
    <rect x="56" y="462" width="14" height="14" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/><text x="76" y="473">복제본 온전·복구 완료</text>
    <rect x="230" y="462" width="14" height="14" fill="#fef2f2" stroke="#dc2626" stroke-width="1"/><text x="250" y="473">DTL_MISSING(복제본 없음)</text>
    <line x1="450" y1="462" x2="450" y2="476" stroke="#fbbf24" stroke-width="3"/><text x="458" y="473">복귀 시점</text>
    <text x="560" y="473" fill="#8b949e">점선 = 아직 오지 않은 txg</text>
  </g>
  <text x="380" y="500" text-anchor="middle" font-size="10.5" fill="#8b949e">장부의 단위는 txg 구간 - 블록 하나하나가 아니라 "언제 쓴 데이터인지"만 기록합니다.</text>
</svg>

장부가 목록이 아니라 구간임이 요점입니다. 시작 판정부터 봅니다.

### 언제 시작되나: 트리거와 판정

필요 판정은 vdev_resilver_needed()가 트리를 재귀하며 내립니다(vdev.c:3796).

```c
if (vd->vdev_children == 0) {            /* 리프만 판정 */
	if (!zfs_range_tree_is_empty(vd->vdev_dtl[DTL_MISSING]) &&
	    vdev_writeable(vd)) {
		needed = B_TRUE;      /* DTL_MISSING이 비어 있지 않으면 무조건 필요 */
	}
}
```

DTL_MISSING이 하나라도 차 있고 쓸 수 있는 디스크가 있으면 무조건 필요합니다. 어떤 경로로 장부가 차느냐가 트리거의 전부입니다.

| 트리거 | 장부(DTL) 모양 | 시작 시점 |
|---|---|---|
| zpool replace로 새 디스크 교체 | 전 구간 [txg 0 ~ 무한) | replace 즉시 |
| 재부팅·재접속으로 돌아온 디스크 | 이탈했던 구간만 (예: [txg 100~250)) | import 후 유예 5 txg(zfs_import_defer_txgs) 뒤 백그라운드 |
| 일반 쓰기 중 한쪽 쓰기 실패 | 실패한 txg부터 리프에 자동 기록(vdev.c:5348) | 다음 비동기 필요 판정(spa.c:6268)에서 |

세 번째 줄이 흥미롭습니다. 한쪽 쓰기 실패는 앱에 성공으로 돌아가고 자식만 장부에 오릅니다. PARTIAL만 차 있어도 대상입니다.

판정되면 복사는 두 경로 중 하나로 들어갑니다. 전통부터.

## Healing resilver: 트리를 걷으며 블록을 고친다

"스캔 + 치유"가 전통 경로입니다. dsl_scan_vis()가 블록 트리를 순회하며 live 블록 포인터마다 콜백을 부르고 필터 통과 블록만 대상입니다. 이후는 세 단계입니다.

```c
/* 이 DVA가 이 vdev 소속이고, DTL 구간 안 txg에 태어났는가? */
if (!vdev_dtl_need_resilver(vd, dva, psize, phys_birth))
	return;                          /* 아니면 스킵 */
```

1. **읽기 + 검증**: 살아 있는 복제본에서 읽어 체크섬을 확인합니다. mirror는 반대편, raidz는 패리티 재구성입니다.
2. **재기록**: 원래 DVA 위치로 씁니다. txg를 거치지 않는 스캔 전용 쓰기인데 내용은 불변(CoW)이라 안전합니다.
3. **정렬된 발급**: I/O는 디스크별 큐(scan_io_queue)에 쌓였다가 오프셋순 재배열돼 발급됩니다. 트리 순회 순서는 디스크 순서가 아니라 정렬이 없으면 헤드가 왕복하며 우선순위는 일반 I/O보다 낮습니다.

다만 이 약점은 큐로 못 고칩니다.

> **healing의 근본 약점은 탐색 비용입니다.** 복사할 게 적어도 블록을 찾으려면 풀 전체 트리를 순회해야 하고 파일 수 조 단위 풀에서는 순회가 시간을 지배합니다. 이 비용을 없애려고 2.0에서 새 경로가 나왔습니다.

## Sequential resilver: mirror는 디스크를 순서대로 채운다

발상의 전환입니다. 블록을 트리에서 찾지 말고 디스크의 오프셋 공간을 처음부터 채우는 것입니다. vdev_rebuild()가 시작되면(vdev_rebuild.c:1028, feature device_rebuild) 재구성은 dsl_scan과 별개로 vdev 단위에서 돕니다.

세 단계입니다. 첫째, space map으로 대상 디스크의 할당 범위 지도를 만듭니다(vdev_rebuild.c:811). MOS와 트리는 전혀 순회하지 않습니다. 둘째, 범위를 덮는 합성 bp를 즉석에서 만들어(vdev_rebuild.c:585) 통째로 읽습니다. 합성 bp에는 체크섬이 없으니 검증도 생략합니다. 셋째, 정상 복제본에서 읽은 데이터를 새 디스크의 같은 오프셋에 기록합니다. 헤드가 동행하는 단방향 스윕이라 HDD에서 빠릅니다.

동시 발급 상한(min(ARC 최대의 절반 ÷ vdev 수, zfs_rebuild_vdev_limit))이 메모리를 지키고 txg별 체크포인트(vr_scan_offset)가 크래시 후 재개를 담당합니다.

오류를 대하는 태도는 정반대입니다. 읽기가 실패해도 멈추지 않고 카운터(vrp_errors)만 올리며 끝까지 밉니다. 완전 성공 시에만 DTL을 excise하고(vdev_rebuild.c:944) 검증은 완료 후 자동 scrub이 맡습니다(vdev_rebuild.c:340). 밀고 검증은 scrub에 맡기는 철학입니다. 갈림을 표로 정리합니다.

| 항목 | Healing resilver | Sequential resilver |
|---|---|---|
| 지원 구성 | 모든 vdev (raidz 포함) | top-level mirror + dRAID 스페어 |
| 탐색 방식 | 메타 트리 순회 후 DTL로 선별 | space map 범위 지도, 트리 순회 없음 |
| I/O 패턴 | 정렬 큐로 순차에 근접 | 완전 순차, 단방향 스윕 |
| 체크섬 검증 | 읽는 복제본 전부 | 복사 원본만, 검증은 완료 후 자동 scrub |
| 거대 메타 풀 | 순회 비용에 느려짐 | 영향 없음 |
| 중단·재개 | DTL이 체크포인트 | DTL + txg별 오프셋 체크포인트 |
| 약점 | 트리 순회가 병목 | 진행 중 새 attach면 처음부터 재시작 |

왼쪽은 트리를 걷는 healing, 오른쪽은 디스크를 채우는 sequential입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 590" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="재구성 두 경로의 구조 비교 다이어그램. 왼쪽 healing resilver는 MOS와 메타 트리를 순회해 live 블록 포인터를 만나면 DTL 필터로 blk_birth가 구간 안인 블록만 선별하고, 살아 있는 복제본에서 읽어 체크섬을 검증한 뒤 원래 DVA 위치로 재기록하며 scan_io_queue가 오프셋 순으로 정렬 발급한다. 장점은 raidz 포함 전 구성 지원과 읽는 복제본 전부를 대상으로 하는 체크섬 검증이고, 단점은 메타 트리 전체 순회 비용이다. 오른쪽 sequential resilver는 space map으로 할당 범위 지도를 만들고 합성 블록 포인터로 범위를 통째로 읽어 새 디스크에 오프셋 순서대로 순차 기록하며, 완료 시 DTL excise와 함께 자동 scrub을 예약한다. 장점은 완전 순차 I/O의 속도와 거대 메타 풀과 무관한 성능, 단점은 top-level mirror만 지원하고 진행 중 새 디스크 attach 시 처음부터 재시작한다는 점이다.">
  <defs>
    <marker id="zs5-ah" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="380" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">재구성의 두 경로: 트리를 걷는가, 디스크를 채우는가</text>

  <rect x="40" y="38" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="205" y="64" text-anchor="middle" font-size="12.5" font-weight="700" fill="#2c3e50">Healing resilver (전통 경로)</text>
  <text x="205" y="85" text-anchor="middle" font-size="10.5" fill="#666">모든 vdev 지원(raidz 포함) - dsl_scan이 주체</text>
  <rect x="390" y="38" width="330" height="70" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="555" y="64" text-anchor="middle" font-size="12.5" font-weight="700" fill="#92400e">Sequential resilver (2.0+, device_rebuild)</text>
  <text x="555" y="85" text-anchor="middle" font-size="10.5" fill="#666">top-level mirror(+dRAID 스페어) 전용 - vdev_rebuild가 주체</text>

  <line x1="205" y1="109" x2="205" y2="119" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>
  <line x1="555" y1="109" x2="555" y2="119" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>

  <rect x="40" y="120" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="144" font-size="12" font-weight="700" fill="#2c3e50">1. MOS·메타 트리 순회 (dsl_scan_vis)</text>
  <text x="56" y="162" font-size="10" fill="#666">uberblock, objset, L2·L1·L0 순으로 live bp만 방문</text>
  <rect x="390" y="120" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="406" y="144" font-size="12" font-weight="700" fill="#2c3e50">1. space map(metaslab)으로 범위 지도 작성</text>
  <text x="406" y="162" font-size="10" fill="#666">할당된 범위만 - MOS·블록 트리는 전혀 순회 안 함</text>

  <line x1="205" y1="191" x2="205" y2="201" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>
  <line x1="555" y1="191" x2="555" y2="201" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>

  <rect x="40" y="202" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="226" font-size="12" font-weight="700" fill="#2c3e50">2. DTL 필터로 복사 대상 선별</text>
  <text x="56" y="244" font-size="10" fill="#666">vdev_dtl_need_resilver(): blk_birth가</text>
  <text x="56" y="260" font-size="10" fill="#666">DTL 구간 안인 블록만, 나머지는 스킵</text>
  <rect x="390" y="202" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="406" y="226" font-size="12" font-weight="700" fill="#2c3e50">2. 합성 bp로 범위를 통째로 읽기</text>
  <text x="406" y="244" font-size="10" fill="#666">블록이 몇 개인지 몰라도 오프셋 범위면 충분</text>
  <text x="406" y="260" font-size="10" fill="#666">(vdev_rebuild_blkptr_init)</text>

  <line x1="205" y1="273" x2="205" y2="283" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>
  <line x1="555" y1="273" x2="555" y2="283" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>

  <rect x="40" y="284" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="308" font-size="12" font-weight="700" fill="#2c3e50">3. 살아 있는 복제본에서 읽어 체크섬 검증</text>
  <text x="56" y="326" font-size="10" fill="#666">mirror는 반대편, raidz는 패리티로 재구성해 읽음</text>
  <rect x="390" y="284" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="406" y="308" font-size="12" font-weight="700" fill="#2c3e50">3. 새 디스크에 오프셋 순서대로 순차 기록</text>
  <text x="406" y="326" font-size="10" fill="#666">읽기·쓰기 헤드가 같은 오프셋 동행, 빈 구간은 점프</text>

  <line x1="205" y1="355" x2="205" y2="365" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>
  <line x1="555" y1="355" x2="555" y2="365" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs5-ah)"/>

  <rect x="40" y="366" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="390" font-size="12" font-weight="700" fill="#2c3e50">4. 원래 DVA 위치로 재기록, 정렬 큐로 발급</text>
  <text x="56" y="408" font-size="10" fill="#666">scan_io_queue가 오프셋순 재배열 - 논리 순서를</text>
  <text x="56" y="424" font-size="10" fill="#666">순차 I/O로, 우선순위는 일반 I/O보다 낮음</text>
  <rect x="390" y="366" width="330" height="70" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="406" y="390" font-size="12" font-weight="700" fill="#2c3e50">4. 완료 시 DTL excise + 자동 scrub 예약</text>
  <text x="406" y="408" font-size="10" fill="#666">체크섬 없이 복사한 만큼 검증은 후속 scrub이 담당</text>

  <rect x="40" y="448" width="330" height="88" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="56" y="470" font-size="10.5" font-weight="600" fill="#16a34a">장점: raidz 포함 모든 구성 + 읽는 복제본 전부를</text>
  <text x="56" y="486" font-size="10.5" fill="#16a34a">체크섬 검증(healing은 scrub 로직을 공유)</text>
  <text x="56" y="508" font-size="10.5" font-weight="600" fill="#dc2626">단점: 메타 트리 전체 순회 - 파일 수 조 단위 풀에서는</text>
  <text x="56" y="524" font-size="10.5" fill="#dc2626">순회 자체가 병목(sequential의 개발 동기)</text>
  <rect x="390" y="448" width="330" height="88" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="406" y="470" font-size="10.5" font-weight="600" fill="#16a34a">장점: 완전 순차 I/O의 속도 + 거대 메타 풀과 무관,</text>
  <text x="406" y="486" font-size="10.5" fill="#16a34a">txg별 체크포인트로 중단 후 재개도 안전</text>
  <text x="406" y="508" font-size="10.5" font-weight="600" fill="#dc2626">단점: top-level mirror만 가능 + 진행 중 새 디스크</text>
  <text x="406" y="524" font-size="10.5" fill="#dc2626">attach 시 처음부터 재시작(deferred 불가)</text>

  <text x="380" y="572" text-anchor="middle" font-size="10.5" fill="#8b949e">sequential이 실패·중단되면 DTL 잔존분은 healing이 이어받습니다 - 폴백은 호출이 아니라 장부 잔존의 결과(spa.c:6268)</text>
</svg>

실패와 전환도 장부가 결정합니다. COMPLETE 외의 종료는 DTL을 지우지 않으므로 장부가 남으면 필요 판정(spa.c:6268)이 healing을 이어서 일으킵니다. 새 디스크 attach 시 처음부터 재시작하는 것도 동시 교체 시 비용이고, DDT 풀의 재구성은 이 시리즈 범위 밖입니다.

## 완료와 DTL excise: 수렴의 조건

스캔이 끝나면 sync 시점에 vdev_dtl_reassess()가 구간을 잘라냅니다(excise). 직관과 다른 규칙을 짚습니다.

> **스캔 중 새 쓰기는 DTL을 늘리지 않습니다.** 새 디스크는 이미 정식 mirror 멤버라 이후의 쓰기는 일반 경로로 멤버 전부에 기록됩니다. 재시작의 실제 조건은 복구 실패입니다. healing은 오류가 남아 끝나면 DTL을 못 잘라내고 스스로 재시작하며(scn_errors &gt; 0, dsl_scan.c:708) 대상이 정상인 한 "resilvered 0 errors"로 수렴합니다.

흔적은 두 갈래입니다. 못 읽은 구간은 DTL_SCRUB에 남아 재시도 목록이 되고 파일 단위는 영구 에러 로그로 zpool status -v에 나옵니다. 의외로 일반 읽기 중의 자발적 self-healing 쓰기 실패만은 transactional context가 없어 DTL에 못 남깁니다(vdev.c:5315).

운영 장치도 둘입니다. 교체 직후 또 디스크가 죽으면 zfs_resilver_defer_percent(기본 10%) 기준으로 새 resilver를 지연시키고 기존 것을 마저 돌리며, 여러 vdev의 DTL은 하나의 스캔이 통합 처리합니다.

장부가 곧 체크포인트입니다. 관찰 방법으로 마무리합니다.

## 운영에서 무엇을 보아야 하나

| 보고 싶은 것 | 방법 | 해석 |
|---|---|---|
| 진행률과 ETA | zpool status | 퍼센트는 live 데이터량 기준 추정. 초반 급상승 후 느려지는 게 정상 |
| 장부의 진실 | zdb -ddd 풀이름, "Dirty time logs" 섹션 | vdev별 missing·partial·scrub 구간이 txg 범위로 출력됨. 퍼센트가 정체돼 보여도 구간이 줄고 있으면 진행 중 |
| 어느 경로인지 | zpool status 문구 | "resilvered"는 healing, "rebuilt"는 sequential. mirror는 보통 sequential, raidz는 항상 healing |
| 속도 조절 | zfs_resilver_min_time_ms (기본 3000) | txg당 스캔에 할당하는 최소 시간. 크면 재구성은 빨라지고 전경 I/O 영향은 커짐 |
| 오류 목록 | zpool status -v | 영구 에러 로그. 재검사는 zpool scrub -e(error scrub)로 오류 블록만 골라 |

> **운영 요령 세 가지.** 교체는 반드시 zpool replace로 합니다. dd 직접 복사는 vdev GUID까지 복제해 import가 거부됩니다. 여러 장은 통합 스캔을 위해 동시에 교체합니다. resilver 중단도 안전합니다. DTL이 체크포인트라 메운 구간은 다시 하지 않습니다.

"resilver가 느리다"는 불만의 상당수는 진행률 추정 착시입니다. 저도 %가 멈춘 듯 보일 때 zdb의 Dirty time logs에서 장부가 줄고 있음을 보고 안심했습니다. 교체를 절차로 만든 비결은 결국 이 장부입니다. 실패는 장부에 남고, 남아 있으면 다시 시도한다. 이 원칙이 자가복구의 전부입니다.

다음 편 (6/8) ZIL, fsync가 크래시에 살아남는 법과 intent log의 생애주기: [ZFS-Study-06-ZIL](/2026/08/29/ZFS-Study-06-ZIL/)
