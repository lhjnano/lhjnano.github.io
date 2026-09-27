---
layout: post
title: "RDMA 학습 시리즈 (4/7): 핵심 개념 — QP·CQ·MR·imm"
categories: [RDMA, Networking]
description: "RDMA의 QP·CQ·MR·imm은 어떻게 맞물려 커널 없는 전송을 지탱할까요? 여섯 개의 톱니와 WRITE_WITH_IMM의 쿠키 매칭까지 그림으로 정리했습니다."
keywords: [RDMA, QP, CQ, MR, WQE, imm, 쿠키 매칭]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (4/7). 소스: 검증 클러스터 S3-over-RDMA 검증 보고서(2026-09-22~26) 실측 기반. 3편이 스택의 층을 다뤘다면, 이번 편은 그 위에서 도는 개념들의 차례입니다.

3편의 마지막 장면을 다시 떠올려 봅시다. 데이터 경로는 커널을 모른 채 애플리케이션 버퍼와 HCA 사이를 직통으로 흘렀습니다. 그렇다면 남는 질문은 하나입니다. 그 직통 통로의 양 끝은 무엇이고, 어떤 규칙 아래서 움직일까요?

이 글이 다루는 여섯 개의 톱니가 그 답입니다. QP(창구), WQE(주문서), CQ(판정창구), MR(등록된 영역과 열쇠), 오퍼레이션(건드리는 방식), 그리고 imm(완료를 확정하는 도장). 하나의 전송을 여섯 번 다른 각도에서 보는 셈인데, 검증 보고서의 데이터플레인 분석도 결국 이 여섯 개의 어휘로 읽힙니다. 마지막 절의 32비트 신호가 1MiB 전송의 성패를 확정하는 장면까지 내려가 봅시다.

## TL;DR

- QP는 SQ·RQ와 QP 컨텍스트의 쌍. RC의 재전송·순서 보장이 소프트웨어가 아니라 하드웨어에서 가능한 이유다
- WQE는 opcode + SGE 목록. doorbell(MMIO 쓰기)이 데이터 경로에서 CPU의 마지막 관여다
- CQ는 여러 QP가 공유하는 완료 창구. 오류 완료에서는 status 외 필드가 미정의값이다
- MR은 등록(페이지 고정 + MTT 기록)의 산물이며 lkey·rkey 두 개의 열쇠를 발급한다
- 오퍼레이션 4종의 축은 "상대측 CPU 관여"와 "RQ 소비". 검증 데이터플레인은 PUT·GET 모두 WRITE_WITH_IMM
- imm은 데이터가 아니라 32비트 신호. 쿠키 매칭으로 완료의 소속을 확정한다

## 1. QP — 큐 페어와 서비스 레벨

애플리케이션이 HCA에게 "여기서 보내고 여기서 받아 달라"고 맡기는 창구가 QP(Queue Pair, 큐 페어)입니다. 3편 §1의 다섯 층에서 HCA가 품고 있다던 "QP 컨텍스트"의 실체가 이번 절의 주인공입니다.

QP는 이름 그대로 한 쌍의 큐입니다. 하나는 SQ(Send Queue, 송신 큐)로, 애플리케이션이 `post_send`로 작업(WQE, 2절)을 내려놓으면 HCA가 그것을 집어 와 패브릭으로 실행합니다. 다른 하나는 RQ(Receive Queue, 수신 큐)로, `post_recv`로 "도착할 데이터를 받아 둘 버퍼"를 미리 게시해 두는 선반이죠. 큐 두 개만으로는 부족한 나머지 정보 — QPN, 다음 패킷 번호(PSN), 연결 상태 — 는 QP 컨텍스트가 HCA 안에 보관합니다. RC 서비스 레벨의 재전송·순서 보장이 소프트웨어가 아니라 하드웨어에서 가능한 이유도 이 컨텍스트가 HCA에 상주하기 때문입니다(1편 §2).

QP마다 부여되는 번호가 QPN(Queue Pair Number, 24비트)입니다. 연결형 서비스에서 두 QP가 서로를 향하려면 연결 수립 시 서로의 좌표 — QPN과 함께 시작 PSN, 그리고 2편에서 본 GID·LID 주소 — 를 교환하고, 그 값을 `ibv_modify_qp`의 RTR 전환으로 자기 컨텍스트에 프로그래밍합니다(5편 §2의 상태 머신이 이 흐름을 다룹니다).

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-01-qp-structure.svg" alt="QP 내부 구조도 — 노드 A(클라이언트)와 노드 B(게이트웨이) 각각의 QP가 SQ·RQ·QP 컨텍스트로 구성되고, 초록 실선 화살이 SQ에서 상대 RQ로 향하며, 회색 점선이 연결 수립 시 QPN·PSN 교환을 나타낸다. 하단에 RC·UC·UD·XRC/DC 서비스 레벨 카드" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - QP의 내부 구조와 QPN·PSN 교환. 각 노드의 QP는 SQ(송신 큐)·RQ(수신 큐)·QP 컨텍스트(QPN·PSN·상태)로 구성된다. 연결 수립 시(회색 점선) 양단은 서로의 QPN·PSN·GID·LID를 교환해 상대를 프로그래밍한다. SEND·WRITE_WITH_IMM처럼 수신 완료 통지(imm)를 남기는 작업은 상대 RQ의 WQE를 소비하지만 plain RDMA WRITE는 RQ를 거치지 않는다(5절)</figcaption>
</figure>

