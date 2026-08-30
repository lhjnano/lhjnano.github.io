---
layout: post
title: "ZFS 소스 학습 (6/8): ZIL - intent log의 생애주기"
categories: [Storage, Filesystem, OpenZFS]
description: "ZFS fsync는 txg를 기다리지 않고 어떻게 크래시에 살아남을까? ZIL의 기록 방식 3가지와 replay 생애주기를 정리했습니다."
keywords: [ZFS, OpenZFS, ZIL, fsync, slog, intent log, replay]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (6/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

이 글의 분기와 함수는 OpenZFS master 소스를 직접 읽어 확인했고, 인용은 `파일:라인` 형식입니다(zil.c:2213, zil.c:3146, zil.c:3967, zil.c:1142, zil.c:4708). 라인은 커밋마다 흐르니 함수명 grep이 안전합니다.

이전 편 (5/8) Resilver, 디스크 교체 후 데이터를 다시 채우는 여정: [ZFS-Study-05-Resilver](/2026/08/29/ZFS-Study-05-Resilver/)

이전 편 (3/8) Write Path, zfs_write()에서 uberblock 커밋까지 두 막: [ZFS-Study-03-Write-Path](/2026/08/29/ZFS-Study-03-Write-Path/)

3편에서 write(2)의 반환은 ARC까지만 가고 디스크 반영은 txg 싱크(기본 최대 5초)의 몫이라고 했습니다. 그런데 POSIX fsync는 반환 후 크래시가 나도 이 데이터는 살아 있어야 한다고 요구합니다. fsync를 txg 완료로 구현하면 건당 수 초의 지연이고, 데이터베이스 WAL이나 메일큐 같은 동기 워크로드는 못 견딥니다. txg는 효율을 위한 묶음이고 POSIX는 개별 보장입니다. 이 간극이 ZIL(ZFS Intent Log)을 낳았습니다. 무엇을 썼는지만 적는 작은 저널로, txg 커밋을 기다리지 않고 크래시 내구성을 보장합니다.

주의할 점 하나를 먼저 박아둡니다. ZIL에는 동기 의미론이 필요한 쓰기만 기록됩니다. 비동기 쓰기는 ZIL을 전혀 거치지 않고 ARC 더티에서 txg로 직행합니다. 그래서 "ZIL이 느리다"는 말은 항상 "동기 쓰기 워크로드가 느리다"는 뜻이고 async 쓰기 성능과는 무관합니다.

## TL;DR

- ZIL은 **동기 쓰기만** 기록하는 저널입니다. ZIL 이야기는 곧 fsync 이야기입니다.
- 네 객체가 분업합니다. **zilog**(objset당 로그 상태머신), **itx**(연산 레코드), **lwb**(디스크로 나르는 체인 블록), **zil_header**(objset_phys 안 체인 머리).
- 기록 방식은 셋입니다. 작은 동기 쓰기는 복사(WR_COPIED), 분할이 필요하면 WR_NEED_COPY, 크면 blkptr만(WR_INDIRECT). **slog가 있으면 INDIRECT가 금지**됩니다.
- fsync는 commit itx를 넣고 **lwb flush 완료**를 기다렸다가 반환합니다. 쓰기 막 1의 유일한 디스크 I/O입니다.
- 크래시 후 import는 claim으로 소유를 확정하고 replay가 미반영분만 재실행합니다. 정상 커밋된 로그는 zil_sync()가 무효화해 로그는 짧게 유지됩니다.

## 구조: zilog, itx, lwb, zil_header

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

## 세 가지 기록 방식: 복사할까, 가리킬까

모든 동기 쓰기가 데이터를 로그에 복사하는 것은 아닙니다. 쓰기마다 `zil_write_state()`(zil.c:2213)가 복사할지, 가리키기만 할지 정합니다. 분기는 짧습니다. logbias=throughput이거나 O_DIRECT면 논쟁 없이 WR_INDIRECT입니다. 크기가 zfs_immediate_write_sz(기본 32K) 이상이면서 블록 크기의 절반 이상이거나 commit 대상이 아니면 INDIRECT 후보입니다. 나머지는 commit 여부로 갈라져 WR_COPIED(fsync 대기 중) 또는 WR_NEED_COPY(나중에 묶음)가 됩니다.

여기에 역설이 하나 있습니다. **slog가 있으면 spa_has_slogs()가 indirect를 무조건 꺼버립니다.** slog는 작은 복사형 쓰기의 지연을 줄이는 전용 공간이므로, slog를 다느냐 마느냐가 기록 방식 자체를 바꿉니다. "전용 로그 디바이스가 있으면 큰 쓰기도 로그로 옮겨가겠거니"라는 직감과 반대 방향입니다. special vdev는 zil_special_is_slog(기본 1) 설정에 따라 slog처럼 취급할지 결정합니다.

강등 규칙도 하나 있습니다. WR_COPIED로 골라졌어도 레코드가 한 로그 블록에 통째로 안 들어가면(zil_maxcopied 기본 7680바이트 초과, zfs_log.c:647) WR_NEED_COPY로 강등됩니다. 복사 도중 dmu_read가 실패해도 같은 길을 갑니다.

| 구분 | WR_COPIED | WR_NEED_COPY | WR_INDIRECT |
|---|---|---|---|
| 언제 선택되나 | commit(fsync 대기)이고 데이터가 한 로그 블록에 들어갈 때(7680바이트 이하) | commit 예정이 없거나 한 블록을 넘어 분할이 필요할 때 | 32K 이상이고 블록 절반 이상 또는 비커밋. logbias=throughput과 O_DIRECT는 무조건 |
| lwb에 기록되는 것 | lr_write 레코드 안에 **데이터 사본** | 데이터를 **여러 lwb에 나눈** 연속 레코드 | **blkptr만**(lr_blkptr). 데이터는 dmu_sync() 경로로 이미 기록 중 |
| 크래시 복구 | 로그에 내장된 데이터를 읽어 원 오프셋에 재기록 | 체인을 순서대로 이어 붙인 뒤 재기록 | claim이 blkptr 생존 검증 후 bp에서 읽어 반영 |
| slog가 있는 풀에서 | slog 블록에 배치 | slog 블록에 배치 | 선택 자체가 금지 |

방식이 정해지면 남은 것은 fsync의 실제 흐름입니다. 다음 그림 하나가 ZIL 전체 동작의 지도입니다.

## fsync 한 번의 관찰 프레임

앱의 write(2)는 ZPL의 zfs_log_write()를 거쳐 itx가 되어 큐에 쌓입니다. 이어 fsync(2)가 오면 zil_commit()(zil.c:3967)이 commit itx를 넣고, zil_process_commit_list(zil.c:3146)가 itx를 lwb로 직렬화하며 waiter를 등록합니다. lwb는 zio로 디스크에 쓰인 뒤 flush(FUA/barrier)를 치르고, flush까지 포함된 완료 ack가 오면 waiter가 깨어나(zcw_done) fsync가 반환됩니다. 크래시 내구성의 판정 기준은 lwb 블록이 디스크에 flush됐는가 하나입니다.

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

## 크래시에서 import, replay까지

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

## zil_suspend: 로그를 끄고 txg로 대체

ZIL은 동기 의미론을 로그로 지키지만, 반대 방향의 스위치도 있습니다. `zil_suspend()`(zil.c:4502)는 로그를 잠시 멈추고 빈 상태로 만듭니다. 원문 주석(zil.c:4480 부근)이 요지를 말해줍니다. suspended 모드에서도 동기 의미론은 그대로 지키되, 그 보장을 로그가 아니라 txg_wait_synced()로 달성한다는 것입니다. suspend 중 들어오는 동기 쓰기는 fsync가 txg 싱크 대기로 대체되는 방식입니다.

호출자는 로그에 미처리 데이터가 남으면 곤란한 작업들입니다. zfs receive의 덮어쓰기 모드와 destroy/reset 경로(zil_reset())가 대표적입니다. 두 번째 인자 cookiep가 suspend와 resume을 분리합니다. NULL이면 suspend 후 즉시 resume까지 한 번에 처리하고, 아니면 데이터셋에 long hold를 건 채 cookie를 돌려줘 짝이 되는 zil_resume()(zil.c:4658)에서 재개합니다. 재개 시점을 호출자가 정하는 구조입니다.

주의점 하나. zh_flags에 ZIL_REPLAY_NEEDED가 남아 있으면, 즉 크래시 후 아직 replay되지 않은 로그가 있으면 zil_suspend는 EBUSY로 실패합니다. replay가 먼저입니다.

## 관찰 포인트: 동기 쓰기가 느릴 때 보는 곳

동기 쓰기 성능은 추측하지 말고 카운터로 봅니다. 도구와 보는 지점은 정해져 있습니다.

| 관찰 수단 | 무엇을 보나 |
|---|---|
| zilstat | 데이터셋별 초당 동기 쓰기 건수와 바이트, lwb 할당 통계 |
| /proc/spl/kstat/zfs/zil | zil_itx_* 카운터로 itx 유형별(indirect/copied/needcopy) 비중과 바이트, commit 횟수 |
| zpool status (logs 항목) | slog 유무. 있으면 기록 방식에서 INDIRECT가 금지됨 |
| zfs get logbias | latency(기본)면 복사형, throughput이면 크기 무관 무조건 WR_INDIRECT |
| zfs get sync | always면 모든 쓰기가 ZIL 행. disabled면 ZIL 회피(크래시 보장 상실) |

점검 순서는 이렇게 잡습니다. 먼저 zpool status의 logs 항목으로 slog 유무를 봅니다. 없으면 작은 복사형 쓰기도 일반 vdev에서 flush를 치릅니다. 다음으로 logbias입니다. throughput이면 전부 indirect라 fsync가 txg 싱크 근처까지 끌립니다. 세 번째로 sync 속성과 앱의 fsync 빈도, 마지막으로 kstat의 needcopy 비중입니다. 비정상적으로 높으면 작은 동기 쓰기 폭풍이라 slog 추가가 정석 처방입니다. 감각 수치 하나를 남기면, logbias=latency에서 8KB 동기 쓰기 1만 건은 ZIL에 약 80MB입니다.

3편을 쓸 때는 ZIL을 디스크에 빨리 쓰는 장치쯤으로 이해했습니다. 소스를 읽고 보니 실체는 크래시까지 유효한 약속 장부에 가깝습니다. 약속(itx)을 어떻게 운반(lwb)하고 파기(zil_sync)하고 청산(replay)하는지가 전부였고, 약속의 형태가 세 가지인 것도 크기와 매체에 따른 절약의 결과였습니다. 약속 장부라는 관점에서 보면 slog 역설도, suspend가 로그를 끄고 txg로 대체하는 설계도 자연스럽게 읽힙니다.

다음 편 (7/8) Scrub, 풀 전체를 읽어 무결성을 검증하는 배경 검사: [ZFS-Study-07-Scrub](/2026/08/29/ZFS-Study-07-Scrub/)
