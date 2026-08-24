---
layout: post
title: "FreeBSD netmap으로 가는 길: ABI부터 VALE 스위칭의 숨은 규칙 3가지까지"
categories: [FreeBSD, Network]
description: "netmap VALE에서 보낸 패킷이 도착하지 않는 이유가 궁금하세요? ABI 실측 수치와 memid 고정 규칙 3가지를 정리했습니다."
keywords: [FreeBSD, netmap, VALE, zero-copy, ABI, RTP]
toc: true
toc_sticky: true
---

송신 쪽에서 패킷 8개를 링에 내려보냈는데, 수신 쪽에는 아무것도 도착하지 않았습니다. 에러 로그는 한 줄도 없었습니다. 이 글은 FreeBSD netmap(4)으로 제로카피 RTP 전송을 구현하면서, 어디에도 문서화되지 않은 VALE 스위칭 규칙 3가지를 실험으로 해독한 기록입니다.

이 글의 모든 커널 동작과 수치는 FreeBSD 15.1-RELEASE-p2(amd64) 전용 머신에서 2026-08-18에 직접 실행해 검증했습니다. netmap API는 14로 협상했고 커널도 14로 응답했으며, 같은 날 회귀 스위트는 573/573으로 통과했습니다.

## TL;DR

- netmap은 소켓 경로를 통째로 건너뜁니다. 시스템 콜이 **패킷당 1회에서 배치당 1회**로 줄고, 복사는 **0회**가 됩니다.
- FreeBSD는 이 프레임워크를 **GENERIC 커널에 기본 포함**합니다. 별도 모듈 없이 `/dev/netmap`이 있습니다.
- 다루는 포트는 다섯 종류(물리 NIC · 호스트 · VALE · pipe · monitor)가 **하나의 같은 API**로 접근됩니다. man 페이지 기준 10G NIC에서 14.88 Mpps를 코어 1개 미만으로 처리합니다.
- 최고 성능의 전제는 **네이티브(netmap-aware) 드라이버**입니다. 미지원 NIC도 에뮬레이션으로 동작하지만 bpf 대비 3~5배 수준으로 내려갑니다.
- ABI는 헤더 없이 숫자로 검증했습니다. `nmreq` **60바이트**, `netmap_ring` 헤더 **256바이트**(필드 합 200에 64정렬 패딩), ioctl 번호 **4개**를 스냅샷 테스트로 못 박았습니다.
- VALE 규칙 1: 스위치의 **모든 포트를 첫 포트의 memid(nr_arg2)에 고정**해야 패킷이 움직입니다. 어긋나면 패킷이 조용히 사라집니다.
- VALE 규칙 2와 3: 새 수신 링은 **프라이밍**(head=cur=tail 후 rxsync 1회)이 필요하고, 송신 가용 슬롯은 **head와 tail의 차**로 계산하며 `cur`가 `head`를 따라가야 합니다.
- 최종 결과: VALE 루프백에서 **8/8 패킷 비트 정합**을 확인했습니다.

숫자가 이렇게 구체적인 이유는 전부 직접 쟀기 때문입니다. 무엇을 왜 버렸는지부터 보겠습니다.

## 배경: 왜 소켓을 버리고 netmap인가

실시간 마감 안에 RTP 패킷을 밀어내야 하는 서비스를 FreeBSD 위에 올리는 중입니다. 전송 경로의 세금이 곧 지연 예산이라, 커널이 제공하는 바이패스 경로를 끝까지 파고들게 됐습니다.

소켓 경로에는 세금이 두 가지 있습니다. `send(2)`와 `recv(2)`는 호출마다 시스템 콜 경계를 횡단하고, 페이로드를 사용자 버퍼와 커널 mbuf 사이에서 복사합니다.

netmap(4)은 FreeBSD의 커널 바이패스 패킷 I/O 프레임워크입니다. NIC나 가상 포트를 TX와 RX **링**, 각 링의 고정 크기 **슬롯**이 가리키는 **버퍼 풀**, 그리고 이 전부를 사용자 공간에 직접 매핑하는 `mmap` 영역으로 노출합니다.

사용자가 다음 여유 TX 슬롯의 버퍼에 패킷을 쓰고 커서 두 개를 옮긴 뒤 `NIOCTXSYNC`를 한 번 부르면, 커널이나 NIC의 DMA 엔진이 그 버퍼에서 바로 전송합니다. 수신도 대칭으로 `NIOCRXSYNC` 뒤에 새 패킷이 이미 사용자 공간에 보입니다.

대가는 소켓 계층이 해주던 링 회계, 버퍼 수명, 스위치 설정이 전부 우리 책임으로 넘어온다는 것입니다. 이 대가를 치르는 과정이 이 글의 나머지입니다.

## netmap은 FreeBSD 어디에 사는가

구조를 알기 전에 위치부터 못 박겠습니다. netmap은 FreeBSD 커널의 네트워크 스택 **옆에 놓인 또 하나의 경로**입니다.

평소의 패킷 경로를 먼저 보면, 애플리케이션이 소켓 API로 보낸 패킷은 소켓 계층을 지나 프로토콜 스택(TCP/UDP/IP)에서 처리되고, mbuf로 할당·복사된 뒤 드라이버를 거쳐 NIC에 닿합니다. 매 단계가 시스템 콜과 복사의 세금입니다.

