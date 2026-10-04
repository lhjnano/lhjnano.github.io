---
layout: post
title: "cuObject 학습 시리즈 (3/4) cuObject 아키텍처: 세션·토큰·DC 전송"
categories: [GPU, Storage]
description: "S3 API는 그대로 둔 채 어떻게 PUT/GET 본문만 RDMA로 직통할 수 있을까요? cuObject를 이루는 클라이언트와 서버의 분업, DC transport의 선택 이유, 두 가지 전송 모드의 요건까지 정리했습니다."
keywords: [cuObject, libcuobjserver, libcuobjclient, DC transport, DCT, staging MR]
toc: true
toc_sticky: true
---

> cuObject 학습 시리즈 (3/4). NVIDIA GPU I/O 학습 자료와 세션 Q&A(2026-10-04)를 블로그용으로 재구성한 글입니다. 인용하는 실측 값은 내부 검증 클러스터의 CX4(VF) 검증과 CX6(네이티브 IB) 검증에서 나왔습니다.

시리즈 1편은 NIC가 GPU 메모리를 직접 읽게 해 주는 물리적 기반, 그러니까 BAR1 창과 peermem 등록을 다뤘습니다. 2편은 그 위에서 GPU 버퍼를 RDMA에 등록하는 cuFile의 역할을 봤고요. 이번 편에서는 그 기반 둘 위에 올라앉은 주인공을 드디어 해부합니다. 처음 던진 질문은 이것입니다. S3 호환 API는 그대로 유지하면서, 어떻게 PUT/GET 본문만 RDMA로 직통할 수 있을까요?

답의 뼈대는 분업입니다. 클라이언트 쪽의 libcuobjclient가 세션과 토큰을 관리하고, 서버 쪽의 libcuobjserver가 DC QP를 받아서 staging MR로 연결합니다. 그 둘을 잇는 매개가 토큰이고, 토큰이 가리키는 좌표로 데이터가 흐르는 길이 DC(Dynamic Connected) transport입니다. API의 겉모습은 S3인데 속을 열면 전송의 대동맥만 RDMA로 바뀌어 있는 셈이죠.

이 구조를 먼저 읽어 두면 이전에는 수수께끼였던 결과들이 자연스럽게 풀립니다. CX4 검증에서 내려졌던 "cuObject 불가" 판정이 왜 NIC 세대의 문제였는지, host-memory 모드에서 왜 GID 인덱스를 명시해야만 했는지도 이번 편의 5절에서 함께 정리합니다.

## TL;DR

- cuObject는 라이브러리 둘의 분업이다. 클라는 세션·토큰, 서버는 DC QP 수신을 맡는다
- 데이터플레인 DC는 상태를 전송 순간에만 쓴다. 대가는 CX5+ NIC 요건이다
- 제어 평면(HTTP+SigV4)과 데이터 평면(DC QP)이 토큰으로 이어진다
- libcuobjserver 1.x와 2.x는 API가 갈라진다. 기준은 지원 기간이다
- GPU-direct(HBM 직송)와 host-memory(RAM 경유, GID idx0 명시) 두 모드가 있다

## 1. 아키텍처 전체: 클라와 서버

cuObject는 하나의 프로세스가 모든 일을 떠안지 않습니다. 라이브러리 둘이 클라이언트와 서버에 나뉘어 앉아 역할을 분담하는 구조입니다. 어느 쪽이 무엇을 소유하는지를 먼저 구분해 두면 이후 절들이 훨씬 읽기 쉬워집니다.

- 클라이언트(libcuobjclient): 세션과 토큰 관리. 검증 버전은 1.2.0.68이다
- 서버(libcuobjserver): DC QP 수신, 토큰 디코딩, staging MR 준비를 맡는다

서버 쪽 배포는 놀랄 만큼 가볍습니다. 게이트웨이 바이너리와 라이브러리 파일 두 개만 있으면 배포판 내장(inbox) verbs로 동작하고, 기동도 한 줄이면 족습니다. 구축 기록은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에 남겨 둡니다.