### 서비스 레벨 — QP의 전송 서비스 유형

QP는 만들어질 때 어떤 전송 서비스를 제공할지 함께 선언됩니다. 같은 QP라도 서비스 레벨에 따라 하드웨어가 보장하는 것의 목록이 달라지는데, 이 표가 이번 편 전체와 6편의 프로토콜 선택을 읽는 기준이 됩니다.

| 서비스 레벨 | 신뢰성 | 순서 | 연결 형태 | 특징 · 이 시리즈에서의 위치 |
|------------|--------|------|----------|------------------------------|
| **RC** (Reliable Connection) | HW 재전송 · ACK | 보장 | 연결형 (1:1) | 손실·순서를 하드웨어가 책임진다. 검증 데이터플레인의 선택 — 6편의 주인공 |
| **UC** (Unreliable Connection) | 재전송 없음 | 보장 | 연결형 (1:1) | 순서만 지킨다. 오류 감지는 되지만 복구는 애플리케이션 몫 |
| **UD** (Unreliable Datagram) | 없음 | 없음 | 비연결 | 한 번에 MTU 크기까지만 전송 가능, 멀티캐스트 지원 — 상태 없는 짧은 메시지용 |
| **XRC·DC** | HW 재전송 | 보장 | 확장 연결 | 수만 개 연결을 QP 폭발 없이 스케일링 — 7편에서 이야기가 다시 시작된다 |

> **실측 — 왜 이 모드들인가.** 검증의 첫 시도는 NVIDIA cuObject 경로였고, 정확히 그 DC transport에서 좌절했습니다. cuObjServer 세션 수립이 IB 패브릭에서 `rc=-1`로 실패한 것입니다(당시 계층 진단의 L5, 8편 §1). 이에 대해 `--rdma-rc-enable`로 발견한 RC 데이터플레인은 AMD hipObject의 RC 세션 코어를 versitygw로 포팅한 것으로, 표준 verbs의 RC QP만 사용하며 NVIDIA 라이브러리·mlx5dv·DC transport가 전혀 필요 없었습니다(보고서 §6.2). 덕분에 ConnectX-4가 inbox/MOFED 어느 스택에서든 동작하고 서버 측도 표준 verbs(dlopen shim)라 양단 모두 CX4 호환이 됐습니다(§8). 이후 2차 검증에서 cuObject 자체는 CX6 네이티브 IB에서 정상 구동됐음이 밝혀졌지만 — 제약은 IB가 아니라 NIC(VF/세대)이었습니다(3편) — "그 하드웨어에 있는 표준만 쓴다"는 이 선택의 가치는 그대로입니다.

이 절의 용어를 짧게 짚고 갑니다. QP는 통신 양단을 이루는 송수신 큐 쌍과 그 컨텍스트로, 생성은 3편의 제어 경로를 따라 커널을 거쳐 HCA에 자원으로 만들어집니다. QPN은 패브릭 입장에서 QP를 지칭하는 24비트 주소로, 토큰의 qpNum(4바이트) 필드에 실립니다(6편 §2). SRQ(Shared Receive Queue)는 여러 QP가 수신 버퍼를 하나의 큐로 공유하는 확장인데, 검증 사례에는 등장하지 않으므로(보고서에 언급 없음) 이름만 짚고 넘어갑니다.

## 2. WQE — 작업 큐의 벽돌

QP를 "애플리케이션이 HCA에 맡기는 창구"라 불렀습니다. 그렇다면 그 창구에 실제로 내려놓는 물건은 무엇일까요. 그것이 WQE(Work Queue Entry, 작업 큐 항목)입니다. SQ에 내려놓는 WQE는 "이 데이터를 이 오퍼레이션으로 처리해 달라"는 송신 의뢰장이고, RQ에 내려놓는 WQE는 "도착하는 것은 이 버퍼에 받아 달라"는 수신 예약표입니다. 애플리케이션과 HCA 사이의 계약은 전부 이 작은 레코드의 나열로 이뤄집니다. 코드에서는 `struct ibv_send_wr`·`struct ibv_recv_wr`로 쓰고(5편 §4), 그것이 큐에 복사되어 앉은 모습이 WQE입니다.