netmap은 이 경로를 우회합니다. `/dev/netmap`을 열어 링을 mmap으로 직접 얻고, **netmap을 인식하는 드라이버 훅**을 통해 NIC의 DMA와 만납니다. 아래 그림에서 두 경로를 나란히 보겠습니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 620" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="FreeBSD 네트워크 스택에서 netmap의 위치: 기존 소켓 경로와 netmap 우회 경로의 비교">
  <defs>
    <marker id="nmp-arr-gray" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="nmp-arr-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="440" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">FreeBSD 네트워크 스택과 netmap의 위치</text>

  <rect x="30" y="48" width="390" height="30" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1"/>
  <text x="225" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">기존 경로: 소켓</text>
  <rect x="460" y="48" width="390" height="30" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1"/>
  <text x="655" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">우회 경로: netmap</text>

  <rect x="55" y="96" width="340" height="54" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="225" y="118" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">애플리케이션</text>
  <text x="225" y="137" text-anchor="middle" font-size="10" fill="#8b949e">send(2) / recv(2), 패킷당 시스템 콜</text>

  <rect x="55" y="170" width="340" height="54" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="225" y="192" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">소켓 계층 + 프로토콜 스택</text>
  <text x="225" y="211" text-anchor="middle" font-size="10" fill="#8b949e">TCP/UDP/IP 처리, mbuf 할당과 복사</text>

  <rect x="55" y="244" width="340" height="54" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="225" y="266" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">드라이버 (em, ix, cxgbe ...)</text>
  <text x="225" y="285" text-anchor="middle" font-size="10" fill="#8b949e">커널 큐 → NIC DMA</text>

  <rect x="55" y="318" width="340" height="50" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.3"/>
  <text x="225" y="339" text-anchor="middle" font-size="12" font-weight="700" fill="#2563eb">NIC / 하드웨어</text>
  <text x="225" y="357" text-anchor="middle" font-size="10" fill="#2563eb">물리 송수신</text>

  <line x1="225" y1="150" x2="225" y2="164" stroke="#666666" stroke-width="1.4" marker-end="url(#nmp-arr-gray)"/>
  <line x1="225" y1="224" x2="225" y2="238" stroke="#666666" stroke-width="1.4" marker-end="url(#nmp-arr-gray)"/>
  <line x1="225" y1="298" x2="225" y2="312" stroke="#666666" stroke-width="1.4" marker-end="url(#nmp-arr-gray)"/>

  <rect x="485" y="96" width="340" height="54" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="655" y="118" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">애플리케이션</text>
  <text x="655" y="137" text-anchor="middle" font-size="10" fill="#16a34a">링 버퍼에 직접 읽고 쓰기, 복사 0</text>

  <rect x="485" y="170" width="340" height="54" rx="8" fill="#ede9fe" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="655" y="192" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">mmap 공유 링 (netmap 코어)</text>
  <text x="655" y="211" text-anchor="middle" font-size="10" fill="#7c3aed">sync ioctl은 배치당 1회, VALE 스위치 내장</text>

  <rect x="485" y="244" width="340" height="54" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="655" y="266" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">드라이버 netmap 훅</text>
  <text x="655" y="285" text-anchor="middle" font-size="10" fill="#16a34a">#ifdef DEV_NETMAP 으로 컴파일된 경로</text>

  <rect x="485" y="318" width="340" height="50" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.3"/>
  <text x="655" y="339" text-anchor="middle" font-size="12" font-weight="700" fill="#2563eb">NIC / 하드웨어</text>
  <text x="655" y="357" text-anchor="middle" font-size="10" fill="#2563eb">같은 하드웨어, 다른 진입로</text>

  <line x1="655" y1="150" x2="655" y2="164" stroke="#16a34a" stroke-width="1.6" marker-end="url(#nmp-arr-green)"/>
  <line x1="655" y1="224" x2="655" y2="238" stroke="#16a34a" stroke-width="1.6" marker-end="url(#nmp-arr-green)"/>
  <line x1="655" y1="298" x2="655" y2="312" stroke="#16a34a" stroke-width="1.6" marker-end="url(#nmp-arr-green)"/>

  <rect x="55" y="396" width="770" height="76" rx="10" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="440" y="424" text-anchor="middle" font-size="13" font-weight="700" fill="#92400e">netmap이 다루는 다섯 포트: 하나의 같은 API</text>
  <text x="440" y="446" text-anchor="middle" font-size="11" fill="#2c3e50">물리 NIC 포트 · 호스트 포트(호스트 스택 주입/채취) · VALE 포트(스위치) · netmap pipe(프로세스 간) · monitor(캡처)</text>
  <text x="440" y="463" text-anchor="middle" font-size="10" fill="#92400e">man netmap(4) 기준: 10G NIC 14.88 Mpps를 코어 1개 미만으로, pipe는 100 Mpps 이상</text>

  <text x="225" y="508" text-anchor="middle" font-size="11" font-weight="600" fill="#666666">경유 계층마다 시스템 콜과 복사</text>
  <text x="655" y="508" text-anchor="middle" font-size="11" font-weight="600" fill="#16a34a">시스템 콜 배치당 1회, 복사 0</text>
  <text x="440" y="536" text-anchor="middle" font-size="10" fill="#8b949e">netmap은 GENERIC 커널에 기본 포함입니다(device netmap). /dev/netmap이 곧 진입점입니다.</text>
</svg>

그림에서 볼 것이 세 가지입니다. 첫째, netmap은 프로토콜 스택을 **우회**할 뿐 드라이버와 NIC를 대체하지 않습니다. 둘째, 우회의 접점은 드라이버 안의 netmap 훅(`#ifdef DEV_NETMAP` 블록)이라서, 같은 하드웨어에 두 경로가 공존합니다. 셋째, netmap 코어에는 VALE 스위치와 pipe가 들어 있어서 하드웨어 없이도 가상 토폴로지를 만들 수 있습니다.

### 다섯 포트, 하나의 API

