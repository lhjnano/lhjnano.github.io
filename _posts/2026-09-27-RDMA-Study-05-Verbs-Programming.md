---
layout: post
title: "RDMA 학습 시리즈 (5/7): verbs 프로그래밍 — 초기화·상태머신·폴링"
categories: [RDMA, Networking]
description: "verbs 프로그램은 왜 여섯 번의 호출로 시작하고, QP는 왜 RTS까지 올라야 말을 걸 수 있을까요? 초기화 시퀀스부터 상태머신, PSN, CQ 폴링까지 검증 코드로 정리했습니다."
keywords: [RDMA, verbs, QP 상태머신, PSN, CQ 폴링, AH, GRH]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (5/7). 소스: S3-over-RDMA 검증 보고서(2026-09)와 학습 로그 — 인용문과 수치는 보고서 실측값입니다.

4편까지는 RDMA가 무엇인지 관찰했다면, 5편부터는 직접 만집니다. 도구는 verbs(libibverbs) — RDMA 디바이스를 다루는 사용자 공간 API입니다. 커널에 시스템 콜을 넣는 대신 `/dev/infiniband/uverbs` 장치 파일을 통해 NIC에 명령을 내리고, 자원이 한번 만들어지고 나면 데이터 경로는 전부 하드웨어에서 돌습니다.

이 편의 색깔은 "검증 클라이언트의 소스에서 배운 것"입니다. 실제로 돌아간 초기화 호출 순서, QP 상태 전이 코드, 그리고 전송이 조용히 죽었던 두 순간(DLID=0, PSN 불일치)을 코드와 함께 정리했습니다. 읽고 나면 RC 데이터플레인을 짜는 재료가 전부 모입니다.

## TL;DR

- 초기화는 여섯 단계: 디바이스 목록 → 오픈 → PD → CQ → QP → MR. 아래 단계는 위 단계가 반환한 핸들을 인자로 쓴다
- QP는 RESET → IDLE → INIT → RTR → RTS 사다리를 올라야 데이터가 흐른다. 전이 하나가 `ibv_modify_qp` 호출 한 번
- AH(주소핸들)에는 IB/RoCE가 갈린다 — IB는 DLID 필수(0이면 드랍), RoCE는 GID·GRH
- 완료 확인은 `ibv_poll_cq` 폴링이 기본. 오류 판정은 `wc.status` 하나로만 한다
- PSN 불일치와 DLID=0의 공통점: 패킷이 조용히 사라진다 — 발신지 로그에 원인이 안 보인다

## 1. 초기화 시퀀스

모든 verbs 프로그램이 따르는 시작 의식 — 여섯 단계의 호출 — 이 아래 그림이다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-01-init-sequence.svg" alt="verbs 초기화 시퀀스 6단계 — ibv_get_device_list, ibv_open_device, ibv_alloc_pd, ibv_create_cq, ibv_create_qp, ibv_reg_mr과 각각이 반환하는 객체" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - verbs 초기화 시퀀스 여섯 단계와 각 단계가 반환하는 핸들. 아래 단계는 위 단계가 반환한 핸들을 인자로 사용한다</figcaption>
</figure>

순서가 정해져 있는 이유는 의존 관계 때문이다. 디바이스를 열어야 컨텍스트가 생기고, 컨텍스트가 있어야 PD를 할당할 수 있으며, QP는 PD와 CQ를 모두 알아야 생성된다. MR 등록은 QP보다 먼저여도 되지만 원격 접근 권한이 붙은 메모리는 반드시 PD 소속이어야 하므로 같은 PD로 등록한다.

호출 체인만 남긴 스켈레톤은 다음과 같다.

