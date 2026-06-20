---
layout: post
title: "[AWS 5/16] 로드밸런싱 & 오토스케일링 — ELB와 Auto Scaling Groups"
categories: [AWS, Networking, Compute]
description: ALB/NLB/GWLB 4가지 로드밸런서와 Auto Scaling Groups의 설정, 정책, ELB 연동까지 정리합니다.
keywords: [ELB, ALB, NLB, AutoScaling, AWS, 로드밸런서]
toc: true
toc_sticky: true
---

## Hook

> 트래픽이 3배로 늘면 서버가 죽습니다. 서버를 늘리면 새벽에 트래픽이 0이 되어 비용만 나갑니다. 이 문제를 해결하는 두 가지 서비스가 ELB와 Auto Scaling입니다.

ELB는 들어오는 트래픽을 여러 인스턴스에 분산하고, Auto Scaling은 부하에 따라 인스턴스를 자동으로 늘리거나 줄입니다. 둘을 함께 쓰면 고가용성과 비용 최적화를 동시에 잡을 수 있습니다. 이 글에서는 4가지 로드밸런서(ALB/NLB/GWLB/CLB)의 차이부터 대상 그룹, 스티키 세션, 교차 영역 로드밸런싱, 커넥션 드레이닝까지 ELB를 정리하고, 이어서 Auto Scaling Groups의 시작 템플릿, 조정 정책, 수명 주기 후크, ELB 연동까지 다룹니다.

---

## TL;DR

- **4가지 LB 선택** — 웹은 ALB, 게임/IoT는 NLB, 방화벽은 GWLB, CLB는 사용 중단
- **ALB vs NLB 핵심 차이** — ALB는 L7 경로 라우팅 + 유동 IP, NLB는 L4 초저지연 + 고정 IP + Client IP 보존
- **Launch Template이 표준** — Launch Configuration은 수정 불가 레거시, 2026년에는 무조건 Template 사용
- **조정 정책 4종** — Target Tracking(권장) / Step / Simple / Predictive, 상황에 맞게 조합
- **ELB + ASG 연동이 기본** — 대상 그룹에 자동 등록, ELB 상태 검사 기반 자동 교체, 연결 드레이닝으로 무중단

---

## Part 1. ELB (Elastic Load Balancing)

Elastic Load Balancing은 들어오는 애플리케이션 트래픽을 여러 대상(EC2, 컨테이너, IP, Lambda)에 자동으로 분산시키는 관리형 서비스입니다. 고가용성, 확장성, 내결함성을 제공하며 현대 AWS 아키텍처의 필수 컴포넌트입니다.

### 4가지 로드밸런서 비교

ELB는 OSI 모델의 여러 계층에서 작동하는 4가지 유형을 제공합니다.

| 구분 | ALB (L7) | NLB (L4) | GWLB (L3) | CLB (레거시) |
|------|----------|----------|-----------|-------------|
| **계층** | 애플리케이션 | 전송 | 네트워크 | L4/L7 혼합 |
| **프로토콜** | HTTP, HTTPS, gRPC | TCP, UDP, TLS | IP 패킷 (Geneve) | HTTP, TCP |
| **라우팅 기준** | URL, 호스트, 헤더 | IP, 포트 | 패킷 캡처 | 제한적 |
| **성능** | 고성능 | 초고성능/초저지연 | 어플라이언스 분산 | 제한적 |
| **고정 IP** | 불가 (DNS 사용) | 가능 (EIP) | — | 불가 |
| **Client IP** | X-Forwarded-For | 원본 유지 | — | 제한적 |
| **교차 영역 LB** | 항상 활성화 | 기본 비활성화 | 항상 활성화 | 기본 비활성화 |
| **주요 용도** | 웹, 마이크로서비스 | 게임, IoT, 금융 | 방화벽, IDS/IPS | ❌ 사용 중단 |

> **CLB는 2026년 Deprecated** 되었습니다. 새 아키텍처에서는 용도에 따라 ALB 또는 NLB를 사용합니다.