netmap의 설계에서 좋은 부분은 다섯 종류의 포트가 전부 같은 링 API로 다루어진다는 점입니다. 위치로 이해하면 이렇습니다.

| 포트 | 역할 | man 페이지 성능 기준 |
|---|---|---|
| 물리 NIC 포트 | 인터페이스의 개별 큐에 직접 접근 | 10G: 14.88 Mpps @ 코어 1개 미만, 40G: 35~40 Mpps |
| 호스트 포트 | 호스트 스택으로 패킷 주입/채취 | 스택과의 연결 다리 |
| VALE 포트 | 인커널 소프트웨어 스위치에 연결 | 코어당 약 20 Mpps |
| netmap pipe | 프로세스 간 제로카피 채널 (크로스오버 연결) | 100 Mpps 이상 |
| netmap monitor | bpf(4) 같은 트래픽 캡처/미러링 | 진단 · 로깅용 |

이 글의 루프백 실험은 전부 VALE 포트에서 일어납니다. 하드웨어가 없어도 스위치와 포트를 만들 수 있기 때문입니다. 위치를 알았으니, 이제 이 경로에서 실제로 커널과 대화하는 프로토콜을 봅니다.

아래 그림은 이 구조를 세 계층으로 펼친 것입니다. 사용자 공간과 커널이 mmap 영역 하나를 사이에 두고 만납니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 548" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="netmap 구조 다이어그램: 사용자 공간과 커널이 mmap 공유 영역의 TX 링, 버퍼 풀, RX 링을 사이에 두고 만나는 3계층 구조">
  <defs>
    <marker id="nm1-arrow-blue" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#2563eb"/>
    </marker>
    <marker id="nm1-arrow-purple" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#7c3aed"/>
    </marker>
  </defs>
  <text x="430" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">netmap: mmap 공유 영역 하나로 이어지는 사용자 공간과 커널</text>
  <rect x="80" y="48" width="700" height="72" rx="10" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="430" y="74" text-anchor="middle" font-size="13" font-weight="700" fill="#2563eb">사용자 공간: 애플리케이션 워커</text>
  <text x="430" y="96" text-anchor="middle" font-size="11" fill="#2563eb">send_rtp / recv_rtp, RTP 인코딩과 파싱</text>
  <line x1="250" y1="120" x2="250" y2="172" stroke="#2563eb" stroke-width="1.5" marker-end="url(#nm1-arrow-blue)"/>
  <line x1="610" y1="172" x2="610" y2="120" stroke="#2563eb" stroke-width="1.5" marker-end="url(#nm1-arrow-blue)"/>
  <text x="430" y="140" text-anchor="middle" font-size="11" fill="#666">mmap MAP_SHARED</text>
  <text x="430" y="157" text-anchor="middle" font-size="11" fill="#666">슬롯 버퍼에 직접 읽고 쓰기, 복사 0</text>
  <rect x="80" y="176" width="700" height="140" rx="10" fill="#ede9fe" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="430" y="200" text-anchor="middle" font-size="13" font-weight="700" fill="#7c3aed">커널과 사용자 공간이 공유하는 링 영역</text>
  <rect x="110" y="216" width="200" height="58" rx="8" fill="#ffffff" stroke="#7c3aed" stroke-width="1.2"/>
  <text x="210" y="239" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">TX 링</text>
  <text x="210" y="258" text-anchor="middle" font-size="10" fill="#666">헤더 256B + 슬롯 배열</text>
  <rect x="330" y="216" width="200" height="58" rx="8" fill="#ffffff" stroke="#7c3aed" stroke-width="1.2"/>
  <text x="430" y="239" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">버퍼 풀</text>
  <text x="430" y="258" text-anchor="middle" font-size="10" fill="#666">고정 크기 버퍼, 슬롯이 가리킴</text>
  <rect x="550" y="216" width="200" height="58" rx="8" fill="#ffffff" stroke="#7c3aed" stroke-width="1.2"/>
  <text x="650" y="239" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">RX 링</text>
  <text x="650" y="258" text-anchor="middle" font-size="10" fill="#666">헤더 256B + 슬롯 배열</text>
  <text x="430" y="302" text-anchor="middle" font-size="10" fill="#7c3aed">링마다 슬롯 512개(vmx0) 또는 1024개(VALE)</text>
  <line x1="250" y1="316" x2="250" y2="368" stroke="#7c3aed" stroke-width="1.5" marker-end="url(#nm1-arrow-purple)"/>
  <line x1="610" y1="368" x2="610" y2="316" stroke="#7c3aed" stroke-width="1.5" marker-end="url(#nm1-arrow-purple)"/>
  <text x="430" y="336" text-anchor="middle" font-size="11" fill="#666">NIOCTXSYNC / NIOCRXSYNC</text>
  <text x="430" y="353" text-anchor="middle" font-size="11" fill="#666">sync ioctl, 시스템 콜은 배치당 1회</text>
  <rect x="80" y="372" width="700" height="108" rx="10" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="430" y="396" text-anchor="middle" font-size="13" font-weight="700" fill="#16a34a">커널 / 하드웨어</text>
  <rect x="110" y="412" width="280" height="52" rx="8" fill="#ffffff" stroke="#16a34a" stroke-width="1.2"/>
  <text x="250" y="433" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">VALE 소프트웨어 스위치</text>
  <text x="250" y="451" text-anchor="middle" font-size="10" fill="#666">가상 포트끼리 브리지</text>
  <rect x="470" y="412" width="280" height="52" rx="8" fill="#ffffff" stroke="#16a34a" stroke-width="1.2"/>
  <text x="610" y="433" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">NIC 드라이버 + DMA</text>
  <text x="610" y="451" text-anchor="middle" font-size="10" fill="#666">버퍼에서 하드웨어가 직접 전송</text>
  <rect x="170" y="496" width="520" height="36" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="430" y="519" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">시스템 콜: 패킷당 1회에서 배치당 1회로, 복사 0</text>
