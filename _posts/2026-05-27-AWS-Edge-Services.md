---
layout: post
title: "[AWS 6/16] 엣지 서비스 — CloudFront, Route 53, Global Accelerator"
categories: [AWS, Networking, CDN]
description: AWS의 글로벌 엣지 서비스 3종을 정리합니다. CDN(CloudFront), DNS(Route 53), 글로벌 가속(Global Accelerator)의 차이와 선택 기준을 다룹니다.
keywords: [CloudFront, Route53, GlobalAccelerator, CDN, DNS, AWS]
toc: true
toc_sticky: true
---

## Hook

전 세계 사용자에게 서비스할 때 가장 먼저 부딪히는 벽은 **지연 시간**입니다. 서울 리전에 서버를 두면 런던 사용자는 왕복 250ms의 지연을 겪습니다. AWS는 이 문제를 푸는 엣지 서비스를 세 종류로 제공합니다. 콘텐츠를 캐싱하는 **CloudFront**, 도메인을 지능적으로 라우팅하는 **Route 53**, 네트워크 경로 자체를 최적화하는 **Global Accelerator**입니다.

세 서비스는 비슷해 보이지만 역할이 다릅니다. 이 글에서는 각 서비스의 핵심 메커니즘과 **언제 어떤 것을 선택해야 하는지**를 정리합니다.

---

## TL;DR

- **CloudFront** — HTTP/HTTPS 콘텐츠를 엣지에 캐싱하는 CDN. 정적 자산·API 응답 가속에 적합합니다
- **Route 53** — DNS 이름 해석 + 7가지 라우팅 정책. 장애조치·지연 기반·지리 기반 분산의 뇌 역할입니다
- **Global Accelerator** — Anycast 고정 IP 2개로 AWS 백본을 태우는 경로 최적화. 비 HTTP·실시간·고정 IP가 필요할 때 씁니다
- **선택 기준** — 캐싱이 필요하면 CloudFront, 라우팅 제어가 필요하면 Route 53, 고정 IP·게임·IoT 트래픽이면 Global Accelerator입니다

---

## 1. CloudFront — 콘텐츠 전송 네트워크(CDN)

Amazon CloudFront는 전 세계 엣지 로케이션에서 HTTP/HTTPS 콘텐츠를 캐싱하여 사용자에게 가깝게 배포하는 CDN 서비스입니다. Origin은 S3 버킷, ALB, EC2, 사용자 지정 서버 모두 가능하며, 엣지 간에는 AWS의 전용 백본 네트워크를 사용해 지연을 최소화합니다.

### 콘텐츠 제공 흐름

```
👤 Client ──요청──▶ 🌐 Edge Location ──✅ Cache Hit──▶ 👤 Client (즉시 응답)
                       │
                       │ ❌ Cache Miss
                       ▼
                   📦 Origin Server (S3 / ALB / EC2)
                       │
                       └──── 콘텐츠 캐싱 후 응답 ────▶
```

1. **Client → Edge Location** — DNS가 가장 가까운 엣지로 라우팅합니다
2. **캐시 확인** — Cache Hit면 즉시 응답합니다
3. **Origin 요청** — Cache Miss면 Origin에서 가져와 캐싱 후 응답합니다. TTL로 갱신 주기를 제어합니다

### Origin 접근 제어: OAI vs OAC

S3 버킷을 CloudFront로만 공개하려면 Origin 접근 제어가 필요합니다. **OAI**는 구형이고 **OAC**(2026 권장)는 개선형입니다.

| 기능 | OAI | OAC (권장) |
|------|-----|-----------|
| SSE-KMS 암호화 객체 접근 | ❌ | ✅ |
| 모든 HTTP Method (PUT/POST/DELETE) | 제한적 | ✅ |
| 단기 서명 자격 증명 | ❌ | ✅ (SigV4) |
| 새 Origin 추가 | 불가 | 가능 |

> 2026년에는 새 배포에 **OAC**를 사용하세요. KMS 암호화 객체와 PUT/DELETE까지 지원합니다.

### Geolocation Restriction (지리적 접근 제한)

국가 코드(ISO 3166-1-alpha-2) 기반으로 콘텐츠 접근을 제한합니다. **Allowlist**(허용 국가만)와 **Blocklist**(차단 국가) 두 모드가 있습니다. 저작권 보호·규제 준수 목적으로 활용합니다.