### ALB — Application Load Balancer (L7)

ALB는 HTTP/HTTPS 트래픽을 URL 경로, 호스트 이름, HTTP 헤더 등 요청 내용을 기반으로 지능적으로 라우팅합니다. 마이크로서비스, 컨테이너 환경에서 세분화된 트래픽 제어가 가능합니다.

**3가지 콘텐츠 기반 라우팅:**

| 라우팅 방식 | 예시 | 대상 분리 |
|------------|------|-----------|
| 경로 기반 | `/api/*` → API 그룹, `/images/*` → 이미지 그룹 | 기능별 분산 |
| 호스트 기반 | `api.example.com` → API, `admin.*` → 관리 | 도메인별 분산 |
| 헤더 기반 | `User-Agent`, `X-Mobile: true` | 디바이스/조건별 분산 |

**ALB 요청 라우팅 흐름:**

```
클라이언트 → [ALB DNS 이름]
                |
         [리스너: HTTPS:443]
                |
         [규칙 평가]
          ├── 경로: /api/*      → 대상 그룹: API-Servers
          ├── 호스트: admin.*   → 대상 그룹: Admin-Servers
          ├── 헤더: X-Mobile: true → 대상 그룹: Mobile-API
          └── 기본              → 대상 그룹: Web-Servers
```

**주의사항 — ALB IP는 유동적입니다.** 시간에 따라 변경되므로 항상 DNS 이름으로 접근해야 합니다. 클라이언트의 실제 IP는 `X-Forwarded-For` 헤더에서 확인합니다.

**2026년 기능:**
- **gRPC 지원** — HTTP/2 기반 gRPC 트래픽 로드밸런싱, 메서드/서비스 기반 라우팅
- **Lambda 타겟** — ALB 대상 그룹에 Lambda 함수 직접 등록, API Gateway 없이 서버리스 API 구축
- **ACM 통합 SSL/TLS** — SNI 지원으로 하나의 리스너에 여러 인증서 연결, 자동 갱신

### NLB — Network Load Balancer (L4)

NLB는 TCP/UDP/TLS 트래픽을 L4 수준에서 처리합니다. 초고성능(수백만 요청/초), 초저지연(마이크로초 단위 추가 지연)이 특징이며 장기 연결(WebSocket, 게임 서버)에 적합합니다.

| 특징 | 설명 |
|------|------|
| **Client IP 보존** | 백엔드에서 클라이언트 원본 IP를 직접 확인 가능 (ALB는 X-Forwarded-For 필요) |
| **고정 IP** | 각 AZ에 Elastic IP 할당 가능 — 방화벽 규칙, DNS 레코드에 유용 |
| **TLS Passthrough** | NLB가 복호화하지 않고 백엔드로 그대로 전달 — 엔드투엔드 암호화 시 사용 |
| **Proxy Protocol v2** | Client IP와 목적지 IP를 모두 전달해야 할 때 활성화 |

### GWLB — Gateway Load Balancer (L3)

GWLB는 서드파티 가상 어플라이언스(방화벽, IDS/IPS, DDoS 방어)의 배포, 확장, 관리를 간소화합니다. Geneve 프로토콜(UDP 6081)로 트래픽을 캡슐화합니다.

```
[인바운드 트래픽] → [GWLB]
                        |
                 [Geneve 캡슐화]
                        |
               [3rd Party 어플라이언스] ← 방화벽, IDS/IPS 검사
                        |
                 [Geneve 디캡슐화]
                        |
                   [원래 목적지] → 애플리케이션 서버
```

GWLB Endpoint를 사용하면 다른 VPC의 트래픽을 GWLB가 있는 VPC로 전달하여 중앙 집중식 보안 검사 아키텍처를 구현할 수 있습니다.

### 대상 그룹 (Target Group)

대상 그룹은 로드밸런서가 트래픽을 라우팅할 대상의 논리적 그룹입니다. 리스너 규칙에 의해 참조됩니다.