</svg>

그림처럼 커널과 소통하는 유일한 수단은 sync ioctl이고 그 단위가 배치입니다. 구조는 단순하지만, 실제 통신은 fd 하나가 처리하는 작은 프로토콜 위에서 벌어집니다.

## 와이어 프로토콜: fd 하나 위의 7단계

사용자 공간에서 보면 netmap은 `/dev/netmap` fd 하나 위의 아주 작은 프로토콜입니다. 등록부터 해제까지 일곱 단계로 끝납니다.

```c
// fd 하나 위에서 벌어지는 netmap 와이어 프로토콜 (의사코드)
fd = open("/dev/netmap", O_RDWR);        // 1. 모든 포트 등록이 지나는 단일 fd
ioctl(fd, NIOCGINFO, &req);              // 2. 능력 탐색: API 버전과 링/슬롯 지오메트리 (등록 아님)
ioctl(fd, NIOCREGIF, &req);              // 3. 포트 등록: nr_offset, nr_memsize, nr_arg2(memid) 반환
region = mmap(NULL, req.nr_memsize,      // 4. 같은 fd에 mmap: 커널과 공유하는 링 영역
              PROT_READ | PROT_WRITE, MAP_SHARED, fd);
nif = region + req.nr_offset;            // 5. netmap_if에서 ring_ofs[]를 따라 링 헤더와 슬롯 순회
ioctl(fd, NIOCTXSYNC, 0);                // 6. 송신 배치 인계, 수신 회수는 NIOCRXSYNC (인자는 0)
close(fd);                               // 7. fd 닫기 = 등록 해제, 매핑도 함께 해제
```

각 단계에는 계약이 붙어 있습니다. `NIOCGINFO`는 아무것도 등록하지 않고 지오메트리와 커널의 API 버전만 알려주고, `NIOCREGIF`는 `netmap_if` 오프셋과 공유 영역 크기, 할당자 id인 memid를 돌려줍니다. `head`, `cur`, `tail` 같은 공유 단어는 커널이 sync 사이에 동시에 쓰므로 volatile으로 접근하고, sync ioctl의 세 번째 인자는 C 호출자와 같은 0을 넘깁니다.

여기까지는 문서화된 부분입니다. 문제는 이 프로토콜이 기대하는 구조체 크기와 필드 오프셋을 담은 헤더가 개발 머신에 없다는 점이었습니다.

## ABI 라이브 검증: 문서 대신 숫자

netmap의 타입 정의는 `/usr/include/net/netmap.h`에 있습니다. FreeBSD 15.1 헤더의 모든 타입을 의존성 없는 `repr(C)` 선언으로 옮기고 크기와 오프셋을 스냅샷 테스트로 못 박았습니다. 테스트는 어떤 호스트에서나 돌아가므로 상수가 조용히 드리프트할 여지가 없고, 나머지는 전부 전용 머신에서 런타임으로 입증했습니다.

### nmreq: 60바이트의 요청 구조체

`ioctl`에 넘기는 `struct nmreq`는 60바이트, 정렬 4입니다. 오프셋 전체를 표로 남깁니다. 이 표 하나가 커널과의 첫 대화의 전부입니다.

| 오프셋 | 필드 | 타입 | 역할 |
|---:|---|---|---|
| 0 | `nr_name` | `[u8; 16]` | 입력: 포트 이름(`"vmx0"`, `"vale60:w"`) |
| 16 | `nr_version` | `u32` | 입력: 요청 API, 출력: 커널 버전 |
| 20 | `nr_offset` | `u32` | 출력: `netmap_if`의 영역 내 오프셋 |
| 24 | `nr_memsize` | `u32` | 출력: 공유 영역 크기(바이트) |
| 28 | `nr_tx_slots` | `u32` | 출력: TX 링당 슬롯 수 |
| 32 | `nr_rx_slots` | `u32` | 출력: RX 링당 슬롯 수 |
| 36 | `nr_tx_rings` | `u16` | 출력: TX 링 수 |
| 38 | `nr_rx_rings` | `u16` | 출력: RX 링 수 |
| 40 | `nr_ringid` | `u16` | 입력: NIOCREGIF 링 선택 |
| 42 | `nr_cmd` | `u16` | 입력: 브리지/등록 하위 명령 |
| 44 | `nr_arg1` | `u16` | 입력: 예비 |
| 46 | `nr_arg2` | `u16` | 입출력: **메모리 할당자 id(memid)** |
| 48 | `nr_arg3` | `u32` | 입력: 추가 버퍼 요청 |
| 52 | `nr_flags` | `u32` | 입력: `NR_REG_*` 등록 플래그 |
| 56 | `nr_spare2` | `[u32; 1]` | 예약 |

슬롯 기술자 `netmap_slot`은 16바이트로 `buf_idx`, `len`, `flags`, 예약된 `ptr` 네 필드입니다. `head`와 `tail` 회계의 대상이 바로 이 배열입니다.

포트 기술자 `netmap_if`는 고정부 56바이트 뒤 오프셋 56부터 `ring_ofs[]` 테이블이 따라옵니다. 순서는 NIC TX 전부, 호스트 TX, NIC RX, 호스트 RX라서 RX 0의 인덱스는 `tx_rings + host_tx_rings`입니다. 실측은 `vmx0`가 TX 4개와 RX 4개 링에 슬롯 512개, 임시 VALE 포트는 링 1쌍에 슬롯 1024개였습니다.

### netmap_ring: 헤더가 곧 256바이트