```bash
# 게이트웨이 기동 예시(포트와 백엔드 경로는 환경에 맞게)
vgwrdma --port 0.0.0.0:7071 posix /s3-backend/kvcache-s3-<host>
```

요건의 무게가 서버가 아니라 클라이언트 쪽에 실린다는 점, 그러니까 서버는 가볍고 클라가 무겁다는 비대칭이 이 제품의 구조적 특징입니다. 클라이언트 쪽 관문(peermem, BAR1)은 시리즈 1편과 2편에서 이미 짚었고, 두 버전을 나란히 띄운 포트 구성과 배포 절차 상세는 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에 남겨 둡니다. 이 시리즈는 그 위에서 아키텍처 자체를 깊게 봅니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch04-01-cuobject-arch.svg" alt="cuObject 아키텍처 구성도: 클라이언트 GPU 노드(앱, libcuobjclient 세션·토큰 관리, cuFile GPU 메모리 등록, GPU HBM peermem MR 또는 호스트 메모리 MR)와 서버 스토리지 노드(S3 게이트웨이 HTTP 수신, libcuobjserver DC QP·토큰 디코딩, staging MR, posix 스토리지 백엔드)가 제어(HTTP+SigV4)와 데이터(DC QP) 경로로 연결된다"/>
  <figcaption>그림 1: cuObject 아키텍처 전체. 클라(앱 → libcuobjclient → cuFile → GPU HBM)와 서버(S3 게이트웨이 → libcuobjserver → staging MR → posix 백엔드)가 제어(HTTP+SigV4)와 데이터(DC QP) 두 경로로 이어진다. GPU 메모리는 peermem MR로 등록되거나(64 MiB 실증) 호스트 메모리 MR로 대체될 수 있다.</figcaption>
</figure>

## 2. DC (Dynamic Connected) transport: NIC 요건

cuObject의 데이터플레인은 DC(Dynamic Connected) transport입니다. 익숙한 RC(Reliable Connected)와 무엇이 다른지가 이 절의 핵심인데, 차이를 한 표로 압축하면 아래와 같습니다.

| 구분 | DC (Dynamic Connected) | RC (Reliable Connected) |
|------|------------------------|--------------------------|
| 연결 수립 | 동적. 전송 때마다 DCT로 연결을 만들고 해제 | 사전 영구. 1:1 QP 쌍을 미리 INIT→RTR→RTS로 전환 |
| 확장성 | 수만 동시 연결. 서버·팬아웃 구조에 유리 | 연결 수만큼 증가. N×M 연결 폭증 부담 |
| 지원 NIC | ConnectX-5 이상, Mellanox 전용 | 표준 verbs면 충분. 구형 NIC와 타사 NIC 포함 |
| 이 시리즈에서 | cuObject 데이터플레인 | 2차 타겟인 hipobj-rc-v2 계열(AMD·비-ConnectX) |

RC의 세계에서 연결은 자산이 아니라 부채처럼 쌓입니다. QP 하나가 곧 하나의 연결 상태이고, 그 상태가 NIC와 호스트 메모리에 영구 상주하거든요. 클라이언트 N대가 게이트웨이 M대와 통신하려면 N×M쌍의 QP를 미리 다 준비해 둬야 합니다. QP 전환(INIT→RTR→RTS)의 의미가 낯선 분은 [RDMA 학습 시리즈 2편](/2026/09/27/RDMA-Study-02-Fabrics/)을 참고하시면 좋습니다. 어느 쪽이든 규모가 커지면 연결 수가 제곱으로 늘고, 대부분 유휴인 상태들이 메모리만 잡아먹게 되죠.

DC는 이 그림을 뒤집습니다. 서버는 DCT(DC Target)라는 진입점 하나를 열어 두고, 개별 클라이언트와의 연결 상태는 전송이 일어나는 그 순간에만 동적으로 할당했다가 끝나면 해제합니다. 수신 쪽에서는 SRQ(공유 수신 큐)가 여러 연결의 도착 패킷을 한군데서 받아 줍니다. 유휴 클라이언트는 서버에 상태를 아무것도 남기지 않으니, 상주 자원이 연결 수에 비례하지 않습니다. "수만 동시 연결"이라는 표현이 가능한 이유가 바로 이 동적 상태 모델입니다.