| 대상 유형 | 설명 | 지원 LB |
|-----------|------|---------|
| **instance** | EC2 인스턴스 ID로 지정 | ALB, NLB, GWLB |
| **ip** | IP 주소 (온프레미스, 다른 VPC 포함) | ALB, NLB, GWLB |
| **lambda** | Lambda 함수 | ALB |
| **alb** | 다른 ALB 리스너 (NLB 전용) | NLB |

**상태 검사 설정 (기본값):**

| 설정 | 기본값 | 설명 |
|------|--------|------|
| 프로토콜/경로 | HTTP `/` | 상태 검사 요청 경로 |
| Healthy 임계값 | 5회 연속 성공 | 정상 상태로 전환 |
| Unhealthy 임계값 | 2회 연속 실패 | 비정상 상태로 전환 |
| 간격 / 타임아웃 | 30초 / 5초 | 검사 주기 및 대기 시간 |

### Sticky Session (세션 선호도)

동일 클라이언트의 요청을 항상 동일한 대상으로 라우팅합니다. 세션이 서버에 로컬 저장되는 애플리케이션에서 필요합니다. 쿠키 기반으로 작동합니다.

| 쿠키 유형 | 설명 | 지원 |
|-----------|------|------|
| ALB 생성 쿠키 | ALB가 자동 생성 (`AWSALB`), 만료 시간 설정 가능 | ALB |
| 애플리케이션 쿠키 | 애플리케이션이 생성한 쿠키를 ALB가 인식 | ALB |

> ⚠️ Sticky Session은 트래픽 불균형을 유발할 수 있습니다. 가능하면 **상태 비저장(Stateless)** 아키텍처를 설계하여 ElastiCache나 DynamoDB에 세션을 저장하는 것이 권장됩니다.

### Cross-Zone Load Balancing

로드밸런서가 AZ별이 아닌 등록된 모든 대상별로 트래픽을 균등하게 분산합니다.

```
[비활성화] AZ당 균등 분산:                [활성화] 인스턴스당 균등 분산:
  AZ-a: 4개 → 각 25%                       AZ-a: 4개 → 각 16.7%
  AZ-b: 2개 → 각 50%  ← 불균형!            AZ-b: 2개 → 각 16.7%  ← 균형!
```

| 로드 밸런서 | 기본값 | 변경 | 비고 |
|------------|--------|------|------|
| ALB | 항상 활성화 | 비활성화 불가 | 무료 |
| NLB | 기본 비활성화 | 활성화 가능 | ⚠️ 활성화 시 교차 AZ 데이터 전송 비용 발생 |
| GWLB | 항상 활성화 | 비활성화 불가 | 무료 |

### Connection Draining (Deregistration Delay)

대상이 등록 취소되거나 비정상 상태가 될 때 기존 연결이 완료될 때까지 대기합니다.

1. 대상 상태가 **Draining**으로 변경
2. **새 연결**은 라우팅되지 않음
3. **기존 연결**은 설정된 시간 동안 유지 (기본 300초, 범위 0~3600초)
4. 시간 만료 또는 모든 연결 완료 시 대상 완전 제거

롤링 배포, Auto Scaling 축소, 유지보수 시 서비스 중단 없이 연결을 안전하게 종료합니다.

### ELB 아키텍처 패턴

**다중 AZ 부하분산** — 가장 기본적인 패턴입니다:

```
[인터넷] → [ALB (외부)]
               |
    ┌──────────┼──────────┐
    |          |          |
  [AZ-a]    [AZ-b]    [AZ-c]
    |          |          |
  EC2 x 2   EC2 x 2   EC2 x 2
```

**Blue/Green 배포** — ALB 가중치 기반 라우팅으로 무중단 배포:

```
[ALB 리스너 규칙]
       |
  [가중치 기반 라우팅]
       |
  ┌────┴────┐
  |         |
[Blue TG] [Green TG]
 (v1.0)    (v1.1)
  90%       10%  → 50%/50% → 0%/100% (완전 전환)
```

