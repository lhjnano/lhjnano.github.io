---
layout: post
title: "cuObject 학습 시리즈 (1/4) GPUDirect RDMA: BAR1과 peermem"
categories: [GPU, Storage]
description: "NIC은 어떻게 호스트 RAM을 거치지 않고 GPU 메모리에 직접 쓸 수 있을까요? BAR1 주소 창의 원리, peermem 등록 6단계, 그리고 MOFED가 필수가 된 사연을 실측 기반으로 정리했습니다."
keywords: [cuObject, GPUDirect RDMA, BAR1, peermem, MOFED, dma-buf]
toc: true
toc_sticky: true
---

> cuObject 학습 시리즈 (1/4). NVIDIA GPU가 원격 스토리지에서 데이터를 읽고 쓰는 경로를 다루는 시리즈입니다. RDMA 기초는 [RDMA 학습 시리즈](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에서, 이 시리즈는 NVIDIA 스택을 축으로 파고듭니다.

추론 클러스터에서 GPU 메모리는 늘 부족합니다. vLLM 같은 서비스가 만들어내는 KV 캐시는 HBM 위에서 태어나고, 여유가 사라지면 원격 스토리지로 쫓겨납니다. 그러다 보니 "NVIDIA GPU가 원격 스토리지에서 데이터를 어떻게 읽고 쓰는가"라는 질문이 실무의 질문이 됐고, NVIDIA 스택이 내놓은 답의 중심에 cuObject가 서 있습니다.

이 시리즈는 cuObject 하나를 축으로 삼아, 그것이 올라앉은 기반(GPUDirect RDMA, BAR1, peermem), 그것이 만나는 층(cuFile/GDS), 그것이 세상과 통하는 생태계(NIXL, LMCache)를 한 번에 조망합니다. 첫 편인 이 글은 시리즈의 지도를 그린 뒤, 모든 것을 떠받치는 물리적 기반인 GPUDirect RDMA를 해부합니다.

글의 실측값은 내부 검증 환경에서 나왔습니다. GPU 노드(gpu-1)가 RTX A6000과 ConnectX-6(네이티브 IB)을 짝으로 쓰고, 스토리지 게이트웨이(stg-node1/2)가 Lustre 백엔드를 받쳐 주는 구성입니다. CX4 검증에서 "IB에서 불가"로 남았던 결론이 CX6 검증에서 어떻게 갱신됐는지도 함께 다룹니다.

## TL;DR

- NVIDIA GPU I/O는 세 축으로 나뉜다. NCCL(GPU↔GPU), cuFile(GPU↔File), cuObject(GPU↔S3)이고, 셋 모두 GPUDirect RDMA라는 공통 기반 위에 있다
- 전통 경로는 복사 2번(Storage → 호스트 RAM → GPU), GPUDirect는 복사 0번이다. NIC이 BAR1 창으로 GPU HBM에 직접 DMA를 건다
- BAR1은 GPU가 PCIe에 내놓는 주소 창이다. 검증 클라이언트 RTX A6000은 256 MiB(실측: 192 MiB 통과, 224 MiB부터 등록 거부)
- peermem 등록은 6단계다. `cuFileBufRegister`에서 출발해 nvidia.ko의 주소 번역과 nvidia_peermem의 중계를 지나 mlx5의 MR 프로그래밍으로 끝난다
- MOFED가 필수인 이유는 하나다. `ib_register_peer_memory_client` 훅이 MOFED의 ib_core에만 존재한다. 이 요건은 클라이언트(GPU 노드) 전용이고 게이트웨이는 inbox OFED로 충분하다
- upstream 커널은 peer memory 훅을 거부하고 dma-buf(2021년 커널 5.12의 `ibv_reg_dmabuf_mr`)를 표준으로 밀었다. 폐쇄 드라이버는 GPL-only 벽에 막혀 이 경로를 구현하지 못했다
- MOFED 없이 가는 대안은 NVIDIA open-dkms 모듈과 `CUFILE_DMABUF_ENABLE` 조합이다. 검증 환경(A6000 + 폐쇄 드라이버)은 지원되는 커널을 골라 peermem 경로로 통과했다

## 1. NVIDIA GPU I/O의 세 축: 무엇이 어디로 흐르는가

GPU가 데이터를 주고받는 상대는 크게 셋입니다. 옆 노드의 GPU, 로컬 파일시스템의 파일, 그리고 원격 오브젝트 스토리지. NVIDIA 스택은 이 세 상대에 각각 다른 라이브러리를 붙였는데, 이것이 세 축입니다.

- **NCCL**: GPU↔GPU. 노드 간 집합통신(AllReduce 등)을 담당하는 학습·추론 파이프라인의 표준 부품이다. 이 시리즈의 범위 밖이다
- **cuFile/GDS**: GPU↔File. 로컬 파일과 블록스토리지를 다루는 GPUDirect Storage의 사용자 공간 API다. libcufile 1.18이 cuObject의 기반 라이브러리다
- **cuObject**: GPU↔S3. 원격 오브젝트 스토리지를 상대로 GPU HBM 직송, 즉 호스트 RAM 무경유 전송을 수행한다. 이 시리즈의 주인공이다

축이 나뉜 이유는 데이터가 있는 곳이 다르기 때문입니다. 로컬 파일은 POSIX 경로로 식별하지만, 원격 오브젝트는 버킷과 키로 식별합니다. 질문의 형태가 다르니 경로도 갈립니다. 위에서는 vLLM, LMCache, NIXL 같은 애플리케이션이 KV 캐시 오프로드 수요를 몰고 오고, 아래에서는 세 축이 같은 바닥을 공유합니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch01-01-gpu-io-stack.svg" alt="NVIDIA GPU I/O 생태계 다이어그램: 애플리케이션(vLLM·LMCache·NIXL) 아래 NCCL·cuFile·cuObject 세 축, 공통 기반 GPUDirect RDMA(BAR1+peermem), ConnectX NIC(mlx5)"/>
  <figcaption>그림 1: NVIDIA GPU I/O 생태계의 세 축과 공통 기반. 애플리케이션 아래에 NCCL·cuFile·cuObject 세 축이 있고, 그 아래 GPUDirect RDMA(BAR1 + peermem)가 공통 기반으로 내려앉으며, 다시 ConnectX NIC(mlx5)가 받친다.</figcaption>
</figure>

### 공통 기반: GPUDirect RDMA

축은 셋이지만 바닥은 하나입니다. 어느 축이든 데이터가 호스트 RAM 버퍼를 거치지 않게 만드는 공통 기반이 GPUDirect RDMA입니다. NIC이 GPU와 직접 DMA를 주고받도록 하는 이 기반은 두 개의 기둥으로 서 있는데, 하나는 주소 창인 BAR1(3절)이고 다른 하나는 등록 메커니즘인 peermem(4절)입니다. 이 글의 나머지가 전부 이 두 기둥의 이야기입니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch01-02-common-base.svg" alt="GPUDirect RDMA 공통 기반 다이어그램: 세 축이 GPUDirect RDMA 밴드로 모이고, BAR1(주소 창)과 peermem(등록 메커니즘) 두 기둥이 이를 받친다"/>
  <figcaption>그림 2. GPUDirect RDMA의 두 기둥. 세 축이 모두 같은 기반 위에 있고, 기반은 BAR1(주소 창)과 peermem(등록 메커니즘)으로 서 있다. 창의 크기는 GPU마다 다른데 RTX A6000은 256 MiB다(시리즈 2편에서 상세).</figcaption>
</figure>

### cuObject의 위치: 입증과 제약

주인공이 어디까지 입증됐는지도 정리해 둡니다. CX6 네이티브 IB 검증에서 cuObject의 GPU HBM 직송은 끝까지 통과했습니다. cuFile이 64 MiB GPU 버퍼를 peermem MR로 등록한 로그(`register with RDMA success mr_size: 67108864`)가 남았고, 4~192 MiB 전 구간에서 체크섬이 일치했습니다.

제약도 있습니다. cuObject의 DC transport는 ConnectX-5 이상에서만 동작합니다. 구형 NIC의 VF, 즉 가상화 환경에서는 DC 연결 수립에 실패했고 대형 전송의 간헐 실패도 환경 의존으로 관찰됐습니다. CX6 네이티브에서는 재현되지 않았습니다. 그래서 초기 결론이었던 "cuObject는 IB에서 불가"는 "제약은 IB가 아니라 NIC(가상화 환경과 세대)"로 갱신됐습니다(서사 갱신 v3).

참고로 cuObject가 제어는 HTTP(SigV4), 데이터는 RDMA로 나누는 제어/데이터 분리 구조와 BAR1 실측 숫자의 측정 맥락은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에서 이미 다뤘습니다. 이 시리즈는 그 위에서 NVIDIA 스택 쪽으로 더 깊이 내려갑니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch01-03-position.svg" alt="cuObject의 위치 다이어그램: 왼쪽 패널은 CX6 네이티브 IB에서의 입증(GPU HBM 직송, 4~192 MiB 통과), 오른쪽 패널은 구형 NIC의 제약(ConnectX-5 이상 요건, SR-IOV VF 가상화 제약)"/>
  <figcaption>그림 3, 입증(CX6 네이티브 IB)과 제약(구형 NIC 가상화 환경)을 나란히 놓은 그림. cuObject의 가용성을 결정하는 것은 프로토콜이 아니라 NIC 세대와 가상화 여부다.</figcaption>
</figure>

### 시리즈 로드맵: 기반에서 주인공으로

시리즈 4편의 순서는 아래에서 위로 쌓입니다. 1편인 이 글은 공통 기반인 GPUDirect RDMA를 다룹니다. 2편은 cuFile/GDS의 경로 선택과 BAR1 한계, 3편은 주인공 cuObject의 아키텍처(세션·토큰·DC 전송), 4편은 생태계(NIXL·LMCache·elbencho)로 이어집니다. 기반을 알고 올라가면 3편의 함수 이름 하나, 4편의 벤치마크 숫자 하나가 전부 이 글의 부품 위에 서 있음이 보입니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch01-04-roadmap.svg" alt="학습 로드맵: 생태계, GPUDirect RDMA, cuFile/GDS, cuObject, BAR1 한계, 생태계의 여섯 장이 기반에서 주인공으로 쌓이는 구성"/>
  <figcaption>그림 4: 학습 로드맵. 원본 학습 가이드의 여섯 장(생태계, GPUDirect RDMA, cuFile/GDS, cuObject, BAR1 한계, 생태계)을 블로그 시리즈의 네 편으로 접은 지도다. 1장과 2장이 이 글이고, 3장과 5장이 2편(cuFile/GDS와 BAR1), 4장이 3편(cuObject), 6장이 4편(생태계)이다. RDMA 학습 시리즈와 상호 참조되되 각자 독립적으로 읽을 수 있다.</figcaption>
</figure>

## 2. 전통 경로 vs GPUDirect: 복사 2번과 복사 0번

GPUDirect가 없던 시절, 원격 스토리지의 데이터가 GPU에 도착하려면 두 번의 복사를 치렀습니다.

1. **복사 1**: Storage → NIC → 호스트 RAM 버퍼. NIC의 DMA는 원래 호스트 메모리로만 보낼 수 있었습니다
2. **복사 2**: 호스트 RAM → GPU. CPU가 `cudaMemcpy`로 옮깁니다. RAM 왕복 지연과 CPU 사이클이 함께 붙습니다

GPUDirect RDMA는 이 경로를 지웁니다. NIC가 GPU 메모리에 직접 DMA를 걸면 데이터는 호스트 RAM을 한 번도 거치지 않고 HBM에 도착합니다. 복사 0번. cuObject의 GPU-direct가 정확히 이 경로입니다.

| 구분 | 전통 경로 (복사 2번) | GPUDirect (복사 0번) |
|------|----------------------|----------------------|
| 데이터 경로 | Storage → NIC → 호스트 RAM → GPU | Storage → NIC → GPU HBM |
| 호스트 RAM 경유 | 필수: 사본이 한 벌 더 생긴다 | 없음 |
| 복사 횟수 | 2회 | 0회 |
| CPU 개입 | `cudaMemcpy`마다 CPU가 참여 | 지시만 하면 장치들이 처리한다 |

<figure>
  <img src="/assets/images/posts/cuobject-study/ch02-01-bar1-peermem.svg" alt="전통 경로(복사 2번)와 GPUDirect 경로(복사 0번)의 대비, BAR1 창의 역할, peermem 등록 흐름(nvidia.ko → MOFED ib_core → nvidia_peermem → mlx5)"/>
  <figcaption>그림 5. 전통 경로(복사 2번)와 GPUDirect 경로(복사 0번)의 대비. 아래쪽은 GPUDirect가 성립하는 두 장치, 즉 BAR1 창을 통한 주소 노출과 peermem 등록 흐름(nvidia.ko → MOFED ib_core → nvidia_peermem → mlx5 → GPU 페이지 물리 주소 전달)을 함께 그린다.</figcaption>
</figure>

### 핵심 용어

- **DMA (Direct Memory Access)**: CPU 개입 없이 장치가 메모리에 직접 읽고 쓰는 전송. "NIC가 GPU 메모리에 DMA를 건다"는 말은 NIC가 GPU HBM의 물리 주소를 향해 전송을 발사한다는 뜻이다
- **MR (Memory Region)**: RDMA로 접근 가능하도록 등록된 메모리 영역. rkey와 주소 좌표가 발급되고, 원격이 그 좌표로 READ/WRITE를 수행한다

## 3. BAR1 창: GPU가 PCIe에 내놓는 주소의 문

NIC 입장에서 GPU 메모리 전체가 한 덩어리로 보이지 않습니다. GPU는 자신의 메모리 중 일부만 PCIe 버스에 주소 창(window)으로 노출하는데, 그것이 BAR1입니다. NIC의 DMA는 이 창 안의 주소로만 유효합니다.

같은 GPU 메모리라도 주소가 다르면 도달 가능성이 달라집니다. CUDA 가상 주소, 즉 커널이 쓰는 주소로는 NIC가 못 감하고, PCIe 주소(BAR1 창)로만 닿습니다. 창 밖의 메모리는 CPU만 접근할 수 있습니다.

> **실측(RTX A6000)**: BAR1 = 256 MiB. HBM 48 GiB의 약 0.5%에 해당한다. cufile 로그의 `BAR 1 size detected via NVML API: 256 MiB`가 이 하드웨어 선언값을 읽은 흔적이고, 크기별 상한 실험은 192 MiB 통과, 224 MiB부터 등록 거부(`cuMemObjGetDescriptor` rc=1)로 갈렸다. 측정 맥락은 [RDMA 학습 시리즈 6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에, 창의 사용 여유와 동시 등록이 창을 나눠 쓰는 이야기는 이 시리즈 2편에 맡긴다.

```bash
# BAR1 창의 크기와 여유 확인
nvidia-smi -q -d MEMORY | grep -A3 "BAR1"   # Total 256 MiB / Used / Free
grep -i "BAR 1 size" cufile.log              # NVML로 읽은 창 크기 흔적
lsmod | grep nvidia_peermem                  # 등록 통로 역할의 모듈 확인
```

<figure>
  <img src="/assets/images/posts/cuobject-study/ch02-02-bar1-window.svg" alt="같은 메모리, 다른 주소: NIC가 DMA를 걸 수 있는 주소 공간은 호스트 RAM과 BAR1 창뿐이고, GPU HBM 48 GiB 중 PCIe에 노출되는 조각은 256 MiB"/>
  <figcaption>그림 6: 같은 메모리, 다른 주소. NIC가 DMA를 걸 수 있는 주소는 호스트 RAM과 BAR1 창뿐이다. GPU HBM 48 GiB 중 PCIe에 노출되는 조각은 256 MiB(RTX A6000 기준)이고, 나머지는 CPU 전용이다.</figcaption>
</figure>

## 4. peermem 등록: GPU 물리 주소가 NIC에 도달하는 6단계

BAR1이 "문"이라면 peermem은 "문이 열리는 절차"입니다. 애플리케이션이 GPU 버퍼를 등록하면(예: cuFile의 `cuFileBufRegister`) 아래 절차가 커널 안에서 일어납니다.

1. `cuFileBufRegister`: GPU 버퍼 등록 요청이 시작점이다
2. nvidia.ko: 가상 주소를 GPU 페이지 물리 주소로 조회한다
3. nvidia_peermem.ko: 자신을 peer memory client로 등록한다
4. `ib_register_peer_memory_client`: MOFED ib_core의 훅을 호출한다
5. mlx5: NIC에 GPU 페이지 주소를 전달한다(MR 프로그래밍)
6. 등록 완료: RDMA가 활성화된다(로그: `register with RDMA success`)

> **왜 필수인가**: NVIDIA 독점 드라이버는 `dmaBufCapable:0`, 즉 자체적으로는 RDMA 등록 수단이 없다. peermem(또는 dma-buf) 없이는 cuFile이 RDMA를 비활성화한다. 로그로는 `nvidia_peermem.ko is not loaded. Disabling UserSpace RDMA access`가 남는다. 검증 환경은 이 요건을 지원되는 커널을 선택하는 경로(검증 보고서의 B' 경로)로 통과했다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch02-03-peermem-steps.svg" alt="peermem 등록 6단계: cuFileBufRegister 시작, nvidia.ko 주소 조회, nvidia_peermem 클라이언트 등록, MOFED ib_core 훅 호출, mlx5 MR 프로그래밍, 등록 완료 로그"/>
  <figcaption>그림 7. peermem 등록 6단계. 전제 조건(독점 드라이버 dmaBufCapable:0)부터 등록 완료 로그까지, `cuFileBufRegister` 한 번이 커널 안에서 지나는 여정이다.</figcaption>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu1-q04.svg" alt="스터디 Q&A: peermem에는 BAR1 정보가 없나요?" loading="lazy"/>
</figure>

## 5. 왜 MOFED인가: 훅의 소재와 dma-buf의 역사

"peermem엔 MOFED가 필요하다"는 말의 정확한 의미는 `ib_register_peer_memory_client` 훅이 MOFED의 ib_core에만 존재한다는 것입니다. 배포판 커널의 inbox OFED에는 이 훅이 없어 nvidia_peermem이 로드되지 않습니다.

이 요건의 주체를 오해하면 안 됩니다. MOFED는 클라이언트, 즉 고객 GPU 노드의 요건입니다. 게이트웨이(스토리지 노드)는 inbox OFED 그대로 서버를 구동합니다. 서버는 가볍고 클라이언트가 무거운 제품 구조가 여기서 나옵니다(3편).

역할 구분도 정확히 해둘 만합니다. MOFED 자체는 GPU를 모릅니다. MOFED는 peer memory client 훅이라는 소켓을 깐 확장 IB 스택이고, 그 소켓에 VRAM을 꽂는 플러그는 NVIDIA의 nvidia_peermem이며, 실제 주소 번역기는 nvidia.ko입니다. "MOFED가 커널의 IB 매핑을 GPU 쪽으로 확장한 wrapper"라고 요약하면 이 주체 관계가 뒤집힙니다.

### upstream은 왜 이 훅을 거부했나

이 훅은 애초에 upstream 커널에 제출됐다가 거부된 설계입니다. 2014~2015년경 Mellanox가 낸 peer memory 패치 시리즈가 계속 리젝션당한 유명한 사연인데, 거부 이유는 세 겹으로 정리됩니다.

1. **아키텍처**: 표준 DMA 매핑 층을 우회하는 벤더별 병렬 경로라는 문제. 커널의 원칙은 모든 메모리 등록이 공통 dma-mapping 층을 지나는 것인데, 콜백마다 주소 번역과 lifetime 의미가 제각각이 된다
2. **정책**: 유일한 소비자가 out-of-tree 폐쇄 드라이버라는 문제. 한 번 머지되면 그 순간 벤더 전용 ABI로 얼어붙는다
3. **결정타**: 표준 대안 dma-buf가 이미 있다는 것. 유지보수 측의 입장은 "GPU 메모리로 RDMA 하고 싶으면 GPU 드라이버가 dma-buf exporter가 되어라"였고, 2021년 커널 5.12에 `ibv_reg_dmabuf_mr`가 머지되며 논쟁은 종결됐다

그런데 아이러니가 남습니다. upstream이 원한 dma-buf 경로를 NVIDIA 폐쇄 드라이버는 구현하지 않았습니다. `dma_buf_export` 같은 export 측 함수가 `EXPORT_SYMBOL_GPL`, 즉 GPL-only 심볼이라 폐쇄 모듈은 호출 자체가 불가능하기 때문입니다. 귀찮아서 안 한 것이 아니라 호출할 수가 없었습니다. 폐쇄 모듈의 설계 철학, 그러니까 커널과의 결합을 최소화하는 얇은 shim 구조도 dma-buf exporter가 되는 일과는 정반대 방향이었습니다.

전략의 결말은 이렇게 굳었습니다. NVIDIA는 Mellanox를 인수해 MOFED 훅 경로의 양 끝을 모두 통제했고, 2022년에는 open-gpu-kernel-modules를 공개했습니다. 오픈 모듈은 GPL 호환이라 dma-buf exporter를 당연히 구현하고, Blackwell부터는 오픈 커널 모듈이 필수가 됐습니다. 문을 고치는 대신 문이 있는 쪽으로 집을 옮긴 셈입니다.

그래서 MOFED 설치가 어려운 환경의 대안도 열려 있습니다. 대안 A는 NVIDIA open-dkms 커널 모듈과 `CUFILE_DMABUF_ENABLE`의 조합입니다. libcufile이 `ibv_reg_dmabuf_mr` 경로로 등록하기 때문에 inbox rdma-core로 동작하고 MOFED가 필요 없습니다. 아직 널리 채택되지는 않았지만 유망한 경로입니다. 검증 환경(RTX A6000 + 폐쇄 드라이버)은 이 예외 상황이라, 지원되는 커널을 골라 peermem과 MOFED 쪽으로 통과했습니다(4절의 B' 경로).

> **peermem 상시화**: nvidia_peermem은 재부팅 시 저절로 올라오지 않는다. `/etc/modules-load.d/nvidia-peermem.conf`에 모듈 이름을 적어 두면 부팅마다 로드된다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch02-04-mofed-hook.svg" alt="왜 MOFED인가: peer memory 등록 훅(ib_register_peer_memory_client)은 MOFED의 ib_core에만 있고 inbox OFED에는 없다. 대안은 open-dkms와 dma-buf 경로"/>
  <figcaption>그림 8: 왜 MOFED인가. peer memory 등록 훅은 MOFED(훅 있음, nvidia_peermem 로드 가능)의 ib_core에만 있고 inbox OFED(훅 없음)에는 없다. inbox 환경의 대안은 open-dkms 모듈과 dma-buf 경로다.</figcaption>
</figure>

### 핵심 용어

- **MOFED (Mellanox OFED)**: Mellanox/NVIDIA가 배포하는 InfiniBand/RoCE 드라이버 스택. 배포판 커널에 내장된 inbox OFED와 구별된다. peer memory client 훅이 ib_core에 존재한다
- **dma-buf**: 리눅스 표준의 디바이스 메모리 공유 프레임워크. export 측 함수는 GPL-only 심볼이다. 2021년 커널 5.12에 RDMA 등록 API가 머지되며 peer memory 훅의 표준 대안이 됐다
- **ibv_reg_dmabuf_mr**: dma-buf 핸들로 MR을 등록하는 표준 verbs API. peermem 훅 없이도 동작하므로 inbox 환경의 대안이 된다

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu1-q05.svg" alt="스터디 Q&A: MOFED는 wrapper가 아니라 소켓을 깐 확장 IB 스택" loading="lazy"/>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu1-q06.svg" alt="스터디 Q&A: upstream이 peer memory 패치를 거부한 세 겹의 이유" loading="lazy"/>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu1-q07.svg" alt="스터디 Q&A: NVIDIA 폐쇄 드라이버가 dma-buf를 구현하지 않은 이유" loading="lazy"/>
</figure>

## 마무리: 핵심 요점

1. NVIDIA GPU I/O는 세 축(NCCL, cuFile, cuObject)이고, 셋 모두 GPUDirect RDMA라는 공통 기반 위에 있다
2. 전통 경로는 복사 2번, GPUDirect는 복사 0번이다. NIC이 GPU HBM에 직접 DMA를 걸면 호스트 RAM은 한 번도 나오지 않는다
3. NIC이 GPU 메모리에 닿는 관문은 BAR1 창이다. RTX A6000은 256 MiB였고, 실측 경계는 192 MiB 통과에 224 MiB 등록 거부였다
4. peermem 등록은 6단계다. nvidia.ko가 번역하고, nvidia_peermem이 중계하고, mlx5가 MR을 프로그래밍한다
5. MOFED 요건의 정체는 훅의 소재다. 요건 주체는 클라이언트뿐이고 게이트웨이는 inbox OFED로 충분하다
6. upstream은 peer memory 대신 dma-buf를 표준으로 밀었다. 폐쇄 드라이버는 GPL-only 벽에 막혔고, 해법은 오픈 모듈 전환이었다

**다음 편 예고**: [cuObject 학습 시리즈 (2/4) cuFile/GDS와 BAR1](/2026/10/04/cuObject-Study-02-cuFile-GDS-BAR1/)에서는 cuFile의 경로 선택 층(GPUDirect와 호스트 fallback 판단), 그리고 BAR1 창이 만드는 전송 크기 상한의 물리적 이유를 다룹니다.