링 헤더 `struct netmap_ring`은 amd64에서 256바이트입니다. 필드를 단순히 더하면 200인데, `sem` 멤버가 64바이트 정렬(`NM_CACHE_ALIGN`)을 요구해서 256으로 패딩됩니다. 이 크기는 곧 `slot[0]`의 오프셋이기도 해서, 하나만 틀려도 모든 슬롯 접근이 쓰레기를 읽습니다.

| 오프셋 | 필드 | 타입 | 역할 |
|---:|---|---|---|
| 0 | `buf_ofs` | `i64` | 버퍼 0의 링 시작 기준 오프셋 |
| 8 | `num_slots` | `u32` | 슬롯 수 |
| 12 | `nr_buf_size` | `u32` | 버퍼 하나의 크기 |
| 16 | `ringid` | `u16` | 링 식별 |
| 18 | `dir` | `u16` | 명목상 0=TX, 1=RX. 그러나 VALE에서는 뒤집힘 |
| 20 | `head` | `u32` | 커널이 읽는 해제 지점, 첫 여유 슬롯 |
| 24 | `cur` | `u32` | 사용자 커서, head와 tail 사이 |
| 28 | `tail` | `u32` | 커널이 쓰는 워터마크 |
| 32 | `flags` | `u32` | 플래그 |
| 40 | `ts` | `timeval` | 타임스탬프, 64비트에서 i64 두 개 |
| 56 | `offset_mask` | `u64` | 오프셋 마스크 |
| 64 | `buf_align` | `u64` | 버퍼 정렬 |
| 72 | 패딩 | 56B | `sem`이 오프셋 128에 64정렬되도록 |
| 128 | `sem[128]` | 바이트 배열 | 커널 예약 |

### ioctl 번호 4개의 파생

FreeBSD는 ioctl 번호 인코딩에서 Linux와 결이 다릅니다. 방향 비트를 상위 니블에 그대로 두고, sync 두 개는 `_IO`로 선언되어 크기 비트가 아예 없습니다. 크기를 실어 보내면 커널이 전체 명령어로 스위치하다 `ENOTTY`를 돌려줍니다.

```c
// FreeBSD <sys/ioccom.h> 파생 규칙과 netmap ioctl 4개
// _IOWR(g, n, t) = IOC_INOUT | ((sizeof(t) & 0x1fff) << 16) | (g << 8) | n
// _IO(g, n)      = IOC_VOID  | (g << 8) | n          // 인자 무시, 크기 비트 없음
// IOC_INOUT = 0xc0000000, IOC_VOID = 0x20000000, group 'i' = 0x69

NIOCGINFO  = _IOWR('i', 145, struct nmreq)  // 0xC03C6991 = INOUT | 60<<16 | 'i'<<8 | 145
NIOCREGIF  = _IOWR('i', 146, struct nmreq)  // 0xC03C6992
NIOCTXSYNC = _IO('i', 148)                  // 0x20006994 (void: 크기 비트 없음)
NIOCRXSYNC = _IO('i', 149)                  // 0x20006995
```

구현에서는 상수를 `size_of::<Nmreq>()`에서 파생해 구조체와 번호가 어긋날 수 없게 했습니다. 버전은 API 14(수용 범위 11 이상 14 이하)로 요청했고, `nr_version`을 덮어쓴 커널은 14로 응답했습니다.

ABI를 숫자로 못 박았으니 이제 진짜 문제입니다. 패킷을 흘려보냈는데 아무것도 도착하지 않았습니다.

## VALE와 숨은 규칙 3가지

VALE는 netmap에 내장된 커널 안 소프트웨어 스위치입니다. `valeN:PPP` 규칙의 임시 포트를 NIOCREGIF로 즉석에서 만들고 fd를 닫으면 사라져서, 하드웨어 없이 한 머신에서 루프백 위상을 만들기에 딱이었습니다.

스위칭 규칙 세 가지는 매뉴얼이나 헤더 주석 어디에도 없었습니다. 그래서 파라미터를 한 번에 하나씩만 바꾼 작은 C 프로그램 행렬을 돌려 커널의 답을 읽었습니다. 각 규칙을 실패 증상, 원인, 수정 순서로 정리합니다.

### 규칙 1: memid 고정, 0/8의 범인

**실패 증상**: 송신자가 패킷 8개를 txsync했는데, 수신자가 아무리 rxsync해도 전달은 0이었습니다. 에러는 어디에도 없었습니다.

**원인**: 커널이 독립 등록된 포트마다 서로 다른 메모리 할당자를 배정합니다. 실측으로 수신자는 memid 2, 송신자는 memid 3을 받았습니다. VALE는 같은 할당자를 공유하는 포트끼리만 스위칭하므로 다르면 패킷이 조용히 증발합니다.

**수정**: 모든 포트를 첫 포트의 `nr_arg2`에 고정합니다. 수신자를 먼저 열어 스위치와 memid를 확보한 뒤 나머지를 그 값으로 핀합니다.

```c
// 규칙 1 수정: 첫 포트의 memid(nr_arg2)를 이후 모든 포트에 핀
ioctl(fd_rx, NIOCREGIF, &req_rx);     // 수신자 먼저 등록, 스위치가 여기서 생성됨
first_memid = req_rx.nr_arg2;         // 커널이 배정한 할당자 id
req_tx.nr_arg2 = first_memid;         // 송신자 요청에 같은 memid를 미리 채워서
ioctl(fd_tx, NIOCREGIF, &req_tx);     // 등록, 이제 두 포트는 같은 할당자
```

> **VALE에서 패킷이 조용히 사라지면 먼저 memid를 의심하세요.** 두 포트의
> `nr_arg2`를 출력해 보면 독립 등록이면 값이 다릅니다. 값이 다르면 스위치가
> 아무것도 전달하지 않습니다.