### Signed URL / Signed Cookies

인증된 사용자에게만 콘텐츠를 제공하는 방법입니다.

| 구분 | Signed URL | Signed Cookies |
|------|-----------|----------------|
| 적용 범위 | 개별 파일 | 여러 파일 (전체 사이트) |
| URL 변경 | 서명 포함 | URL 변경 없음 |
| 사용 사례 | 개별 다운로드, 유료 콘텐츠 | 프리미엄 영역 전체 접근 |

두 방식 모두 만료 시간을 설정할 수 있어 프리미엄 콘텐츠·유료 동영상에 적합합니다.

### Lambda@Edge vs CloudFront Functions

엣지에서 코드를 실행해 요청·응답을 동적으로 처리합니다. Lambda@Edge는 4개 트리거 포인트(Viewer/Origin Request/Response)에서 작동하고, CloudFront Functions는 Viewer 포인트에서만 경량 실행됩니다.

| 구분 | Lambda@Edge | CloudFront Functions |
|------|-------------|----------------------|
| 런타임 | Node.js, Python | JavaScript |
| 실행 시간 | 최대 30초 | 최대 1ms |
| 트리거 | 4개 포인트 | Viewer만 |
| 네트워크 접근 | 가능 | 불가 |
| 적합 용도 | 무거운 로직, 이미지 변환 | URL 리라이트, 헤더 조작, 인증 |

### 캐시 최적화

- **Cache-Control 헤더** — `max-age`(유효 시간), `s-maxage`(CDN 전용), `no-cache`(재검증), `no-store`(캐시 안 함)
- **Invalidation(무효화)** — 캐시 강제 삭제. 경로 패턴(`/images/*`, `/*`) 사용. 월 1,000건 무료, 이후 건당 과금
- **Cache Policy / Origin Request Policy** — 캐시 키에 포함할 헤더·쿠키·쿼리 문자열을 관리형 또는 사용자 지정으로 설정합니다. 두 정책은 분리되어 독립 관리됩니다

### CloudFront 보안 통합

- **AWS WAF** — SQL 인젝션·XSS 등 웹 공격 차단, 규칙 기반 필터링, 관리형 규칙 그룹
- **AWS Shield Standard** — 모든 배포에 기본 적용되는 L3/L4 DDoS 방어 (무료). Advanced는 L7 방어 + DRT 지원
- **Field-Level Encryption** — 특정 폼 필드를 공개 키로 암호화
- **TLS/SSL** — ACM 통합 인증서, 최소 TLS 1.2 권장, HTTP→HTTPS 리다이렉트, SNI 지원

---

## 2. Route 53 — 지능형 DNS

Amazon Route 53은 고가용성·확장 가능한 클라우드 DNS입니다. 이름의 **53**은 DNS 포트 번호에서 왔습니다. 이름 해석, 도메인 등록, 7가지 라우팅 정책, 상태 체크를 모두 제공하며 SLA 100% 가용성을 보장합니다.

### TTL (Time to Live)

DNS 레코드가 클라이언트 캐시에 머무는 시간(초)입니다. 기본값 300초(5분).

| TTL | 효과 |
|-----|------|
| 높은 TTL (3600s+) | 쿼리 감소 → 비용 절감, 단 변경 전파 지연 |
| 낮은 TTL (60s 이하) | 변경 신속 전파, 단 쿼리 증가 → 비용 상승 |
| Alias 레코드 | TTL 설정 불가 (AWS 자동 관리) |

> 장애조치 구성은 TTL을 60초 이하로, 안정적인 서비스는 3600초 이상도 권장합니다.

### 7가지 라우팅 정책 (2026)

| 정책 | 동작 | 대표 사용 사례 |
|------|------|---------------|
| **Simple** | 단일 리소스로 라우팅 (여러 값 시 무작위) | 기본 웹사이트 |
| **Weighted** | 가중치 비율로 분산 | 블루/그린, A/B 테스트 |
| **Latency-based** | 지연 시간이 가장 낮은 리전으로 라우팅 | 글로벌 서비스 지연 최소화 |
| **Failover** | Primary 비정상 시 Secondary 자동 전환 | 재해 복구(DR) |
| **Geolocation** | 실제 위치(국가/대륙) 기준 라우팅 | 콘텐츠 현지화, 규제 준수 |
| **Multi-value Answer** | 정상 엔드포인트만 무작위 다중 반환 | DNS 기반 간이 로드밸런싱 |
| **IP-based (NEW)** | 클라이언트 CIDR 블록 기준 라우팅 | ISP·사내망 전용 엔드포인트 |