송신 WQE의 내부는 두 부분으로 요약됩니다. opcode는 "무엇을" — WRITE·SEND·READ 같은 오퍼레이션(5절) 하나를 지정합니다. SGE(Scatter-Gather Entry) 목록은 "어디서" — 데이터 조각들의 좌표입니다. SGE 하나는 `lkey`·`addr`·`len` 세 필드로 등록된 메모리(MR, 4절)의 한 구간을 가리킵니다. 전송할 페이로드가 주소상 멀리 떨어진 조각 여럿으로 나뉘어 있다면 어떻게 될까요. 조각마다 SGE를 하나씩 두면 그만입니다. 흩어진 버퍼를 하나로 모으는 복사(memcpy)는 필요 없고, NIC가 SGE 순서대로 읽어 한 번의 송신으로 묶습니다. 이것이 scatter-gather입니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-02-wqe-queues.svg" alt="WQE 구조와 산란-수집 — 상단은 post_send/post_recv 기록 → doorbell(MMIO 쓰기) 통지 → HCA가 비동기로 소비하는 제출 파이프라인. 중앙의 WQE 바는 opcode 카드와 SGE[0..2] 카드(lkey·addr·len)로 구성되고, 청록 화살표가 각 SGE에서 주소가 멀리 떨어진 버퍼 A·B·C로 내려간다. 초록 화살표는 세 조각이 하나의 전송으로 조립되는 gather를 가리킨다" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - WQE의 구조와 산란-수집(scatter-gather). WQE 하나는 opcode(무엇을 할지)와 SGE 목록으로 구성된다. 각 SGE는 등록된 메모리의 한 구간을 지목하므로(청록) 조각들이 주소상 멀리 떨어져 있어도 되고, NIC가 SGE 순서대로 조각을 읽어 하나의 작업(WR)으로 송신한다(초록, gather). MTU 단위의 패킷 분할도 NIC 몫이다</figcaption>
</figure>

제출에서 소비까지의 시점도 그림 상단에 있습니다. `post_send`·`post_recv`는 사용자 공간에서 호스트 메모리의 큐(링)에 WQE를 기록하는 함수 호출입니다. 시스템 콜을 거치지 않고 곧장 기록됩니다(3편 §1의 제어 경로와 데이터 경로 분리가 이것을 가능하게 합니다). 기록만으로는 HCA가 알 방법이 없으므로, 라이브러리가 doorbell이라 불리는 MMIO 쓰기로 "새 WQE가 있다"를 알립니다. 여기까지가 CPU가 하는 일 전부입니다. 이후 HCA는 자기 페이스대로 WQE를 DMA로 인출해 실행합니다. 패킷 조립, 전송, ACK 처리까지 전부 하드웨어 몫이고(1편 §2), CPU는 완료를 기다리는 대신 다음 일을 합니다. 완료 통지는 CQ에 쌓이는 CQE로 오며, 그것이 3절의 주제입니다.

> **실측 — GET의 zero-SGE recv.** 보고서 §7.2의 2왕복 시퀀스에서 GET 3단계는 클라이언트가 "zero-SGE recv 게시(imm 수신 대기)"만 수행합니다. `num_sge`가 0인, 그러니까 버퍼 좌표가 아예 없는 recv WQE입니다. 데이터 본체는 서버가 클라이언트 토큰(6편 §2)의 rkey·addr로 RDMA WRITE해서 토큰이 지목한 버퍼에 직접 도착하므로, 이 recv가 담당하는 것은 imm(쿠키) 수신 통지 하나뿐입니다. 반대로 PUT에서 서버가 staging 영역에 대해 게시하는 recv는 SGE를 갖습니다. 보고서 §10의 로그가 그 실측 흔적입니다.

```text
PUT recv posted: s.size=… staging_mr_len=… sge_len=…
GET data received via RDMA (…, imm=…)
```

용어 세 가지만 남깁니다. WQE는 작업 큐의 한 슬롯을 차지하는 요청 레코드로, 제출 시점에 실어 둔 `wr_id`가 완료(CQE)와 매칭됩니다(3절·6절). SGE는 `lkey`·`addr`·`len` 세 필드로 이루어진 버퍼 좌표 하나로, lkey는 그 버퍼가 속한 MR(4절)의 로컬 접근 키입니다. doorbell은 WQE 기록 후 HCA에 새 작업 도착을 알리는 MMIO 쓰기로, 데이터 경로에서 CPU의 마지막 관여입니다.

## 3. CQ와 CQE — 완료 통지

2절의 마지막 장면을 이어받습니다. CPU는 doorbell까지만 두드리고 자리를 떴고, HCA는 WQE를 자기 페이스대로 소비합니다. 그렇다면 "끝났다"는 소식은 어디로 돌아올까요. 그 창구가 CQ(Completion Queue, 완료 큐)입니다. HCA가 작업 하나를 끝내면 — 송신 WQE가 ACK를 받았거나, 게시해 둔 recv 버퍼에 데이터가 착지했거나 — 그 결과를 CQE(Completion Queue Entry, 완료 항목)로 만들어 CQ에 쌓습니다. 제출이 애플리케이션에서 QP로 흘러간 것의 반대 방향, 즉 HCA에서 애플리케이션으로 돌아오는 절반이 완료 통지입니다. 참고로 송신 쪽에서는 완료 보고를 요청한 WR만 CQE를 남깁니다. `IBV_SEND_SIGNALED` 플래그가 그 요청이며(5편 §4), 수신(recv) 완료는 항상 보고됩니다.

