---
layout: post
title: "RDMA 학습 시리즈 (3/7): 소프트웨어 스택 — verbs·MOFED·컨테이너 RDMA"
categories: [RDMA, Networking]
description: "RDMA는 정말 커널 없이 동작할까요? verbs 스택의 다섯 층과 MOFED 대 inbox, 디바이스 노드 열거, 컨테이너 디바이스 전달까지 실측으로 정리했습니다."
keywords: [RDMA, verbs, libibverbs, MOFED, inbox, rdma_cm, 컨테이너]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (3/7). 소스: 검증 클러스터 S3-over-RDMA 검증 보고서(2026-09-22~26) 실측 기반. 시리즈 1·2편이 하드웨어와 패브릭을 다뤘다면, 이번 편부터 소프트웨어의 차례입니다.

1편에서 HCA라는 하드웨어가 어떻게 커널 바이패스를 가능하게 하는지 보았습니다. 그렇다면 남은 질문은 하나입니다. 애플리케이션은 그 능력을 누구를 통해서, 어떤 경로로 빌려 쓸까요?

이 글은 그 답을 다섯 층의 계층도에서 시작해 두 가지 verbs 스택(MOFED·inbox)의 선택 문제, 디바이스 노드와 열거, verbs API의 동사들, 컨테이너에서 RDMA를 돌리는 조건, 그리고 층별 진단 도구까지 내려갑니다. 특히 흥미로운 지점은 검증이 밝힌 반전입니다. 스토리지 노드에는 MOFED가 아예 필요 없었다는 사실말이죠.

## TL;DR

- 스택은 다섯 층: 애플리케이션 → libibverbs/librdmacm → uverbsN 노드 → mlx5_core → HCA
- 커널이 우회하는 것은 데이터뿐. QP·MR 생성 같은 제어는 여전히 커널을 경유
- 같은 mlx5_core라도 MOFED(벤더·dkms)와 inbox(커널 내장) 두 가지 조달이 갈린다
- 검증 반전: 스토리지 노드는 inbox verbs로 충분. MOFED는 클라이언트(GPU 노드) 요건이었다
- "libcuobjserver는 el9 필요"는 오류 — 제약은 NVIDIA 패키징뿐, 심볼은 el8로 충분
- 컨테이너 RDMA의 핵심은 디바이스 노드·/sys·memlock 전달 네 가지 묶음
- 도구는 층마다 다르다: ibstat(L1) → ibping(L2) → ib_write_bw(L4) → 애플리케이션(L5)

## 1. 전체 스택 계층 — 제어 경로와 데이터 경로

RDMA 소프트웨어 스택은 위에서부터 다음 다섯 층으로 요약됩니다.

1. 애플리케이션 — 검증 사례로는 S3 게이트웨이(vgwrdma), NVIDIA 정식 클라이언트 라이브러리(libcuobjclient)와 그 위의 GPU 애플리케이션, 대역폭 측정 도구(perftest 계열의 ib_write_bw 등)입니다.
2. 사용자 공간 라이브러리 — libibverbs(verbs API)와 librdmacm(연결 관리). 애플리케이션이 직접 호출하는 사실상 유일한 층입니다.
3. 디바이스 노드 — /dev/infiniband/uverbsN. 사용자 공간과 커널 사이의 문이자 ioctl 경계입니다(3절에서 상세).
4. 커널 드라이버 — mlx5_core. QP·MR 같은 커널 리소스를 만들고 검증하며 HCA를 초기화합니다.
5. HCA — ConnectX-4(VF). RDMA 엔진·QP 컨텍스트·MTT를 품고 실제 전송을 수행합니다(1편 그림 1의 카드 내부).

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-01-stack-layers.svg" alt="RDMA 소프트웨어 스택 계층도 — 사용자 공간(애플리케이션, libibverbs·librdmacm), 커널 공간(/dev/infiniband/uverbsN, mlx5_core), HCA 하드웨어와, 파란 제어 경로 화살표 및 초록 데이터 경로 우회선" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - RDMA 소프트웨어 스택. 제어 경로(파랑)는 모든 층을 관통해 내려가지만, 데이터 경로(초록)는 등록된 사용자 버퍼와 HCA 사이를 직접 오가며 커널을 지나지 않는다</figcaption>
</figure>

### 왜 화살표가 두 벌인가

