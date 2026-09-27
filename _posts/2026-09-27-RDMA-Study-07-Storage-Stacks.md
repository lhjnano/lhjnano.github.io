---
layout: post
title: "RDMA 학습 시리즈 (7/7): 스토리지 스택 — Lustre·LNet·versitygw"
categories: [RDMA, Networking]
description: "Lustre는 LNet 아래에서 어떻게 RDMA를 쓰고, S3 게이트웨이는 어떻게 그 위에 올라설까요?"
keywords: [Lustre, LNet, o2ib, versitygw, S3 over RDMA, NVMe-oF]
toc: true
toc_sticky: true
---

> RDMA 학습 시리즈 (7/7). 소스: 내부 S3-over-RDMA 검증 보고서(2026-09-22~26)와 학습 대화록.

지금까지 여섯 편에서 다룬 RDMA는 "두 노드가 어떻게 메모리를 주고받는가"였습니다. 이 마지막 편에서는 그 전송 능력이 실제 서비스에 붙어 도는 계층을 봅니다. 하드웨어에서 시작해 verbs까지 내려온 길이 스토리지에서 완성되는 셈입니다.

무대는 두 개입니다. 초기 시험(node-a/b/c, ConnectX-4 VF)은 Lustre 스택 자체를 다루는 1~3절의 기록이고, 검증 환경(gpu-1·stg-node1/2, ConnectX-6 네이티브 IB)은 4절부터 합류해 S3-over-RDMA 전체 경로를 완성합니다. 같은 층계가 하드웨어 세대를 바꿔 어떻게 재검증되는지도 함께 보이는 구성입니다.

## TL;DR

- Lustre의 모든 RPC는 LNet 메시지로 운반되며, NID의 타입 문자열(`o2ib`)이 LND 플러그인(ko2iblnd)을 선택한다
- ko2iblnd는 RC QP를 만들고 MR로 메모리를 등록해 커널 안에서 RDMA로 스토리지 트래픽을 실어 나른다
- 마운트 실패의 진짜 원인은 네트워크가 아니라 설정 로그와 ZFS 속성에 남은 과거의 주소였다
- versitygw는 객체=파일, 메타데이터=xattr로 S3를 POSIX 위에 얹는다 — 그래서 user_xattr이 필수 옵션이다
- S3-over-RDMA는 제어는 HTTP(SigV4), 데이터는 RDMA로 갈라지고, 2026-09-22 전 경로가 완성됐다
- 데이터플레인은 cuObject(DC)와 RC 두 갈래 — 대체가 아니라 커버리지 확장으로 양립한다

## 1. Lustre 스택과 LNet

검증 클러스터의 스토리지는 대규모 HPC 표준인 오픈소스 병렬 파일시스템 Lustre입니다. 초기 시험의 클러스터는 Lustre 2.15.8에 ZFS 백엔드를 얹은 lmcfs 파일시스템이고, 모든 트래픽이 InfiniBand(o2ib) 위를 흐릅니다.

Lustre의 두 축은 메타데이터와 데이터입니다. 메타데이터 서버(MDT)가 디렉터리·권한·스트라이프 정보를 관리하고, 실제 파일 내용은 스토리지 타깃(OST)들이 나눠 저장합니다. 클라이언트는 두 종류 서버와 각각 RPC로 대화하는데, 이 RPC가 최하단에서 LNet → LND → RDMA 패브릭을 거쳐 운반됩니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-01-lustre-stack.svg" alt="Lustre 클라이언트 스택과 서버 토폴로지 — VFS에서 llite, lmv·lov, mdc·osc, ptlrpc, LNet, LND 플러그인을 거쳐 InfiniBand 패브릭으로, 서버 노드의 MGS+MDT0000, OST0000, OST0001" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - Lustre 클라이언트 스택과 서버 토폴로지. 모든 Lustre RPC는 LNet 메시지로 운반된다</figcaption>
</figure>

### 클라이언트 스택 — 시스템콜에서 패브릭까지

그림 1의 왼쪽 열을 위에서부터 짚습니다. 각 층은 자기 바로 아래 층만 안다는 점이 스택이 스택인 이유입니다.

| 계층 | 역할 |
|------|------|
| VFS | 커널 가상 파일시스템 — 앱의 read/write 시스템콜이 처음 도착하는 지점 |
| llite | Lustre의 VFS 접착 계층 — 표준 파일 연산을 Lustre 의미론으로 번역 |
| lmv · lov | MDT·OST 스트라이프 논리 — 파일이 여러 OST에 어떻게 쪼개지는지 결정 |
| mdc · osc | 메타데이터·데이터 타깃 클라이언트 — 각각 MDT·OST와 통신하는 RPC 클라이언트 |
| ptlrpc | Lustre RPC 의미론 — 요청-응답, 타임아웃, 장애 복구의 규칙 |
| LNet | 전송 독립 메시지 계층 — NID로 "어느 노드로"만 정하고 하부 전송은 가린다 |
| LND 플러그인 | 실제 전송 구현 — socklnd(TCP) 또는 o2iblnd(InfiniBand RDMA) |