**Canary 배포** — 새 버전을 소수에게만 먼저 노출:

```
[ALB 리스너 규칙]
       |
  ┌────┴────────┐
  |             |
[Stable TG]  [Canary TG]
 (v1.0)       (v2.0)
  99%           1%  → 95%/5% → 100%/0%
```

**ELB 선택 가이드:**

| 시나리오 | 권장 LB | 이유 |
|----------|---------|------|
| 웹 애플리케이션 (HTTP/HTTPS) | ALB | 경로/호스트 라우팅, SSL 종료 |
| 마이크로서비스 | ALB | 콘텐츠 기반 라우팅 |
| 게임 서버, 실시간 통신 | NLB | 초저지연, TCP/UDP, 고정 IP |
| IoT 디바이스 연결 | NLB | 수백만 연결, TCP/UDP |
| 금융 거래 시스템 | NLB | 초저지연, Client IP 보존 |
| 방화벽/IDS 어플라이언스 | GWLB | 3rd Party 어플라이언스 분산 |
| 서버리스 HTTP API | ALB + Lambda | ALB에서 Lambda 직접 호출 |

---

## Part 2. Auto Scaling Groups (ASG)

EC2 Auto Scaling은 애플리케이션 부하에 따라 EC2 인스턴스를 자동으로 확장(Scale Out) 및 축소(Scale In)합니다. Auto Scaling 서비스 자체는 무료이며 EC2 요금만 부과됩니다.

### 시작 템플릿 (Launch Template)

ASG에서 인스턴스를 시작할 때 사용하는 템플릿입니다. AMI, 인스턴스 유형, 보안 그룹, 키 페어, User Data, IAM Role을 정의합니다.

| 비교 항목 | Launch Configuration | Launch Template |
|-----------|---------------------|-----------------|
| 수정 | ❌ 불가 (새로 만들어야 함) | ✅ 가능 |
| 버전 관리 | ❌ 없음 | ✅ 지원 |
| Spot 인스턴스 | 제한적 | 완전 지원 |
| 다중 유형 | ❌ 불가 | ✅ 가능 |
| 권장 | ❌ 레거시 | ✅ **2026 표준** |

> Launch Configuration은 생성 후 수정이 불가능합니다. 2026년에는 **무조건 Launch Template을 사용**합니다.

### 조정 정책 (Scaling Policies)

4가지 조정 정책이 있으며, 상황에 맞게 선택하거나 조합합니다.

**1. 대상 추적 (Target Tracking) — 가장 권장됩니다.**

CloudWatch 지표 평균값이 목표값을 유지하도록 자동 조정합니다. 설정이 가장 간단합니다.

```
ASG → CloudWatch 지표 평균값 모니터링
    예: CPU 사용률 50% 목표
    → 평균 50% 초과 시 Scale Out
    → 평균 50% 미만 시 Scale In
```

| 일반 지표 | 목표 예시 |
|-----------|----------|
| CPUUtilization | 40~60% |
| RequestCountPerTarget | 1000/분 |
| Average Network In/Out | 트래픽 패턴에 따라 |

**2. 단계 조정 (Step Scaling)** — 지표 값 범위에 따라 차등 증감:

```
CPU 60~70% → +1 인스턴스
CPU 70~80% → +2 인스턴스
CPU 80%+   → +4 인스턴스
```

**3. 단순 조정 (Simple Scaling)** — 알람 임계치 도달 시 고정 수만큼 증감:

```
CloudWatch Alarm (CPU > 80%) → +2 인스턴스
CloudWatch Alarm (CPU < 30%) → -1 인스턴스
```

> 단순 조정은 조정 후 Cooldown이 끝나야 다음 조정이 가능합니다.

**4. 예측 조정 (Predictive Scaling) — ML 기반:**