```c
/* 1. 디바이스 조회 후 오픈 */
struct ibv_device **dev_list = ibv_get_device_list(&num_dev);
struct ibv_context  *ctx      = ibv_open_device(dev_list[0]);

/* 2~4. 보호 도메인, 완료 큐, 큐 페어 */
struct ibv_pd *pd = ibv_alloc_pd(ctx);
struct ibv_cq *cq = ibv_create_cq(ctx, CQ_DEPTH, NULL, NULL, 0);

struct ibv_qp_init_attr init = {
    .qp_type = IBV_QPT_RC,      /* 송신·수신 완료는 같은 CQ로 */
    .send_cq = cq,  .recv_cq = cq,
};
struct ibv_qp *qp = ibv_create_qp(pd, &init);   /* 반환 시점 상태: RESET */

/* 5. 메모리 등록 — 페이지 고정, lkey·rkey 획득 */
struct ibv_mr *mr = ibv_reg_mr(pd, buf, size,
                     IBV_ACCESS_LOCAL_WRITE  |
                     IBV_ACCESS_REMOTE_READ  |
                     IBV_ACCESS_REMOTE_WRITE);
```

검증 클라이언트는 이 초기화를 두 호출로 묶었다 — RC QP를 만들어 INIT까지 올리는 것과, 원격 읽기·쓰기 권한을 붙인 MR을 등록하는 것이다. 이어지는 좌표 교환은 6편에서 다룬다.

> **보고서 실측 — 언어 구분** · "구조: RDMA/verbs 조작은 C(표준 verbs만 — CX4 호환), SigV4·HTTP·흐름 제어는 Go. 전부 신규 코드" (보고서 §8). 표준 verbs만 사용하므로 ConnectX-4의 inbox/MOFED 어느 쪽에서든 동작했다 — DC/mlx5dv/CUDA는 어디에도 필요 없다.

이 절의 용어 다섯 개가 나머지 절 전부를 지탱한다.

| 용어 | 역할 |
|------|------|
| PD (Protection Domain) | MR과 QP를 하나의 소유 영역으로 묶는 컨테이너. 다른 PD의 MR을 그 PD 밖의 QP가 건드릴 수 없다 — 권한 격리의 단위 |
| CQ (Completion Queue) | 완료된 작업의 통지(CQE)가 쌓이는 큐. 애플리케이션이 `ibv_poll_cq`로 능동적으로 소비한다(폴링 모델 — 인터럽트 없음) |
| QP (Queue Pair) | 송신 큐(SQ)와 수신 큐(RQ)의 쌍. RC 서비스에서 QP 하나가 곧 하나의 연결 엔드포인트 |
| MR (Memory Region) | 등록된 사용자 버퍼. 등록 과정에서 페이지가 피닝(고정)되고 가상→물리 변환표가 NIC에 내려간다 |
| lkey / rkey | lkey는 로컬(자기 QP의 송신) 접근용, rkey는 원격(RDMA READ/WRITE) 접근용 키. rkey는 연결 상대에게 미리 알려줘야 한다 — cuObject 토큰으로 전달된다(6편 §2) |

<figure>
  <img src="/assets/images/posts/rdma-study/qa-ch05-q01.svg" alt="스터디 Q&A 카드 — RDMA 클라이언트는 보통 어떤 언어로 구현하나요? 검증 클라이언트는 Go+C 하이브리드: verbs 데이터 경로는 표준 libibverbs만 쓰는 C, 제어 경로는 Go" />
</figure>

## 2. QP 상태 머신

QP는 만들었다고 바로 쓸 수 없다. 상태를 단계적으로 전이시켜 양단이 서로의 좌표를 알아야 비로소 데이터가 흐른다. RC 서비스에서 핵심 경로는 RESET → IDLE → INIT → RTR → RTS이며, 각 전이는 `ibv_modify_qp` 호출 한 번에 대응된다(생성 직후 RESET→IDLE만 예외 — 속성 지정이 없다).

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-02-qp-state-machine.svg" alt="RC QP 상태 머신 — RESET에서 IDLE, INIT, RTR, RTS로 이어지는 전이도와 각 전이의 attr_mask 항목" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - RC QP 상태 전이, RESET에서 RTS까지. RTR에서 피어의 좌표(QPN·PSN·AH)가, RTS에서 재전송 정책(타임아웃·재시도)이 정해진다</figcaption>
</figure>

