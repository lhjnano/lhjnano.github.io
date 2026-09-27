---
layout: post
title: "RDMA 학습 시리즈 (2/7) 패브릭과 전송 프로토콜: IB·RoCE·iWARP·IPoIB"
categories: [RDMA, Networking]
description: "InfiniBand는 왜 '네트워크'가 아니라 '패브릭'이라 부를까요? 무손실 전송, LID·GID 두 주소, 서브넷 매니저, RoCE·iWARP·IPoIB를 실측 값으로 정리했습니다."
keywords: [RDMA, InfiniBand, RoCE, iWARP, LID, GID, IPoIB, 서브넷 매니저]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (2/7). 1편에서 RDMA NIC 한 장의 내부를 들여다봤다면, 이번 편은 시선을 넓혀 NIC과 스위치가 얽혀 만드는 패브릭 전체를 다룹니다. 소스: 내부 S3-over-RDMA 검증 보고서(2026-09) 실측 + InfiniBand 아키텍처 사양.

1편의 주인공은 NIC 안이었다. 큐페어, 메모리 영역, 커널 바이패스까지 전부 한 장의 카드 안에서 벌어지는 일이었다. 하지만 NIC은 혼자 서 있는 장치가 아닙니다. 케이블 너머의 스위치, 그 너머의 다른 노드까지 묶어야 비로소 데이터가 흐른다.

이번 편이 다루는 패브릭(fabric)이 바로 그 전체다. 이더넷과 무엇이 다른지, IB 패킷이 어떤 층으로 싸이는지, 노드는 어떤 주소로 찾아지는지를 차례로 보고, 이어서 IB·RoCE·iWARP라는 세 전송 프로토콜과 IPoIB의 정체까지 내려간다. 마지막에는 두 차례 검증의 패브릭 진단 기록으로 이론을 확인한다.

이 글의 숫자는 특별한 표기가 없는 한 두 차례의 검증(1차 CX4, 2차 CX6 네이티브 IB)에서 직접 측정한 값이다. 주소, LID, MTU, 대역폭까지 전부 실측이다.

## TL;DR

- 패브릭 = 무손실 스위치드 네트워크. 크레딧 기반 흐름 제어로 드롭 자체를 막는다
- IB 패킷은 3겹 캡슐화: BTH(QPN·PSN) ← GRH(GID) ← LRH(LID). 읽고 쓰는 건 전부 NIC 하드웨어
- 주소는 두 개: LID(16bit, SM이 할당, 서브넷 안) / GID(128bit, GUID 파생, 전역)
- 서브넷 매니저(SM)가 스캔 → LID 할당 → 라우팅 계산 → 배포까지 집중 관리
- RoCE는 GID만 씁니다. 이 가정을 IB에 그대로 옮기면 DLID=0으로 전송이 죽는다(검증 보고서의 가장 깊은 버그)
- IPoIB는 RDMA가 아니다. 커널 스택을 경유하는 IP 전송이라 ping이 통해도 raw RC 전송은 별개 관문
- 패브릭 건강 증명은 계층 사다리: L1 링크 → L2 IPoIB → L4 raw RC(실측 91 Gb/s(CX4) · 196 Gb/s(CX6 HDR))

## 1. 패브릭이란: 이더넷과 다른 점

패브릭은 HCA와 IB 스위치가 얽혀 만드는 전체 스위치드 네트워크를 가리키는 InfiniBand 용어다. "네트워크"가 아니라 "직물(fabric)"이라고 부르는 데는 이유가 있습니다. 이더넷이 호스트끼리 점대점으로 통신하는 모델이라면, IB 패브릭은 스위치들이 미리 계산된 경로 위에서 전송 자체를 보장하는 하나의 유기적 구조물이기 때문이다.

가장 근본적인 차이는 무손실(lossless)이다. 이더넷은 최선형(best-effort) 전송이라 스위치 큐가 차면 패킷을 버리고, 잃어버린 패킷은 엔드 호스트의 TCP가 재전송합니다. 반면 IB 패브릭은 크레딧 기반 흐름 제어(credit-based flow control)로 수신 측에 버퍼 여유가 있는 만큼만 보낸다. 드롭이 원천적으로 일어나지 않으니 재전송 로직도, 그로 인한 지연 지터도 없다.

| 구분 | 이더넷 (TCP/IP) | InfiniBand 패브릭 |
|------|----------------|-------------------|
| 전송 신뢰성 | 최선형: 스위치가 드롭, 엔드에서 TCP 재전송 | 무손실: 크레딧 기반 흐름 제어로 드롭 방지 |
| 스위칭 방식 | 저장 후 전달(store-and-forward) 일반적 | 컷스루: 헤더(LRH)만 보고 즉시 출력 포트로 |
| 혼잡 시 동작 | 큐 오버플로 → 드롭 → 재전송 폭증 | 크레딧 부족 → 전송 보류(백프레셔) |
| 경로 결정 | 엔드 호스트가 IP·MAC 헤더로 지정 | 패브릭이 관리: SM이 계산한 테이블로 LID 포워딩 |
| 제어 평면 | 분산(스패닝 트리·라우팅 프로토콜) | 집중: 서브넷 매니저(SM)가 경로·QoS 계산·배포 |