아래 시퀀스 다이어그램이 규칙 1 적용 전과 후를 대비합니다. 전에는 패킷이 스위치에서 증발하고, 후에는 8개 전부 도착합니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 600" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="VALE 규칙 1 시퀀스 다이어그램: memid 불일치 때 패킷이 스위치에서 소멸하는 실패 흐름과 첫 포트 memid 고정 후 8개 전부 전달되는 성공 흐름의 대비">
  <defs>
    <marker id="nm2-arrow-blue" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#2563eb"/>
    </marker>
    <marker id="nm2-arrow-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
    <marker id="nm2-arrow-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="430" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">VALE 규칙 1: memid 불일치(패킷 소멸) vs memid 고정(전달)</text>
  <rect x="55" y="42" width="150" height="50" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="130" y="63" text-anchor="middle" font-size="13" font-weight="700" fill="#2563eb">송신자</text>
  <text x="130" y="80" text-anchor="middle" font-size="10" fill="#2563eb">vale60:w</text>
  <rect x="355" y="42" width="150" height="50" rx="8" fill="#ede9fe" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="430" y="63" text-anchor="middle" font-size="13" font-weight="700" fill="#7c3aed">VALE 스위치</text>
  <text x="430" y="80" text-anchor="middle" font-size="10" fill="#7c3aed">vale60 (커널)</text>
  <rect x="655" y="42" width="150" height="50" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="730" y="63" text-anchor="middle" font-size="13" font-weight="700" fill="#16a34a">수신자</text>
  <text x="730" y="80" text-anchor="middle" font-size="10" fill="#16a34a">vale60:r</text>
  <line x1="130" y1="92" x2="130" y2="535" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="430" y1="92" x2="430" y2="535" stroke="#ddd" stroke-dasharray="4,4"/>
  <line x1="730" y1="92" x2="730" y2="535" stroke="#ddd" stroke-dasharray="4,4"/>
  <text x="430" y="118" text-anchor="middle" font-size="11" font-weight="700" fill="#dc2626">규칙 1 적용 전: memid 불일치</text>
  <circle cx="130" cy="145" r="12" fill="#2563eb"/>
  <text x="130" y="149" text-anchor="middle" font-size="11" font-weight="700" fill="white">1</text>
  <line x1="145" y1="145" x2="415" y2="145" stroke="#2563eb" stroke-width="1.5" marker-end="url(#nm2-arrow-blue)"/>
  <text x="280" y="139" text-anchor="middle" font-size="10" fill="#2c3e50">패킷 8개 txsync (memid 3)</text>
  <circle cx="430" cy="200" r="12" fill="#dc2626"/>
  <text x="430" y="204" text-anchor="middle" font-size="11" font-weight="700" fill="white">2</text>
  <rect x="460" y="184" width="250" height="32" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.5"/>
  <text x="585" y="204" text-anchor="middle" font-size="11" fill="#2c3e50">memid 불일치(3 ≠ 2): 다른 할당자</text>
  <circle cx="430" cy="255" r="12" fill="#dc2626"/>
  <text x="430" y="259" text-anchor="middle" font-size="11" font-weight="700" fill="white">3</text>
  <line x1="445" y1="255" x2="640" y2="255" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#nm2-arrow-red)"/>
  <text x="542" y="249" text-anchor="middle" font-size="10" fill="#dc2626">전달 없음, 에러 없음</text>
  <text x="662" y="261" text-anchor="middle" font-size="16" font-weight="700" fill="#dc2626">✕</text>
  <line x1="60" y1="292" x2="800" y2="292" stroke="#fbbf24" stroke-width="1.5" stroke-dasharray="6,4"/>
  <text x="430" y="312" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">규칙 1 적용: 모든 포트를 첫 포트의 memid에 고정</text>
  <circle cx="730" cy="345" r="12" fill="#16a34a"/>
  <text x="730" y="349" text-anchor="middle" font-size="11" font-weight="700" fill="white">4</text>
  <rect x="445" y="329" width="240" height="32" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="565" y="349" text-anchor="middle" font-size="11" fill="#2c3e50">수신자 먼저 open, memid 2 배정</text>
  <circle cx="130" cy="400" r="12" fill="#2563eb"/>
  <text x="130" y="404" text-anchor="middle" font-size="11" font-weight="700" fill="white">5</text>
  <rect x="160" y="384" width="250" height="32" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="285" y="404" text-anchor="middle" font-size="11" fill="#2c3e50">송신자 open: nr_arg2에 memid 2 지정</text>
  <circle cx="130" cy="455" r="12" fill="#2563eb"/>
  <text x="130" y="459" text-anchor="middle" font-size="11" font-weight="700" fill="white">6</text>
  <line x1="145" y1="455" x2="415" y2="455" stroke="#2563eb" stroke-width="1.5" marker-end="url(#nm2-arrow-blue)"/>
  <text x="280" y="449" text-anchor="middle" font-size="10" fill="#2c3e50">패킷 8개 txsync (memid 2)</text>
  <circle cx="430" cy="510" r="12" fill="#16a34a"/>
  <text x="430" y="514" text-anchor="middle" font-size="11" font-weight="700" fill="white">7</text>
  <line x1="445" y1="510" x2="715" y2="510" stroke="#16a34a" stroke-width="1.5" marker-end="url(#nm2-arrow-green)"/>
  <text x="580" y="504" text-anchor="middle" font-size="10" fill="#2c3e50">같은 할당자: 8/8 전달, 비트 정합</text>
  <rect x="145" y="540" width="570" height="48" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="430" y="559" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">첫 포트(수신자)의 nr_arg2 = memid를 모든 포트에 핀</text>
  <text x="430" y="577" text-anchor="middle" font-size="10" fill="#92400e">이 규칙 하나로 0/8이 8/8로 바뀝니다</text>
