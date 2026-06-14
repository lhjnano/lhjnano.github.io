---
layout: post
title: "[AWS 4/16] VPC 네트워킹 — 서브넷부터 Transit Gateway까지"
categories: [AWS, Networking]
description: AWS VPC의 핵심 개념과 서브넷, 라우팅, 보안 그룹, NACL, 피어링, Transit Gateway, 엔드포인트, VPN/Direct Connect를 정리합니다.
keywords: [VPC, AWS, 네트워킹, 서브넷, 보안그룹, TransitGateway]
toc: true
toc_sticky: true
---

## Hook

> 클라우드에서 "네트워크"라고 하면 결국 하나의 질문으로 귀결됩니다. "누가, 어디로, 어떻게 통신할 수 있는가?" AWS VPC는 이 질문에 대한 답을 설계하는 캔버스입니다.

데이터베이스는 인터넷에 노출되면 안 됩니다. 애플리케이션 서버는 패치를 위해 아웃바운드로만 인터넷에 접근해야 합니다. 본사 데이터센터와 AWS를 전용선으로 연결해야 합니다. 수십 개의 VPC를 서로 연결해야 합니다. 이 모든 요구사항이 하나의 VPC 설계로 표현됩니다.

이 글에서는 VPC의 16가지 핵심 개념을 **기초 → 보안 → 확장** 세 영역으로 정리합니다. ASCII 다이어그램과 비교 테이블로, 면접과 실무에 모두 쓸 수 있는 참조서를 만듭니다.

---

## TL;DR

- **VPC = 격리된 가상 네트워크**: CIDR 블록으로 IP 범위를 정의하고, 서브넷으로 AZ별로 분할합니다
- **보안은 두 층**: Security Group(인스턴스, Stateful) + NACL(서브넷, Stateless)으로 심층 방어합니다
- **연결은 규모에 따라**: 2~5 VPC는 Peering, 5+ VPC는 Transit Gateway, 온프레미스는 VPN 또는 Direct Connect로 연결합니다
- **엔드포인트로 비용 절감**: S3/DynamoDB는 무료 Gateway Endpoint, 나머지는 Interface Endpoint(PrivateLink)로 인터넷을 거치지 않습니다

---

## Part 1: VPC 기초 — CIDR, 서브넷, 라우팅, NAT

### VPC 개요와 CIDR 설계

Amazon VPC(Virtual Private Cloud)는 AWS 계정 전용으로 프로비저닝되는 논리적으로 격리된 가상 네트워크입니다. 리전 단위 리소스이며, 리전 내 모든 가용 영역(AZ)에 걸쳐 서브넷을 생성할 수 있습니다.

VPC 생성 시 **CIDR 블록**을 지정해야 하며, `/16`(최대)에서 `/28`(최소)까지 가능합니다.

| CIDR | 가용 IP 수 | 용도 |
|------|-----------|------|
| /16 | 65,536 | 대규모 VPC (권장 최대) |
| /20 | 4,096 | 중간 규모 |
| /24 | 256 | 서브넷 단위 |
| /28 | 16 | 최소 서브넷 |

VPC에서는 **RFC 1918 사설 IP 대역** 사용을 권장합니다.

| 사설 IP 대역 | CIDR | 가용 IP 수 | 비고 |
|-------------|------|-----------|------|
| 10.0.0.0 ~ 10.255.255.255 | 10.0.0.0/8 | 16,777,216 | 대기업 권장 |
| 172.16.0.0 ~ 172.31.255.255 | 172.16.0.0/12 | 1,048,576 | 기본 VPC 사용 |
| 192.168.0.0 ~ 192.168.255.255 | 192.168.0.0/16 | 65,536 | 온프레미스와 겹침 주의 |

> VPC CIDR은 온프레미스 네트워크, 다른 VPC와 **절대 겹쳐서는 안 됩니다**. 향후 Peering이나 VPN 연결 시 충돌이 발생하며, 생성 후 변경이 제한적이므로 초기 설계가 결정적입니다.

### 서브넷: Public vs Private

서브넷은 VPC 내에서 더 작은 네트워크 세그먼트입니다. **하나의 서브넷은 하나의 AZ에만 속하며**, 고가용성을 위해서는 최소 2개 이상의 AZ에 분산 배치해야 합니다.

