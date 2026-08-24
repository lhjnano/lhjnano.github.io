---
layout: post
title: "FreeBSD kqueue(2): 커널이 기억하는 이벤트 큐"
categories: [FreeBSD, Kernel]
description: "select와 epoll은 매번 관심 목록을 다시 건네는데 kqueue는 커널이 상태를 기억합니다. 필터 구조와 epoll과의 차이를 정리했습니다."
keywords: [FreeBSD, kqueue, kevent, epoll, 이벤트 루프, EV_SET, EVFILT]
toc: true
toc_sticky: true
---

네트워크 서비스의 심장은 이벤트 루프입니다. 지켜볼 것이 열 개면 열 개를 감시하다가, 준비된 것만 골라 깨어나 처리하는 구조죠. 여기에는 피할 수 없는 질문이 하나 있습니다. **"누가 준비를 기억하는가"**입니다. 응용이 매번 관심 목록을 다시 건네면 select(2)/poll(2)이고, 커널이 기억하면 epoll이고 kqueue입니다. 이 글은 FreeBSD가 이 질문에 어떻게 답했는지, 그 답인 kqueue(2)를 설계부터 읽는 기록입니다.

select와 poll이 매번 목록 전체를 다시 건넬 때, kqueue는 커널이 등록을 기억합니다. 이 차이에서 출발해 필터 구조, 트리거 모드, epoll과의 대비까지 정리했습니다. API 시그니처와 동작은 FreeBSD 매뉴얼(kqueue(2), 14.x-RELEASE 기준)으로 대조해 정리했고, Rust 바인딩(nix 0.31.3, mio 1.2.2)의 FreeBSD 타깃 지원은 2026-07-27에 검증했습니다.

## TL;DR

- kqueue는 **커널이 관리하는 stateful 이벤트 큐**입니다. 응용이 목록을 다시 건네지 않습니다.
- 소켓·타이머·시그널·AIO·파일시스템·프로세스가 **같은 큐에 필터로 공존**합니다. epoll이 timerfd, signalfd를 별도 fd로 만들어 등록하는 것과 가장 다른 지점입니다.
- `kevent()` **한 번의 호출이 등록(changelist)과 반출(eventlist)을 동시에** 처리합니다. epoll이 `epoll_ctl`과 `epoll_wait`로 분리된 것과 대비됩니다.
- 기본은 레벨 트리거이고 `EV_CLEAR`를 붙여야 엣지 트리거입니다. epoll의 기본 레벨·`EPOLLET` 엣지와 대칭 구조입니다.
- epoll에서 kqueue로 오는 방향은 축소 통합이지만, 반대 방향은 inotify·pidfd·eventfd 조합이 필요해 어렵습니다.

## 한 줄 정의와 세 가지 설계 축

한 문장으로 정의하면 이렇습니다.

> kqueue는 이질적인 이벤트 소스를 필터 단위로 등록하고, 커널이 그 상태를 기억하게 만든 뒤, 하나의 시스템 콜로 변경과 반출을 함께 수행하는 통합 이벤트 통보 메커니즘이다.

설계를 뒷받침하는 축이 세 개 있습니다.

1. **커널 이벤트 큐**: 큐의 주인이 응용이 아니라 커널입니다. 등록한 사실이 커널에 남습니다(stateful).
2. **필터 기반 다중 타입**: `EVFILT_READ`, `EVFILT_TIMER`, `EVFILT_SIGNAL`, `EVFILT_AIO`, `EVFILT_VNODE`, `EVFILT_PROC`, `EVFILT_USER`가 모두 같은 큐에 들어갑니다.
3. **단일 구조체**: `struct kevent` 하나가 모든 이벤트를 표현합니다. 읽기 가능한 소켓과 만료된 타이머가 같은 eventlist 배열에 섞여 돌아옵니다.