포인트는 LNet 아래만 바꾸면 전송 기술이 통째로 교체된다는 것입니다. socklnd 위에서 돌던 Lustre가 o2iblnd로 갈아타면 같은 파일시스템이 RDMA의 대역폭을 그대로 누립니다. 스택 전체를 고칠 필요 없이 플러그인 하나면 됩니다.

### 서버 토폴로지와 핵심 용어

초기 시험의 서버 구성과 이 절의 용어를 한 표에 묶습니다.

| 용어 | 뜻 | 이 클러스터에서 |
|------|-----|----------------|
| MGS | 클러스터 전체 설정 배포 서비스 | MDT0000이 MGS를 겸함 (172.16.44.41@o2ib) |
| MDT | 메타데이터 타깃 — 디렉터리·권한·스트라이프 | ZFS lustre-mdt0/mdt0 |
| OST | 객체 스토리지 타깃 — 파일 내용 실체 | OST0000(.41) · OST0001(.42) |
| LNet | 전송 독립 메시징 계층, NID 라우팅 | 모든 RPC의 운반로 |
| LND | LNet의 전송 플러그 인터페이스 | o2iblnd(커널 모듈 ko2iblnd) 채택 |

클라이언트는 node-a(게이트웨이 노드)와 node-b의 루프백 마운트이며 마운트포인트는 `/mnt/lustre`, MGS NID는 `172.16.44.41@o2ib`입니다. 이 주소 형식이 다음 절의 주인공입니다.

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch07-q10.svg" alt="스터디 Q&A 카드 — LNet도 RDMA를 쓰는데 사용법이 다른 건 없을 텐데 래퍼라서 그런가요? RDMA를 소유하는 계층의 차이" />
</figure>

## 2. LNet NID와 o2ib

LNet 세계에서 노드의 주소는 NID(Network Identifier)입니다. 형식은 `IP주소@네트워크타입`이어서, MGS NID를 다시 보면 앞부분 `172.16.44.41`은 ib0(IPoIB)에 부여한 IP 주소이고 뒷부분 `o2ib`는 네트워크 타입 문자열입니다.

이 문자열이 곧 LND를 선택합니다. `o2ib`면 ko2iblnd가, `tcp`면 socklnd가 그 메시지를 운반합니다. 노드 하나가 여러 네트워크에 동시에 참여할 수 있으므로 NID도 네트워크마다 하나씩 여러 개를 가질 수 있습니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-02-lnet-o2ib.svg" alt="LNet NID와 o2ib — NID 해부(IP 주소@네트워크 타입), lnetctl 설정 명령, LNet 메시지가 ko2iblnd를 거쳐 RC QP·MR로 운반되는 흐름" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - NID의 해부와 타입 문자열이 LND를 선택하는 관계, 그리고 ko2iblnd까지의 흐름</figcaption>
</figure>

### lnetctl로 o2ib 등록하기

NID는 저절로 생기지 않습니다. IPoIB 인터페이스에 IP를 부여하고, LNet에 네트워크를 등록하고, 그 상태를 재부팅에도 남도록 저장해야 합니다.

```bash
ip addr add 172.16.44.41/24 dev ib0   # 노드별 IB IP
lnetctl net add --net o2ib --if ib0   # 이 버전은 --interface가 아니라 --if
lnetctl export > /etc/lnet.conf       # 재부팅 대비 저장
```

결과적으로 세 노드에 `172.16.44.40/41/42@o2ib`의 NID가 생기고 export 결과는 `/etc/lnet.conf`에 저장돼 재부팅 시 자동 복원됩니다. 사소하지만 실제로 걸렸던 함정이 이 버전의 lnetctl은 `--interface`가 아니라 `--if`를 쓴다는 점입니다.

### ko2iblnd — 5편의 QP·MR가 일하는 곳

`o2ib`를 고르는 순간 LNet 메시지는 ko2iblnd에 전달됩니다. ko2iblnd는 RC(Reliable Connection) QP를 만들고 메모리를 MR로 등록해, Lustre의 RPC 페이로드를 RDMA로 직접 운반합니다.