</svg>

규칙 1로 패킷은 움직이기 시작했습니다. 그런데 이번에는 트래픽이 없는데도 패킷이 도착하는 기이한 상태가 나타났습니다.

### 규칙 2: 새 링은 프라이밍이 필요하다

**실패 증상**: 방금 연 딜리버리 링을 폴링하면 패킷이 계속 도착했습니다. 길이도 페이로드도 쓰레기였고, 트래픽을 보낸 적이 없는데도 그랬습니다.

**원인**: 새 VALE 수신 링의 슬롯 기술자는 커널이 회수를 인식하기 전까지 이전 매핑의 찌꺼기를 담고 있었습니다. 슬롯 1024개짜리 링에서 새 포트의 `tail`은 `num_slots - 1`에서 시작해 그 쓰레기를 가리키고, 인식 전의 sync는 이를 수신으로 오독합니다.

**수정**: 오픈 직후 단 한 번 프라이밍합니다. 커서 셋을 `tail`로 정렬하고 rxsync를 호출하면 커널이 상태를 인식하고 회계를 시작합니다.

```c
// 규칙 2 수정: open 직후 딱 한 번, 새 링을 프라이밍
ring->head = ring->cur = ring->tail;   // 커서 셋을 tail로 정렬
ioctl(fd, NIOCRXSYNC, 0);              // 커널이 새 상태를 인식하고 회계 시작
```

프라이밍으로 가짜 수신은 사라졌습니다. 마지막 문제는 수치 자체가 거짓말을 하던 경우입니다.

### 규칙 3: TX 슬롯 회계와 cur 규칙

**실패 증상**: 초기 실험이 4/8 전달을 보고했습니다. 스위치가 패킷 절반을 버리는 것처럼 보였습니다.

**원인**: 스위치가 아니라 우리 회계였습니다. `NIOCTXSYNC` 직후의 `tail`은 커널이 소비한 마지막 슬롯의 다음이라, `head = 1, tail = 0`은 링이 가득 찬 것이 아니라 1개가 비행 중이라는 뜻입니다. 테스트가 이를 오독해 조기에 송신을 멈춘 것이 4/8의 정체였습니다.

가용 슬롯 수는 `num_slots - ((head - tail) mod num_slots)`로 계산합니다. `head == tail`은 문맥에 따라 갈립니다. 사용 중인 링에서는 진짜 가득 찬 상태이고 새 링(`head = tail = 0`)은 빈 것이라, 이 상태가 나오면 sync하고 다시 보는 쪽으로 자동 교정했습니다.

**동반 규칙**: `cur`는 커널의 깨우기 지점이라 반드시 `head`를 따라가야 합니다. 패킷 8개를 쌓아두고 `cur`를 옮기지 않으니 `tail`이 1023에 얼어붙고 커널은 아무것도 소비하지 않았습니다. `head`를 옮길 때마다 `cur`까지 함께 옮기면 링이 완전히 비워집니다.

```c
// 규칙 3 수정: 가용 슬롯 회계와 커서 전진
free = num_slots - ((head - tail) % num_slots);  // tail은 소비한 마지막 다음 슬롯
slot[head].len = n;
head = cur = head + 1;                           // cur가 head를 따라가야 커널이 깨어남
```

회계를 고치고 나니 `dir` 필드마저 믿을 수 없다는 사실이 남았습니다.

### 링 역할 뒤집힘: dir 필드를 믿지 마세요

`ring_ofs[]` 순서상 VALE 포트의 센드 링은 `ring_ofs[0]`에, 딜리버리 링은 `tx_rings + host_tx_rings` 인덱스에 있습니다. 그런데 헤더의 `dir` 필드는 명목 규칙과 반대로 찍힙니다.

| 역할 | 위치 | dir 필드 | 방향 |
|---|---|---|---|
| 센드 링 | `ring_ofs[0]` | 1 | 사용자가 쓰고 스위치가 읽음 |
| 딜리버리 링 | `ring_ofs[tx + host_tx]` | 0 | 스위치가 쓰고 사용자가 읽음 |

호스트 링은 NIC TX와 RX 항목 사이에 끼어 있습니다. `vale1:1`은 TX 1개, 호스트 TX 0개, RX 1개였고 루프백 포트는 `tx + host_tx = 2`, `vmx0`는 TX와 호스트 TX 합이 5라 RX 0이 인덱스 5에 있었습니다.

운영상 주의가 하나 있습니다. sync ioctl은 링 인덱스가 아니라 역할 기준으로 동작해서, 송신자 fd에서 `NIOCRXSYNC`를 부르면 센드 링(`ofs[0]`, `dir = 1`)이 드레인되어 이후 송신이 막힙니다. 그래서 송신 경로는 TX sync만 호출합니다.

역할 구분까지 끝냈으니, 이제 전체 경로를 한 번에 증명할 차례였습니다.

## 루프백 검증: 8/8 패킷 비트 정합

증명은 예제 프로그램 하나가 맡았습니다. 규칙 세 가지를 절차에 그대로 녹인 다음, 5초 마감 안에 수신을 확인합니다.

| 단계 | 내용 | 반영 규칙 |
|---:|---|---|
| 1 | 수신자 `vale60:r`을 먼저 열고 memid를 확보 | 규칙 1 |
| 2 | 수신 링 프라이밍, 커서 정렬 후 rxsync 1회 | 규칙 2 |
| 3 | 송신자 `vale60:w`를 같은 memid로 등록 | 규칙 1 |
| 4 | 패턴이 심어진 RTP 페이로드 8개 송신, cur 동반 전진 | 규칙 3 |
| 5 | 수신 폴링, 마감 5초 | 해당 없음 |