스위칭 방식도 다르다. IB 스위치는 프레임 전체를 받아 확인하는 저장 후 전달 대신, 목적지 주소가 담긴 링크 헤더(LRH) 앞부분만 파싱해 곧바로 출력 포트로 흘려보내는 컷스루(cut-through)로 동작한다. 전달 지연이 프레임 크기와 무관해져 홉마다 지연이 일정하게 낮습니다. 흐름 제어는 링크 단위(VL별)로 적용되어 스위치 큐 오버플로를 원천 차단합니다. IB 무손실성의 실체가 이것이다.

> **실측: IP를 거치지 않는 데이터 경로.** CX4 검증 클러스터의 스토리지 패브릭은 `ib0` = 172.16.44.x/24(IPoIB), MTU 4096이다. IPoIB는 이 패브릭 위에 얹은 IP 계층일 뿐, RDMA 데이터가 IP 서브넷을 경유한다는 뜻이 아닙니다. 계층 진단의 Layer 4에서 raw RC 전송 `ib_write_bw`로 node-b → node-a = **91 Gb/s**가 나왔다. LID·GID 좌표만으로 패브릭을 직접 흐르는 경로가 IP 스택과 무관하게 동작함을 확인한 측정이다.

## 2. InfiniBand 프로토콜 스택

IB 패킷은 TCP/IP처럼 계층이 헤더를 더하는 캡슐화로 만들어진다. 아래에서 위로: 전송 계층이 데이터에 BTH를 붙이고, 네트워크 계층이 GRH로 감싸고, 링크 계층이 LRH로 감싼다. 링크에 가까운 헤더일수록 와이어의 앞쪽에 실립니다. 스위치가 가장 먼저 봐야 할 주소(DLID)가 맨 앞에 있는 셈이다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-01-ib-protocol-stack.svg" alt="InfiniBand 프로토콜 스택: 전송/네트워크/링크/물리 계층과 BTH·GRH·LRH 헤더, 완성 패킷 구성">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1: InfiniBand 프로토콜 스택. 왼쪽은 계층별 역할, 오른쪽은 각 계층이 더하는 헤더의 핵심 필드. 링크에 가까울수록 와이어 앞쪽에 실리며, 물리 계층은 헤더를 더하지 않고 완성 패킷 전체를 레인에 부호화해 싣는다</figcaption>
</figure>

각 헤더가 무엇을 싣는지 정리하면 다음 표 하나로 충분합니다.

| 계층 | 헤더 | 핵심 필드 | 역할 |
|------|------|-----------|------|
| 전송 (Transport) | BTH | Opcode · QPN(24bit) · PSN(24bit) | 어떤 QP의 몇 번째 패킷인지: RC·UC·UD 전송 서비스의 기준 |
| 네트워크 (Network) | GRH | SGID · DGID(각 128bit) · hop limit | 서브넷을 넘는 전역 경로: GID 주소 체계(3절) |
| 링크 (Link) | LRH | DLID(16bit) · SL(4bit) · VL · LEN | 로컬 서브넷 안의 스위칭과 서비스 레벨 구분 |
| 물리 (Physical) |: | 레인 ×4 · 8b10b(SDR/DDR) → 64b66b(QDR~) | 완성 패킷을 레인에 싣는 부호화: 헤더를 추가하지 않음 |

TCP/IP 스택에 비유하면 LRH는 이더넷+VLAN(MAC 계층), GRH는 IP, BTH의 QPN은 포트 번호에 대응한다. 결정적 차이는 이 헤더들을 NIC 하드웨어가 스스로 읽고 쓴다는 점입니다. 호스트 CPU와 커널이 스택을 구성하지 않는다(1편의 커널 바이패스 참조). 패킷 맨 끝에는 무결성용 ICRC 트레일러가 붙는다.

> **실측값이 말해주는 스택 매개변수.** 링크 레벨 MTU 4096(`ibstat`으로 확인)은 이 스택이 한 번에 실을 수 있는 페이로드 상한이고, GRH hop_limit = 64(RTR 설정에서 확인)는 패킷이 넘을 수 있는 라우터 수 상한이다. 두 값 모두 verbs 프로그래밍의 연결 수립에서 그대로 등장하니 verbs를 다루는 편에서 다시 만난다.

## 3. 주소 체계: LID와 GID