말로는 추상적입니다. 구조를 그림으로 펼치면 세 축이 한 번에 보입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 560" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="kqueue 구조 다이어그램: 이질적 이벤트 소스 5종이 커널의 kqueue에 필터로 등록되고, 애플리케이션이 kevent 호출 하나로 등록과 반출을 동시에 수행하는 구조">
  <defs>
    <marker id="kq-arr-gray" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="kq-arr-blue" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#2563eb"/>
    </marker>
    <marker id="kq-arr-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="450" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">kqueue: 이질적 소스를 하나의 커널 큐로</text>

  <text x="145" y="62" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">이벤트 소스 (ident)</text>
  <rect x="50" y="72" width="190" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="145" y="99" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">소켓 · 파이프 · fd</text>
  <text x="145" y="120" text-anchor="middle" font-size="10" fill="#8b949e">EVFILT_READ / EVFILT_WRITE</text>
  <rect x="50" y="154" width="190" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="145" y="181" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">타이머</text>
  <text x="145" y="202" text-anchor="middle" font-size="10" fill="#8b949e">EVFILT_TIMER, ns 단위, fd 불필요</text>
  <rect x="50" y="236" width="190" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="145" y="263" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">시그널</text>
  <text x="145" y="284" text-anchor="middle" font-size="10" fill="#8b949e">EVFILT_SIGNAL, 핸들러 없이 동작</text>
  <rect x="50" y="318" width="190" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="145" y="345" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">파일시스템</text>
  <text x="145" y="366" text-anchor="middle" font-size="10" fill="#8b949e">EVFILT_VNODE, 쓰기·삭제·이름 변경</text>
  <rect x="50" y="400" width="190" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="145" y="427" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">프로세스</text>
  <text x="145" y="448" text-anchor="middle" font-size="10" fill="#8b949e">EVFILT_PROC, 종료 · fork · exec</text>

  <line x1="240" y1="105" x2="335" y2="220" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#kq-arr-gray)"/>
  <line x1="240" y1="187" x2="335" y2="250" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#kq-arr-gray)"/>
  <line x1="240" y1="269" x2="335" y2="280" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#kq-arr-gray)"/>
  <line x1="240" y1="351" x2="335" y2="310" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#kq-arr-gray)"/>
  <line x1="240" y1="433" x2="335" y2="340" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#kq-arr-gray)"/>
  <text x="287" y="168" text-anchor="middle" font-size="10" fill="#8b949e">필터로 등록</text>

  <rect x="340" y="180" width="250" height="220" rx="10" fill="#dcfce7" stroke="#16a34a" stroke-width="1.7"/>
  <text x="465" y="212" text-anchor="middle" font-size="13" font-weight="700" fill="#16a34a">커널: kqueue</text>
  <text x="465" y="234" text-anchor="middle" font-size="11" fill="#16a34a">stateful 이벤트 큐</text>
  <rect x="360" y="250" width="210" height="40" rx="6" fill="#ffffff" stroke="#16a34a" stroke-width="1"/>
  <text x="465" y="275" text-anchor="middle" font-size="10" fill="#2c3e50">등록된 필터 상태를 커널이 기억</text>
  <rect x="360" y="300" width="210" height="40" rx="6" fill="#ffffff" stroke="#16a34a" stroke-width="1"/>
  <text x="465" y="325" text-anchor="middle" font-size="10" fill="#2c3e50">조건이 참이 되면 큐에 적재</text>
  <rect x="360" y="350" width="210" height="36" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1"/>
  <text x="465" y="373" text-anchor="middle" font-size="10" font-weight="600" fill="#92400e">kevent() 호출마다 재등록 불필요</text>

  <rect x="690" y="230" width="170" height="120" rx="10" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="775" y="262" text-anchor="middle" font-size="13" font-weight="700" fill="#2563eb">애플리케이션</text>
  <text x="775" y="284" text-anchor="middle" font-size="10" fill="#2563eb">이벤트 루프</text>
  <text x="775" y="304" text-anchor="middle" font-size="10" fill="#2563eb">struct kevent 배열로 수신</text>

  <line x1="690" y1="260" x2="590" y2="260" stroke="#2563eb" stroke-width="1.5" marker-end="url(#kq-arr-blue)"/>
  <text x="640" y="252" text-anchor="middle" font-size="10" fill="#2563eb">changelist 등록/변경</text>
  <line x1="590" y1="320" x2="690" y2="320" stroke="#16a34a" stroke-width="1.5" marker-end="url(#kq-arr-green)"/>
  <text x="640" y="312" text-anchor="middle" font-size="10" fill="#16a34a">eventlist 반출</text>

  <rect x="200" y="494" width="500" height="44" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="450" y="513" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">kevent() 한 번의 호출 = changelist(변경) + eventlist(반출)</text>
  <text x="450" y="530" text-anchor="middle" font-size="10" fill="#92400e">epoll이 ctl과 wait로 분리한 것을 하나로 합칩니다</text>