각 상태의 의미는 다음과 같다.

| 상태 | 의미 | 이 상태에서 가능한 일 |
|------|------|----------------------|
| RESET | 초기 상태 — 큐 비움 | 아무것도 못 함. `ibv_create_qp`의 반환 지점 |
| IDLE | 생성된 큐의 대기 상태 | 통신 불가 — 아직 포트·PKEY조차 지정 안 됨 |
| INIT | 초기화 — 포트·PKEY 지정됨 | 수신 큐에 recv WR 게시 가능(도착한 패킷 수용은 RTR부터) |
| RTR | Ready to Receive — 수신 준비 | 피어가 보낸 패킷 수신·처리 가능. 송신은 아직 불가 |
| RTS | Ready to Send — 송신 개시 | 데이터플레인 가동 — WR 게시 즉시 전송 |

전이 코드에서 attr_mask가 말하는 것은 "이번에 지정하는 속성"이다. 세 전이의 뼈대만 남기면 아래와 같다.

```c
/* INIT — 내 좌표만 지정 */
attr.qp_state        = IBV_QPS_INIT;
attr.port_num        = 1;
attr.qp_access_flags = IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE;
ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS);

/* RTR — 피어 좌표로 수신 준비 */
attr.qp_state           = IBV_QPS_RTR;
attr.path_mtu           = IBV_MTU_4096;   /* 포트의 active MTU */
attr.dest_qp_num        = peer_qpn;       /* 토큰의 qpNum 필드 */
attr.rq_psn             = peer_psn;
attr.min_rnr_timer      = 12;
attr.ah_attr            = ah_attr;        /* §3 참조 */
ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
        IBV_QP_DEST_QPN | IBV_QP_RQ_PSN | IBV_QP_MIN_RNR_TIMER);

/* RTS — 송신 정책 확정 */
attr.qp_state      = IBV_QPS_RTS;
attr.timeout       = 14;      attr.retry_cnt  = 7;
attr.rnr_retry     = 7;       /* 7 = 무한 재시도 */
attr.sq_psn        = my_psn;  /* 피어가 기대하는 시작 PSN과 동일값 */
attr.max_rd_atomic = 1;
ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
        IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC);
```

> **보고서 실측값 — 검증 클라이언트가 사용한 전이 파라미터** · "RTR: path_mtu=active, dest_qpn, rq_psn, AH: is_global=1, dgid=피어GID, dlid=피어LID(패치), hop_limit=64, min_rnr=12 / RTS: timeout=14, retry=7, rnr=7(infinite), max_rd_atomic=1" (보고서 §8). 눈여겨볼 값들:
>
> - `path_mtu=active` — 포트의 활성 MTU를 따라감(검증 패브릭에서는 4096). 양단 MTU가 어긋나면 패킷이 잘린다
> - `min_rnr_timer=12` — 수신 큐가 비어 있을 때 응답자가 보내는 RNR NAK의 "이만큼 뒤에 다시 보내라" 시간. 인코딩 12 = 640μs
> - `timeout=14` — ACK를 기다리는 로컬 타임아웃. 약 4.096μs × 2¹⁴ ≈ 67ms
> - `retry_cnt=7` — 타임아웃 시 Go-Back-N 재전송 최대 7회. 이를 넘기면 `transport retry exceeded`로 QP가 SQE 상태가 된다(트러블슈팅 편 이슈④의 에러 메시지가 바로 이것)
> - `rnr_retry=7` — RNR NAK에 대한 재시도 횟수. 7은 무한 재시도 — "수신 준비 안 됨"은 상대가 곧 게시할 것이므로 기다리겠다는 뜻
> - `max_rd_atomic=1` — 동시에 날릴 수 있는 RDMA READ/ATOMIC 요청 수. 1이면 하나의 응답을 받고 다음을 보낸다