| 특징 | 설명 |
|------|------|
| 분석 기간 | 최근 14일 CloudWatch 데이터 분석 |
| 예측 주기 | 매일 다음 48시간 예측 |
| 모드 | Forecast only (관찰) / Forecast and scale (실행) |

> 💡 **대상 추적 + 예측 조정을 조합**하면 반복적 트래픽 패턴에서 최적의 결과를 얻을 수 있습니다.

| 정책 | 복잡도 | 권장 상황 |
|------|--------|----------|
| Target Tracking | 낮음 | 기본 선택, 단일 지표 기준 |
| Step Scaling | 중간 | 부하 정도별 세밀한 제어 |
| Simple Scaling | 낮음 | 레거시 (Cooldown 제약) |
| Predictive Scaling | 높음 | 반복적 트래픽 패턴 (Target Tracking과 조합) |

### 조정 휴지 (Scaling Cooldown)

조정 활동 후 추가 조정을 일시 중지하는 시간입니다. 기본값은 **300초(5분)**입니다.

- 인스턴스 시작 후 지표가 안정화될 시간 확보
- 과도한 Scale Out 방지
- 단순 조정 정책에서만 적용 (대상 추적은 내장 Cooldown 포함)

### 수명 주기 후크 (Lifecycle Hook)

인스턴스가 ASG에 추가되거나 제거될 때 사용자 정의 작업을 수행합니다.

| 후크 | 시점 | 용도 |
|------|------|------|
| **launch** | 인스턴스 시작 → In Service 전 | 소프트웨어 설치, 설정 스크립트 실행 |
| **terminate** | In Service → 종료 전 | 로그 수집, 정상 종료 처리 |

- 기본 제한 시간: **3600초 (1시간)**
- 하트비트로 시간 연장 가능
- 결과: `CONTINUE` (계속) / `ABANDON` (중단)
- 알림: EventBridge, SNS, SQS로 전송

### ELB 연동

ASG와 ELB를 연동하면 트래픽 분산과 인스턴스 건전성을 함께 관리합니다.

```
┌─────────────────────────────────────────────┐
│                   ELB (ALB)                  │
│              ┌───────┬───────┐               │
│              │Target │ Group │               │
│              └───┬───┴───┬───┘               │
└──────────────────┼───────┼───────────────────┘
                   │       │
    ┌──────────────┼───────┼──────────────┐
    │      Auto Scaling Group             │
    │  ┌────────┐ ┌────────┐ ┌────────┐  │
    │  │  EC2   │ │  EC2   │ │  EC2   │  │
    │  │  AZ-a  │ │  AZ-b  │ │  AZ-c  │  │
    │  └────────┘ └────────┘ └────────┘  │
    │      Min: 2  Desired: 3  Max: 6    │
    └─────────────────────────────────────┘
```

- **대상 그룹 자동 등록** — 새 인스턴스가 시작되면 자동으로 대상 그룹에 등록됩니다
- **ELB 상태 검사 기반 교체** — 비정상 인스턴스를 자동으로 감지하고 교체합니다
- **연결 드레이닝** — 인스턴스 종료 전 기존 요청 완료 대기 (기본 300초)

### 2026년 ASG 업데이트

| 기능 | 설명 | 효과 |
|------|------|------|
| **Warm Pools** | 미리 초기화된 인스턴스 풀 유지 (Stopped 상태) | 콜드스타트 최소화 |
| **Instance Refresh** | 런치 템플릿 변경 시 점진적 인스턴스 교체 | 롤링 업데이트, 최소 정상 비율 유지 |
| **Mixed Instances Policy** | 온디맨드 + 스팟 혼합, 다중 유형 지정 | 비용과 가용성 최적화 |
| **Capacity Rebalance** | 스팟 중단 알림 수신 시 사전 교체 | 서비스 중단 최소화 |

---

## Best Practices

**웹 계층 자동 확장 아키텍처 — CloudFront + ALB + ASG + RDS:**