CQ의 첫 번째 성질은 공유입니다. QP마다 완료 큐를 새로 팔 필요가 없습니다. 여러 QP의 SQ·RQ 완료를 하나의 CQ에 모을 수 있고, 연결 수가 늘어도 애플리케이션이 들여다보는 창구는 하나면 됩니다. 두 번째 성질은 CQE가 판결문이라는 것입니다. 꺼낸 CQE — 코드에서는 `struct ibv_wc` — 의 필드는 그림 3처럼 요약됩니다. `status`는 성공·실패의 판정(0이면 성공), `opcode`는 무엇이 끝났는지, `byte_len`은 몇 바이트였는지, 그리고 `imm_data`는 32비트 즉값으로 6절의 쿠키가 실리는 자리입니다. 여기에 제출 시점에 실어 둔 `wr_id`(2절)가 돌아와 원래 WQE와 매칭됩니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-03-cq-cqe.svg" alt="CQ와 CQE 개념도 — 상단의 QP A·B·C 세 박스에서 초록 화살표 세 개가 하나의 CQ 컨테이너로 내려간다. CQ 안에는 FIFO 노트 카드와 CQE 카드 3장(WRITE 성공 status 0, RECV 완료 imm_data=쿠키, 빨간 테두리의 오류 완료)이 있다. 청록 화살표가 CQE를 펼친 struct ibv_wc 필드 카드 다섯 장(wr_id·status·opcode·byte_len·imm_data)으로 연결하고, 파랑 화살표 둘이 아래의 폴링 박스(ibv_poll_cq 루프)와 이벤트 박스(ibv_get_cq_event)로 갈라진다" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - CQ와 CQE — 완료의 창구와 소비의 두 갈래. 여러 QP의 완료가 하나의 CQ에 CQE로 쌓이고(초록), 꺼내면 struct ibv_wc의 필드들 — wr_id(매칭)·status(판정)·opcode·byte_len·imm_data 32비트 — 이 드러난다(청록). 소비는 폴링과 이벤트 둘로 갈리지만 꺼내는 창구는 ibv_poll_cq로 같다(파랑). 빨간 테두리의 오류 완료에서는 status만 유의미하다(보고서 §10)</figcaption>
</figure>

### 완료를 기다리는 두 방식 — 폴링과 이벤트

CQ에 쌓였다는 사실을 애플리케이션은 어떻게 알까요. 여기서 두 갈래 길이 갈립니다. 폴링은 `ibv_poll_cq`를 반복 호출하며 큐를 계속 들여다보는 것입니다. 완료가 놓이는 즉시 픽업하므로 지연이 가장 짧고 코드도 짧지만, 기다리는 동안 CPU를 계속 씁니다. 이벤트 방식은 미리 `ibv_req_notify_cq`로 알림을 등록해 두고 컴플리션 채널(파일 디스크립터)에서 `ibv_get_cq_event`로 잡니다. CQE가 도착하면 채널이 깨우고, 깨어난 쪽은 `ibv_ack_cq_events`로 알림을 정리한 뒤 결국 `ibv_poll_cq`로 몰린 CQE를 배수(drain)합니다. CPU는 쉬지만 깨어나는 오버헤드가 지연에 더해지죠.

| 방식 | 동작 | CPU 사용률 | 지연 | 이 시리즈에서의 위치 |
|------|------|-----------|------|---------------------|
| **폴링** — ibv_poll_cq | CQ를 반복해 들여다보며 능동으로 꺼낸다 — 반환값 0은 "아직 없음" | 대기 중에도 CPU 점유 | 최소 — 놓이는 즉시 픽업 | 검증 경로도 폴링으로 확인한다(5편 §4) |
| **이벤트** — ibv_get_cq_event | 컴플리션 채널(fd)에 알림을 등록해 두고 잔다 — 기상 후 ack_cq_events → poll_cq로 배수 | 대기 중 CPU 휴식 | 기상 오버헤드만큼 추가 | 연결이 많아 CPU를 아껴야 하는 자세 — 문법은 5편 §4 |

공통점이 중요합니다. 어느 길을 택해도 CQE를 실제로 꺼내는 창구는 `ibv_poll_cq`로 같습니다. 이벤트 방식은 "알림"을 받을 뿐이고 소비는 여전히 폴링이라는 점이 처음에는 헷갈리기 쉽습니다. 검증 클라이언트는 단일 전송 PoC라 저지연이 우선이었고 폴링으로 충분했습니다(5편 §4). 이렇게 꺼낸 CQE의 `opcode`가 말하던 일들 — WRITE와 READ가 상대 메모리를 어떻게 건드리는가 — 의 재료는 4절의 MR이 쥐고 있습니다.

> **실측 — CQE는 status 하나로 말한다.** 보고서 §10이 오류 완료의 성질을 못 박습니다. 오류 완료(status≠0)에서는 opcode·byte_len·flags가 미정의값이라는 것. 그래서 오류 진단은 status 하나로 이뤄지고(8편의 진단 트리), 성공 완료에서야 imm_data가 믿을 수 있는 값이 됩니다. GET의 클라이언트는 recv CQE의 imm이 자신이 발급한 쿠키와 일치하는지만 확인해서 데이터 착지를 확정합니다(6편 §3). 완료 통지의 문법 — status와 imm_data — 이 곧 프로토콜의 판정 근거입니다.