양단이 이 사다리를 다 오르는 시점이 서로 다르다는 점이 cuObject 설계의 열쇠다. 클라이언트는 피어 좌표를 받은 뒤 RTR→RTS, 서버는 READY 요청을 받으며 RTR→RTS를 완성한다 — 어느 한쪽만 RTS여도 전송은 즉시 실패하거나 재전송 타임아웃까지 매달린다. 트러블슈팅 편 관문④의 교착이 정확히 이 어긋남에서 왔다.

## 3. AH와 GRH — 주소핸들

RTR 전이에서 피어의 주소를 담는 것이 AH(Address Handle, 주소핸들)이다. `ibv_create_ah`로 PD로부터 생성하며, 그 속성 구조체 `ibv_ah_attr`에 패브릭 종류에 따른 주소 좌표를 채운다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-03-ah-grh.svg" alt="AH와 GRH 구조 — ibv_ah_attr 필드, GRH 40바이트 레이아웃, IB(LRH·LID) 대 RoCE(GRH·GID) 라우팅 비교, DLID=0 경고" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - AH와 GRH. is_global=1이면 40바이트 GRH가 모든 패킷에 포함되고, IB는 LRH의 DLID로 스위치가 패킷을 전달한다</figcaption>
</figure>

```c
struct ibv_ah_attr ah = {
    .is_global = 1,               /* GRH 포함 — RoCE 필수, 검증 클라는 IB에서도 1 */
    .grh = {
        .dgid       = peer_gid,   /* 피어 GID — 토큰의 gid 필드 */
        .hop_limit  = 64,
    },
    .dlid     = peer_lid,          /* 피어 LID — IB에서는 필수! */
    .port_num = 1,
};
struct ibv_ah *ah_handle = ibv_create_ah(pd, &ah);
/* 이후 RTR의 attr.ah_attr에 값을 넘겨 QP에 묶는다 */
```

주소는 두 종류다. LID(Local ID)는 IB 서브넷 안에서 SM(Subnet Manager)이 각 포트에 배정하는 16비트 주소이고, 스위치는 패킷 헤더 LRH(Local Routing Header)의 DLID를 보고 다음 홉을 결정한다. GID(Global ID)는 IPv6 형태의 128비트 주소로 RoCE에서는 IP 주소와 직결되며 GRH(Global Routing Header)에 실린다. `is_global=1`로 설정하면 GRH가 모든 패킷에 포함된다 — 검증 클라이언트는 IB 패브릭에서도 1을 사용했다(GID 기반 좌표 교환 때문이다).

| 구분 | IB 패브릭 | RoCE 패브릭 |
|------|-----------|-------------|
| 기본 주소 | LID (16비트, SM이 배정) | GID (= IP 주소) |
| 라우팅 헤더 | LRH — DLID로 스위치 전달 | GRH — IP로 이더넷 스위치 전달 |
| DLID 요구 | 필수 — 0이면 드랍 | 불필요 (0이어도 동작) |
| 검증 환경 예 | LID 0x3FA(node-a), 0x494(node-b) | — (검증은 IB 모드 고정) |

> **이슈⑤ — "dlid=0 하드코딩": RoCE 가정이 IB에서 낳은 침묵의 드랍** · cuObject 서버의 RTR 코드는 AH의 `dlid=0`을 하드코딩하고 있었다(RoCE에서는 DLID가 불필요하다는 가정). 그러나 IB에서 DLID=0은 링크 라우팅이 불가능해 패킷이 그냥 사라진다. 증상은 "write: remote invalid request / transport retry" — 타임아웃과 재전송만 반복되는, 원인이 발신지에서 보이지 않는 실패였다. 해결은 서버 패치 6곳: LID 조회·저장부터 응답 토큰 인코딩까지 RoCE 가정을 걷어내는 것이었다(보고서 §9). 응답 토큰의 LID 미기재 버그(§7.1)와 한 세트다.