IB 노드는 크기도 성격도 다른 두 개의 주소를 동시에 가진다. 패킷이 어느 경로로 흐르는지(스위치가 LRH를 보는가, 라우터가 GRH를 보는가)를 이해하려면 이 두 주소의 구분이 필수다. 그리고 검증 보고서의 가장 깊은 버그가 바로 이 주소 하나를 잘못 다룬 사건이었습니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-02-lid-gid.svg" alt="LID와 GID 두 주소 공간: node-a/node-b 노드와 IB 스위치, LRH의 DLID 경로와 GRH의 DGID 경로">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2. 두 주소 공간. 실선(LRH)은 스위치가 DLID만 보고 포워딩하는 로컬 경로, 점선(GRH)은 서브넷을 넘어서도 유효한 전역 경로다. 실측: node-a LID 0x3FA(1018), node-b LID 0x494(1172), node-a GID fe80::122:3300:501:8691</figcaption>
</figure>

### LID: 로컬 식별자

LID(Local Identifier)는 16bit 주소로, 서브넷 매니저(SM)가 각 엔드포트에 할당한다. 로컬 서브넷 안에서만 유효하며, 스위치는 LRH의 DLID 하나만 보고 포워딩합니다. 16bit라 짧고 조회가 단순해 1절의 컷스루 스위칭과 잘 맞는다. 실측값도 이 할당의 흔적이다. CX4 검증에서 게이트웨이 node-a는 0x3FA(=1018), Lustre 노드 node-b는 0x494(=1172)를 받았다.

### GID: 전역 식별자

GID(Global Identifier)는 128bit 주소로 IPv6와 같은 형식이며, HCA의 GUID(64bit 고유 번호)에서 파생된다. 링크 로컬 주소는 `fe80::` 접두로 시작합니다. 실측 GID `fe80::122:3300:501:8691`이 그 예다. GID는 서브넷을 넘어서도 유효하므로 GRH가 이 주소를 운반한다.

| 구분 | LID | GID |
|------|-----|-----|
| 크기 | 16bit | 128bit(IPv6 형식) |
| 할당 주체 | SM이 할당(4절) | GUID에서 파생: 프로토콜이 자동 구성 |
| 유효 범위 | 로컬 서브넷 안에서만 | 서브넷 경계를 넘어 전역 |
| 실려 가는 헤더 | LRH(DLID·SLID) | GRH(DGID·SGID) |
| 누가 읽나 | IB 스위치: 매 홉 포워딩 | IB 라우터, 그리고 소프트웨어(verbs 주소 핸들) |

| 용어 | 한 줄 정의 |
|------|-----------|
| GUID | HCA 하드웨어에 새겨진 64bit 고유 번호. GID의 씨앗이며 설정으로 바꿀 수 없는 장치 신원 |
| 주소 핸들 (AH) | verbs에서 피어 주소(DLID·DGID·hop limit·서비스 레벨)를 묶은 핸들. AH의 dlid가 0이면 IB에서 도착지가 사라진다 |

### 왜 IB는 LID가 필수이고 RoCE는 GID만 쓰나

IB 스위치는 하드웨어 속도로 DLID를 조회합니다. LID가 없으면 패브릭이 패킷을 보낼 곳을 모릅니다. 반면 RoCE는 이더넷 스위치 위에서 동작하므로 IB식 LID 포워딩이 애초에 없고, GID(의 IP 부분)를 이더넷 헤더의 MAC·IP에 매핑해 라우팅한다. 그래서 RoCE 소프트웨어는 "GID만 있으면 된다"고 가정하기 쉽고, 그 가정이 IB에서 어떻게 깨지는지가 검증 보고서의 교훈이다.

> **이슈⑤ 복선: DLID=0은 IB에서 치명적.** versitygw 서버는 RoCE 전용 가정으로 작성돼 있었다. (a) 응답 토큰에 LID를 아예 실어 보내지 않았고 (b) 서버 QP의 주소 핸들(AH)에서 `dlid=0`을 하드코딩했다. IB에서 DLID=0이면 스위치가 프레임을 라우팅할 수 없어 전송이 재전송 타임아웃으로 죽습니다. "GRH 라우팅이 있으니 LID는 불필요하다"는 가정이 LRH 세계에서는 거짓이었던 것. 해결은 서버 패치 6곳(LID 저장·전달·인코딩)이었습니다. 상세한 디버깅 여정은 verbs를 다루는 편에서 다룬다.

> **네이티브 IB 각주: 유효 GID가 하나뿐인 세계.** CX6 검증의 네이티브 IB 패브릭에서는 유효 GID가 idx0(`fe80::`) 하나다. LID는 클라이언트 gpu-1 = 13, 게이트웨이 stg-node1 = 12(ib0)/11(ib1), SM lid 8, active_mtu 4096 전 노드 일치. RoCE에서 흔한 '다중 GID 자동선택 오류'가 구조적으로 불가능한 주소 풍경이다. 본문의 0x3FA/0x494 실측은 CX4 검증(CX4)에서 얻은 값임을 구분해 둔다.

## 4. 서브넷 매니저와 라우팅

