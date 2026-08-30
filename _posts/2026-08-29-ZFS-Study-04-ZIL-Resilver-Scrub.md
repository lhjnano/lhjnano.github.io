---
layout: post
title: "ZFS 소스 학습 (4/5): ZIL·Resilver·Scrub - 약속 장부와 자가복구"
categories: [Storage, Filesystem, OpenZFS]
description: "fsync는 어떻게 크래시에 살아남고 디스크 교체는 무엇을 다시 쓸까요? ZIL의 약속 장부와 자가복구의 두 스캔을 정리했습니다."
keywords: [ZFS, OpenZFS, ZIL, fsync, Resilver, DTL, scrub, self-healing, dsl_scan]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (4/5). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

인용은 OpenZFS master 직독 파일:라인입니다(zil.c:2213, zil.c:3967, vdev.h:44, dsl_scan.c:255, vdev_rebuild.c:1028)이고 관찰 근거는 ZFS 풀 상태 45케이스 실측입니다. 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (3/5) Write & Read Path, 쓰기의 두 막과 읽기의 두 갈래: [ZFS-Study-03-Write-Read-Path](/2026/08/29/ZFS-Study-03-Write-Read-Path/)

이전 편 (1/5) 바이트 지도, 디스크의 밑바닥: [ZFS-Study-01-Byte-Map](/2026/08/29/ZFS-Study-01-Byte-Map/)

이 글은 세 개의 이야기를 담습니다. 쓰기가 ARC까지만 가고 반환된다면 fsync의 약속은 무엇이 지키는가(ZIL), 디스크가 죽으면 무엇을 어디부터 다시 쓰는가(Resilver), 그리고 채워진 데이터가 온전한지 누가 검증하는가(Scrub). 세 이야기의 열쇠는 전부 "장부"입니다. ZIL은 약속의 장부, DTL은 결손의 장부, errlog는 실패의 장부입니다.

## TL;DR

- ZIL = 동기 쓰기만의 약속 장부. fsync는 lwb flush로 판정
- 기록 3방식: COPIED / NEED_COPY / INDIRECT(slog 시 금지)
- resilver와 scrub은 같은 콜백 공유(dsl_scan.c:255)
- DTL은 txg 구간 장부. healing 순회 vs sequential 순차
- scrub 오류: self-healing → errlog → error scrub 순환

## ZIL: 크래시까지 유효한 약속 장부

앞 편(3/5)에서 write(2)의 반환은 ARC까지만 가고 디스크 반영은 txg 싱크(기본 최대 5초)의 몫이라고 했습니다. 그런데 POSIX fsync는 반환 후 크래시가 나도 이 데이터는 살아 있어야 한다고 요구합니다.

fsync를 txg 완료로 구현하면 건당 수 초의 지연이고, 데이터베이스 WAL이나 메일큐 같은 동기 워크로드는 못 견딥니다. txg는 효율을 위한 묶음이고 POSIX는 개별 보장입니다.

이 간극이 ZIL(ZFS Intent Log)을 낳았습니다. 무엇을 썼는지만 적는 작은 저널로, txg 커밋을 기다리지 않고 크래시 내구성을 보장합니다.

주의할 점 하나를 먼저 박아둡니다. ZIL에는 동기 의미론이 필요한 쓰기만 기록됩니다. 비동기 쓰기는 ZIL을 전혀 거치지 않고 ARC 더티에서 txg로 직행합니다. 그래서 "ZIL이 느리다"는 말은 항상 "동기 쓰기 워크로드가 느리다"는 뜻이고 async 쓰기 성능과는 무관합니다.

### 구조: zilog, itx, lwb, zil_header

네 객체가 메모리와 디스크에 반반씩 삽니다. 각 정체와 사는 곳부터가 구조의 전부입니다.

| 객체 | 사는 곳 | 정체 |
|---|---|---|
| `zilog_t` | 메모리 | objset(데이터셋)당 하나의 로그 상태머신. itx 대기열, lwb 리스트, 통계 보유 |
| itx (intent tx) | 메모리 | "이 파일의 이 오프셋에 이 데이터를 썼다"는 연산 레코드. zfs_log_write()가 쓰기마다 생성 |
| lwb (log write block) | 메모리 버퍼 + 디스크 블록 | itx를 직렬화해 담아 디스크로 나르는 로그 체인 블록. 다음 블록 주소를 기억하며 체인으로 연결 |
| `zil_header_t` | objset_phys 안 | 체인 머리(zh_log blkptr)와 클레임/리플레이 상태. CoW 대상이라 objset과 함께 갱신 |

lwb는 단순 버퍼가 아니라 상태머신입니다. 할당, 기입, 발급, 플러시를 순회하며(zil_impl.h의 lwb_state) 담은 itx 중 최고 txg를 lwb_max_txg로 기억합니다. 디스크에서 lwb 블록들은 blkptr으로 연결된 체인이고 그 머리가 zil_header의 zh_log입니다.

zil_header가 objset_phys 안에 산다는 점이 눈여겨볼 곳입니다. ZIL 상태 자체가 CoW 트리의 일부라는 뜻입니다. 그래서 txg 싱크마다 zil_sync()가 커밋 확정분을 잘라내고, 크래시가 나지 않는 한 로그는 계속 짧게 유지됩니다. 로그가 길게 쌓이는 순간은 크래시 직후뿐입니다.

