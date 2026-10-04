---
layout: post
title: "cuObject 학습 시리즈 (2/4) cuFile/GDS와 BAR1: 층과 한계"
categories: [GPU, Storage]
description: "cuFile은 어떻게 GPUDirect 직통과 호스트 fallback 중 경로를 고르고, 전송 크기는 왜 RTX A6000의 BAR1 창 256 MiB에서 끊길까요?"
keywords: [cuFile, GDS, BAR1, cuFileBufRegister, RTX A6000, NVML]
toc: true
toc_sticky: true
---

> cuObject 학습 시리즈 (2/4). 1편에서 GPU I/O의 세 가지 길과 GPUDirect RDMA의 관문(BAR1 창과 peermem)을 다뤘다면, 이번 편은 그 관문 바로 위에 얹히는 소프트웨어 층과 관문의 크기를 함께 봅니다. 실제 S3-over-RDMA 검증 환경의 실측 기반 학습 자료입니다.

애플리케이션이 스토리지에 바라는 것은 결국 한 문장입니다. "이 파일을 GPU 버퍼로 읽어줘"가 전부고, 나머지는 이 요청을 어떤 길로 실어 나를지의 문제다. cuFile(GPUDirect Storage의 사용자 공간 라이브러리, libcufile)이 바로 그 길을 고르는 층이다. 요청을 받아 어느 경로로 보낼지, 어느 버퍼에 놓을지를 정리한 뒤, 실제 전송은 1편에서 본 GPUDirect 하부로 떨어뜨립니다.

그런데 이야기는 절반만 끝났습니다. cuFile이 GPU 버퍼를 등록하면 그 등록은 언제나 BAR1 창 안에서 일어난다. 창이 작으면 등록도 작을 수밖에 없습니다. 한 줄로 요약하면, cuFile이 등록을 맡고 BAR1이 그 한계를 정한다. 이 두 문장을 나란히 두면 "왜 192 MiB까지는 되는데 224 MiB부터 안 되는가"라는 질문에 소프트웨어와 하드웨어가 동시에 답하게 됩니다.

이 글은 학습 자료의 두 장(cuFile/GDS, BAR1 한계)을 "층과 한계"라는 하나의 주제로 묶었습니다. 실측값은 CX6 검증 환경(RTX A6000 클라이언트와 ConnectX-6, S3-over-RDMA)에서 나왔고, cufile.log와 nvidia-smi 출력을 그대로 인용합니다. BAR1 경계 실측은 [RDMA 학습 시리즈 (6/7)](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)와 겹치는 부분이 있어 표로 간결히 정리하고, 이 시리즈 고유의 관심사인 API 호출 순서와 경로 선택, GPU별 비교에 분량을 둡니다.

## TL;DR

- cuFile은 GPUDirect 직통(복사 0)과 호스트 fallback(복사 1)을 고르는 경로 선택 층이다
- 경로 선택은 초기화 때 프로브로 결정된다. CX6 검증에서는 GPUDirect였다
- 핵심 API 세 가지의 순서가 곧 계약이다. HandleOpen → BufRegister → Read/Write
- 분업: cuFile이 MR 좌표를 발급하면 cuObject가 토큰에 실어 서버로 전달한다
- 전송 크기 상한은 프로토콜이 아니라 BAR1 창이 정한다. A6000: 192 통과, 224 거부
- 데이터센터급(A100·H100·H200)은 BAR1이 128 GiB로 이 조건이 사실상 사라진다

## 1. cuFile의 역할: 경로 선택자

애플리케이션과 스토리지 사이에서 cuFile이 서는 자리를 먼저 그려 봅시다. 애플리케이션은 GPU 버퍼로의 읽기를 요청하고, 스토리지는 파일과 블록장치를 제공합니다. 그 사이에서 어느 경로로 갈지, 어느 버퍼에 데이터를 놓을지를 정리하는 것이 이 라이브러리의 일이다. 그 아래 구현은 1편에서 다룬 GPUDirect 기반으로 떨어집니다.