</svg>

그림의 핵심은 화살표 두 개입니다. 등록과 반출이 같은 시스템 콜을 지나가고, 왼쪽의 이질적 소스들이 오른쪽에 도달할 때까지 자기 형태를 유지합니다. API가 이 구조를 그대로 코드로 옮깁니다.

## API와 struct kevent

헤더는 `<sys/event.h>`와 `<sys/time.h>`입니다. 함수는 셋뿐입니다.

```c
int kqueue(void);   // 커널 이벤트 큐 생성, fd 반환

int kevent(int kq,
    const struct kevent *changelist, int nchanges,  // 등록/변경
    struct kevent *eventlist, int nevents,          // 반출
    const struct timespec *timeout);                // NULL = 무한 대기

EV_SET(&kev, ident, filter, flags, fflags, data, udata);  // 초기화 매크로
```

모든 이벤트를 표현하는 것은 `struct kevent` 하나입니다. 여섯 필드의 역할을 표로 남깁니다.

| 필드 | 타입 | 역할 |
|---|---|---|
| `ident` | `uintptr_t` | 식별자. fd, 시그널 번호, PID, 임의 정수 id. **필터가 해석을 결정** |
| `filter` | `short` | 이벤트 종류. `EVFILT_READ`, `EVFILT_TIMER` 등 |
| `flags` | `u_short` | 동작 플래그. `EV_ADD`, `EV_CLEAR`, `EV_ONESHOT` + 반환 전용 `EV_EOF`, `EV_ERROR` |
| `fflags` | `u_int` | 필터별 세부 플래그. `NOTE_*` 계열 |
| `data` | `intptr_t` | 필터별 데이터. 읽기 가능 바이트 수, 타이머 주기, `EV_ERROR` 시 errno |
| `udata` | `void *` | 사용자 데이터. 반출 시 그대로 돌아와 매핑 테이블이 필요 없음 |

`ident`가 조심스러운 부분입니다. 소켓 필터에서는 fd였던 값이 시그널 필터에서는 시그널 번호가 되고, 프로세스 필터에서는 PID가 됩니다. **필터가 ident의 의미를 결정**한다는 규칙 하나로 여섯 필터가 한 구조체를 공유합니다.

## 최소 동작 코드: 생성부터 드레인까지

구조를 코드로 확인하겠습니다. 큐를 만들고, 읽기 필터 하나를 등록하고, 대기하고, 엣지 트리거라면 완전히 비우기까지. kqueue의 전체 리듬이 이 코드에 다 들어 있습니다.

```c
#include <sys/event.h>
#include <sys/time.h>

int kq = kqueue();                    // 1) 커널 이벤트 큐 생성. fd 하나 반환

int ssock = /* 감시할 소켓 */;
struct kevent chg;
EV_SET(&chg, ssock,                   // ident : 감시 대상
    EVFILT_READ,                      // filter: 읽기 준비
    EV_ADD | EV_CLEAR,                // flags : 등록 + 엣지 트리거
    0, 0, NULL);                      // fflags/data/udata 기본값

struct kevent ev;
int n = kevent(kq,
    &chg, 1,                          // changelist: 등록 1건을 큐에 반영
    &ev, 1,                           // eventlist: 준비된 이벤트 최대 1건 반출
    NULL);                            // timeout NULL = 무한 대기

if (n > 0 && ev.flags & EV_ERROR) {   // 2) 등록 실패는 호출 실패가 아니라
    errno = (int)ev.data;             //    eventlist 슬롯에 EV_ERROR로 보고
    /* 개별 항목 에러 처리 */
}

for (;;) {                            // 3) EV_CLEAR(엣지)이므로 EAGAIN까지 드레인
    char buf[1500];
    ssize_t r = recv((int)ev.ident, buf, sizeof buf, 0);
    if (r <= 0) break;                // r==0: EOF, EAGAIN: 드레인 완료
    /* 패킷 처리 */
}
close(kq);
```