| 구분 | Public Subnet | Private Subnet |
|------|--------------|----------------|
| 인터넷 접근 | IGW 통해 직접 가능 | 불가 (NAT 필요) |
| 공인 IP | 할당 가능 | 할당 불가 |
| 라우팅 | 0.0.0.0/0 → IGW | 0.0.0.0/0 → NAT GW |
| 용도 | 웹 서버, ALB, Bastion | App 서버, DB, 내부 서비스 |
| 보안 | 상대적 노출 | 격리, 높은 보안 |

각 서브넷에는 **5개의 예약 IP**가 있습니다. `10.0.0.0/24`의 경우:

| IP 주소 | 용도 | 설명 |
|---------|------|------|
| 10.0.0.0 | Network ID | 네트워크 주소 |
| 10.0.0.1 | VPC Router | AWS 예약 |
| 10.0.0.2 | DNS Server | AWS 예약 (VPC CIDR+2) |
| 10.0.0.3 | Reserved | AWS 예약 (향후 사용) |
| 10.0.0.255 | Broadcast | 브로드캐스트 (AWS 미지원) |

> `/24` 서브넷은 256개 중 5개 예약으로 **251개** IP 사용 가능, `/28`은 16개 중 5개 예약으로 **11개**만 사용 가능합니다. 서브넷 설계 시 반드시 고려합니다.

### ENI (Elastic Network Interface)

ENI는 VPC 내 가상 네트워크 인터페이스입니다. EC2 인스턴스가 VPC와 통신하려면 반드시 ENI가 필요합니다. 구성 요소는 사설 IPv4(필수), 공인 IPv4(선택), 탄력적 IP(선택), MAC 주소, 보안 그룹(최대 5개)입니다.

하나의 인스턴스에 여러 ENI를 연결할 수 있어, 방화벽 어플라이언스, 관리/데이터 네트워크 분리(Dual-Homed), 빠른 장애 조치(Failover)에 활용합니다. ENI를 다른 인스턴스로 이동하면 탄력적 IP도 함께 이동합니다.

### 라우팅 테이블

라우팅 테이블은 트래픽이 어디로 전달될지 결정하는 규칙 집합입니다. **가장 구체적인 경로가 우선**합니다. `0.0.0.0/0`보다 `10.0.1.0/24`가 더 구체적이므로 먼저 적용됩니다.

| 대상 | 타겟 | 설명 |
|------|------|------|
| 10.0.0.0/16 | local | VPC 내부 (자동 생성, 수정 불가) |
| 0.0.0.0/0 | igw-xxx | 인터넷 (Public Subnet) |
| 0.0.0.0/0 | nat-xxx | NAT Gateway (Private Subnet) |
| 172.16.0.0/16 | pcx-xxx | VPC Peering |
| 10.0.0.0/8 | vgw-xxx | VPN Gateway → 온프레미스 |

핵심 규칙: 하나의 서브넷은 하나의 라우팅 테이블에만 연결되지만, 하나의 라우팅 테이블은 여러 서브넷에 연결될 수 있습니다. 명시적으로 연결하지 않은 서브넷은 Main Route Table을 사용합니다.

### 인터넷 게이트웨이(IGW)와 NAT Gateway

**IGW**는 VPC와 인터넷 간의 출입문입니다. 수평 확장, 중복 고가용성 컴포넌트이며, VPC와 1:1로 연결됩니다. IGW는 사설 IP ↔ 공인 IP NAT 변환을 수행합니다.

인스턴스가 인터넷에 접근하려면 4가지 조건이 모두 충족되어야 합니다:

```
[인터넷 접근 4대 조건]
  1. VPC에 IGW 연결
  2. 라우팅 테이블에 0.0.0.0/0 → igw-xxx 경로
  3. 인스턴스에 공인 IP 또는 탄력적 IP 할당
  4. 보안 그룹과 NACL이 트래픽 허용
```

**NAT Gateway**는 Private Subnet의 인스턴스가 아웃바운드로만 인터넷에 접근할 수 있게 하는 관리형 서비스입니다. 최대 45Gbps까지 자동 확장되며, 탄력적 IP 연결이 필수입니다. NAT Gateway 자체에는 보안 그룹을 연결할 수 없고, NACL로 제어합니다.

| 구분 | NAT Gateway | NAT Instance |
|------|------------|--------------|
| 관리 주체 | AWS (관리형) | 사용자 (자체 관리) |
| 성능 | 최대 45Gbps 자동 확장 | 인스턴스 대역폭 제한 |
| 가용성 | AZ 내 고가용성 | 사용자가 직접 구성 |
| 보안 그룹 | 불가 | 가능 |
| Bastion 겸용 | 불가 | 가능 |
| 권장 여부 | **✅ 권장** | ❌ 비추천 (레거시) |