[5편](/2026/09/27/RDMA-Study-05-Verbs-Programming/)에서 QP 상태 머신과 MR 등록을 배울 때 다룬 그 기본 요소들이 커널 안에서 스토리지 트래픽을 실어 나르는 계층이 바로 이것입니다. [6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)의 cuObject가 사용자 공간에서 RC QP를 직접 다뤘다면, ko2iblnd는 같은 원리를 커널 파일시스템 밑단에 심어 둔 셈입니다.

실측 교훈 하나를 덧붙입니다. 각 노드에는 mlx5_0·mlx5_1 두 포트가 있지만 LNet에는 mlx5_0(ib0)만 등록 가능했고, ib1은 "couldn't query intf"로 거부됐습니다(원인 미규명). 포트가 보인다고 전부 쓸 수 있다고 가정하면 안 됩니다.

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch07-q06.svg" alt="스터디 Q&A 카드 — LNet 등록 거부 couldn't query intf는 무슨 뜻인가요? 등록 전 인터페이스 조회 단계의 실패와 원인 후보, 규명 사다리" />
</figure>

## 3. 클라이언트 마운트와 함정

LNet이 살아 있으면 클라이언트 마운트는 한 줄입니다.

```bash
mount -t lustre -o user_xattr 172.16.44.41@o2ib:/lmcfs /mnt/lustre
```

그런데 초기 시험 클러스터에서 이 한 줄은 곧바로 되지 않았습니다. ZFS 풀과 fstab 정의, `/etc/lnet.conf`는 존재했지만 서비스는 전부 내려가 있었고 주소 체계가 바뀐 역사가 설정 곳곳에 새겨져 있었습니다. 마운트가 실패할 때 의심하게 되는 "네트워크 문제"가 아니라 과거의 주소가 설정 로그와 ZFS 속성에 남아 있었던 것이 진짜 원인이었습니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-03-mount-traps.svg" alt="클라이언트 마운트와 두 개의 함정 — 마운트 명령이 세 타깃을 가리키고, 함정 1 OST ZFS 속성과 함정 2 MDT 설정 로그의 옛 NID, 각각의 수정 절차" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - 마운트가 찾아가는 세 타깃과 두 개의 함정, 그리고 수정 경로</figcaption>
</figure>

### 함정 ① — OST ZFS 속성이 옛 MGS를 지목

OST를 서버 측에서 마운트할 때 mount.lustre는 ZFS 사용자 속성 `lustre:mgsnode`를 읽어 어느 MGS에 접속할지 정합니다. 잔재 상태의 OST에는 옛 MGS 주소 `172.16.44.1`이 남아 있어서, 네트워크가 아무리 건강해도 OST는 현재의 MGS를 찾아가지 못했습니다.

함정인 이유는 writeconf로도 재생성되지 않는다는 점입니다. 설정 로그와 달리 ZFS 사용자 속성은 별도로 보존되므로 손으로 직접 고쳐야 합니다.

```bash
zfs set lustre:mgsnode=172.16.44.41@o2ib lustre-ost0/ost0
zfs set lustre:mgsnode=172.16.44.41@o2ib lustre-ost1/ost1
```

### 함정 ② — MDT 설정 로그의 옛 NID

MDT 쪽 함정은 설정 로그입니다. 재생성 전의 로그에는 과거 NID가 남아 있어 새로 붙는 클라이언트가 옛 주소를 참조하도록 안내합니다. 이쪽은 `tunefs.lustre --writeconf`로 전 타깃의 설정 로그를 재생성해 해결합니다.

옛 클라이언트의 복귀를 기다리는 MDT가 WAITING_FOR_CLIENTS 리커버리에 머물러 있으면 그 사이 모든 새 마운트가 hang됩니다. 전체 수정 절차는 이렇게 정리됩니다.

```bash
zfs set lustre:mgsnode=172.16.44.41@o2ib lustre-ost0/ost0  # 1) 속성 수정
tunefs.lustre --writeconf lustre-mdt0/mdt0                 # 2) 설정 로그 재생성
mount -t lustre lustre-mdt0/mdt0 /mnt/mdt0                 # 3) MDT(MGS) 먼저
mount -t lustre lustre-ost0/ost0 /mnt/ost0                 #    그다음 OST
lctl --device lmcfs-MDT0000 abort_recovery                 # 4) 리커버리 강제 종료
```

### user_xattr — remount로는 안 되는 필수 옵션

마운트 옵션의 `-o user_xattr`은 취향이 아니라 요구사항입니다. Lustre 클라이언트 마운트의 기본값은 nouser_xattr인데, versitygw는 기동 시 xattr 검사를 수행해 이 기본값 위에서는 죽어 버립니다. 문제는 remount로는 이 옵션이 반영되지 않는다는 것 — 완전히 umount한 뒤 다시 마운트해야 합니다.