```
[Failover 라우팅]
  상태 체크 OK  → Primary (us-east-1)
  상태 체크 실패 → Secondary (ap-northeast-2) 자동 전환

[Weighted 라우팅]
  레코드 A: weight 70 → 70% 트래픽
  레코드 B: weight 30 → 30% 트래픽

[IP-based 라우팅]
  203.0.113.0/24   → 전용 엔드포인트 A
  198.51.100.0/24  → 전용 엔드포인트 B
  기타             → 기본 엔드포인트
```

> **참고**: Geo-proximity(Bias 기반 트래픽 편향)는 Traffic Flow에서만 설정 가능하며, 위 7종과 별개의 고급 정책입니다.

### Alias vs CNAME

AWS 리소스를 가리킬 때는 **항상 Alias 레코드**를 쓰세요.

| 항목 | Alias | CNAME |
|------|-------|-------|
| 대상 | AWS 리소스 (ELB, CloudFront, S3) | 임의 도메인 이름 |
| 루트 도메인(Zone Apex) | 가능 (`example.com`) | ❌ 불가 |
| TTL | AWS 자동 관리 | 직접 설정 |
| 쿼리 비용 | **무료** | 과금 |
| IP 자동 갱신 | ✅ (리소스 IP 변경 시) | 수동 |

### 상태 체크 (Health Check)

엔드포인트 가용성을 자동 모니터링하여 장애조치 라우팅과 결합합니다. 전 세계 15개 이상 리전의 에이전트가 30초(무료)/10초(유료) 간격으로 평가합니다.

- **TCP** — 포트 연결 성공 시 정상
- **HTTP/HTTPS** — 2xx·3xx 응답 시 정상
- **String Matching** — 응답 본문에 지정 문자열 포함 여부
- **Calculated** — 여러 상태 체크를 AND/OR 조합
- **CloudWatch Alarm 기반** — 경보 상태를 상태 체크로 사용

기본 임계값은 연속 3회 실패 시 비정상, 연속 3회 성공 시 정상 복구입니다.

### Route 53 Resolver

VPC 내부 DNS 해석을 담당하며, 하이브리드 환경에서 양방향 해석을 제공합니다.

```
[인바운드]  온프레미스 DNS → Resolver Inbound  → VPC 프라이빗 호스팅 영역
[아웃바운드] VPC 인스턴스    → Resolver Outbound → 온프레미스 DNS 서버
```

모든 DNS 쿼리를 CloudWatch Logs·S3·Kinesis로 로깅할 수 있어 보안 감사와 분석에 활용합니다. **Resolver Rules 기반 라우팅**으로 온프레미스-클라우드 간 분할 호라이즌(split-horizon) DNS도 구성합니다.

<details>
<summary>분할 호라이즌 DNS (Split-Horizon) — 전체 보기</summary>

```
동일한 도메인: api.example.com

[Public Hosted Zone]            [Private Hosted Zone]
→ 인터넷 사용자                 → VPC 내부 리소스
→ ALB 공개 엔드포인트           → 내부 NLB 프라이빗 IP
```

</details>

---

## 3. Global Accelerator — Anycast 경로 최적화

AWS Global Accelerator는 사용자 트래픽을 **AWS 글로벌 백본 네트워크**를 통해 최적 엔드포인트로 라우팅합니다. 인터넷 공용망을 최소화하고 프라이빗 관리망을 사용해 지연·패킷 손실·경로 불안정을 줄입니다.

### 핵심 아키텍처

```
사용자 (전 세계)
    ↓ (인터넷 — 최소 구간)
Edge Location (최근접)
    ↓ (AWS 글로벌 백본 — 프라이빗 고속망)
대상 리전
    ↓
엔드포인트 (ALB / NLB / EC2 / Elastic IP)
```

### Anycast 고정 IP 2개

Global Accelerator를 생성하면 **고정 Anycast IPv4 주소 2개**(IPv6 듀얼스택 가능)가 할당됩니다. 전 세계 어디서나 동일 IP로 접속하지만, 각 사용자는 BGP 최단 경로의 가장 가까운 엣지로 라우팅됩니다.