> 고가용성을 위해 **각 AZ마다 NAT Gateway를 배치**하고, 해당 AZ의 Private Subnet 라우팅 테이블이 같은 AZ의 NAT Gateway를 가리키도록 설계합니다. 하나의 AZ 장애에도 다른 AZ에서 인터넷 접근이 유지됩니다.

IPv6 아웃바운드 전용으로는 **Egress-only Internet Gateway**를 사용합니다. NAT 변환 없이 아웃바운드만 허용하고 인바운드는 차단합니다.

---

## Part 2: 보안 계층 — Security Groups vs NACL

### Security Group (인스턴스 수준)

보안 그룹은 EC2 인스턴스(ENI) 수준의 가상 방화벽입니다. **Stateful(상태 저장)**이므로, 인바운드로 들어온 트래픽에 대한 응답은 아웃바운드 규칙과 무관하게 자동 허용됩니다. 반대 방향도 마찬가지입니다.

| 특징 | 설명 |
|------|------|
| 상태 | **Stateful** (응답 자동 허용) |
| 규칙 유형 | **Allow만 가능** (Deny 작성 불가) |
| 평가 방식 | 모든 규칙 동시 평가, 하나라도 매치되면 허용 |
| 기본 인바운드 | 전체 거부 |
| 기본 아웃바운드 | 전체 허용 |
| 인스턴스당 | 최대 5개 SG 연결 |

다른 보안 그룹을 소스로 참조할 수 있습니다. 예를 들어 DB 보안 그룹의 인바운드 규칙을 `sg-app-xxx`에서만 3306포트 접근 허용으로 설정하면, App 보안 그룹이 적용된 인스턴스만 DB에 접근할 수 있습니다.

### Network ACL (서브넷 수준)

NACL은 **서브넷 수준**의 방화벽입니다. **Stateless(상태 비저장)**이므로, 인바운드를 허용해도 그 응답(아웃바운드)을 별도로 허용해야 합니다. 이것이 보안 그룹과의 가장 큰 차이점입니다.

| 특징 | 설명 |
|------|------|
| 상태 | **Stateless** (응답 별도 허용 필요) |
| 규칙 유형 | **Allow / Deny 모두 가능** |
| 평가 방식 | 규칙 번호 순서 (낮을수록 우선) |
| 기본 인바운드 | 전체 허용 |
| 기본 아웃바운드 | 전체 허용 |
| 서브넷당 | 1개 NACL 연결 |

### 핵심 비교

| 구분 | Security Group | Network ACL |
|------|---------------|-------------|
| 작동 수준 | 인스턴스(ENI) | 서브넷 |
| 상태 | **Stateful** | **Stateless** |
| 규칙 유형 | Allow만 | Allow + Deny |
| 규칙 평가 | 동시 평가 | 번호 순서 (우선순위) |
| 기본 인바운드 | 전체 거부 | 전체 허용 |
| 적용 방식 | 인스턴스에 직접 연결 | 서브넷에 자동 적용 |
| 연결 제한 | 인스턴스당 최대 5개 | 서브넷당 1개 |

> 실무에서는 **심층 방어(Defense in Depth)** 원칙으로 두 층을 함께 사용합니다. NACL로 서브넷 단위의 coarse 차단을, SG로 인스턴스 단위의 세밀한 제어를 수행합니다. 특정 IP 대역을 명시적으로 차단(Deny)해야 하는 경우에는 NACL만 가능합니다.

---

## Part 3: 네트워크 확장 — Peering, Transit Gateway, 엔드포인트, 하이브리드

### VPC Peering

VPC Peering은 두 VPC 간에 AWS 프라이빗 네트워크를 통해 트래픽을 직접 전송하는 연결입니다. 인터넷을 거치지 않습니다.

- **다른 리전, 다른 계정 간 가능** (Inter-Region, Cross-Account)
- **전이적 라우팅 불가**: A-B, B-C가 각각 Peering되어 있어도 A→C로 트래픽 전달 불가. 별도 A-C Peering 필요
- **CIDR 겹침 불가**: 두 VPC의 CIDR이 overlap이면 연결할 수 없음
- N개 VPC 상호 연결 시 **N×(N-1)/2** 개의 Peering 연결 필요

> Peering 수가 폭발하는 환경(5개 이상 VPC 상호 연결)에서는 Transit Gateway로 전환해야 관리 복잡도를 낮출 수 있습니다.

### Transit Gateway