IB 패브릭의 두드러진 특징 하나는 제어 평면이 집중돼 있다는 것이다. 이더넷의 스위치들이 각자 스패닝 트리·라우팅 프로토콜로 분산 합의하는 것과 달리, IB 서브넷은 서브넷 매니저(SM) 한 곳이 경로 전체를 계산해 배포합니다. SM이 관리하는 재산이 바로 3절까지 나온 것들, 즉 LID 할당과 스위칭 테이블이다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-03-sm-subnet.svg" alt="서브넷 매니저의 작동: 스캔·LID 할당·라우팅 계산·배포 절차와 로컬 서브넷 토폴로지, IB 라우터 경계">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3: SM의 작동 절차(위)와 로컬 서브넷(아래). SM은 서브넷을 스캔해 각 엔드포트에 LID를 할당하고, 스위치별 최단 경로 테이블을 계산해 배포한다. 서브넷을 넘는 트래픽은 IB 라우터에서 GID(GRH) 기준으로 다음 서브넷으로 옮겨진다</figcaption>
</figure>

### SM의 작동 절차

1. **서브넷 스캔**: 스위치와 모든 엔드포트를 조사해 토폴로지를 파악한다
2. **LID 할당**: 발견한 엔드포트마다 고유 LID를 배정한다(node-a = 0x3FA, node-b = 0x494도 이렇게 만들어진 값)
3. **라우팅 테이블 계산**: 토폴로지에서 목적지 LID별 최단 경로를 계산한다(대표 알고리즘: 상향-하향 최단경로 위주의 라우팅)
4. **배포**: 계산된 포워딩 테이블을 각 스위치에, LID·서비스 레벨 설정은 각 CA에 내려보낸다

SM은 마스터/스탠바이로 운영된다. 서브넷당 마스터 1대가 실제로 관장하고, 스탠바이들이 마스터를 감시하다 장애 시 승계합니다. 구현은 두 가지 형태가 흔합니다. 호스트에서 도는 `opensm` 데몬, 또는 스위치 내장 SM. 검증 클러스터는 스위치 내장 SM으로 운용됐다. 컨테이너가 SM과 대화하는 `issm` 디바이스까지 마운트해야 했다는 점이 그 증거다.

### 로컬 서브넷과 라우터의 경계

LID의 유효 범위는 로컬 서브넷까지다. 서브넷을 넘을 때는 IB 라우터가 중간에 서서 GRH의 GID를 보고 다음 서브넷으로 패킷을 옮긴다. 이때 LRH의 LID는 라우터가 새 서브넷 기준으로 다시 쓰입니다. 링크(LRH·LID)는 서브넷 안의 관문, 네트워크(GRH·GID)는 서브넷을 잇는 관문이라는 계층 분담이 주소 체계에 그대로 드러난다.

> **실측: SM이 이미 일하고 있었다.** 검증 클러스터(node-a/node-b/node-c + 스위치)는 별도의 SM 설정 없이 스위치 내장 SM이 토폴로지를 관리하는 상태였다. 확인 도구가 곧 증명 도구였습니다. `ibstat`으로 각 포트의 LID(0x3FA/0x494)와 링크 상태(ACTIVE, MTU 4096)를 읽었고, `ibping`으로 서브넷 안 노드 도달성을 검증했다. 계층 진단의 Layer 1~2가 한 방에 통과한 배경이다.

## 5. 전송 프로토콜 삼국지: IB vs RoCE vs iWARP

RDMA를 실어 나르는 전송 프로토콜은 크게 세 갈래다. InfiniBand(IB)는 전용 패브릭 위에서 자기만의 와이어 프로토콜로 움직이고, RoCE는 기존 이더넷 위에 RDMA를 캡슐화해 얹으며, iWARP는 TCP 연결 위에 RDMA를 올린다. 어느 쪽이든 애플리케이션에게는 같은 verbs API가 보인다는 점이 이 삼국지를 읽는 열쇠입니다.

그 공통 서비스가 2절에서 예고한 전송 서비스 레벨 RC·UC·UD다. BTH가 구분하는 이 세 모드는 패브릭의 종류와 무겁게 얽혀 있지 않아 세 프로토콜 어디서든 같은 의미로 쓰인다.

| 서비스 | 의미 | 특징 |
|--------|------|------|
| RC (Reliable Connection) | 신뢰 연결 | 순서 보장·ACK·재전송: Lustre ko2iblnd가 쓰는 모드 |
| UC (Unreliable Connection) | 비신뢰 연결 | 연결형이지만 확인 응답 없음: 오류 처리는 애플리케이션 몫 |
| UD (Unreliable Datagram) | 비신뢰 데이터그램 | 비연결, 링크 MTU 크기 제한: IPoIB 데이터그램 모드(6절)의 기반 |

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-04-transports-compare.svg" alt="전송 프로토콜 비교: 공통 verbs 서비스 아래 IB·RoCE·iWARP 3열 비교: 주소 체계, 캡슐화, 무손실 전제, 강점과 제약">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4. 전송 프로토콜 삼국지. 꼭대기의 verbs·RC·UC·UD는 세 프로토콜이 공유하는 서비스 층이다. 아래로 갈수록 각 프로토콜의 정체가 드러난다: 주소(LID의 유무), 캡슐화(원생 헤더 vs 이더넷/TCP 실음), 무손실 전제(크레딧 vs PFC·ECN vs TCP에 맡김)</figcaption>
</figure>