cuObject 입장에서 cuFile은 선택 사항이 아니라 부품입니다. cuObject의 클라이언트 라이브러리(libcuobjclient)가 GPU 메모리 등록에 cuFile을 쓰기 때문이다. cuObject를 이해하려면 반드시 지나야 하는 층이 바로 여기라는 뜻입니다.

- **libcufile**: GDS 사용자 공간 라이브러리. CUFILE_DMABUF_ENABLE으로 dma-buf를 켠다

<figure>
  <img src="/assets/images/posts/cuobject-study/ch03-01-cufile-layers.svg" alt="cuFile/GDS의 층 구조도: 애플리케이션 요청이 cuFile을 지나 GPUDirect 경로와 호스트 fallback 경로로 갈라지고, 핵심 API 3종이 옆에 붙는다"/>
  <figcaption>그림 1: cuFile의 위치. 애플리케이션의 "이 파일을 GPU 버퍼로 읽어줘" 요청을 받아 GPUDirect(복사 0)와 호스트 fallback(복사 1) 두 경로로 갈라준다. 핵심 API 3종(cuFileHandleOpen·cuFileBufRegister·cuFileRead/Write)을 노출하며, 등록이 만든 MR 좌표를 cuObject가 서버에 전달한다.</figcaption>
</figure>

## 2. 경로 선택: GPUDirect 직통과 호스트 fallback

cuFile은 드라이버 초기화 때 프로브를 돌려 경로를 결정합니다. 요건이 갖춰지면 GPUDirect 경로(NIC/블록장치 → BAR1 → GPU HBM, 중간 복사 0회)로 가고, 아니면 호스트 fallback(NIC → 호스트 RAM → cudaMemcpy, 복사 1회)으로 내려갑니다. fallback은 요건이 없어도 항상 동작하도록 설계된 대체 경로다. 실패가 아니라 원래 준비된 두 번째 길이라는 뜻입니다.

| 구분 | GPUDirect 경로 | 호스트 fallback |
|------|----------------|-----------------|
| 데이터 경로 | NIC/블록장치 → BAR1 → GPU HBM | NIC → 호스트 RAM → cudaMemcpy → GPU |
| 중간 복사 | 0회 (zero-copy) | 1회 (호스트 버퍼 경유) |
| 요건 | peermem + BAR1 여유 | 없음: 항상 동작 |
| 성격 | 조건 충족 시 선택되는 우선 경로 | 설계된 대체 경로 (실패 아님) |

> **프로브 로그 예시**: `nvidia_peermem is enabled` · `Device mlx5_0: IB link layer, using default GID index 0` · `Userspace RDMA: Supported / Mellanox PeerDirect: Enabled`. GPUDirect가 선택됐을 때의 모습이고, GID idx0 자동 처리는 host-memory 모드의 함정(3편)과 대비된다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch03-02-path-selection.svg" alt="cuFile의 경로 선택 분기도: I/O 요청이 프로브 결과에 따라 GPUDirect 경로와 호스트 fallback으로 나뉜다"/>
  <figcaption>그림 2. 경로 선택 분기. 드라이버 초기화 때 프로브로 갈린다. 요건(peermem + BAR1 여유)이 충족되면 GPUDirect 직통으로, 미충족 시 자동으로 호스트 fallback으로 내려간다.</figcaption>
</figure>

## 3. 핵심 API: 세 가지와 호출 순서

cuFile의 API는 수십 개지만 GPU-direct 전송의 뼈대는 세 가지입니다. 관점을 API 각각이 아니라 호출 순서에 두는 것이 핵심입니다. 등록 없이 읽으면 fallback 또는 오류로 떨어지기 때문입니다.