GRH의 `hop_limit`은 IPv6 TTL에 대응하는 필드다. 64는 충분히 관대한 기본값 — 서브넷 경계를 넘는 경로에서 라우터 홉 수만큼 감소하며 0이 되면 패킷이 폐기된다. 검증 클라이언트는 실측대로 64를 사용했고, 단일 서브넷 환경에서는 사실상 제약이 없는 값이다.

AH가 준비되면 QP는 비로소 "어디로 보낼지"를 안다. 다음 절은 무엇을 보낼지 — WR 제출과 완료 처리 — 를 다룬다.

## 4. WR 제출과 완료

QP가 RTS에 오르면 남은 일은 두 가지다 — 작업을 큐에 넣는 것(제출)과 끝난 작업을 꺼내는 것(완료). 작업의 단위가 WR(Work Request)이고, 송신은 `struct ibv_send_wr` 체인을 `ibv_post_send`로, 수신 버퍼 게시는 `struct ibv_recv_wr`을 `ibv_post_recv`로 넣는다. 제출한 뒤의 일 — WQE 인출, 패킷 조립, 전송, ACK 처리, 완료 항목(CQE) 적재 — 은 전부 NIC가 한다. CPU가 만지는 곳은 제출과 완료 소비뿐이다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-04-wr-polling.svg" alt="WR 제출과 완료 대기 흐름 — WR 체인 구성, ibv_post_send의 SQ 복사와 doorbell, NIC의 WQE 소비, ACK에 따른 CQE 적재, ibv_poll_cq 루프" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - WR 제출과 완료 대기 다섯 단계. ①②⑤만 사용자 공간(CPU)이고 ③④는 하드웨어다</figcaption>
</figure>

WR을 채우는 세 가지 열쇠는 `opcode`(무엇을 — SEND·RDMA WRITE·READ…), `sg_list`(어디서 — 등록된 MR의 lkey·주소·길이), `next`(체인의 다음 WR)다. 한 번의 `ibv_post_send`로 여러 작업을 묶어 제출할 수 있는 이유가 `next`다. doorbell은 "큐에 새 작업이 있다"는 문 두드리기일 뿐, 내용은 NIC가 SQ에서 DMA로 직접 읽어 간다.

제출과 완료 대기의 실제 모습 — WRITE_WITH_IMM 한 건과 폴 루프 — 을 스켈레톤으로 옮기면 다음과 같다.

```c
/* 제출 — WRITE_WITH_IMM 한 건 */
struct ibv_send_wr wr = {0}, *bad = NULL;
struct ibv_sge sge = {
    .addr = (uintptr_t)buf,  .length = size,
    .lkey = mr->lkey,                            /* 로컬 접근 키 */
};
wr.opcode = IBV_WR_RDMA_WRITE_WITH_IMM;
wr.sg_list = &sge;  wr.num_sge = 1;
wr.wr.rdma.remote_addr = peer_addr;   /* 토큰의 addr 필드 */
wr.wr.rdma.rkey        = peer_rkey;   /* 토큰의 rkey 필드 */
wr.send_flags = IBV_SEND_SIGNALED;    /* 완료 알림(CQE) 요청 */
wr.imm_data   = cookie;               /* 4B 즉값 — 수신측 CQE로 전달 */

ibv_post_send(qp, &wr, &bad);         /* 반환 0 = 성공 */

/* GET용 수신 게시 — 데이터+imm을 받는 zero-SGE recv */
struct ibv_recv_wr rr = {0}, *bad_r = NULL;
ibv_post_recv(qp, &rr, &bad_r);       /* sg_list=NULL — imm만 목적 */

/* 완료 대기 — 폴링 루프 */
struct ibv_wc wc;  int n;
while ((n = ibv_poll_cq(cq, 1, &wc)) == 0)
    ;                                /* CQE가 쌓일 때까지 */
if (n < 0 || wc.status != IBV_WC_SUCCESS)
    die("poll_cq: status=%d", wc.status);
if ((wc.wc_flags & IBV_WC_WITH_IMM) && wc.imm_data == cookie)
    ;  /* 내 전송의 완료 — 버퍼 확정 */
```