| zil_header 필드 | 역할 | 언제 바뀌나 |
|---|---|---|
| zh_log | lwb 체인 머리 blkptr | lwb 발급 시 갱신, 정상 커밋 시 zil_sync()가 체인 절단 |
| zh_claim_txg | 클레임(소유 확정)한 txg. 0보다 크면 리플레이 필요 표식 | import 시 zil_claim()이 설정 |
| zh_replay_seq | 이미 재생한 최종 레코드 번호(lrc_seq) | replay 진행 중 갱신 |
| zh_claim_blk / zh_claim_lr_seq | 블록/레코드 단위 클레임 진행 지점 | zil_claim() 순회 중 |
| zh_flags | ZIL_REPLAY_NEEDED 등 상태 비트 | 크래시 후 설정, replay 완료 후 해제 |

구조를 알았으니 다음 질문으로 넘어갑니다. 실제 쓰기는 어떤 형태로 로그에 들어갈까요.

### 세 가지 기록 방식: 복사할까, 가리킬까

모든 동기 쓰기가 데이터를 로그에 복사하는 것은 아닙니다. 쓰기마다 `zil_write_state()`(zil.c:2213)가 복사할지, 가리키기만 할지 정합니다.

분기는 짧습니다. logbias=throughput이거나 O_DIRECT면 논쟁 없이 WR_INDIRECT입니다. 크기가 zfs_immediate_write_sz(기본 32K) 이상이거나 commit 대상이 아니면 INDIRECT 후보입니다.

나머지는 commit 여부로 갈라져 WR_COPIED(fsync 대기 중) 또는 WR_NEED_COPY(나중에 묶음)가 됩니다.

여기에 역설이 하나 있습니다. **slog가 있으면 spa_has_slogs()가 indirect를 무조건 꺼버립니다.** slog는 작은 복사형 쓰기의 지연을 줄이는 전용 공간이므로, slog를 다느냐 마느냐가 기록 방식 자체를 바꿉니다. "전용 로그 디바이스가 있으면 큰 쓰기도 로그로 옮겨가겠거니"라는 직감과 반대 방향입니다. special vdev는 zil_special_is_slog(기본 1) 설정에 따라 slog처럼 취급할지 결정합니다.

강등 규칙도 하나 있습니다. WR_COPIED로 골라졌어도 레코드가 한 로그 블록에 통째로 안 들어가면(zil_maxcopied 기본 7680바이트 초과, zfs_log.c:647) WR_NEED_COPY로 강등됩니다. 복사 도중 dmu_read가 실패해도 같은 길을 갑니다.

| 구분 | WR_COPIED | WR_NEED_COPY | WR_INDIRECT |
|---|---|---|---|
| 언제 선택되나 | commit(fsync 대기)이고 데이터가 한 로그 블록에 들어갈 때(7680바이트 이하) | commit 예정이 없거나 한 블록을 넘어 분할이 필요할 때 | 32K 이상이고 블록 절반 이상 또는 비커밋. logbias=throughput과 O_DIRECT는 무조건 |
| lwb에 기록되는 것 | lr_write 레코드 안에 **데이터 사본** | 데이터를 **여러 lwb에 나눈** 연속 레코드 | **blkptr만**(lr_blkptr). 데이터는 dmu_sync() 경로로 이미 기록 중 |
| 크래시 복구 | 로그에 내장된 데이터를 읽어 원 오프셋에 재기록 | 체인을 순서대로 이어 붙인 뒤 재기록 | claim이 blkptr 생존 검증 후 bp에서 읽어 반영 |
| slog가 있는 풀에서 | slog 블록에 배치 | slog 블록에 배치 | 선택 자체가 금지 |

방식이 정해지면 남은 것은 fsync의 실제 흐름입니다. 다음 그림 하나가 ZIL 전체 동작의 지도입니다.

### fsync 한 번의 관찰 프레임

앱의 write(2)는 ZPL의 zfs_log_write()를 거쳐 itx가 되어 큐에 쌓입니다. 이어 fsync(2)가 오면 zil_commit()(zil.c:3967)이 commit itx를 넣고, zil_process_commit_list(zil.c:3146)가 itx를 lwb로 직렬화하며 waiter를 등록합니다.