```c
/* 1) 핸들 열기: 파일(또는 대상) 식별 */
CUfileHandle_t h;
cuFileHandleOpen(&h, &cf_desc, &err);

/* 2) GPU 버퍼 등록: RDMA 접근 허용 (사전 필수) */
cuFileBufRegister(devPtr, size, flags);

/* 3) 등록된 버퍼로 직접 입출력: GPU 포인터 그대로 */
cuFileRead (h, devPtr, size, fileOffset, &bytesRead);
cuFileWrite(h, devPtr, size, fileOffset, &bytesWritten);
```

- `cuFileHandleOpen`: 대상을 식별한다. 파일 경로 기반이 기본이다
- `cuFileBufRegister`: GPU 버퍼를 등록한다. 1편의 peermem 6단계를 트리거한다
- `cuFileRead/cuFileWrite`: 등록된 버퍼로 직접 입출력한다

<figure>
  <img src="/assets/images/posts/cuobject-study/ch03-03-api-sequence.svg" alt="핵심 API 호출 순서 다이어그램: cuFileHandleOpen, cuFileBufRegister, cuFileRead/Write 순서와 각 단계의 역할"/>
  <figcaption>그림 3: 핵심 API 호출 순서. HandleOpen → BufRegister → Read/Write. Register가 만드는 MR 좌표를 cuObject가 토큰으로 재사용한다.</figcaption>
</figure>

## 4. cuObject에서의 역할: MR 좌표의 토큰화

이 글 전체에서 가장 중요한 그림은 cuFile과 cuObject의 분업이다. 등장인물은 셋입니다. 클라이언트의 cuFile, 그 좌표를 나르는 cuObject, 그리고 서버의 DC QP다.

1. cuFile이 GPU HBM 버퍼를 peermem MR로 등록한다. rkey와 addr이 발급된다
2. 그 좌표를 cuObject가 토큰에 담아 서버에 전달한다. 제어 채널은 HTTP다
3. 서버는 그 좌표로 DC QP WRITE/READ를 건다. GPU HBM에 직접 도달한다

정리하면 cuFile은 클라이언트 쪽 등록 담당, cuObject는 그 좌표를 원격에 알리고 전송을 주고받는 담당입니다. 서버가 클라이언트의 GPU 주소를 미리 알면 데이터가 게이트웨이 RAM에 머물 이유가 없다. staging MR을 거쳐 곧장 HBM으로 들어갑니다.


<figure>
  <img src="/assets/images/posts/cuobject-study/ch03-04-token-flow.svg" alt="MR 좌표가 토큰을 타고 서버로 흐르는 다이어그램: 클라 GPU HBM, cuFile MR 발급, 토큰 전달, 서버 DC QP"/>
  <figcaption>그림 4. MR 좌표가 토큰을 타고 서버로. 클라 GPU HBM에서 cuFile이 peermem으로 MR을 발급(rkey·addr)하고, 그 좌표를 토큰에 실어 제어 채널(HTTP)로 전달하면 서버의 DC QP가 WRITE/READ로 HBM에 직접 닿는다.</figcaption>
</figure>

여기서 한 가지 함정을 미리 짚어 둡니다. 이 좌표 체계가 다루는 주소는 BAR1 창 안뿐이다. 그러므로 등록 가능한 버퍼 크기는 BAR1 여유를 넘을 수 없습니다. 256 MiB 등록 시도가 `cuMemObjGetDescriptor rc=1`로 실패한 이유가 여기에 있다. 이 함정의 물리적 근거를 이 글 후반부(5절)에서 파고듭니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu2-q01.svg" alt="스터디 Q&A: cuFile과 cuObject는 대체 관계가 아니라 재사용 관계다" loading="lazy"/>
</figure>

## 5. BAR1의 원리: 창과 창 밖

1편에서 본 그림을 숫자로 다시 씁니다. RTX A6000의 GPU 메모리는 48 GiB인데, NIC가 DMA를 걸 수 있는 영역은 BAR1 창 256 MiB뿐입니다. 나머지 약 47.75 GiB는 CUDA 커널과 CPU만 쓰는 영역이다. GPUDirect RDMA의 관점에서는 존재하지 않는 주소라고 해도 틀린 말이 아닙니다.