"마운트는 되는데 게이트웨이가 죽는" 증상을 만나면 제일 먼저 확인할 지점입니다. 검증 보고서 §3의 결론도 같습니다. 마운트 실패의 진짜 원인은 네트워크가 아니라 Lustre 설정 로그와 ZFS 속성에 새겨진 과거의 주소였고, writeconf와 속성 수정 둘 다 손봐야 했습니다.

## 4. versitygw 게이트웨이

Lustre 마운트까지 끝났으니 남은 질문은 "S3를 어떻게 앞세우는가"입니다. 답은 versitygw — POSIX 파일시스템 앞에 S3 API를 얹는 오픈소스 게이트웨입니다. 검증에 쓴 것은 내부 fork(1.6.0)를 OSS 업스트림 v1.8.0 기준으로 동기화한 빌드로, 이 버전대에 처음으로 RDMA 데이터플레인(vgwrdma)이 들어왔습니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-04-versitygw.svg" alt="versitygw 구조 — S3 클라이언트가 HTTP SigV4로 게이트웨이를 호출하고 버킷 ACL 관리, posix 변환을 거쳐 백엔드로 내려가는 흐름과 빌드·배포 경로" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - versitygw: S3 API와 POSIX 스토리지를 잇는 게이트웨이와 빌드·배포 경로</figcaption>
</figure>

### 구조 — 객체는 파일, 메타데이터는 xattr

versitygw의 posix 백엔드는 S3의 개념을 파일시스템에 그대로 내립니다. 객체 = 파일, 버킷 = 디렉터리, 메타데이터 = xattr. 게이트웨이 루트(gwroot)가 3절에서 고생해 마운트한 lmcfs 클라이언트(`/mnt/lustre`)를 가리키므로 S3 PUT 한 번이 결국 Lustre 위의 파일 생성으로 끝납니다.

여기서 3절의 user_xattr 이야기가 회수됩니다. 메타데이터를 xattr에 저장하는 이상 게이트웨이는 기동 시 xattr 검사를 수행하고, nouser_xattr 기본값으로 마운트된 클라이언트 위에서는 그 검사에서 죽습니다. "마운트는 되는데 게이트웨이가 죽는" 증상의 원인이 게이트웨이 안에 있었던 셈입니다.

### 빌드와 배포 — HTTP 전 경로 실측

빌드는 GitLab CI(내부 저장소)가 맡습니다. Rocky8 컨테이너에서 `make build`(CGO=0 스태틱) 후 rpmbuild로 versitygw-1.6.0 RPM을 짜고, 배포는 node-b가 담당했습니다. HTTP 게이트웨이는 :7070, RDMA 데이터플레인은 vgwrdma가 :7071에서 기동합니다.

초기 시험의 HTTP S3 전 경로 성능은 다음과 같습니다(객체 checksum 전 구간 OK).

| 객체 | PUT | GET |
|------|-----|-----|
| 64 MiB ×1 | 0.178 GB/s | 2.000 GB/s |
| 256 MiB ×10 | 0.185 GB/s (avg 1.45s) | 2.321 GB/s (avg 116ms) |

해석은 이렇습니다. PUT의 상한은 Lustre 쓰기 경로(~0.27 GB/s와 동급)이고, GET 수치는 게이트웨이가 node-b의 로컬(루프백) 마운트를 경유하는 구조와 1MiB 스트라이프의 영향입니다.

### 버전 핀 — v1.8.0은 libcuobjserver 1.x API 전용

검증이 게이트웨이에 NVIDIA 서버 라이브러리를 얹으며 발견한 첫 번째 정합 규칙입니다. v1.8.0의 cuObject 결합은 libcuobjserver 1.x(1.2.0.68) API 전용이라, 2.0.0.109를 향해 빌드하면 `setTelemFlags(unsigned)`가 `(unsigned, unsigned)`로 바뀌고 `initRDMAConfigParams`가 사라져 컴파일이 실패합니다.

2.x를 쓰려면 래퍼 2곳에 조건부 패치 17줄이 필요한데 upstream main에는 같은 취지의 커밋(ee25c95)이 이미 들어와 있습니다. 메이저 전환으로 라이브러리를 바꿔 다시 빌드할 때는 `rm -f rdma/libcuobjwrapper.a`부터 — 스테일 아카이브가 남으면 2.x 심볼을 1.x 라이브러리에 링크해 빌드가 실패합니다.

### 검증 환경의 배포 — 바이너리 2개, 패키지 설치 0건