코드에서 봐야 할 것이 셋입니다. 첫째, `kevent()` **한 번의 호출이 등록(changelist)과 대기(eventlist)를 동시에** 합니다. epoll에서 `epoll_ctl`과 `epoll_wait`로 나뉘는 자리가 여기선 하나입니다. 둘째, 등록이 실패해도 호출은 실패하지 않고 `EV_ERROR` 플래그와 `data`의 errno로 항목 단위 보고가 옵니다. 그래서 여러 변경을 한 번에 넣어도 안전합니다. 셋째, 엣지 트리거(`EV_CLEAR`)를 택했다면 드레인 루프는 선택이 아니라 의무입니다. 끝까지 비우지 않으면 다음 통보가 오지 않습니다.

## 필터 8종: 같은 큐에 사는 이질적 이벤트

필터가 실제로 무엇을 감시하는지 정리한 표입니다. 이 표가 kqueue의 활동 반경의 전부라고 봐도 됩니다.

| 필터 | 감시 대상 (ident) | 반출 의미 |
|---|---|---|
| `EVFILT_READ` | 소켓/파이프/fd, vnode | 읽기 가능. `data` = 읽을 수 있는 바이트 수. 연결 종료 시 `EV_EOF` |
| `EVFILT_WRITE` | 소켓/파이프/fd | 쓰기 가능. 백프레셔 해제 시점 감지 |
| `EVFILT_TIMER` | 임의 정수 id | 주기/일회 타이머. `NOTE_NSECONDS`까지 ns 단위, **별도 fd 불필요** |
| `EVFILT_SIGNAL` | 시그널 번호 | 시그널 발생. `data` = 적재 횟수. **핸들러 없이 동작** |
| `EVFILT_AIO` | `struct aiocb *` | POSIX AIO 완료 통보. 시그널/콜백 대신 큐로 회수 |
| `EVFILT_VNODE` | 파일 fd | 파일시스템 변경. `NOTE_WRITE`/`NOTE_DELETE`/`NOTE_RENAME` 등 |
| `EVFILT_PROC` | PID | 프로세스 상태 변화. `NOTE_EXIT`/`NOTE_FORK`/`NOTE_EXEC` |
| `EVFILT_USER` | 임의 정수 id | 사용자 정의 이벤트. 다른 스레드가 `NOTE_TRIGGER`로 주입 |

이 외에 `EVFILT_PROCDESC`, `EVFILT_FS`, `EVFILT_LIO`가 더 있지만 자주 쓰는 여덟 가지가 핵심입니다. epoll 세계에서 같은 일을 하려면 timerfd, signalfd, inotify, pidfd, eventfd를 각각 만들어 epoll에 등록해야 합니다. kqueue는 그 전부를 필터로 흡수합니다.

## 레벨이냐 엣지냐

트리거 모드는 epoll과 같은 대칭 구조입니다. **kqueue는 기본이 레벨 트리거**입니다. 조건이 참인 동안 계속 반출됩니다. `EV_CLEAR`를 붙여야 엣지 트리거가 되고, 반출 후 상태를 지우므로 응용이 `EAGAIN`까지 완전히 드레이닝해야 다음 통보를 받습니다.

선택 기준도 동일합니다. 안정성 우선이면 기본 레벨 트리거, 시스템 콜 수를 줄이고 싶으면 `EV_CLEAR`입니다. 엣지를 택했다면 read/recv 루프를 `EAGAIN`까지 도는 것을 잊으면 안 됩니다. 드레이닝을 빠뜨리면 다음 통보가 영영 오지 않는 교착이 만들어집니다.

동작 플래그 중 눈여겨볼 둘을 더 소개합니다. `EV_ONESHOT`은 한 번 반출 후 자동 삭제이고, `EV_DISPATCH`는 반출 직후 자동 비활성화입니다. 처리 완료 후 응용이 명시적으로 재활성화하는 패턴에 맞습니다.

## epoll과의 비교

같은 문제를 푸는 두 설계를 나란히 놓습니다.