### 세 프로토콜, 세 전략

| 구분 | InfiniBand | RoCE v1 / v2 | iWARP |
|------|-----------|--------------|-------|
| 전송로 | 전용 와이어: LRH·GRH·BTH 원생 헤더 | 이더넷 프레임에 캡슐화: v1은 이더타입 0x8915(L2 한정), v2는 UDP/IP 4791로 라우팅 가능 | TCP 스트림: RDMA 세그먼트를 TCP에 실어 보냄 |
| 주소 | LID + GID: SM이 LID 할당 | GID만 사용: IP 부분을 MAC·IP에 매핑, LID·SM 불필요 | IP 주소: TCP 연결 자체가 피어 식별 |
| 무손실 | 크레딧 흐름 제어로 원천 내장 | 무손실 이더넷이 전제: v1은 PFC(스위치 의존), v2는 ECN·DCQCN 협상 병행 | TCP 혼잡 제어에 맡김: 드롭·재전송 허용, 무손실 보장 없음 |
| 강점 | 최저 지연 · 최고 대역폭 | 기존 이더넷 인프라 재사용: 대형 데이터센터의 주류 | 광역 라우팅: TCP가 도는 곳이면 어디서나 |
| 제약 | 전용 스위치·SM 필수, 서브넷 간 확장은 라우터로 | PFC·ECN 튜닝에 민감 | 지연 증가 · 생태계 축소 |

### RoCE: 이더넷을 입은 RDMA

RoCE v1은 이더넷 프레임에 RDMA 패킷을 직접 실는 설계(이더타입 0x8915)라 같은 L2 브로드캐스트 도메인 안에서만 통한다. RoCE v2는 UDP/IP 캡슐화(목적지 포트 4791)로 바꾸면서 3계층 라우팅이 가능해졌습니다. 무손실은 프리미티브가 아니라 설정으로 만들어야 합니다. v1은 스위치의 PFC(우선 순위 기반 흐름 제어)에, v2는 여기에 ECN 마킹과 DCQCN 혼잡 제어 협상을 더한다.

주소 체계가 GID만으로 충분하다는 점이 IB와 가장 다른 지점이고, 바로 이 차이가 3절의 이슈⑤ 복선으로 이어진다. RoCE 소프트웨어는 "DLID는 필요 없다"고 가정해도 살아남지만, IB 패브릭에 그 코드를 올리는 순간 가정이 무너집니다.

### iWARP: 광역 라우팅의 대가

iWARP는 표준 TCP 연결 위에 RDMA 세그먼트를 얹는다. TCP가 도는 곳이면 어디서나 동작한다는 것이 유일하고 결정적인 강점이며, 광역망(WAN)을 건너는 구성에서는 이 대안이 없다. 대가는 지연입니다. TCP의 연결 관리·혼잡 제어·순서 재조립이 매 전송에 붙고, 무손실 패브릭이 주는 일정한 지연 특성도 포기한다. 낮은 지연이 생명인 HPC 클러스터에서는 IB·RoCE에 밀려 채택이 줄어든 추세다.

> **실측: 왜 IB였나.** CX4 검증 클러스터의 NIC은 모두 ConnectX-4 Virtual Function(SR-IOV)이고, VF는 링크 타입을 호스트 PF를 따랐고 당시 IB 모드 고정이었다. 링크 모드 전환은 가상화 호스트 작업이라 이번 검증에서는 불가능했고, 그래서 과제 자체가 "IB 그대로에서 되는 방법 찾기"가 됐습니다. 참고로 그 이전 문서는 RoCE(ConnectX-7, 400GbE) 환경이었습니다. 같은 게이트웨이 소프트웨어라도 검증 패브릭이 바뀌었고, 그 환경 차이가 서버 코드의 RoCE 가정(이슈⑤)이 이번에 터진 배경이다.

## 6. IPoIB: IB 위의 IP 계층