> **구형 NIC에서 실패하는 이유**: DC는 DCT를 사용하므로 ConnectX-5 이상의 NIC이 필요하다. CX4는 DCT 미지원이라 연결 수립 단계에서 막힌다. 제약의 정체는 IB 프로토콜이 아니라 NIC 세대와 가상화다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch04-02-dc-vs-rc.svg" alt="DC와 RC 전송 방식 비교: 연결 수립은 동적 DCT 대 사전 영구 1:1 QP(INIT RTR RTS), 확장성은 수만 동시 연결 대 N×M 연결 폭증, 지원 NIC는 ConnectX-5 이상 Mellanox 전용 대 표준 verbs(타사 NIC 포함)"/>
  <figcaption>그림 2. DC와 RC의 대비. 연결 수립 방식, 확장성, 지원 NIC가 갈리고, cuObject가 DC를 택한 대가는 ConnectX-5 이상 요건이다. CX6 네이티브 IB에서 데이터플레인이 완주한 반면 CX4는 DCT 미지원으로 수립 단계에서 막혔다.</figcaption>
</figure>

### 핵심 용어

- **DCT**: 서버 측 DC 수신 진입점 하나가 여러 발신자를 받는다. CX5+ 전용 기능이다
- **SRQ**: 여러 QP가 공유하는 수신 큐. DCT와 함께 수신 자원을 묶는다
- **fan-in**: 다수 클라이언트가 한 서버로 몰리는 형태. DC가 빛나는 조건이다

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu3-q09.svg" alt="스터디 Q&A 카드: DC의 수만 연결로 대형 생성형 AI 회사 운용이 괜찮나요라는 질문에 세션과 연결은 자릿수가 다르고 진짜 상한은 NIC 대역폭과 게이트웨이 처리량이라고 답한다" loading="lazy"/>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu3-q12.svg" alt="스터디 Q&A 카드: AMD나 인텔에서도 DC를 쓰게 작성해야겠네요라는 질문에 DC/RC 선택은 GPU 벤더가 아니라 NIC이 정하며 프로브 후 폴백이 올바른 목표라고 답한다" loading="lazy"/>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu3-q13.svg" alt="스터디 Q&A 카드: 다른 GPU도 DC 지원 NIC를 쓰면 DC 사용이 가능한가요라는 질문에 DCT는 NIC 간 전송 방식이라 GPU 벤더와 무관하며 DC가 필요 없는 환경도 많다고 답한다" loading="lazy"/>
</figure>

## 3. 제어·데이터 평면 분리

cuObject는 두 개의 평면으로 나뉘어 돌아갑니다. 평면을 나눈다는 말은 즉 승인과 대역을 다른 길로 보낸다는 뜻입니다.

- 제어 평면(HTTP+SigV4): 버킷, 세션, 토큰 교환. 표준 S3 인증을 그대로 쓴다
- 데이터 평면(DC QP): PUT/GET 대역. GPU HBM과 staging MR이 직통한다

두 평면을 잇는 것이 토큰입니다. 제어 평면에서 교환해 둔 MR 좌표를 토큰에 실으면, 데이터 평면의 전송이 그 좌표를 향해 이루어집니다. 2편에서 본 cuFile의 등록 작업이 rkey와 addr을 발급했다면, cuObject는 그 좌표를 토큰에 담아 서버에 알리는 역할을 맡는 거죠. 이 분리 덕분에 S3 호환성(인증, 버킷 의미 체계)은 그대로 유지되면서, 대역이 필요한 전송만 RDMA로 내보낼 수 있습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch04-03-two-planes.svg" alt="제어·데이터 평면 분리도: 제어 평면(HTTP+SigV4, 버킷·세션·토큰)과 데이터 평면(DC QP, PUT/GET 대역)이 토큰으로 연결되고 GPU HBM(클라 측 버퍼)과 staging MR(서버 측 준비 버퍼)이 RDMA로 직통한다"/>
  <figcaption>그림 3: 제어·데이터 평면 분리. 제어 평면(HTTP+SigV4, 버킷·세션·토큰)과 데이터 평면(DC QP, GPU HBM ↔ staging MR)이 토큰 하나로 이어진다. 좌표는 제어 평면에서 오가고, 데이터는 그 좌표로 직통한다.</figcaption>
