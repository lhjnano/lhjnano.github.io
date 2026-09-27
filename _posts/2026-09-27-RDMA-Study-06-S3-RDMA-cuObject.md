---
layout: post
title: "RDMA 학습 시리즈 (6/7): S3-over-RDMA — cuObject 데이터플레인"
categories: [RDMA, Networking]
description: "S3 API는 그대로 두고 PUT/GET 본문만 RDMA로 흘릴 수 있을까요? cuObject 게이트웨이 구축부터 GPU HBM 직송 실측, 동시성 천장 격리까지 정리했습니다."
keywords: [S3 over RDMA, cuObject, GPUDirect, peermem, BAR1, versitygw, vgwrdma]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (6/7). 소스: 검증 클러스터(stg-node1/2) S3-over-RDMA 검증 보고서(2026-09-22~26) 실측 기반.

지금까지 이 시리즈는 RDMA를 "부품"의 관점에서 봤습니다. NIC 내부구조부터 verbs 프로그래밍까지, 각 층이 어떻게 생겼는지를 열어봤죠. 이번 편부터는 이 부품들을 조립해 실제 서비스에 얹는 이야기입니다.

주인공은 NVIDIA의 cuObject 데이터플레인입니다. S3 API는 그대로 두고 PUT/GET의 본문만 RDMA로 흘리는 설계인데, 1차 검증 당시에는 "cuObject는 IB에서 불가하다"는 결론이 남았었습니다. 이번 검증에서 그 제약이 CX4 VF 환경 한정이었음이 밝혀졌고, CX6 네이티브 IB에서 GPU HBM 직송까지 완주했습니다. 제약의 정체는 IB가 아니라 NIC의 세대와 구성이었던 셈입니다.

## TL;DR

- S3 API(REST·SigV4)는 그대로, 데이터 본문만 cuObject(DC transport)로 직행한다
- 서버 요건은 바이너리 2개뿐 — el8 inbox verbs로 충분했고 "el9 필요"는 패키징 오류로 판명
- 무거운 쪽은 클라이언트다: ConnectX NIC, peermem(또는 dma-buf), 전송 크기 ≤ BAR1
- 실측은 PUT ~1.8×, GET ~1.7× RDMA 우위. 다만 동시 스트림을 늘리면 두 경로 모두 ~7 GB/s 부근에서 둔화
- 천장은 여섯 가설을 배제하고 클라이언트 측 전송경로로 좁혀졌다 — 완전한 분리는 후속 과제로 표기

## 1. S3-over-RDMA 경로 개관

그림 1이 전체 경로입니다. 기억할 대비는 두 가지입니다. 첫째, 제어와 데이터의 분리. 버킷 생성이나 세션 수립 같은 제어는 여전히 HTTP(SigV4)이고, 데이터만 cuObject로 직행합니다. 둘째, 요건의 비대칭입니다. 스토리지 노드 쪽은 `libcuobjserver` 바이너리 하나로 el8 inbox verbs에서 동작하는 반면, 고객 GPU 노드는 ConnectX NIC과 peermem(또는 dma-buf) 경로가 필요합니다. 서버는 가볍고 클라가 무겁다는 제품 구조가 여기서 나옵니다.

검증은 이 경로를 검증 클러스터(stg-node1/2) 위에서 처음부터 끝까지 열어냈습니다. 고객 GPU 노드(gpu-1, RTX A6000)에서 GPU HBM 직송 PUT/GET까지, 체크섬 전 구간 통과로요.

<figure>
<img src="/assets/images/posts/rdma-study/ch06-04-cuobject-path.svg" alt="S3-over-RDMA 전체 경로 — 고객 GPU 노드(RTX A6000 BAR1 256MiB·CX6·libcuobjclient+cuFile)에서 회색 제어 경로(HTTP·SigV4)와 청록 데이터 경로(cuObject DC — GPU HBM peermem 등록 또는 host MR)가 검증 클러스터 게이트웨이(stg-node, CX6 inbox·libcuobjserver)로 내려가고 posix 백엔드를 거쳐 Lustre /vol0로 이어지고, 맨 아래 IB 200G HDR 패브릭 바와 IPoIB netdev MTU 대비 각주가 붙는다"/>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 — S3-over-RDMA 전체 경로. 제어는 HTTP, 데이터는 cuObject. GPU-direct 경로는 GPU HBM을 peermem으로 직접 등록해 호스트 메모리 경유 없이 전송한다. 모든 경로는 같은 IB 패브릭(MTU 4096) 위를 지나지만 제어(HTTP)만 IPoIB netdev MTU(1500/2044)에 묶인다.</figcaption>
</figure>