그림 1에서 화살표가 두 가지 색인 이유가 이 글 전체를 관통하는 핵심입니다. RDMA는 흔히 "커널을 우회한다"고 요약되지만, 정확히 말해 우회하는 것은 데이터뿐입니다.

- 제어 경로(파랑): QP 생성, 메모리 등록(MR), 연결 상태 전환 같은 설정 행위는 커널을 경유합니다. libibverbs가 명령을 uverbsN 노드로 ioctl을 통해 내려보내면 mlx5_core가 요청을 검증하고 HCA에 자원을 반영합니다.
- 데이터 경로(초록): 설정이 끝난 뒤의 실제 페이로드는 커널을 전혀 지나지 않습니다. HCA가 미리 등록된 버퍼의 물리 주소를 MTT로 알고 있으므로 애플리케이션 버퍼와 HCA 사이는 PCIe DMA로 직통합니다. 복사도, 문맥 전환도 없습니다.

데이터 경로의 건강함은 raw RC 전송으로 확인됐습니다. 크로스노드 ib_write_bw 8QP에서 196.1 Gb/s, 이어진 검증에서도 같은 계층의 GET 방향 raw 전송이 196 Gb/s(8QP)를 기록했습니다(보고서 §6.2). "한 번 설정하면 데이터는 커널을 모르는 척한다"는 이중 구조가 열쇠인데, 두 경로의 운명은 다릅니다. 데이터 경로는 한 번 열리면 빠르지만 제어 경로가 순조로워야만 열립니다. 8편의 디버깅 이야기 대부분이 제어 경로에서 벌어진 일입니다.

> **커널 바이패스 ≠ 커널 불필요.** 데이터가 커널을 지나지 않아도 제어 경로는 여전히 커널·디바이스 노드·/sys에 의존합니다. uverbsN이 보이지 않거나 /sys/class/infiniband/가 비어 있으면 verbs는 디바이스를 열거조차 하지 못합니다. 컨테이너에서 RDMA가 "라이브러리는 있는데 디바이스가 안 보인다"로 실패하는 대부분의 원인이 여기에 있습니다.

이 절의 용어 네 가지를 짚고 갑니다. verbs는 RDMA 프로그래밍 인터페이스의 총칭으로, 디바이스 열기·메모리 등록·WR 게시 같은 행위의 모음입니다. uverbs는 그중 사용자 공간 진입점이며 물리적 실체가 uverbsN 노드입니다. libibverbs는 verbs API를 구현한 라이브러리(ibv_ 접두사 함수군)이고, librdmacm은 rdma_ 접두사의 주소 해석·연결 수립 API를 제공하는 짝입니다. 표준 verbs만 쓰면 밑에 깔린 스택이나 벤더 확장에 덜 종속됩니다.

## 2. MOFED vs inbox — 두 가지 verbs 스택

그림 1의 다섯 층 중 사용자 공간 라이브러리와 커널 모듈은 두 가지 방식으로 조달할 수 있습니다. 하나는 NVIDIA(Mellanox)가 배포하는 벤더 스택 MLNX_OFED(통칭 MOFED)이고, 다른 하나는 리눅스 커널·배포판에 이미 들어 있는 inbox 스택입니다. 같은 mlx5_core라도 어디서 왔는지에 따라 기능 시점과 운영 부담이 갈립니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-02-mofed-inbox.svg" alt="MLNX_OFED와 inbox 두 verbs 스택 비교도 — 좌측 OFED(벤더 라이브러리 + dkms 재빌드된 커널 모듈), 우측 inbox(배포판 라이브러리 + 커널 내장 모듈), 각각의 장단점과 공통 결론" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - 두 가지 verbs 스택. 어떤 스택이든 표준 verbs API는 양쪽에서 동일하다</figcaption>
</figure>

| 구분 | MLNX_OFED (벤더 스택) | inbox (커널 내장 스택) |
|------|----------------------|----------------------|
| 사용자 공간 | OFED 라이브러리 + 벤더 provider | 배포판 패키지(libibverbs 등) |
| 커널 모듈 | dkms 재빌드로 교체 — 검증 환경: 클라이언트 gpu-1 | 커널 소스 트리에 내장 — 검증 환경: 게이트웨이 stg-node1·stg-node2(4.18.0-553 포함분) |
| 강점 | 최신 기능·신형 HCA 지원이 우선 반영 | 배포판 QA를 거친 안정성 |
| 대가 | 커널 업데이트마다 dkms 재빌드 수반 | 신기능 수용이 커널 릴리스 주기에 종속 |