IB 패브릭은 RDMA 없이는 쓸 수 없는 성물이 아니다. IPoIB(IP-over-InfiniBand)는 IB 링크 위에 IP 패킷을 캡슐화해 얹는 커널 드라이버다. IPoIB가 활성화되면 `ib0` 같은 일반 네트워크 인터페이스가 생기고, 그 위에는 평범한 IP 서브넷이 놓입니다. ping, ssh, 일반 소켓 애플리케이션 전부 IB 패브릭 위에서 돌아간다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-05-ipoib.svg" alt="IPoIB 구조: node-a/node-b 노드의 ib0와 IB 스위치, 데이터그램/커넥티드 모드 비교, IPoIB는 RDMA가 아니다 경고 박스">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5: IPoIB. 위쪽은 IP 패킷이 IB 프레임에 캡슐화돼 ib0 간에 오가는 경로, 가운데는 두 가지 모드(datagram·connected)의 차이, 아래 빨간 박스는 이 절의 핵심 경고다. 스위치는 IB 프레임만 본다, IP 서브넷의 존재를 모른다</figcaption>
</figure>

### 두 가지 모드: datagram과 connected

IPoIB에는 전송 서비스를 고르는 스위치가 하나 있다. 데이터그램 모드는 UD(5절)로 패킷을 보내며 ARP를 멀티캐스트로 처리하고 별도 연결 없이 동작하는 기본값이다. 커넥티드 모드는 피어마다 RC 연결을 미리 맺고 큰 메시지를 가상 점대점으로 재조립해 보냅니다.

눈에 보이는 차이는 MTU다. 링크 MTU 4096 환경에서 데이터그램 모드의 IP MTU는 2048이 대표값이고, 커넥티드 모드는 재조립 덕에 최대 65520까지 키울 수 있다. 전환은 `/sys/class/net/ib0/mode`에 `datagram` 또는 `connected`를 기록하는 것으로 끝나지만, 재부팅하면 기본값으로 돌아온다.

> **실측: 스토리지 패브릭의 IP 얼굴.** CX4 검증 클러스터에서 `ib0` = 172.16.44.x/24(IPoIB)다. 이 서브넷은 관리망 10.0.35.x(virtio `ens18`)와 분리된 스토리지 패브릭의 IP 표현이며, Lustre의 LNet NID(@o2ib)도 이 주소 위에 만들어졌다. 링크 MTU는 4096. CX6 검증에서는 IPoIB 서브넷으로 100.64.33.0/24를 사용했다.

### IPoIB는 RDMA가 아니다

이 절에서 가장 중요한 문장이다. IPoIB는 커널 네트워크 스택을 경유하는 일반 IP 전송입니다. 소켓 버퍼 복사가 있고 CPU를 쓰며, 1편에서 본 커널 바이패스와는 정반대 길을 걷습니다. IB 패브릭 "위에서" 돌아갈 뿐, RDMA 하드웨어 경로와는 무관하다.

이 구분이 실전에서는 진단의 갈림길이 된다. IPoIB ping이 통과했다는 것은 IP 스택 경로(L2)가 살아 있다는 증거일 뿐, raw RC 전송(L4)이 동작한다는 보증이 아니다. 계층 진단이 L2와 L4를 별개 관문으로 취급하는 이유가 여기에 있습니다. 참고로 Lustre의 o2ib는 이 둘의 중간쯤에 섭니다. IPoIB 위가 아니라 커널 안에서 RC QP를 직접 만들어 쓴다.

### MTU의 이중구조: 링크는 4096, netdev는 제각각

"IPoIB는 RDMA가 아니다"라는 원칙이 성능으로 돌아오는 모습을 CX6 검증(네이티브 IB, ConnectX-6 200G)이 정밀하게 포착했다. 링크 MTU(active_mtu)는 전 노드 4096으로 일치하지만, IPoIB 인터페이스가 IP 계층에 내보내는 netdev MTU는 별도의 값입니다. 실측으로, 게이트웨이 stg-node1은 1500(LNet이 bond를 사용하므로 변경하지 않음), 클라이언트 gpu-1은 2044.

HTTP 트래픽은 IPoIB(100.64.33.0/24, datagram 모드)을 타는 순간 이 netdev MTU에 묶여 큰 전송이 1500바이트 조각으로 쪼개진다. RDMA verbs는 커널 스택·IPoIB를 거치지 않으므로 링크 MTU 4096을 그대로 씁니다. 같은 링크에서 다른 실효 상한이 나오는 셈이다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-07-ipoib-mtu-reality.svg" alt="IPoIB MTU 이중구조: HTTP 경로는 커널 스택과 IPoIB netdev(MTU 1500 분할)를 거치고, RDMA verbs 경로는 커널·IPoIB를 건너뛰고 링크 MTU 4096으로 직행, 실측 GET 3.6 vs 2.2 GB/s">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6. MTU의 이중구조. 위(HTTP) 경로는 커널 TCP/IP 스택과 IPoIB netdev를 거쳐 netdev MTU 1500에 묶이고, 아래(RDMA) 경로는 커널·IPoIB를 건너뛰고 링크 MTU 4096으로 직행한다. 같은 IB 링크를 타지만 실효 상한이 다르다, 실측(CX6 검증, stg-node1 · 64MiB): RDMA GET 3.6 vs HTTP GET 2.2 GB/s</figcaption>
</figure>