용어를 정리하면 이렇습니다. CQ는 완료 통지가 도착하는 큐로 데이터플레인 작업의 "끝"이 애플리케이션에 드러나는 유일한 창구이며, QP 생성 시 송신용·수신용으로 지정됩니다(5편 §1). CQE는 그 항목으로, 꺼내면 `struct ibv_wc`로 보이고 오류 완료에서는 status 외 필드가 미정의값이라 판단은 status 하나로 합니다(5편 §6의 WC 상태 계급과 이어집니다). 컴플리션 채널은 이벤트 방식의 알림 파이프로, 폴링의 저지연과 이벤트의 CPU 여유 중 어느 쪽을 택할지가 완료 설계의 기본 선택입니다.

## 4. MR·PD와 메모리 등록 — 두 개의 열쇠

3절의 CQE는 일이 "끝났다"만 말했습니다. 그 일이 어떤 메모리에서 일어났는지 이야기하려면 다른 준비가 필요합니다. 커널 바이패스(3편 §1)의 대가가 여기서 지급됩니다. 평소라면 CPU가 커널을 통해 가상 주소를 물리 주소로 번역하지만, RDMA로 데이터를 주고받는 동안에는 NIC가 user-space 버퍼의 주소를 스스로 해석해야 합니다. 그러려면 버퍼의 페이지가 물리 메모리에 묶여(고정, pinning) 있어야 하고, NIC 안에 가상→물리 대응표가 기록되어 있어야 합니다. 이 절차가 메모리 등록이고 그 결과물이 MR(Memory Region)입니다. 등록되지 않은 주소로는 HCA가 DMA를 걸 수 없습니다. 이것이 5절의 오퍼레이션이 "등록된 영역에만" 동작하는 이유입니다.

등록은 세 단계로 흐릅니다(그림 4 왼쪽). 애플리케이션이 `ibv_reg_mr(pd, addr, len, access)`로 버퍼의 시작 주소·길이·접근 권한을 제시하면, 커널이 해당 페이지들을 물리 메모리에 고정합니다. 스왑아웃되어 페이지가 디스크로 내려가는 순간 NIC의 주소 해석이 무효가 되기 때문입니다. 마지막으로 HCA가 자신의 매핑 테이블(MTT, Memory Translation Table)에 이 버퍼의 가상→물리 대응을 기록하면 등록이 끝나고, 두 개의 열쇠가 발급됩니다. lkey(local key)는 자기 자신의 WQE·SGE에 실리는 것으로, 내 HCA가 "이 버퍼는 등록됐고 로컬 읽기·쓰기 권한이 있다"를 검사하는 근거입니다. rkey(remote key)는 원격으로 건네지는 것으로, rkey와 addr(그리고 length)을 함께 받은 노드만 내 버퍼에 원격 WRITE·READ를 걸 수 있습니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-04-mr-pd-keys.svg" alt="MR 등록 개념도 — 왼쪽 3단 파이프라인(앱의 ibv_reg_mr → 커널의 페이지 고정 pinning → HCA의 MTT 매핑 기록)을 거쳐 MR이 등록되면 두 개의 열쇠가 발급된다. 오른쪽 위 PD 점선 컨테이너 안에 QP와 MR이 함께 격리되어 있고, 아래 행에서 lkey(청록, 자신의 WQE·SGE에 실림)와 rkey(보라, rkey+addr+len을 받은 원격 노드만 WRITE·READ 가능)가 갈라진다. 바닥의 경고 노트는 미등록·권한 밖 접근이 LOC 계열 오류의 단골 원인임을 적는다" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - MR·PD — 등록의 3단계(앱 → 커널 고정 → HCA 매핑)와 두 개의 열쇠. lkey는 로컬 WQE/SGE용(청록), rkey는 원격 노드에 전달되는 원격 접근 권한(보라)이다. PD 울타리 안에서 QP와 MR은 하나의 보호 도메인을 공유한다</figcaption>
</figure>

등록을 어디에 소속시킬지가 PD(Protection Domain)입니다. 같은 PD 안의 QP와 MR끼리만 서로 접근할 수 있습니다. 남의 PD의 MR 좌표를 알아내도 rkey가 다르면 문이 열리지 않죠. 검증 시나리오에서는 클라이언트가 PUT 데이터를 담을 버퍼와 서버가 응답 토큰으로 알려주는 staging 버퍼가 각각 이 방식으로 등록되고, 서버가 클라 버퍼에 WRITE_WITH_IMM을 걸 수 있는 근거가 바로 클라이언트가 토큰에 실어 보낸 rkey·addr·len입니다.

> **실측 — 토큰의 절반이 MR 좌표다.** 검증 데이터플레인의 토큰(6편 §2)에서 `rkey(4B) + addr(8B) + length(8B)`가 차지하는 20바이트는 정확히 이 절의 MR 좌표입니다. 실측값 rkey·addr·len이 토큰으로 교환된다는 것은 클라이언트가 자신의 MR을 등록하고 그 열쇠를 서버에 건넨 흔적이고, 서버 측도 PUT을 받기 위해 staging calloc + MR을 수행합니다(보고서 §7.2) — 같은 원리의 반대 방향입니다. 즉 토큰은 "내 버퍼의 열쇠와 좌표"를 직렬화한 와이어 포맷입니다.