dkms(Dynamic Kernel Module Support)는 커널 버전이 바뀔 때마다 외부 모듈을 자동으로 다시 컴파일해 붙이는 메커니즘입니다. MOFED가 사실상 커널의 RDMA 부분을 통째로 갈아끼우는 스택인 이유이기도 합니다. 신기능을 빨리 쓸 수 있지만 커널 업데이트와 재빌드가 서로를 기다리는 운영 비용이 따르고, inbox는 그 반대로 기능은 늦게 들어와도 배포판이 전체를 책임집니다.

혼용 환경의 실측도 있습니다. MOFED(클라이언트)와 inbox(서버)가 섞인 구성에서도 cuObject의 DC 전송이 성공했습니다. 표준 verbs 위에서 동작하는 한 스택 선택은 이식성의 장애가 되지 않는다는 원칙의 근거입니다.

### 검증의 반전 — 서버에서는 MOFED가 필요 없었다

앞의 호환성 이야기가 "양쪽 스택 모두 표준 verbs를 소화한다"였다면, 검증은 결론을 한 단계 끌어올립니다. 이번 상대는 표준 verbs만 쓰는 구현이 아니었습니다. NVIDIA cuObject의 서버 라이브러리 libcuobjserver(1.2.0.68·2.0.0.109)는 벤더 폐쇄 라이브러리고, Mellanox 전용 전송인 DC(Dynamically Connected) QP를 `mlx5dv_create_qp`로 생성합니다.

그런데 이 라이브러리조차 Rocky 8.10 게이트웨이(stg-node1·stg-node2)의 inbox verbs 위에서 MOFED·컨테이너 없이 네이티브 구동됐습니다. DC QP 생성과 INIT→RTR→RTS 상태 전환이 전부 통과했고(보고서 §3), 클라이언트(libcuobjclient, GPU-direct)는 4~192 MiB 전 구간에서 GPU HBM 직송 PUT/GET checksum에 통과했습니다(보고서 §4). 예전 실험의 inbox 스택에서 관찰됐던 malformed WR 거부(로컬 오류)도 재현되지 않았습니다. 스토리지 노드엔 MOFED가 불필요 — 이것이 검증이 확정한 결론입니다.

그렇다면 MOFED는 이제 누구의 요건일까요. 답은 클라이언트(고객 GPU 노드)입니다. GPU-direct 클라이언트의 cuFile은 nvidia_peermem 모듈(또는 dma-buf 경로)이 없으면 RDMA를 아예 비활성합니다. "nvidia_peermem.ko is not loaded. Disabling UserSpace RDMA access"라는 로그가 바로 그 순간입니다. 그런데 peermem은 MOFED ib_core가 제공하는 `ib_register_peer_memory_client` 등록 인터페이스를 요구합니다(보고서 §5). 이렇게 MOFED의 자리는 서버 요건에서 클라이언트 요건으로 재정의됩니다.

| 노드 | 스택 요건 | 근거 |
|------|----------|------|
| 서버 — 검증 클러스터 스토리지 노드(stg-node1·stg-node2) | inbox verbs 그대로. MOFED·컨테이너·패키지 설치 어느 것도 불필요, 배포는 바이너리 2개(아래 정정 참조) | 보고서 §3 |
| 클라이언트 — 고객 GPU 노드(GPU-direct) | MOFED + `nvidia_peermem`. 또는 대안 A(미검증): nvidia open-dkms + `CUFILE_DMABUF_ENABLE`로 `ibv_reg_dmabuf_mr` 경로를 타면 inbox rdma-core만으로 구성 — 제품 방향으로 유력 | 보고서 §5 |

이번 검증이 클라이언트 요건을 채운 방식은 MOFED 위에 peermem을 올리는 경로였습니다. 일회성 커널 부팅(5.14.0-570.32.1.el9_6) + dkms nvidia 빌드 + modprobe nvidia_peermem의 조합이죠. 대안 A가 열어줄 "MOFED 없는 클라이언트"는 아직 미검증이지만, 커널 요건이 단일 벤더 스택에서 표준 인터페이스(dma-buf + rdma-core)로 좁아지는 구성이라 주목할 후보입니다.