cuObject GPU-direct의 전송 버퍼는 반드시 이 창 안에 등록됩니다. 4절의 MR 좌표가 바로 창 안 주소의 좌표라는 뜻이다. 그러므로 전송 크기의 상한은 프로토콜의 파라미터가 아니라 GPU가 PCIe에 내놓은 창의 크기가 정합니다. "왜 딱 여기서 끊기는가"라는 질문의 답이 이 한 문장 안에 있습니다.

- **BAR1**: GPU가 PCIe에 매핑하는 주소 창. 크기는 GPU 모델마다 다르다
- **NVML**: GPU 상태 조회 라이브러리. nvidia-smi의 기반이다

<figure>
  <img src="/assets/images/posts/cuobject-study/ch05-01-bar1-limits.svg" alt="BAR1 크기가 전송 크기 한계가 되는 구조도: 48 GiB HBM 중 BAR1 창 256 MiB만 NIC가 DMA 가능, 전송 크기 경계와 GPU별 비교"/>
  <figcaption>그림 5: BAR1 크기가 곧 전송 크기 한계. RTX A6000의 HBM 48 GiB 중 NIC가 DMA로 건드릴 수 있는 영역은 BAR1 창 256 MiB뿐이고 나머지는 CPU 전용이다. 64·192 MiB는 등록·통과, 224·256 MiB는 등록 단계에서 거부된다.</figcaption>
</figure>

## 6. 크기 스윕: 192 MiB와 224 MiB 사이

RTX A6000 클라이언트에서 GPU-direct 버퍼 크기를 훑은 결과입니다. 어느 크기에서 등록이 열리고 어디서 닫히는지가 한눈에 보입니다.

| 버퍼 크기 | 결과 |
|-----------|------|
| 4 MiB | 통과 |
| 64 MiB | 통과 |
| 128 MiB | 통과 |
| 192 MiB | 통과 (BAR1 안쪽 마지막 측정 지점) |
| 224 MiB | 실패 (등록 거부) |
| 256 MiB | 실패 (cuMemObjGetDescriptor rc=1) |

경계의 의미만 짚고 넘어갑시다. 192 MiB는 BAR1 256 MiB 안쪽에서 등록 오버헤드를 감안해 들어올 수 있는 마지막 측정 지점이고, 224·256 MiB는 창을 넘으므로 등록 단계에서 거부됩니다. 실패가 전송 중 오류가 아니라 등록 실패라는 점이 핵심이다. 크기 설계는 전송 이전의 등록 단계에서 이미 갈린다는 뜻입니다.

이 192/224 MiB 경계 실측은 [RDMA 학습 시리즈 (6/7)](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)의 S3-over-RDMA 검증에서 하드웨어 경로 전체와 함께 이미 다뤘습니다. 이 시리즈에서는 요점만 위 표로 남기고, 시리즈 고유의 관심사인 등록을 만드는 API 순서(3절)와 다음 절의 GPU별 비교로 돌아갑니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch05-02-size-sweep.svg" alt="버퍼 크기 스윕 결과표: 4·64·128·192 MiB 통과, 224·256 MiB 실패 그래프"/>
  <figcaption>그림 6. 버퍼 크기 스윕. 192 MiB까지 통과하고 224 MiB부터 실패한다. 256 MiB 요청은 cuMemObjGetDescriptor rc=1로 거부된다.</figcaption>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu2-q14.svg" alt="스터디 Q&A: 256 MiB는 남은 창고가 아니라 GPU가 선언한 태생적 창 크기다" loading="lazy"/>
</figure>

## 7. GPU별 BAR1 비교: 데이터센터급은 사실상 무제한

지금까지의 한계는 RTX A6000, 그러니까 워크스테이션 GPU의 이야기입니다. 데이터센터급은 창의 규모 자체가 다릅니다.