이것이 CX6 검증에서 RDMA가 PUT 약 1.8배 · GET 약 1.7배 전 구간 우위를 기록한 이유다(host-memory 클라이언트, 64MiB에서 RDMA GET 3.6 / HTTP GET 2.2 GB/s). 노드도 패브릭도 같은 시각의 비교에서 데이터플레인만 달랐습니다. 돌아볼 대비가 있습니다. 이전 RoCE(400GbE) 환경에서는 GET이 HTTP 승이었다. HTTP가 400GbE 라인레이트 이더넷을 탔던 구성이다. HTTP의 성능은 링크 속도가 아니라 실제로 통과하는 스택과 그 MTU의 함수라는 뜻이다. IPoIB 위의 HTTP는 'IB 패브릭을 쓰면서도 RDMA의 이점은 받지 못하는' 자리다.

### 네이티브 IB의 단일 GID: 선택이 틀릴 수 없는 세계

같은 CX6 검증 환경은 GID에 관한 교훈도 준다. 네이티브 IB에서 유효 GID는 idx0(`fe80::`) 하나뿐이라(3절 각주), RoCE 환경의 흔한 함정(여러 GID가 나열된 테이블에서 소프트웨어의 자동선택이 엉뚱한 인덱스를 고르는 문제)이 구조적으로 발생하지 않는다.

단 역설이 하나 있습니다. RoCE 전제로 작성된 클라이언트는 link-local 주소를 후보에서 제외하도록 짜여 있었고, 그런 코드는 네이티브 IB의 유일한 GID를 버려 세션 초기화에 실패합니다. 이때는 `VGWRDMA_GID_INDEX=0`처럼 인덱스 0을 명시해야 한다. 반면 NVIDIA cuFile은 로그에 "IB link layer, using default GID index 0"을 남기며 스스로 처리했습니다. GID가 하나뿐인 세계에서는 자동 선택의 실패 양상만 달라질 뿐, 주소 체계 자체는 오히려 단순하다.

## 7. 검증 환경의 패브릭 품질과 진단

1절부터 6절까지의 이론을 이제 실측 위에 올려본다. 패브릭이 건강한지는 두 묶음으로 읽습니다. 링크 상태(물리 계층이 살아 있는가)와 계층별 도달성(어느 높이까지 데이터가 흐르는가). 두 차례의 검증 모두 정확히 이 순서로 패브릭을 검증했습니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch02-06-report-fabric.svg" alt="검증 환경 패브릭 진단: ibstatus 출력, mlx5_0 등록 성공과 ib1 거부, L1-L2-L4 계층 사다리">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 7: 검증 환경의 패브릭 진단. 왼쪽은 mlx5_0의 링크 상태 출력(ACTIVE · 100 Gb/sec · LID 0x3FA · MTU 4096), 오른쪽 위는 두 포트의 LNet 등록 결과 대비, 아래는 L1 → L2 → L4로 내려가는 계층 진단 사다리. L4의 91 Gb/s가 패브릭 건강의 최종 증명이다</figcaption>
</figure>

### 링크 상태 읽기: ibstat · ibstatus

두 도구가 분업한다. `ibstatus`는 포트의 실시간 상태를, `ibstat`은 디바이스 단위로 LID·MTU까지 폭넓게 보여준다. CX4 검증 클러스터 mlx5_0의 출력 요지는 다음과 같다.

```bash
$ ibstatus mlx5_0
Infiniband device 'mlx5_0' port 1:
  State: Active              # 물리적으로 링크 업
  Physical state: LinkUp
  Rate: 100                  # 100 Gb/sec: EDR 4레인
  Base lid: 0x3FA            # SM이 할당한 LID
  Link layer: InfiniBand
$ ibstat mlx5_0 | grep -E "MTU|State"   # MTU는 ibstat에서
  MTU: 4096
  State: Active
```

`State: Active`와 정상적인 LID가 함께 보이면 4절의 서브넷 초기화(SM 스캔 → LID 할당)까지 완료됐다는 뜻이다. 반대편 노드(node-b, LID 0x494)에서도 동일한 확인을 거쳤다.

### 두 포트의 다른 운명: mlx5_0과 ib1

각 노드에는 mlx5_0·mlx5_1 두 포트가 있지만, LNet에는 mlx5_0만 등록할 수 있었다. ib1은 `couldn't query intf` 오류로 거부됐고 원인은 보고서에서도 미규명으로 남는다. 다행히 검증은 단일 포트로 충분했고, 지금까지의 모든 실측값(LID, MTU, 91 Gb/s)은 전부 mlx5_0 포트의 이야기다.

> **미해결 잔존: ib1 등록 거부.** `lnetctl net add`에서 ib1이 "couldn't query intf"로 거부된 원인은 규명되지 않았다. 후보로는 VF 포트 상태·`/sys` 노출 문제 등을 생각할 수 있지만 별도 과제로 남긴다. 교훈을 쪼개면 이것입니다. "두 포트가 보인다"와 "두 포트가 쓸 수 있다"는 다르고, 등록은 곧 확인이다.