이 글의 구성은 이렇습니다. 2절에서 서버 쪽 게이트웨이 구축을, 3절에서 클라이언트 쪽 관문을 다룹니다. 4절은 개통 증거와 실측, 5절은 동시성 스케일과 천장의 격리, 6절은 제품화 전망입니다.

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch06-q03.svg" alt="스터디 Q&A 카드 — S3 over RDMA는 API가 아닌가 보네요? 라는 질문에 API가 아니라 구현(전송 계층)의 문제이고 API는 그대로 유지되며 전송 부분은 아직 미표준이라고 답한다"/>
</figure>

## 2. 서버 — libcuobjserver와 게이트웨이 구축

게이트웨이는 `vgwrdma`(versitygw v1.8.0)에 NVIDIA `libcuobjserver`를 얹어 구동합니다(검증 보고서 §3). 이 장의 핵심 발견부터 짚겠습니다. "게이트웨이는 el9가 필요하다"는 통념이 검증 없이 계승된 오류였다는 것입니다. 실제 제약은 NVIDIA가 rhel8용 서버 패키지를 내놓지 않는 패키징 문제뿐이었습니다(상세 근거는 3편 §2).

| 항목 | 확인 결과 |
|------|-----------|
| NVIDIA 리포 | rhel8: libcuobjclient만 존재(서버 없음) / rhel9: libcuobjserver 1.2.0.68 · 2.0.0.109 |
| libcuobjserver.so 요구 심볼 | 최대 GLIBC_2.14(1.2) / GLIBC_2.16(2.0), GLIBCXX_3.4.21 — el8(glibc 2.28)로 충분 |
| DT_NEEDED | libibverbs·librdmacm·libmlx5·libnuma·libstdc++ — stg-node1에서 ldd 결손 0 |

배포 방식은 그래서 단순해집니다. rhel9 rpm에서 .so를 추출해, vgwrdma 바이너리와 libcuobjserver.so.1.2.0(심링크 .so.1) 두 파일만 스토리지 노드에 내리면 됐습니다. 패키지 설치 0건, 커널 변경 없음. 결과는 완전했습니다. el8 inbox verbs에서 DC QP 생성(`mlx5dv_create_qp`)과 INIT→RTR→RTS 전환이 전부 통과했고, bond0 위의 IPoIB IP도 mlx5_0으로 정상 역매핑됐습니다.

### 버전 핀 — v1.8.0은 libcuobjserver 1.x 전용

서버 라이브러리 버전은 마음대로 고를 수 없습니다. v1.8.0은 1.2.0.68과 정합하고, 2.0.0.109로 빌드하면 `setTelemFlags(unsigned)` 시그니처가 `(unsigned, unsigned)`로 바뀌고 `initRDMAConfigParams`가 삭제돼 컴파일이 실패합니다. 2.x 지원은 래퍼 2곳의 조건부 패치 17줄(`CUOBJ_SERVER_MAJOR_VERSION>=2`)로 가능하며, upstream에 동일 취지의 커밋(ee25c95)이 이미 있습니다.

A/B 실측(4절)에서 두 버전의 성능은 동일했습니다. 2.x로 가야 하는 이유가 성능이 아니라 라이프사이클이라는 뜻입니다. 메이저 전환 시 주의점 하나: `rm -f rdma/libcuobjwrapper.a`를 먼저 지워야 합니다. 스테일 아카이브가 2.x 심볼을 1.x lib에 링크해 실패시킵니다.

### 포트맵과 기동

게이트웨이 노드의 포트 구성은 :7070 HTTP, :7071 cuObject 1.2.0.68, :7072 cuObject 2.0.0.109입니다. 두 버전을 나란히 띄워 A/B와 상호운용 검증이 가능했습니다. 기동 커맨드는 이렇게 짧습니다.

```bash
VGW_RDMA_IP=100.64.33.243 VGW_RDMA_PORT=19100 CUFILE_ENV_PATH_JSON=versitygw/cufile.json \
  vgwrdma --port 0.0.0.0:7071 posix /lustre/agent/vol0/kvcache-s3-<host>
# cufile.json = {"properties":{"rdma_dev_addr_list":["100.64.33.243"]}}
```

백엔드는 posix이고 gwroot가 Lustre /vol0를 가리킵니다(7편 §4). 평문 HTTP 게이트웨이는 CGO_ENABLED=0 정적 빌드로 그대로 실행됐고, Lustre user_xattr이 켜져 있어 `--nometa`도 불필요했습니다.