| 항목 | kqueue (FreeBSD) | epoll (Linux) |
|---|---|---|
| 호출 구조 | **통합.** `kevent()` 한 호출이 changelist + eventlist 동시 처리 | **분리.** `epoll_ctl`(등록)과 `epoll_wait`(대기) 별도 |
| 통합 이벤트 타입 | timer·signal·AIO·vnode·proc·user가 **같은 큐의 필터** | fd 읽기/쓰기만. timerfd·signalfd·eventfd를 별도 fd로 등록 |
| 이벤트 표현 | `struct kevent`. ident+filter+fflags+data+udata로 구조화 | `epoll_data_t` 공용체. 응용이 매핑 테이블 직접 관리 |
| 타이머 | `EVFILT_TIMER` + `NOTE_NSECONDS`. fd 불필요 | `timerfd_create` 후 epoll에 등록 |
| 시그널 | `EVFILT_SIGNAL`. 핸들러 없이 큐에서 회수 | `signalfd`. 사전 마스킹 필요 |
| 파일시스템·프로세스 | `EVFILT_VNODE`, `EVFILT_PROC` 네이티브 | inotify, pidfd 별도 서브시스템 |
| 에러 보고 | 항목 단위 실패를 eventlist 슬롯에 `EV_ERROR` + errno로 보고 | `epoll_ctl`이 호출 단위로 실패 |

마지막 행이 실무에서 좋은 설계라 생각하는 부분입니다. changelist의 개별 등록이 실패해도 `kevent()` 호출 전체가 실패하지 않습니다. 해당 슬롯에 `EV_ERROR`와 errno가 실려 돌아오므로, **여러 변경을 한 번에 넣어도 안전**합니다. "한 호출에 다중 연산"이 가능한 근거입니다.

포팅 방향의 비대칭도 표에 담긴 결이 그대로 만듭니다. epoll에서 kqueue로 오는 쪽은 timerfd가 `EVFILT_TIMER`로, signalfd가 `EVFILT_SIGNAL`로, eventfd가 `EVFILT_USER`로 자연스럽게 축소 통합됩니다. 반대 방향은 vnode·proc·user에 대응이 없어 여러 메커니즘을 조합해야 합니다. 그래서 크로스플랫폼 추상화는 보통 이 계층을 감싸는 쪽에서 해결합니다.

## Rust에서 쓰려면

직접 시스템 콜을 감추고 싶으면 선택지가 둘입니다. **nix 0.31.3**은 `nix::sys::event` 모듈로 `kqueue()`와 `kevent()`의 안전 래퍼를 제공합니다(`features = ["event"]`, `x86_64-unknown-freebsd` 타깃 검증됨). **mio 1.2.2**는 FreeBSD에서 kqueue 백엔드, Linux에서 epoll 백엔드를 자동 선택하는 크로스플랫폼 런타임이라, tokio 기반이라면 별도 kqueue 코딩 없이 이 기능을 활용하게 됩니다.

한 가지 주의가 있습니다. libkqueue는 kqueue가 없는 플랫폼용 사용자 공간 포팅이라 FreeBSD에서 쓸 이유가 없습니다. 커널 네이티브 구현을 두고 에뮬레이션을 얹는 셈입니다.

## 어디를 더 볼 것인가

이 글을 읽고 직접 파고들 준비가 됐다면, 참조 순서는 이렇습니다.

1. **man kqueue(2)**: 시그니처와 필터의 최종 참조원. 이 글의 표도 전부 여기서 나왔습니다.
2. **/usr/include/sys/event.h**: `EVFILT_*`, `EV_*`, `NOTE_*` 상수의 실제 정의. 커널과 맺는 계약서 원본입니다.
3. **FreeBSD 소스 트리의 sys/kern/kern_event.c**: kqueue의 커널 구현. 필터별 동작이 궁금할 때 읽습니다.
4. **Rust 바인딩**: nix 0.31.3(`features = ["event"]`)의 안전 래퍼 또는 mio 1.2.2의 크로스플랫폼 추상화.

진입점이 전부 시스템 안에 있다는 점이 FreeBSD를 다루는 즐거움입니다. 매뉴얼과 헤더와 커널 소스가 서로 모순 없이 하나의 이야기를 이룹니다.

**시리즈 안내**

- 함께 읽기: [FreeBSD netmap으로 가는 길: ABI부터 VALE 스위칭의 숨은 규칙 3가지까지](/2026/08/24/FreeBSD-Netmap-VALE-Zero-Copy/). 같은 커널의 패킷 경로 이야기