완료 확인에는 두 가지 방식이 있다. 폴링은 CQ를 계속 들여다보는 것 — 지연이 짧고 구현이 단순하지만 대기 중 CPU를 계속 쓴다. 이벤트 방식은 `ibv_req_notify_cq`로 알림을 등록해 두고 `ibv_get_cq_event`로 잠들었다가, 깨어난 뒤 `ibv_ack_cq_events`로 알림을 정리하고 다시 폴링으로 CQ를 배수(drain)한다 — CPU는 쉬지만 깨어나는 오버헤드가 붙는다. 어느 쪽이든 CQE를 소비하는 창구는 `ibv_poll_cq`로 같다. 검증 클라이언트는 단일 전송 PoC라 저지연의 폴링으로 충분했다.

> **보고서 실측 — 제출·대기 쌍** · 검증 클라이언트는 이 절의 흐름을 정확히 두 함수로 묶었다 — RDMA WRITE_WITH_IMM 한 건(imm=cookie) 제출과, poll_cq 루프로 imm==cookie 확인(보고서 §8). 방향만 다를 뿐 완료 메커니즘은 양쪽 같다. PUT에서는 서버가 READY 시점에 recv를 게시해 imm을 기다리고, GET에서는 클라이언트가 zero-SGE recv를 게시해 데이터 도착과 imm을 함께 기다린다.

## 5. PSN과 신뢰 전송

RC가 "신뢰 전송"인 까닭은 패킷마다 달리는 PSN(Packet Sequence Number, 24비트) 때문이다. 송신측 QP는 패킷을 보낼 때마다 PSN을 1씩 올리고, 수신측 QP는 자신이 기다리는 PSN과 비교해 정상·중복·순서 어긋을 판정한다. 이 짝의 출발점이 §2의 전이 파라미터다 — 송신측 RTS의 `sq_psn`(첫 패킷의 PSN)과 수신측 RTR의 `rq_psn`(기대 시작 PSN)이 같은 값이어야 첫 패킷이 살아남는다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-05-psn.svg" alt="PSN과 신뢰 전송 — 매 패킷 증가하는 PSN 스트립, 수신측 일치·불일치 판정, ACK 타임아웃 Go-Back-N 재전송과 RNR NAK 타이머, PSN 불일치 경고" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5 - PSN과 신뢰 전송. 일치하면 수용, 기대값보다 낮으면 중복으로 버리되 ACK 재전송, 어긋난 패킷은 조용히 폐기한다</figcaption>
</figure>

판정 규칙은 단순하다. 일치하면 수용하고 rq_psn을 1 올리며 ACK로 승인한다. 기대값보다 낮은 PSN은 중복 패킷 — 버리되 ACK는 다시 보낸다. 기대값에 안 맞는(건너뛴) PSN은 조용히 폐기한다. 이 침묵이 바로 송신측 타임아웃을 유발하는 신호다.

재전송에는 두 개의 트리거가 있다. ACK 타임아웃 — 승인이 `timeout=14`(약 67ms) 안에 오지 않으면 송신측은 아직 승인받지 못한 구간부터 전부 다시 보낸다(Go-Back-N). 최대 `retry_cnt=7`회까지이며 이를 넘기면 `transport retry exceeded`와 함께 QP는 SQE 상태로 빠진다. RNR NAK(Receiver Not Ready) — 수신 큐에 게시된 recv가 없을 때 응답자가 즉시 돌려주는 "준비 안 됨" 신호다. `rnr_retry=7`은 무한 재시도, `min_rnr_timer=12`(640μs)만큼 기다렸다가 다시 보낸다 — 상대가 곧 recv를 게시할 것이라는 기다림이다.