### "el9 필요"의 정정 — 제약은 NVIDIA 패키징뿐

앞의 반전에는 통설을 뒤집는 확인 작업이 담겨 있습니다(보고서 §3). "libcuobjserver는 rhel9용 패키지만 있으니 게이트웨이는 el9"라는 노트는 검증 없이 계승된 오류였습니다. NVIDIA의 공식 리포에는 rhel8용 server 패키지가 없을 뿐, 라이브러리 바이너리가 요구하는 심볼 버전은 el8이 갖춘 것보다 오래됐습니다.

| 확인 항목 | 결과 |
|----------|------|
| NVIDIA 공식 리포 | rhel8: libcuobjclient만 존재(server 패키지 없음) / rhel9: libcuobjserver 1.2.0.68·2.0.0.109 |
| libcuobjserver.so 요구 심볼 | 최대 GLIBC_2.14(1.2)·GLIBC_2.16(2.0), GLIBCXX_3.4.21 — el8(glibc 2.28, GLIBCXX 3.4.25)로 충분 |
| DT_NEEDED(동적 의존) | libibverbs·librdmacm·libmlx5·libnuma·libstdc++ — 게이트웨이(stg-node1)에서 ldd 결손 0 |

해법은 그래서 단순해집니다. rhel9 rpm에서 libcuobjserver.so를 추출해 el8에 그대로 실행하면 됩니다. 실제 배포는 vgwrdma 바이너리 + libcuobjserver.so.1.2.0(심링크 .so.1) 두 파일로 끝났고 설치된 패키지는 0건이었습니다. "게이트웨이엔 바이너리만 배포(패키지 설치·커널 변경 금지)"라는 제품 제약과 정확히 부합하는 결과이고, 위 반전의 실증(DC QP 생성·INIT→RTR→RTS 통과)이 바로 이 배포 위에서 나왔습니다.

버전을 다룰 때의 주의 한 가지. versitygw v1.8.0은 libcuobjserver 1.x API 전용이라 2.0(2.0.0.109)으로 빌드하면 `setTelemFlags` 시그니처 변경과 `initRDMAConfigParams` 삭제로 컴파일이 실패합니다. 2.x 지원은 조건부 패치가 필요하다는 점을 기억해 두세요(보고서 §3.2).

## 3. 디바이스 노드와 열거 — /dev/infiniband/와 /sys/class/infiniband/

1절의 계층도에서 "문"이라 했던 것이 /dev/infiniband/ 디렉터리입니다. 사용자 공간 verbs가 커널·하드웨어와 만나는 물리적 지점이며, RDMA 디바이스가 있으면 여기에 다음 노드들이 생깁니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-03-device-nodes.svg" alt="/dev/infiniband/ 디바이스 노드와 용도 — uverbs0·uverbs1(verbs 명령 통로), rdma_cm(연결 관리), umad0·issm0(서브넷 관리), 그리고 컨테이너 개별 전달·/sys:ro 주석" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - /dev/infiniband/의 노드들과 용도. uverbsN(파랑)은 디바이스당 하나씩 붙는 verbs 명령 통로, rdma_cm(보라)은 연결 관리 채널, umad0·issm0(청록)은 서브넷 관리 통신용이다</figcaption>
</figure>

| 노드 | 대상 | 용도 |
|------|------|------|
| `uverbs0` | mlx5_0 (디바이스 0) | verbs 명령 통로(ioctl) — QP·MR·CQ의 생성·조작. RDMA 디바이스당 하나씩 생긴다 |
| `uverbs1` | mlx5_1 (디바이스 1) | 같은 역할 — 두 번째 HCA(VF)용 통로 |
| `rdma_cm` | 공통 | 연결 관리 — librdmacm의 연결 설정·주소 해석이 지나가는 커널 채널 |
| `umad0` | mlx5_0 포트 0 | MAD 송수신(사용자 공간) — SA 조회, perfquery 같은 카운터 조회 등 관리 통신 |
| `issm0` | mlx5_0 포트 0 | SM을 향한 인터페이스 — 서브넷 관리자(opensm)와 LID·포트 관리를 주고받는다 |

### 열거 도구 — 무엇이 보이는지 확인하는 세 가지 명령