lwb는 zio로 디스크에 쓰인 뒤 flush(FUA/barrier)를 치르고, flush까지 포함된 완료 ack가 오면 waiter가 깨어나(zcw_done) fsync가 반환됩니다. 크래시 내구성의 판정 기준은 lwb 블록이 디스크에 flush됐는가 하나입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1070 650" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="fsync 시퀀스 다이어그램. 앱, ZPL, ZIL, 디스크 네 액터의 라이프라인이 있다. 앱이 write를 호출하면 ZPL의 zfs_log_write가 쓰기를 itx로 만들며 기록 방식을 판정한다. 앱이 fsync를 호출하면 ZPL은 zil_commit으로 commit itx를 ZIL에 넘기고, ZIL은 zil_process_commit_list로 itx를 lwb 블록에 직렬화해 waiter를 등록한 뒤 디스크에 lwb를 기록하고 flush한다. 디스크에서 flush를 포함한 완료 ack가 돌아오면 대기하던 waiter가 깨어나 앱의 fsync가 반환된다. WR_INDIRECT면 lwb에는 blkptr만 기록되고 데이터는 같은 txg의 dmu_sync 결과물이 담당하며 fsync 대기는 lwb flush 완료로 풀린다.">
  <defs>
    <marker id="zs6-fgray" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
    <marker id="zs6-fgreen" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#16a34a"/></marker>
    <marker id="zs6-famber" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#fbbf24"/></marker>
  </defs>
  <text x="535" y="22" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">fsync 한 번의 여정: write(2)에서 lwb flush까지</text>
  <rect x="50" y="36" width="160" height="65" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="130" y="62" text-anchor="middle" font-size="12.5" font-weight="700" fill="#666">앱</text>
  <text x="130" y="80" text-anchor="middle" font-size="10" fill="#666">write(2) · fsync(2)</text>
  <rect x="320" y="36" width="160" height="65" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="400" y="62" text-anchor="middle" font-size="12.5" font-weight="700" fill="#666">ZPL</text>
  <text x="400" y="80" text-anchor="middle" font-size="10" fill="#666">zfs_write · zfs_log_write</text>
  <rect x="590" y="36" width="160" height="65" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="670" y="62" text-anchor="middle" font-size="12.5" font-weight="700" fill="#92400e">ZIL</text>
  <text x="670" y="80" text-anchor="middle" font-size="10" fill="#92400e">zilog · itx · lwb</text>
  <rect x="860" y="36" width="160" height="65" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="940" y="62" text-anchor="middle" font-size="12.5" font-weight="700" fill="#16a34a">디스크</text>
  <text x="940" y="80" text-anchor="middle" font-size="10" fill="#16a34a">slog 또는 풀 안</text>
  <line x1="130" y1="101" x2="130" y2="555" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="400" y1="101" x2="400" y2="555" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="670" y1="101" x2="670" y2="555" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="940" y1="101" x2="940" y2="555" stroke="#ddd" stroke-dasharray="4,4"/>
  <circle cx="130" cy="145" r="12" fill="#16a34a"/>
  <text x="130" y="149" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">1</text>
  <line x1="145" y1="145" x2="385" y2="145" stroke="#666" stroke-width="1.5" marker-end="url(#zs6-fgray)"/>
  <text x="265" y="137" text-anchor="middle" font-size="10.5" fill="#2c3e50">write(fd, buf, len)</text>
  <circle cx="400" cy="200" r="12" fill="#fbbf24"/>
  <text x="400" y="204" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">2</text>
  <line x1="412" y1="200" x2="428" y2="200" stroke="#fbbf24" stroke-width="1.5"/>
  <rect x="430" y="182" width="210" height="36" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="535" y="197" text-anchor="middle" font-size="10.5" fill="#92400e">zfs_log_write(): itx 생성</text>
  <text x="535" y="211" text-anchor="middle" font-size="9" fill="#92400e">기록 방식 판정(세 가지 분기)</text>
  <circle cx="130" cy="255" r="12" fill="#16a34a"/>
  <text x="130" y="259" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">3</text>
  <line x1="145" y1="255" x2="385" y2="255" stroke="#666" stroke-width="1.5" marker-end="url(#zs6-fgray)"/>
  <text x="265" y="247" text-anchor="middle" font-size="10.5" fill="#2c3e50">fsync(fd)</text>
  <circle cx="400" cy="310" r="12" fill="#fbbf24"/>
  <text x="400" y="314" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">4</text>
  <line x1="415" y1="310" x2="655" y2="310" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#zs6-famber)"/>
  <text x="535" y="302" text-anchor="middle" font-size="10.5" fill="#92400e">zil_commit() (zil.c:3967)</text>
  <circle cx="670" cy="365" r="12" fill="#fbbf24"/>
  <text x="670" y="369" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">5</text>
  <line x1="682" y1="365" x2="698" y2="365" stroke="#fbbf24" stroke-width="1.5"/>
  <rect x="700" y="347" width="220" height="36" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="810" y="362" text-anchor="middle" font-size="10.5" fill="#92400e">zil_process_commit_list</text>
  <text x="810" y="376" text-anchor="middle" font-size="9" fill="#92400e">(zil.c:3146) itx 직렬화 · waiter 등록</text>
  <circle cx="670" cy="420" r="12" fill="#fbbf24"/>
  <text x="670" y="424" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">6</text>
  <line x1="685" y1="420" x2="925" y2="420" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#zs6-famber)"/>
  <text x="805" y="412" text-anchor="middle" font-size="10.5" fill="#92400e">lwb 블록 쓰기 + flush</text>
  <circle cx="940" cy="475" r="12" fill="#16a34a"/>
  <text x="940" y="479" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">7</text>
  <line x1="925" y1="475" x2="685" y2="475" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs6-fgreen)"/>
  <text x="805" y="467" text-anchor="middle" font-size="10.5" fill="#16a34a">zio 완료 ack (flush 포함)</text>
  <circle cx="400" cy="530" r="12" fill="#16a34a"/>
  <text x="400" y="534" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">8</text>
  <line x1="385" y1="530" x2="145" y2="530" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs6-fgreen)"/>
  <text x="265" y="522" text-anchor="middle" font-size="10.5" fill="#16a34a">fsync() 반환 - 내구성 확보</text>
  <rect x="50" y="565" width="970" height="68" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="70" y="588" font-size="11" font-weight="700" fill="#2c3e50">WR_INDIRECT라면</text>
  <text x="70" y="606" font-size="10.5" fill="#495057">단계 5~6의 lwb에는 blkptr만 기록됩니다. 데이터는 같은 txg의 dmu_sync() 결과물이 담당하고,</text>
  <text x="70" y="622" font-size="10.5" fill="#495057">replay는 blkptr 생존 검증 후 재연결할 뿐입니다. fsync 대기는 어느 쪽이든 lwb flush 완료로 풀립니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - fsync 한 번의 여정. 크래시 내구성의 판정 기준은 lwb 블록의 flush 완료 하나입니다</figcaption>
</figure>

정상 운영에서는 이렇게 쌓은 로그가 커밋과 함께 무효화됩니다. 그런데 크래시 직후에는 이 로그가 디스크에 남은 유일한 진실이 됩니다. 생애주기의 다음 단계입니다.

### 크래시에서 import, replay까지