정리하면 서버 요건은 이렇게 됩니다. 스토리지 노드가 cuObject 게이트웨이에 요구하는 것은 바이너리 2개뿐 — MOFED 불필요(inbox OFED로 DC QP까지 통과), 컨테이너 불필요, 패키지 설치 0건. 종전의 "el9·MOFED 필요" 통념이 무너진 자리에, MOFED는 클라이언트(고객 GPU 노드) 요건으로 자리를 옮겼습니다. 요건의 방향이 뒤집힌 것이 이번 검증의 구조적 발견입니다.

## 3. 클라 — libcuobjclient와 GPU-direct

정식 클라이언트는 NVIDIA libcuobjclient입니다(CUDA Toolkit ≥ 13.1.1 계열, 검증은 1.2.0.68). 전송 모드는 두 가지입니다. GPU-direct는 cuFile이 GPU 메모리를 peermem으로 RDMA 등록해 HBM에 직접 닿는 그림 1의 청록 레인이고, host-memory는 cuObject 토큰 프로토콜로 호스트 MR을 쓰는 모드입니다(peermem 불필요). 두 모드 모두 게이트웨이의 libcuobjserver를 향합니다.

### peermem 관문 — GPU-direct의 입장료

NVIDIA 독점 드라이버는 `dmaBufCapable:0`으로 태어납니다. 그래서 cuFile은 nvidia_peermem(또는 dma-buf 경로) 없이는 RDMA를 비활성합니다. 로그로는 "nvidia_peermem.ko is not loaded. Disabling UserSpace RDMA access" 한 줄로 나오죠. peermem은 MOFED `ib_core`의 `ib_register_peer_memory_client`를 요구하므로, 고객 GPU 노드의 커널 스택 선정이 관문이 됩니다(검증 보고서 §5).

| 경로 | 판정 |
|------|------|
| el9_8 최신 커널에서 MOFED 24.10 소스 빌드 | 컴파일 실패(from_timer·fw_fatal_reporter — RHEL 9.8 백포트 불일치). 벤더 MOFED/DOCA는 rhel9.6까지만 제공 |
| A. nvidia open-dkms + CUFILE_DMABUF_ENABLE | libcufile 1.18의 `ibv_reg_dmabuf_mr` 경로 — inbox rdma-core로 MOFED 불필요. 미검증, 제품 방향으로 유력 |
| B'. el9_6 커널 일회성 부팅 + 기존 MOFED + dkms nvidia + peermem | 채택 — 리부팅 전 dkms build/install, 부팅 후 modprobe OK. 129초 복귀, IB 링크 ~30초 후 Active |

### BAR1 한계 — GPU-direct 전송 크기의 물리적 상한

GPUDirect RDMA는 GPU 메모리를 BAR1 창으로 매핑해서 DMA를 걸고 갑니다. 검증 클라이언트 RTX A6000의 BAR1은 256 MiB입니다. 그래서 192 MiB까지는 정상 동작하지만 224 MiB부터 `cuMemObjGetDescriptor rc=1`로 실패합니다. cufile.log에도 "BAR 1 size detected via NVML API: 256 MiB"라고 기록되더군요. H100(BAR1 128 GiB)급 데이터센터 GPU는 해당 없는 이야기입니다.