초기 게이트웨이는 RPM과 systemd로 올렸지만 검증 환경(stg-node1/2)의 제약은 더 빡빡했습니다. 제품 요건상 이 노드에는 바이너리만 배포할 수 있고 패키지 설치·커널 변경은 금지입니다.

"게이트웨이는 el9 필요"라는 통설도 이 검증에서 깨졌습니다. NVIDIA가 rhel8용 libcuobjserver를 만들지 않을 뿐(rhel9에만 1.2.0.68·2.0.0.109), `.so`가 요구하는 심볼은 최대 GLIBC_2.16·GLIBCXX_3.4.21이라 el8(glibc 2.28)로 충분합니다. rhel9 rpm에서 `.so`를 추출해 el8 네이티브로 그대로 구동했더니 inbox verbs에서 DC QP 생성과 INIT→RTR→RTS 전이가 전부 통과했습니다. MOFED도 컨테이너도 필요 없습니다.

빌드는 클라이언트 노드(gpu-1, el9)에서 rockylinux:8 컨테이너로 돌려 el8 호환 바이너리를 만들었습니다(v1.8은 go ≥ 1.25 요구). 배포물은 결국 두 파일 — vgwrdma 바이너리와 libcuobjserver.so.1.2.0(심링크 .so.1)이며 게이트웨이 기동은 다음 한 줄입니다.

```bash
VGW_RDMA_IP=100.64.33.243 VGW_RDMA_PORT=19100 \
  CUFILE_ENV_PATH_JSON=<cufile.json 경로> \
  vgwrdma --port 0.0.0.0:7071 posix <Lustre 백엔드 경로>
```

같은 노드에서 데이터플레인별로 포트를 나눠 띄운 포트 맵이 검증의 운영 형태입니다.

| 포트 | 데이터플레인 |
|------|--------------|
| `:7070` | HTTP(S3) — 평문 제어·전송 (CGO_ENABLED=0 정적 빌드) |
| `:7071` | cuObject(DC) — libcuobjserver 1.2.0.68, 버전 핀의 실천 |
| `:7072` | cuObject(DC) — libcuobjserver 2.0.0.109, A/B·상호운용 확인용 |
| `:7075` | RC — upstream main + 검증 패치, `--rc-device mlx5_0` |

백엔드는 1~3절의 lmcfs가 아니라 검증 클러스터 Lustre `/vol0`입니다(Lustre 2.15.8 + ZFS, OST 1개, stripe 1). 게이트웨이 루트는 호스트별로 잡았고 S3 객체는 Lustre 실파일(`lfs getstripe` raid0)로 떨어집니다. 이 파일시스템은 user_xattr이 켜져 있어 게이트웨이가 그대로 살아 있습니다.

## 5. S3-over-RDMA 전체 경로

이 그림이 시리즈의 총종합입니다. [5편](/2026/09/27/RDMA-Study-05-Verbs-Programming/)의 QP 상태 머신과 MR, [6편](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)의 cuObject 토큰과 세션 수립이 한 장에 모입니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-05-s3-rdma-path.svg" alt="S3-over-RDMA 전체 경로 — S3 클라이언트에서 회색 제어 경로 HTTP SigV4와 청록 데이터 경로 RDMA RC QP가 게이트웨이로 내려가고, 초록 Lustre 경로 o2ib로 메타데이터와 데이터 타깃으로 흐른다" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 5 - 제어는 HTTP, 데이터는 RDMA — 모든 경로는 결국 같은 IB 패브릭 위를 지나간다</figcaption>
</figure>

### 4단계 여정

검증 보고서의 목표는 네 단계로 선언됐고 앞의 세 단계가 1~4절이었습니다.

| 단계 | 내용 | 이 글의 대응 |
|------|------|--------------|
| ① v1.8.0 동기화 | 내부 fork를 OSS v1.8.0 기준으로 리베이스 — RDMA 데이터플레인 첫 유입 | 4절 (빌드) |
| ② 클러스터 배포 | lmcfs 구축·복구 후 새 빌드 배포 | 1~4절 |
| ③ HTTP S3 검증 | 전 경로 PUT/GET·checksum 확인 | 4절 (실측 표) |
| ④ S3-over-RDMA | 2026-09-22 달성 — 테스트 클라이언트 직접 구현으로 PUT/GET 성공 | 5~6절, 6편 |

### 제어는 HTTP, 데이터는 RDMA

cuObject의 설계 원칙이 그림 5의 두 색입니다. S3 제어 경로는 HTTP(SigV4 서명)를 그대로 유지합니다 — 버킷 생성도 prepare/ready 라우트 호출도 모두 평범한 HTTP입니다. PUT/GET의 본문만 RC QP로 직접 씁니다. 정확히 2왕복(세션 수립→전송)의 프로토콜은 6편에서 이미 해부했습니다.