</figure>

### 핵심 용어

- **staging MR**: 서버 측 수신 버퍼. DC QP 전송이 이 버퍼를 거쳐 백엔드로 이어진다
- **SigV4**: AWS S3 요청 서명 체계. 제어 평면이 그대로 사용한다

HTTP 평면과 RDMA 평면을 한 노드에 나란히 띄우는 이중 데이터플레인 운영은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)이 상세히 다룬다.

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu3-q03.svg" alt="스터디 Q&A 카드: VRAM과 S3의 RDMA 주소로 통신한다면 영구 저장은 저장장치에 되겠네요라는 질문에 게이트웨이 메모리는 환적 버퍼일 뿐이며 posix I/O로 백엔드 디스크에 기록된다고 답한다" loading="lazy"/>
</figure>

## 4. libcuobjserver 버전: 1.2.0.68과 2.0.0.109

서버 라이브러리에는 두 계열이 있고, 그 사이에는 하위 호환성이 없는 메이저 전환점이 하나 있습니다. 버전을 고르는 일이 생길 때마다 마주치게 되는 갈림길이죠.

- 1.x(1.2.0.68): 초기 안정 버전. 널리 쓰인다
- 2.x(2.0.0.109): API 불일치로 통합 코드 수정이 필요하다. 성능 차이는 없다

2.x로 옮기려다 컴파일 오류를 만나는 지점을 구체적으로 볼까요. 게이트웨이 래퍼가 호출하는 setTelemFlags의 인자가 1.x의 (unsigned) 하나에서 2.x의 (unsigned, unsigned) 둘로 바뀌었고, initRDMAConfigParams는 아예 사라졌습니다. 그래서 전 처리기로 갈라 쓰는 조건부 분기가 실무의 표준 대응이 됩니다.

```c
/* 메이저 전환 대응: 버전 전 처리기로 갈라 쓴다 */
#if CUOBJ_SERVER_MAJOR_VERSION >= 2
  setTelemFlags(0u, 0u);     /* 2.x: 인자 두 개 (unsigned, unsigned) */
#else
  setTelemFlags(0u);         /* 1.x: 인자 한 개 (unsigned) */
#endif
```

두 버전 간 선택 기준은 성능이 아니라 지원 기간(라이프사이클)입니다. 두 버전은 성능이 동일하고 상호운용도 확인돼 있으니까요. 다만 메이저 전환 작업에서는 두 가지 함정을 기억해야 합니다. 조건부 패치를 넣을 때 이전 빌드의 스테일 아카이브가 남아 심볼 충돌을 일으키는 경우가 있고, 버전 고정(1.x에 머무르는 선택)도 지원 종료 시점을 함께 계획해야 한다는 점입니다. 래퍼 2곳에 조건부 패치를 넣는 실제 작업 기록은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)을 참고하시면 좋습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch04-04-versions.svg" alt="libcuobjserver 1.x(1.2.0.68, 초기 안정·널리 사용, GLIBC_2.14 요구)와 2.x(2.0.0.109, API 불일치로 수정 필요, 조건부 분기 권장) 비교 다이어그램. 성능 차이는 없고 기준은 라이프사이클"/>
  <figcaption>그림 4. libcuobjserver 1.x와 2.x. API는 달라도 성능은 동일하고, 갈림길은 지원 기간(라이프사이클)이다. 메이저 전환 시에는 조건부 분기(CUOBJ_SERVER_MAJOR_VERSION &gt;= 2)를 권장한다.</figcaption>
</figure>

## 5. GPU-direct 모드 vs host-memory 모드

cuObject 계열 클라이언트는 두 가지 모드로 동작합니다. 요건과 한계가 다르니 상황별 선택이 가능한데, 이 요건표가 이번 편의 실전적인 수확이라고 생각합니다.