> **등록 없는 접근 — LOC 계열 오류의 단골 원인.** 미등록 주소로 접근하거나 권한 플래그를 벗어나면(로컬 읽기 전용인데 쓰기를 걸거나, 원격 쓰기를 허용하지 않은 MR에 WRITE를 걸거나) HCA는 전송을 로컬 오류로 종료합니다. `IBV_WC_LOC_PROT_ERR` 계열이 그것입니다(5편 §6). 보고서 §10의 대형 전송 실패는 원인이 달랐지만, 이 문구가 처음 보이는 순간 가장 먼저 의심해야 하는 것이 바로 이 등록·권한 불일치입니다. 진단은 늘 상식적인 후보부터 배제하는 순서로.

용어를 묶으면 이렇습니다. MR은 `ibv_reg_mr`의 산물로 좌표(addr·len)와 접근 권한을 보유하며 lkey/rkey 두 열쇠를 발급합니다. PD는 QP와 MR을 하나의 울타리로 묶는 소유권 단위로 `ibv_alloc_pd`로 생성하며 모든 리소스 생성의 시작점입니다(5편 §1). pinning은 스왑아웃되면 NIC의 주소 해석이 무효화되므로 전송 중 페이지가 절대 움직이지 않게 묶는 작업인데, 대량 등록은 memlock 한계와 직결됩니다. 3편 §5의 컨테이너 함정(memlock=-1·IPC_LOCK)이 이것 때문이었습니다. MTT는 HCA 내부의 가상→물리 변환표로, NIC 세대마다 MTT 용량이 등록 가능한 메모리양의 상한을 정합니다.

## 5. RDMA 오퍼레이션 — 4총사

4절에서 버퍼는 MR로 등록되며 원격에서 쓸 수 있는 좌표 — rkey와 addr — 를 얻었습니다. 그렇다면 그 좌표를 어떻게 쓸 것인가. 그것이 오퍼레이션의 선택이고, 선택지는 넷입니다. 2절의 WQE가 opcode 필드를 갖고 있던 이유가 여기서 드러납니다. opcode에 네 값 중 하나를 넣으면 HCA는 그 값이 정한 방식대로 상대를 상대합니다. 넷을 가르는 가장 중요한 축은 상대측 CPU가 관여하는가입니다.

SEND/RECV는 편지에 가깝습니다. 보내는 쪽은 "이 덩어리를 준다"만 말하고, 받는 쪽은 어디에 받을지 `post_recv`로 미리 예약해 둬야 합니다. 양쪽 다 CPU가 큐에 관여하므로 two-sided(양측형)라 불리고, 상대 버퍼의 좌표(rkey·addr)는 아예 몰라도 됩니다. 반면 RDMA WRITE는 열쇠가 달린 방문입니다. 상대가 등록해 둔 MR의 rkey와 addr을 알면 그 주소로 곧장 씁니다. 상대측 CPU는 일어난 일을 전혀 모르고, 상대의 RQ도 소비하지 않죠(one-sided, 편측형). RDMA READ는 같은 열쇠로 반대 방향을 여는 것이라 하겠습니다. 개시측이 상대 MR의 좌표를 지정해 그 안의 데이터를 당겨 읽습니다.

그리고 RDMA WRITE_WITH_IMM — 이 시리즈의 실제 주인공입니다. 데이터 경로는 plain WRITE와 똑같이 one-sided로 직행하지만, 패킷에 32비트 imm(즉값) 하나를 얹어 보냅니다. 수신측 HCA는 이 값을 버리지 않고, 마치 SEND가 도착한 것처럼 게시돼 있던 recv WQE 하나를 소비하면서 CQE의 `imm_data` 필드에 그 값을 올립니다(그림 3에서 보라색으로 칠해 둔 자리입니다). 즉 데이터는 one-sided로 흘리고 완료 신호만 two-sided 채널로 두드리는 오퍼레이션입니다. 그림 5가 이 대칭 — 누가 CPU를 쓰고 누가 RQ를 쓰는가 — 를 네 패널로 놓아 비교합니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-05-operations.svg" alt="RDMA 오퍼레이션 4종 비교 — 상단의 WQE opcode 바에서 네 갈래로 내려간 4열 매트릭스. 각 열이 SEND/RECV(two-sided), RDMA WRITE(one-sided), WRITE_WITH_IMM(one-sided + imm 통지), RDMA READ(one-sided)이고, 행은 데이터 방향, 수신측 CPU·RQ 관여, 검증 데이터플레인에서의 사용(PUT·GET 모두 WRITE_WITH_IMM)을 담는다" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5 - RDMA 오퍼레이션 4총사 — 비교의 축은 둘이다: 상대측 CPU가 관여하는가(two-sided/one-sided), 상대 RQ를 소비하는가. SEND와 WRITE_WITH_IMM만이 상대 RQ의 recv WQE를 소비하고, WRITE_WITH_IMM은 데이터는 one-sided로 흘리면서 imm(32비트)으로 수신측에 완료를 통지한다. 검증 데이터플레인은 PUT·GET 모두 이 WRITE_WITH_IMM로 데이터를 옮긴다(보고서 §7.2·§8)</figcaption>
</figure>