```
사용자 A (서울) ──→ Anycast IP ──→ 서울 Edge
사용자 B (런던) ──→ Anycast IP ──→ 런던 Edge
사용자 C (도쿄) ──→ Anycast IP ──→ 도쿄 Edge

※ 동일 IP지만 각각 가장 가까운 Edge로 라우팅
```

고정 IP이므로 방화벽 화이트리스트·파트너 시스템 연동에 안정적으로 사용할 수 있습니다. 특정 엣지 장애 시 BGP가 자동으로 다른 엣지로 라우팅됩니다.

### 엔드포인트와 리스너

| 엔드포인트 | 특징 |
|-----------|------|
| ALB | L7, HTTP/HTTPS, 패스 기반 라우팅 |
| NLB | L4, TCP/UDP, 초고성능 |
| EC2 인스턴스 | 직접 연결, ALB/NLB 불필요 |
| Elastic IP | 온프레미스·기타 엔드포인트 간접 지원 |

> 엔드포인트는 반드시 **AWS 리전 내**에 있어야 합니다. 온프레미스는 Elastic IP로만 간접 지원됩니다.

리스너는 **TCP·UDP·TCP+UDP(QUIC/HTTP/3)** 를 지원합니다. **클라이언트 원래 IP를 보존**하므로 엔드포인트에서 실제 클라이언트 IP를 확인할 수 있어 로깅·보안 정책에 유용합니다.

### 엔드포인트 그룹과 Traffic Dial

하나의 리전에 있는 엔드포인트 집합입니다. **Traffic Dial**(0~100%)로 리전 간 트래픽 비율을 조절합니다.

```
리스너 (TCP:443)
├── 엔드포인트 그룹 A (서울, Traffic Dial: 80%)
│   ├── ALB-1 (가중치 50%)
│   └── ALB-2 (가중치 50%)
└── 엔드포인트 그룹 B (도쿄, Traffic Dial: 20%)
    └── NLB-1 (가중치 100%)
```

상태 체크는 기본 30초 간격·TCP·연속 3회 실패 시 비정상입니다.

### BYOIP (Bring Your Own IP)

자체 보유 공인 IP 대역(/24 이상, RIR 등록)을 AWS로 가져와 Anycast IP로 사용합니다. ROA 생성 → AWS 프로비저닝 → 소유권 증명(TXT 레코드) → 검증 완료 순서로 진행합니다. IP 기반 화이트리스트 연동, 기존 IP 유지 마이그레이션, 규제용 고정 IP 대역에 사용합니다.

### Shield 통합

Global Accelerator에는 **AWS Shield Standard**가 기본 통합되어 L3/L4 DDoS를 자동·무료 방어합니다. Anycast IP로 트래픽이 전역 엣지에 분산되어 대규모 공격을 흡수합니다. Advanced 활성화 시 L7 방어·WAF 통합·DRT 지원·비용 환불이 추가됩니다.

### DNS 무관 즉각 장애조치

```
[정상]                                [장애 발생]
├── 그룹 A (서울, Dial 100%)          ├── 그룹 A → ALB-A 상태 체크 실패
└── 그룹 B (도쿄, Dial 0%) ← 대기     └── 자동으로 그룹 B(도쿄)로 전환
                                        (DNS 변경 없이, 클라이언트 영향 없음)
```

> **핵심 차이**: Route 53 장애조치는 DNS TTL만큼 지연되지만, Global Accelerator는 고정 IP가 변경되지 않아 **즉각적**으로 전환됩니다.

---

## 4. CloudFront vs Global Accelerator — 선택 기준

두 서비스 모두 엣지를 사용하지만 목적이 다릅니다. CloudFront는 **캐싱**이 핵심이고, Global Accelerator는 **경로 최적화**가 핵심입니다.

| 항목 | CloudFront | Global Accelerator |
|------|-----------|-------------------|
| 주 목적 | 콘텐츠 캐싱(CDN) | 네트워크 경로 최적화 |
| 프로토콜 | HTTP, HTTPS, WebSocket | TCP, UDP (모든 포트) |
| 캐싱 | ✅ 엣지에서 캐싱 | ❌ 캐싱 없음 (투명 전달) |
| 진입점 | 도메인 기반 (CNAME) | 고정 IP 2개 (Anycast) |
| 비 HTTP 트래픽 | 제한적 | 완전 지원 (게임, IoT) |
| 고정 IP | ❌ 없음 (동적 엣지 IP) | ✅ 2개 Anycast IP |
| 장애조치 속도 | DNS/TTL 의존 | 즉각 (DNS 무관) |
| DDoS 보호 | Shield Standard | Shield Standard |