클라이언트의 이중 구조도 기억할 만합니다. RDMA/verbs 조작은 C(표준 verbs만), SigV4·HTTP·흐름 제어는 Go — 이 분리가 "표준 verbs만 쓴다 = ConnectX-4에서도 돌아간다"는 6절 결론을 가능하게 한 설계입니다.

| 경로 단계 | 하는 일 | 다룬 곳 |
|-----------|---------|---------|
| S3 클라이언트(node-a) | RC QP 생성·INIT, MR 등록, 토큰 발급 · PUT = WRITE_WITH_IMM / GET = zero-SGE recv | 5·6편 |
| vgwrdma 게이트웨이(node-b) | 토큰 디코딩, staging MR, 서버측 QP 완성 · posix 백엔드로 객체 기록 | 6편, 4절 |
| LNet / o2ib | 게이트웨이 노드의 Lustre RPC를 ko2iblnd(RC RDMA)로 운반 | 1~2절 |
| MDT · OST | 메타데이터와 데이터 스트라이프의 최종 착지 | 1절 |

실측은 이렇습니다. 1MiB 크로스노드 PUT·GET 모두 200 — etag·내용 해시 완전 일치, 백엔드 파일의 md5 == etag. 2~46MiB 스윕에서 다수 성공. 9월 22일, ConnectX-4 + IB 위에서 S3-over-RDMA가 처음으로 완성된 순간입니다.

### 검증 환경의 경로 — CX6 네이티브 IB와 /vol0

검증은 같은 층계를 다른 하드웨어 위에 세웠습니다. 클라이언트는 gpu-1 — RTX A6000(BAR1 256 MiB)에 ConnectX-6(mlx5_0, 200G HDR)이고, 게이트웨이는 stg-node1/2 — Rocky 8.10에 CX6 inbox OFED인 채로 4절의 바이너리 2개가 뜹니다. 데이터플레인은 RC 한 갈래에서 두 갈래로 늘어 cuObject(DC)와 RC가 같은 vgwrdma에서 동시에 기동합니다.

| 구분 | 초기 시험 (node-a/b/c) | 검증 (gpu-1·stg-node1/2) |
|------|------------------------|---------------------------|
| S3 클라이언트 | node-a — A2 GPU 테스트 클라 | gpu-1 — RTX A6000 · libcuobjclient 1.2(GPU-direct) / RC 클라 |
| 게이트웨이 | node-b — v1.8.0 동기화 빌드(RPM·systemd) | stg-node1/2 — v1.8.0 + libcuobjserver (양쪽 :7071, node1은 :7072/:7075 추가) |
| 데이터플레인 | RC (표준 verbs) | cuObject(DC) + RC — 같은 vgwrdma 동시 기동 |
| 백엔드 | lmcfs (/mnt/lustre, OST 2) | /vol0 (Lustre 2.15.8, OST 1 · stripe 1) |
| GID 환경 | 다중 GID — 자동선택 함정(6편) | 유효 GID idx0 하나뿐 — 구조적으로 함정 불가 |

네이티브 IB라서 유효 GID가 idx0(fe80::) 하나뿐이라는 점이 이 환경의 지문입니다. RoCE 전제의 다중 GID 자동선택 오류가 구조적으로 일어날 수 없고 cuFile은 네이티브 IB GID를 스스로 처리합니다. 대신 HTTP가 IPoIB(netdev MTU 1500)를 타야 하므로 이 환경에서는 RDMA가 PUT·GET 모두 HTTP 대비 우위입니다.

GPU-direct 경로의 상한은 클라이언트 GPU의 BAR1입니다. RTX A6000은 192 MiB까지 OK, 224 MiB부터 실패 — 그리고 초기 시험의 미해결이었던 대형 전송 실패(47.5MiB LOC_LEN_ERR)는 CX6 네이티브에서 재현되지 않아(47·64·128·256 MiB 전부 통과) CX4 VF(SR-IOV) 한정으로 좁혀졌습니다.

## 6. 생태계 비교 — 데이터플레인

마지막으로 시야를 넓힙니다. RDMA 위에 S3를 얹는 길은 검증 보고서(§8~§10)에 따라 두 생태계로 분담됩니다 — NVIDIA 진영의 cuObject(DC)와 표준 RC verbs 기반의 cuObject(RC). 우열의 문제가 아니라 각 경로가 누구를 위한 문인지 분명히 하는 것이 이 절의 목적입니다.

