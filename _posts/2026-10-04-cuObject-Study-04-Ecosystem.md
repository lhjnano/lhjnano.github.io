---
layout: post
title: "cuObject 학습 시리즈 (4/4) 생태계: NIXL·LMCache·elbencho"
categories: [GPU, Storage]
description: "NIXL과 LMCache는 왜 cuObject 위에 올라탔고, elbencho는 무엇을 측정할까요?"
keywords: [NIXL, LMCache, vLLM, KV cache, elbencho, S3 over RDMA]
toc: true
toc_sticky: true
---

> cuObject 학습 시리즈 (4/4). 소스: cuObject 학습 가이드 6편(생태계), 내부 S3-over-RDMA 검증 보고서(2026-09-22~26), 학습 대화록(2026-10-04).

지금까지 세 편은 cuObject의 안쪽을 걸었습니다. GPUDirect RDMA가 만든 메모리의 좌표(1편), cuFile과 GDS가 쌓은 계층 그리고 BAR1이라는 물리적 상한(2편), 마지막으로 cuObject 스스로의 아키텍처(3편)까지. 이 마지막 편에서는 시야를 바깥으로 돌립니다. 이 라이브러리를 오늘 누가 실제로 부르고 있는지를 봅니다.

소비자는 크게 셋입니다. 데이터 이동을 벤더 중립 API로 감싸는 NIXL, vLLM의 KV 캐시를 원격 스토리지로 내보내는 LMCache, 그리고 `--cuobj` 플래그로 라이브러리를 직접 두드리는 벤치마크 도구 elbencho. 이 셋을 하나의 흐름으로 묶는 실전 파이프라인과, 표준화를 향해 열려 있는 NIXL #2241 제안까지가 이번 지도의 전부입니다.