스택 점검의 첫 단추는 "이 시스템에 RDMA 디바이스가 어떻게 보이는가"입니다. 자주 쓰는 세 도구는 보는 관점이 다릅니다. ibv_devices는 존재 목록, ibv_devinfo는 verbs 관점의 상세, ibstat은 링크 관점(LID·Rate·MTU)의 상태를 보여줍니다.

```text
$ ibv_devices
    device           node GUID
    ------           ----------------
    mlx5_0           0122330005018691
    mlx5_1           0122330005018692
```

```text
$ ibv_devinfo -d mlx5_0
hca_id: mlx5_0
        transport:      InfiniBand (0)
        fw_ver:         12.28.2002
        port:   1
                state:          PORT_ACTIVE (4)
                active_mtu:     4096 (5)
                port_lid:       0x3fa
                link_layer:     InfiniBand
```

```text
$ ibstat mlx5_0
CA 'mlx5_0'
        CA type: MT4115
        Firmware version: 12.28.2002
        Port 1:
                State: Active
                Physical state: LinkUp
                Rate: 100
                Base lid: 0x3fa
                Link layer: InfiniBand
```

출력은 실제 도구들의 포맷을 따른 예시입니다. 포트 상태(ACTIVE)·active_mtu 4096·port_lid 0x3fa는 예전 검증 환경에서 얻은 교육용 값이며, node GUID 0122:3300:0501:8691은 보고서에 기록된 링크 로컬 GID(fe80::122:3300:501:8691)에서 유도한 것입니다. port_lid 0x3fa가 1·2편에 등장했던 바로 그 LID입니다. SM이 이 디바이스에 부여한 패브릭 좌표라는 점에서, 열거 도구의 출력이 곧 패브릭의 눈에 보이는 모습이라고 할 수 있습니다.

### /sys/class/infiniband/ — 열거의 또 다른 반쪽

ibv_devices가 보여주는 목록의 출처는 사실 커널이 유지하는 /sys/class/infiniband/입니다. verbs 라이브러리는 디바이스를 열거할 때 이 디렉터리를 조회하므로, "디바이스가 있는데 왜 안 보이나"의 답은 대개 여기에 있습니다.

```text
$ ls /sys/class/infiniband/
mlx5_0  mlx5_1
$ cat /sys/class/infiniband/mlx5_0/node_guid
0x0122330005018691
```

## 4. verbs API — 다섯 동사와 네 동사

3절의 디바이스 노드를 열었다면 이제 그 위에서 부르는 동사들입니다. libibverbs의 함수군은 쓰임새로 세 묶음입니다. 리소스 생성(제어 경로의 동사들), 통신(데이터플레인의 동사들), 그리고 주소·연결(rdma_cm의 몫). 그림 4가 세 묶음과 호출 체인을 정리합니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-04-verbs-api.svg" alt="libibverbs verbs API 함수군 분류도 — 왼쪽 리소스 생성(open_device→alloc_pd→create_cq→create_qp→reg_mr 체인, 파랑), 가운데 통신(post_send·post_recv·poll_cq·create_ah, 초록), 오른쪽 주소·연결(rdma_cm 함수군, 보라)과 5편 예고 박스" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - verbs API 함수군 분류. 리소스 생성(파랑)은 초기화 체인이고(1절의 제어 경로), 통신(초록)은 설정이 끝난 뒤 오가는 데이터플레인의 동사들이다</figcaption>
</figure>

### 리소스 생성 — 제어 경로의 동사들

왼쪽 열의 다섯 함수는 호출 순서 그대로 초기화 체인을 이룹니다. `ibv_open_device`가 uverbsN 노드를 통해 디바이스 컨텍스트를 얻어오고, `ibv_alloc_pd`는 이후 리소스들을 묶을 보호 도메인(PD)을 만듭니다. `ibv_create_cq`는 완료 통지가 도착할 완료 큐(CQ)를, `ibv_create_qp`는 RC 연결의 양 끝이 될 큐 페어(QP)를 생성합니다.

마지막 `ibv_reg_mr`이 전송에 쓸 사용자 버퍼를 등록해 물리 주소를 HCA의 MTT에 반영합니다. 그림 1의 초록 데이터 경로가 뚫리는 순간입니다. 다섯 동사 모두 1절의 제어 경로, 즉 커널을 경유하는 설정 행위라는 점을 놓치지 마세요.