<figure>
<img src="/assets/images/posts/rdma-study/ch07-07-two-paths.svg" alt="S3-over-RDMA의 두 경로 — cuObject DC 카드와 RC 카드의 출처, 정본 클라이언트, 소비자, NIC 요건과 두 데이터플레인의 양립 구조" />
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 6 - 같은 게이트웨이, 다른 생태계 — RC는 cuObject의 대체가 아니라 커버리지 확장</figcaption>
</figure>

### cuObject(DC) — NVIDIA 생태계의 정문

출처는 NVIDIA 폐쇄 라이브러리(CUDA Toolkit ≥ 13.1.1)입니다. 정본 클라이언트는 libcuobjclient — 검증이 GPU HBM 직송 PUT/GET으로 실증한 바로 그 경로입니다. 소비자도 실재합니다. NIXL의 OBJ accelerated engine(Dell/NVIDIA 머지), `elbencho --cuobj`, LMCache→NIXL로 이어지는 KV 캐시 오프로드가 전부 cuObject 계열이고 NIXL #2241("generic S3-over-RDMA", 아직 open)도 cuObject 기반입니다.

클라이언트 NIC은 ConnectX 계열(DC transport는 Mellanox 전용)에 peermem/dma-buf가 필요합니다. 반대로 게이트웨이 쪽 요건은 libcuobjserver 하나 — 본 검증에서 MOFED 없이 el8 inbox verbs로 구동했습니다. 서버 배포는 가볍고 관문은 고객 GPU 노드 쪽에 있습니다.

### cuObject(RC) — 커버리지 확장의 두 번째 길

출처는 AMD의 cuObject 전송 API(github.com/ROCm/cuObject, 2026-08-22 early access)로, `x-amz-rdma-token` 체계에서 cuObject 서버와 와이어 호환을 주장합니다. 초기 시험이 클라이언트로 연 문(6편)이 이 계열의 서버 포팅이었습니다.

클라이언트는 표준 RC verbs면 충분합니다. ConnectX-4·타사 NIC 포함 — 초기 시험이 증명한 강점이고, 게이트웨이 쪽도 표준 verbs만 요구합니다.