고객 안내 문구가 하나 나옵니다. GPU-direct 전송 크기는 BAR1 여유 이하로. BAR1이 부족한 시나리오는 host-memory 모드가 대안입니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch06-05-client-prereqs.svg" alt="클라이언트 요건 2패널 — 좌: peermem 관문(독점 드라이버 dmaBufCapable 0 → cuFile RDMA 비활성 → 해결 B' MOFED+dkms 채택, A open-dkms dma-buf 대안), 우: BAR1 한계(256MiB 창, 192MiB OK 초록, 224~256MiB 실패 빨강, H100 무관, 전송크기 BAR1 이하 안내)"/>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 — 클라이언트의 두 가지 현실적 제약. 둘 다 고객 GPU 노드의 사양이지 게이트웨이의 사양이 아니다.</figcaption>
</figure>

### GID 선택 — 네이티브 IB에서는 idx0

네이티브 IB 포트의 유효 GID는 idx0(fe80:: link-local) 하나뿐입니다(2편 §3). cuFile은 이를 스스로 처리합니다. "Device mlx5_0: IB link layer, using default GID index 0"가 그 증거죠. 그런데 versitygw의 host-memory 클라이언트 래퍼는 RoCE를 전제로 link-local을 건너뛰도록 짜여 있었습니다. 네이티브 IB에서는 `VGWRDMA_GID_INDEX=0` 명시가 필수입니다(8편 §2의 관문 ①).

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch06-q15.svg" alt="스터디 Q&A 카드 — NVIDIA 쪽 데이터플레인은 VRAM을 활용한 RDMA인가요? 라는 질문에 네, GPUDirect로 호스트 RAM 경유 없이 VRAM에 직접 닿으며 RC 계열은 호스트 메모리 MR을 쓴다고 답한다"/>
</figure>

## 4. 실증 — 개통 증거와 성능

개통의 증거는 cufile.log 세 줄입니다(검증 보고서 §4.1).

```text
nvidia_peermem is enabled                                  # peermem 관문 통과
Device mlx5_0: IB link layer, using default GID index 0    # 네이티브 IB GID 자동 처리
register with RDMA success mr_size: 67108864               # GPU HBM 64 MiB RDMA 등록
```

이 세 줄이 뜨는 순간 GPU-direct 데이터플레인이 열린 것입니다. 실측 결과는 다음과 같습니다(모두 n=10, GB/s, PUT/GET).

| 대상 | 4 MiB | 64 MiB | 128 / 192 MiB | 256 MiB |
|------|-------|--------|----------------|---------|
| stg-node1 · 서버 1.2.0.68 (GPU-direct) | 0.450 / 2.096 | 0.523 / 3.655 | 0.531/2.919 · 0.538/2.860 (n=3) | 클라 BAR1 한계 |
| stg-node1 · 서버 2.0.0.109 (GPU-direct) | 0.425 / 2.154 | 0.520 / 3.616 | — | 동일 |
| stg-node2 · 서버 1.2.0.68 (GPU-direct) | 0.379 / 1.718 | 0.513 / 3.139 | — | 동일 |
| (참조) HTTP → stg-node1 | 0.249 / 1.314 | 0.333 / 2.225 | — | 0.306 / 2.033 |

전 iteration 체크섬 OK, 객체는 Lustre 실파일(`lfs getstripe`로 raid0 확인), 클라이언트 1.2 ↔ 서버 2.0 상호운용까지 확인됐습니다. host-memory 모드도 같은 그림입니다. 256 MiB 기준 RDMA(host) PUT 0.548 / GET 3.904 vs HTTP 0.301 / 2.258.

요약하면 이 환경(네이티브 IB)에서 RDMA가 PUT ~1.8×, GET ~1.7×로 전 구간 우위입니다. 이유는 2편 §6에서 본 MTU 이중구조입니다. HTTP는 IPoIB netdev MTU 1500에 묶이고 RDMA는 링크 MTU 4096으로 직행합니다. PUT이 GET보다 느린 프로파일은 백엔드(Lustre 쓰기 경로)가 상한인 구조로, 7편 §4의 HTTP 실측과 같은 요인입니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch06-03-cuobject-evidence.svg" alt="cuObject 실증 종합 3패널 — 개통 증거(cufile.log 3줄), 성능 막대(4/64/128/192 MiB의 PUT·GET 쌍), BAR1 경계(192 OK와 224~256 실패, BAR1 256MiB 창)"/>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 — 실증의 세 가지 얼굴. 개통 증거(좌), 크기별 성능(중), GPU-direct의 물리적 상한인 BAR1 경계(우).</figcaption>
</figure>

## 5. 동시성과 천장

단일 스트림이 아니라 동시 스트림을 늘리면 어떻게 될까요(검증 보고서 §6). 64 MiB GET을 C개의 동시 스트림으로 돌린 sum-of-rates입니다. RDMA는 C=1 3.21 → C=2 6.04 → C=4 7.05 → C=8 7.34 GB/s(2.29×), HTTP는 2.28 → 7.02(3.08×). 두 경로 모두 ~7 GB/s 부근에서 증가가 둔해집니다. 천장이 보입니다.

천장의 위치를 가리기 위해 여섯 가설을 하나씩 배제했습니다. 패브릭은 raw `ib_write_bw` GET 방향 1QP 195.6 / 8QP 196.1 Gb/s(≈24.5 GB/s 라인레이트)로 여유가 있었고, 백엔드는 8-way warm Lustre read 75.5 GB/s, 게이트웨이 CPU는 C=8에서 0.72 CPU-초(96코어 중 1개 미만)였습니다. RDMA 버퍼 풀을 기본 4에서 16×256 MiB로 늘려도 7.25, 8스트림을 두 게이트웨이에 4+4로 분산해도 7.27, op당 오버헤드 가설도 256 MiB 4배 확대로 레이턴시만 비례(83.5→309ms)하고 C=8 6.95로 대역폭 천장임이 확인됐습니다.

배제를 다 통과하고 남는 유일 후보는 클라이언트 측 전송경로입니다. CPU 5.71 CPU-초(≈6.6코어 사용 중), softirq 0.11, PCIe Gen4 ×16.

> **정직한 기록 — 천장의 귀속은 아직 미분리.** 이 측정의 클라이언트는 versitygw의 host-memory 클라이언트(rdma_host_client_wrapper)였습니다. 그래서 ~7 GB/s 천장이 그 클라 구현의 한계인지, cuObject 공통 경로의 한계인지는 아직 가려지지 않았습니다. GPU-direct 경로 또는 두 번째 클라이언트 노드로 실험을 반복해야 분리됩니다. 어디까지 확정되고 어디부터 미분리인지 표기해 두는 것 자체가 후속 실험의 출발점입니다(8편 §5).

<figure>
<img src="/assets/images/posts/rdma-study/ch06-06-concurrency-scale.svg" alt="동시성 스케일과 천장 — 좌: C=1/2/4/8의 RDMA·HTTP 막대(3.21→7.34 / 2.28→7.02 GB/s, 배수 표기), 우: 가설 6종 배제 후 남는 클라 측 전송경로와 미분리 주석"/>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 — 동시성 스케일(좌)과 천장 격리(우). 여섯 가설을 배제하는 소거법은 8편 §1의 계층 진단과 같은 문법이다. 방법은 환경이 바뀌어도 유효합니다.</figcaption>
</figure>

## 6. 제품화 전망

검증이 남긴 제품 스토리는 명확합니다(검증 보고서 §10). 1단계 권고는 cuObject 제품화입니다. versitygw main(2.0 포팅 포함)과 libcuobjserver를 검증 클러스터에 패키징하고 — el8 동작은 검증됐으니 NVIDIA가 el8 서버 패키지를 내놓지 않는 문제의 지원 스토리(rhel9 rpm 추출 vs NVIDIA 문의)만 결정하면 됩니다. 그리고 고객 GPU 노드의 전제조건을 문서화합니다.

| 전제조건 | 내용 |
|----------|------|
| NIC | ConnectX 계열 — cuObject의 DC transport는 Mellanox 전용 |
| GPU 메모리 경로 | nvidia_peermem(MOFED) 또는 open-dkms + dma-buf(대안 A, 검증 과제) |
| 전송 크기 | GPU-direct ≤ BAR1 여유 — 부족하면 host-memory 모드 |
| GID | 네이티브 IB에서는 idx0 — cuFile은 자동, host 클라는 `VGWRDMA_GID_INDEX=0` |

생태계의 방향도 짚어둡니다. cuObject의 실제 소비자는 이미 존재합니다. NIXL의 OBJ accelerated engine(Dell/NVIDIA 머지), elbencho의 --cuobj, LMCache→NIXL 경로가 전부 cuObject로 묶입니다. NIXL의 "generic S3-over-RDMA" 이슈(#2241, 아직 open)가 범용 전송으로 확장되면 선택지는 더 넓어지겠죠. 지켜볼 지표입니다.

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch06-q16.svg" alt="스터디 Q&A 카드 — AI용이면 VRAM RDMA는 필요 없나요? 라는 질문에 일반론은 반대로 AI일수록 가치가 올라가며, 필요 없어지는 조건과 DC 전송 외 대안이 있다고 답한다"/>
</figure>

### 6편 총정리

이 편에서 우리는 S3-over-RDMA를 "라이브러리가 하는 일"의 관점에서 다뤘습니다. 서버는 바이너리 2개(el8 inbox), 클라는 peermem과 BAR1이라는 물리적 관문, 그리고 개통 증거·성능·천장이라는 실측. 통념이 검증으로 무너지는 과정(el9, MOFED의 방향)과, 확정된 것과 미분리인 것을 구분해 기록하는 태도가 이번 검증이 남긴 두 가지 수확입니다.

**다음 편 예고**: [RDMA 학습 시리즈 (7/7): 스토리지 스택](/2026/09/27/RDMA-Study-07-Storage-Stacks/) — 이 경로가 앉혀진 스토리지 스택 전체(Lustre /vol0까지)를 다룹니다. 데이터플레인이 도달하는 최종 착지점을 스택의 아래부터 다시 올라가 봅니다.