### 의사결정 흐름

```
콘텐츠 캐싱이 필요한가?
├── YES ─▶ CloudFront
│           (정적 자산, API 응답 캐싱, SPA 배포)
└── NO
    └── 비HTTP·실시간·고정 IP가 필요한가?
        ├── YES ─▶ Global Accelerator
        │           (게임 UDP, IoT, 파트너 화이트리스트)
        └── NO ─▶ Route 53 라우팅 정책
                    (장애조치, 지연 기반, 가중치 분산)
```

### 함께 쓰는 패턴

세 서비스는 **배타적이지 않습니다**. 대표적인 조합:

- **Route 53 + CloudFront** — Route 53 Latency/Failover로 CloudFront 배포를 리전별 분산
- **CloudFront + Global Accelerator** — 고정 IP 진입 + 캐싱이 모두 필요한 엔터프라이즈 시나리오
- **Route 53 + Global Accelerator** — Route 53은 Apex 도메인, GA는 고정 IP + 즉각 장애조치

```
              Route 53 (DNS · 라우팅 정책)
                     │
        ┌────────────┴────────────┐
   CloudFront (캐싱)        Global Accelerator (고정 IP)
        │                          │
       ALB                       NLB/EC2
```

---

## 엣지 서비스 선택 체크리스트

| # | 질문 | YES → 추천 서비스 |
|---|------|------------------|
| 1 | 정적 자산·API 응답을 캐싱해야 하는가? | CloudFront |
| 2 | SPA를 글로벌 배포해야 하는가? | CloudFront (S3 + OAC) |
| 3 | 프리미엄 콘텐츠 인증이 필요한가? | CloudFront (Signed URL/Cookies) |
| 4 | 장애조치·지연 분산 라우팅이 필요한가? | Route 53 (Failover/Latency) |
| 5 | 특정 국가만 허용/차단해야 하는가? | Route 53 (Geolocation) |
| 6 | 고정 IP 2개가 필요한가? | Global Accelerator |
| 7 | UDP·게임·IoT 트래픽을 가속해야 하는가? | Global Accelerator |
| 8 | TTL 지연 없는 즉각 장애조치가 필요한가? | Global Accelerator |
| 9 | BYOIP로 자체 IP 대역을 써야 하는가? | Global Accelerator |
| 10 | 파트너 사내망 CIDR 전용 엔드포인트? | Route 53 (IP-based) |

---

## 마치며

엣지 서비스 하면 CDN 하나만 떠올렸는데, CloudFront·Route 53·Global Accelerator가 각각 캐싱, DNS 라우팅 제어, Anycast 백본 가속이라는 서로 다른 문제를 해결한다는 걸 이해하고 나서 혼란이 사라졌습니다. 세 서비스의 핵심 메커니즘을 구분하니, 어떤 상황에 무엇을 써야 하는지가 명확해졌습니다.

2026년의 기본값들이 바뀌었다는 점도 놀라웠습니다. CloudFront는 OAI 대신 OAC를 쓰고, Route 53은 CNAME 대신 무료이면서 자동 갱신되는 Alias를 사용하며, 두 서비스 모두 Shield Standard가 기본 탑재되어 DDoS를 자동 방어합니다. 보안과 성능이 기본값으로 녹아들어 있다는 것은 클라우드가 성숙해진 증거입니다.

결국 세 서비스를 계층화해서 조합할 때 지연·가용성·보안을 동시에 잡을 수 있다는 통찰이 가장 중요한 깨달음이었습니다. 앞으로 Route 53로 DNS·라우팅 뇌를, CloudFront로 캐싱을, Global Accelerator로 고정 IP와 비HTTP 가속을 맡기는 글로벌 아키텍처를 직접 설계해 보고 싶습니다.

---

> **AWS 시리즈 6/16**
>
> | | |
> |---|---|
> | ← [로드밸런싱 & 오토스케일링 — ELB와 Auto Scaling Groups]({% post_url 2026-05-26-AWS-ELB-AutoScaling %}) | |
> | | [데이터베이스 & 캐시 — RDS, Aurora, ElastiCache]({% post_url 2026-05-28-AWS-Database-Cache %}) → |