크래시가 나면 메모리의 zilog, itx, lwb는 전부 소실되고 디스크의 로그 블록과 zil_header만 남습니다. import가 이 잔해를 어떻게 청산하는지가 ZIL 생애주기의 후반부입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1020 440" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="크래시에서 replay까지 ZIL 타임라인. 정상 운영 단계에서는 동기 쓰기를 lwb에 적재하고 txg 커밋분은 zil_sync가 무효화해 로그를 짧게 유지한다. 크래시 단계에서는 메모리의 zilog와 itx, lwb가 소실되고 디스크 로그만 남는다. import 단계에서는 uberblock을 선택해 first_txg를 확정해 미반영 경계를 획정한다. ZIL claim 단계에서는 zil_claim이 birth가 first_txg 이상인 블록만 소유 확정하며 zh_claim_txg를 남긴다. replay 완료 단계에서는 미반영 레코드만 순서대로 재실행하고 zil_destroy로 헤더를 정리해 빈 로그로 재출발한다. 하단의 3규칙은 txg 반영분 스킵, 미반영분만 순서 재생, 실패 레코드는 재시도 1회 후 경고하고 계속 진행함을 담는다.">
  <defs>
    <marker id="zs6-bgray" markerWidth="8" markerHeight="8" refX="6.5" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#666"/></marker>
  </defs>
  <text x="510" y="24" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">크래시에서 재기동까지: ZIL 타임라인</text>
  <circle cx="105" cy="56" r="12" fill="#16a34a"/>
  <text x="105" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">1</text>
  <rect x="20" y="56" width="170" height="90" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="105" y="84" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">정상 운영</text>
  <text x="105" y="103" text-anchor="middle" font-size="9.5" fill="#495057">동기 쓰기는 lwb에 적재</text>
  <text x="105" y="118" text-anchor="middle" font-size="9.5" fill="#495057">txg 커밋분은 zil_sync()</text>
  <text x="105" y="133" text-anchor="middle" font-size="9.5" fill="#495057">무효화 - 로그는 짧게</text>
  <circle cx="305" cy="56" r="12" fill="#dc2626"/>
  <text x="305" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">2</text>
  <rect x="220" y="56" width="170" height="90" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="305" y="84" text-anchor="middle" font-size="12" font-weight="700" fill="#dc2626">크래시</text>
  <text x="305" y="103" text-anchor="middle" font-size="9.5" fill="#495057">메모리 소실</text>
  <text x="305" y="118" text-anchor="middle" font-size="9.5" fill="#495057">zilog · itx · lwb 증발</text>
  <text x="305" y="133" text-anchor="middle" font-size="9.5" fill="#495057">디스크 로그만 남음</text>
  <circle cx="505" cy="56" r="12" fill="#666"/>
  <text x="505" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">3</text>
  <rect x="420" y="56" width="170" height="90" rx="8" fill="#f0f4f8" stroke="#666" stroke-width="1.5"/>
  <text x="505" y="84" text-anchor="middle" font-size="12" font-weight="700" fill="#666">import</text>
  <text x="505" y="103" text-anchor="middle" font-size="9.5" fill="#495057">uberblock 선택</text>
  <text x="505" y="118" text-anchor="middle" font-size="9.5" fill="#495057">first_txg 확정</text>
  <text x="505" y="133" text-anchor="middle" font-size="9.5" fill="#495057">미반영 경계 획정</text>
  <circle cx="705" cy="56" r="12" fill="#fbbf24"/>
  <text x="705" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">4</text>
  <rect x="620" y="56" width="170" height="90" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="705" y="84" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">ZIL claim</text>
  <text x="705" y="103" text-anchor="middle" font-size="9.5" fill="#495057">zil_claim (zil.c:1142)</text>
  <text x="705" y="118" text-anchor="middle" font-size="9.5" fill="#495057">birth &gt;= first_txg만</text>
  <text x="705" y="133" text-anchor="middle" font-size="9.5" fill="#495057">소유 확정 + claim_txg</text>
  <circle cx="905" cy="56" r="12" fill="#16a34a"/>
  <text x="905" y="60" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">5</text>
  <rect x="820" y="56" width="170" height="90" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="905" y="84" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">replay 완료</text>
  <text x="905" y="103" text-anchor="middle" font-size="9.5" fill="#495057">미반영분만 재실행</text>
  <text x="905" y="118" text-anchor="middle" font-size="9.5" fill="#495057">zil_destroy로 정리</text>
  <text x="905" y="133" text-anchor="middle" font-size="9.5" fill="#495057">빈 로그로 재출발</text>
  <line x1="190" y1="101" x2="218" y2="101" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs6-bgray)"/>
  <line x1="390" y1="101" x2="418" y2="101" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs6-bgray)"/>
  <line x1="590" y1="101" x2="618" y2="101" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs6-bgray)"/>
  <line x1="790" y1="101" x2="818" y2="101" stroke="#666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#zs6-bgray)"/>
  <text x="20" y="176" font-size="11" font-weight="700" fill="#2c3e50">zil_header 상태 (objset_phys 안) - 단계별 변화</text>
  <rect x="20" y="188" width="170" height="68" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1"/>
  <text x="105" y="212" text-anchor="middle" font-size="9.5" fill="#495057">zh_log가 체인 머리</text>
  <text x="105" y="228" text-anchor="middle" font-size="9.5" fill="#495057">커밋마다 체인 절단</text>
  <text x="105" y="244" text-anchor="middle" font-size="9.5" fill="#495057">zh_flags 평시 상태</text>
  <rect x="220" y="188" width="170" height="68" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1"/>
  <text x="305" y="212" text-anchor="middle" font-size="9.5" fill="#495057">디스크 상태 그대로</text>
  <text x="305" y="228" text-anchor="middle" font-size="9.5" fill="#495057">동결 - 마지막 진실</text>
  <text x="305" y="244" text-anchor="middle" font-size="9.5" fill="#495057">ZIL_REPLAY_NEEDED</text>
  <rect x="420" y="188" width="170" height="68" rx="6" fill="#f0f4f8" stroke="#666" stroke-width="1"/>
  <text x="505" y="212" text-anchor="middle" font-size="9.5" fill="#495057">uberblock txg 기준</text>
  <text x="505" y="228" text-anchor="middle" font-size="9.5" fill="#495057">first_txg = import txg</text>
  <text x="505" y="244" text-anchor="middle" font-size="9.5" fill="#495057">재생 범위 결정</text>
  <rect x="620" y="188" width="170" height="68" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1"/>
  <text x="705" y="212" text-anchor="middle" font-size="9.5" fill="#495057">zh_claim_txg &gt; 0</text>
  <text x="705" y="228" text-anchor="middle" font-size="9.5" fill="#495057">블록별 zio_claim</text>
  <text x="705" y="244" text-anchor="middle" font-size="9.5" fill="#495057">이미 커밋분은 제외</text>
  <rect x="820" y="188" width="170" height="68" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <text x="905" y="212" text-anchor="middle" font-size="9.5" fill="#495057">헤더 초기화</text>
  <text x="905" y="228" text-anchor="middle" font-size="9.5" fill="#495057">빈 체인 = 정상 복귀</text>
  <text x="905" y="244" text-anchor="middle" font-size="9.5" fill="#495057">플래그 해제</text>
  <rect x="20" y="296" width="970" height="124" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="40" y="322" font-size="12" font-weight="700" fill="#16a34a">replay 3규칙 - zil_replay_log_record()</text>
  <text x="40" y="348" font-size="11" fill="#2c3e50">1. txg 반영분은 건너뛴다 - blkptr birth &lt; first_txg 또는 lrc_txg &lt; claim_txg면 이미 커밋된 것 (zil.c:4710)</text>
  <text x="40" y="372" font-size="11" fill="#2c3e50">2. 미반영분만 순서대로 - lrc_seq &gt; zh_replay_seq인 레코드부터 로그 순서대로 재실행 (zil.c:4708)</text>
  <text x="40" y="396" font-size="11" fill="#2c3e50">3. 실패한 레코드는 스킵하고 계속 - 재시도 1회 후 경고만 남기고 import는 중단되지 않는다</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - 크래시에서 재출발까지. claim이 미반영 경계를 획정하고 replay가 미반영분만 순서대로 재생합니다</figcaption>