> **이슈⑥ — PSN 불일치: 조용히 드랍되는 첫 패킷** · 검증 클라이언트 초기 버전은 세션 헤더에 랜덤 PSN을 실어 보내면서, 정작 자기 QP의 RTS에는 `sq_psn`을 0x100으로 고정해 두었다. 서버는 헤더가 알려준 PSN으로 rq_psn을 맞추고 데이터를 기다리는데, 실제 첫 패킷의 PSN이 그 값이 아니니 전부 조용히 드랍 — 타임아웃과 재전송만 반복되는 실패가 됐다(증상만 보면 이슈⑤와 구분되지 않는다). 해결은 발급한 PSN을 헤더와 sq_psn 양쪽에 동일하게 쓰는 단일화 하나였다(보고서 §9).

PSN은 cuObject에서 토큰이 아니라 별도 헤더로 전달되는 유일한 좌표다(보고서 §7.1). 이유가 이 절에 있다 — 토큰이 메모리·QP의 정적 좌표라면 PSN은 연결마다 새로 뽑는 난수성 좌표여서, 한 번 발급하면 헤더·sq_psn 어느 쪽에도 흩어지지 않게 단일 소스로 관리해야 한다.

여기까지 오면 verbs 데이터플레인은 완성이다. 마지막 절은 일이 어긋났을 때 — WC 에러 상태를 읽는 법을 다룬다.

## 6. 에러와 WC 상태

verbs 데이터플레인에서 벌어지는 일은 대부분 침묵으로 지나간다 — NIC가 패킷을 조립하고 ACK를 처리하는 동안 CPU는 아무것도 듣지 못한다. 그 현상이 드러나는 유일한 창구가 완료 큐다. `ibv_poll_cq`가 꺼낸 `struct ibv_wc`의 `status` 필드가 0(`IBV_WC_SUCCESS`)이면 성공, 0이 아니면 전부 오류 완료다. 오류 완료에서는 opcode·byte_len·flags가 미정의값이라는 것도 보고서 §10의 CQE 분석이 확인했다 — 판단은 status 하나로만 한다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch05-06-wc-status.svg" alt="WC 상태 분류 — 성공, 로컬 오류, 전송 오류, 원격 오류 네 계급과 오류 후 큐 플러시, 보고서 사례 2건 매핑" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6 - WC 상태의 네 계급. 오류가 보고되면 QP는 SQE 또는 ERROR로 전이하고 잔여 WQE는 WR_FLUSH_ERR 완료로 배출(플러시)된다</figcaption>
</figure>

네 계급을 가르는 관점은 "누가 틀렸는가"다.

| 계급 | 대표 상태 | 의미 — 어디를 들여다봐야 하나 |
|------|-----------|------------------------------|
| 성공 | `IBV_WC_SUCCESS` | opcode·byte_len·imm_data가 비로소 유효. `wr_id`로 원래 WR를 특정 |
| 로컬 오류 | LOC_LEN_ERR · LOC_PROT_ERR 등 | 내가 게시한 WQE 자체의 결함 — SGE 길이가 MR 등록 범위를 넘거나(len), lkey·주소가 범위 밖(prot) |
| 전송 오류 | RETRY_EXC_ERR · RNR_RETRY_EXC_ERR | 재전송 한도 소진 — 상대가 패킷을 받지 못했다는 사실은 알려주지만 원인은 알려주지 않는다 |
| 원격 오류 | REM_INV_REQ_ERR · REM_ACCESS_ERR | 상대측 QP의 기각 — 요청이 무효(remote invalid request)하거나 rkey·접근 권한이 거부됨 |