| 오퍼레이션 | 형태 | 상대 버퍼 좌표 | 수신측 CPU · RQ | 완료가 드러나는 곳 |
|-----------|------|---------------|----------------|--------------------|
| **SEND / RECV** | two-sided | 불필요 — 착지는 수신측의 recv가 정함 | 관여함 · recv 게시 필수 · **RQ 소비** | 양측의 CQE (수신측은 byte_len로 크기 확인) |
| **RDMA WRITE** | one-sided | 필요 — rkey·addr로 직접 씀 | 불참 · RQ 소비 없음 | 송신측 CQE뿐 — 수신측은 전혀 모른다 |
| **WRITE_WITH_IMM** | one-sided + 통지 | 필요 — rkey·addr로 직접 씀 | 불참(통지 수신만) · **RQ 소비** | 송신측 CQE + 수신측 recv CQE의 `imm_data` |
| **RDMA READ** | one-sided | 필요 — rkey·addr에서 당겨 읽음 | 불참 · RQ 소비 없음 | 개시측 CQE뿐 |

> **실측 — 검증 데이터플레인은 넷 중 무엇을 썼나.** 보고서 §7.2·§8의 데이터플레인을 오퍼레이션으로 번역하면 한 줄입니다. PUT도 GET도 전부 WRITE_WITH_IMM입니다. PUT은 클라이언트가 서버의 staging에 본문을 쓰며 imm에 쿠키를 실었고, GET은 클라이언트가 zero-SGE recv만 게시해 놓고 서버가 토큰의 rkey·addr로 클라이언트 버퍼에 WRITE_WITH_IMM을 보냅니다. "왜 plain WRITE가 아니라 WITH_IMM인가"의 답도 여기서 나옵니다. plain WRITE는 수신측에 아무 신호도 남기지 않아 데이터 착지를 판정할 방법이 없는데, 검증 데이터플레인은 그 판정을 imm=쿠키와 recv CQE의 대조(6절)로 수행하기 때문입니다. SEND/RECV와 READ는 이 데이터플레인에 등장하지 않습니다(제어는 HTTP가 담당). 이 오퍼레이션을 코드로 제출하는 문법은 5편 §4, 실제 시퀀스는 6편 §3에서 만납니다.

용어 두 가지로 압축하면 이렇습니다. one-sided/two-sided는 전송에 양측 CPU가 모두 관여하는가(SEND/RECV — 수신측 recv 게시 필수)와 개시측만으로 완결되는가(WRITE·READ — 상대 좌표 rkey·addr로 상대 메모리를 직접 건드림)의 구분이고, RQ 소비 여부가 정확한 지표입니다. SEND와 WRITE_WITH_IMM은 상대 RQ를 소비하고 plain WRITE·READ는 소비하지 않죠(그림 1의 주의 참조). imm(immediate data)은 오퍼레이션에 함께 실려 가는 32비트 즉값으로, 페이로드가 아니라 신호입니다.

## 6. imm 데이터와 쿠키 매칭 — 완료를 확정하는 손도장

5절의 WRITE_WITH_IMM이 왜 특별대우를 받는지, 이제 마지막 조각으로 설명이 완성됩니다. 핵심은 imm(immediate data, 즉값)이 데이터가 아니라 신호라는 점입니다. one-sided WRITE는 상대측 CPU를 전혀 깨우지 않으므로, 데이터가 아무리 정확히 착지해도 상대는 "왔다는 사실"을 알 길이 없습니다. imm은 그 알림 채널입니다. 송신측이 패킷에 32비트 값을 하나 얹어 보내면, 수신측 HCA는 게시되어 있던 recv WQE 하나를 소비하면서 그 값을 CQE의 `imm_data` 필드에 올립니다. 데이터는 one-sided로 흘리고, 완료 신호만 two-sided 창구(RQ→CQ)로 두드리는 설계가 여기서 완결됩니다.

그런데 알림만으로는 부족합니다. 수신측 CQ에는 여러 전송의 완료가 뒤섞여 도착할 수 있으므로(3절 — CQ는 공유됩니다), 이 완료가 어느 전송의 완료인지 확정할 장치가 필요합니다. 그것이 쿠키 매칭입니다. 송신측은 전송마다 쿠키(식별값)를 하나 발급해 imm에 실어 보내고, 수신측은 자신이 발급해 둔(또는 세션 수립 때 주고받은) 쿠키와 CQE의 imm이 일치하는지 검사합니다. 일치하면 그 시점에 버퍼의 내용이 확정되고, 불일치하면 엉뚱한 세션의 완료를 붙잡은 것이므로 폐기합니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch04-06-imm-cookie.svg" alt="imm과 쿠키 매칭 개념도 — 클라이언트와 게이트웨이 양단 타임라인. 클라이언트가 쿠키를 발급하고 WRITE_WITH_IMM으로 데이터와 imm(초록 화살표)을 보내면, 서버의 recv CQE에 imm_data가 등장한다. 판정 박스에서 imm과 자신의 쿠키를 비교해 일치하면 초록 '버퍼 확정·세션 완료'로, 불일치하면 빨강 '폐기'로 갈라진다. 하단 노트는 zero-SGE recv를 설명한다" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6 - imm 쿠키 매칭 — 완료의 확정 절차. 32비트 imm은 페이로드가 아니라 "이 전송이 끝났다"는 신호이며, 수신측은 imm==자기 쿠키 판정으로 완료의 소속을 확정한다. GET 경로의 클라이언트는 zero-SGE recv로 imm 수신만 전담한다</figcaption>
</figure>