### 통신 — 데이터플레인의 동사들

설정이 끝나면 남는 것은 네 동사입니다. `ibv_post_send`는 송신 작업(WR)을 게시하는데, 상대 메모리를 직접 읽고 쓰는 RDMA WRITE·READ도 여기서 시작됩니다. `ibv_post_recv`는 도착할 데이터를 받을 수신 버퍼를 미리 걸어두고, `ibv_poll_cq`는 완료 큐에서 완료 항목(CQE)을 회수합니다. `ibv_create_ah`는 목적지 GID·LID를 담은 주소 핸들(AH)을 만듭니다.

이 시점의 동사들은 커널을 지나지 않습니다. cuObject 클라이언트도 이 동사들을 래핑해 씁니다(6편).

### 주소와 연결 — rdma_cm

libibverbs는 "어디로 연결할지"를 스스로 알아내지 않습니다. 주소 해석과 연결 수립은 librdmacm(rdma_cm)의 역할입니다. rdma_create_id로 식별자를 만들고, rdma_resolve_addr·rdma_resolve_route으로 주소와 경로를 풀고, rdma_connect/accept로 RC 연결을 맺는 것이 표준 경로입니다.

다만 연결 좌표를 이미 안다면 이 경로 전체를 생략할 수 있습니다. cuObject의 토큰 프로토콜이 그 사례입니다. 토큰에 상대의 GID·QP 번호가 실려 오므로 클라이언트는 rdma_cm 없이 토큰의 좌표로 QP를 곧바로 RTR·RTS로 옮깁니다(6편). 실전 구현은 5편 「verbs 프로그래밍」에서 초기화 시퀀스·QP 상태 전이·AH 구성을 코드로 다룹니다.

> **실측 — 서버 측도 표준 verbs(dlopen shim).** 서버(vgwrdma)와 클라이언트(libcuobjclient) 모두 런타임에 libibverbs를 동적 로딩하도록 짜여 있어, 그 아래 깔린 스택이 MOFED인지 inbox인지 따지지 않고 양쪽에서 동작했습니다. 당시 정리는 "DC/mlx5dv/CUDA는 어디에도 필요 없다". 검증은 이 문장의 범위를 분명히 합니다. 데이터플레인의 서버(libcuobjserver)는 DC QP에 mlx5dv 확장을 쓰지만 그마저 el8 inbox verbs에서 소화되므로, 서버 커널에 부과되는 요건은 데이터플레인을 골라도 여전히 없습니다. 함수 이름이 곧 공통 문법이고, 공통 문법이 곧 이식성입니다.

## 5. 컨테이너에서 RDMA

3절의 복선을 회수합니다. 초기 시험에서 RDMA 게이트웨이 vgwrdma는 별도 노드에서 podman 컨테이너로 구동됐습니다. 컨테이너 이미지(vgwrdma-builder:local, rhel9 + CUDA)는 verbs 라이브러리와 빌드 도구를 스스로 갖고 있지만, 디바이스 노드·/sys·Lustre 마운트는 호스트가 넘겨줘야만 합니다. 그림 5가 이 컨테이너 구성 전체를 재현한 것입니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-05-container-rdma.svg" alt="podman 컨테이너 게이트웨이 구성도 — 호스트의 /dev/infiniband 노드 5개(uverbs0·1·rdma_cm·umad·issm)가 개별 --device로 전달되고, /sys는 읽기 전용, 소스 트리와 Lustre 마운트는 bind, 호스트 능력(--net host·memlock=-1·IPC_LOCK)이 부여되어 컨테이너 안 vgwrdma가 :7071로 구동" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5 - 컨테이너에서 RDMA(실험 구성 재현). 호스트(좌)에서 컨테이너(우)로 넘어가는 다섯 지점: --device 개별 전달, /sys:ro 마운트, bind 2건, 그리고 --net host·memlock=-1·IPC_LOCK 능력 부여</figcaption>
</figure>

구성을 묶음으로 정리하면 넷입니다.