왜 이 관점이 필요할까요. 기술의 생존은 내부의 우아함이 아니라 매일 그것을 부르는 워크로드가 결정합니다. RDMA 학습 시리즈 [6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에서 해부한 그 프로토콜이 지금 어디서 살아 숨 쉬는지 묻는 것이 이 편의 질문입니다.

## TL;DR

- NIXL은 GPU 메모리, 호스트 메모리, 스토리지 사이의 이동을 하나의 API로 추상화한다. 오브젝트 전송을 맡은 OBJ accelerated engine이 cuObject 기반이다
- LMCache는 vLLM의 KV 캐시를 원격으로 내보내 HBM 압박을 푼다. 전송은 NIXL을 거쳐 cuObject로 이뤄진다
- elbencho는 `--cuobj`로 cuObject를 직접 호출하는 오픈소스 벤치마크다. 직접 소비자는 NIXL과 사실상 양대뿐이다
- 실전 파이프라인은 vLLM → KV cache → LMCache → NIXL → cuObject → 원격 S3의 6단계로, 착지점은 Lustre 백엔드(kvcache-s3)를 가진 S3 게이트웨이다
- NVIDIA 스택의 KV 오프로드가 전부 cuObject로 묶여 있어, NVIDIA GPU 고객의 수요는 libcuobjclient 호출로 귀결된다
- NIXL #2241은 generic S3-over-RDMA 표준화 제안(아직 open). 결과와 무관하게 당장의 아키텍처는 바뀌지 않는다

## 1. NIXL, 벤더 중립 이식 계층

NIXL(NVIDIA Inference Xfer Library)은 NVIDIA와 Dell이 공동으로 개발하는 벤더 중립 데이터 이식 계층입니다. GPU 메모리와 호스트 메모리, 스토리지 사이의 이동을 하나의 API로 추상화하고 실제 전송은 GDS, cuObject, UCX 같은 백엔드에 맡깁니다. 백엔드를 갈아끼워도 애플리케이션의 호출부는 그대로 남습니다.

[3편](/2026/10/04/cuObject-Study-03-cuObject-Architecture/)에서 본 cuObject의 디테일, 즉 세션 수립과 토큰 교환, DC와 RC의 갈래를 매번 애플리케이션이 직접 다루는 것은 큰 비용입니다. NIXL은 이 복잡함을 통합 API 안으로 감춰 버립니다. 이식 계층이라는 이름이 붙은 이유죠.

| 용어 | 뜻 |
|------|------|
| NIXL | 추론·학습 워크로드의 데이터 이동을 위한 벤더 중립 추상화 계층. 통합 API로 여러 전송 백엔드를 감싼다 |
| accelerated engine | NIXL의 백엔드 구현 단위. 오브젝트(S3) 전송을 맡는 OBJ accelerated engine은 cuObject 기반이다 |
| UCX | 벤더 중립 통신 프레임워크. AMD 등 비(非) NVIDIA 환경이 NIXL에 자연스럽게 붙는 백엔드 자리다 |

cuObject와 만나는 지점은 바로 **OBJ accelerated engine**입니다. Dell과 NVIDIA의 머지를 거쳐 이 엔진의 오브젝트 전송이 cuObject 기반으로 구현되어 있습니다. 덕분에 NIXL을 쓰는 애플리케이션은 cuObject라는 이름을 의식하지 않고도 S3-over-RDMA의 이점을 얻습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch06-01-ecosystem.svg" alt="cuObject 생태계 지도: libcuobjclient와 libcuobjserver를 중심에 두고 NIXL의 OBJ accelerated engine, LMCache의 vLLM KV 캐시 오프로드, elbencho의 직접 호출이 소비자로 붙고 NIXL #2241 표준화 제안과 실전 파이프라인이 확장 지평으로 표시된 그림" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - cuObject의 소비자들. NIXL의 OBJ accelerated engine, LMCache의 KV 오프로드, elbencho의 직접 호출이 한 지도에 모인다</figcaption>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu4-q08.svg" alt="스터디 Q&A 카드: AMD 쪽은 어떻게 대응하고 있나요? amdgpu는 처음부터 upstream에 있었고 이제 표준 dma-buf와 ibv_reg_dmabuf_mr가 공식 경로이며 NIXL이 UCX 같은 벤더 중립 백엔드를 두는 이유이기도 하다" loading="lazy"/>
</figure>

## 2. LMCache, vLLM KV 캐시의 원격 탈출

문제는 추론 서빙 현장에서 시작합니다. vLLM이 추론을 돌리면 KV 캐시가 GPU HBM 위에 쌓이는데, 컨텍스트가 길수록 이 비용은 커집니다. HBM이 부족해지면 배치가 줄고 컨텍스트가 잘리며, 같은 프리픽스를 여러 번 다시 계산하는 낭비도 함께 자라납니다.

LMCache는 vLLM 플러그인으로 동작하는 캐시 계층입니다. KV 블록 단위로 캐싱하고 재사용해 이 압박을 풉니다. 내보낸 KV는 NIXL을 거쳐 cuObject로 전송되며, 목적지는 여러 vLLM 인스턴스가 함께 쓰는 원격 캐시입니다.

원격으로 내보내는 값은 계산 관점에서도 명확합니다. 한번 만든 KV를 다시 만드는 것은 GPU 연산(재계산)이고, 저장된 것을 가져오는 것은 대역폭(재로딩)인데 후자가 압도적으로 쌉니다. 재사용 가치가 있는 블록만 남기는 정책(TTL, LRU eviction)과 짝을 이루는 경제죠.

수명의 관점도 흥미롭습니다. HBM 안의 KV 캐시는 휘발성이라 vLLM이 종료되면 함께 사라집니다. 오프로드된 KV 오브젝트는 다릅니다. 프로세스와 수명이 분리되어 vLLM이 재시작되든 다른 노드의 vLLM이 꺼내든 그대로 남아 재사용을 기다립니다. 프로세스 수명에서 캐시를 분리시키는 것 자체가 이 아키텍처의 존재 이유라고 요약할 수 있겠습니다.

이 경로가 AI 추론 워크로드의 실전 수요처입니다. 프리필 재사용이나 P/D 분리(prefill과 decode를 서로 다른 노드에 맡기는 배치) 같은 시나리오가 원격 스토리지 수요를 실제로 부르는 곳이죠. 검증 보고서의 수요 분석(§8)이 "NVIDIA 환경 고객이 부르는 것은 libcuobjclient다"라는 포지셔닝에 도달한 것도 이 파이프라인을 통해서였습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch06-02-lmcache.svg" alt="LMCache의 문제와 해법 대비: 왼쪽은 vLLM 추론의 KV 캐시가 GPU HBM을 압박해 배치 축소와 컨텍스트 제한, 프리필 중복 계산이 생기는 모습, 오른쪽은 LMCache가 KV 블록을 캐싱해 NIXL과 OBJ accelerated engine을 거쳐 cuObject로 원격 스토리지에 보내 HBM 여유를 만드는 구조" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 · 문제는 KV 캐시의 HBM 압박, 해법은 원격 캐시 계층. 전송은 NIXL 경유 cuObject로 이뤄진다</figcaption>
</figure>

## 3. elbencho, 직접 호출하는 벤치마크

elbencho는 스토리지 벤치마크 도구인데 `--cuobj` 플래그로 cuObject를 직접 호출합니다. NVMe와 GDS, cuObject를 아우르는 통합 측정이 가능하고 PUT/GET 처리량과 레이턴시, 분산 확장까지 함께 봅니다.

```bash
# NVMe · GDS · cuObject를 아우르는 통합 벤치마크
elbencho --cuobj <S3 게이트웨이 엔드포인트>
# PUT/GET 처리량 · 레이턴시 · 분산 확장 측정
```

주목할 점은 이런 도구가 드물다는 사실입니다. cuObject는 폐쇄 라이브러리인 데다 와이어 프로토콜까지 비공개라, 이를 직접 소비하는 오픈소스는 NIXL과 elbencho가 사실상 전부라고 봐도 됩니다.

호출 계층은 그림 3의 순서입니다. elbencho가 libcuobjclient로 GPU 버퍼를 등록하면 게이트웨이의 libcuobjserver가 HTTP 제어와 DC QP 데이터로 응답하고, posix 백엔드에서 객체는 곧 실파일로 떨어집니다.

한 가지 구분은 분명히 해둡니다. 정합성 입증에 elbencho를 쓰지는 않았습니다. 그 역할은 자체 클라이언트(cuobjtest)가 맡았는데, libcuobjclient 계열 GPU-direct 경로와 host 계열로 CX4와 CX6 두 세대에서 검증을 마쳤습니다. elbencho는 이후 고객 환경 벤치마킹의 후보로 남아 있습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch06-03-elbencho.svg" alt="elbencho의 호출 계층: elbencho가 libcuobjclient로 GPU 버퍼를 등록하고 게이트웨이의 libcuobjserver와 HTTP 제어·DC QP 데이터로 통신하며 posix 백엔드의 Lustre 실파일에 객체가 착지하는 흐름과 직접 호출 오픈소스가 드문 이유" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3: elbencho에서 게이트웨이, posix 백엔드까지의 호출 계층. 직접 호출 오픈소스가 드문 이유는 폐쇄 라이브러리와 비공개 프로토콜</figcaption>
</figure>

## 4. 실전 파이프라인, vLLM에서 원격 S3까지

지금까지의 생태계를 하나의 흐름으로 잇습니다.

```text
vLLM → KV cache(GPU HBM) → LMCache → NIXL → cuObject → 원격 S3
```

각 단계의 역할을 표로 옮기면 이렇습니다.

| 단계 | 하는 일 |
|------|---------|
| vLLM | 추론 엔진. 긴 컨텍스트일수록 KV 캐시가 HBM을 압박한다 |
| KV cache | GPU HBM 상의 블록. 오프로드 대상 |
| LMCache | 캐시 계층. 프리필 재사용, P/D 분리 시나리오를 담는다 |
| NIXL | 벤더 중립 이식 계층. GDS, cuObject, UCX를 통합 API로 감싼다 |
| cuObject | 전송. NIXL의 OBJ accelerated engine 기반으로 실제 움직인다 |
| 원격 S3 | 게이트웨이(libcuobjserver)와 Lustre 백엔드에서 객체가 착지한다 |

흐름의 착지점은 원격 S3 게이트웨이입니다. 게이트웨이 루트(gwroot)가 Lustre 백엔드(kvcache-s3)를 가리키는 구성에서 KV 오브젝트는 프로세스와 수명이 분리된 채 실파일로 남습니다. 절약된 HBM은 더 큰 배치와 더 긴 컨텍스트로 돌아옵니다.

게이트웨이 자체의 구조, 즉 제어는 HTTP(SigV4)이고 데이터는 RDMA로 갈라지며 정확히 2왕복인 세션 프로토콜은 RDMA 학습 시리즈 [6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)에서 해부했습니다.

규모의 감각도 짚어둡니다. 사용자 채팅 세션은 연결이 아니라 오브젝트(PUT/GET)일 뿐이고, 연결의 단위는 vLLM 인스턴스의 libcuobjclient입니다. 그래서 수십만 세션을 섬기는 서비스라도 클라이언트 노드는 수십에서 수백 개 수준에서 멈춥니다. 세션 수와 연결 수는 자릿수가 다릅니다.

이 파이프라인이 전략적으로 중요한 까닭은 수요의 방향입니다. vLLM과 LMCache, NIXL의 KV 오프로드가 전부 cuObject로 묶여 있으니 NVIDIA GPU 고객의 S3-over-RDMA 수요는 결국 libcuobjclient 호출로 귀결됩니다. 검증 보고서가 권고 첫 순서에 cuObject 제품화를 놓은 근거가 바로 여기 있습니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch06-04-pipeline.svg" alt="실전 파이프라인 6단계: vLLM이 만든 KV cache가 GPU HBM에서 LMCache로 나오고 NIXL의 벤더 중립 계층을 지나 cuObject로 전송되어 게이트웨이와 Lustre 백엔드에 도달하며 HBM 절약이 더 큰 배치와 긴 컨텍스트로 돌아오는 그림" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4, KV 오프로드가 부르는 S3-over-RDMA. 절약된 HBM은 더 큰 배치와 긴 컨텍스트로 돌아온다</figcaption>
</figure>

<figure>
  <img src="/assets/images/posts/cuobject-study/qa-cu4-q02.svg" alt="스터디 Q&A 카드: LLM을 전부 사용하고 종료되면 없어지는 객체들인가요? HBM 안의 KV 캐시는 휘발성이라 사라지지만 오프로드한 KV 오브젝트는 프로세스와 수명이 분리돼 지울 때까지 남고 TTL과 LRU eviction으로 관리된다" loading="lazy"/>
</figure>

## 5. NIXL #2241, 표준화 제안

NIXL 저장소에는 #2241 "generic S3-over-RDMA" 표준화 제안이 열려 있습니다. 상태는 open, 아직 머지되지 않았습니다. 내용은 S3-over-RDMA를 특정 벤더 라이브러리에 두지 않고 NIXL의 범용 전송 계층으로 올리자는 것인데, 현재 그 구현 실체는 cuObject입니다.

| 시나리오 | 구조 | RC 계열의 자리 |
|----------|------|----------------|
| 채택 시 | 벤더 중립 엔진으로 표준화. cuObject가 NVIDIA 전용이라는 경계가 흐려짐 | 같은 계층에 닿는 길이 생김 |
| 보류 시 | 현 구조 유지. NVIDIA 진영은 cuObject 중심 | AMD와 비 ConnectX NIC 담당(듀얼 구조) |

어느 쪽이든 당장의 아키텍처는 바뀌지 않습니다. 판정이 나기 전까지 cuObject는 NVIDIA GPU에서 KV 오프로드의 사실상 표준 자리를 지키고, RC 계열은 AMD와 비 ConnectX NIC이라는 자기 영역을 담당합니다. 그래서 이 제안을 결말이 아니라 지켜볼 지평으로 기록해 둡니다.

<figure>
  <img src="/assets/images/posts/cuobject-study/ch06-05-nixl-2241.svg" alt="NIXL #2241 제안의 현재 상태와 두 시나리오: open 상태의 generic S3-over-RDMA 제안이 범용 전송 계층으로 올라가면 벤더 중립 엔진으로 표준화되고 RC도 NVIDIA 스택에 닿으며, 보류되면 cuObject 중심의 현 구조가 유지되는 분기 그림" />
  <figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5. 판정이 나기 전까지는 지켜볼 지평. 어느 쪽이든 당장의 아키텍처는 바뀌지 않는다</figcaption>
</figure>

## 마무리

4편을 관통한 질문은 "누가 쓰고 있나"였습니다. 답은 선명합니다. 이식 계층(NIXL)과 추론 캐시(LMCache)라는 실전 소비자가 이미 cuObject 위에 올라타 있고, 벤치마크 도구(elbencho)까지 직접 호출을 지원합니다. 그 수요는 표준화 제안(#2241)이라는 다음 국면을 향해 움직이고 있었습니다.

되짚으면 순서는 이렇습니다. 하드웨어가 만든 좌표(1편), 그 위의 파일과 전송 계층 그리고 물리적 상한(2편), 객체 전송의 아키텍처(3편), 소비자와 지평(4편). 아래로 내려갈수록 추상화 대신 수요가 두터워지는 순서였습니다.

## 시리즈 마무리

cuObject 학습 시리즈 4편이 여기서 완결됩니다. GPU가 버스와 메모리를 어떻게 쓰는지에서 시작해, 객체 전송 프로토콜을 지나, 마침내 그것을 부르는 생태계에 닿았습니다.

1. [cuObject 학습 시리즈 (1/4): GPUDirect RDMA](/2026/10/04/cuObject-Study-01-GPUDirect-RDMA/)
2. [cuObject 학습 시리즈 (2/4): cuFile·GDS·BAR1](/2026/10/04/cuObject-Study-02-cuFile-GDS-BAR1/)
3. [cuObject 학습 시리즈 (3/4): cuObject 아키텍처](/2026/10/04/cuObject-Study-03-cuObject-Architecture/)
4. [cuObject 학습 시리즈 (4/4): 생태계, NIXL·LMCache·elbencho](/2026/10/04/cuObject-Study-04-Ecosystem/) (이 글)

와이어 레벨의 프로토콜 해부가 궁금하다면 RDMA 학습 시리즈 [6편, S3 over RDMA와 cuObject 프로토콜](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)이 가장 가까운 이웃입니다. 시작은 GPU I/O의 물리였고 끝은 생태계였습니다. 그 사이의 모든 층이 "메모리를 직접 움직인다"는 하나의 원리 위에 서 있었죠. 이 지도가 다음 여정의 출발점이 되길 바랍니다.