</figure>

claim이 먼저입니다. `zil_claim()`(zil.c:1142)이 zh_log 체인을 훑며 블록 단위로 소유를 확정합니다. 이때 birth가 first_txg 이상인 블록만 클레임합니다. birth가 first_txg보다 작으면 이미 이전 txg에 커밋된 블록이므로 제외합니다. "재생할 필요가 있는가"라는 판별이 replay 이전의 claim 단계에서 이미 이뤄집니다.

replay는 두 조건을 건너뛰며 순서대로 재생합니다(zil.c:4708, zil.c:4710). lrc_seq가 zh_replay_seq 이하면 이미 재생된 레코드이고, lrc_txg가 claim_txg보다 작으면 이미 커밋된 레코드입니다. 개별 재생 실패는 재시도 1회 후 경고만 남기고 계속합니다. 재생이 끝나면 zil_destroy가 헤더를 초기화하고 체인을 해제합니다. 실패가 남아 있어도 import가 실패하지는 않습니다.

### zil_suspend: 로그를 끄고 txg로 대체

ZIL은 동기 의미론을 로그로 지키지만, 반대 방향의 스위치도 있습니다. `zil_suspend()`(zil.c:4502)는 로그를 잠시 멈추고 빈 상태로 만듭니다. 원문 주석(zil.c:4480 부근)이 요지를 말해줍니다. suspended 모드에서도 동기 의미론은 그대로 지키되, 그 보장을 로그가 아니라 txg_wait_synced()로 달성한다는 것입니다. suspend 중 들어오는 동기 쓰기는 fsync가 txg 싱크 대기로 대체되는 방식입니다.

호출자는 로그에 미처리 데이터가 남으면 곤란한 작업들입니다. zfs receive의 덮어쓰기 모드와 destroy/reset 경로(zil_reset())가 대표적입니다. 두 번째 인자 cookiep가 suspend와 resume을 분리합니다. NULL이면 suspend 후 즉시 resume까지 한 번에 처리하고, 아니면 데이터셋에 long hold를 건 채 cookie를 돌려줘 짝이 되는 zil_resume()(zil.c:4658)에서 재개합니다. 재개 시점을 호출자가 정하는 구조입니다.

주의점 하나. zh_flags에 ZIL_REPLAY_NEEDED가 남아 있으면, 즉 크래시 후 아직 replay되지 않은 로그가 있으면 zil_suspend는 EBUSY로 실패합니다. replay가 먼저입니다.

### 관찰 포인트: 동기 쓰기가 느릴 때 보는 곳

동기 쓰기 성능은 추측하지 말고 카운터로 봅니다. 도구와 보는 지점은 정해져 있습니다.

| 관찰 수단 | 무엇을 보나 |
|---|---|
| zilstat | 데이터셋별 초당 동기 쓰기 건수와 바이트, lwb 할당 통계 |
| /proc/spl/kstat/zfs/zil | zil_itx_* 카운터로 itx 유형별(indirect/copied/needcopy) 비중과 바이트, commit 횟수 |
| zpool status (logs 항목) | slog 유무. 있으면 기록 방식에서 INDIRECT가 금지됨 |
| zfs get logbias | latency(기본)면 복사형, throughput이면 크기 무관 무조건 WR_INDIRECT |
| zfs get sync | always면 모든 쓰기가 ZIL 행. disabled면 ZIL 회피(크래시 보장 상실) |