```
┌──────────────────────────────────────────┐
│              CloudFront (CDN)             │
└─────────────────┬────────────────────────┘
                  │
┌─────────────────▼────────────────────────┐
│           ALB (Application LB)            │
│     ┌───────────┬───────────┐             │
│     │Target Grp │Target Grp │             │
│     └─────┬─────┴─────┬─────┘             │
└───────────┼───────────┼───────────────────┘
            │           │
┌───────────▼───────────▼───────────────────┐
│      Auto Scaling Group (Web Tier)        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐     │
│  │ EC2  │ │ EC2  │ │ EC2  │ │ EC2  │     │
│  │ AZ-a │ │ AZ-b │ │ AZ-a │ │ AZ-b │     │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘     │
└─────┼────────┼────────┼────────┼─────────┘
      │        │        │        │
┌─────▼────────▼────────▼────────▼─────────┐
│              RDS (Multi-AZ)               │
│         ┌──────────┬──────────┐           │
│         │ Primary  │ Standby  │           │
│         └──────────┴──────────┘           │
└──────────────────────────────────────────┘
```

**핵심 모범 사례 8가지:**

1. **다중 AZ 배치** — 최소 2개 AZ에 대상을 분산하여 고가용성 확보
2. **상태 검사 최적화** — 경량 엔드포인트(`/health`) 사용, 적절한 간격과 임계값 설정
3. **SSL/TLS는 ELB에서 종료** — 백엔드 부담 감소, ACM으로 인증서 자동 갱신
4. **Launch Template 버전 관리** — AMI 업데이트 시 새 버전 생성, Instance Refresh로 롤링 교체
5. **Target Tracking 기본 + Predictive 조합** — 반복 패턴 대응, 사전 스케일링
6. **Connection Draining 설정** — 배포/스케일 인 시 서비스 중단 방지 (기본 300초)
7. **보안 그룹 최소 권한** — ELB는 80/443만 인바운드, 백엔드는 ELB에서만 접근 허용
8. **CloudWatch 모니터링** — RequestCount, TargetResponseTime, HTTPCode_ELB_5XX 경보 설정

**예약 기반 스케일링 예시 — 시간대별 용량 조정:**

| 시간대 | Min / Max | 정책 |
|--------|-----------|------|
| 평일 09:00~18:00 | 4 / 10 | 예약 + 대상 추적 |
| 평일 18:00~09:00 | 2 / 4 | 예약 + 대상 추적 |
| 주말 | 1 / 3 | 예약 + 대상 추적 |

---

## Takeaway

1. **LB 선택은 프로토콜과 성능 요구사항으로 결정합니다** — 웹/HTTP는 ALB(경로 라우팅, 유동 IP), 게임/IoT/금융은 NLB(초저지연, 고정 IP, Client IP 보존), 보안 어플라이언스는 GWLB(Geneve 캡슐화)를 사용합니다. CLB는 2026년 Deprecated이므로 마이그레이션해야 합니다.
2. **Launch Template + Target Tracking이 ASG의 표준입니다** — 수정 불가능한 Launch Configuration 대신 버전 관리가 가능한 Launch Template을 사용하고, 조정 정책은 가장 간단한 Target Tracking을 기본으로 하되 반복 트래픽 패턴에는 Predictive Scaling을 조합합니다.
3. **ELB + ASG 연동으로 무중단 자동 복구를 구현합니다** — 대상 그룹에 인스턴스를 자동 등록하고 ELB 상태 검사 기반으로 비정상 인스턴스를 자동 교체하며, Connection Draining으로 배포와 스케일 인 시 기존 연결을 안전하게 완료하면 고가용성과 비용 최적화를 동시에 달성할 수 있습니다.

---

> **AWS 시리즈 5/16**
>
> | | |
> |---|---|
> | ← [VPC 네트워킹 — 서브넷부터 Transit Gateway까지]({% post_url 2026-05-25-AWS-VPC-Networking %}) | |
> | | [엣지 서비스 — CloudFront, Route 53, Global Accelerator]({% post_url 2026-05-27-AWS-Edge-Services %}) → |