1. 디바이스 — uverbs0·uverbs1·rdma_cm·umad·issm 다섯 노드를 개별 `--device`로 하나씩 전달합니다.
2. /sys:ro — verbs의 디바이스 열거는 /sys/class/infiniband/ 조회가 필요하므로 읽기 전용이라도 마운트가 필수입니다.
3. bind 2건 — 소스·빌드 트리는 /workspace로, /mnt/lustre는 /lustre로(백엔드 저장소) 연결됐습니다.
4. 능력 부여 — `--net host`로 호스트 네트워크를 공유해 7071 리슨을 가능하게 하고, memlock=-1과 IPC_LOCK으로 MR이 물리 메모리에 제한 없이 고정되게 합니다.

등록된 버퍼가 스왑아웃되는 순간 RDMA 전송은 무너지므로, 마지막 두 설정은 성능이 아니라 정합성의 조건입니다.

### 실행 — 컨테이너 안의 한 줄

이 구성 위에서 게이트웨이가 실행하는 명령은 다음 한 줄입니다.

```bash
$ VGW_RDMA_IP=100.64.33.243 vgwrdma --port 0.0.0.0:7071 posix /lustre
```

읽는 순서는 이렇습니다. 7071에서 S3 API를 리슨하고(--net host이므로 호스트 포트 그대로), VGW_RDMA_IP(또는 --rdma-ip 옵션)가 cuObject 데이터플레인을 켜며, 백엔드는 posix로 /lustre를 객체 저장소로 삼습니다. 클라이언트(libcuobjclient)와 주고받는 프로토콜은 6편, /lustre 아래의 스토리지 스택은 7편에서 다룹니다.

> **실측 — 컨테이너에서 네이티브로, 제품 형태의 수렴.** 위 구성은 초기 시험(rhel9 + CUDA 컨테이너 이미지)의 기록입니다. 검증의 게이트웨이(stg-node1·stg-node2)는 반대편 끝에서 출발했습니다. podman조차 설치돼 있지 않은 el8 노드에서, vgwrdma와 libcuobjserver.so 두 파일만으로 컨테이너도 MOFED도 없이 inbox verbs 위에서 네이티브 구동을 이뤘습니다(보고서 §3). 컨테이너는 검증용 편의장치였지 RDMA의 필요조건이 아니었습니다. 디바이스 노드와 /sys 열거는 네이티브에서 커널이 처음부터 제공하고, 라이브러리 종속은 ldd로, 메모리 고정은 memlock 한도로 확인하면 됩니다. 이 절의 네 가지 묶음은 컨테이너를 걷어낸 뒤에도 네이티브 구동의 점검 목록으로 그대로 이전됩니다.

## 6. 진단 도구 — 층마다 다른 눈

이 글을 닫으며 스택 점검 도구를 한 장의 지도로 정리합니다. 3절에서 열거 도구 세 가지를, 5절에서 컨테이너 구성을 봤는데, 그 사이에 놓인 원칙이 하나 있습니다. 도구는 각자 확인하는 층이 다르다는 것. 링크를 보는 도구로 디바이스를 진단하거나, IP가 통한다고 RC 전송을 보장받으려 하면 헛돕니다.

<figure>
  <img src="/assets/images/posts/rdma-study/ch03-06-tools.svg" alt="진단 도구 지도 6행 — ibstat·ibstatus(L1 링크), ip addr·ping(IPoIB), ibv_devinfo(디바이스), ibping(L2 도달성), ib_write_bw·ib_read_bw·ib_send_bw(L4 대역폭), 애플리케이션 세션(L5)이 왼쪽 확인 순서 화살표로 이어짐" loading="lazy">
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6 - 진단 도구 지도. 왼쪽 화살표가 확인 순서다. L1~L4 전 층이 정상이어도 L5 세션은 별도 확인 대상이며, 8편이 이 지도를 판정(PASS/FAIL) 사다리로 다시 그린다</figcaption>
</figure>

| 층 | 도구 | 확인 대상 |
|----|------|----------|
| L1 링크 | `ibstat` · `ibstatus` | 포트 State/LinkUp · Rate · LID · MTU — 물리 링크의 건강(3절 출력 예시) |
| IPoIB | `ip addr` · `ping` | ib0에 172.16.44.x/24 부여와 IP 왕복 — IB 위의 IP 계층(2편) |
| 디바이스 | `ibv_devinfo` | verbs 관점 상세 — phys_port_cnt · active_mtu · sm_lid(3절) |
| L2 도달성 | `ibping` | IP를 거치지 않고 IB 링크 계층에서 LID로 직접 왕복 |
| L4 대역폭 | `ib_write_bw` · `ib_read_bw` · `ib_send_bw` | RC WRITE · READ · Send 동사별 전송 처리량(perftest) |
| L5 세션 | 애플리케이션 | libcuobjclient ↔ vgwrdma(cuObject) — 실제 서비스 동작 |