점검 순서는 이렇게 잡습니다. 먼저 zpool status의 logs 항목으로 slog 유무를 봅니다. 없으면 작은 복사형 쓰기도 일반 vdev에서 flush를 치릅니다.

다음은 logbias입니다. throughput이면 전부 indirect라 fsync가 txg 싱크 근처까지 끌립니다. 세 번째로 sync 속성과 앱의 fsync 빈도, 마지막으로 kstat의 needcopy 비중을 봅니다.

비정상적으로 높으면 작은 동기 쓰기 폭풍이라 slog 추가가 정석 처방입니다. 감각 수치 하나를 남기면, logbias=latency에서 8KB 동기 쓰기 1만 건은 ZIL에 약 80MB입니다.

Write Path를 쓸 때는 ZIL을 디스크에 빨리 쓰는 장치쯤으로 이해했습니다. 소스를 읽고 보니 실체는 크래시까지 유효한 약속 장부에 가깝습니다. 약속(itx)을 어떻게 운반(lwb)하고 파기(zil_sync)하고 청산(replay)하는지가 전부였고, 약속의 형태가 세 가지인 것도 크기와 매체에 따른 절약의 결과였습니다. 약속 장부라는 관점에서 보면 slog 역설도, suspend가 로그를 끄고 txg로 대체하는 설계도 자연스럽게 읽힙니다.


ZIL은 크래시 직후의 약속을 지키는 장부였습니다. 그런데 디스크가 아예 죽으면 약속 장부만으로는 데이터가 돌아오지 않습니다. 복구의 열쇠는 또 하나의 장부, DTL입니다.

## Resilver: DTL 장부와 자가복구

미러나 raidz에서 디스크 한 장이 죽는 일은 예정된 이벤트입니다. 교체 디스크를 꽂으면 resilver가 장부를 펴고 그 만큼만 다시 씁니다. 질문은 무엇을, 얼마나, 어디부터 다시 쓰는가이고 답은 DTL 장부와 두 경로에 있습니다.

### 같은 기계, 다른 질문: resilver 대 scrub

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

### DTL: 어디가 비었는지의 장부

vdev마다 잃은 데이터를 range_tree로 들고 있고 운영상 의미 있는 세 종류입니다(vdev.h:44).

| 종류 | 뜻 | 운영에서의 의미 |
|---|---|---|
| DTL_MISSING | 이 구간 데이터의 복제본이 하나도 없음(0%) | 위험 상태. resilver의 1차 대상이며 zpool status의 DEGRADED 표기의 실체 |
| DTL_PARTIAL | 복제본은 있으나 일부 vdev에 없음(100% 미만) | resilver가 MISSING과 함께 메움. 상태 표시로는 잘 드러나지 않음 |
| DTL_SCRUB | scrub·resilver 중 끝내 복구 못 한 흔적 | 다음 스캔의 재시도 목록 |

네 번째 DTL_OUTAGE는 detach용 임시 장부로 평소 비어 있습니다. 핵심은 단위입니다. DTL은 "블록 12345가 없다"가 아니라 "txg 100~250에 쓴 데이터가 없다"고 적습니다. 블록 포인터가 태어난 txg(blk_birth)를 달고 있으니 birth가 구간 안인가만 보면 되고 시간 구간 하나로 수천 블록을 대신하니 장부가 작습니다.

장부는 이탈 순간부터 쌓입니다. 죽은 순간의 txg부터 DTL_MISSING에 구간이 자라고, 죽어 있던 동안의 쓰기가 없으니 돌아와도 그대로입니다. 풀이 통째로 죽어 있었다면 import 시 마지막 정상 txg부터 깔립니다. 아래 그림이 장부의 일생입니다.

<figure>
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
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - DTL 장부의 일생. 이탈 순간(txg 100)부터 복구 완료(excise)까지, 장부의 단위는 txg 구간</figcaption>
</figure>

장부가 목록이 아니라 구간임이 요점입니다. 시작 판정부터 봅니다.

#### 언제 시작되나: 트리거와 판정

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

### Healing resilver: 트리를 걷으며 블록을 고친다

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

### Sequential resilver: mirror는 디스크를 순서대로 채운다

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

<figure>
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
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - 두 경로의 대비. healing은 트리를 걷고(raidz 포함), sequential은 디스크를 순서대로 채운다(mirror)</figcaption>
</figure>

실패와 전환도 장부가 결정합니다. COMPLETE 외의 종료는 DTL을 지우지 않으므로 장부가 남으면 필요 판정(spa.c:6268)이 healing을 이어서 일으킵니다. 새 디스크 attach 시 처음부터 재시작하는 것도 동시 교체 시 비용이고, DDT 풀의 재구성은 이 시리즈 범위 밖입니다.

### 완료와 DTL excise: 수렴의 조건

스캔이 끝나면 sync 시점에 vdev_dtl_reassess()가 구간을 잘라냅니다(excise). 직관과 다른 규칙을 짚습니다.

> **스캔 중 새 쓰기는 DTL을 늘리지 않습니다.** 새 디스크는 이미 정식 mirror 멤버라 이후의 쓰기는 일반 경로로 멤버 전부에 기록됩니다. 재시작의 실제 조건은 복구 실패입니다. healing은 오류가 남아 끝나면 DTL을 못 잘라내고 스스로 재시작하며(scn_errors &gt; 0, dsl_scan.c:708) 대상이 정상인 한 "resilvered 0 errors"로 수렴합니다.