| 항목 | cuObject (DC) | cuObject (RC) |
|------|---------------|----------------|
| 출처 | NVIDIA 폐쇄 라이브러리 (CUDA ≥ 13.1.1) | AMD cuObject 전송 API (2026-08-22 early access) — 와이어 호환 주장 |
| 정본 클라이언트 | libcuobjclient | ROCm/cuObject (PR 진행 중) |
| 실제 소비자 | NIXL OBJ 엔진 · elbencho --cuobj · LMCache→NIXL (+ NIXL #2241) | AMD/ROCm 워크로드, 비-ConnectX NIC |
| 클라 NIC 요건 | ConnectX 계열 + peermem/dma-buf | 표준 RC verbs면 충분 |

### "닫혀 있던 문"의 재해석

초기 시험은 cuObject를 먼저 시도했고 계층 진단의 기록은 이랬습니다.

| 계층 | 결과 |
|------|------|
| Layer 1 — IB 링크 | ACTIVE (mlx5_0, MTU 4096) 통과 |
| Layer 2 — IPoIB ping | 정상 통과 |
| Layer 3 — Lustre o2ib 클라이언트 IO | 정상 통과 |
| Layer 4 — raw RC RDMA | 91 Gb/s 통과 |
| Layer 5 — NVIDIA cuObject (DC) | 세션 rc=-1 실패 (당시 환경) |

IB 스택과 하드웨어는 완전히 건강했습니다. Layer 4에서 91 Gb/s가 나오는 패브릭이니까요. 막힌 것은 DC transport(DCT)를 요구하는 라이브러리 계층이었고, 당시의 결론 "다른 데이터플레인을 찾아라"가 RC 접근으로 이어졌습니다. 검증이 밝힌 것은 그 문이 IB 전체가 아니라 NIC(VF/세대)에 있었다는 점입니다. 같은 cuObject가 CX6 네이티브 IB에서 GPU HBM 직송까지 실증됐습니다. "cuObject는 IB에서 불가"는 "CX4 VF 환경 한정"으로 갱신된 것입니다.

### RC는 cuObject를 대체하지 않는다

두 경로가 같은 게이트웨이에서 돈다고 교환이 되는 것은 아닙니다. NVIDIA 진영에서 RC가 cuObject를 대체할 수 없는 이유는 소비자가 이미 cuObject로 묶여 있기 때문입니다. vLLM·LMCache·NIXL의 KV 오프로드가 전부 cuObject 바인딩이고, cuObject가 아닌 경로를 NVIDIA GPU에서 쓰면 host-memory 전송만 가능합니다.

RC의 자리는 그래서 ① AMD/ROCm 워크로드 ② 비-ConnectX NIC·CX4 ③ CPU host-memory S3-over-RDMA입니다. 같은 vgwrdma가 두 데이터플레인을 동시에 켤 수 있어(`--rdma-ip` + `--rdma-rc-enable`) 제품 구조상 양립합니다 — "대체"가 아니라 커버리지 확장이라는 말의 실체입니다.

권고 순서도 이 논리를 따릅니다. 1단계는 cuObject 제품화 — el8 동작은 이미 검증됐으니 NVIDIA의 패키징 지원 스토리와 고객 GPU 노드 전제조건(ConnectX, peermem 또는 dma-buf, BAR1 ≥ 전송 크기)의 문서화가 남았습니다. 2단계는 RC — upstream PR 제출(초안 완료) 후 정본 클라이언트와의 상호운용 재검증, 그리고 성능·동시성·오류복구 측정이 뒤따릅니다. 지켜볼 것은 NIXL #2241입니다. 벤더 중립 전송으로 확장되면 RC가 NVIDIA 스택에서도 닿게 됩니다.

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch07-q02.svg" alt="스터디 Q&A 카드 — 보통 RDMA S3 클라이언트로 뭘 쓰나요? 범용 클라이언트는 사실상 존재하지 않고 실존 조합과 실무 선택지" />
</figure>

<figure>
<img src="/assets/images/posts/rdma-study/qa-ch07-q18.svg" alt="스터디 Q&A 카드 — 분산 풀 RDMA와 S3 RDMA는 관점이 다르지 않나요? 닫힌 내부 데이터플레인과 공개 프로토콜의 가속 옵션, 두 관점의 조합" />
</figure>

## 마무리

7편을 관통한 질문은 하나였습니다. "RDMA는 어디까지 서비스가 될 수 있는가". 답을 쌓아올린 계층을 되짚으면 이렇습니다.

패브릭 위에 QP와 MR이라는 좌표계를 세우고(4~5편), 그 좌표를 토큰으로 주고받는 세션 프로토콜을 설계했으며(6편), 마지막 편에서는 그 프로토콜이 Lustre라는 검증된 스토리지 스택과 versitygw라는 게이트웨이를 만나 하나의 S3 서비스가 됐습니다. 커널 쪽의 ko2iblnd와 사용자 공간의 cuObject가 같은 RC QP·MR 위에서 각자 도는 그림 — 두 세대 검증이 증명한 것은 결국 이 구조의 견고함입니다.

스토리지 스택의 이야기는 여기서 끝입니다. 진단 방법론(계층별 문과 삼각 측량)은 시리즈 전체에 스며 있었으므로, 별도의 정리 없이도 각 절의 실측 기록이 그 사례집이 될 것입니다.

## 시리즈 마무리

RDMA 학습 시리즈 7편이 여기서 완결됩니다. 하드웨어 한 구석에서 시작한 질문이 스토리지 서비스 전체의 설계도로 자라는 과정을 담았습니다.

1. [RDMA 학습 시리즈 (1/7): 하드웨어 — NIC·패브릭·GPU-direct](/2026/09/27/RDMA-Study-01-Hardware/)
2. [RDMA 학습 시리즈 (2/7): 패브릭 — InfiniBand 프로토콜과 서브넷](/2026/09/27/RDMA-Study-02-Fabrics/)
3. [RDMA 학습 시리즈 (3/7): 소프트웨어 스택 — MOFED·inbox·컨테이너](/2026/09/27/RDMA-Study-03-Software-Stack/)
4. [RDMA 학습 시리즈 (4/7): 핵심 개념 — QP·CQ·MR·메모리 등록](/2026/09/27/RDMA-Study-04-Core-Concepts/)
5. [RDMA 학습 시리즈 (5/7): Verbs 프로그래밍 — QP 상태 머신과 WR](/2026/09/27/RDMA-Study-05-Verbs-Programming/)
6. [RDMA 학습 시리즈 (6/7): S3 over RDMA — cuObject 프로토콜](/2026/09/27/RDMA-Study-06-S3-RDMA-cuObject/)
7. [RDMA 학습 시리즈 (7/7): 스토리지 스택 — Lustre·LNet·versitygw](/2026/09/27/RDMA-Study-07-Storage-Stacks/) (이 글)

시작은 NIC의 내부 구조였고 끝은 운영 권고였습니다. 사이의 모든 계층이 "메모리를 직접 움직인다"는 하나의 원리 위에 서 있습니다. 어디서 다시 시작하든, 이 지도가 다음 여정의 출발점이 되길 바랍니다.