Transit Gateway는 다수의 VPC와 온프레미스 네트워크를 **중앙 허브(Hub)**를 통해 연결합니다. Peering의 전이적 라우팅 제한을 해결하며, N개의 연결만으로 모든 VPC를 상호 연결합니다.

| 구분 | VPC Peering | Transit Gateway |
|------|------------|-----------------|
| 연결 방식 | 1:1 (VPC 간 직접) | Hub-and-Spoke (중앙 허브) |
| 전이적 라우팅 | 불가 | **가능** |
| 확장성 | N×(N-1)/2 연결 | N개 연결 |
| 관리 복잡도 | 높음 (연결 수 증가 시) | 낮음 (중앙 관리) |
| VPN/Direct Connect 연동 | 불가 | 가능 |
| 적합한 규모 | 소규모 (2~5 VPC) | 중/대규모 (5+ VPC) |

Transit Gateway는 Direct Connect, Site-to-Site VPN 연동과 **멀티캐스트** 지원(비디오 스트리밍, 주식 시세 분배)을 제공합니다. Network Manager 대시보드로 글로벌 네트워크 토폴로지와 트래픽 흐름을 시각화할 수 있습니다.

### VPC Endpoint

VPC Endpoint를 사용하면 **퍼블릭 IP, NAT Gateway, 인터넷 게이트웨이 없이** AWS 서비스에 비공개로 연결합니다. 트래픽이 인터넷을 거치지 않으므로 보안과 성능이 향상됩니다.

| 구분 | Interface Endpoint | Gateway Endpoint |
|------|-------------------|-----------------|
| 기술 | PrivateLink (ENI) | 라우팅 테이블 |
| 지원 서비스 | 다수 (SQS, SNS, KMS, CloudWatch...) | **S3, DynamoDB만** |
| 사설 IP | ENI에 할당됨 | 생성되지 않음 |
| 보안 그룹 | 가능 | 불가 (Endpoint Policy로 제어) |
| 비용 | 시간당 + 데이터 요금 | **무료** |
| 온프레미스 접근 | 가능 (PrivateLink) | 불가 |

> S3와 DynamoDB는 **무료 Gateway Endpoint**를 사용해 NAT Gateway 데이터 처리 비용을 절감하고 보안을 강화합니다. 나머지 AWS 서비스는 Interface Endpoint(PrivateLink)로 연결합니다. 2026년에는 VPC Endpoint Policy로 특정 버킷만 접근, 조건부 접근 등 세분화된 제어가 가능합니다.

### Site-to-Site VPN vs Direct Connect

온프레미스와 AWS를 연결하는 두 가지 방법입니다.

| 구분 | Direct Connect | Site-to-Site VPN |
|------|---------------|-----------------|
| 연결 방식 | 전용선 (사설 네트워크) | 인터넷 기반 IPSec 터널 |
| 설정 시간 | 수주 (물리적 회선 설치) | 수분 (논리적 설정) |
| 성능 | 일관된 고성능, 저지연 | 인터넷 품질에 따라 변동 |
| 대역폭 | 1/10/100 Gbps | 터널당 ~1.25 Gbps |
| 비용 | 높음 (초기 설정 + 월정액) | 낮음 (연결 시간당) |
| 적합한 경우 | 대규모, 프로덕션, 일관된 성능 | 소규모, 빠른 설정, 임시 연결 |

VPN의 구성 요소는 **Customer Gateway**(온프레미스 라우터), **Virtual Private Gateway**(VPC 측 종단점)이며, Transit Gateway를 VPN 종단점으로 사용할 수도 있습니다. 기본적으로 **2개의 IPSec 터널**로 고가용성을 제공하고, 정적/동적(BGP) 라우팅을 선택합니다.

Direct Connect는 **Direct Connect Gateway**를 통해 하나의 전용선으로 여러 리전의 VPC에 접근할 수 있습니다.

### VPC Flow Logs

Flow Logs는 ENI의 송수신 트래픽 메타데이터를 캡처합니다. VPC / 서브넷 / ENI 세 가지 레벨에서 활성화할 수 있으며, CloudWatch Logs(실시간 모니터링), S3(Athena SQL 분석, 장기 보관), Kinesis Data Firehose(실시간 스트리밍)로 전송합니다.

| 주요 필드 | 설명 |
|----------|------|
| srcaddr / dstaddr | 소스/목적지 IP 주소 |
| srcport / dstport | 소스/목적지 포트 |
| protocol | 프로토콜 번호 (6=TCP, 17=UDP) |
| action | ACCEPT 또는 REJECT |
| packets / bytes | 전송된 패킷 수 / 바이트 수 |
| start / end | 캡처 윈도우 시작/종료 시간 |