흔적은 두 갈래입니다. 못 읽은 구간은 DTL_SCRUB에 남아 재시도 목록이 되고 파일 단위는 영구 에러 로그로 zpool status -v에 나옵니다. 의외로 일반 읽기 중의 자발적 self-healing 쓰기 실패만은 transactional context가 없어 DTL에 못 남깁니다(vdev.c:5315).

운영 장치도 둘입니다. 교체 직후 또 디스크가 죽으면 zfs_resilver_defer_percent(기본 10%) 기준으로 새 resilver를 지연시키고 기존 것을 마저 돌리며, 여러 vdev의 DTL은 하나의 스캔이 통합 처리합니다.

장부가 곧 체크포인트입니다. 관찰 방법으로 마무리합니다.

### 운영에서 무엇을 보아야 하나

| 보고 싶은 것 | 방법 | 해석 |
|---|---|---|
| 진행률과 ETA | zpool status | 퍼센트는 live 데이터량 기준 추정. 초반 급상승 후 느려지는 게 정상 |
| 장부의 진실 | zdb -ddd 풀이름, "Dirty time logs" 섹션 | vdev별 missing·partial·scrub 구간이 txg 범위로 출력됨. 퍼센트가 정체돼 보여도 구간이 줄고 있으면 진행 중 |
| 어느 경로인지 | zpool status 문구 | "resilvered"는 healing, "rebuilt"는 sequential. mirror는 보통 sequential, raidz는 항상 healing |
| 속도 조절 | zfs_resilver_min_time_ms (기본 3000) | txg당 스캔에 할당하는 최소 시간. 크면 재구성은 빨라지고 전경 I/O 영향은 커짐 |
| 오류 목록 | zpool status -v | 영구 에러 로그. 재검사는 zpool scrub -e(error scrub)로 오류 블록만 골라 |

> **운영 요령 세 가지.** 교체는 반드시 zpool replace로 합니다. dd 직접 복사는 vdev GUID까지 복제해 import가 거부됩니다. 여러 장은 통합 스캔을 위해 동시에 교체합니다. resilver 중단도 안전합니다. DTL이 체크포인트라 메운 구간은 다시 하지 않습니다.

"resilver가 느리다"는 불만의 상당수는 진행률 추정 착시입니다. 저도 %가 멈춘 듯 보일 때 zdb의 Dirty time logs에서 장부가 줄고 있음을 보고 안심했습니다. 교체를 절차로 만든 비결은 결국 이 장부입니다. 실패는 장부에 남고, 남아 있으면 다시 시도한다. 이 원칙이 자가복구의 전부입니다.


복사로 빈 디스크를 다시 채웠다면, 남은 질문은 그 데이터가 온전한가입니다. 검증이 본업인 스캔이 여기 등장합니다.

## Scrub: 검증이 본업인 배경 스캔

### 같은 기계, 다른 본업

앞 절에서 resilver는 "비어 있는 복제본을 메우는 복사"가 목적이라고 했습니다. scrub의 목적은 복사가 아니라 검증입니다. 풀에 살아 있는 모든 블록을 읽어 체크섬과 대조하고, 어긋나면 고칠 수 있는 경로로 고치며, 최종적으로 못 고친 오류의 목록을 사용자에게 보고합니다.

흥미로운 사실은 이 둘이 같은 기계를 돌린다는 점입니다.

```c
/* dsl_scan.c:255: scrub과 resilver가 같은 콜백을 공유한다 */
scan_funcs[POOL_SCAN_SCRUB]    = dsl_scan_scrub_cb;
scan_funcs[POOL_SCAN_RESILVER] = dsl_scan_scrub_cb;
```

하나의 콜백이 두 모드를 모두 처리하고, 내부에서 지금 검증 중인지 복제 중인지를 스캔 상태로 구분합니다. 앞 절에서 본 순회, 발급, 완료 골격이 그대로 재사용되기 때문에, 이 글은 scrub 모드에 고유한 부분인 순회 대상, 시간 배분, 오류 처리의 갈림길에 집중합니다.

#### 순회 대상과 checkpoint 제외

순회의 1차 대상은 5편과 같이 MOS와 데이터셋 트리를 따라가며 live 블록 포인터를 하나씩 콜백에 넘기는 구조입니다. scrub이 한 걸음 더 나아가는 지점은 검증 대상의 폭입니다. dedup이 활성화된 풀에서는 DDT 엔트리 자체도 검증 대상에 들어갑니다. `ddt_walk_init(spa, scn_max_txg)`(dsl_scan.c:746)로 DDT를 처음부터 끝까지 걷는 커서를 준비하고, 엔트리가 적힌 체크섬과 위치, 참조 카운트가 실제 디스크와 일치하는지까지 확인합니다.

주의할 제외 대상도 있습니다. 풀에 checkpoint가 존재하면 해당 블록은 scrub 순회에서 제외되고 사용자에게 경고가 출력됩니다(zpool_main.c:9453). 예전 시점으로 돌아가기 위한 보존 구간이므로 지금 상태를 검증해 봤자 의미가 없기 때문입니다. checkpoint가 있는 풀에서 scrub 리포트를 읽을 때는 이 경고 문구를 먼저 확인해야 합니다.

대상을 알았으니, 이 스캔이 얼마나 공격적으로 디스크를 읽는지가 다음 질문입니다.

### 시간 배분: mintime과 조건부 양보

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

<figure>
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
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5 - 한 txg의 시간 배분. mintime까지는 보장, 이후에는 조건 하나라도 걸리면 즉시 양보하는 손님 설계</figcaption>
</figure>

mintime이 scrub의 권리라면 양보 조건은 scrub의 예의입니다. 이 설계가 3편의 txg 상태머신과 만나는 지점도 자연스럽습니다. scrub이 sync를 늘어지게 하는 주범이 되지 않도록 자기 발급을 스스로 끊는 것입니다. 그럼 스캔이 블록을 읽고 난 뒤에는 무슨 일이 벌어질까요.