오류 status를 만나면 두 가지 후속이 따라온다. 첫째 QP의 전이 — RC에서 송신측 오류(재전송 소진 등)는 QP를 SQE로, 원격·수신 오류는 ERROR로 옮긴다. 둘째 큐 플러시 — 이 순간 SQ/RQ에 남아 있던 WQE들은 실행되지 못하고 `WR_FLUSH_ERR` 오류 CQE로 전부 배출된다. 폴 루프는 이 배출물까지 전부 소비(drain)하고 나서야 다음 시도를 준비할 수 있다.

```c
for (;;) {
    n = ibv_poll_cq(cq, 1, &wc);
    if (n == 0) continue;                 /* 아직 완료 없음 */
    if (n < 0) die("poll_cq failed");     /* 폴링 자체 실패 */

    if (wc.status == IBV_WC_SUCCESS) {
        handle(&wc);                      /* 비로소 opcode·byte_len 유효 */
        continue;
    }

    /* 오류 완료 — opcode·byte_len·flags는 미정의값 (보고서 §10) */
    warn("wr_id=%llu status=%d (%s)", wc.wr_id, wc.status,
         ibv_wc_status_str(wc.status));

    if (wc.status == IBV_WC_WR_FLUSH_ERR)
        continue;      /* 플러시 배출 — 남은 WQE가 쏟아지는 중 */

    ibv_query_qp(qp, &attr, IBV_QP_STATE, &init_attr);
    /* SQE=4(송신 오류) · ERROR=6(원격·수신 오류) — 재전이 필요 */
    break;             /* 드레인 후 RESET→INIT→RTR→RTS 재전이 */
}
```

디버깅 관점에서 status는 증상의 주소지 원인이 아니다. 특히 전송·원격 오류는 "상대가 내 패킷을 받지 못했다"는 사실만 말할 뿐, 못 받은 이유 — 라우팅? 좌표? 순서? — 는 CQE 어디에도 없다. 그래서 다음 수는 `ibv_query_qp`로 QP 상태를 확인하는 것이고, 원인 탐색은 게이트웨이 로그·와이어 덤프·최소 프로브의 삼각 측량으로 넘어간다(트러블슈팅 편 §1의 방법론).

> **보고서 사례 매핑 — 같은 문장, 다른 계급** · 검증 여정의 두 사례가 네 계급 읽기를 그대로 보여준다(보고서 §9·§10).
>
> - 이슈⑤ — 클라이언트 로그는 `write: remote invalid request / transport retry`, 즉 원격 오류(REM_INV_REQ_ERR)와 전송 오류(RETRY_EXC_ERR)가 섞여 나왔다. 그러나 원인은 두 계급 어디에도 없었다 — 서버 AH의 `dlid=0` 하드코딩 때문에 패킷이 링크 라우팅 불가로 사라지고(§3), 남은 것은 재전송 소진과 상대측 기각뿐이었다. 패치 6곳의 상세는 트러블슈팅 편 §4.
> - 보류 이슈 — 대형 PUT의 LOC_LEN_ERR. recv 게시가 정상임을 로그로 확인했으므로 "응답자(서버 QP·RQ) 측의 상태 의존 동작"이 좁혀진 채 보류됐고, 후속 검증에서 CX4 VF 환경 한정으로 범위가 더 좁아졌다(트러블슈팅 편 §5).

5편은 여기서 완결이다 — 초기화(§1), 상태 전이(§2), 주소핸들(§3), 제출과 완료(§4), 신뢰 전송(§5), 에러 해석(§6)까지, RC 데이터플레인을 짜는 재료가 전부 모였다. 이 재료로 실제 프로토콜을 조립하는 것 — 좌표를 cuObject 토큰에 담아 2왕복으로 전송을 여는 구조와, 그 클라이언트 절반을 채운 검증 코드 — 이 6편의 주제다.

**다음 편 예고**: [RDMA 학습 시리즈 (6/7): S3-over-RDMA — cuObject 데이터플레인](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에서 이 편의 여섯 단계와 상태머신이 어떻게 토큰 교환 프로토콜로 이어지는지 봅니다. …