GET 방향에서 이 패턴이 특히 빛납니다. 클라이언트는 받을 버퍼의 MR만 등록해 두고(4절), SGE 없는 recv WQE — zero-SGE recv — 를 게시합니다. 버퍼 좌표는 이미 서버에 rkey·addr로 알려준 상태라 수신 버퍼 지정이 필요 없고, recv의 역할은 imm을 받아 "착지 완료"를 확인하는 것뿐입니다(2절의 복선 회수). 서버가 그 버퍼로 write+imm을 걸어오면 클라이언트의 CQE에 imm이 올라오고, 쿠키 일치로 버퍼가 확정됩니다. 데이터 경로는 한 번도 CPU를 거치지 않은 채로입니다.

> **실측 — 데이터플레인도 이 그림 위에서 돈다.** 보고서 §7.2·§8의 시퀀스를 다시 읽어보면 PUT은 데이터가 WRITE로 흐르고 서버가 READY 처리 중 recv로 imm을 기다리며, GET은 클라이언트가 zero-SGE recv를 게시한 뒤 서버의 write+imm을 받아 imm==cookie 확인으로 버퍼를 확정합니다(6편 §3). 재현 로그의 확인 문구 — `GET data received via RDMA (…, imm=…)`(보고서 §11) — 가 바로 이 판정이 통과된 순간의 출력입니다. 32비트의 신호가 1MiB 전송의 성패를 확정하는, 이 시리즈에서 가장 작으면서 가장 중요한 필드입니다.

용어 세 가지로 마무리합니다. imm은 WRITE_WITH_IMM·SEND에 실어 보내는 32비트 완료 신호로 수신측 recv CQE의 imm_data로 드러납니다(3절). 쿠키 매칭은 송신측이 발급한 쿠키와 수신 CQE의 imm_data 일치를 검사해 완료의 소속을 확정하는 절차로, 일치 시 버퍼 확정·불일치 시 폐기 — 여러 세션의 완료가 공유 CQ에 뒤섞이는 환경의 필수 안전장치입니다. zero-SGE recv는 SGE 없이 게시하는 recv WQE로 수신 버퍼 지정 없이 imm 수신만 담당합니다(보고서 §7.2).

<figure>
  <img src="/assets/images/posts/rdma-study/qa-ch04-q13.svg" alt="스터디 Q&A 카드 — 질문: imm은 SR-IOV 때문에 있는 건가요? 답변: 완전히 별개의 개념. imm은 IB 스펙의 verbs 기능으로 one-sided WRITE의 알림 없음을 메우는 32비트 완료 신호 채널이고 SR-IOV는 PCIe 가상화(PF·VF 분할). PF든 VF든 imm은 동일하게 동작" loading="lazy">
</figure>

<figure>
  <img src="/assets/images/posts/rdma-study/qa-ch04-q14.svg" alt="스터디 Q&A 카드 — 질문: imm은 commit 같은 개념이군요? 답변: 절반만 맞음. RC 순서 보장 위 마지막 신호로 확정하는 패턴은 커밋과 유사하고 쿠키 매칭은 트랜잭션 ID 확인. 단 imm은 내구성·원자성 보장이 없는 전달 완료 영수증이며 실제 커밋은 그 뒤 백엔드 기록 — imm=준비 신호, publish=커밋에 가까움" loading="lazy">
</figure>

## 마무리 — 4편 총정리, 여섯 개의 톱니가 맞물리는 곳

이번 편의 여섯 개념을 하나의 문장으로 꿰어 봅시다. QP(창구, 1절)에 WQE(주문서, 2절)를 내면 HCA가 실행하고, 결과는 CQ(판정창구, 3절)로 돌아옵니다. 주문서가 건드릴 수 있는 메모리는 MR(등록된 영역과 열쇠, 4절)로 한정되고, 건드리는 방식이 오퍼레이션(5절)이며, 완료의 소속을 확정하는 도장이 imm(6절)입니다. 여섯 개는 각자 따로 노는 부품이 아니라 하나의 전송을 이루는 톱니라는 점 — 이것이 4편의 총정리입니다.

이 여섯 개는 앞으로 두 번 더 등장합니다. 5편에서는 실제 C 코드의 문장으로, 6편에서는 검증 데이터플레인이라는 프로토콜의 동작으로 각각 다시 만나죠. 개념을 코드와 와이어에서 한 번 더 만나는 것이 다음 두 편의 일입니다.

**다음 편 예고**: [RDMA 학습 시리즈 (5/7): verbs 프로그래밍](/2026/09/27/RDMA-Study-05-Verbs-Programming/)에서 이 여섯 개념을 실제 코드로 다룹니다 — 초기화 시퀀스, QP 상태 머신, WR 게시와 폴링의 문법입니다.