연결성 도구 둘의 갈림길을 짚어두겠습니다. ping은 IPoIB, 곧 IB 위에 올린 IP 스택을 지나갑니다. 이 경로가 통해도 RC QP 전송과는 층이 다르다는 것이 2편의 경고였습니다. ibping은 그 아래, IP를 아예 거치지 않고 IB 링크 계층에서 LID로 상대에게 직접 왕복합니다. 한쪽을 서버 모드(`ibping -S`)로 띄우고 반대쪽에서 상대 LID(`-L`) 또는 GID(`-G`)를 지정하면 링크 계층의 도달성만 분리해 확인할 수 있습니다.

perftest 삼형제의 이름은 4절의 통신 동사와 정확히 맞물립니다. ib_write_bw·ib_read_bw·ib_send_bw는 각각 RDMA WRITE, RDMA READ, Send/Recv를 측정합니다. 도구 이름이 곧 `ibv_post_send`의 opcode이므로, 애플리케이션이 쓸 전송 유형과 같은 동사의 도구로 측정하면 됩니다.

### 실전 예시 — ib_write_bw 서버와 클라이언트

```bash
# 서버(게이트웨이 node-b) — -R은 rdma_cm으로 연결 수립(4절의 rdma_ 동사 경로)
$ ib_write_bw -d mlx5_0 -R
# 클라이언트(node-a) — 서버 주소를 지정해 측정 시작
$ ib_write_bw -d mlx5_0 -R 172.16.44.41
```

`-R`은 연결 수립에 rdma_cm을 쓰는 옵션입니다. 기본 동작처럼 파라미터 교환용 TCP 소켓을 여는 대신, rdma_resolve_addr → rdma_connect로 양단을 잇습니다. 도구 하나가 제어 경로(rdma_cm 연결)와 데이터 경로(RC WRITE)를 함께 보여주는 셈입니다.

> **실측 — L4 ib_write_bw = 196.1 Gb/s(8QP).** 계층 진단에서 이 명령은 L4(raw RC RDMA)의 probe였습니다. 크로스노드 196.1 Gb/s(8QP)로 RC QP 전송 자체가 완전히 건강함을 증명했고, L1(링크 ACTIVE)·L2(IPoIB ping)·L3(Lustre IO)까지 전부 정상이었는데 처음으로 FAIL이 뜬 곳은 L5의 cuObject 세션이었습니다. "막힌 것은 하드웨어가 아니라 그 구현"이라는 판정의 근거가 이 도구 하나로 찍혔고, 환경 재검토로 가는 출발점이 됐습니다. 단 이 판정은 그 환경 한정이었음이 검증에서 밝혀졌습니다. cuObject는 CX6·네이티브 IB에서 정상 구동됐고, 제약은 IB가 아니라 NIC(VF/세대)였습니다(보고서 §4·§8).

## 마무리 — 소프트웨어의 결론 세 가지

이번 편의 결론을 세 가지로 압축하면 이렇습니다. 첫째, RDMA는 데이터만 우회하며 제어는 여전히 커널·디바이스 노드·/sys에 기댑니다. 둘째, 스택 선택(MOFED·inbox)은 이식성의 문제가 아니라 운영 위치의 문제입니다. 서버는 inbox로 충분했고 MOFED는 클라이언트의 peermem 요건이었다는 검증이 그 증거입니다. 셋째, 컨테이너든 네이티브든 점검 목록은 같습니다. 디바이스 노드·/sys 열거·라이브러리 종속·메모리 고정.

다음 편에서는 이 스택 위에서 도는 개념들의 정체를 파헤칩니다. QP, MR, CQ, PD — 4절에서 이름만 스쳐 간 이 자원들이 어떻게 서로 연결되어 커널 없는 전송을 지탱하는지가 4편의 주제입니다.

**다음 편 예고**: [RDMA 학습 시리즈 (4/7): 핵심 개념](/2026/09/27/RDMA-Study-04-Core-Concepts/)에서 QP·MR·CQ·PD의 구조와 왜 이 넷이 함께 움직이는지를 다룹니다.