### 계층 진단의 사다리: L1에서 L4까지

링크가 Active인 것(L1)과 IPoIB ping이 통하는 것(L2), 그리고 raw RC 전송이 나오는 것(L4)은 각각 다른 층의 증명이다. 계층 진단은 이 사다리를 한 칸씩 내려가 패브릭이 어디까지 건강한지 좁힌다.

1. **Layer 1: 링크**: `ibstat`으로 ACTIVE(mlx5_0, MTU 4096) 확인
2. **Layer 2: IPoIB**: 172.16.44.x ping 통과. 단, 6절이 경고한 대로 IP 스택 경로의 증명일 뿐
3. **Layer 3: Lustre o2ib**: 클라이언트 IO 흐름 정상
4. **Layer 4: raw RC**: `ib_write_bw` node-b → node-a = **91 Gb/s**. QP·MR·AH까지 동원하는 진짜 RDMA 경로의 최종 증명

사다리의 다음 칸인 Layer 5(NVIDIA cuObject·DC transport)만 `rc=-1`로 실패했다는 것. IB 스택·하드웨어는 완전히 건강했고 막힌 것은 사설 라이브러리의 DC transport였다는 것이 CX4 검증의 결론입니다. 이 좌절의 계층 진단과 CX6 검증에서의 개통은 시리즈 후반부(진단 편)가 이어받는다.

### CX6 검증: CX6 200G 패브릭, 같은 사다리에 다른 결말

CX6 검증은 같은 진단 골격을 ConnectX-6 · 200G HDR 네이티브 IB 패브릭에서 다시 밟았다. 링크 상태는 SM lid 8, active_mtu 4096 전 노드 일치, LID는 게이트웨이 stg-node1 = 12(ib0)/11(ib1), 클라이언트 gpu-1 = 13이다. raw verbs 층(L4)의 측정은 이번엔 라인레이트를 찍었다.

```bash
$ ib_write_bw -d mlx5_0 -x 0 -s 67108864 -F --report_gbits    # GET 방향
195.6 Gb/s    # 1QP
$ ib_write_bw -d mlx5_0 -x 0 -s 67108864 -F --report_gbits -q 8
196.1 Gb/s    # 8QP: 약 24.5 GB/s, 200G(HDR) 라인레이트
```

195.6/196.1 Gb/s는 200G의 98%다. 이 측정의 원래 임무는 성능 천장 격리였습니다. 애플리케이션 GET이 약 7 GB/s에서 막혔을 때 패브릭 raw가 24.5 GB/s를 내주면 병목은 패브릭이 아니라는 배제 논법이다(최종 귀속은 클라이언트 측 전송 경로). 그리고 1차 환경에서 실패했던 사다리의 마지막 칸 L5(cuObject GPU-direct · DC transport)는 이번에 통과했다. 같은 골격의 진단이 세대가 다른 NIC에서 내린 결론은 "막힌 것은 IB 패브릭이 아니라 NIC(VF/세대)"라는 것. 이것이 시리즈 전체의 기준선이 된다.

## 마무리 요점

- IB가 "패브릭"인 이유는 무손실에 있다. 크레딧 흐름 제어로 드롭을 원천 차단하고, 컷스루 스위칭으로 홉 지연을 일정하게 유지한다
- 패킷은 BTH·GRH·LRH 3겹 캡슐화. 읽고 쓰는 주체는 호스트가 아니라 NIC 하드웨어다
- 주소는 LID(서브넷 안, SM 할당)와 GID(전역, GUID 파생) 두 층이며, 스위치는 DLID만 본다
- SM이 스캔 → 할당 → 라우팅 → 배포를 집중 수행한다. `State: Active`와 LID가 함께 보이면 서브넷 초기화 완료의 신호다
- RoCE의 "GID만 있으면 된다" 가정은 IB에서 DLID=0 치명 버그로 돌아옵니다. 주소 체계는 프로토콜의 전제다
- IPoIB는 편리하지만 RDMA가 아니다. ping(L2)과 raw RC(L4)는 별개 관문이고, netdev MTU가 일반 트래픽의 실효 상한이다
- 패브릭 진단은 계층 사다리로: 같은 골격이 CX4(91 Gb/s, L5 실패)와 CX6(196 Gb/s 라인레이트, L5 통과)에서 다른 결론을 내렸다

**다음 편 예고**: [RDMA 학습 시리즈 (3/7): 소프트웨어 스택](/2026/09/27/RDMA-Study-03-Software-Stack/)에서 MOFED와 inbox rdma-core의 갈림길, `/dev/infiniband/` 디바이스 파일의 생김새, verbs API가 사용자 공간에 드러나는 모습까지 내려갑니다.