페이로드에는 패턴(`i % 256` 값과 그 보수)을 심어, 수신 쪽에서 정합을 기계적으로 검증하게 했습니다.

결과는 2026-08-18, **8/8 패킷이 비트 단위까지 정합**했습니다. RTP 인코딩에서 TX 슬롯, 커널 VALE 스위치, RX 슬롯, RTP 파싱까지 전 경로가 제로카피로 동작한다는 실증입니다. 같은 날 전체 회귀 스위트도 573/573으로 통과했습니다.

## 최고 성능의 전제: 네이티브 드라이버

여기까지의 이야기에는 전제가 하나 숨어 있습니다. 드라이버가 netmap을 인식해야 합니다. man netmap(4)의 SUPPORTED DEVICES 절이 그 목록인데, 핵심만 옮기면 이렇습니다.

| 드라이버 | 대표 칩셋 | netmap 네이티브 |
|---|---|---|
| `cxgbe(4)` | Chelsio T4/T5/T6 | 네이티브 |
| `em(4)` | Intel e1000 | 네이티브 |
| `igb(4)` | Intel I210/I350 | 네이티브 |
| `ix(4)` | Intel 82598/82599/X540 | 네이티브 |
| `ixl(4)` | Intel XL710/X722 | 네이티브 |
| `re(4)` | Realtek 8169/8111 | 네이티브 |
| `vtnet(4)` | VirtIO net (KVM/QEMU) | 네이티브 |
| 그 외 전부 | - | **에뮬레이션** (bpf 대비 3~5배 빠른 수준) |

동작 방식이 재미있습니다. 커널 설정에 `device netmap`이 들어가면 빌드 시 `DEV_NETMAP`이 정의되고, 각 드라이버 소스의 `#ifdef DEV_NETMAP` 블록이 활성화됩니다. GENERIC 커널은 이 설정을 포함하므로 위 드라이버들은 **이미 훅이 켜진 상태로 로드**됩니다. 에뮬레이션으로 갈지 네이티브로 갈지는 sysctl `dev.netmap.admode`(0=자동, 1=네이티브 강제, 2=에뮬레이션 강제)로 런타임에 정할 수 있습니다.

그러니 실전의 순서는 이렇습니다. 하드웨어를 고르기 전에 표를 먼저 보고, 대상 NIC이 네이티브 목록에 있는지 확인합니다. 저희 실험 머신의 `vmx0`는 표에 없는 확인 대상이라 루프백 검증은 전부 VALE로 했습니다. 하드웨어와 무관하게 netmap의 세계관을 검증할 수 있다는 점이 VALE의 실용적 가치입니다.

## 다른 OS는 어떻게 답했나

"사용자 공간 mmap 링 + 커널 우회"라는 설계는 netmap만의 것이 아닙니다. 같은 문제를 다른 OS는 이렇게 답했습니다.

| 기술 | 목적 | 제로카피 | 드라이버 조건 | FreeBSD 가용성 |
|---|---|---|---|---|
| **netmap(4)** | 고속 패킷 I/O + 가상 스위치 | 네이티브 제로카피 | 네이티브 7종 + 에뮬레이션 범용 | **GENERIC 기본 포함** |
| AF_XDP (Linux) | 고속 패킷 처리 + eBPF | XDP_ZEROCOPY 모드 | 드라이버 XDP 지원 필수 | 없음 (Linux 전용) |
| DPDK | 풀 사용자 공간 데이터플레인 | PMD 기반 | 전용 PMD 필요 | Linux 중심, 지원 축소 이력 |
| TPACKET v3 (Linux) | 고속 패킷 캡처 (PF_PACKET) | mmap ring (완전 ZC 아님) | 범용 드라이버 | 없음 (Linux 전용) |

비교에서 드는 인상은 접근성의 차이입니다. Linux의 대응 기술들이 저마다 별도의 설정과 지식을 요구하는 반면, netmap은 **커널에 기본 들어 있고** 가상 스위치(VALE)와 프로세스 간 채널(pipe)까지 같은 프레임워크로 묶여 있습니다. `bpf(4)` 같은 캡처조차 monitor 포트로 흡수합니다. FreeBSD가 이 문제에 내린 답은 "기능을 여러 개 만들기보다 하나의 프레임워크로 통합한다"였고, 다섯 포트 하나의 API가 그 결과입니다.

루프백이 증명한 것은 소프트웨어 스위치 안의 경로입니다. 실제 배포를 위해서는 남은 작업이 세 가지 있습니다.

## 남은 것: 멀티큐, 멀티캐스트, 워커 통합

첫째, **NIC 멀티큐**입니다. 지금은 링 쌍 0만 다루는데, 실제 `vmx0` 트래픽을 RSS 큐로 나누려면 링 세트 API가 필요합니다.

둘째, **진짜 멀티캐스트**입니다. AES67 스타일은 링 위에 IP 경로 설계가 필요합니다. 링은 IP 소켓이 아니므로 그룹 관리는 외부 경로 몫입니다.

셋째, **워커 통합**입니다. 루프백은 예제 수준이라, UDP 트랜스포트처럼 실시간 그래프 뒤의 워커 루프에 연결하는 것이 다음 단계입니다.

**시리즈 안내**

- 함께 읽기: [FreeBSD kqueue(2): 커널이 기억하는 이벤트 큐](/2026/08/24/FreeBSD-Kqueue-Event-Notification/). 같은 커널의 이벤트 통보 이야기