> Flow Logs는 **페이로드(내용)를 캡처하지 않으며**, 실시간이 아닙니다 (수분 지연). DHCP, DNS, 인스턴스 메타데이터 트래픽은 기록되지 않습니다.

### 아키텍처 패턴

**퍼블릭/프라이빗 서브넷 패턴** — 가장 기본적인 구조입니다.

```
[인터넷] ←→ [Internet Gateway]
                  |
            [VPC: 10.0.0.0/16]
                  |
    ┌─────────────┼─────────────┐
    |             |             |
 [AZ-a]        [AZ-b]        [AZ-c]
    |             |             |
 [Public]     [Public]      [Public]  ← ALB, NAT GW, Bastion
    |             |             |
 [Private]    [Private]     [Private] ← App Server, DB
```

Public Subnet에는 ALB, NAT Gateway, Bastion Host를 배치하고, Private Subnet에는 애플리케이션 서버와 데이터베이스를 배치합니다.

**3계층 아키텍처 (Web-App-DB)** — 엔터프라이즈 표준 구조입니다.

| 계층 | 서브넷 유형 | 배치 리소스 | 보안 그룹 |
|------|-----------|------------|----------|
| Web | Public | ALB, EC2 (웹 서버) | 80/443 인바운드 허용 |
| App | Private | EC2/ECS (앱 서버) | Web 계층에서만 접근 허용 |
| DB | Private (격리) | RDS, ElastiCache | App 계층에서만 접근 허용 |

```
[인터넷] → [IGW] → [ALB (Public)]
                        |
                   [Web Server (Public)]
                        |
                   [App Server (Private)]  ← NAT GW로 아웃바운드
                        |
                   [RDS DB (Private/격리)]
```

**VPC 설계 모범 사례:**

1. **CIDR 계획**: 향후 확장을 고려해 `/16` 권장, 온프레미스/다른 VPC와 겹치지 않게 설계
2. **다중 AZ**: 최소 2개, 권장 3개 AZ에 서브넷 분산 배치
3. **심층 방어**: NACL(서브넷) + SG(인스턴스) 동시 사용
4. **최소 권한**: 0.0.0.0/0 전체 허용을 피하고 필요한 최소 트래픽만 허용
5. **NAT Gateway 다중 배치**: 각 AZ마다 배치하여 단일 장애점(SPOF) 제거
6. **Gateway Endpoint 활용**: S3/DynamoDB는 무료 엔드포인트로 NAT 비용 절감
7. **Flow Logs 활성화**: 모든 VPC에 트래픽 모니터링 설정
8. **환경 분리**: 개발/스테이징/프로덕션을 별도 VPC로 분리

---

## Takeaway

1. **VPC 설계는 CIDR에서 결정됩니다** — `/16`으로 충분한 IP 공간을 확보하고 RFC 1918 사설 대역을 사용하며, 온프레미스 및 다른 VPC와 절대 겹치지 않게 초기에 설계해야 합니다. 서브넷은 AZ 단위로 분할하고 5개의 예약 IP를 감안해 크기를 산정합니다
2. **보안은 SG와 NACL 두 층으로 심층 방어합니다** — Security Group은 Stateful로 인스턴스 단위 세밀 제어를, NACL은 Stateless로 서브넷 단위 차단을 담당합니다. 특정 IP를 명시적으로 Deny해야 하거나 서브넷 전체에 일괄 규칙을 적용할 때만 NACL을 활용합니다
3. **연결 규모에 맞게 기술을 선택합니다** — 2~5개 VPC는 Peering, 5개 이상은 Transit Gateway로 중앙 허브를 구축합니다. S3/DynamoDB는 무료 Gateway Endpoint로 NAT 비용을 절감하고, 온프레미스 연결은 일관된 성능이 필요하면 Direct Connect, 빠른 설정이 필요하면 Site-to-Site VPN을 선택합니다

---

> **AWS 시리즈 4/16**
>
> | | |
> |---|---|
> | ← [S3 객체 스토리지 기초 — 버킷부터 수명주기까지]({% post_url 2026-06-14-AWS-S3-Storage-Basics %}) | |
> | | [로드밸런싱 & 오토스케일링 — ELB와 Auto Scaling Groups]({% post_url 2026-06-14-AWS-ELB-AutoScaling %}) → |