| 구분 | GPU-direct 모드 | host-memory 모드 |
|------|-----------------|------------------|
| 경로 | 원격 → GPU HBM 직송 (복사 0) | 원격 → 호스트 RAM → cudaMemcpy (복사 1) |
| 요건 | peermem + BAR1 ≥ 전송 크기 + ConnectX | peermem 불필요. GID idx0 명시만 |
| 클라이언트 | libcuobjclient (정식) | libcuobjserver 기반 host 클라 |
| 전송 크기 상한 | BAR1 여유 이하 (192 MiB OK, 224 MiB부터 실패 실측) | BAR1과 무관. 큰 객체도 통과 |

GPU-direct의 요건은 시리즈 1편과 2편에서 쌓은 이야기 그대로입니다. peermem이 GPU HBM을 RDMA에 등록해 주고, 그 등록이 BAR1 창 안에서만 유효하므로 전송 크기는 BAR1 여유를 넘지 못합니다. 검증 클라이언트 RTX A6000(BAR1 256 MiB)에서 192 MiB까지 통과하고 224 MiB부터 등록이 거부된 경계의 상세는 시리즈 2편에서 다룹니다. BAR1 창의 물리적 의미가 궁금하다면 [RDMA 학습 시리즈 1편](/2026/09/27/RDMA-Study-01-Hardware/)도 좋은 참고가 됩니다.

> **host-memory 모드의 함정, GID 자동 선택**: host 클라이언트의 GID 자동 선택이 link-local(fe80::) 주소를 건너뛰도록 짜여 있었습니다(RoCE 전제, rdma_host_client_wrapper.cpp:131). 네이티브 IB에서는 유효 GID가 idx0 하나뿐이므로 `VGWRDMA_GID_INDEX=0` 명시가 필수입니다. 반면 GPU-direct의 cuFile은 GID idx0을 자동으로 처리합니다("using default GID index 0" 로그로 확인).

host-memory 모드는 요건이 가벼운 만큼 성능이 궁금해지는 지점인데, 이 모드에서도 RDMA가 우위를 지킵니다. HTTP 쪽이 IPoIB(MTU 1500, datagram)을 타야 하는 환경 특성이 격차의 배경입니다(MTU 이중구조는 [RDMA 학습 시리즈 2편](/2026/09/27/RDMA-Study-02-Fabrics/) 참조). 수치 실측은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에 정리돼 있습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch04-05-modes.svg" alt="두 가지 모드 비교: GPU-direct 모드(원격에서 GPU HBM 직송, 복사 0, peermem과 BAR1 요건, ConnectX 필요)와 host-memory 모드(원격에서 호스트 RAM을 거쳐 cudaMemcpy, 복사 1, GID idx0 명시만 요구, BAR1 한계 없음)"/>
  <figcaption>그림 5: GPU-direct 모드(HBM 직송, peermem + BAR1 + ConnectX 요건)와 host-memory 모드(RAM 경유, GID idx0 명시만 요구). BAR1 여유가 부족하면 host-memory 모드로 내려가고, 토큰 프로토콜은 두 모드가 동일하다.</figcaption>
</figure>

## 마무리: 핵심 요점

1. cuObject는 라이브러리 둘의 분업이다. 클라는 세션·토큰, 서버는 DC QP 수신을 맡는다
2. DC의 핵심은 DCT 상태 모델이다. 상주 자원 없이 수만 동시 연결을 흡수한다
3. 대가는 NIC 세대다. CX5+ 요건이 CX4 VF 검증 실패의 진짜 원인이었다
4. 두 평면의 분리와 토큰이 S3 호환성과 RDMA 직통을 동시에 만족시킨다
5. 버전 갈림길의 기준은 라이프사이클이다. API 차이는 조건부 분기로 흡수한다
6. 요건이 갖춰지면 GPU-direct, 아니면 host-memory(GID idx0 명시)로 내려간다

**다음 편 예고**: [cuObject 학습 시리즈 (4/4) 생태계](/2026/10/04/cuObject-Study-04-Ecosystem/)에서는 NIXL과 LMCache, elbencho까지, 실전에서 누가 cuObject를 소비하는지 둘러봅니다. 아키텍처가 끝난 자리에서 생태계가 시작됩니다.