### 오류 처리의 갈림길

콜백이 블록을 읽어 체크섬을 대조한 결과는 두 갈래로 나뉩니다. 일치하면 아무 일도 없이 순회가 계속됩니다. 불일치하면 앞 편의 읽기 절에서 본 self-healing 경로가 동원됩니다. mirror라면 반대편, raidz라면 패리티로 정상 복제본을 재구성하고, 확보한 정상 데이터로 원래 자리를 다시 씁니다. 재기록이 성공하면 수선 카운터만 남고 scrub은 계속 전진합니다.

문제는 모든 복제본이 다 틀렸거나 읽히지 않을 때입니다. 이 경우 세 곳에 흔적이 남습니다.

1. **scn_errors 카운터**: 스캔 오류 수. 완료 보고의 재료입니다.
2. **영구 에러 로그(errlog)**: 어느 파일의 어느 범위가 깨졌는지 기록합니다. `zpool status -v`의 목록이자 error scrub의 입력입니다.
3. **DTL_SCRUB 마킹**: 이번 scrub으로도 못 고친 txg 구간을 vdev 장부에 적습니다(vdev.c:3086).

DTL_SCRUB은 5편에서 본 DTL 장부 시스템의 세 번째 페이지입니다. scrub이 완료되면 "마지막 scrub 이후 못 고친 txg 구간"이 DTL_MISSING을 대체해 등재됩니다. 구현 디테일도 재미있습니다. vdev.c:3379의 refcnt 2 트릭은 교체 직후의 DTL_MISSING과 방금 끝난 scrub의 DTL_SCRUB이 같은 range 구조를 참조로 공유해, 장부를 복사하는 비용 없이 소유권만 넘깁니다. 이 장부는 이후 resilver가 재시도 목록으로 읽어 들이는 대상입니다.

여기서 5편과의 중요한 대비가 나옵니다. resilver는 오류가 쌓이면 스스로 재시작하지만(dsl_scan.c:708-719), **scrub은 재시작하지 않습니다.** 오류가 나도 끝까지 순회를 마치고 수집된 오류를 보고하는 것으로 종료합니다. 검증 스캔이 실패 블록에서 무한 루프에 빠지지 않게 하는 절제 장치입니다. 아래 그림이 블록 하나의 운명을 정리합니다.

<figure>
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
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6 - 블록 하나의 운명. 초록은 조용한 통과와 수선, 빨강은 errlog와 DTL_SCRUB 장부에 기록된 뒤 순회에 합류</figcaption>
</figure>

실패가 스캔을 중단시키지 않고 장부로 넘어가는 구조. 이것이 검증 스캔의 절제입니다. 그런데 못 고친 블록을 다시 보고 싶을 때는 어떻게 할까요.

### 운영의 손잡이: pause, thorough, error scrub

scrub은 시간 단위로 걸리는 작업이라 운영상 통제 장치가 필요합니다. 세 가지가 있습니다.

**pause/resume**. `zpool scrub -p`와 `-s`의 입구는 `dsl_scrub_set_pause_resume`(dsl_scan.c:1373)이며 스캔 상태에 PAUSE를 새깁니다. 일시정지는 진행 중인 I/O를 날리는 게 아니라 txg 경계에서 추가 발급을 멈추는 것에 가깝습니다. 이미 발급된 I/O는 마무리되고 resume까지 새 발급이 없습니다.

**thorough 모드**. `DSF_SCRUB_THOROUGH`(dsl_scan.h:79, 값 1<<2)는 더 빠짐없이 훑으라는 스위치입니다. 플래그가 스캔 상태에 남아 있으므로 pause/resume 도중에도 이 scrub이 thorough였다는 사실이 유지됩니다.

**error scrub**. 2.2+의 제3 스캔 모드입니다. `POOL_SCAN_ERRORSCRUB`가 별도 타입으로 등록되고(dsl_scan.c:840), 검사 대상 수를 `spa_get_last_errlog_size()`(dsl_scan.c:855)로 정합니다. 즉 전체 블록이 아니라 영구 에러 로그에 남아 있는 블록만 골라 재검사합니다. `zpool scrub -e`로 시작하며 진행도는 별도 계열로 집계됩니다.

역할이 선명합니다. scrub이 실패 블록을 errlog에 기록해 두면, error scrub은 그 장부를 입력으로 삼아 정말 고쳐졌는지를 최소 비용으로 확인합니다. 검증(full scrub)에서 기록(errlog)을 거쳐 선별 재검증(error scrub)으로 이어지는 루프의 마지막 조각입니다.

### 관찰 포인트와 튜닝

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

Resilver 절을 쓸 때는 resilver와 scrub이 비슷한 것 아닌가 했는데, 소스를 읽고 보면 같은 기계에 정반대의 철학이었습니다. resilver가 실패하면 몇 번이든 다시 시작하는 집념의 스캔이라면, scrub은 실패를 장부에 적고 끝까지 앞으로만 가는 절제의 스캔입니다. 재시작하지 않는 이유를 질문하다 보니 DTL 장부의 세 페이지와 errlog, error scrub까지가 하나의 순환 구조로 이어졌습니다. 검증은 고침이 아니라 측정이고, 측정의 결과는 다음 복구의 입력이 된다는 설계였습니다.

다음 편 (5/5, 마지막) zresmon, 시리즈의 관찰 포인트를 도구로 만든 이야기는 준비 중입니다: [ZFS-Study-05-Zresmon](/2026/08/29/ZFS-Study-05-Zresmon/)