| GPU | BAR1 크기 | 의미 |
|-----|-----------|------|
| RTX A6000 | 256 MiB | 224 MiB부터 등록 거부, 한계 도달 |
| A100 | 128 GiB | 사실상 무제한 |
| H100 | 128 GiB | 사실상 무제한 |
| H200 | 128 GiB | 사실상 무제한 |

256 MiB와 128 GiB는 512배 차이입니다. HBM 용량과 비슷한 규모의 창을 여는 데이터센터급 설계에서는 "GPU-direct 전송 크기가 BAR1 이하"라는 조건이 사실상 사라집니다. 반대로 말하면 BAR1 한계는 워크스테이션 GPU를 사용 환경으로 쓸 때만 두드러지는 제약이다. 데이터센터급과 워크스테이션급의 갈림이 연산 성능만이 아니라 이런 창 하나에서도 나타난다는 점이 흥미롭습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch05-03-bar1-by-gpu.svg" alt="GPU별 BAR1 크기 로그 스케일 막대그래프: RTX A6000 256 MiB, A100·H100·H200 128 GiB"/>
  <figcaption>그림 7: GPU별 BAR1 비교(로그 스케일). RTX A6000 256 MiB 대비 A100·H100·H200은 128 GiB로 512배다. 데이터센터급은 사실상 무제한이다.</figcaption>
</figure>

## 8. 확인 방법: nvidia-smi 한 줄로

BAR1 크기는 고객 GPU 노드에서 한 줄이면 확인됩니다. 별도 도구도, 커널 파라미터도 필요 없습니다.

```bash
$ nvidia-smi -q -d MEMORY | grep -A 3 'BAR1'
 BAR1 Memory Usage
   Total : 256 MiB
   Used  : 4 MiB
   Free  : 252 MiB
```

출력의 해석은 두 줄이면 족합니다. Total은 BAR1 창 크기, 곧 GPU-direct 버퍼의 물리적 상한이다. Free는 지금 사용 가능한 여유로, 전송 크기와 직접 비교할 값입니다. Used가 이미 몇 MiB 쓰고 있다면 설계 여유는 Total이 아니라 Free를 기준으로 계산해야 합니다.

> **고객 안내 3단계**: ① GPU-direct 전송 크기가 BAR1 여유(Free) 이하인지 위 커맨드로 확인한다. ② 여유가 부족하면 host-memory 모드로 피한다(peermem·BAR1과 무관, 3편에서 다룬다). ③ 데이터센터 GPU(A100 이상)는 사실상 무제한이라 이 검토 자체가 불필요하다

<figure>
  <img src="/assets/images/posts/cuobject-study/ch05-04-check-bar1.svg" alt="BAR1 확인 절차도: nvidia-smi -q 출력 해석과 고객 안내 3단계"/>
  <figcaption>그림 8. 확인 절차. nvidia-smi -q -d MEMORY 출력에서 Total은 창 크기, Free는 사용 가능 여유다. 전송 크기 설계의 첫 확인 항목이다.</figcaption>
</figure>

## 마무리: 핵심 요점

1. cuFile은 GPUDirect 직통과 호스트 fallback을 갈라주는 경로 선택자다
2. fallback은 실패가 아니라 설계된 두 번째 길이다
3. API 순서가 곧 계약이다. HandleOpen → BufRegister → Read/Write
4. cuFile이 MR 좌표를 발급하면 cuObject가 토큰에 실어 서버로 보낸다
5. 전송 크기 상한은 BAR1이 정한다. 실측 경계는 192 통과, 224 거부였다
6. 데이터센터급은 BAR1 128 GiB로 사실상 무제한이다

**다음 편 예고**: [cuObject 학습 시리즈 (3/4) cuObject 아키텍처](/2026/10/04/cuObject-Study-03-cuObject-Architecture/)에서는 오늘 본 토큰의 실체를 쫓습니다. 세션과 채널 구조, DC QP와 RC의 선택 기준, 그리고 GPU-direct 모드와 host-memory 모드가 갈리는 조건까지 내려갑니다.
